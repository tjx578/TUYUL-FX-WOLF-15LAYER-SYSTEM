import asyncio
import os
import signal
import sys

from loguru import logger  # pyright: ignore[reportMissingImports]
from redis.asyncio import Redis as AsyncRedis  # pyright: ignore[reportMissingImports]

from config_loader import CONFIG
from context.runtime_state import RuntimeState
from core.event_bus import Event, EventType, get_event_bus
from ingest.candle_builder import CandleBuilder
from ingest.dependencies import create_finnhub_ws
from ingest.finnhub_market_news import FinnhubMarketNews
from ingest.finnhub_news import FinnhubNews
from journal.journal_router import journal_router
from journal.journal_schema import ContextJournal, DecisionJournal, VerdictType
from pipeline import WolfConstitutionalPipeline
from storage.l12_cache import set_verdict
from storage.snapshot_store import save_snapshot
from storage.startup import init_persistent_storage, shutdown_persistent_storage
from utils.timezone_utils import is_trading_session, now_utc

try:
    from engines.v11 import V11PipelineHook
    _v11_hook: V11PipelineHook | None = V11PipelineHook()
except Exception:  # V11 optional — missing = skip
    _v11_hook = None

PAIRS = [p["symbol"] for p in CONFIG["pairs"]["pairs"] if p.get("enabled", True)]

_shutdown_event: asyncio.Event | None = None
_pipeline = WolfConstitutionalPipeline()


def _build_j1(pair: str, synthesis: dict) -> ContextJournal:
    layers = synthesis.get("layers", {})
    bias = synthesis.get("bias", {})
    session = is_trading_session()
    return ContextJournal(
        timestamp=now_utc(),
        pair=pair,
        session=session,
        market_regime=synthesis.get("market_regime", "UNKNOWN"),
        news_lock=synthesis.get("news_lock", False),
        context_coherence=layers.get("conf12", 0.5),
        mta_alignment=synthesis.get("mta_alignment", True),
        technical_bias=bias.get("technical", "NEUTRAL"),
    )


def _build_j2(pair: str, synthesis: dict, l12: dict) -> DecisionJournal:
    scores = synthesis.get("scores", {})
    layers = synthesis.get("layers", {})
    gates = l12.get("gates", {})
    setup_id = f"{pair}_{now_utc().strftime('%Y%m%d_%H%M%S')}"

    failed_gates = [
        gate_name
        for gate_name, gate_value in gates.items()
        if gate_name not in ["passed", "total"] and gate_value == "FAIL"
    ]

    primary_rejection_reason = None
    if l12["verdict"] in [VerdictType.HOLD.value, VerdictType.NO_TRADE.value]:
        if failed_gates:
            primary_rejection_reason = f"Failed gates: {', '.join(failed_gates)}"
        else:
            primary_rejection_reason = "Constitutional violation"

    try:
        verdict_type = VerdictType(l12["verdict"])
    except ValueError:
        verdict_type = VerdictType.NO_TRADE

    return DecisionJournal(
        timestamp=now_utc(),
        pair=pair,
        setup_id=setup_id,
        wolf_30_score=int(scores.get("wolf_30_point", 0)),
        f_score=int(scores.get("f_score", 0)),
        t_score=int(scores.get("t_score", 0)),
        fta_score=int((scores.get("fta_score") or 0) * 10),
        exec_score=int(scores.get("exec_score", 0)),
        tii_sym=float(layers.get("L8_tii_sym", 0.0)),
        integrity_index=float(layers.get("L8_integrity_index", 0.0)),
        monte_carlo_win=float(layers.get("L7_monte_carlo_win", 0.0)),
        conf12=float(layers.get("conf12", 0.0)),
        verdict=verdict_type,
        confidence=l12.get("confidence", "LOW"),
        wolf_status=l12.get("wolf_status", "NO_HUNT"),
        gates_passed=gates.get("passed", 0),
        gates_total=gates.get("total", 9),
        failed_gates=failed_gates,
        violations=[],
        primary_rejection_reason=primary_rejection_reason,
    )


