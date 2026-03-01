"""Centralized Redis URL resolution.

Every module that needs a Redis URL should import ``get_redis_url`` from here.
``REDIS_URL`` **must** be explicitly set in the environment — there is no
fallback to localhost or auto-built URLs from individual Railway vars.
This prevents silent misconfigurations and AUTH errors in production.
"""

import os
from urllib.parse import urlsplit, urlunsplit


def get_redis_url() -> str:
    """Return the Redis connection URL from the environment.

    ``REDIS_URL`` must be explicitly set (e.g. to ``$REDIS_PRIVATE_URL`` on
    Railway).  No fallback to localhost or auto-built URLs is provided —
    silent fallbacks hide misconfigurations and cause AUTH errors.

    Raises:
        RuntimeError: when ``REDIS_URL`` is not set.
    """
    url = os.environ.get("REDIS_URL")
    if not url:
        raise RuntimeError(
            "REDIS_URL must be explicitly set. "
            "Fallback to REDISHOST/REDISPASSWORD is disabled in production."
        )
    return url


def get_safe_redis_url() -> str:
    """Return Redis URL with password masked for safe logging."""
    url = get_redis_url()
    parts = urlsplit(url)
    if not parts.netloc or "@" not in parts.netloc:
        return url

    userinfo, hostinfo = parts.netloc.rsplit("@", 1)
    if ":" not in userinfo:
        return url

    username, _password = userinfo.split(":", 1)
    safe_netloc = f"{username}:***@{hostinfo}"
    return urlunsplit((parts.scheme, safe_netloc, parts.path, parts.query, parts.fragment))
