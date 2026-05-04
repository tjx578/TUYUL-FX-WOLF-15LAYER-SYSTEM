"""
Redis client factory — native async, connection pool management.

TUYUL FX v2 Architecture:
------------------------------------------------------------
• Redis is a first-class architecture component: stream bridge, context sync, heartbeat, fanout, and durability.
• Not just transport — Redis coordinates multi-container pub/sub, cross-service context, verdict sync, producer heartbeat, and recovery snapshots.
• Redis is the primary bridge for low-latency state, history, and freshness tracking across ingest, analysis, execution, and dashboard services.
• All durability, fanout, and recovery logic is handled via Redis Streams, Lists, and Pub/Sub (see infrastructure/redis/stream_publisher.py, stream_consumer.py).
• Heartbeat and freshness lane: Redis stores producer heartbeat, last_seen timestamps, and readiness checks for all critical data (tick, candle, verdict).
• Readiness = fresh data present, not just process alive; explicit freshness checks and heartbeat tracking for all producers/consumers.
• Redis is the authoritative context sync for multi-service orchestration, not just a message bus.

Key design: uses redis.asyncio natively. No run_in_executor anywhere.

Config source: REDIS_URL (via infrastructure.redis_url) — identical to the sync RedisClient in storage/redis_client.py.  This eliminates the duplicate config-source problem (I1: two clients potentially connecting to different servers) and ensures Railway/Docker deployments work with just REDIS_URL without requiring separate REDIS_HOST/REDIS_PORT env vars (I2).

Priority for connection target:
    1. REDIS_URL  (Railway / Docker / production — single source of truth)
    2. Individual REDIS_HOST / REDIS_PORT / REDIS_PASSWORD / REDIS_DB overrides
    3. localhost:6379 dev fallback
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlsplit

import redis.asyncio as aioredis
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from redis.retry import Retry

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float, *, minimum: float | None = None) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid %s=%r; using default %.2f", name, raw, default)
        return default
    if minimum is not None:
        return max(minimum, value)
    return value


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid %s=%r; using default %d", name, raw, default)
        return default
    if minimum is not None:
        return max(minimum, value)
    return value


@dataclass(frozen=True)
class RedisConfig:
    """
    Redis connection configuration.

    ``host``, ``port``, ``password``, ``db`` are resolved by ``from_env()``
    with REDIS_URL as the primary source; they are also used by
    ``RedisClientManager.get_pool()`` for introspection / logging.
    Pool-tuning knobs (max_connections, timeouts) are always taken from this
    object regardless of how the pool is constructed.
    """

    host: str = "127.0.0.1"
    port: int = 6379
    password: str | None = None
    db: int = 0
    decode_responses: bool = True
    max_connections: int = 50
    socket_timeout: float = 15.0
    socket_connect_timeout: float = 10.0
    retry_on_timeout: bool = True
    health_check_interval: int = 30
    socket_keepalive: bool = True
    retry_attempts: int = 5
    retry_backoff_base: float = 1.0
    retry_backoff_cap: float = 10.0
    blocking_pool_timeout: float = 5.0

    @classmethod
    def from_env(cls) -> RedisConfig:
        """
        Resolve connection config from the environment.

        Priority:
          1. REDIS_URL  (via infrastructure.redis_url — Railway/Docker/prod)
          2. Individual REDIS_HOST / REDIS_PORT / REDIS_PASSWORD / REDIS_DB
             overrides (backward-compat; these take precedence over the URL
             components when explicitly set).
          3. localhost:6379 dev fallback.
        """
        from infrastructure.redis_url import get_redis_url  # avoid circular at module level

        url = get_redis_url()
        parts = urlsplit(url)

        # URL-derived defaults
        url_host = parts.hostname or "localhost"
        url_port = int(parts.port or 6379)
        url_password = parts.password or None
        raw_db = (parts.path or "/0").lstrip("/") or "0"
        url_db = int(raw_db)

        # Individual env vars override URL-derived values (backward-compat)
        # Also check Railway-style vars (REDISHOST, etc.) as secondary fallback
        host = os.environ.get("REDIS_HOST") or os.environ.get("REDISHOST") or url_host
        port = int(os.environ.get("REDIS_PORT") or os.environ.get("REDISPORT") or url_port)
        password = os.environ.get("REDIS_PASSWORD") or os.environ.get("REDISPASSWORD") or url_password or None
        db = int(os.environ.get("REDIS_DB") or url_db)

        # Normalise empty string password to None
        if password == "":
            password = None

        # Pool and TCP tuning. These defaults intentionally prefer modest
        # backpressure over failing fast when a short Redis burst checks out
        # every pooled connection.
        socket_timeout = _env_float("REDIS_SOCKET_TIMEOUT_SEC", cls.socket_timeout, minimum=1.0)
        socket_connect_timeout = _env_float(
            "REDIS_SOCKET_CONNECT_TIMEOUT_SEC",
            cls.socket_connect_timeout,
            minimum=1.0,
        )
        max_connections = _env_int("REDIS_MAX_CONNECTIONS", cls.max_connections, minimum=1)
        health_check_interval = _env_int(
            "REDIS_HEALTH_CHECK_INTERVAL_SEC",
            cls.health_check_interval,
            minimum=1,
        )
        retry_attempts = _env_int("REDIS_RETRY_ATTEMPTS", cls.retry_attempts, minimum=0)
        retry_backoff_base = _env_float("REDIS_RETRY_BACKOFF_BASE_SEC", cls.retry_backoff_base, minimum=0.1)
        retry_backoff_cap = _env_float("REDIS_RETRY_BACKOFF_CAP_SEC", cls.retry_backoff_cap, minimum=0.1)
        blocking_pool_timeout = _env_float("REDIS_POOL_TIMEOUT_SEC", cls.blocking_pool_timeout, minimum=0.1)

        return cls(
            host=host,
            port=port,
            password=password,
            db=db,
            max_connections=max_connections,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            retry_on_timeout=_env_bool("REDIS_RETRY_ON_TIMEOUT", cls.retry_on_timeout),
            health_check_interval=health_check_interval,
            socket_keepalive=_env_bool("REDIS_SOCKET_KEEPALIVE", cls.socket_keepalive),
            retry_attempts=retry_attempts,
            retry_backoff_base=retry_backoff_base,
            retry_backoff_cap=retry_backoff_cap,
            blocking_pool_timeout=blocking_pool_timeout,
        )


class RedisClientManager:
    """
    Manages a shared async Redis connection pool.

    Thread-safe singleton pattern for the connection pool.
    All methods are native async — no run_in_executor.

    The pool is created with ``BlockingConnectionPool.from_url()`` so callers
    wait briefly for an available connection instead of failing immediately
    during short bursts. Both async and sync clients resolve the same Redis
    URL and expose matching pool-tuning environment variables.
    """

    def __init__(self) -> None:
        super().__init__()
        self._pool: aioredis.ConnectionPool | None = None
        self._config: RedisConfig | None = None

    async def get_pool(self, config: RedisConfig | None = None) -> aioredis.ConnectionPool:
        if self._pool is None:
            from infrastructure.redis_url import get_redis_url  # avoid circular at module level

            cfg = config or RedisConfig.from_env()
            self._config = cfg
            url = get_redis_url()
            use_tls = url.startswith("rediss://")

            # Retry with exponential backoff on connection errors and timeouts.
            # This mirrors the tenacity retry logic in storage/redis_client.py
            # but uses redis-py's native Retry mechanism which works at the
            # connection level (retries inside parse_response / send_command).
            retry = Retry(
                backoff=ExponentialBackoff(cap=cfg.retry_backoff_cap, base=cfg.retry_backoff_base),
                retries=cfg.retry_attempts,
                supported_errors=(RedisConnectionError, RedisTimeoutError),
            )

            self._pool = aioredis.BlockingConnectionPool.from_url(
                url,
                decode_responses=cfg.decode_responses,
                max_connections=cfg.max_connections,
                timeout=cfg.blocking_pool_timeout,
                socket_timeout=cfg.socket_timeout,
                socket_connect_timeout=cfg.socket_connect_timeout,
                retry_on_timeout=cfg.retry_on_timeout,
                retry_on_error=[RedisConnectionError, RedisTimeoutError],
                retry=retry,
                health_check_interval=cfg.health_check_interval,
                socket_keepalive=cfg.socket_keepalive,
            )
            logger.info(
                (
                    "Redis async pool created: %s:%d db=%d "
                    "(blocking_pool, max=%d, wait=%.1fs, socket_timeout=%.1fs, "
                    "connect_timeout=%.1fs, tls=%s, retries=%d)"
                ),
                cfg.host,
                cfg.port,
                cfg.db,
                cfg.max_connections,
                cfg.blocking_pool_timeout,
                cfg.socket_timeout,
                cfg.socket_connect_timeout,
                use_tls,
                cfg.retry_attempts,
            )
        return self._pool

    async def get_client(self, config: RedisConfig | None = None) -> aioredis.Redis:
        pool = await self.get_pool(config)
        return aioredis.Redis(connection_pool=pool)

    async def reset_pool(self) -> None:
        """Tear down and recreate the pool on next access.

        Call this when the pool is suspected to be fully stale (e.g. after
        repeated ConnectionError even with retries).
        """
        cfg = self._config
        if self._pool is not None:
            try:  # noqa: SIM105
                await self._pool.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._pool = None
            logger.warning("Redis async pool reset — will reconnect on next use")
        # Pre-warm a new pool so the next caller doesn't pay the latency
        if cfg is not None:
            await self.get_pool(cfg)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
            logger.info("Redis async pool closed")

    async def health_check(self) -> bool:
        try:
            client = await self.get_client()
            # redis-py async stub incorrectly types ping() as bool; at runtime it's a coroutine
            result = cast(bool, await client.ping())  # type: ignore[misc]
            return result
        except Exception:
            logger.warning("Redis health check failed")
            return False


# Module-level default manager
_manager = RedisClientManager()


async def get_client(config: RedisConfig | None = None) -> aioredis.Redis:
    """Get an async Redis client from the shared pool."""
    return await _manager.get_client(config)


async def close_pool() -> None:
    """Close the shared async connection pool. Call during app shutdown."""
    await _manager.close()


# ── FastAPI dependency ────────────────────────────────────────────────────────


async def get_async_redis() -> aioredis.Redis:
    """FastAPI ``Depends()`` provider for the shared async Redis client.

    Usage in route modules::

        from fastapi import Depends
        from infrastructure.redis_client import get_async_redis
        import redis.asyncio as aioredis

        @router.get("/example")
        async def example(r: aioredis.Redis = Depends(get_async_redis)):
            value = await r.get("key")
            ...

    This replaces per-request ``redis_lib.from_url()`` calls that created
    a new sync connection on every request.
    """
    return await _manager.get_client()
