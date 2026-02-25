"""
Wolf L12 API Server

FastAPI server for L12 verdict polling, dashboard trade management, and system health monitoring.
"""

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any

import fastapi  # pyright: ignore[reportMissingImports]
import uvicorn  # pyright: ignore[reportMissingImports]
from fastapi.middleware.cors import CORSMiddleware  # pyright: ignore[reportMissingImports]
from loguru import logger  # pyright: ignore[reportMissingImports]

from api.dashboard_routes import router as dashboard_router
from api.journal_routes import router as journal_router
from api.l12_routes import router as l12_router
from api.middleware.rate_limit import RateLimitMiddleware
from api.ws_routes import router as ws_router
from config_loader import CONFIG
from context.live_context_bus import LiveContextBus
from context.runtime_state import RuntimeState
from core.metrics import (
    ACTIVE_PAIRS,
    FEED_AGE,
    PIPELINE_LATENCY_MS,
    SYSTEM_HEALTHY,
    get_registry,
)
from dashboard.backend.auth import verify_token
from dashboard.price_feed import PriceFeed
from dashboard.price_watcher import PriceWatcher
from risk.risk_router import router as risk_router
from storage.health import postgres_health
from storage.startup import init_persistent_storage, shutdown_persistent_storage
from utils.timezone_utils import format_local, format_utc, now_utc

# Background task references
_price_feed_task = None
_price_watcher_task = None
_ingest_task = None
_redis_consumer = None  # RedisConsumer instance (when CONTEXT_MODE=redis)


async def _run_ingest_embedded() -> None:
    """Embedded ingest for single-container deploys (Railway/Render).

    Imports ingest_service lazily to avoid hard dependency when
    EMBED_INGEST is not enabled.
    """
    api_key = os.getenv("FINNHUB_API_KEY", "")
    if not api_key or api_key == "YOUR_FINNHUB_API_KEY":
        logger.warning(
            "FINNHUB_API_KEY not set — embedded ingest disabled. "
            "Real-time data feed will NOT work."
        )
        return

    try:
        from ingest_service import run_ingest_services  # noqa: PLC0415

        logger.info("Embedded ingest starting (single-container mode)")
        await run_ingest_services(has_api_key=True)
    except asyncio.CancelledError:
        logger.info("Embedded ingest cancelled")
    except Exception as exc:
        logger.error(f"Embedded ingest fatal error: {exc}", exc_info=True)


async def _run_price_feed_updater():
    """Background task to update price feed from LiveContextBus."""
    price_feed = PriceFeed()
    interval_sec = int(os.getenv("PRICE_FEED_INTERVAL_SEC", "2"))

    logger.info(f"Price feed updater started (interval: {interval_sec}s)")

    while True:
        try:
            price_feed.update_prices()
        except Exception as exc:
            logger.error(f"Price feed update error: {exc}")

        await asyncio.sleep(interval_sec)


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    """
    Lifespan context manager for background tasks.

    Starts price feed updater, price watcher, and optionally embedded
    ingest service on startup.  Stops them on shutdown.
    """
    global _price_feed_task, _price_watcher_task, _ingest_task, _redis_consumer

    # Startup
    logger.info("Starting background tasks...")

    # Start embedded ingest if EMBED_INGEST=true (single-container mode)
    if os.getenv("EMBED_INGEST", "false").lower() in ("true", "1", "yes"):
        _ingest_task = asyncio.create_task(
            _run_ingest_embedded(), name="EmbeddedIngest"
        )

    # Start RedisConsumer when CONTEXT_MODE=redis so that ticks written
    # to Redis by the ingest container are consumed into the local
    # LiveContextBus (required for multi-container AND single-container).
    if os.getenv("CONTEXT_MODE", "local").lower() == "redis":
        try:
            from context.redis_consumer import RedisConsumer  # noqa: PLC0415

            symbols = [
                p["symbol"]
                for p in CONFIG.get("pairs", {}).get("pairs", [])
                if p.get("enabled", True)
            ]
            _redis_consumer = RedisConsumer(symbols=symbols)
            await _redis_consumer.start()
            logger.info(f"RedisConsumer started for {len(symbols)} symbols")
        except Exception as exc:
            logger.error(f"Failed to start RedisConsumer: {exc}")
            _redis_consumer = None

    # Start price feed updater
    _price_feed_task = asyncio.create_task(_run_price_feed_updater())

    # Start price watcher
    price_watcher = PriceWatcher()
    _price_watcher_task = asyncio.create_task(price_watcher.start())

    await init_persistent_storage()

    logger.info("Background tasks started")

    yield

    # Shutdown
    logger.info("Stopping background tasks...")

    for task_name, task_ref in [
        ("ingest", _ingest_task),
        ("price_feed", _price_feed_task),
        ("price_watcher", _price_watcher_task),
    ]:
        if task_ref:
            task_ref.cancel()
            with suppress(asyncio.CancelledError):
                await task_ref
            logger.debug(f"Task {task_name} stopped")

    if _price_watcher_task:
        price_watcher.stop()

    # Stop RedisConsumer if running
    if _redis_consumer is not None:
        try:
            await _redis_consumer.stop()
            logger.debug("RedisConsumer stopped")
        except Exception as exc:
            logger.error(f"Error stopping RedisConsumer: {exc}")

    await shutdown_persistent_storage()

    logger.info("Background tasks stopped")


app = fastapi.FastAPI(
    title="Wolf L12 API",
    version="7.4r∞",
    description="Wolf 15-Layer Trading System - L12 Verdict & Dashboard API",
    lifespan=lifespan,
)

