"""Health helper for PostgreSQL backup subsystem."""

from __future__ import annotations

from typing import Any

from storage.postgres_client import pg_client


async def postgres_health() -> dict[str, Any]:
    """Return PostgreSQL health status payload."""
    return await pg_client.health_check()