def _validate_api_key() -> bool:
    api_key = os.getenv("FINNHUB_API_KEY", "")
    if not api_key or api_key == "YOUR_FINNHUB_API_KEY":
        logger.warning("WARNING: FINNHUB_API_KEY not configured; running in DRY RUN mode.")
        return False
    logger.info("FINNHUB_API_KEY validated")
    return True


async def run_ingest_services(has_api_key: bool, redis: AsyncRedis) -> None:
    """Run ingestion tasks concurrently in local mode."""
    if not has_api_key:
        logger.info("Skipping ingest services - no API key configured")
        while not (_shutdown_event and _shutdown_event.is_set()):  # noqa: ASYNC110
            await asyncio.sleep(1)
        return

    ws_feed = await create_finnhub_ws(redis=redis)
    news_feed = FinnhubNews()
    market_news = FinnhubMarketNews()
    candle_builder = CandleBuilder()

    logger.info("Starting ingest services: WebSocket, News, MarketNews, CandleBuilder")
    try:
        await asyncio.gather(
            ws_feed.run(),
            news_feed.run(),
            market_news.run(),
            candle_builder.run(),
        )
    except asyncio.CancelledError:
        logger.info("Ingest services cancelled - shutting down")
        raise
    finally:
        await ws_feed.stop()
        await redis.aclose()
        logger.info("Ingest services cleanup complete")


async def run_redis_consumer() -> None:
    """Run RedisConsumer when CONTEXT_MODE=redis."""
    try:
        from context.redis_consumer import RedisConsumer  # noqa: PLC0415

        redis_consumer = RedisConsumer(symbols=PAIRS)
        logger.info("Starting RedisConsumer...")
        await redis_consumer.start()
    except Exception as exc:
        logger.error(f"Failed to start RedisConsumer: {exc}. Continuing without Redis consumer.")
        while not (_shutdown_event and _shutdown_event.is_set()):  # noqa: ASYNC110
            await asyncio.sleep(1)


async def _analyze_pair(pair: str) -> None:
    # Execute pipeline
    result = _pipeline.execute(pair)

    synthesis = result["synthesis"]
    l12 = result["l12_verdict"]

    # ══ V11 POST-PIPELINE FILTER ══
    if _v11_hook is not None:
        try:
            v11_overlay = _v11_hook.evaluate(result, symbol=pair, timeframe="H1")
            synthesis["v11"] = v11_overlay.to_dict()
            if l12["verdict"].startswith("EXECUTE") and not v11_overlay.should_trade:
                l12["verdict"] = "HOLD"
                l12["confidence"] = "MEDIUM"
                l12["v11_veto"] = True
                logger.info(f"[V11] {pair} — EXECUTE vetoed by V11 sniper filter")
        except Exception as v11_exc:
            logger.warning(f"[V11] {pair} — hook error (skipped): {v11_exc}")

    # Inject runtime latency
    synthesis["system"]["latency_ms"] = RuntimeState.latency_ms

    # Journal (KEEP existing journal logic)
    try:
        journal_router.record_context(_build_j1(pair, synthesis))
    except Exception as journal_exc:
        logger.error(f"J1 journal failed for {pair}: {journal_exc}")

    try:
        journal_router.record_decision(_build_j2(pair, synthesis, l12))
    except Exception as journal_exc:
        logger.error(f"J2 journal failed for {pair}: {journal_exc}")

    # Storage (KEEP existing storage logic)
    set_verdict(pair, l12)
    save_snapshot(pair, l12)
    logger.debug(f"[L12] {pair} -> {l12['verdict']}")


