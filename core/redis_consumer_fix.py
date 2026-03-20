"""Type-aware Redis candle reader and key sanitiser for wolf15-engine.

Zone: core/ — shared utilities, no execution side-effects.

Problem solved
--------------
Redis keys ``wolf15:candle:{sym}:{tf}`` are HASH (HSET by RedisContextBridge),
while ``wolf15:candle_history:{sym}:{tf}`` are LIST (RPUSH by ingest).
Blindly calling LRANGE on a HASH key triggers ``WRONGTYPE`` errors and
the warmup silently fails.  The functions here check the key TYPE
*before* issuing a read command so we never send a wrong-type operation.

Provides
--------
- ``get_bars_fixed``              — type-aware multi-source bar reader
- ``sanitize_redis_keys``         — delete keys whose type conflicts with TYPE_MAP
- ``seed_historical_candles_fixed`` — type-safe candle seeder (Finnhub REST)
"""

from __future__ import annotations

from typing import Any

import orjson
from loguru import logger
from redis.asyncio import Redis as AsyncRedis

from core.redis_keys import (
    CANDLE_HISTORY_MAXLEN,
    TYPE_MAP,
    candle_history,
    candle_history_temp,
    latest_candle,
)

__all__ = [
    "get_bars_fixed",
    "sanitize_redis_keys",
    "seed_historical_candles_fixed",
]


# ──────────────────────────────────────────────────────────────────────
#  Internal helpers
# ──────────────────────────────────────────────────────────────────────


async def _get_key_type(redis: AsyncRedis, key: str) -> str:
    """Return normalised Redis type string for *key* ('none' if absent)."""
    try:
        raw: bytes | str = await redis.type(key)  # redis.asyncio ResponseT
        if isinstance(raw, bytes | bytearray):
            return raw.decode().lower()
        return str(raw).lower()
    except Exception:
        return "none"


def _parse_candle_entries(raw_entries: list[Any]) -> list[dict[str, Any]]:
    """Parse a list of JSON blobs into candle dicts, skipping malformed items."""
    candles: list[dict[str, Any]] = []
    for raw in raw_entries:
        try:
            data = orjson.loads(raw)
            if isinstance(data, dict):
                candles.append(data)
        except Exception:
            pass
    return candles


# ──────────────────────────────────────────────────────────────────────
#  get_bars_fixed — proactive TYPE check before access
# ──────────────────────────────────────────────────────────────────────


async def get_bars_fixed(
    redis: AsyncRedis,
    symbol: str,
    timeframe: str,
    required: int = 5,
) -> list[dict[str, Any]]:
    """Type-aware bar reader.

    Checks ``TYPE`` before calling ``LRANGE`` / ``HGETALL`` so we never
    send a list command to a hash key (WRONGTYPE).

    Priority:
      1. ``wolf15:candle_history:{sym}:{tf}`` (LIST)
      2. ``candle_history:{sym}:{tf}`` (LIST — legacy unprefixed)
      3. ``wolf15:candle:{sym}:{tf}`` (HASH — single latest candle fallback)
    """
    # ── Priority 1: canonical list key ──
    list_key = candle_history(symbol, timeframe)
    key_type = await _get_key_type(redis, list_key)

    if key_type == "list":
        raw = await redis.lrange(list_key, -required, -1)  # type: ignore[misc]  # redis.asyncio ResponseT
        if raw:
            return _parse_candle_entries(raw)
    elif key_type not in ("none",):
        logger.warning(
            "get_bars_fixed: %s is %s (expected list) — skipping",
            list_key,
            key_type,
        )

    # ── Priority 2: unprefixed legacy key ──
    legacy_key = f"candle_history:{symbol}:{timeframe}"
    key_type = await _get_key_type(redis, legacy_key)

    if key_type == "list":
        raw = await redis.lrange(legacy_key, -required, -1)  # type: ignore[misc]  # redis.asyncio ResponseT
        if raw:
            return _parse_candle_entries(raw)
    elif key_type not in ("none",):
        logger.warning(
            "get_bars_fixed: %s is %s (expected list) — skipping",
            legacy_key,
            key_type,
        )

    # ── Priority 3: hash fallback (latest single candle) ──
    hash_key = latest_candle(symbol, timeframe)
    key_type = await _get_key_type(redis, hash_key)

    if key_type == "hash":
        data = await redis.hgetall(hash_key)  # type: ignore[misc]  # redis.asyncio ResponseT
        if data:
            raw_json = data.get(b"data") or data.get("data")
            if raw_json:
                # Inject last_seen_ts for freshness metadata (P0-3)
                last_seen = data.get(b"last_seen_ts") or data.get("last_seen_ts")
                if last_seen:
                    try:
                        candle_dict = orjson.loads(raw_json)
                        ts_str = last_seen if isinstance(last_seen, str) else last_seen.decode("utf-8")
                        candle_dict["last_seen_ts"] = float(ts_str)
                        raw_json = orjson.dumps(candle_dict)
                    except Exception:
                        pass
                return _parse_candle_entries([raw_json])

    return []


