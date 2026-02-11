import os

from redis.asyncio import Redis


def create_redis_client() -> Redis:
    """Create Redis client with TLS if configured.

    Returns:
        Configured async Redis client instance.
    """
    redis_url = os.environ["REDIS_URL"]
    use_tls = redis_url.startswith("rediss://")

    return Redis.from_url(
        redis_url,
        decode_responses=True,
        max_connections=20,
        retry_on_timeout=True,
        ssl=use_tls,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
