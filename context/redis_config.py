import redis.asyncio as aioredis

from infrastructure.redis_client import RedisConfig
from infrastructure.redis_url import get_redis_url


def create_redis_client() -> aioredis.Redis:
    """Create an async Redis client using shared infrastructure configuration.

    Delegates to :class:`infrastructure.redis_client.RedisConfig` so that all
    Redis clients in the process share the same connection parameters and URL
    source (``infrastructure.redis_url.get_redis_url``), eliminating the
    duplicate-config problem where ``context/`` and ``infrastructure/`` could
    silently connect to different Redis instances.

    TCP_OVERWINDOW mitigation:
      - Keepalive enabled (SO_KEEPALIVE) to prune stale connections.
      - health_check_interval prunes idle conns before they accumulate.
      - Detailed keepalive timing delegated to Redis server-side
        ``--tcp-keepalive`` to avoid EINVAL on container runtimes.
    """
    cfg = RedisConfig.from_env()
    url = get_redis_url()
    use_tls = url.startswith("rediss://")

    return aioredis.Redis.from_url(
        url,
        decode_responses=cfg.decode_responses,
        max_connections=cfg.max_connections,
        retry_on_timeout=cfg.retry_on_timeout,
        ssl=use_tls,
        socket_connect_timeout=cfg.socket_connect_timeout,
        socket_timeout=cfg.socket_timeout,
        socket_keepalive=cfg.socket_keepalive,
        health_check_interval=cfg.health_check_interval,
    )
