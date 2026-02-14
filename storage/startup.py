"""Startup helpers for persistent PostgreSQL backup services."""

from __future__ import annotations

import asyncio

from loguru import logger

from storage.persistence_sync import PersistenceSync
from storage.postgres_client import pg_client
from storage.redis_client import RedisClient

_sync_service: PersistenceSync | None = None
_sync_task: asyncio.Task[None] | None = None


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
    if not redis.get("wolf15:peak_equity"):
        logger.warning("Redis appears empty; attempting recovery from PostgreSQL")
        recovery_service = PersistenceSync(pg=pg_client, redis=redis)
        await recovery_service.recover_from_postgres()

    _sync_service = PersistenceSync(interval_sec=30.0, pg=pg_client, redis=redis)
    _sync_task = asyncio.create_task(_sync_service.run())
    logger.info("Persistent storage initialized")
    return _sync_service


async def shutdown_persistent_storage() -> None:
    """Stop sync service and close PostgreSQL pool."""
    global _sync_service, _sync_task

    if _sync_service is not None:
        await _sync_service.stop()
        _sync_service = None

    if _sync_task is not None:
        _sync_task.cancel()
        try:
            await _sync_task
        except asyncio.CancelledError:
            pass
        _sync_task = None

    await pg_client.close()


def get_sync_service() -> PersistenceSync | None:
    """Return active sync service instance."""
    return _sync_service