# CORS middleware for Next.js dashboard
# Configure allowed origins via environment variable in production
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],  # Allow POST for trade actions
    allow_headers=["*"],
)

# Rate limiting middleware (applied AFTER CORS so preflight isn't blocked)
app.add_middleware(RateLimitMiddleware)

# Include routers
# HTTP routers -- protected by Bearer token (JWT or API key)
app.include_router(l12_router, dependencies=[fastapi.Depends(verify_token)])
app.include_router(dashboard_router, dependencies=[fastapi.Depends(verify_token)])
app.include_router(journal_router, dependencies=[fastapi.Depends(verify_token)])
app.include_router(risk_router, dependencies=[fastapi.Depends(verify_token)])

# WebSocket router -- auth handled inside each endpoint via query-param token
# (FastAPI HTTP dependencies don't apply to WS upgrade handshakes)
app.include_router(ws_router)


def _get_feed_status() -> dict[str, str]:
    """
    Get per-symbol feed status.

    Returns:
        Dictionary with per-symbol status and overall status
    """
    api_key = os.getenv("FINNHUB_API_KEY", "")
    if not api_key or api_key == "YOUR_FINNHUB_API_KEY":
        return {"overall": "no_api_key"}

    context_bus = LiveContextBus()
    pairs = [p["symbol"] for p in CONFIG["pairs"]["pairs"] if p.get("enabled", True)]

    statuses = {}
    for pair in pairs:
        statuses[pair] = context_bus.get_feed_status(pair)

    # Overall status
    all_statuses = list(statuses.values())
    if all(s == "CONNECTED" for s in all_statuses):
        statuses["overall"] = "connected"
    elif any(s == "DOWN" for s in all_statuses):
        statuses["overall"] = "degraded"
    elif any(s == "NO_DATA" for s in all_statuses):
        statuses["overall"] = "no_data"
    else:
        statuses["overall"] = "connected"

    return statuses


def _get_last_tick_times() -> dict[str, float | None]:
    """
    Get last tick age in seconds for each symbol.

    Returns:
        Dictionary of symbol -> age in seconds (or None if no data)
    """
    context_bus = LiveContextBus()
    pairs = [p["symbol"] for p in CONFIG["pairs"]["pairs"] if p.get("enabled", True)]
    return {pair: context_bus.get_feed_age(pair) for pair in pairs}


def _get_candle_freshness() -> dict[str, int]:
    """
    Get age of latest candle per symbol in seconds.

    Returns:
        Dictionary of symbol -> age in seconds
    """
    context_bus = LiveContextBus()
    snapshot = context_bus.snapshot()
    raw_candles: Any = snapshot.get("candles", {})
    candles: dict[str, Any] = raw_candles if isinstance(raw_candles, dict) else {}

    now = datetime.now(UTC)
    freshness = {}

    for symbol, timeframes in candles.items():
        if not isinstance(timeframes, dict):
            continue
        for tf, candle in timeframes.items():
            if not isinstance(candle, dict):
                continue
            ts = candle.get("timestamp")
            if isinstance(ts, datetime):
                age = (now - ts).total_seconds()
                key = f"{symbol}_{tf}"
                freshness[key] = int(age)

    return freshness


def _get_redis_status() -> str:
    """
    Check Redis connection status.

    Returns:
        "connected" | "disconnected" | "not_configured"
    """
    context_mode = os.getenv("CONTEXT_MODE", "local").lower()

    if context_mode != "redis":
        return "not_configured"

    try:
        # Try to get LiveContextBus and check if Redis bridge exists
        context_bus = LiveContextBus()
        if hasattr(context_bus, "_redis_bridge") and context_bus._redis_bridge:
            return "connected"
        return "disconnected"
    except Exception:
        return "disconnected"


@app.get("/")
async def root():
    """Root endpoint."""
    current_time = now_utc()
    return {
        "service": "Wolf 15-Layer System",
        "version": "7.4r∞",
        "status": "operational",
        "time_utc": format_utc(current_time),
        "time_local": format_local(current_time),
    }


@app.get("/health")
async def health_check():
    """
    Enhanced health check endpoint for monitoring.

    Returns:
        Dictionary with system health information including:
        - Overall status
        - Feed connection status
        - Last tick timestamps per symbol
        - Candle freshness (age in seconds)
        - Redis status
        - System latency
    """
    pg_status = await postgres_health()

    return {
        "status": "healthy",
        "service": "wolf-l12-api",
        "version": "7.4r∞",
        "latency_ms": RuntimeState.latency_ms,
        "feed_status": _get_feed_status(),
        "last_tick_at": _get_last_tick_times(),
        "candle_freshness": _get_candle_freshness(),
        "redis_status": _get_redis_status(),
        "postgres": pg_status,
    }


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus text exposition endpoint.

    Returns all registered Wolf metrics in Prometheus text format.
    Feed-age gauges are refreshed on each scrape so they reflect the
    current staleness of each symbol's tick stream.
    """
    from fastapi.responses import PlainTextResponse  # noqa: PLC0415

    # Refresh runtime gauges before exposition
    context_bus = LiveContextBus()
    pairs = [p["symbol"] for p in CONFIG["pairs"]["pairs"] if p.get("enabled", True)]

    # Per-symbol feed age
    for pair in pairs:
        age = context_bus.get_feed_age(pair)
        if age is not None:
            FEED_AGE.labels(symbol=pair).set(age)

    # System-level gauges
    PIPELINE_LATENCY_MS.set(float(RuntimeState.latency_ms))
    ACTIVE_PAIRS.set(float(len(pairs)))
    SYSTEM_HEALTHY.set(1.0 if RuntimeState.healthy else 0.0)

    body = get_registry().exposition()
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
