"""Authentication boundary for dashboard BFF business routes.

The BFF accepts only an explicit Bearer credential and delegates validation to
the core API session endpoint.  It deliberately has no local signing secret and
does not accept a browser cookie: the server-side dashboard proxy must make the
caller's authorization explicit before the BFF contacts business dependencies.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.dashboard_bff.http_client import get_client

VIEWER_ROLE = "viewer"
DASHBOARD_READ_SCOPE = "read:dashboard"

_viewer_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="ViewerBearer",
    description="Viewer JWT carrying the read:dashboard scope.",
)


def _has_dashboard_read_scope(payload: dict[str, Any]) -> bool:
    raw_scopes = payload.get("scopes", [])
    if not isinstance(raw_scopes, list):
        return False
    return DASHBOARD_READ_SCOPE in raw_scopes


async def require_bff_authorization(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_viewer_bearer)],
) -> dict[str, Any]:
    """Fail closed unless the caller presents a scoped viewer JWT."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials.strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        response = await get_client().get(
            "/api/auth/session",
            headers={
                "authorization": f"Bearer {token}",
                "accept": "application/json",
                # The shared httpx client may retain Set-Cookie from a previous
                # successful session validation.  Never let core auth fall back
                # to another caller's cookie when validating this Bearer token.
                "cookie": "",
            },
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("user_id"):
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if (
            payload.get("auth_method") != "jwt"
            or payload.get("role") != VIEWER_ROLE
            or not _has_dashboard_read_scope(payload)
        ):
            raise HTTPException(status_code=403, detail="Viewer access required")

        return payload
    except HTTPException:
        raise
    except Exception:
        pass
    raise HTTPException(
        status_code=401,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
