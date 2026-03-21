"""Agent Manager API router.

Exposes CRUD and lifecycle endpoints for EA agents and profiles.
All endpoints require JWT/API-key authentication.  Write operations
additionally require the governance write policy.

Prefix: /api/v1/agent-manager
Tags:   Agent Manager
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from agents.exceptions import (
    AgentConflictError,
    AgentError,
    AgentLockError,
    AgentNotFoundError,
    AgentValidationError,
)
from agents.models import (
    AgentAuditLogResponse,
    AgentEventResponse,
    AgentListResponse,
    AgentResponse,
    AgentRuntimeResponse,
    CreateAgentRequest,
    CreateProfileRequest,
    LockAgentRequest,
    PortfolioSnapshotResponse,
    ProfileResponse,
    UpdateAgentRequest,
)
from agents.service import AgentManagerService
from api.middleware.auth import verify_token
from api.middleware.governance import GovernanceContext, enforce_write_policy

__all__ = ["router"]

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/agent-manager",
    tags=["Agent Manager"],
    dependencies=[Depends(verify_token)],
)

_service = AgentManagerService()

# ---------------------------------------------------------------------------
# Error mapping helpers
# ---------------------------------------------------------------------------

_NOT_FOUND_DETAIL = "Agent not found"


def _handle_agent_error(exc: AgentError) -> HTTPException:
    """Map domain exceptions to HTTP errors."""
    if isinstance(exc, AgentNotFoundError):
        return HTTPException(status_code=404, detail=str(exc) or _NOT_FOUND_DETAIL)
    if isinstance(exc, AgentConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, AgentLockError):
        return HTTPException(status_code=423, detail=str(exc))
    if isinstance(exc, AgentValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _actor_from_context(ctx: GovernanceContext) -> str:
    return ctx.actor or "SYSTEM"


# ---------------------------------------------------------------------------
# Helpers — row → response model
# ---------------------------------------------------------------------------


def _dict_to_agent_response(data: dict[str, Any]) -> AgentResponse:
    runtime_raw = data.get("runtime")
    runtime = AgentRuntimeResponse(**runtime_raw) if runtime_raw else None
    return AgentResponse(
        **{k: v for k, v in data.items() if k != "runtime"},
        runtime=runtime,
    )


def _dict_to_runtime_response(data: dict[str, Any]) -> AgentRuntimeResponse:
    return AgentRuntimeResponse(**data)


def _dict_to_event_response(data: dict[str, Any]) -> AgentEventResponse:
    return AgentEventResponse(**data)


def _dict_to_audit_response(data: dict[str, Any]) -> AgentAuditLogResponse:
    return AgentAuditLogResponse(**data)


def _dict_to_profile_response(data: dict[str, Any]) -> ProfileResponse:
    return ProfileResponse(**data)


def _dict_to_snapshot_response(data: dict[str, Any]) -> PortfolioSnapshotResponse:
    return PortfolioSnapshotResponse(**data)


# ---------------------------------------------------------------------------
# Agents — read
# ---------------------------------------------------------------------------


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(
    ea_class: str | None = Query(None, description="Filter by ea_class (PRIMARY or PORTFOLIO)"),
    status: str | None = Query(None, description="Filter by agent status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AgentListResponse:
    """List EA agents with optional filters and pagination."""
    try:
        agents, total = await _service.list_agents(ea_class, status, limit, offset)
    except AgentError as exc:
        raise _handle_agent_error(exc) from exc
    return AgentListResponse(
        agents=[_dict_to_agent_response(a) for a in agents],
        total=total,
    )


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str) -> AgentResponse:
    """Get a single agent with its runtime metrics."""
    try:
        data = await _service.get_agent(agent_id)
    except AgentError as exc:
        raise _handle_agent_error(exc) from exc
    return _dict_to_agent_response(data)


@router.get("/agents/{agent_id}/runtime", response_model=AgentRuntimeResponse)
async def get_agent_runtime(agent_id: str) -> AgentRuntimeResponse:
    """Get runtime metrics for a single agent."""
    try:
        agent_data = await _service.get_agent(agent_id)
    except AgentError as exc:
        raise _handle_agent_error(exc) from exc
    runtime = agent_data.get("runtime")
    if runtime is None:
        raise HTTPException(status_code=404, detail="No runtime data available for this agent")
    return _dict_to_runtime_response(runtime)


@router.get("/agents/{agent_id}/events", response_model=list[AgentEventResponse])
async def list_agent_events(
    agent_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[AgentEventResponse]:
    """List events for an agent ordered by most-recent first."""
    try:
        events = await _service.get_agent_events(agent_id, limit, offset)
    except AgentError as exc:
        raise _handle_agent_error(exc) from exc
    return [_dict_to_event_response(e) for e in events]


@router.get("/agents/{agent_id}/audit", response_model=list[AgentAuditLogResponse])
async def list_agent_audit(
    agent_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[AgentAuditLogResponse]:
    """List audit log entries for an agent ordered by most-recent first."""
    try:
        logs = await _service.get_agent_audit_log(agent_id, limit, offset)
    except AgentError as exc:
        raise _handle_agent_error(exc) from exc
    return [_dict_to_audit_response(entry) for entry in logs]


@router.get("/agents/{agent_id}/snapshots", response_model=list[PortfolioSnapshotResponse])
async def list_agent_snapshots(
    agent_id: str,
    limit: int = Query(50, ge=1, le=500),
) -> list[PortfolioSnapshotResponse]:
    """List portfolio snapshots for an agent ordered by most-recent first."""
    try:
        snapshots = await _service.list_portfolio_snapshots(agent_id, limit)
    except AgentError as exc:
        raise _handle_agent_error(exc) from exc
    return [_dict_to_snapshot_response(s) for s in snapshots]


# ---------------------------------------------------------------------------
# Agents — write
# ---------------------------------------------------------------------------


@router.post("/agents", response_model=AgentResponse, status_code=201)
async def create_agent(
    body: CreateAgentRequest,
    ctx: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> AgentResponse:
    """Create a new EA agent."""
    try:
        data = await _service.create_agent(body, performed_by=_actor_from_context(ctx))
    except AgentError as exc:
        raise _handle_agent_error(exc) from exc
    return _dict_to_agent_response(data)


@router.put("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    ctx: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> AgentResponse:
    """Update mutable fields of an existing EA agent."""
    try:
        data = await _service.update_agent(agent_id, body, performed_by=_actor_from_context(ctx))
    except AgentError as exc:
        raise _handle_agent_error(exc) from exc
    return _dict_to_agent_response(data)


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: str,
    ctx: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> None:
    """Delete an EA agent by UUID."""
    try:
        await _service.delete_agent(agent_id, performed_by=_actor_from_context(ctx))
    except AgentError as exc:
        raise _handle_agent_error(exc) from exc


@router.post("/agents/{agent_id}/lock", response_model=AgentResponse)
async def lock_agent(
    agent_id: str,
    body: LockAgentRequest,
    ctx: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> AgentResponse:
    """Lock an EA agent, preventing further state changes."""
    try:
        data = await _service.lock_agent(agent_id, body, performed_by=_actor_from_context(ctx))
    except AgentError as exc:
        raise _handle_agent_error(exc) from exc
    return _dict_to_agent_response(data)


@router.post("/agents/{agent_id}/unlock", response_model=AgentResponse)
async def unlock_agent(
    agent_id: str,
    ctx: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> AgentResponse:
    """Unlock a previously locked EA agent."""
    try:
        data = await _service.unlock_agent(agent_id, performed_by=_actor_from_context(ctx))
    except AgentError as exc:
        raise _handle_agent_error(exc) from exc
    return _dict_to_agent_response(data)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


@router.get("/profiles", response_model=list[ProfileResponse])
async def list_profiles() -> list[ProfileResponse]:
    """List all EA profiles."""
    try:
        profiles = await _service.list_profiles()
    except AgentError as exc:
        raise _handle_agent_error(exc) from exc
    return [_dict_to_profile_response(p) for p in profiles]


@router.post("/profiles", response_model=ProfileResponse, status_code=201)
async def create_profile(
    body: CreateProfileRequest,
    ctx: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> ProfileResponse:
    """Create a new EA profile template."""
    try:
        data = await _service.create_profile(body, performed_by=_actor_from_context(ctx))
    except AgentError as exc:
        raise _handle_agent_error(exc) from exc
    return _dict_to_profile_response(data)
