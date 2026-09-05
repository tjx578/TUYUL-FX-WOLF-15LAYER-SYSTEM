"""Authentication boundary for dashboard BFF business routes.

The BFF accepts only an explicit Bearer credential and delegates validation to
the core API session endpoint.  It deliberately has no local signing secret and
does not accept a browser cookie: the server-side dashboard proxy must make the
caller's authorization explicit before the BFF contacts business dependencies.
"""

from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException

from services.dashboard_bff.http_client import get_client


async def require_bff_authorization(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Fail closed unless *authorization* is a valid Bearer credential."""
    scheme, _, token = (authorization or "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Authentication required")

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
        if response.status_code == 200:
            payload = response.json()
            if isinstance(payload, dict) and payload.get("user_id"):
                return payload
    except Exception:
        pass
    raise HTTPException(status_code=401, detail="Invalid credentials")
