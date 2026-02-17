import asyncio
import os
import signal
import sys
from collections.abc import Callable, Coroutine

from loguru import logger  # pyright: ignore[reportMissingImports]
from redis.asyncio import Redis as AsyncRedis  # pyright: ignore[reportMissingImports]

from config_loader import CONFIG
from core.event_bus import Event, EventType, get_event_bus
from core.health_probe import HealthProbe
from ingest.candle_builder import CandleBuilder
from ingest.dependencies import create_finnhub_ws
from ingest.finnhub_market_news import FinnhubMarketNews
from ingest.finnhub_news import FinnhubNews
from journal.journal_schema import ContextJournal, DecisionJournal, VerdictType
from pipeline import WolfConstitutionalPipeline
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

# ── Health probe for container orchestration ────────────────────
_ENGINE_HEALTH_PORT = int(os.getenv("ENGINE_HEALTH_PORT", "8081"))
_health_probe = HealthProbe(port=_ENGINE_HEALTH_PORT, service_name="engine")
_analysis_healthy = False


def _engine_readiness() -> bool:
    """Readiness gate: True once at least one analysis cycle has completed."""
    return _analysis_healthy


_health_probe.set_readiness_check(_engine_readiness)

# ── Run mode: 'all' (default/dev), 'engine-only', 'ingest-only' ─
RUN_MODE = os.getenv("RUN_MODE", "all").lower()

_MAX_TASK_RESTARTS = int(os.getenv("MAX_TASK_RESTARTS", "5"))
_RESTART_COOLDOWN = float(os.getenv("RESTART_COOLDOWN_SEC", "5.0"))

# Pipeline execution timeout in seconds
_PIPELINE_TIMEOUT_SEC = 30.0


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

    # Create CandleBuilder instances for each enabled pair at default timeframe
    default_timeframe = CONFIG["settings"].get("default_timeframe", "1h")
    candle_builders = [
        CandleBuilder(symbol=pair, timeframe=default_timeframe)
        for pair in PAIRS
    ]

    logger.info("Starting ingest services: WebSocket, News, MarketNews, CandleBuilder")
    try:
        await asyncio.gather(
            ws_feed.run(),
            news_feed.run(),
            market_news.run(),
            *[cb.run() for cb in candle_builders], # pyright: ignore[reportAttributeAccessIssue]
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


async def _analyze_pair(pair: str) -> dict | None:
    """Run pipeline for a single pair with timeout + thread offload."""
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_pipeline.execute, pair),
            timeout=_PIPELINE_TIMEOUT_SEC,
        )
        return result
    except TimeoutError:
        logger.error(
            f"[Pipeline] TIMEOUT after {_PIPELINE_TIMEOUT_SEC}s for {pair} — skipping"
        )
        return None
    except Exception as exc:
        logger.error(f"[Pipeline] Error for {pair}: {exc}")
        return None


async def analysis_loop() -> None:
    """Event-driven analysis loop.

    Triggers immediately on CANDLE_CLOSED events from CandleBuilder,
    with ``loop_interval`` (default 60 s) as a maximum-wait fallback so
    analysis still runs periodically even if no candles close.

    When a CANDLE_CLOSED event arrives *only* the affected symbol is
    re-analysed, keeping CPU usage proportional to market activity.
    """
    global _analysis_healthy
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

    while True:
        if _shutdown_event and _shutdown_event.is_set():
            logger.info("Analysis loop shutting down...")
            break

        # Wait for a candle-close event OR the fallback timeout
        try:  # noqa: SIM105
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

        # Mark engine ready after first successful cycle
        if not _analysis_healthy:
            _analysis_healthy = True
            logger.info("Engine readiness: READY (first analysis cycle complete)")


def _signal_handler(signum: int, frame) -> None:
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    if _shutdown_event:
        _shutdown_event.set()


async def _supervised_task(
    name: str,
    coro_factory: Callable[[], Coroutine],
    max_restarts: int = _MAX_TASK_RESTARTS,
    cooldown: float = _RESTART_COOLDOWN,
) -> None:
    """Run *coro_factory()* with automatic restart on crash.

    In local (dev) mode the engine and ingest share a process.  This
    supervisor ensures one component crashing does not kill the other.
    After *max_restarts* consecutive failures the task is abandoned and
    the health probe is marked dead.
    """
    restarts = 0
    while restarts <= max_restarts:
        if _shutdown_event and _shutdown_event.is_set():
            return
        try:
            logger.info(f"[SUPERVISOR] Starting task '{name}' (attempt {restarts + 1})")
            await coro_factory()
            return  # clean exit
        except asyncio.CancelledError:
            logger.info(f"[SUPERVISOR] Task '{name}' cancelled")
            return
        except Exception as exc:
            restarts += 1
            logger.error(
                f"[SUPERVISOR] Task '{name}' crashed: {exc} "
                f"(restart {restarts}/{max_restarts})"
            )
            if restarts > max_restarts:
                logger.critical(
                    f"[SUPERVISOR] Task '{name}' exceeded max restarts — giving up"
                )
                _health_probe.set_alive(False)
                _health_probe.set_detail("dead_reason", f"{name}_crash_limit")
                return
            await asyncio.sleep(cooldown)


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
    logger.info(f"Context mode: {context_mode.upper()} | Run mode: {RUN_MODE.upper()}")
    await init_persistent_storage()

    # ── Health probe (always runs) ──────────────────────────────────
    tasks: list[asyncio.Task] = [
        asyncio.create_task(_health_probe.start(), name="HealthProbe"),
    ]

    if context_mode == "redis":
        # ── Production: engine reads from Redis (ingest is a separate container)
        if RUN_MODE in ("all", "engine-only"):
            tasks.append(
                asyncio.create_task(
                    _supervised_task("RedisConsumer", run_redis_consumer),
                    name="RedisConsumer",
                )
            )
            tasks.append(
                asyncio.create_task(
                    _supervised_task("AnalysisLoop", analysis_loop),
                    name="AnalysisLoop",
                )
            )
            if RUN_MODE == "engine-only":
                logger.info("RUN_MODE=engine-only — skipping ingest services")
    else:
        # ── Local dev: everything in one process (supervised) ───────
        if RUN_MODE in ("all", "ingest-only"):
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            redis_client = AsyncRedis.from_url(redis_url)
            tasks.append(
                asyncio.create_task(
                    _supervised_task(
                        "IngestServices",
                        lambda: run_ingest_services(has_api_key, redis_client),
                    ),
                    name="IngestServices",
                )
            )
        if RUN_MODE in ("all", "engine-only"):
            tasks.append(
                asyncio.create_task(
                    _supervised_task("AnalysisLoop", analysis_loop),
                    name="AnalysisLoop",
                )
            )

        if RUN_MODE == "all":
            logger.warning(
                "Running ingest + engine in ONE process (dev mode). "
                "Use separate containers or RUN_MODE=engine-only|ingest-only for production."
            )

    logger.info(f"System initialized. Running {len(tasks)} concurrent tasks.")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Tasks cancelled, shutting down...")
    except Exception as exc:
        logger.error(f"Fatal error: {exc}")
        raise
    finally:
        await _health_probe.stop()
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
