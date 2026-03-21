"""Agent Ingest API router.

Lightweight ingestion endpoints for MT5 EA → backend data flow:
heartbeats, status changes, and portfolio snapshots.

Authentication: standard JWT/API-key via verify_token (same as other routers).

Prefix: /api/v1/agent-ingest
Tags:   Agent Ingest
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from agents.exceptions import AgentError, AgentLockError, AgentNotFoundError, AgentValidationError
from agents.models import (
    IngestHeartbeatRequest,
    IngestPortfolioSnapshotRequest,
    IngestStatusChangeRequest,
)
from agents.service import AgentManagerService
from api.middleware.auth import verify_token

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/agent-ingest",
    tags=["Agent Ingest"],
    dependencies=[Depends(verify_token)],
)

_service = AgentManagerService()


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------


def _http_from_agent_error(exc: AgentError) -> HTTPException:
    if isinstance(exc, AgentNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, AgentLockError):
        return HTTPException(status_code=423, detail=str(exc))
    if isinstance(exc, AgentValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/heartbeat")
async def ingest_heartbeat(body: IngestHeartbeatRequest) -> dict[str, Any]:
    """Upsert runtime metrics from an MT5 EA heartbeat.

    The EA should call this endpoint on every heartbeat tick to keep
    runtime data current.  The agent must already exist in ea_agents.

    Returns:
        Updated runtime row.
    """
    try:
        runtime = await _service.record_heartbeat(body)
    except AgentError as exc:
        raise _http_from_agent_error(exc) from exc
    return runtime


@router.post("/status-change")
async def ingest_status_change(body: IngestStatusChangeRequest) -> dict[str, Any]:
    """Record a status change notification from an MT5 EA.

    Updates the agent's status field and emits a STATUS_CHANGE event.
    Blocked if the agent is locked.

    Returns:
        Updated agent row.
    """
    try:
        agent = await _service.change_status(body, performed_by="EA_INGEST")
    except AgentError as exc:
        raise _http_from_agent_error(exc) from exc
    return agent


@router.post("/portfolio-snapshot")
async def ingest_portfolio_snapshot(body: IngestPortfolioSnapshotRequest) -> dict[str, Any]:
    """Record an account portfolio snapshot from an MT5 EA.

    Snapshots are append-only time-series records for trend analysis.

    Returns:
        Inserted snapshot row.
    """
    try:
        snapshot = await _service.record_portfolio_snapshot(body)
    except AgentError as exc:
        raise _http_from_agent_error(exc) from exc
    return snapshot
