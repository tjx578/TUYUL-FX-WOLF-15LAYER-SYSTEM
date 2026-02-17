"""
Redis client factory — native async, connection pool management.

Zone: infrastructure/ — shared utility, no business logic.

Key design: uses redis.asyncio natively. No run_in_executor anywhere.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

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
        return cls(
            host=os.environ.get("REDIS_HOST", "127.0.0.1"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            password=os.environ.get("REDIS_PASSWORD") or None,
            db=int(os.environ.get("REDIS_DB", "0")),
        )


class RedisClientManager:
    """
    Manages a shared async Redis connection pool.

    Thread-safe singleton pattern for the connection pool.
    All methods are native async — no run_in_executor.
    """

    def __init__(self) -> None:
        self._pool: aioredis.ConnectionPool | None = None
        self._config: RedisConfig | None = None

    async def get_pool(self, config: RedisConfig | None = None) -> aioredis.ConnectionPool:
        if self._pool is None:
            cfg = config or RedisConfig.from_env()
            self._config = cfg
            self._pool = aioredis.ConnectionPool(
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
            logger.info(
                "Redis async pool created: %s:%d db=%d (native async, no executor)",
                cfg.host, cfg.port, cfg.db,
            )
        return self._pool

    async def get_client(self, config: RedisConfig | None = None) -> aioredis.Redis:
        pool = await self.get_pool(config)
        return aioredis.Redis(connection_pool=pool)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
            logger.info("Redis async pool closed")

    async def health_check(self) -> bool:
        try:
            client = await self.get_client()
            return await client.ping() # pyright: ignore[reportGeneralTypeIssues]
        except Exception:
            logger.warning("Redis health check failed")
            return False


# Module-level default manager
_manager = RedisClientManager()


async def get_client(config: RedisConfig | None = None) -> aioredis.Redis:
    """Get an async Redis client from the shared pool."""
    return await _manager.get_client(config)


async def close_pool() -> None:
    """Close the shared pool. Call on application shutdown."""
    await _manager.close()
