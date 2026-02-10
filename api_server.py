"""
Wolf L12 API Server

FastAPI server for L12 verdict polling and system health monitoring.
"""

import os
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.l12_routes import router as l12_router
from context.live_context_bus import LiveContextBus
from context.runtime_state import RuntimeState
from utils.timezone_utils import format_local, format_utc, now_utc

app = FastAPI(
    title="Wolf L12 API",
    version="7.4r∞",
    description="Wolf 15-Layer Trading System - L12 Verdict API",
)

# CORS middleware for Next.js dashboard
# Configure allowed origins via environment variable in production
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET"],  # Read-only
    allow_headers=["*"],
)

app.include_router(l12_router)


def _get_feed_status() -> str:
    """
    Determine data feed status.

    Returns:
        "connected" | "disconnected" | "no_api_key"
    """
    api_key = os.getenv("FINNHUB_API_KEY", "")

    if not api_key or api_key == "YOUR_FINNHUB_API_KEY":
        return "no_api_key"

    # Check if we have recent tick data
    context_bus = LiveContextBus()
    snapshot = context_bus.snapshot()

    if snapshot.get("ticks"):
        return "connected"

    return "disconnected"


def _get_last_tick_times() -> Dict[str, Optional[str]]:
    """
    Get timestamp of last tick per symbol.

    Returns:
        Dictionary of symbol -> ISO timestamp
    """
    context_bus = LiveContextBus()
    snapshot = context_bus.snapshot()
    ticks = snapshot.get("ticks", [])

    last_ticks = {}
    for tick in reversed(ticks):
        symbol = tick.get("symbol")
        if symbol and symbol not in last_ticks:
            ts = tick.get("timestamp")
            if isinstance(ts, (int, float)):
                # Unix timestamp
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                last_ticks[symbol] = dt.isoformat()
            elif isinstance(ts, datetime):
                last_ticks[symbol] = ts.isoformat()

    return last_ticks


def _get_candle_freshness() -> Dict[str, int]:
    """
    Get age of latest candle per symbol in seconds.

    Returns:
        Dictionary of symbol -> age in seconds
    """
    context_bus = LiveContextBus()
    snapshot = context_bus.snapshot()
    candles = snapshot.get("candles", {})

    now = datetime.now(timezone.utc)
    freshness = {}

    for symbol, timeframes in candles.items():
        for tf, candle in timeframes.items():
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
    return {
        "status": "healthy",
        "service": "wolf-l12-api",
        "version": "7.4r∞",
        "latency_ms": RuntimeState.latency_ms,
        "feed_status": _get_feed_status(),
        "last_tick_at": _get_last_tick_times(),
        "candle_freshness": _get_candle_freshness(),
        "redis_status": _get_redis_status(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
