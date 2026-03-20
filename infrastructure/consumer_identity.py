"""
Dynamic consumer identity — unique per instance.

Zone: infrastructure/ — no business logic.
"""

from __future__ import annotations

import os
import socket


def generate_consumer_name(
    prefix: str = "engine",
    override: str | None = None,
) -> str:
    """
    Generate a unique consumer name for Redis consumer groups.

    Priority:
    1. Explicit override parameter.
    2. REDIS_CONSUMER_NAME env var.
    3. Auto: {prefix}_{hostname}_{pid}.
    """
    if override:
        return override

    env_name = os.environ.get("REDIS_CONSUMER_NAME")
    if env_name:
        return env_name

    hostname = socket.gethostname().replace(".", "_")
    pid = os.getpid()
    return f"{prefix}_{hostname}_{pid}"
