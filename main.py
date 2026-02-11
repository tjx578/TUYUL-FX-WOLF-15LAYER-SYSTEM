import asyncio
import os
import signal
import sys
from typing import Optional

from loguru import logger

from analysis.synthesis import build_synthesis
from analysis.synthesis_adapter import adapt_synthesis
from config_loader import CONFIG
from constitution.verdict_engine import generate_l12_verdict
from context.runtime_state import RuntimeState
from ingest.candle_builder import CandleBuilder
from ingest.finnhub_news import FinnhubNews
from ingest.dependencies import create_default_finnhub_ws
from journal.journal_router import journal_router
from journal.journal_schema import ContextJournal, DecisionJournal, VerdictType
from storage.l12_cache import set_verdict
from storage.snapshot_store import save_snapshot
from utils.timezone_utils import is_trading_session, now_utc

PAIRS = [p["symbol"] for p in CONFIG["pairs"]["pairs"] if p.get("enabled", True)]

# Global flag for graceful shutdown
_shutdown_event: Optional[asyncio.Event] = None


def _build_j1(pair: str, synthesis: dict) -> ContextJournal:
    """
    Build J1 ContextJournal from synthesis data.

    Args:
        pair: Trading pair symbol
        synthesis: Synthesis output from adapt_synthesis

    Returns:
        ContextJournal instance
    """
    # Extract context from synthesis layers
    layers = synthesis.get("layers", {})
    bias = synthesis.get("bias", {})

    # Get trading session
    session = is_trading_session()

    # Build J1
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
    """
    Build J2 DecisionJournal from synthesis and L12 verdict.

    Args:
        pair: Trading pair symbol
        synthesis: Synthesis output from adapt_synthesis
        l12: L12 verdict output from generate_l12_verdict

    Returns:
        DecisionJournal instance
    """
    scores = synthesis.get("scores", {})
    layers = synthesis.get("layers", {})
    gates = l12.get("gates", {})

    # Build setup_id from pair and timestamp
    timestamp_str = now_utc().strftime("%Y%m%d_%H%M%S")
    setup_id = f"{pair}_{timestamp_str}"

    # Extract failed gates
    failed_gates = [
        gate_name
        for gate_name, gate_value in gates.items()
        if gate_name not in ["passed", "total"] and gate_value == "FAIL"
    ]

    # Determine primary rejection reason
    primary_rejection_reason = None
    if l12["verdict"] in [VerdictType.HOLD.value, VerdictType.NO_TRADE.value]:
        if failed_gates:
            primary_rejection_reason = f"Failed gates: {', '.join(failed_gates)}"
        else:
            primary_rejection_reason = "Constitutional violation"

    # Map verdict string to VerdictType enum
    verdict_str = l12["verdict"]
    try:
        verdict_type = VerdictType(verdict_str)
    except ValueError:
        verdict_type = VerdictType.NO_TRADE

    # Build J2
    return DecisionJournal(
        timestamp=now_utc(),
        pair=pair,
        setup_id=setup_id,
        wolf_30_score=int(scores.get("wolf_30_point", 0)),
        f_score=int(scores.get("f_score", 0)),
        t_score=int(scores.get("t_score", 0)),
        fta_score=int(
            (scores.get("fta_score") or 0) * 10
        ),  # Convert fta_score from 0-1 scale to 0-10 scale
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
        violations=[],  # Would be populated if available in L12
        primary_rejection_reason=primary_rejection_reason,
    )


def _validate_api_key() -> bool:
    """
    Validate Finnhub API key on startup.

    Returns:
        bool: True if API key is valid, False otherwise
    """
    api_key = os.getenv("FINNHUB_API_KEY", "")

    if not api_key or api_key == "YOUR_FINNHUB_API_KEY":
        logger.warning(
            "╔════════════════════════════════════════════════════════════╗\n"
            "║  WARNING: FINNHUB_API_KEY not configured                 ║\n"
            "║  System running in DRY RUN mode                           ║\n"
            "║  No live data feed available                              ║\n"
            "║  Set FINNHUB_API_KEY environment variable for live data  ║\n"
            "╚════════════════════════════════════════════════════════════╝"
        )
        return False

    logger.info("✓ FINNHUB_API_KEY validated")
    return True


async def run_ingest_services(
    has_api_key: bool,
) -> None:
    """
    Run data ingestion services concurrently.

    Args:
        has_api_key: Whether a valid Finnhub API key is configured
    """
    if not has_api_key:
        logger.info("Skipping ingest services - no API key configured")
        # Keep task alive but don't do anything
        while True:
            if _shutdown_event and _shutdown_event.is_set():
                break
            await asyncio.sleep(1)
        return

    ws_feed = await create_default_finnhub_ws()
    news_feed = FinnhubNews()
    candle_builder = CandleBuilder()

    logger.info("Starting ingest services: WebSocket, News, CandleBuilder")

    # Run all three services concurrently
    await asyncio.gather(
        ws_feed.run(),
        news_feed.run(),
        candle_builder.run(),
    )


