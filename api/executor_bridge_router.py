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
    CommandNotFoundError,
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


def _governance_headers(snapshot: Any) -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "X-Protocol-Version": PROTOCOL_VERSION,
        "X-Execution-Mode": str(snapshot.execution_mode or ""),
        "X-Mode-Version": str(snapshot.mode_version or ""),
        "X-Kill-Switch-Active": str(snapshot.kill_switch_active).lower(),
        "X-Governance-Version": str(snapshot.governance_version),
    }


def _translate_repository_error(exc: ExecutorRepositoryError) -> HTTPException:
    if isinstance(exc, (ExecutorNotFoundError, CommandNotFoundError)):
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
        "mode_version": int(executor["mode_version"]),
        "kill_switch_active": bool(executor["kill_switch_active"]),
        "kill_switch_reason": str(executor["kill_switch_reason"]),
        "governance_version": int(executor["governance_version"]),
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
        governance = await repository.governance_snapshot(executor_id)
        delivery = await repository.next_command(executor_id)
    except ExecutorRepositoryError as exc:
        raise _translate_repository_error(exc) from exc
    for header, value in _governance_headers(governance).items():
        response.headers[header] = value
    if delivery is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers=_governance_headers(governance))
    data: dict[str, Any] = {"command": delivery.command.model_dump(mode="json")}
    if delivery.signed_envelope is not None:
        data["signed_envelope"] = delivery.signed_envelope.model_dump(mode="json")
    return _response_envelope(
        request_id=_request_id(x_request_id),
        data=data,
    )


@router.get("/api/v1/executors/{executor_id}/governance")
async def get_executor_governance(
    executor_id: UUID,
    repository: RepositoryDep,
    auth: AuthDep,
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> dict[str, Any]:
    _assert_executor(auth, executor_id)
    try:
        governance = await repository.governance_snapshot(executor_id)
    except ExecutorRepositoryError as exc:
        raise _translate_repository_error(exc) from exc
    return _response_envelope(
        request_id=_request_id(x_request_id),
        data=governance.to_dict(),
    )


@router.post("/api/v1/commands/{command_id}/claim")
async def claim_executor_command(
    command_id: UUID,
    body: ClaimRequest,
    response: Response,
    repository: RepositoryDep,
    auth: AuthDep,
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    try:
        executor_id = UUID(str(auth["executor_id"]))
        claim = await repository.claim_command(
            executor_id=executor_id,
            command_id=command_id,
            lease_seconds=body.lease_seconds,
        )
        governance = await repository.governance_snapshot(executor_id)
    except ExecutorRepositoryError as exc:
        raise _translate_repository_error(exc) from exc
    data: dict[str, Any] = {
        "command": claim.command.model_dump(mode="json"),
        "request_hash": (
            claim.signed_envelope.payload_sha256
            if claim.signed_envelope is not None
            else sha256_tag(claim.command.model_dump(mode="json"))
        ),
        "claim_token": claim.claim_token,
        "lease_expires_at_utc": claim.lease_expires_at.isoformat(),
        "governance": governance.to_dict(),
    }
    if claim.signed_envelope is not None:
        data["signed_envelope"] = claim.signed_envelope.model_dump(mode="json")
    return _response_envelope(
        request_id=_request_id(x_request_id),
        data=data,
    )


@router.get("/api/v1/executors/{executor_id}/commands/{command_id}/status")
async def get_executor_command_status(
    executor_id: UUID,
    command_id: UUID,
    response: Response,
    repository: RepositoryDep,
    auth: AuthDep,
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
) -> dict[str, Any]:
    _assert_executor(auth, executor_id)
    response.headers["Cache-Control"] = "no-store"
    try:
        result = await repository.command_status(
            executor_id=executor_id,
            command_id=command_id,
        )
    except ExecutorRepositoryError as exc:
        raise _translate_repository_error(exc) from exc
    return _response_envelope(request_id=_request_id(x_request_id), data=result)


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