async def analysis_loop() -> None:
    """Event-driven analysis loop.

    Triggers immediately on CANDLE_CLOSED events from CandleBuilder,
    with ``loop_interval`` (default 60 s) as a maximum-wait fallback so
    analysis still runs periodically even if no candles close.

    When a CANDLE_CLOSED event arrives *only* the affected symbol is
    re-analysed, keeping CPU usage proportional to market activity.
    """
    env_interval = os.getenv("ANALYSIS_LOOP_INTERVAL_SEC")
    loop_interval = int(env_interval) if env_interval else CONFIG["settings"].get("loop_interval_sec", 60)
    logger.info(f"Analysis loop started (event-driven, fallback interval={loop_interval}s)")

    # ── asyncio.Event used as a lightweight signal ──────────────────
    _candle_signal = asyncio.Event()
    _pending_symbols: set[str] = set()
    def _on_candle_closed(event: Event) -> None:
        """Non-async callback – just record the symbol and wake the loop."""
        symbol = event.data.get("symbol")
        if symbol:
            _pending_symbols.add(symbol)
        _candle_signal.set()

    bus = get_event_bus()
    bus.subscribe(EventType.CANDLE_CLOSED, _on_candle_closed)
    bus.subscribe(EventType.CANDLE_CLOSED, _on_candle_closed)

    while True:
        if _shutdown_event and _shutdown_event.is_set():
            logger.info("Analysis loop shutting down...")
            break

        # Wait for a candle-close event OR the fallback timeout
        try:
            await asyncio.wait_for(_candle_signal.wait(), timeout=loop_interval)
        except TimeoutError:
            pass  # Fallback: run full sweep on all pairs

        _candle_signal.clear()

        # Decide which pairs to analyse this iteration
        if _pending_symbols:
            # Event-driven: only symbols that just had a candle close
            symbols_to_run = [s for s in PAIRS if s in _pending_symbols]
            _pending_symbols.clear()
            if not symbols_to_run:
                # Symbol from event not in our PAIRS list – full sweep
                symbols_to_run = PAIRS
            logger.info(f"[EVENT] Candle close triggered analysis for {symbols_to_run}")
        else:
            # Timeout fallback: analyse everything
            symbols_to_run = PAIRS
            logger.debug("[TIMER] Fallback sweep - analysing all pairs")

        results = await asyncio.gather(
            *(_analyze_pair(pair) for pair in symbols_to_run),
            return_exceptions=True,
        )
        for pair, result in zip(symbols_to_run, results, strict=False):
            if isinstance(result, Exception):
                logger.error(f"[ERROR] {pair} | {result}")


def _signal_handler(signum: int, frame) -> None:
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    if _shutdown_event:
        _shutdown_event.set()


async def main() -> None:
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    logger.remove()
    logger.add(
        sys.stdout,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
        ),
        level="INFO",
        filter=lambda record: record["level"].no < 40,
    )
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
        ),
        level="ERROR",
    )

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info("=" * 60)
    logger.info("WOLF 15-LAYER TRADING SYSTEM")
    logger.info("=" * 60)

    has_api_key = _validate_api_key()
    context_mode = os.getenv("CONTEXT_MODE", "local").lower()
    logger.info(f"Context mode: {context_mode.upper()}")
    await init_persistent_storage()

    if context_mode == "redis":
        tasks = [
            asyncio.create_task(run_redis_consumer(), name="RedisConsumer"),
            asyncio.create_task(analysis_loop(), name="AnalysisLoop"),
        ]
    else:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        redis_client = AsyncRedis.from_url(redis_url)
        tasks = [
            asyncio.create_task(run_ingest_services(has_api_key, redis_client), name="IngestServices"),
            asyncio.create_task(analysis_loop(), name="AnalysisLoop"),
        ]

    logger.info(f"System initialized. Running {len(tasks)} concurrent tasks.")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Tasks cancelled, shutting down...")
    except Exception as exc:
        logger.error(f"Fatal error: {exc}")
        raise
    finally:
        await shutdown_persistent_storage()
        logger.info("System shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, exiting...")
        sys.exit(0)
    except Exception as exc:
        logger.error(f"Fatal error: {exc}")
        sys.exit(1)
