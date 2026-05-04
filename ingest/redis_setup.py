"""Redis client construction and connection with retry for ingest service.

Extracted from ingest_service.py for maintainability.
"""

from __future__ import annotations

import asyncio
import os
from importlib import import_module
from typing import Any, Protocol

from loguru import logger

from ingest.service_metrics import health_probe


class RedisClient(Protocol):
    """Async Redis client contract used by ingest service."""

    async def ping(self) -> Any: ...
    async def aclose(self) -> None: ...
    async def delete(self, name: str) -> int: ...
    async def rename(self, src: str, dst: str) -> bool: ...
    async def scan(self, cursor: int, *, match: str, count: int) -> tuple[int, list[str]]: ...
    async def llen(self, name: str) -> int: ...
    async def rpush(self, name: str, *values: str) -> int: ...
    async def ltrim(self, name: str, start: int, end: int) -> Any: ...
    async def publish(self, channel: str, message: str) -> int: ...
    async def set(self, name: str, value: str, ex: int | None = None) -> Any: ...


def build_redis_client() -> RedisClient:
    try:
        redis_asyncio = import_module("redis.asyncio")
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing dependency 'redis'. Install it with: pip install redis") from exc

    from infrastructure.redis_client import RedisConfig
    from infrastructure.redis_url import get_redis_url, get_safe_redis_url

    url = get_redis_url()
    cfg = RedisConfig.from_env()
    try:
        max_connections = int(os.getenv("INGEST_REDIS_MAX_CONNECTIONS", str(cfg.max_connections)))
    except (TypeError, ValueError):
        max_connections = cfg.max_connections
    max_connections = max(1, max_connections)

    from redis.backoff import ExponentialBackoff
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import TimeoutError as RedisTimeoutError
    from redis.retry import Retry

    retry = Retry(
        backoff=ExponentialBackoff(cap=cfg.retry_backoff_cap, base=cfg.retry_backoff_base),
        retries=cfg.retry_attempts,
        supported_errors=(RedisConnectionError, RedisTimeoutError),
    )

    logger.info(
        "Ingest Redis: {} max={} wait={}s timeout={}s",
        get_safe_redis_url(),
        max_connections,
        cfg.blocking_pool_timeout,
        cfg.socket_timeout,
    )
    pool = redis_asyncio.BlockingConnectionPool.from_url(
        url,
        decode_responses=cfg.decode_responses,
        max_connections=max_connections,
        timeout=cfg.blocking_pool_timeout,
        socket_timeout=cfg.socket_timeout,
        socket_connect_timeout=cfg.socket_connect_timeout,
        socket_keepalive=cfg.socket_keepalive,
        health_check_interval=cfg.health_check_interval,
        retry_on_timeout=cfg.retry_on_timeout,
        retry_on_error=[RedisConnectionError, RedisTimeoutError],
        retry=retry,
    )
    return redis_asyncio.Redis(connection_pool=pool)


async def connect_redis() -> RedisClient:
    redis = build_redis_client()
    try:
        await redis.ping()
    except Exception:
        await redis.aclose()
        raise
    logger.info("Redis connection validated")
    return redis


async def connect_redis_with_retry(shutdown_event: asyncio.Event | None = None) -> RedisClient:
    """Connect to Redis with bounded retry/backoff during startup."""
    max_retries = int(os.getenv("INGEST_REDIS_CONNECT_MAX_RETRIES", "15"))
    base_delay = float(os.getenv("INGEST_REDIS_CONNECT_DELAY_SEC", "2"))
    max_delay = float(os.getenv("INGEST_REDIS_CONNECT_MAX_DELAY_SEC", "10"))

    attempt = 0
    while True:
        if shutdown_event and shutdown_event.is_set():
            raise RuntimeError("shutdown_requested")

        attempt += 1
        try:
            client = await connect_redis()
            health_probe.set_detail("redis", "connected")
            health_probe.set_detail("redis_retry", str(attempt))
            return client
        except Exception as exc:
            health_probe.set_detail("redis", "connecting")
            health_probe.set_detail("redis_retry", str(attempt))

            if max_retries > 0 and attempt >= max_retries:
                logger.error(
                    "Redis connection failed after %d attempt(s): %s",
                    attempt,
                    exc,
                )
                raise

            delay = min(max_delay, base_delay * (2 ** max(0, attempt - 1)))
            logger.warning(
                "Redis not ready yet (attempt %d): %s — retrying in %.1fs",
                attempt,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
