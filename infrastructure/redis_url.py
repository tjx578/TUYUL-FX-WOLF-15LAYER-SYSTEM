"""Centralized Redis URL resolution.

Every module that needs a Redis URL should import ``get_redis_url`` from here
instead of duplicating ``os.getenv("REDIS_URL", ...)``.  This keeps the
default in one place, simplifies audits, and prevents security drift
(hardcoded credentials, inconsistent DB selection, etc.).
"""

import os

_DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def get_redis_url() -> str:
    """Return the Redis connection URL from the environment or the default.

    Priority:
        1. ``REDIS_URL`` environment variable (production / Railway / Docker).
        2. ``_DEFAULT_REDIS_URL`` — localhost fallback for local dev.
    """
    return os.getenv("REDIS_URL", _DEFAULT_REDIS_URL)
