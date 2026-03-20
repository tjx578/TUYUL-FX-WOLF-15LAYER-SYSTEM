"""System-wide health aggregation endpoint.

Zones: dashboard (monitoring/ops) — no market logic, no execution authority.

Combines:
    * API self-health (Redis, Postgres, engine state)
    * Peer service probes (Engine, Ingest) via cached PeerHealthChecker
    * Overall fleet status
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1/health", tags=["health"])


@router.get("/system")
async def system_health(request: Request) -> dict[str, Any]:
    """Aggregated fleet health — all services + self diagnostics.

    Returns the cached peer health snapshot from :class:`PeerHealthChecker`
    combined with the API service's own status.
    """
    from infrastructure.peer_health import PeerHealthChecker

    checker: PeerHealthChecker | None = getattr(request.app.state, "peer_health_checker", None)

    if checker is None:
        return {
            "status": "unavailable",
            "reason": "peer health checker not initialised",
            "self": "api",
            "peers": [],
        }

    snap = checker.snapshot()
    return snap
