"""Governance routes — audit dan compliance reporting."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from agents.audit_governance import AuditGovernanceAgent
from api.middleware.auth import verify_token

router = APIRouter(prefix="/api/v1/governance", tags=["governance"])
_audit_agent = AuditGovernanceAgent()


@router.get("/report")
async def governance_report(_: dict = Depends(verify_token)) -> dict:
    """Laporan governance — audit flags, violations, dan rekomendasi."""
    return await _audit_agent.get_governance_report()
