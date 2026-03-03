from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config.profile_engine import ConfigProfileEngine

router = APIRouter(prefix="/api/v1/config/profiles", tags=["config-profile"])

_engine = ConfigProfileEngine()


class ActivateProfileRequest(BaseModel):
    profile_name: str = Field(..., min_length=1)


@router.get("")
async def list_profiles() -> dict:
    return {
        "active_profile": _engine.get_active_profile(),
        "profiles": _engine.list_profiles(),
    }


@router.get("/active")
async def get_active_profile() -> dict:
    return {
        "active_profile": _engine.get_active_profile(),
        "effective_config": _engine.get_effective_config(),
    }


@router.post("/active")
async def activate_profile(req: ActivateProfileRequest) -> dict:
    try:
        return _engine.activate(req.profile_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
