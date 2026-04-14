"""Sync-safe bridge for publishing candles to Redis from synchronous callbacks.

The CandleBuilder ``on_complete`` callbacks are **synchronous** (``Callable[[Candle], None]``),
but the Redis write path is async.  Previous code used bare ``loop.create_task()``
which silently dropped errors and leaked references.

This module provides ``publish_candle_sync`` — the **single correct bridge** between
a sync CandleBuilder callback and the async Redis write layer.  It:

1. Detects whether an event loop is running in the current thread.
2. If yes, schedules a tracked ``asyncio.Task`` with proper error logging.
3. If no loop is running (e.g. unit tests), silently skips — candle persistence
   is best-effort and must never block the tick pipeline.

Zone: core/ — infrastructure glue.  No analysis or execution logic.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

import orjson

logger = logging.getLogger(__name__)


def _candle_open_epoch(candle: dict) -> float | None:
    """Extract the candle open-time as epoch seconds.

    Handles both WS-built candles (``open_time`` ISO string) and
    REST-sourced candles (``timestamp`` as datetime or epoch float).
    Returns ``None`` if no usable timestamp is found.
    """
    for key in ("open_time", "timestamp", "time"):
        val = candle.get(key)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, datetime):
            return val.timestamp()
        if isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                try:
                    return datetime.fromisoformat(val).timestamp()
                except Exception:
                    continue
    return None


async def is_duplicate_candle(
    redis: Any,
    history_key: str,
    candle_dict: dict[str, Any],
    *,
    tail_size: int = 10,
) -> bool:
    """Check whether a candle with the same open-time already exists in the Redis list tail.

    Reads the last *tail_size* entries from the ``history_key`` LIST,
    deserialises them, and compares their open-time epoch with the incoming
    candle.  Returns ``True`` if a duplicate is found.

    This is intentionally cheap: it only checks the tail, not the full list.
    For the dedup use-case (preventing the same REST/WS bar from being
    appended within seconds/minutes of each other) this is sufficient.
    """
    new_epoch = _candle_open_epoch(candle_dict)
    if new_epoch is None:
        return False  # Can't dedup without a timestamp — allow write

    try:
        tail: list[bytes] = await redis.lrange(history_key, -tail_size, -1)
    except Exception:
        return False  # Redis error — allow write to avoid data loss

    for raw in tail:
        try:
            existing = orjson.loads(raw)
            existing_epoch = _candle_open_epoch(existing)
            if existing_epoch is not None and abs(existing_epoch - new_epoch) < 1.0:
                return True
        except Exception:
            continue
    return False


def _safe_epoch(candle: dict) -> float:
    """Extract epoch float from candle dict, handling ISO strings."""
    for key in ("ts_close", "close_time", "timestamp", "time"):
        val = candle.get(key)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                from datetime import datetime

                try:
                    return datetime.fromisoformat(val).timestamp()
                except Exception:
                    continue
    return time.time()


# Weak set of outstanding tasks so they aren't garbage-collected mid-flight.
# (asyncio tasks are weak-referenced by the event loop; without a strong ref
# a fire-and-forget task can be collected before it finishes.)
_background_tasks: set[asyncio.Task[None]] = set()


async def _push_candle_to_redis_safe(
    redis: Any,
    candle_dict: dict[str, Any],
    rpush_fn: Any | None = None,
) -> None:
    """Async implementation — write candle to Redis list + publish notification.

    Parameters
    ----------
    redis:
        An async Redis client instance (``redis.asyncio.Redis``).
    candle_dict:
        Normalised candle dictionary (must contain ``symbol`` and ``timeframe``).
    rpush_fn:
        Optional override for the push coroutine (used in tests).
    """

    symbol = candle_dict.get("symbol")
    timeframe = candle_dict.get("timeframe")
    if not symbol or not timeframe:
        return
    # Normalize symbol and timeframe for key consistency
    symbol = str(symbol).strip().upper()
    timeframe = str(timeframe).strip().upper()

    try:
        from core.redis_keys import candle_history, channel_candle

        key = candle_history(symbol, timeframe)

        # ── Dedup: skip if this candle's open_time already exists in tail ──
        if rpush_fn is None and await is_duplicate_candle(redis, key, candle_dict):
            logger.debug("[CandleBridgeFix] Dedup skip %s:%s — same open_time in tail", symbol, timeframe)
            return

        candle_json = orjson.dumps(candle_dict).decode("utf-8")

        if rpush_fn is not None:
            await rpush_fn(key, candle_json)
        else:
            await redis.rpush(key, candle_json)
            await redis.ltrim(key, -500, -1)

            # Write latest_candle hash so pipeline gets last_seen_ts
            from core.redis_keys import latest_candle

            lc_key = latest_candle(symbol, timeframe)
            await redis.hset(
                lc_key,
                mapping={
                    "last_seen_ts": str(_safe_epoch(candle_dict)),
                    "symbol": symbol,
                    "timeframe": timeframe,
                },
            )

            # Notify engine-side consumers via Pub/Sub
            pub_channel = channel_candle(symbol, timeframe)
            await redis.publish(pub_channel, candle_json)

        # Best-effort persistence for restart recovery
        try:
            from storage.candle_persistence import enqueue_candle_dict

            enqueue_candle_dict(candle_dict)
        except Exception:
            pass
    except Exception as exc:
        logger.warning("[CandleBridgeFix] Redis push failed for %s:%s — %s", symbol, timeframe, exc)


def publish_candle_sync(
    candle_dict: dict[str, Any],
    redis: Any,
) -> None:
    """Sync-safe entry point: schedule a Redis candle push from a sync callback.

    Safe to call from CandleBuilder ``on_complete`` callbacks.  If there is
    no running event loop (unit tests, pure-sync contexts) the call is a
    silent no-op.

    Parameters
    ----------
    candle_dict:
        Normalised candle dict — must have at least ``symbol`` and ``timeframe``.
    redis:
        Async Redis client.  Must be provided — the caller is responsible for
        passing the shared pool-backed client so connections are reused rather
        than created per-candle.
    """
    if redis is None:
        logger.warning("[CandleBridgeFix] redis client is None — candle push skipped")
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop — skip silently (e.g. unit tests).
        return

    async def _do_push() -> None:
        await _push_candle_to_redis_safe(redis, candle_dict)

    task = loop.create_task(_do_push(), name="candle_bridge_push")
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
