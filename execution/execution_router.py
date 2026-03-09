"""
Execution Router — FastAPI router for execution domain.

GET  /api/v1/execution/queue    → queue depth stats
GET  /api/v1/execution/{request_id} → execution result by request ID
POST /api/v1/execution/cancel   → cancel a pending order
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from execution.ea_manager import EAManager
from execution.broker_executor import BrokerExecutor, ExecutionRequest, OrderAction

router = APIRouter(prefix="/api/v1/execution", tags=["execution"])

_ea_manager = EAManager()
_broker = BrokerExecutor()


class CancelRequest(BaseModel):
    account_id: str
    ticket: int
    symbol: str


@router.get("/queue")
async def queue_stats() -> dict:
    """Return current execution queue depth."""
    snapshot = _ea_manager.queue_snapshot()
    return {
        "queue_depth": snapshot["queue_depth"],
        "max_size": snapshot["queue_max"],
        "running": snapshot["running"],
        "overload_mode": snapshot["overload_mode"],
        "overload_rejections": snapshot["overload_rejections"],
        "overload_drops": snapshot["overload_drops"],
    }


@router.get("/{request_id}")
async def get_result(request_id: str) -> dict:
    """Get execution result by request ID."""
    result = _ea_manager.get_result(request_id)
    if not result:
        raise HTTPException(status_code=404, detail="Execution result not found")
    return {
        "request_id": result.request_id,
        "success": result.success,
        "ticket": result.ticket,
        "error_code": result.error_code,
        "error_msg": result.error_msg,
    }


@router.post("/cancel")
async def cancel_order(req: CancelRequest) -> dict:
    """Cancel a pending order via EA bridge."""
    result = _broker.cancel_order(
        account_id=req.account_id,
        ticket=req.ticket,
        symbol=req.symbol,
    )
    if not result.success:
        raise HTTPException(status_code=502, detail=result.error_msg)
    return {"success": True, "ticket": result.ticket, "request_id": result.request_id}
