"""
Settings Governance API Routes — P1-8
=======================================
GET  /api/v1/settings/{domain}          — Read current settings
POST /api/v1/settings/{domain}          — Update settings (requires reason, changed_by)
POST /api/v1/settings/{domain}/rollback — Rollback to a previous version
GET  /api/v1/settings/{domain}/audit    — Audit history

Zone: API — settings governance, no verdict authority.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from api.middleware.governance import enforce_write_policy
from api.settings_governance import (
    SettingsAuditEntry,
    SettingsGovernanceService,
    SettingsResponse,
    SettingsRollbackRequest,
    SettingsWriteRequest,
)
from contracts.api_response_schema import ApiResponse

from .middleware.auth import verify_token

router = APIRouter(
    prefix="/api/v1/settings",
    tags=["settings-governance"],
    dependencies=[Depends(verify_token)],
)

_service: SettingsGovernanceService | None = None


def _get_service() -> SettingsGovernanceService:
    global _service
    if _service is None:
        _service = SettingsGovernanceService()
    return _service


@router.get(
    "/{domain}",
    response_model=ApiResponse[SettingsResponse],
    summary="Read current settings for a domain",
)
async def get_settings(domain: str) -> ApiResponse[SettingsResponse]:
    svc = _get_service()
    try:
        response = await svc.get_settings(domain)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if response is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No settings found for domain: {domain}",
        )
    return ApiResponse(ok=True, data=response)


@router.post(
    "/{domain}",
    response_model=ApiResponse[SettingsResponse],
    dependencies=[Depends(enforce_write_policy)],
    summary="Update settings (requires reason and changed_by)",
)
async def update_settings(
    domain: str,
    body: SettingsWriteRequest,
) -> ApiResponse[SettingsResponse]:
    svc = _get_service()
    try:
        response = await svc.update_settings(domain, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(ok=True, data=response)


@router.post(
    "/{domain}/rollback",
    response_model=ApiResponse[SettingsResponse],
    dependencies=[Depends(enforce_write_policy)],
    summary="Rollback settings to a previous version",
)
async def rollback_settings(
    domain: str,
    body: SettingsRollbackRequest,
) -> ApiResponse[SettingsResponse]:
    svc = _get_service()
    try:
        response = await svc.rollback_settings(domain, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(ok=True, data=response)


@router.get(
    "/{domain}/audit",
    response_model=ApiResponse[list[SettingsAuditEntry]],
    summary="Get settings audit history for a domain",
)
async def get_audit_history(
    domain: str,
    limit: int = 50,
) -> ApiResponse[list[SettingsAuditEntry]]:
    svc = _get_service()
    try:
        entries = await svc.get_audit_history(domain, min(limit, 200))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApiResponse(ok=True, data=entries)
