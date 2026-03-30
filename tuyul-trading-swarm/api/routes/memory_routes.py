"""Memory routes — akses ke shared memory fabric."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from agents.memory_handoff import MemoryHandoffAgent
from api.middleware.auth import verify_token
from core.memory_fabric import get_memory_fabric

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])
_memory_agent = MemoryHandoffAgent()


@router.get("/context")
async def full_context(_: dict = Depends(verify_token)) -> dict[str, Any]:
    """Full memory context dari semua namespace."""
    return await _memory_agent.get_full_context()


@router.get("/open-trades")
async def open_trades(_: dict = Depends(verify_token)) -> dict[str, Any]:
    memory = get_memory_fabric()
    trades = await memory.get_open_trades()
    return {"open_trades": trades, "count": len(trades)}


@router.delete("/open-trades/{trade_id}")
async def close_trade(trade_id: str, _: dict = Depends(verify_token)) -> dict[str, Any]:
    memory = get_memory_fabric()
    await memory.close_trade(trade_id)
    return {"status": "closed", "trade_id": trade_id}


@router.get("/psychology-warnings")
async def psychology_warnings(_: dict = Depends(verify_token)) -> dict[str, Any]:
    memory = get_memory_fabric()
    warnings = await memory.get_psychology_warnings()
    return {"warnings": warnings, "count": len(warnings)}


@router.post("/psychology-warnings/clear")
async def clear_psychology_warnings(_: dict = Depends(verify_token)) -> dict[str, Any]:
    memory = get_memory_fabric()
    await memory.clear_psychology_warnings()
    return {"status": "cleared"}


@router.get("/audit-flags")
async def audit_flags(_: dict = Depends(verify_token)) -> dict[str, Any]:
    memory = get_memory_fabric()
    flags = await memory.get_audit_flags()
    return {"flags": flags, "count": len(flags)}


@router.get("/upcoming-events")
async def upcoming_events(_: dict = Depends(verify_token)) -> dict[str, Any]:
    memory = get_memory_fabric()
    events = await memory.get_upcoming_events()
    return {"events": events, "count": len(events)}


@router.post("/upcoming-events")
async def set_upcoming_events(events: list[dict[str, Any]], _: dict = Depends(verify_token)) -> dict:
    """Update daftar upcoming events (dari news agent atau manual input)."""
    memory = get_memory_fabric()
    await memory.set_upcoming_events(events)
    return {"status": "updated", "count": len(events)}
