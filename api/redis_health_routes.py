"""Redis health and cache-management endpoints.

Zones: dashboard (monitoring/ops) — no market logic, no execution authority.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Request

router = APIRouter(prefix="/api/v1/redis", tags=["redis"])

# ---------------------------------------------------------------------------
# Candle-cache key prefixes known to this system
# ---------------------------------------------------------------------------

CANDLE_KEY_PREFIXES: list[str] = [
    "candles",
    "candle_cache",
    "ohlcv",
]

_SYMBOL_RE = re.compile(r"^[A-Z0-9]+$")
_TIMEFRAME_RE = re.compile(r"^[A-Z][0-9]+$")


# ---------------------------------------------------------------------------
# Public helper — used by routes and exposed for unit testing
# ---------------------------------------------------------------------------


async def delete_keys_by_pattern(redis: Any, pattern: str) -> int:
    """Scan Redis for *pattern* and delete all matching keys.

    Returns the total number of keys deleted.
    """
    cursor: int = 0
    deleted: int = 0

    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        if keys:
            deleted += await redis.delete(*keys)
        if cursor == 0:
            break

    return deleted


# ---------------------------------------------------------------------------
# DELETE /api/v1/redis/candles — flush ALL candle keys
# ---------------------------------------------------------------------------


@router.delete("/candles")
async def flush_all_candles(request: Request) -> dict[str, Any]:
    """Delete every candle-cache key across all known prefixes."""
    redis = request.app.state.redis
    total_deleted: int = 0

    for prefix in CANDLE_KEY_PREFIXES:
        total_deleted += await delete_keys_by_pattern(redis, f"{prefix}:*")

    return {
        "status": "ok",
        "deleted_count": total_deleted,
        "flushed_at": datetime.now(UTC).isoformat(),
    }


# ---------------------------------------------------------------------------
# DELETE /api/v1/redis/candles/{symbol}/{timeframe} — flush specific pair
# ---------------------------------------------------------------------------


@router.delete("/candles/{symbol}/{timeframe}")
async def flush_pair_candles(
    request: Request,
    symbol: str = Path(...),
    timeframe: str = Path(...),
) -> dict[str, Any]:
    """Delete all candle-cache keys for a specific symbol + timeframe."""
    symbol = symbol.upper()
    timeframe = timeframe.upper()

    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=422, detail=f"Invalid symbol: {symbol!r}")
    if not _TIMEFRAME_RE.match(timeframe):
        raise HTTPException(status_code=422, detail=f"Invalid timeframe: {timeframe!r}")

    redis = request.app.state.redis

    keys = [f"{prefix}:{symbol}:{timeframe}" for prefix in CANDLE_KEY_PREFIXES]
    deleted: int = await redis.delete(*keys)

    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        "deleted_count": deleted,
        "flushed_at": datetime.now(UTC).isoformat(),
    }
