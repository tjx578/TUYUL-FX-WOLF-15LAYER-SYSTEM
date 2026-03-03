"""Service-level dependency aliases for API composition."""

from infrastructure.redis_client import get_client as get_redis_client

__all__ = ["get_redis_client"]
