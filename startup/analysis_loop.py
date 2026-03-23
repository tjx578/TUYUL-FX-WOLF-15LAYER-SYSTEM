"""Event-driven analysis loop and per-pair pipeline executor.

Zone: analysis orchestration — runs the 15-layer pipeline on market events.

Triggers immediately on CANDLE_CLOSED events from CandleBuilder,
with a configurable fallback interval so analysis still runs
periodically even if no candles close.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from typing import Any
from uuid import uuid4

from loguru import logger

from analysis.latency_tracker import LatencyTracker
from analysis.reflex_rqi import compute_rqi
from config_loader import CONFIG
from core.event_bus import Event, EventType, get_event_bus
from core.metrics import (
    ENGINE_HEARTBEAT_AGE_SECONDS,
    ENGINE_HEARTBEAT_READY,
    INGEST_HEARTBEAT_AGE_SECONDS,
    INGEST_HEARTBEAT_READY,
    VERDICT_PATH_EVENT_TOTAL,
)
from infrastructure.tracing import setup_tracer
from journal.builders import build_j1, build_j2
from pipeline import WolfConstitutionalPipeline
from state.heartbeat_classifier import (
    HeartbeatState,
    IngestHealthState,
    classify_heartbeat,
    classify_ingest_health,
)
from state.redis_keys import (
    HEARTBEAT_ENGINE,
    HEARTBEAT_INGEST,
    HEARTBEAT_INGEST_PROCESS,
    HEARTBEAT_INGEST_PROVIDER,
)
from storage.l12_cache import set_verdict

__all__ = ["analysis_loop"]

# Hard deadline for a single pipeline execution.  Prevents indefinite hangs
# (e.g.  CPU-bound computation or Redis latency spike) from blocking the
# entire analysis loop.  Override via ``PIPELINE_TIMEOUT_SEC`` env var.
_PIPELINE_TIMEOUT_SEC = float(os.getenv("PIPELINE_TIMEOUT_SEC", "30"))
_ENGINE_HEARTBEAT_INTERVAL_SEC = float(os.getenv("ENGINE_HEARTBEAT_INTERVAL_SEC", "10"))
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


def _build_degraded_verdict(pair: str, reason: str) -> dict[str, Any]:
    """Build a minimal HOLD/DEGRADED payload so the dashboard always has data."""
    return {
        "symbol": pair,
        "signal_id": f"DEG-{pair}-{uuid4().hex[:8].upper()}",
        "verdict": "HOLD",
        "confidence": 0.0,
        "wolf_status": "DEGRADED",
        "direction": "HOLD",
        "scores": {},
        "gates": {"passed": 0, "total": 9},
        "layers": {},
        "execution": {},
        "system": {"latency_ms": 0.0, "degraded": True, "degraded_reason": reason},
        "timestamp": time.time(),
        "errors": [reason],
        "last_hold_block_reason": reason,
    }


def _extract_last_hold_block_reason(result: dict[str, Any]) -> str | None:
    governance = result.get("governance")
    if isinstance(governance, dict):
        action = str(governance.get("action") or "").upper()
        reasons_raw = governance.get("reasons")
        reasons = [str(r) for r in reasons_raw] if isinstance(reasons_raw, list) else []
        if action in {"HOLD", "BLOCK"}:
            return f"{action}:{','.join(reasons) if reasons else 'governance'}"

    errors_raw = result.get("errors")
    errors = [str(e) for e in errors_raw] if isinstance(errors_raw, list) else []
    for prefix in ("GOVERNANCE_BLOCK:", "GOVERNANCE_HOLD:", "WARMUP_INSUFFICIENT:"):
        matched = next((e for e in errors if e.startswith(prefix)), None)
        if matched:
            return matched
    return None


def _build_verdict_cache_payload(pair: str, result: dict[str, Any]) -> dict[str, Any]:
    synthesis = dict(result.get("synthesis") or {})
    l12 = dict(result.get("l12_verdict") or {})
    execution_map = dict(result.get("execution_map") or {})
    governance = dict(result.get("governance") or {})

    confidence_raw = l12.get("confidence", 0.0)
    if isinstance(confidence_raw, str):
        conf_map = {"LOW": 0.25, "MEDIUM": 0.50, "HIGH": 0.75, "VERY_HIGH": 0.95}
        confidence = float(conf_map.get(confidence_raw.upper(), 0.0))
    else:
        confidence = float(confidence_raw or 0.0)

    execution = dict(synthesis.get("execution") or {})
    scores = dict(synthesis.get("scores") or {})
    layers = dict(synthesis.get("layers") or {})
    system = dict(synthesis.get("system") or {})

    timestamp = time.time()
    hold_block_reason = _extract_last_hold_block_reason(result)

    payload: dict[str, Any] = {
        "symbol": pair,
        "signal_id": str(l12.get("signal_id") or f"SIG-{pair}-{uuid4().hex[:12].upper()}"),
        "verdict": str(l12.get("verdict") or "HOLD"),
        "confidence": confidence,
        "wolf_status": str(l12.get("wolf_status") or "NO_HUNT"),
        "direction": execution.get("direction") or l12.get("direction") or "HOLD",
        "scores": scores,
        "gates": dict(l12.get("gates") or {}),
        "layers": layers,
        "execution": execution,
        "system": {
            **system,
            "latency_ms": float(result.get("latency_ms") or system.get("latency_ms") or 0.0),
        },
        "timestamp": timestamp,
        "entry_price": execution.get("entry_price"),
        "stop_loss": execution.get("stop_loss"),
        "take_profit_1": execution.get("take_profit_1"),
        "risk_reward_ratio": execution.get("rr_ratio"),
        "execution_map": execution_map,
        "governance": governance,
        "errors": list(result.get("errors") or []),
        "last_hold_block_reason": hold_block_reason,
    }

    gates_v74 = l12.get("gates_v74")
    if isinstance(gates_v74, dict):
        payload["gates"] = {
            **payload["gates"],
            **dict(gates_v74),
        }

    return payload


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
                # ABORT: pipeline explicitly set result["verdict"] = None to signal
                # that no analysis was performed (e.g., warmup rejection).
                # Never persist a verdict in this case — it would pollute Redis with
                # stale/empty payloads while candle history is still warming up.
                if "verdict" in result and result["verdict"] is None:
                    logger.debug(
                        "[VerdictPath] Pipeline ABORTED for {} — skipping verdict persist (will retry next cycle)",
                        pair,
                    )
                    return None  # pair will be re-scheduled next cycle

                try:
                    verdict_payload = _build_verdict_cache_payload(pair, result)
                    set_verdict(pair, verdict_payload)
                except Exception as persist_exc:
                    VERDICT_PATH_EVENT_TOTAL.labels(event="verdict_persisted", symbol=pair, status="error").inc()
                    logger.warning("[VerdictPath] persist failed | pair={} error={}", pair, persist_exc)
                    # Fallback: write a degraded verdict so the dashboard is never empty
                    try:
                        set_verdict(pair, _build_degraded_verdict(pair, f"PERSIST_ERROR:{type(persist_exc).__name__}"))
                    except Exception:
                        logger.warning("[VerdictPath] degraded fallback also failed | pair={}", pair)

                _lt.record_verdict_emit(pair)
                synthesis: dict[str, Any] = dict(result.get("synthesis") or {})
                l12: dict[str, Any] = dict(result.get("l12_verdict") or {})
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
            try:
                set_verdict(pair, _build_degraded_verdict(pair, f"PIPELINE_TIMEOUT:{_PIPELINE_TIMEOUT_SEC}s"))
            except Exception:
                logger.warning("[VerdictPath] degraded persist failed | pair={}", pair)
            return None
        except Exception as exc:
            span.record_exception(exc)
            _log_pipeline_exception(pair, exc, kind="ERROR")
            try:
                set_verdict(pair, _build_degraded_verdict(pair, f"PIPELINE_ERROR:{type(exc).__name__}"))
            except Exception:
                logger.warning("[VerdictPath] degraded persist failed | pair={}", pair)
            return None


_INGEST_HEARTBEAT_MAX_AGE_SEC = float(os.getenv("HEARTBEAT_INGEST_MAX_AGE_SEC", "30"))
_INGEST_HEARTBEAT_LOG_INTERVAL_SEC = 60.0  # rate-limit repeated warnings
_last_ingest_heartbeat_log_ts: float = 0.0


def _check_ingest_heartbeat(redis_client: Any) -> None:
    """Read the split ingest heartbeat keys and update metrics/logging.

    Uses the sync Redis client already available in the engine heartbeat loop.
    Reads both process and provider keys to distinguish weekend-idle from dead.
    """
    global _last_ingest_heartbeat_log_ts  # noqa: PLW0603

    # Try split keys first; fall back to legacy combined key
    try:
        raw_process = redis_client.get(HEARTBEAT_INGEST_PROCESS)
        raw_provider = redis_client.get(HEARTBEAT_INGEST_PROVIDER)
    except Exception as exc:
        logger.debug("[EngineHeartbeat] Failed to read ingest heartbeat: {}", exc)
        INGEST_HEARTBEAT_READY.set(0.0)
        return

    process_status = classify_heartbeat(raw_process, _INGEST_HEARTBEAT_MAX_AGE_SEC, service="ingest_process")
    provider_status = classify_heartbeat(raw_provider, _INGEST_HEARTBEAT_MAX_AGE_SEC, service="ingest_provider")

    # If split keys not yet populated, fall back to legacy combined key
    if process_status.state == HeartbeatState.MISSING and provider_status.state == HeartbeatState.MISSING:
        try:
            raw_legacy = redis_client.get(HEARTBEAT_INGEST)
        except Exception:
            raw_legacy = None
        legacy = classify_heartbeat(raw_legacy, _INGEST_HEARTBEAT_MAX_AGE_SEC, service="ingest")
        if legacy.age_seconds is not None:
            INGEST_HEARTBEAT_AGE_SECONDS.set(legacy.age_seconds)
        INGEST_HEARTBEAT_READY.set(1.0 if legacy.state == HeartbeatState.ALIVE else 0.0)
        return

    health = classify_ingest_health(process_status, provider_status)

    # Use provider age for metrics when available, otherwise process age
    display_age = provider_status.age_seconds if provider_status.age_seconds is not None else process_status.age_seconds
    if display_age is not None:
        INGEST_HEARTBEAT_AGE_SECONDS.set(display_age)

    # HEALTHY or DEGRADED both mean the process is alive
    INGEST_HEARTBEAT_READY.set(1.0 if health.state != IngestHealthState.NO_PRODUCER else 0.0)

    now = time.time()
    if health.state != IngestHealthState.HEALTHY:  # noqa: SIM102
        if (now - _last_ingest_heartbeat_log_ts) >= _INGEST_HEARTBEAT_LOG_INTERVAL_SEC:
            _last_ingest_heartbeat_log_ts = now
            logger.warning(
                "[EngineHeartbeat] Ingest health {} | process={} provider={}",
                health.state.value,
                process_status.state.value,
                provider_status.state.value,
            )


async def _engine_heartbeat_loop(
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Publish engine heartbeat and consume ingest heartbeat for cross-service health."""
    import orjson  # noqa: PLC0415

    _redis_client = None
    try:
        from storage.redis_client import RedisClient  # noqa: PLC0415

        _redis_client = RedisClient()
    except Exception:
        logger.warning("[EngineHeartbeat] Redis client unavailable — heartbeat disabled")
        return

    while not (shutdown_event and shutdown_event.is_set()):
        try:
            payload = orjson.dumps({"producer": "engine_analysis", "ts": time.time()}).decode("utf-8")
            _redis_client.set(HEARTBEAT_ENGINE, payload)
            ENGINE_HEARTBEAT_AGE_SECONDS.set(0.0)
            ENGINE_HEARTBEAT_READY.set(1.0)
        except Exception as exc:
            logger.debug("[EngineHeartbeat] Failed to write heartbeat: {}", exc)

        # Consume ingest heartbeat — detect no-producer independently of transport
        _check_ingest_heartbeat(_redis_client)

        await asyncio.sleep(_ENGINE_HEARTBEAT_INTERVAL_SEC)


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
    rqi_force_stale_sec = float(os.getenv("ANALYSIS_RQI_FORCE_STALE_SEC", str(max(1, loop_interval * 2))))
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

    # Launch engine heartbeat as a background task so readyz/dashboard
    # can detect whether the analysis loop is alive.
    _heartbeat_task = asyncio.create_task(_engine_heartbeat_loop(shutdown_event))

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
                with contextlib.suppress(Exception):
                    set_verdict(pair, _build_degraded_verdict(pair, f"GATHER_ERROR:{type(result).__name__}"))
                continue

            # Only mark as analyzed when a real result was produced.
            # Failed pairs (result is None) will be retried next cycle.
            if result is None:
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

    # Clean up heartbeat task on shutdown
    _heartbeat_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _heartbeat_task
