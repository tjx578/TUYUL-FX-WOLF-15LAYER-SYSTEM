from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.middleware.governance import enforce_write_policy
from config.profile_engine import ConfigProfileEngine

router = APIRouter(prefix="/api/v1/config/profiles", tags=["config-profile"])

_engine = ConfigProfileEngine()


class ActivateProfileRequest(BaseModel):
    profile_name: str = Field(..., min_length=1)


class OverrideUpsertRequest(BaseModel):
    scope: str = Field(..., pattern="^(global|account|prop_firm|pair)$")
    scope_key: str = Field(..., min_length=1)
    override: dict


class ConfigLockRequest(BaseModel):
    locked: bool


@router.get("")
async def list_profiles() -> dict:
    return {
        "active_profile": _engine.get_active_profile(),
        "profiles": _engine.list_profiles(),
        "scopes": _engine.list_scoped_overrides(),
        "locked": _engine.is_locked(),
    }


@router.get("/active")
async def get_active_profile() -> dict:
    return {
        "active_profile": _engine.get_active_profile(),
        "locked": _engine.is_locked(),
        "effective_config": _engine.get_effective_config(
            account_id=None,
            prop_firm=None,
            pair=None,
        ),
    }


@router.get("/effective")
async def get_effective_profile(
    account_id: str | None = Query(default=None),
    prop_firm: str | None = Query(default=None),
    pair: str | None = Query(default=None),
) -> dict:
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


@router.post("/active", dependencies=[Depends(enforce_write_policy)])
async def activate_profile(req: ActivateProfileRequest) -> dict:
    try:
        return _engine.activate(req.profile_name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/override", dependencies=[Depends(enforce_write_policy)])
async def upsert_override(req: OverrideUpsertRequest) -> dict:
    try:
        return _engine.upsert_override(req.scope, req.scope_key, req.override)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/override", dependencies=[Depends(enforce_write_policy)])
async def delete_override(
    scope: str = Query(..., pattern="^(global|account|prop_firm|pair)$"),
    scope_key: str = Query(..., min_length=1),
) -> dict:
    try:
        return _engine.delete_override(scope, scope_key)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/lock", dependencies=[Depends(enforce_write_policy)])
async def lock_config(req: ConfigLockRequest) -> dict:
    return _engine.set_lock(req.locked)
