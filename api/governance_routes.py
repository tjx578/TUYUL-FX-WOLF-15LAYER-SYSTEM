"""
Governance Routes — ARCH-GAP-10
==================================
API endpoints for feature flags and per-service circuit breakers.

Provides read/write control over:
  - Per-service feature flags (enable/disable/rollout)
  - Per-service circuit breakers (force open/close, status)
  - Maintenance mode (per-service toggle)

All write endpoints require authenticated token (JWT or API key).
Read endpoints are open to any authenticated user.

Zone: API — governance control plane, no market logic.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from storage.redis_client import redis_client

from .middleware.auth import verify_token

router = APIRouter(
    prefix="/api/v1/governance",
    tags=["governance"],
    dependencies=[Depends(verify_token)],
)

# ── Lazy singletons ──────────────────────────────────────────────────────────

_ff_service = None
_cb_registry: dict[str, Any] = {}


def _get_ff():
    global _ff_service  # noqa: PLW0603
    if _ff_service is None:
        from infrastructure.feature_flags import FeatureFlagService  # noqa: PLC0415

        _ff_service = FeatureFlagService(redis_client=redis_client.client)
    return _ff_service


def _get_cb(service: str):
    if service not in _cb_registry:
        from infrastructure.service_circuit_breaker import ServiceCircuitBreaker  # noqa: PLC0415

        _cb_registry[service] = ServiceCircuitBreaker(service=service, redis_client=redis_client.client)
    return _cb_registry[service]


# ── Request/Response models ───────────────────────────────────────────────────


class SetFlagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    rollout_pct: int = Field(default=100, ge=0, le=100)
    reason: str = Field(default="", max_length=512)
    changed_by: str = Field(default="operator", min_length=2, max_length=64)


class CBActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="manual", max_length=512)


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE FLAGS
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/flags/{service}")
async def get_service_flags(service: str) -> dict[str, Any]:
    """Get all feature flags for a service."""
    ff = _get_ff()
    flags = ff.get_all_flags(service)
    return {"service": service, "flags": {k: v.to_dict() for k, v in flags.items()}}


@router.get("/flags/{service}/{flag_name}")
async def get_flag(service: str, flag_name: str) -> dict[str, Any]:
    """Get a single feature flag."""
    ff = _get_ff()
    state = ff.get_flag(service, flag_name)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Flag {service}/{flag_name} not found")
    return {"service": service, "flag": state.to_dict()}


@router.put("/flags/{service}/{flag_name}")
async def set_flag(service: str, flag_name: str, body: SetFlagRequest) -> dict[str, Any]:
    """Set a feature flag for a service."""
    ff = _get_ff()
    state = ff.set_flag(
        service,
        flag_name,
        enabled=body.enabled,
        rollout_pct=body.rollout_pct,
        reason=body.reason,
        changed_by=body.changed_by,
    )
    return {"service": service, "flag": state.to_dict()}


@router.delete("/flags/{service}/{flag_name}")
async def delete_flag(service: str, flag_name: str) -> dict[str, Any]:
    """Delete a feature flag."""
    ff = _get_ff()
    existed = ff.delete_flag(service, flag_name)
    if not existed:
        raise HTTPException(status_code=404, detail=f"Flag {service}/{flag_name} not found")
    return {"deleted": True, "service": service, "flag_name": flag_name}


@router.get("/flags")
async def get_all_flags() -> dict[str, Any]:
    """Get feature flags across all known services."""
    ff = _get_ff()
    all_flags = ff.get_all_services()
    return {
        "services": {
            svc: {k: v.to_dict() for k, v in flags.items()} for svc, flags in all_flags.items()
        }
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MAINTENANCE MODE (convenience over feature flags)
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/maintenance/{service}")
async def get_maintenance_status(service: str) -> dict[str, Any]:
    """Check if a service is in maintenance mode."""
    ff = _get_ff()
    return {"service": service, "maintenance": ff.is_maintenance(service)}


@router.put("/maintenance/{service}/enable")
async def enable_maintenance(service: str, body: CBActionRequest | None = None) -> dict[str, Any]:
    """Enable maintenance mode for a service."""
    ff = _get_ff()
    reason = body.reason if body else "maintenance"
    ff.set_flag(
        service,
        "maintenance_mode",
        enabled=True,
        reason=reason,
        changed_by="operator",
    )
    return {"service": service, "maintenance": True, "reason": reason}


@router.put("/maintenance/{service}/disable")
async def disable_maintenance(service: str) -> dict[str, Any]:
    """Disable maintenance mode for a service."""
    ff = _get_ff()
    ff.set_flag(
        service,
        "maintenance_mode",
        enabled=False,
        reason="maintenance ended",
        changed_by="operator",
    )
    return {"service": service, "maintenance": False}


# ══════════════════════════════════════════════════════════════════════════════
#  SERVICE CIRCUIT BREAKER
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/circuit-breaker/{service}")
async def get_circuit_breaker(service: str) -> dict[str, Any]:
    """Get circuit breaker state for a service."""
    cb = _get_cb(service)
    return {"service": service, "circuit_breaker": cb.snapshot().to_dict()}


@router.put("/circuit-breaker/{service}/open")
async def force_open_cb(service: str, body: CBActionRequest | None = None) -> dict[str, Any]:
    """Force-open the circuit breaker for a service (block calls)."""
    cb = _get_cb(service)
    reason = body.reason if body else "manual"
    cb.force_open(reason=reason)
    return {"service": service, "circuit_breaker": cb.snapshot().to_dict()}


@router.put("/circuit-breaker/{service}/close")
async def force_close_cb(service: str, body: CBActionRequest | None = None) -> dict[str, Any]:
    """Force-close the circuit breaker for a service (allow calls)."""
    cb = _get_cb(service)
    reason = body.reason if body else "manual"
    cb.force_close(reason=reason)
    return {"service": service, "circuit_breaker": cb.snapshot().to_dict()}


@router.put("/circuit-breaker/{service}/reset")
async def reset_cb(service: str) -> dict[str, Any]:
    """Full reset of circuit breaker to CLOSED with zero counters."""
    cb = _get_cb(service)
    cb.reset()
    return {"service": service, "circuit_breaker": cb.snapshot().to_dict()}
