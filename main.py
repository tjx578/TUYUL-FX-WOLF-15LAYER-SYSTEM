"""WOLF 15-LAYER TRADING SYSTEM — Engine Orchestrator.

Slim entrypoint that composes lifecycle modules from startup/ package.
Each concern lives in its own module:

  startup/candle_seeding.py   — Coldstart warmup (Redis or Finnhub REST)
  startup/signal_handlers.py  — OS signal handling + shutdown event
  startup/task_supervisor.py  — Auto-restart supervision for async tasks
  startup/analysis_loop.py    — Event-driven analysis loop + per-pair executor
  journal/builders.py         — J1/J2 journal entry construction

Run modes (RUN_MODE env):
  all            — Engine + ingest + HTTP API (local dev)
  engine-only    — Pipeline analysis loop only
  ingest-only    — WebSocket + candle ingest only
  engine-ingest  — Engine + ingest, no HTTP (Railway consolidated)
  api-only     — HTTP API only
"""

from __future__ import annotations

import asyncio
import os
import sys

import uvicorn
from loguru import logger
from redis.asyncio import Redis as AsyncRedis

from config_loader import get_enabled_symbols
from core.health_probe import HealthProbe
from core.startup_validator import validate_engine_startup_async
from infrastructure.tracing import (
    instrument_asyncio,
    instrument_httpx,
    instrument_redis,
    instrument_requests,
    setup_tracer,
)
from ingest.service_runner import run_ingest_services
from pipeline import WolfConstitutionalPipeline
from startup.analysis_loop import analysis_loop
from startup.candle_seeding import seed_candles_on_startup
from startup.graceful_shutdown import GracefulShutdown
from startup.signal_handlers import install_signal_handlers
from startup.task_supervisor import supervised_task
from storage.startup import init_persistent_storage, shutdown_persistent_storage

try:
    from engines.v11 import V11PipelineHook

    _v11_hook: V11PipelineHook | None = V11PipelineHook()
except Exception:  # V11 optional — missing = skip
    _v11_hook = None

PAIRS: list[str] = get_enabled_symbols()

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
        ws_per_message_deflate=True,
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


async def _sanitize_redis_keys(redis_client: AsyncRedis) -> None:
    """Delete keys whose Redis type conflicts with what writers/consumers expect.

    Delegates to the shared implementation in ``core.redis_consumer_fix``
    which uses SCAN (instead of KEYS) and proactive TYPE checks.
    """
    from core.redis_consumer_fix import sanitize_redis_keys  # noqa: PLC0415

    await sanitize_redis_keys(redis_client)


async def run_redis_consumer() -> None:
    """Run RedisConsumer when CONTEXT_MODE=redis."""
    from context.redis_consumer import RedisConsumer  # noqa: PLC0415
    from infrastructure.redis_client import get_client  # noqa: PLC0415

    redis_client = await get_client()

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

    # Configure logging — split streams for Railway compatibility
    logger.remove()

    _app_env = os.getenv("APP_ENV", os.getenv("ENV", "development")).strip().lower()
    _stdout_level = "WARNING" if _app_env == "production" else "INFO"

    # INFO/WARNING (or WARNING-only in production) → stdout (Railway classifies as "info")
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
        "<level>{message}</level>",
        level=_stdout_level,
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

    install_signal_handlers(_shutdown_event)

    logger.info("=" * 60)
    logger.info("WOLF 15-LAYER TRADING SYSTEM")
    logger.info("=" * 60)

    # Log the resolved Redis URL (password masked) so operators can cross-check
    # that engine and API services target the same Redis instance (BUG #6).
    from infrastructure.redis_url import get_safe_redis_url as _get_safe_redis_url  # noqa: PLC0415

    logger.info("[Redis] Engine service Redis target: {}", _get_safe_redis_url())

    # ── Startup validation ──────────────────────────────────────────
    startup_check = await validate_engine_startup_async()
    if not startup_check.ok:
        logger.error(
            "Startup validation found {} error(s) — engine may not function correctly. "
            "Continuing to keep health probe alive for diagnostics.",
            len(startup_check.errors),
        )

    has_api_key = _validate_api_key()
    context_mode = os.getenv("CONTEXT_MODE", "local").lower()
    logger.info(f"Context mode: {context_mode.upper()} | Run mode: {RUN_MODE.upper()}")

    # ── Health probe FIRST so orchestrators see liveness immediately ─
    # In engine-only mode the runner (services/engine/runner.py) already
    # started a bootstrap probe on PORT before entering main(). Binding
    # the same port again would fail with EADDRINUSE.
    tasks: list[asyncio.Task[object]] = []
    if RUN_MODE not in ("engine-only", "engine-ingest"):
        tasks.append(asyncio.create_task(_health_probe.start(), name="HealthProbe"))

    await init_persistent_storage()

    # ── Redis pool health check at startup ──────────────────────────
    try:
        from infrastructure.redis_health import check_redis_pool_health  # noqa: PLC0415

        pool_report = await check_redis_pool_health()
        if not pool_report.get("healthy"):
            logger.error("[Startup] Redis pool unhealthy: {}", pool_report)
    except Exception as exc:
        logger.warning("[Startup] Redis health check skipped: {}", exc)

    # ── Seed candles BEFORE analysis loop starts ────────────────────
    if RUN_MODE in ("all", "engine-only", "engine-ingest"):
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
        if RUN_MODE in ("all", "engine-only", "engine-ingest"):
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
        if RUN_MODE in ("all", "ingest-only", "engine-ingest"):
            tasks.append(
                asyncio.create_task(
                    supervised_task(
                        "IngestServices",
                        lambda: run_ingest_services(has_api_key, _shutdown_event),
                        _shutdown_event,
                        _health_probe,
                    ),
                    name="IngestServices",
                )
            )
        if RUN_MODE in ("all", "engine-only", "engine-ingest"):
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
    elif RUN_MODE == "engine-ingest":
        logger.info("RUN_MODE=engine-ingest — engine + ingest consolidated, HTTP API disabled")

    logger.info(f"System initialized. Running {len(tasks)} concurrent tasks.")

    # ── Graceful shutdown coordinator ──────────────────────────────
    from infrastructure.redis_client import close_pool  # noqa: PLC0415

    gs = GracefulShutdown(drain_timeout=float(os.getenv("SHUTDOWN_DRAIN_SEC", "15")))
    gs.register_cleanup("health probe", _health_probe.stop)
    gs.register_cleanup("persistent storage", shutdown_persistent_storage)
    gs.register_cleanup("redis pool", close_pool)

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Tasks cancelled, initiating graceful shutdown...")
    except Exception as exc:
        logger.error(f"Fatal error: {exc}")
        raise
    finally:
        await gs.shutdown(tasks)
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
