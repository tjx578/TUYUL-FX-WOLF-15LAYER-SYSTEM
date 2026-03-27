"""Startup helpers for persistent PostgreSQL backup services."""

from __future__ import annotations

import asyncio
import contextlib

from loguru import logger

from core.redis_keys import CANDLE_HISTORY_SCAN, PEAK_EQUITY
from storage.persistence_sync import PersistenceSync
from storage.postgres_client import pg_client
from storage.redis_client import RedisClient

_sync_service: PersistenceSync | None = None
_sync_task: asyncio.Task[None] | None = None


def _has_candle_data(redis: RedisClient) -> bool:
    """Return True if Redis holds any candle history keys.

    Uses ``SCAN`` to avoid blocking the server.  A single key is sufficient
    to conclude that candle data survived the restart.
    Returns False on Redis errors so callers can fall back to PostgreSQL recovery.
    """
    try:
        cursor = 0
        while True:
            cursor, keys = redis.client.scan(cursor, match=CANDLE_HISTORY_SCAN, count=20)
            if keys:
                return True
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning("Failed to scan Redis for candle data — assuming empty: {}", exc)
        logger.warning("Failed to scan Redis for candle data; assuming empty: {}", exc)
        return False
    return False


async def init_persistent_storage() -> PersistenceSync | None:
    """Initialize PostgreSQL and start sync service if configured."""
    global _sync_service, _sync_task

    try:
        await pg_client.initialize()
    except Exception as exc:
        logger.warning(f"PostgreSQL init failed; continuing without durable backup: {exc}")
        return None

    if not pg_client.is_available:
        return None

    redis = RedisClient()
    try:
        has_candles = await _has_candle_data(redis)
        has_risk_data = bool(redis.get(PEAK_EQUITY))

        if not has_candles and not has_risk_data:
            logger.warning("Redis truly empty (no candle history, no risk state); attempting recovery from PostgreSQL")
            recovery_service = PersistenceSync(pg=pg_client, redis=redis)
            await recovery_service.hydrate_redis_from_postgres(mode="full")
        elif not has_risk_data:
            logger.info("Redis has candle data but missing peak_equity — risk state only recovery from PostgreSQL")
            recovery_service = PersistenceSync(pg=pg_client, redis=redis)
            await recovery_service.hydrate_redis_from_postgres(mode="risk_only")
        else:
            logger.info("Redis has existing data — skipping PostgreSQL recovery")
    except Exception as exc:
        logger.warning(f"Redis unavailable during PG sync init; skipping recovery: {exc}")

    try:
        _sync_service = PersistenceSync(interval_sec=30.0, pg=pg_client, redis=redis)
        _sync_task = asyncio.create_task(_sync_service.run())
        logger.info("Persistent storage initialized")
    except Exception as exc:
        logger.warning(f"Persistence sync startup failed: {exc}")
        return None

    # Start OHLC candle persistence flush loop
    try:
        from storage.candle_persistence import start_candle_persistence

        await start_candle_persistence()
    except Exception as exc:
        logger.warning(f"Candle persistence startup failed: {exc}")

    return _sync_service


async def shutdown_persistent_storage() -> None:
    """Stop sync service and close PostgreSQL pool."""
    global _sync_service, _sync_task

    if _sync_service is not None:
        await _sync_service.stop()
        _sync_service = None

    if _sync_task is not None:
        _sync_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _sync_task
        _sync_task = None

    # Stop OHLC candle persistence
    try:
        from storage.candle_persistence import stop_candle_persistence

        await stop_candle_persistence()
    except Exception:
        pass

    await pg_client.close()


def get_sync_service() -> PersistenceSync | None:
    """Return active sync service instance."""
    return _sync_service
