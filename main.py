import asyncio
import os
import signal
import sys

from loguru import logger  # pyright: ignore[reportMissingImports]
from redis.asyncio import Redis as AsyncRedis  # pyright: ignore[reportMissingImports]

from config_loader import CONFIG
from pipeline import WolfConstitutionalPipeline
from context.runtime_state import RuntimeState
from ingest.candle_builder import CandleBuilder
from ingest.dependencies import create_finnhub_ws
from ingest.finnhub_market_news import FinnhubMarketNews
from ingest.finnhub_news import FinnhubNews
from journal.journal_router import journal_router
from journal.journal_schema import ContextJournal, DecisionJournal, VerdictType
from storage.l12_cache import set_verdict
from storage.snapshot_store import save_snapshot
from utils.timezone_utils import is_trading_session, now_utc

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
        while not (_shutdown_event and _shutdown_event.is_set()):
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
        from context.redis_consumer import RedisConsumer

        redis_consumer = RedisConsumer(symbols=PAIRS)
        logger.info("Starting RedisConsumer...")
        await redis_consumer.start()
    except Exception as exc:
        logger.error(f"Failed to start RedisConsumer: {exc}. Continuing without Redis consumer.")
        while not (_shutdown_event and _shutdown_event.is_set()):
            await asyncio.sleep(1)


async def _analyze_pair(pair: str) -> None:
    # Execute pipeline
    result = _pipeline.execute(pair)

    synthesis = result["synthesis"]
    l12 = result["l12_verdict"]

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
    """Main analysis loop with per-pair parallel execution."""
    env_interval = os.getenv("ANALYSIS_LOOP_INTERVAL_SEC")
    loop_interval = int(env_interval) if env_interval else CONFIG["settings"].get("loop_interval_sec", 60)
    logger.info(f"Analysis loop started (interval={loop_interval}s)")

    while True:
        if _shutdown_event and _shutdown_event.is_set():
            logger.info("Analysis loop shutting down...")
            break

        results = await asyncio.gather(*(_analyze_pair(pair) for pair in PAIRS), return_exceptions=True)
        for pair, result in zip(PAIRS, results, strict=False):
            if isinstance(result, Exception):
                logger.error(f"[ERROR] {pair} | {result}")

        await asyncio.sleep(loop_interval)


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
