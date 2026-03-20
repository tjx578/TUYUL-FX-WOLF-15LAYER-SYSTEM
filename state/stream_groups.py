"""Redis stream consumer groups used by distributed workers.

Backward-compatibility shim — canonical source is now core/redis_keys.py.
"""

from core.redis_keys import (  # noqa: F401
    API_GROUP,
    ENGINE_GROUP,
    INGEST_GROUP,
)
