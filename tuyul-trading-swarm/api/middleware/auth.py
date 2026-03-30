"""Auth middleware — JWT + API key verification."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import jwt as pyjwt

JWT_SECRET = os.getenv("DASHBOARD_JWT_SECRET", "change-me-in-production-min-32-chars")
JWT_ALGO = os.getenv("DASHBOARD_JWT_ALGO", "HS256")
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")

_bearer = HTTPBearer(auto_error=False)


async def verify_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Verifikasi JWT atau API key dari request."""
    # Dev mode bypass
    if os.getenv("ENABLE_DEV_ROUTES", "false").lower() == "true":
        return {"user": "dev", "role": "admin"}

    # API Key check
    api_key = request.headers.get("X-API-Key", "")
    if DASHBOARD_API_KEY and api_key == DASHBOARD_API_KEY:
        return {"user": "api_key", "role": "service"}

    # JWT check
    if credentials:
        try:
            payload = pyjwt.decode(
                credentials.credentials,
                JWT_SECRET,
                algorithms=[JWT_ALGO],
            )
            return payload
        except pyjwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
            )
        except pyjwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


def create_access_token(user: str, role: str = "viewer") -> str:
    """Buat JWT token untuk user."""
    import time
    ttl = int(os.getenv("DASHBOARD_TOKEN_EXPIRE_MIN", "60"))
    payload = {
        "user": user,
        "role": role,
        "exp": int(time.time()) + (ttl * 60),
        "iat": int(time.time()),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