async def run_redis_consumer() -> None:
    """
    Run RedisConsumer for CONTEXT_MODE=redis.

    This consumes ticks/candles from Redis that were published by a
    separate ingest container.
    """
    try:
        from context.redis_consumer import RedisConsumer

        redis_consumer = RedisConsumer(symbols=PAIRS)
        logger.info("Starting RedisConsumer...")
        await redis_consumer.start()

    except Exception as exc:
        logger.error(
            f"Failed to start RedisConsumer: {exc}. "
            "Continuing without Redis consumer."
        )
        # Keep task alive so main doesn't exit
        while True:
            if _shutdown_event and _shutdown_event.is_set():
                break
            await asyncio.sleep(1)


async def analysis_loop() -> None:
    """
    Main analysis loop (async version).

    Reads from LiveContextBus and runs L1-L12 analysis pipeline.
    """
    loop_interval = CONFIG["settings"].get("loop_interval_sec", 60)

    logger.info(f"Analysis loop started (interval={loop_interval}s)")

    while True:
        if _shutdown_event and _shutdown_event.is_set():
            logger.info("Analysis loop shutting down...")
            break

        for pair in PAIRS:
            try:
                # 1. Build analysis (L1-L11)
                raw_synthesis = build_synthesis(pair)

                # 2. Adapt contract
                synthesis = adapt_synthesis(raw_synthesis)

                # 3. Inject latency
                synthesis["system"]["latency_ms"] = RuntimeState.latency_ms

                # === JOURNAL J1: Record context (BEFORE L12) ===
                try:
                    j1 = _build_j1(pair, synthesis)
                    journal_router.record_context(j1)
                except Exception as journal_exc:
                    logger.error(f"J1 journal failed for {pair}: {journal_exc}")
                    # Continue execution — journal failures must not break trading loop

                # 4. L12 verdict
                l12 = generate_l12_verdict(synthesis)

                # === JOURNAL J2: Record decision (AFTER L12) ===
                try:
                    j2 = _build_j2(pair, synthesis, l12)
                    journal_router.record_decision(j2)
                except Exception as journal_exc:
                    logger.error(f"J2 journal failed for {pair}: {journal_exc}")
                    # Continue execution — journal failures must not break trading loop

                # 5. Cache verdict for EA
                set_verdict(pair, l12)

                # 6. Snapshot L14
                save_snapshot(pair, l12)

                logger.debug(f"[L12] {pair} → {l12['verdict']}")

            except Exception as e:
                logger.error(f"[ERROR] {pair} | {e}")

        await asyncio.sleep(loop_interval)


def _signal_handler(signum: int, frame) -> None:
    """Handle shutdown signals."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    if _shutdown_event:
        _shutdown_event.set()


async def main() -> None:
    """
    Main async orchestrator.

    Runs ingest services and analysis loop concurrently.
    Supports both local mode (with Finnhub ingestion) and redis mode
    (with RedisConsumer).
    """
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    # Configure logging — split streams for Railway compatibility
    logger.remove()

    # INFO/WARNING → stdout (Railway classifies as "info")
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
        "<level>{message}</level>",
        level="INFO",
        filter=lambda record: record["level"].no < 40,  # Below ERROR
    )

    # ERROR/CRITICAL → stderr (Railway classifies as "error")
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
        "<level>{message}</level>",
        level="ERROR",
    )

    # Register signal handlers
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    logger.info("═" * 60)
    logger.info("WOLF 15-LAYER TRADING SYSTEM v7.4r∞")
    logger.info("═" * 60)

    # Validate API key
    has_api_key = _validate_api_key()

    # Check context mode
    context_mode = os.getenv("CONTEXT_MODE", "local").lower()
    logger.info(f"Context mode: {context_mode.upper()}")

    # Create tasks based on mode
    tasks = []

    if context_mode == "redis":
        # Redis mode: Run RedisConsumer + analysis loop
        logger.info("Redis mode: Starting RedisConsumer + analysis loop")
        tasks = [
            asyncio.create_task(run_redis_consumer(), name="RedisConsumer"),
            asyncio.create_task(analysis_loop(), name="AnalysisLoop"),
        ]
    else:
        # Local mode: Run ingest services + analysis loop
        logger.info("Local mode: Starting ingest services + analysis loop")
        tasks = [
            asyncio.create_task(
                run_ingest_services(has_api_key),
                name="IngestServices",
            ),
            asyncio.create_task(analysis_loop(), name="AnalysisLoop"),
        ]

    logger.info(f"System initialized. Running {len(tasks)} concurrent tasks.")

    try:
        # Run all tasks concurrently
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
