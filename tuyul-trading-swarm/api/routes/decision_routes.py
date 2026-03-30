"""Decision routes — submit trade candidate dan baca decision history."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from agents.orchestrator import TradingOrchestratorAgent
from api.middleware.auth import verify_token
from core.memory_fabric import get_memory_fabric
from core.shift_manager import get_shift_manager
from schemas.trade_candidate import TradeCandidate

router = APIRouter(prefix="/api/v1/decisions", tags=["decisions"])
_orchestrator = TradingOrchestratorAgent()


@router.post("/evaluate")
async def evaluate_candidate(
    payload: dict[str, Any],
    _: dict = Depends(verify_token),
) -> dict[str, Any]:
    """Submit trade candidate untuk dievaluasi oleh semua agent."""
    # Generate candidate_id jika tidak ada
    if "candidate_id" not in payload:
        payload["candidate_id"] = str(uuid.uuid4())
    if "submitted_at" not in payload:
        payload["submitted_at"] = datetime.utcnow().isoformat()

    try:
        candidate = TradeCandidate(**payload)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid candidate: {e}")

    packet = await _orchestrator.run_full_cycle(candidate)
    return packet.dict()


@router.get("/today")
async def decisions_today(_: dict = Depends(verify_token)) -> dict[str, Any]:
    """Semua keputusan hari ini."""
    journal = _orchestrator.journal
    summary = await journal.get_daily_summary()
    return summary


@router.get("/date/{date_str}")
async def decisions_by_date(date_str: str, _: dict = Depends(verify_token)) -> dict[str, Any]:
    """Keputusan pada tanggal tertentu (format: YYYY-MM-DD)."""
    journal = _orchestrator.journal
    return await journal.get_daily_summary(date_str)


@router.get("/watchlist")
async def get_watchlist(_: dict = Depends(verify_token)) -> dict[str, Any]:
    """Semua setup dalam watchlist aktif."""
    memory = get_memory_fabric()
    watchlist = await memory.get_all_watchlist()
    return {"watchlist": watchlist, "count": len(watchlist)}


@router.delete("/watchlist/{candidate_id}")
async def remove_watchlist(candidate_id: str, _: dict = Depends(verify_token)) -> dict[str, Any]:
    """Hapus entry dari watchlist."""
    memory = get_memory_fabric()
    await memory.remove_watchlist(candidate_id)
    return {"status": "removed", "candidate_id": candidate_id}


@router.get("/handoff")
async def get_latest_handoff(_: dict = Depends(verify_token)) -> dict[str, Any]:
    """Handoff summary terakhir."""
    memory = get_memory_fabric()
    handoff = await memory.get_last_handoff()
    if not handoff:
        return {"message": "No handoff data available yet"}
    return handoff


@router.post("/handoff/produce")
async def produce_handoff(_: dict = Depends(verify_token)) -> dict[str, Any]:
    """Produksi handoff summary sekarang (dipanggil saat shift berganti)."""
    summary = await _orchestrator.produce_handoff()
    return summary
