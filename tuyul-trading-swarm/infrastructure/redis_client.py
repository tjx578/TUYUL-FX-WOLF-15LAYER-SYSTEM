"""Redis client singleton — shared across all components."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

import redis.asyncio as aioredis
import redis as syncredis
from loguru import logger


def _build_redis_url() -> str:
    """Bangun Redis URL dari env vars (kompatibel dengan Railway)."""
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        return redis_url
    host = os.getenv("REDIS_HOST", "127.0.0.1")
    port = os.getenv("REDIS_PORT", "6379")
    password = os.getenv("REDIS_PASSWORD", "")
    db = os.getenv("REDIS_DB", "0")
    if password:
        return f"redis://:{password}@{host}:{port}/{db}"
    return f"redis://{host}:{port}/{db}"


_async_redis: Optional[aioredis.Redis] = None
_sync_redis: Optional[syncredis.Redis] = None


async def get_async_redis() -> aioredis.Redis:
    """Dapatkan async Redis client (singleton)."""
    global _async_redis
    if _async_redis is None:
        url = _build_redis_url()
        _async_redis = aioredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=float(os.getenv("REDIS_SOCKET_TIMEOUT_SEC", "5")),
            socket_connect_timeout=5.0,
        )
        logger.info("Async Redis client initialized")
    return _async_redis


def get_sync_redis() -> syncredis.Redis:
    """Dapatkan sync Redis client (singleton, untuk background tasks)."""
    global _sync_redis
    if _sync_redis is None:
        url = _build_redis_url()
        _sync_redis = syncredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=float(os.getenv("REDIS_SOCKET_TIMEOUT_SEC", "5")),
        )
        logger.info("Sync Redis client initialized")
    return _sync_redis


async def ping_redis() -> bool:
    """Cek koneksi Redis."""
    try:
        r = await get_async_redis()
        return await r.ping()
    except Exception as e:
        logger.warning(f"Redis ping failed: {e}")
        return False
