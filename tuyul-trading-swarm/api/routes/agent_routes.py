"""Agent routes — status dan kontrol semua agent dalam swarm."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from agents.orchestrator import TradingOrchestratorAgent
from api.middleware.auth import verify_token
from core.shift_manager import get_shift_manager

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])
_orchestrator = TradingOrchestratorAgent()


@router.get("/status")
async def all_agents_status(_: dict = Depends(verify_token)) -> dict:
    """Status semua 12 agent dalam swarm."""
    agents = _orchestrator.agents_status()
    shift_status = get_shift_manager().status_summary()
    return {
        "agents": agents,
        "total": len(agents),
        "shift": shift_status,
        "active_agents": shift_status["active_agents"],
    }


@router.get("/shift")
async def current_shift(_: dict = Depends(verify_token)) -> dict:
    """Status shift dan session aktif saat ini."""
    return get_shift_manager().status_summary()


@router.get("/{agent_name}/status")
async def single_agent_status(agent_name: str, _: dict = Depends(verify_token)) -> dict:
    """Status satu agent spesifik."""
    all_agents = _orchestrator.agents_status()
    agent = next((a for a in all_agents if a["agent_name"] == agent_name), None)
    if not agent:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
    return agent
