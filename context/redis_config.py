import os
import socket
from typing import Any

from redis.asyncio import Redis


def _keepalive_options() -> dict[int, int]:
    """Build TCP keepalive socket options using platform-portable constants."""
    opts: dict[int, int] = {}
    if hasattr(socket, "TCP_KEEPIDLE"):
        opts[socket.TCP_KEEPIDLE] = 60
    if hasattr(socket, "TCP_KEEPINTVL"):
        opts[socket.TCP_KEEPINTVL] = 15
    if hasattr(socket, "TCP_KEEPCNT"):
        opts[socket.TCP_KEEPCNT] = 4
    return opts


def create_redis_client() -> Redis:
    """Create Redis client with TLS if configured.

    Returns:
        Configured async Redis client instance.

    TCP_OVERWINDOW mitigation:
      - Keepalive enabled to prune stale connections.
      - Pool capped at 10 (async callers pipeline / share better).
      - health_check_interval prunes idle conns before they accumulate.
    """
    redis_url = os.environ["REDIS_URL"]
    use_tls = redis_url.startswith("rediss://")

    kwargs: dict[str, Any] = dict(
        decode_responses=True,
        max_connections=10,
        retry_on_timeout=True,
        ssl=use_tls,
        socket_connect_timeout=5,
        socket_timeout=5,
        socket_keepalive=True,
        health_check_interval=30,
    )

    ka_opts = _keepalive_options()
    if ka_opts:
        kwargs["socket_keepalive_options"] = ka_opts

    return Redis.from_url(redis_url, **kwargs)
