from redis.asyncio import Redis

from infrastructure.redis_client import RedisConfig
from infrastructure.redis_url import get_redis_url


def create_redis_client() -> Redis:
    """Create an async Redis client using shared infrastructure configuration."""
    cfg = RedisConfig.from_env()
    url = get_redis_url()
    # ssl is inferred from URL scheme (rediss:// = TLS, redis:// = plain)
    client: Redis = Redis.from_url(  # type: ignore[no-untyped-call]
        url,
        decode_responses=cfg.decode_responses,
        max_connections=cfg.max_connections,
        retry_on_timeout=cfg.retry_on_timeout,
        socket_connect_timeout=cfg.socket_connect_timeout,
        socket_timeout=cfg.socket_timeout,
        socket_keepalive=cfg.socket_keepalive,
        health_check_interval=cfg.health_check_interval,
    )
    return client
