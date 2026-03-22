"""
Allocation Router — FastAPI router for allocation domain.

POST /api/v1/allocation/take → trigger multi-account allocation for a signal
GET  /api/v1/allocation/signals → list latest signals in registry
GET  /api/v1/allocation/{request_id} → get allocation result
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from allocation.allocation_models import AllocationRequest, AllocationResult
from allocation.allocation_service import AllocationService
from allocation.signal_registry import SignalRegistry

router = APIRouter(prefix="/api/v1/allocation", tags=["allocation"])
_service = AllocationService()
_registry = SignalRegistry()
_results: dict[str, AllocationResult] = {}


class TakeRequest(BaseModel):
    signal_id: str = Field(..., description="Signal ID from registry")
    account_ids: list[str] | None = Field(default=None, description="Target account IDs")
    accounts: list[str] | None = Field(default=None, description="Target account IDs (alias for account_ids)")
    operator: str = Field(default="operator")
    action: str = Field(default="TAKE", description="TAKE or PREVIEW")
    risk_percent: float = Field(1.0, gt=0, le=5.0)


@router.post("/take", response_model=AllocationResult)
async def take_signal(req: TakeRequest) -> AllocationResult:
    """Operator takes a signal — allocates simultaneously to all specified accounts."""
    account_ids = req.account_ids or req.accounts or []
    request = AllocationRequest(
        request_id=str(uuid.uuid4()),
        signal_id=req.signal_id,
        account_ids=account_ids,
        operator=req.operator,
        action=req.action,
        risk_percent=req.risk_percent,
    )
    result = _service.allocate(request)
    _results[request.request_id] = result
    return result


@router.get("/signals")
async def list_signals(n: int = 10) -> list[dict]:
    """List latest signals in the global registry."""
    return _registry.get_latest(n)


@router.get("/{request_id}", response_model=AllocationResult)
async def get_result(request_id: str) -> AllocationResult:
    result = _results.get(request_id)
    if not result:
        raise HTTPException(status_code=404, detail="Allocation result not found")
    return result
