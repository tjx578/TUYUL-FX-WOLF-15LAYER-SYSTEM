import asyncio
import os
import signal
import sys
import types
from collections.abc import Callable, Coroutine

import uvicorn
from loguru import logger
from redis.asyncio import Redis as AsyncRedis

from config_loader import CONFIG
from core.event_bus import Event, EventType, get_event_bus
from core.health_probe import HealthProbe
from ingest.candle_builder import CandleBuilder
from ingest.dependencies import create_finnhub_ws
from ingest.finnhub_market_news import FinnhubMarketNews
from ingest.finnhub_news import FinnhubNews
from infrastructure.tracing import instrument_asyncio, instrument_redis, setup_tracer
from journal.journal_schema import ContextJournal, DecisionJournal, VerdictType
from pipeline import WolfConstitutionalPipeline
from storage.startup import init_persistent_storage, shutdown_persistent_storage
from utils.timezone_utils import is_trading_session, now_utc  # pyright: ignore[reportUnknownVariableType]

try:
    from engines.v11 import V11PipelineHook
    _v11_hook: V11PipelineHook | None = V11PipelineHook()
except Exception:  # V11 optional — missing = skip
    _v11_hook = None

PAIRS = [p["symbol"] for p in CONFIG["pairs"]["pairs"] if p.get("enabled", True)]

_shutdown_event: asyncio.Event | None = None
_pipeline = WolfConstitutionalPipeline()
_engine_tracer = setup_tracer("wolf-engine")
instrument_asyncio()
instrument_redis()

# ── Health probe for container orchestration ────────────────────
_ENGINE_HEALTH_PORT = int(os.getenv("ENGINE_HEALTH_PORT", "8081"))
_health_probe = HealthProbe(port=_ENGINE_HEALTH_PORT, service_name="engine")
_analysis_healthy = False


# ── Candle seeding (warmup) ─────────────────────────────────────

async def seed_candles_on_startup() -> None:
    """Seed candle history into LiveContextBus BEFORE the analysis loop starts.

    Strategy depends on CONTEXT_MODE:
      - redis  : load candle history from Redis Lists (populated by ingest container)
      - local  : fetch historical candles directly from Finnhub REST API

    This ensures the pipeline warmup gate passes on the first analysis cycle.
    """
    context_mode = os.getenv("CONTEXT_MODE", "local").lower()
    logger.info(
        f"[SEED] Seeding candles on startup (mode={context_mode}, pairs={len(PAIRS)})"
    )

    if context_mode == "redis":
        await _seed_from_redis()
    else:
        await _seed_from_finnhub()

    # Verify warmup status
    from context.live_context_bus import LiveContextBus  # noqa: PLC0415

    bus = LiveContextBus()
    ready_count = 0
    for pair in PAIRS:
        status = bus.check_warmup(pair, WolfConstitutionalPipeline.WARMUP_MIN_BARS)
        if status.get("ready"):
            ready_count += 1
        else:
            logger.warning(
                f"[SEED] {pair} warmup still insufficient after seeding: {status.get('missing')}"
            )
    logger.info(f"[SEED] Warmup ready: {ready_count}/{len(PAIRS)} pairs")


async def _seed_from_redis() -> None:
    """Load candle history from Redis Lists into LiveContextBus."""
    try:
        from context.redis_consumer import RedisConsumer  # noqa: PLC0415
        from infrastructure.redis_url import get_redis_url  # noqa: PLC0415

        redis_url = get_redis_url()
        redis_client: AsyncRedis = AsyncRedis.from_url(redis_url)  # type: ignore[no-untyped-call]
        try:
            consumer = RedisConsumer(symbols=PAIRS, redis_client=redis_client)
            await consumer.load_candle_history()
            logger.info("[SEED] Redis candle history loaded into LiveContextBus")
        finally:
            await redis_client.aclose()
    except Exception as exc:
        logger.error(f"[SEED] Failed to seed from Redis: {exc}")


