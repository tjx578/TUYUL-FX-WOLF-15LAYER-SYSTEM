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
from __future__ import annotations

import os
from urllib.parse import quote_plus, urlsplit, urlunsplit

_DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_production_env() -> bool:
    env = os.environ.get("ENV", os.environ.get("APP_ENV", "")).strip().lower()
    return env in {"prod", "production"}


def _is_local_redis_host(hostname: str | None) -> bool:
    return (hostname or "").strip().lower() in {"localhost", "127.0.0.1", "::1"}


def _is_railway_private_network(hostname: str | None) -> bool:
    """Railway private-network hostnames end with ``.railway.internal``."""
    return (hostname or "").strip().lower().endswith(".railway.internal")


def _is_railway_runtime() -> bool:
    """Detect Railway runtime through standard platform-provided env vars."""
    return bool(
        os.environ.get("RAILWAY_ENVIRONMENT")
        or os.environ.get("RAILWAY_ENVIRONMENT_ID")
        or os.environ.get("RAILWAY_PROJECT_ID")
        or os.environ.get("RAILWAY_SERVICE_ID")
        or os.environ.get("RAILWAY_DEPLOYMENT_ID")
        or os.environ.get("RAILWAY_REPLICA_ID")
    )


def _validate_redis_security(url: str) -> str:
    """Enforce AUTH + TLS for non-local Redis in production.

    Set REDIS_ALLOW_INSECURE_IN_PROD=true only for temporary break-glass
    situations; default behavior is fail-loud for insecure production URLs.
    """
    if not _is_production_env():
        return url
    if _is_true(os.environ.get("REDIS_ALLOW_INSECURE_IN_PROD")):
        return url

    parts = urlsplit(url)
    if _is_local_redis_host(parts.hostname):
        return url
    if _is_railway_private_network(parts.hostname):
        return url

    if not parts.password:
        raise RuntimeError("In production, Redis URL must include AUTH credentials (password).")
    if parts.scheme != "rediss":
        raise RuntimeError("In production, Redis URL must use TLS (rediss:// scheme).")
    return url


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
        return _validate_redis_security(url)

    private_url = os.environ.get("REDIS_PRIVATE_URL")
    if private_url:
        return _validate_redis_security(private_url)

    railway_url = _build_url_from_railway_vars()
    if railway_url:
        return _validate_redis_security(railway_url)

    # Fail-loud on Railway to avoid silently connecting to localhost in containers.
    allow_local_fallback = _is_true(os.environ.get("REDIS_ALLOW_LOCALHOST_FALLBACK"))
    if _is_railway_runtime() and not allow_local_fallback:
        raise RuntimeError(
            "Redis configuration missing on Railway: set REDIS_URL or REDIS_PRIVATE_URL "
            "(or REDISHOST/REDISPORT/REDISPASSWORD). "
            "If this is intentional for debugging, set REDIS_ALLOW_LOCALHOST_FALLBACK=true."
        )

    return _validate_redis_security(_DEFAULT_REDIS_URL)


def sanitize_redis_url(url: str) -> str:
    """Return a Redis URL with the password masked for safe logging."""
    parts = urlsplit(url)
    if not parts.netloc or "@" not in parts.netloc:
        return url

    userinfo, hostinfo = parts.netloc.rsplit("@", 1)
    if ":" not in userinfo:
        return url

    username, _password = userinfo.split(":", 1)
    safe_netloc = f"{username}:***@{hostinfo}"
    return urlunsplit((parts.scheme, safe_netloc, parts.path, parts.query, parts.fragment))


def get_safe_redis_url() -> str:
    """Return Redis URL with password masked for safe logging."""
    return sanitize_redis_url(get_redis_url())
