"""
Take-Signal API Routes — P1-1
================================
POST /api/v1/execution/take-signal    — Create a take-signal binding
GET  /api/v1/execution/take-signal/{take_id}  — Get take-signal by ID

Zone: API / control plane — operator action to bind global signal to account + EA.
Authority: Does NOT compute market direction or override constitutional verdict.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from api.middleware.governance import enforce_write_policy
from contracts.api_response_schema import ApiResponse
from execution.take_signal_models import (
    TakeSignalCreateRequest,
    TakeSignalResponse,
)
from execution.take_signal_service import (
    SignalExpiredError,
    SignalNotFoundError,
    TakeSignalService,
)

from .middleware.auth import verify_token

router = APIRouter(
    prefix="/api/v1/execution",
    tags=["take-signal"],
    dependencies=[Depends(verify_token)],
)

_service: TakeSignalService | None = None


def _get_service() -> TakeSignalService:
    global _service
    if _service is None:
        _service = TakeSignalService()
    return _service


@router.post(
    "/take-signal",
    response_model=ApiResponse[TakeSignalResponse],
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_write_policy)],
    summary="Bind a global signal to an account + EA instance",
)
async def create_take_signal(
    body: TakeSignalCreateRequest,
) -> ApiResponse[TakeSignalResponse]:
    """Create a take-signal operational binding.

    Idempotent: replaying the same request_id returns the existing record.
    Returns 202 on success, 409 on idempotency conflict, 404 on missing signal.
    """
    svc = _get_service()
    try:
        response, created = await svc.create(body)
    except SignalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SIGNAL_NOT_FOUND: {exc.signal_id}",
        ) from exc
    except SignalExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"SIGNAL_EXPIRED: {exc.signal_id}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return ApiResponse(ok=True, data=response)


@router.get(
    "/take-signal/{take_id}",
    response_model=ApiResponse[TakeSignalResponse],
    summary="Get take-signal record by ID",
)
async def get_take_signal(take_id: str) -> ApiResponse[TakeSignalResponse]:
    """Retrieve a take-signal binding record by its take_id."""
    svc = _get_service()
    response = await svc.get(take_id)
    if response is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"TAKE_SIGNAL_NOT_FOUND: {take_id}",
        )
    return ApiResponse(ok=True, data=response)