# ──────────────────────────────────────────────────────────────────────
#  sanitize_redis_keys — proactive type-conflict cleanup
# ──────────────────────────────────────────────────────────────────────


async def sanitize_redis_keys(redis: AsyncRedis) -> int:
    """Delete keys whose Redis type conflicts with TYPE_MAP expectations.

    Uses SCAN (not KEYS) to avoid blocking on large keyspaces.
    Returns the number of keys deleted.
    """
    total_deleted = 0

    for pattern, expected_type in TYPE_MAP.items():
        try:
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
                for key_raw in keys:
                    key_str = key_raw.decode() if isinstance(key_raw, bytes | bytearray) else str(key_raw)
                    actual = await _get_key_type(redis, key_str)
                    if actual in ("none", expected_type):
                        continue
                    logger.warning(
                        "[sanitize] %s type=%s expected=%s → deleting",
                        key_str,
                        actual,
                        expected_type,
                    )
                    try:
                        await redis.delete(key_str)
                        total_deleted += 1
                    except Exception as exc:
                        logger.error("[sanitize] Failed to delete '%s': %s", key_str, exc)
                if cursor == 0:
                    break
        except Exception as exc:
            logger.warning("[sanitize] scan for %s failed: %s", pattern, exc)

    if total_deleted:
        logger.info("[sanitize] Cleaned %d conflicting key(s)", total_deleted)
    else:
        logger.debug("[sanitize] No type conflicts found")

    return total_deleted


# ──────────────────────────────────────────────────────────────────────
#  seed_historical_candles_fixed — type-safe candle seeder
# ──────────────────────────────────────────────────────────────────────


async def seed_historical_candles_fixed(
    redis_client: AsyncRedis,
    finnhub_client: Any,
    pairs: list[str],
    bars_needed: int = 50,
) -> dict[str, int]:
    """Type-safe candle seeder.

    1. Sanitise conflicting keys first.
    2. Fetch candles from Finnhub REST via *finnhub_client*.
    3. Atomic-swap into ``wolf15:candle_history:{sym}:M15``.

    Returns ``{symbol: bars_seeded}`` mapping.
    """
    await sanitize_redis_keys(redis_client)

    seeded: dict[str, int] = {}
    for symbol in pairs:
        try:
            candles = await _fetch_candles_from_finnhub(finnhub_client, symbol, bars_needed)
            if not candles:
                continue

            key = candle_history(symbol, "M15")

            # Ensure key is list (should be after sanitise, but double-check)
            key_type = await _get_key_type(redis_client, key)
            if key_type not in ("none", "list"):
                logger.warning(
                    "[seed] %s is %s after sanitise — force-deleting",
                    key,
                    key_type,
                )
                await redis_client.delete(key)

            # Atomic swap via temp key
            tmp_key = candle_history_temp(symbol, "M15")
            await redis_client.delete(tmp_key)

            entries = [orjson.dumps(c) for c in candles]
            for i in range(0, len(entries), 50):
                chunk = entries[i : i + 50]
                await redis_client.rpush(tmp_key, *chunk)  # type: ignore[misc]  # redis.asyncio ResponseT

            await redis_client.rename(tmp_key, key)
            # Trim to max history length
            await redis_client.ltrim(key, -CANDLE_HISTORY_MAXLEN, -1)  # type: ignore[misc]  # redis.asyncio ResponseT

            seeded[symbol] = len(candles)
            logger.info("[seed] %s: %d M15 candles seeded", symbol, len(candles))
        except Exception as exc:
            logger.error("[seed] Failed to seed %s: %s", symbol, exc)

    return seeded


async def _fetch_candles_from_finnhub(
    client: Any,
    symbol: str,
    count: int,
) -> list[dict[str, Any]]:
    """Fetch historical candles from Finnhub via the client's REST interface.

    Supports both ``FinnhubCandleFetcher`` instances and generic clients
    by duck-typing their API surface.
    """
    try:
        if hasattr(client, "fetch_candles"):
            return await client.fetch_candles(symbol, count=count)
        if hasattr(client, "warmup"):
            results = await client.warmup(symbols=[symbol])
            return results.get(symbol, {}).get("M15", [])
    except Exception as exc:
        logger.warning("[seed] Finnhub fetch for %s failed: %s", symbol, exc)
    return []