async def _seed_from_finnhub() -> None:
    """Fetch historical candles from Finnhub REST API into LiveContextBus."""
    from ingest.finnhub_key_manager import finnhub_keys  # noqa: PLC0415
    if not finnhub_keys.available:
        logger.warning("[SEED] No Finnhub API key — skipping REST warmup")
        return
    try:
        from ingest.finnhub_candles import FinnhubCandleFetcher  # noqa: PLC0415

        fetcher = FinnhubCandleFetcher()
        results = await fetcher.warmup_all()
        total = sum(
            len(candles)
            for tfs in results.values()
            for candles in tfs.values()
        )
        logger.info(
            f"[SEED] Finnhub warmup complete: {len(results)} symbols, {total} total bars"
        )
    except Exception as exc:
        logger.error(f"[SEED] Failed to seed from Finnhub: {exc}")


def _engine_readiness() -> bool:
    """Readiness gate: True once at least one analysis cycle has completed."""
    return _analysis_healthy


_health_probe.set_readiness_check(_engine_readiness)


async def _run_http_server() -> None:
    """Run FastAPI HTTP server as an async task inside the main event loop."""
    port = int(os.environ.get("PORT", "8000"))
    config = uvicorn.Config(
        "api_server:app",
        host="0.0.0.0",
        port=port,
        workers=1,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


# ── Run mode: 'all' (default/dev), 'engine-only', 'ingest-only', 'api-only' ─
RUN_MODE = os.getenv("RUN_MODE", "all").lower()

_MAX_TASK_RESTARTS = int(os.getenv("MAX_TASK_RESTARTS", "5"))
_RESTART_COOLDOWN = float(os.getenv("RESTART_COOLDOWN_SEC", "5.0"))

# Pipeline execution timeout in seconds
_PIPELINE_TIMEOUT_SEC = 30.0


def _build_j1(pair: str, synthesis: dict[str, object]) -> ContextJournal:
    layers: dict[str, object] = dict(synthesis.get("layers") or {})  # type: ignore[arg-type]
    bias: dict[str, object] = dict(synthesis.get("bias") or {})  # type: ignore[arg-type]
    session = is_trading_session()
    return ContextJournal(
        timestamp=now_utc(),
        pair=pair,
        session=session,
        market_regime=str(synthesis.get("market_regime", "UNKNOWN")),
        news_lock=bool(synthesis.get("news_lock", False)),
        context_coherence=float(layers.get("conf12", 0.5)),  # type: ignore[arg-type]
        mta_alignment=bool(synthesis.get("mta_alignment", True)),
        technical_bias=str(bias.get("technical", "NEUTRAL")),
    )


def _build_j2(pair: str, synthesis: dict[str, object], l12: dict[str, object]) -> DecisionJournal:
    scores: dict[str, object] = dict(synthesis.get("scores") or {})  # type: ignore[arg-type]
    layers: dict[str, object] = dict(synthesis.get("layers") or {})  # type: ignore[arg-type]
    gates: dict[str, object] = dict(l12.get("gates") or {})  # type: ignore[arg-type]
    setup_id = f"{pair}_{now_utc().strftime('%Y%m%d_%H%M%S')}"

    failed_gates: list[str] = [
        str(gate_name)
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
        wolf_30_score=int(scores.get("wolf_30_point", 0)),  # type: ignore[arg-type]
        f_score=int(scores.get("f_score", 0)),  # type: ignore[arg-type]
        t_score=int(scores.get("t_score", 0)),  # type: ignore[arg-type]
        fta_score=int((scores.get("fta_score") or 0) * 10),  # type: ignore[operator]
        exec_score=int(scores.get("exec_score", 0)),  # type: ignore[arg-type]
        tii_sym=float(layers.get("L8_tii_sym", 0.0)),  # type: ignore[arg-type]
        integrity_index=float(layers.get("L8_integrity_index", 0.0)),  # type: ignore[arg-type]
        monte_carlo_win=float(layers.get("L7_monte_carlo_win", 0.0)),  # type: ignore[arg-type]
        conf12=float(layers.get("conf12", 0.0)),  # type: ignore[arg-type]
        verdict=verdict_type,
        confidence=str(l12.get("confidence", "LOW")),
        wolf_status=str(l12.get("wolf_status", "NO_HUNT")),
        gates_passed=int(gates.get("passed", 0)),  # type: ignore[arg-type]
        gates_total=int(gates.get("total", 9)),  # type: ignore[arg-type]
        failed_gates=failed_gates,
        violations=[],
        primary_rejection_reason=primary_rejection_reason,
    )


def _validate_api_key() -> bool:
    from ingest.finnhub_key_manager import finnhub_keys  # noqa: PLC0415
    if not finnhub_keys.available:
        logger.warning("WARNING: FINNHUB_API_KEY not configured; running in DRY RUN mode.")
        return False
    logger.info("FINNHUB_API_KEY validated (%d key(s) loaded)", finnhub_keys.key_count)
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
        cb_coros: list[Coroutine[object, object, object]] = [cb.run() for cb in candle_builders]  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        await asyncio.gather(
            ws_feed.run(),
            news_feed.run(),
            market_news.run(),
            *cb_coros,
        )
    except asyncio.CancelledError:
        logger.info("Ingest services cancelled - shutting down")
        raise
    finally:
        await ws_feed.stop()
        await redis.aclose()
        logger.info("Ingest services cleanup complete")


async def _sanitize_redis_keys(redis_client: AsyncRedis) -> None:
    """Delete keys whose Redis type conflicts with what writers/consumers expect.

    This prevents WRONGTYPE errors when the ingest bridge or RedisConsumer
    encounters a key left over from an earlier schema (e.g. a ``string`` where
    a ``hash`` or ``list`` is now expected).

    Key-pattern → expected-type mapping mirrors:
      - context/redis_context_bridge.py  (bridge writes)
      - context/redis_consumer.py        (consumer reads)
    """
    # pattern → expected Redis type
    keys_expected: dict[str, str] = {
        "wolf15:tick:*":            "stream",   # bridge XADD
        "wolf15:latest_tick:*":     "hash",     # bridge HSET
        "wolf15:candle:*":          "hash",     # bridge HSET (latest candle)
        "wolf15:candle_history:*":  "list",     # bridge RPUSH / consumer LRANGE
        "candle_history:*":         "list",     # legacy consumer LRANGE
    }

    total_deleted = 0
    for pattern, expected_type in keys_expected.items():
        try:
            keys: list[bytes | str] = await redis_client.keys(pattern)  # type: ignore[assignment]
        except Exception as exc:
            logger.warning("[Redis-sanitize] KEYS %s failed: %s", pattern, exc)
            continue

        for key in keys:
            key_str = key if isinstance(key, str) else key.decode()
            try:
                actual_type: str = await redis_client.type(key_str)
            except Exception as exc:
                logger.warning("[Redis-sanitize] TYPE %s failed: %s", key_str, exc)
                continue

            if actual_type == "none":
                continue
            if actual_type == expected_type:
                continue

            logger.warning(
                "[Redis-sanitize] Key '%s' type mismatch: expected=%s, actual=%s → deleting",
                key_str, expected_type, actual_type,
            )
            try:
                await redis_client.delete(key_str)
                total_deleted += 1
            except Exception as exc:
                logger.error("[Redis-sanitize] Failed to delete '%s': %s", key_str, exc)

    if total_deleted:
        logger.info("[Redis-sanitize] Cleaned %d conflicting key(s)", total_deleted)
    else:
        logger.debug("[Redis-sanitize] No type conflicts found")


async def run_redis_consumer() -> None:
    """Run RedisConsumer when CONTEXT_MODE=redis.

    Fail-loud: any startup or runtime error is re-raised so the supervisor
    can detect the failure and restart (rather than continuing silently
    without a consumer, which would leave the pipeline with 0 bars).
    """
    from context.redis_consumer import RedisConsumer  # noqa: PLC0415
    from infrastructure.redis_url import get_redis_url  # noqa: PLC0415

    redis_url = get_redis_url()
    redis_client: AsyncRedis = AsyncRedis.from_url(redis_url)  # type: ignore[no-untyped-call]

    # Clean keys with wrong type before consumer touches them
    await _sanitize_redis_keys(redis_client)

    redis_consumer = RedisConsumer(symbols=PAIRS, redis_client=redis_client)
    logger.info("Starting RedisConsumer...")
    await redis_consumer.run()


async def _analyze_pair(pair: str) -> dict[str, object] | None:
    """Run pipeline for a single pair with timeout + thread offload."""
    with _engine_tracer.start_as_current_span("pipeline_full") as span:
        span.set_attribute("pair", pair)
        span.set_attribute("pipeline.timeout_sec", _PIPELINE_TIMEOUT_SEC)
        try:
            # Capture last tick timestamp for end-to-end latency tracing
            from context.live_context_bus import LiveContextBus  # noqa: PLC0415

            _bus = LiveContextBus()
            _latest: dict[str, object] | None = _bus.get_latest_tick(pair)
            _tick_ts: float | None = (
                float(_latest.get("local_ts") or _latest.get("timestamp") or 0.0)  # type: ignore[arg-type]
                if _latest
                else None
            )
            if _tick_ts:
                span.set_attribute("tick.timestamp", _tick_ts)

            # Ensure pipeline.execute never blocks event loop
            result = await asyncio.wait_for(
                asyncio.to_thread(lambda: _pipeline.execute(pair, None, tick_ts=_tick_ts)),
                timeout=_PIPELINE_TIMEOUT_SEC,
            )

            # ── Journal J1 (context) and J2 (decision) after each pipeline run ──
            if result:
                synthesis: dict[str, object] = dict(result.get("synthesis") or {})
                l12: dict[str, object] = dict(result.get("l12") or {})
                span.set_attribute("l12.verdict", str(l12.get("verdict", "")))
                span.set_attribute("l12.confidence", str(l12.get("confidence", "")))
                try:
                    j1 = _build_j1(pair, synthesis)
                    logger.debug(f"[J1] Context journal created for {pair}: {j1.market_regime}")
                except Exception as j1_exc:
                    logger.warning(f"[J1] Failed to build context journal for {pair}: {j1_exc}")
                if l12:
                    try:
                        j2 = _build_j2(pair, synthesis, l12)
                        logger.debug(f"[J2] Decision journal created for {pair}: verdict={j2.verdict}")
                    except Exception as j2_exc:
                        logger.warning(f"[J2] Failed to build decision journal for {pair}: {j2_exc}")

            return result
        except TimeoutError as exc:
            span.record_exception(exc)
            logger.error(
                f"[Pipeline] TIMEOUT after {_PIPELINE_TIMEOUT_SEC}s for {pair} — skipping"
            )
            return None
        except Exception as exc:
            import traceback

            span.record_exception(exc)
            logger.error(f"[Pipeline] Error for {pair}: {exc}\n{traceback.format_exc()}")
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
        data: dict[str, object] = dict(event.data)  # type: ignore[arg-type]
        symbol = data.get("symbol")
        if isinstance(symbol, str) and symbol:
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


def _signal_handler(signum: int, frame: types.FrameType | None) -> None:
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    if _shutdown_event:
        _shutdown_event.set()


async def _supervised_task(
    name: str,
    coro_factory: Callable[[], Coroutine[object, object, object]],
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

    # ── Seed candles BEFORE analysis loop starts ────────────────────
    if RUN_MODE in ("all", "engine-only"):
        try:
            await seed_candles_on_startup()
        except Exception as exc:
            logger.error(f"[SEED] Candle seeding failed (non-fatal): {exc}")

    # ── Health probe (always runs) ──────────────────────────────────
    tasks: list[asyncio.Task[object]] = [
        asyncio.create_task(_health_probe.start(), name="HealthProbe"),
    ]

    # ── HTTP server (only in all/api-only mode) ─────────────────────
    if RUN_MODE in ("all", "api-only"):
        tasks.append(
            asyncio.create_task(
                _supervised_task("HTTPServer", _run_http_server),
                name="HTTPServer",
            )
        )

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
            from infrastructure.redis_url import get_redis_url
            redis_url = get_redis_url()
            redis_client: AsyncRedis = AsyncRedis.from_url(redis_url)  # type: ignore[no-untyped-call]
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

    if RUN_MODE == "engine-only":
        logger.info("RUN_MODE=engine-only — HTTP API is disabled by design")
    elif RUN_MODE == "ingest-only":
        logger.info("RUN_MODE=ingest-only — HTTP API is disabled by design")

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
