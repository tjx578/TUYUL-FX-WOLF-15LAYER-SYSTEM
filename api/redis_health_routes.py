"""
TUYUL FX Wolf-15 — Redis Observability & Cache-Management Endpoints
====================================================================
GET    /api/v1/redis/health                          — PING latency, connected/blocked clients,
                                                       ops/sec, slowlog length.
DELETE /api/v1/redis/candles                         — Flush all candle-cache keys (selective;
                                                       safe for fresh deploy).
DELETE /api/v1/redis/candles/{symbol}/{timeframe}    — Flush candle-cache keys for a specific
                                                       symbol+timeframe pair.

Used to diagnose TCP_OVERWINDOW root cause:
  - High ``blocked_clients``  → consumer-starvation (event-loop blockage)
  - Rising ``latency_ms``     → Redis backpressure or slow operations
  - High ``slowlog_len``      → expensive commands stalling the Redis server

All reads go through ``request.app.state.redis`` (the lifecycle-managed async
pool seeded in the FastAPI lifespan), so this endpoint never creates a new
connection.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/redis", tags=["redis"])

# All key prefixes that hold candle data (must stay in sync with context/redis_consumer.py)
_CANDLE_KEY_PREFIXES: tuple[str, ...] = (
    "wolf15:candle_history",
    "candle_history",
    "wolf15:candle",
    "candles",
)

# Validation patterns — symbols are 3–10 uppercase alphanumeric chars;
# timeframes are letters + optional digits (e.g. M1, M15, H1, H4, D1, W1, MN).
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,10}$")
_TIMEFRAME_RE = re.compile(r"^[A-Z]{1,2}[0-9]{0,2}$")


async def _delete_keys_by_pattern(r: aioredis.Redis, pattern: str) -> int:
    """Scan for keys matching *pattern* and delete them.  Returns count deleted."""
    deleted = 0
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor=cursor, match=pattern, count=100)  # type: ignore[misc]
        if keys:
            deleted += await r.delete(*keys)
        if cursor == 0:
            break
    return deleted


@router.get("/health")
async def redis_health(request: Request) -> dict:
    """Redis connectivity and server stats for TCP_OVERWINDOW diagnostics.

    Returns:
        status, latency_ms, blocked_clients, connected_clients,
        ops_per_sec, slowlog_len, checked_at
    """
    r: aioredis.Redis = request.app.state.redis

    t0 = datetime.now(UTC)
    await r.ping()
    latency_ms = (datetime.now(UTC) - t0).total_seconds() * 1000

    clients: dict = await r.info(section="clients")  # type: ignore[assignment]
    stats: dict = await r.info(section="stats")  # type: ignore[assignment]

    try:
        slowlog_len: int | None = await r.slowlog_len()
    except Exception:
        slowlog_len = None

    return {
        "status": "ok",
        "latency_ms": round(latency_ms, 2),
        "blocked_clients": clients.get("blocked_clients"),
        "connected_clients": clients.get("connected_clients"),
        "ops_per_sec": stats.get("instantaneous_ops_per_sec"),
        "slowlog_len": slowlog_len,
        "checked_at": datetime.now(UTC).isoformat(),
    }


@router.delete("/candles")
async def flush_all_candles(request: Request) -> dict:
    """Delete all candle-cache keys from Redis.

    Scans for every key that matches the known candle-cache prefixes
    (``wolf15:candle_history:*``, ``candle_history:*``, ``wolf15:candle:*``,
    ``candles:*``) and removes them.

    This is the programmatic equivalent of running::

        DEL candles:EURUSD:M15
        DEL candles:GBPUSD:M15
        ...

    for every active pair, but covers all known key namespaces at once.

    Returns:
        status, deleted_count, flushed_at
    """
    r: aioredis.Redis = request.app.state.redis
    total_deleted = 0
    for prefix in _CANDLE_KEY_PREFIXES:
        count = await _delete_keys_by_pattern(r, f"{prefix}:*")
        if count:
            logger.info("flush_all_candles: deleted %d keys with prefix '%s'", count, prefix)
        total_deleted += count

    logger.info("flush_all_candles: total keys deleted=%d", total_deleted)
    return {
        "status": "ok",
        "deleted_count": total_deleted,
        "flushed_at": datetime.now(UTC).isoformat(),
    }


@router.delete("/candles/{symbol}/{timeframe}")
async def flush_candles_for_pair(request: Request, symbol: str, timeframe: str) -> dict:
    """Delete candle-cache keys for a specific symbol and timeframe.

    Removes keys of the form ``<prefix>:{symbol}:{timeframe}`` across all
    known candle-cache namespaces.  Equivalent to::

        DEL wolf15:candle_history:EURUSD:M15
        DEL candle_history:EURUSD:M15
        DEL wolf15:candle:EURUSD:M15
        DEL candles:EURUSD:M15

    Args:
        symbol:    Trading pair symbol, e.g. ``EURUSD``.
        timeframe: Timeframe label, e.g. ``M15``.

    Returns:
        status, symbol, timeframe, deleted_count, flushed_at
    """
    symbol = symbol.upper().strip()
    timeframe = timeframe.upper().strip()

    if not _SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=422, detail=f"Invalid symbol: {symbol!r}")
    if not _TIMEFRAME_RE.match(timeframe):
        raise HTTPException(status_code=422, detail=f"Invalid timeframe: {timeframe!r}")

    r: aioredis.Redis = request.app.state.redis
    keys_to_delete = [f"{prefix}:{symbol}:{timeframe}" for prefix in _CANDLE_KEY_PREFIXES]
    deleted: int = await r.delete(*keys_to_delete)

    if deleted == 0:
        logger.debug(
            "flush_candles_for_pair: no keys found for symbol=%s tf=%s",
            symbol, timeframe,
        )
    logger.info(
        "flush_candles_for_pair: symbol=%s tf=%s deleted=%d",
        symbol, timeframe, deleted,
    )
    return {
        "status": "ok",
        "symbol": symbol,
        "timeframe": timeframe,
        "deleted_count": deleted,
        "flushed_at": datetime.now(UTC).isoformat(),
    }
