"""Redis health and cache-management endpoints.

Zones: dashboard (monitoring/ops) — no market logic, no execution authority.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from fastapi import APIRouter, Depends, HTTPException, Request

from .middleware.auth import verify_token
from .middleware.governance import enforce_write_policy

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


class RedisClient(Protocol):
    async def ping(self) -> bool: ...
    async def info(self, section: str | None = None, *args: str, **kwargs: Any) -> dict[str, Any]: ...
    async def slowlog_len(self) -> int: ...
    async def scan(
        self,
        cursor: int = 0,
        match: str | None = None,
        count: int | None = None,
    ) -> tuple[int, list[Any]]: ...
    async def delete(self, *names: Any) -> int: ...


async def _delete_keys_by_pattern(r: RedisClient, pattern: str) -> int:
    """Scan for keys matching *pattern* and delete them.  Returns count deleted."""
    deleted = 0
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor=cursor, match=pattern, count=100)
        if keys:
            deleted += await r.delete(*keys)
        if cursor == 0:
            break
    return deleted


# Public alias — allows tests (and other callers) to import without the leading
# underscore while keeping the private name for internal use.
delete_keys_by_pattern = _delete_keys_by_pattern


@router.get("/health", dependencies=[Depends(verify_token)])
async def redis_health(request: Request) -> dict[str, Any]:
    """Return quick Redis diagnostics for dashboard observability."""
    r = cast(RedisClient, request.app.state.redis)
    started = datetime.now(UTC)
    try:
        pong = await r.ping()
        info = await r.info(section="stats")
        clients = await r.info(section="clients")
        slowlog_len = await r.slowlog_len()
        elapsed_ms = (datetime.now(UTC) - started).total_seconds() * 1000.0

        return {
            "status": "ok" if pong else "degraded",
            "latency_ms": round(elapsed_ms, 2),
            "connected_clients": int(clients.get("connected_clients", 0)),
            "blocked_clients": int(clients.get("blocked_clients", 0)),
            "instantaneous_ops_per_sec": int(info.get("instantaneous_ops_per_sec", 0)),
            "slowlog_len": int(slowlog_len),
            "timestamp": datetime.now(UTC).isoformat(),
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Redis health check failed: {exc}") from exc


@router.delete("/candles", dependencies=[Depends(verify_token), Depends(enforce_write_policy)])
async def flush_all_candles(request: Request) -> dict[str, Any]:
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
    r = cast(RedisClient, request.app.state.redis)
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


@router.delete("/candles/{symbol}/{timeframe}", dependencies=[Depends(verify_token), Depends(enforce_write_policy)])
async def flush_candles_for_pair(request: Request, symbol: str, timeframe: str) -> dict[str, Any]:
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

    r = cast(RedisClient, request.app.state.redis)
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
