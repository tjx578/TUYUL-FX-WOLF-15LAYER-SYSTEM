"""Event-driven analysis loop and per-pair pipeline executor.

Zone: analysis orchestration — runs the 15-layer pipeline on market events.

Triggers immediately on CANDLE_CLOSED events from CandleBuilder,
with a configurable fallback interval so analysis still runs
periodically even if no candles close.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from loguru import logger

from analysis.latency_tracker import LatencyTracker
from analysis.reflex_rqi import compute_rqi
from config_loader import CONFIG
from core.event_bus import Event, EventType, get_event_bus
from infrastructure.tracing import setup_tracer
from journal.builders import build_j1, build_j2
from pipeline import WolfConstitutionalPipeline

__all__ = ["analysis_loop"]

_PIPELINE_TIMEOUT_SEC = 30.0
_engine_tracer = setup_tracer("wolf-engine-loop")
_ERROR_LOG_WINDOW_SEC = float(os.getenv("PIPELINE_ERROR_LOG_WINDOW_SEC", "30"))
_error_log_state: dict[str, dict[str, float | int]] = {}


def _log_pipeline_exception(pair: str, exc: BaseException, *, kind: str) -> None:
    """Rate-limit repeated pipeline exceptions to prevent log floods."""
    now = time.time()
    signature = f"{kind}:{type(exc).__name__}:{exc}"
    state = _error_log_state.get(signature)

    # Emit full traceback at most once per window for each unique signature.
    if state is None or (now - float(state["last_emit"])) >= _ERROR_LOG_WINDOW_SEC:
        suppressed = int(state["suppressed"]) if state else 0
        if suppressed > 0:
            logger.warning(
                "[Pipeline] {} repeating signature={} (suppressed={} over {}s)",
                kind,
                signature,
                suppressed,
                int(_ERROR_LOG_WINDOW_SEC),
            )
        logger.exception("[Pipeline] {} for {}: {}", kind, pair, exc)
        _error_log_state[signature] = {"last_emit": now, "suppressed": 0}
        return

    state["suppressed"] = int(state["suppressed"]) + 1


async def _analyze_pair(
    pair: str,
    pipeline: WolfConstitutionalPipeline,
) -> dict[str, Any] | None:
    """Run pipeline for a single pair with timeout + thread offload."""
    _lt = LatencyTracker()
    with _engine_tracer.start_as_current_span("pipeline_full") as span:
        span.set_attribute("pair", pair)
        span.set_attribute("pipeline.timeout_sec", _PIPELINE_TIMEOUT_SEC)
        try:
            from context.live_context_bus import LiveContextBus  # noqa: PLC0415

            _bus = LiveContextBus()
            _latest: dict[str, Any] | None = _bus.get_latest_tick(pair)
            _tick_ts: float | None = (
                float(_latest.get("local_ts") or _latest.get("timestamp") or 0.0) if _latest else None
            )
            if _tick_ts:
                span.set_attribute("tick.timestamp", _tick_ts)

            _lt.record_analysis_start(pair)
            result = await asyncio.wait_for(
                asyncio.to_thread(lambda: pipeline.execute(pair, None, tick_ts=_tick_ts)),
                timeout=_PIPELINE_TIMEOUT_SEC,
            )

            if result:
                _lt.record_verdict_emit(pair)
                synthesis: dict[str, Any] = dict(result.get("synthesis") or {})
                l12: dict[str, Any] = dict(result.get("l12") or {})
                span.set_attribute("l12.verdict", str(l12.get("verdict", "")))
                span.set_attribute("l12.confidence", str(l12.get("confidence", "")))
                try:
                    j1 = build_j1(pair, synthesis)
                    logger.debug(f"[J1] Context journal created for {pair}: {j1.market_regime}")
                except Exception as j1_exc:
                    logger.warning(f"[J1] Failed to build context journal for {pair}: {j1_exc}")
                if l12:
                    try:
                        j2 = build_j2(pair, synthesis, l12)
                        logger.debug(f"[J2] Decision journal created for {pair}: verdict={j2.verdict}")
                    except Exception as j2_exc:
                        logger.warning(f"[J2] Failed to build decision journal for {pair}: {j2_exc}")

            return result
        except TimeoutError as exc:
            span.record_exception(exc)
            _log_pipeline_exception(pair, exc, kind="TIMEOUT")
            return None
        except Exception as exc:
            span.record_exception(exc)
            _log_pipeline_exception(pair, exc, kind="ERROR")
            return None


async def analysis_loop(
    pairs: list[str],
    pipeline: WolfConstitutionalPipeline,
    shutdown_event: asyncio.Event | None = None,
    on_first_cycle: asyncio.Event | None = None,
) -> None:
    """Event-driven analysis loop.

    Args:
        pairs: List of trading pair symbols.
        pipeline: The constitutional pipeline instance.
        shutdown_event: Set to trigger graceful shutdown.
        on_first_cycle: Set after the first successful analysis cycle (readiness).
    """
    env_interval = os.getenv("ANALYSIS_LOOP_INTERVAL_SEC")
    loop_interval = int(env_interval) if env_interval else CONFIG["settings"].get("loop_interval_sec", 60)
    rqi_sigma_sec = float(os.getenv("ANALYSIS_RQI_SIGMA_SEC", str(max(1, loop_interval))))
    rqi_retrigger_threshold = max(
        0.0,
        min(1.0, float(os.getenv("ANALYSIS_RQI_RETRIGGER_THRESHOLD", "0.72"))),
    )
    rqi_force_stale_sec = float(os.getenv("ANALYSIS_RQI_FORCE_STALE_SEC", str(max(1, loop_interval * 3))))
    logger.info(f"Analysis loop started (event-driven, fallback interval={loop_interval}s)")

    _candle_signal = asyncio.Event()
    _pending_symbols: set[str] = set()
    _candle_latency_tracker = LatencyTracker()

    def _on_candle_closed(event: Event) -> None:
        data: dict[str, object] = dict(event.data)
        symbol = data.get("symbol")
        if isinstance(symbol, str) and symbol:
            _pending_symbols.add(symbol)
            _candle_latency_tracker.record_candle_complete(symbol)
        _candle_signal.set()

    bus = get_event_bus()
    bus.subscribe(EventType.CANDLE_CLOSED, _on_candle_closed)

    _symbol_reflex_inputs: dict[str, tuple[float, float]] = {}
    _symbol_last_analysis_ts: dict[str, float] = {}

    def _to_float(value: object, default: float = 0.0) -> float:
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return default
        return default

    _first_cycle_done = False

    while True:
        if shutdown_event and shutdown_event.is_set():
            logger.info("Analysis loop shutting down...")
            break

        try:  # noqa: SIM105
            await asyncio.wait_for(_candle_signal.wait(), timeout=loop_interval)
        except TimeoutError:
            pass

        _candle_signal.clear()

        symbols_to_run: list[str] = []
        if _pending_symbols:
            symbols_to_run = [s for s in pairs if s in _pending_symbols]
            _pending_symbols.clear()
            if not symbols_to_run:
                symbols_to_run = list(pairs)
            logger.info(f"[EVENT] Candle close triggered analysis for {symbols_to_run}")
        else:
            if not _symbol_last_analysis_ts:
                symbols_to_run = list(pairs)
                logger.debug("[TIMER] Fallback sweep (cold-start) - analysing all pairs")
            else:
                now_ts = time.time()
                symbols_to_run = list[str]()
                for pair in pairs:
                    last_ts = _symbol_last_analysis_ts.get(pair)
                    if last_ts is None:
                        symbols_to_run.append(pair)
                        continue

                    age_sec = max(0.0, now_ts - last_ts)
                    if age_sec >= rqi_force_stale_sec:
                        symbols_to_run.append(pair)
                        continue

                    coherence, emotion_delta = _symbol_reflex_inputs.get(pair, (1.0, 0.0))
                    projected_rqi = compute_rqi(
                        delta_t_sec=age_sec,
                        coherence=coherence,
                        emotion_delta=emotion_delta,
                        sigma_sec=rqi_sigma_sec,
                    )
                    if projected_rqi <= rqi_retrigger_threshold:
                        symbols_to_run.append(pair)

                logger.debug(
                    "[TIMER] Selective fallback - analysing %d/%d pair(s), threshold=%.2f",
                    len(symbols_to_run),
                    len(pairs),
                    rqi_retrigger_threshold,
                )

                if not symbols_to_run:
                    continue

        results = await asyncio.gather(
            *(_analyze_pair(pair, pipeline) for pair in symbols_to_run),
            return_exceptions=True,
        )
        for pair, result in zip(symbols_to_run, results, strict=False):
            if isinstance(result, Exception):
                logger.error(f"[ERROR] {pair} | {result}")
                continue

            _symbol_last_analysis_ts[pair] = time.time()
            if isinstance(result, dict):
                synthesis: dict[str, Any] = dict(result.get("synthesis") or {})
                layers: dict[str, Any] = dict(synthesis.get("layers") or {})
                discipline: dict[str, Any] = dict(synthesis.get("wolf_discipline") or {})

                coherence = _to_float(layers.get("L2_reflex_coherence"), 0.0)
                emotion_delta = _to_float(discipline.get("polarity_deviation"), 0.0)
                _symbol_reflex_inputs[pair] = (coherence, emotion_delta)

        if not _first_cycle_done:
            _first_cycle_done = True
            if on_first_cycle:
                on_first_cycle.set()
            logger.info("Engine readiness: READY (first analysis cycle complete)")
