import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from redis.retry import Retry

from infrastructure.redis_client import RedisConfig
from infrastructure.redis_url import get_redis_url


def create_redis_client() -> Redis:
    """Create an async Redis client using shared infrastructure configuration."""
    cfg = RedisConfig.from_env()
    url = get_redis_url()
    retry = Retry(
        backoff=ExponentialBackoff(cap=cfg.retry_backoff_cap, base=cfg.retry_backoff_base),
        retries=cfg.retry_attempts,
        supported_errors=(RedisConnectionError, RedisTimeoutError),
    )
    # ssl is inferred from URL scheme (rediss:// = TLS, redis:// = plain)
    pool = aioredis.BlockingConnectionPool.from_url(
        url,
        decode_responses=cfg.decode_responses,
        max_connections=cfg.max_connections,
        timeout=cfg.blocking_pool_timeout,
        retry_on_timeout=cfg.retry_on_timeout,
        retry_on_error=[RedisConnectionError, RedisTimeoutError],
        retry=retry,
        socket_connect_timeout=cfg.socket_connect_timeout,
        socket_timeout=cfg.socket_timeout,
        socket_keepalive=cfg.socket_keepalive,
        health_check_interval=cfg.health_check_interval,
    )
    return Redis(connection_pool=pool)
