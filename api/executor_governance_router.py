"""Operator-only governance API for the MT5 executor bridge."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from api.middleware.auth import verify_token
from api.middleware.governance import GovernanceContext, enforce_write_policy
from contracts.mt5_execution_protocol import ExecutorMode
from execution.mt5_executor_governance import (
    ExecutorGovernanceError,
    GovernanceConflictError,
    GovernanceNotReadyError,
    GovernanceSnapshot,
    ModeTransitionError,
    MT5ExecutorGovernanceRepository,
    get_mt5_executor_governance_repository,
)

router = APIRouter(
    prefix="/api/v1/ea/executor-governance",
    tags=["MT5 Executor Governance"],
    dependencies=[Depends(verify_token)],
)


class KillSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool
    expected_version: int | None = Field(default=None, ge=1)


class ModeTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_mode: ExecutorMode
    expected_mode: ExecutorMode | None = None
    expected_version: int | None = Field(default=None, ge=1)


RepositoryDep = Annotated[
    MT5ExecutorGovernanceRepository,
    Depends(get_mt5_executor_governance_repository),
]
WriteContextDep = Annotated[GovernanceContext, Depends(enforce_write_policy)]


def _translate_error(exc: ExecutorGovernanceError) -> HTTPException:
    if isinstance(exc, GovernanceConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ModeTransitionError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, GovernanceNotReadyError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _require_admin(context: GovernanceContext) -> None:
    if context.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required for executor governance")


@router.get("")
async def get_global_governance(repository: RepositoryDep) -> dict[str, Any]:
    try:
        return repository_snapshot(await repository.global_snapshot())
    except ExecutorGovernanceError as exc:
        raise _translate_error(exc) from exc


@router.get("/executors/{executor_id}")
async def get_executor_governance(executor_id: UUID, repository: RepositoryDep) -> dict[str, Any]:
    try:
        return repository_snapshot(await repository.executor_snapshot(executor_id))
    except ExecutorGovernanceError as exc:
        raise _translate_error(exc) from exc


@router.post("/kill-switch")
async def update_kill_switch(
    body: KillSwitchRequest,
    context: WriteContextDep,
    repository: RepositoryDep,
) -> dict[str, Any]:
    _require_admin(context)
    try:
        snapshot = await repository.set_kill_switch(
            active=body.active,
            actor=context.actor,
            reason=context.reason,
            expected_version=body.expected_version,
        )
        return repository_snapshot(snapshot)
    except ExecutorGovernanceError as exc:
        raise _translate_error(exc) from exc


@router.post("/executors/{executor_id}/execution-mode")
async def update_execution_mode(
    executor_id: UUID,
    body: ModeTransitionRequest,
    context: WriteContextDep,
    repository: RepositoryDep,
) -> dict[str, Any]:
    _require_admin(context)
    try:
        snapshot = await repository.transition_mode(
            executor_id,
            target_mode=body.target_mode,
            actor=context.actor,
            reason=context.reason,
            expected_mode=body.expected_mode,
            expected_version=body.expected_version,
        )
        return repository_snapshot(snapshot)
    except ExecutorGovernanceError as exc:
        raise _translate_error(exc) from exc


def repository_snapshot(snapshot: GovernanceSnapshot) -> dict[str, Any]:
    return snapshot.to_dict()


__all__ = ["router"]
