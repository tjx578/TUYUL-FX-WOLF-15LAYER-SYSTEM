"""
Redis client factory — native async, connection management.

Zone: infrastructure/ — shared utility, no business logic.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RedisConfig:
    """Redis connection configuration."""
    host: str = "127.0.0.1"
    port: int = 6379
    password: str | None = None
    db: int = 0
    decode_responses: bool = True
    max_connections: int = 20
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0
    retry_on_timeout: bool = True
    health_check_interval: int = 30

    @classmethod
    def from_env(cls) -> RedisConfig:
        """Load config from environment variables."""
        return cls(
            host=os.environ.get("REDIS_HOST", "127.0.0.1"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            password=os.environ.get("REDIS_PASSWORD") or None,
            db=int(os.environ.get("REDIS_DB", "0")),
        )


_pool: Optional[aioredis.ConnectionPool] = None  # noqa: UP045


async def get_pool(config: RedisConfig | None = None) -> aioredis.ConnectionPool:
    """Get or create the shared connection pool."""
    global _pool
    if _pool is None:
        cfg = config or RedisConfig.from_env()
        _pool = aioredis.ConnectionPool(
            host=cfg.host,
            port=cfg.port,
            password=cfg.password,
            db=cfg.db,
            decode_responses=cfg.decode_responses,
            max_connections=cfg.max_connections,
            socket_timeout=cfg.socket_timeout,
            socket_connect_timeout=cfg.socket_connect_timeout,
            retry_on_timeout=cfg.retry_on_timeout,
            health_check_interval=cfg.health_check_interval,
        )
        logger.info("Redis pool created: %s:%d db=%d", cfg.host, cfg.port, cfg.db)
    return _pool


async def get_client(config: RedisConfig | None = None) -> aioredis.Redis:
    """Get a Redis client backed by the shared pool."""
    pool = await get_pool(config)
    return aioredis.Redis(connection_pool=pool)


async def close_pool() -> None:
    """Close the shared connection pool. Call on shutdown."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
        logger.info("Redis pool closed")
