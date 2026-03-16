"""WOLF 15-LAYER TRADING SYSTEM — Engine Orchestrator.

Slim entrypoint that composes lifecycle modules from startup/ package.
Each concern lives in its own module:

  startup/candle_seeding.py   — Coldstart warmup (Redis or Finnhub REST)
  startup/signal_handlers.py  — OS signal handling + shutdown event
  startup/task_supervisor.py  — Auto-restart supervision for async tasks
  startup/analysis_loop.py    — Event-driven analysis loop + per-pair executor
  journal/builders.py         — J1/J2 journal entry construction

Run modes (RUN_MODE env):
  all          — Engine + ingest + HTTP API (local dev)
  engine-only  — Pipeline analysis loop only
  ingest-only  — WebSocket + candle ingest only
  api-only     — HTTP API only
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Coroutine

import uvicorn
from loguru import logger
from redis.asyncio import Redis as AsyncRedis

from config_loader import CONFIG
from core.health_probe import HealthProbe
from infrastructure.tracing import (
    instrument_asyncio,
    instrument_httpx,
    instrument_redis,
    instrument_requests,
    setup_tracer,
)
from ingest.calendar_news import CalendarNewsIngestor
from ingest.candle_builder import CandleBuilder
from ingest.dependencies import create_finnhub_ws
from ingest.finnhub_market_news import FinnhubMarketNews
from pipeline import WolfConstitutionalPipeline
from startup.analysis_loop import analysis_loop
from startup.candle_seeding import seed_candles_on_startup
from startup.signal_handlers import install_signal_handlers
from startup.task_supervisor import supervised_task
from storage.startup import init_persistent_storage, shutdown_persistent_storage

try:
    from engines.v11 import V11PipelineHook

    _v11_hook: V11PipelineHook | None = V11PipelineHook()
except Exception:  # V11 optional — missing = skip
    _v11_hook = None

PAIRS: list[str] = [str(p["symbol"]) for p in CONFIG["pairs"]["pairs"] if p.get("enabled", True)]

_shutdown_event: asyncio.Event | None = None
_pipeline = WolfConstitutionalPipeline()
_engine_tracer = setup_tracer("wolf-engine")
instrument_asyncio()
instrument_redis()
instrument_requests()
instrument_httpx()

# ── Health probe for container orchestration ────────────────────
_ENGINE_HEALTH_PORT = int(os.getenv("ENGINE_HEALTH_PORT", "8081"))
_health_probe = HealthProbe(port=_ENGINE_HEALTH_PORT, service_name="engine")
_analysis_healthy = False

# ── Run mode configuration ──────────────────────────────────────
RUN_MODE = os.getenv("RUN_MODE", "all").lower()


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


def _validate_api_key() -> bool:
    from ingest.finnhub_key_manager import finnhub_keys  # noqa: PLC0415

    if not finnhub_keys.available:
        logger.warning("WARNING: FINNHUB_API_KEY not configured; running in DRY RUN mode.")
        return False
    logger.info("FINNHUB_API_KEY validated ({} key(s) loaded)", finnhub_keys.key_count)
    return True


async def run_ingest_services(has_api_key: bool, redis: AsyncRedis) -> None:
    """Run ingestion tasks concurrently in local mode."""
    if not has_api_key:
        logger.info("Skipping ingest services - no API key configured")
        while not (_shutdown_event and _shutdown_event.is_set()):  # noqa: ASYNC110
            await asyncio.sleep(1)
        return

    ws_feed = await create_finnhub_ws(redis=redis)
    news_feed = CalendarNewsIngestor(redis_client=redis)
    market_news = FinnhubMarketNews()

    default_timeframe = CONFIG["settings"].get("default_timeframe", "1h")
    candle_builders = [CandleBuilder(symbol=pair, timeframe=default_timeframe) for pair in PAIRS]

    logger.info("Starting ingest services: WebSocket, CalendarNews, MarketNews, CandleBuilder")
    try:
        cb_coros: list[Coroutine[object, object, object]] = [cb.run() for cb in candle_builders]  # pyright: ignore[reportAttributeAccessIssue]
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
    """Delete keys whose Redis type conflicts with what writers/consumers expect."""

    def _normalize_redis_type(value: bytes | str) -> str:
        if isinstance(value, bytes | bytearray):
            return value.decode().lower()
        return str(value).lower()

    keys_expected: dict[str, str] = {
        "wolf15:tick:*": "stream",
        "wolf15:latest_tick:*": "hash",
        "wolf15:candle:*": "hash",
        "wolf15:candle_history:*": "list",
        "candle_history:*": "list",
    }

    total_deleted = 0
    mismatch_diagnostic_logged = False
    for pattern, expected_type in keys_expected.items():
        try:
            keys: list[bytes | str] = await redis_client.keys(pattern)
        except Exception as exc:
            logger.warning("[Redis-sanitize] KEYS {} failed: {}", pattern, exc)
            continue

        for key in keys:
            key_str = key if isinstance(key, str) else key.decode()
            try:
                actual_type_raw: bytes | str = await redis_client.type(key_str)
            except Exception as exc:
                logger.warning("[Redis-sanitize] TYPE {} failed: {}", key_str, exc)
                continue

            actual_type = _normalize_redis_type(actual_type_raw)

            if actual_type == "none":
                continue
            if actual_type == expected_type:
                continue

            if not mismatch_diagnostic_logged:
                logger.warning(
                    "[Redis-sanitize] Mismatch diagnostic (one-time): key='{}' raw_type={!r} normalized_type={} expected_type={}",
                    key_str,
                    actual_type_raw,
                    actual_type,
                    expected_type,
                )
                mismatch_diagnostic_logged = True

            logger.warning(
                "[Redis-sanitize] Key '{}' type mismatch: expected={}, actual={} → deleting",
                key_str,
                expected_type,
                actual_type,
            )
            try:
                await redis_client.delete(key_str)
                total_deleted += 1
            except Exception as exc:
                logger.error("[Redis-sanitize] Failed to delete '{}': {}", key_str, exc)

    if total_deleted:
        logger.info("[Redis-sanitize] Cleaned {} conflicting key(s)", total_deleted)
    else:
        logger.debug("[Redis-sanitize] No type conflicts found")


async def run_redis_consumer() -> None:
    """Run RedisConsumer when CONTEXT_MODE=redis."""
    from context.redis_consumer import RedisConsumer  # noqa: PLC0415
    from infrastructure.redis_url import get_redis_url  # noqa: PLC0415

    redis_url = get_redis_url()
    redis_client: AsyncRedis = AsyncRedis.from_url(redis_url)

    await _sanitize_redis_keys(redis_client)

    redis_consumer = RedisConsumer(symbols=PAIRS, redis_client=redis_client)
    logger.info("Starting RedisConsumer...")
    await redis_consumer.run()


async def _run_analysis_loop() -> None:
    """Wrapper that bridges the analysis loop to the engine health state."""
    global _analysis_healthy
    _ready_event = asyncio.Event()

    async def _monitor_readiness() -> None:
        global _analysis_healthy
        await _ready_event.wait()
        _analysis_healthy = True

    monitor = asyncio.create_task(_monitor_readiness())
    try:
        await analysis_loop(
            pairs=PAIRS,
            pipeline=_pipeline,
            shutdown_event=_shutdown_event,
            on_first_cycle=_ready_event,
        )
    finally:
        monitor.cancel()


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

    install_signal_handlers(_shutdown_event)

    logger.info("=" * 60)
    logger.info("WOLF 15-LAYER TRADING SYSTEM")
    logger.info("=" * 60)

    has_api_key = _validate_api_key()
    context_mode = os.getenv("CONTEXT_MODE", "local").lower()
    logger.info(f"Context mode: {context_mode.upper()} | Run mode: {RUN_MODE.upper()}")

    # ── Health probe FIRST so orchestrators see liveness immediately ─
    tasks: list[asyncio.Task[object]] = [
        asyncio.create_task(_health_probe.start(), name="HealthProbe"),
    ]

    await init_persistent_storage()

    # ── Seed candles BEFORE analysis loop starts ────────────────────
    if RUN_MODE in ("all", "engine-only"):
        try:
            await seed_candles_on_startup(PAIRS, WolfConstitutionalPipeline.WARMUP_MIN_BARS)
        except Exception as exc:
            logger.error(f"[SEED] Candle seeding failed (non-fatal): {exc}")

    # ── HTTP server (only in all/api-only mode) ─────────────────────
    if RUN_MODE in ("all", "api-only"):
        tasks.append(
            asyncio.create_task(
                supervised_task("HTTPServer", _run_http_server, _shutdown_event, _health_probe),
                name="HTTPServer",
            )
        )

    if context_mode == "redis":
        if RUN_MODE in ("all", "engine-only"):
            tasks.append(
                asyncio.create_task(
                    supervised_task("RedisConsumer", run_redis_consumer, _shutdown_event, _health_probe),
                    name="RedisConsumer",
                )
            )
            tasks.append(
                asyncio.create_task(
                    supervised_task("AnalysisLoop", _run_analysis_loop, _shutdown_event, _health_probe),
                    name="AnalysisLoop",
                )
            )
            if RUN_MODE == "engine-only":
                logger.info("RUN_MODE=engine-only — skipping ingest services")
    else:
        if RUN_MODE in ("all", "ingest-only"):
            from infrastructure.redis_url import get_redis_url

            redis_url = get_redis_url()
            redis_client: AsyncRedis = AsyncRedis.from_url(redis_url)
            tasks.append(
                asyncio.create_task(
                    supervised_task(
                        "IngestServices",
                        lambda: run_ingest_services(has_api_key, redis_client),
                        _shutdown_event,
                        _health_probe,
                    ),
                    name="IngestServices",
                )
            )
        if RUN_MODE in ("all", "engine-only"):
            tasks.append(
                asyncio.create_task(
                    supervised_task("AnalysisLoop", _run_analysis_loop, _shutdown_event, _health_probe),
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
