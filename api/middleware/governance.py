from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request

from api.middleware.auth import decode_token, validate_api_key
from storage.redis_client import redis_client

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CRITICAL_PATH_PARTS = (
    "/kill-switch",
    "/close-all",
    "/ea/restart",
    "/ea/safe-mode",
    "/config/profiles/lock",
)
SAFE_MODE_CLOSE_ALLOWLIST = (
    "/trades/close",
    "/operator/close",
)
ALLOWED_ROLES = {"viewer", "trader", "admin"}


@dataclass(frozen=True)
class GovernanceContext:
    role: str
    actor: str
    auth_method: str


def _parse_authorization(authorization: str | None) -> tuple[str, str] | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return scheme, token


def _is_critical_path(path: str) -> bool:
    lowered = path.lower()
    return any(part in lowered for part in CRITICAL_PATH_PARTS)


def _safe_mode_enabled() -> bool:
    try:
        raw = redis_client.client.get("EA:SAFE_MODE")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        return str(raw or "0").strip().lower() in {"1", "true", "on", "enabled"}
    except Exception:
        return False


def _allow_during_safe_mode(path: str) -> bool:
    lowered = path.lower()
    return any(part in lowered for part in SAFE_MODE_CLOSE_ALLOWLIST)


def _resolve_context(token: str) -> GovernanceContext:
    payload = decode_token(token)
    if payload is not None:
        role_raw = payload.get("role")
        if role_raw is None:
            raise HTTPException(status_code=403, detail="JWT missing required role claim")

        role = str(role_raw).strip().lower()
        if role not in ALLOWED_ROLES:
            raise HTTPException(status_code=403, detail=f"JWT role is invalid: {role}")

        required_issuer = os.getenv("DASHBOARD_JWT_REQUIRED_ISSUER", "").strip()
        if required_issuer:
            token_issuer = str(payload.get("iss") or "").strip()
            allowed_issuers = {i.strip() for i in required_issuer.split(",") if i.strip()}
            if token_issuer not in allowed_issuers:
                raise HTTPException(status_code=403, detail="JWT issuer is not allowed")

        actor = str(payload.get("sub") or "user:unknown")
        return GovernanceContext(role=role, actor=actor, auth_method="jwt")

    if validate_api_key(token):
        return GovernanceContext(role="admin", actor="api_key_user", auth_method="api_key")

    raise HTTPException(status_code=401, detail="Invalid or expired token")


async def enforce_write_policy(
    request: Request,
    authorization: str | None = Header(default=None),
    x_edit_mode: str | None = Header(default=None, alias="X-Edit-Mode"),
    x_action_reason: str | None = Header(default=None, alias="X-Action-Reason"),
    x_action_pin: str | None = Header(default=None, alias="X-Action-Pin"),
) -> GovernanceContext | None:
    """
    Enforce global edit-mode policy for WRITE operations only.

    Rules:
    - Edit mode header must be ON for write actions.
    - Every write must include reason header.
    - Viewer is read-only.
    - Critical actions require PIN.
    - Safe mode blocks all writes except close actions.
    """
    if request.method.upper() not in WRITE_METHODS:
        return None

    parsed = _parse_authorization(authorization)
    if not parsed:
        raise HTTPException(status_code=401, detail="Missing Authorization header for write action")
    _, token = parsed
    context = _resolve_context(token)

    if context.role not in {"trader", "admin"}:
        raise HTTPException(status_code=403, detail="Role does not permit write operations")

    if str(x_edit_mode or "").strip().upper() != "ON":
        raise HTTPException(status_code=403, detail="Edit Mode is OFF. Set X-Edit-Mode: ON")

    reason = (x_action_reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="Missing X-Action-Reason for write operation")

    if _safe_mode_enabled() and not _allow_during_safe_mode(request.url.path):
        raise HTTPException(status_code=423, detail="EA safe mode active: write actions are blocked")

    if _is_critical_path(request.url.path):
        expected_pin = os.getenv("DASHBOARD_ACTION_PIN", "").strip()
        if not expected_pin:
            raise HTTPException(status_code=503, detail="Critical action PIN is not configured")
        if (x_action_pin or "").strip() != expected_pin:
            raise HTTPException(status_code=403, detail="Invalid or missing X-Action-Pin")

    return context
