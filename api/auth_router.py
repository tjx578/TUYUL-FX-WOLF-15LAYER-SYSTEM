"""
Auth Router — session validation and token refresh.

Endpoints:
  GET  /auth/session  — validate JWT, return SessionUser payload.
  POST /auth/refresh  — issue a fresh JWT from a still-valid token.

The dashboard frontend (Next.js) calls these on every page render and
on periodic client-side refresh.  The response shape matches the Zod
``SessionUserSchema`` defined in dashboard/nextjs/src/schema/authSchema.ts:

    { user_id: str, email: str, role: str, name?: str }
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.middleware.auth import create_token, decode_token, verify_token

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Response model ────────────────────────────────────────────────────────────

class SessionUserResponse(BaseModel):
    """Matches the frontend SessionUserSchema (Zod)."""

    user_id: str = Field(..., min_length=1)
    email: str
    role: str
    name: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _session_from_payload(payload: dict[str, Any]) -> SessionUserResponse:
    """
    Extract SessionUser fields from a decoded JWT payload.

    The JWT ``sub`` claim is used as ``user_id``.  ``email``, ``role``, and
    ``name`` are pulled from extra claims embedded at token-creation time.
    Falls back to sensible defaults so the endpoint never 500s for a valid JWT.
    """
    return SessionUserResponse(
        user_id=str(payload.get("sub", "unknown")),
        email=str(payload.get("email", payload.get("sub", "unknown"))),
        role=str(payload.get("role", "viewer")),
        name=payload.get("name"),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/session", response_model=SessionUserResponse)
async def get_session(
    payload: dict[str, Any] = Depends(verify_token),
) -> SessionUserResponse:
    """
    Validate the caller's JWT / API key and return the session user.

    Used by the Next.js server-side ``getVerifiedSessionUser()`` on every
    page render.  Returns 401 (via ``verify_token``) when the token is
    missing, expired, or invalid.
    """
    return _session_from_payload(payload)


@router.post("/refresh", response_model=SessionUserResponse)
async def refresh_session(
    payload: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    """
    Issue a fresh JWT from a still-valid token.

    The old token must still be valid (not expired).  A brand-new token is
    created with the same claims and a reset expiry window.  The response
    includes both the new ``token`` and the ``SessionUser`` fields so the
    client can update its store in one round-trip.
    """
    # Preserve claims from the original token
    extra: dict[str, Any] = {}
    for key in ("email", "role", "name"):
        if key in payload:
            extra[key] = payload[key]

    new_token = create_token(sub=str(payload.get("sub", "dashboard")), extra=extra or None)
    user = _session_from_payload(payload)

    return {
        "token": new_token,
        **user.model_dump(),
    }
