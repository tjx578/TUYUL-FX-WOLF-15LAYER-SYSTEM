import os

from redis.asyncio import Redis


def create_redis_client() -> Redis:
    """Create Redis client with TLS if configured.

    Returns:
        Configured async Redis client instance.

    TCP_OVERWINDOW mitigation:
      - Keepalive enabled (SO_KEEPALIVE) to prune stale connections.
      - Pool capped at 10 (async callers pipeline / share better).
      - health_check_interval prunes idle conns before they accumulate.
      - Detailed keepalive timing delegated to Redis server-side
        ``--tcp-keepalive`` to avoid EINVAL on container runtimes.
    """
    redis_url = os.environ["REDIS_URL"]
    use_tls = redis_url.startswith("rediss://")

    return Redis.from_url(
        redis_url,
        decode_responses=True,
        max_connections=10,
        retry_on_timeout=True,
        ssl=use_tls,
        socket_connect_timeout=5,
        socket_timeout=5,
        socket_keepalive=True,
        health_check_interval=30,
    )
