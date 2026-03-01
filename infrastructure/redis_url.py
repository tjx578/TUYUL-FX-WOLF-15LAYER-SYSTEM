"""Centralized Redis URL resolution.

Every module that needs a Redis URL should import ``get_redis_url`` from here
instead of duplicating ``os.getenv("REDIS_URL", ...)``.  This keeps the
default in one place, simplifies audits, and prevents security drift
(hardcoded credentials, inconsistent DB selection, etc.).

Railway Redis addon injects *both* ``REDIS_URL`` **and** individual vars
without underscores (``REDISHOST``, ``REDISPASSWORD``, ``REDISPORT``,
``REDISUSER``).  We prefer ``REDIS_URL`` but fall back to ``REDIS_PRIVATE_URL``
(Railway private-network URL) then the Railway-style vars when ``REDIS_URL``
is absent.
"""

import os
from urllib.parse import quote_plus, urlsplit, urlunsplit

_DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def _build_url_from_railway_vars() -> str | None:
    """Attempt to build a Redis URL from Railway-style env vars.

    Railway Redis addon sets:
        REDISHOST, REDISPORT, REDISUSER, REDISPASSWORD

    Returns ``None`` when REDISHOST is not set (i.e. not running on Railway
    with a Redis addon).
    """
    host = os.environ.get("REDISHOST")
    if not host:
        return None

    port = os.environ.get("REDISPORT", "6379")
    user = os.environ.get("REDISUSER", "")
    password = os.environ.get("REDISPASSWORD", "")

    # Build userinfo portion — only include when credentials exist
    if password:
        userinfo = f"{quote_plus(user)}:{quote_plus(password)}@" if user else f":{quote_plus(password)}@"
    elif user:
        userinfo = f"{quote_plus(user)}@"
    else:
        userinfo = ""

    return f"redis://{userinfo}{host}:{port}/0"


def get_redis_url() -> str:
    """Return the Redis connection URL from the environment or the default.

    Priority:
        1. ``REDIS_URL`` environment variable (production / Railway / Docker).
        2. ``REDIS_PRIVATE_URL`` environment variable (Railway private network URL).
        3. URL built from Railway-style vars (``REDISHOST``, etc.).
        4. ``_DEFAULT_REDIS_URL`` — localhost fallback for local dev.
    """
    url = os.environ.get("REDIS_URL")
    if url:
        return url

    private_url = os.environ.get("REDIS_PRIVATE_URL")
    if private_url:
        return private_url

    railway_url = _build_url_from_railway_vars()
    if railway_url:
        return railway_url

    return _DEFAULT_REDIS_URL


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
