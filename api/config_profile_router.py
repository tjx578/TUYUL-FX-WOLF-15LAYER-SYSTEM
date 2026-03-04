from __future__ import annotations

from typing import Annotated, Any

from fastapi import HTTPException, Query
from fastapi.params import Depends
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field

from api.middleware.auth import verify_token
from api.middleware.governance import GovernanceContext, enforce_write_policy
from config.profile_engine import ConfigProfileEngine
from journal.audit_trail import AuditAction, AuditTrail

router: APIRouter = APIRouter(prefix="/api/v1/config/profiles", tags=["config-profile"])

_engine = ConfigProfileEngine()
_audit = AuditTrail()


class ActivateProfileRequest(BaseModel):
    profile_name: str = Field(..., min_length=1)


class OverrideUpsertRequest(BaseModel):
    scope: str = Field(..., pattern="^(global|account|prop_firm|pair)$")
    scope_key: str = Field(..., min_length=1)
    override: dict[str, Any]


class ConfigLockRequest(BaseModel):
    locked: bool


@router.get("", dependencies=[Depends(verify_token)])
async def list_profiles() -> dict[str, Any]:
    return {
        "active_profile": _engine.get_active_profile(),
        "profiles": _engine.list_profiles(),
        "scopes": _engine.list_scoped_overrides(),
        "locked": _engine.is_locked(),
    }


@router.get("/active", dependencies=[Depends(verify_token)])
async def get_active_profile() -> dict[str, Any]:
    return {
        "active_profile": _engine.get_active_profile(),
        "locked": _engine.is_locked(),
        "effective_config": _engine.get_effective_config(
            account_id=None,
            prop_firm=None,
            pair=None,
        ),
    }


@router.get("/effective", dependencies=[Depends(verify_token)])
async def get_effective_profile(
    account_id: Annotated[str | None, Query()] = None,
    prop_firm: Annotated[str | None, Query()] = None,
    pair: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    return {
        "active_profile": _engine.get_active_profile(),
        "locked": _engine.is_locked(),
        "scope": {
            "account_id": account_id,
            "prop_firm": prop_firm,
            "pair": pair,
        },
        "effective_config": _engine.get_effective_config(
            account_id=account_id,
            prop_firm=prop_firm,
            pair=pair,
        ),
    }


@router.get("/revisions", dependencies=[Depends(verify_token)])
async def list_config_revisions(limit: Annotated[int, Query(ge=1, le=500)] = 50) -> dict[str, Any]:
    return {
        "count": min(limit, len(_engine.list_revisions(limit=limit))),
        "revisions": _engine.list_revisions(limit=limit),
    }


@router.post("/active", dependencies=[Depends(verify_token)])
async def activate_profile(
    req: ActivateProfileRequest,
    context: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> dict[str, Any]:
    try:
        result = _engine.activate(req.profile_name, actor=context.actor, reason=context.reason)
        _audit.log(
            AuditAction.ORDER_MODIFIED,
            actor=context.actor,
            resource="config:profiles",
            details={"action": "ACTIVATE_PROFILE", "reason": context.reason, "result": result},
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/override", dependencies=[Depends(verify_token)])
async def upsert_override(
    req: OverrideUpsertRequest,
    context: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> dict[str, Any]:
    try:
        result = _engine.upsert_override(
            req.scope,
            req.scope_key,
            req.override,
            actor=context.actor,
            reason=context.reason,
        )
        _audit.log(
            AuditAction.ORDER_MODIFIED,
            actor=context.actor,
            resource=f"config:override:{req.scope}:{req.scope_key}",
            details={"action": "UPSERT_OVERRIDE", "reason": context.reason, "result": result},
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/override", dependencies=[Depends(verify_token)])
async def delete_override(
    scope: Annotated[str, Query(pattern="^(global|account|prop_firm|pair)$")],
    scope_key: Annotated[str, Query(min_length=1)],
    context: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> dict[str, Any]:
    try:
        result = _engine.delete_override(
            scope,
            scope_key,
            actor=context.actor,
            reason=context.reason,
        )
        _audit.log(
            AuditAction.ORDER_MODIFIED,
            actor=context.actor,
            resource=f"config:override:{scope}:{scope_key}",
            details={"action": "DELETE_OVERRIDE", "reason": context.reason, "result": result},
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/lock", dependencies=[Depends(verify_token)])
async def lock_config(
    req: ConfigLockRequest,
    context: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> dict[str, Any]:
    result = _engine.set_lock(req.locked, actor=context.actor, reason=context.reason)
    _audit.log(
        AuditAction.ORDER_MODIFIED,
        actor=context.actor,
        resource="config:lock",
        details={"action": "SET_LOCK", "reason": context.reason, "result": result},
    )
    return result
