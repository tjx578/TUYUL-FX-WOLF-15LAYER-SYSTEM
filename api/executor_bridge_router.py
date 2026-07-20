"""Public pull-based API used by the Wolf15 MT5 dumb executor."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from api.middleware.executor_auth import verify_executor_auth
from contracts.mt5_execution_protocol import (
    PROTOCOL_VERSION,
    ExecutionReportV1,
    ExecutorHeartbeatV1,
    ExecutorRegistrationV1,
    sha256_tag,
)
from execution.mt5_command_repository import (
    CommandConflictError,
    ExecutorBindingMismatchError,
    ExecutorNotFoundError,
    ExecutorRepositoryError,
    MT5CommandRepository,
    get_mt5_command_repository,
)

router = APIRouter(tags=["MT5 Executor Bridge"])


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lease_seconds: int = Field(default=30, ge=10, le=120)


RepositoryDep = Annotated[MT5CommandRepository, Depends(get_mt5_command_repository)]
AuthDep = Annotated[dict[str, Any], Depends(verify_executor_auth)]


def _assert_executor(auth: dict[str, Any], executor_id: UUID) -> None:
    try:
        authenticated = UUID(str(auth.get("executor_id") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid authenticated executor id") from exc
    if authenticated != executor_id:
        raise HTTPException(status_code=403, detail="Executor credential is not bound to this resource")


def _request_id(value: str | None) -> str:
    candidate = (value or "").strip()
    return candidate[:100] if candidate else str(uuid4())


def _response_envelope(*, request_id: str, data: Any) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "server_time_utc": datetime.now(UTC).isoformat(),
        "request_id": request_id,
        "data": data,
    }


def _translate_repository_error(exc: ExecutorRepositoryError) -> HTTPException:
    if isinstance(exc, ExecutorNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ExecutorBindingMismatchError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, CommandConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=503, detail=str(exc))


@router.post("/api/v1/executors/register", status_code=status.HTTP_201_CREATED)
async def register_executor(
    body: ExecutorRegistrationV1,
    repository: RepositoryDep,
    auth: AuthDep,
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> dict[str, Any]:
    _assert_executor(auth, body.executor_id)
    try:
        executor = await repository.register_executor(body)
    except ExecutorRepositoryError as exc:
        raise _translate_repository_error(exc) from exc
    data = {
        "executor_id": str(executor["executor_id"]),
        "account_id": executor["account_id"],
        "execution_mode": str(executor["execution_mode"]),
        "status": str(executor["status"]),
    }
    return _response_envelope(request_id=_request_id(x_request_id), data=data)


@router.post("/api/v1/executors/{executor_id}/heartbeat")
async def executor_heartbeat(
    executor_id: UUID,
    body: ExecutorHeartbeatV1,
    repository: RepositoryDep,
    auth: AuthDep,
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> dict[str, Any]:
    _assert_executor(auth, executor_id)
    if body.executor_id != executor_id:
        raise HTTPException(status_code=422, detail="Body executor_id does not match path")
    try:
        result = await repository.record_heartbeat(body)
    except ExecutorRepositoryError as exc:
        raise _translate_repository_error(exc) from exc
    return _response_envelope(request_id=_request_id(x_request_id), data=result)


@router.get("/api/v1/executors/{executor_id}/commands/next")
async def next_executor_command(
    executor_id: UUID,
    response: Response,
    repository: RepositoryDep,
    auth: AuthDep,
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> Any:
    _assert_executor(auth, executor_id)
    try:
        command = await repository.next_command(executor_id)
    except ExecutorRepositoryError as exc:
        raise _translate_repository_error(exc) from exc
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Protocol-Version"] = PROTOCOL_VERSION
    if command is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})
    return _response_envelope(
        request_id=_request_id(x_request_id),
        data={"command": command.model_dump(mode="json")},
    )


@router.post("/api/v1/commands/{command_id}/claim")
async def claim_executor_command(
    command_id: UUID,
    body: ClaimRequest,
    repository: RepositoryDep,
    auth: AuthDep,
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> dict[str, Any]:
    try:
        executor_id = UUID(str(auth["executor_id"]))
        claim = await repository.claim_command(
            executor_id=executor_id,
            command_id=command_id,
            lease_seconds=body.lease_seconds,
        )
    except ExecutorRepositoryError as exc:
        raise _translate_repository_error(exc) from exc
    return _response_envelope(
        request_id=_request_id(x_request_id),
        data={
            "command": claim.command.model_dump(mode="json"),
            "request_hash": sha256_tag(claim.command.model_dump(mode="json")),
            "claim_token": claim.claim_token,
            "lease_expires_at_utc": claim.lease_expires_at.isoformat(),
        },
    )


@router.post("/api/v1/commands/{command_id}/reports", status_code=status.HTTP_202_ACCEPTED)
async def append_execution_report(
    command_id: UUID,
    body: ExecutionReportV1,
    repository: RepositoryDep,
    auth: AuthDep,
    x_claim_token: str = Header(..., alias="X-Claim-Token"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> dict[str, Any]:
    _assert_executor(auth, body.executor_id)
    if body.command_id != command_id:
        raise HTTPException(status_code=422, detail="Body command_id does not match path")
    try:
        result = await repository.append_report(body, claim_token=x_claim_token)
    except ExecutorRepositoryError as exc:
        raise _translate_repository_error(exc) from exc
    return _response_envelope(request_id=_request_id(x_request_id), data=result)


__all__ = ["router"]
