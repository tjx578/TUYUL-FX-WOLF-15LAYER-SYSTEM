"""Dedicated machine authentication for the public MT5 executor bridge."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from fastapi import Header, HTTPException

_TOKEN_CONTEXT = "wolf15-executor-token-v1"


def _resolve_secrets() -> tuple[str, ...]:
    current = os.getenv("EXECUTOR_BRIDGE_AUTH_SECRET", "").strip()
    previous = os.getenv("EXECUTOR_BRIDGE_AUTH_SECRET_PREVIOUS", "").strip()
    return tuple(value for value in (current, previous) if value)


def derive_executor_token(executor_id: str, *, secret: str) -> str:
    """Derive a scoped bearer token without storing raw per-executor keys."""

    if len(secret.encode("utf-8")) < 32:
        raise ValueError("executor auth secret must be at least 32 bytes")
    message = f"{_TOKEN_CONTEXT}:{executor_id}".encode()
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_executor_auth(
    authorization: str | None = Header(default=None),
    x_executor_id: str | None = Header(default=None, alias="X-Executor-Id"),
) -> dict[str, Any]:
    """Authenticate an executor and bind the credential to its executor id."""

    executor_id = (x_executor_id or "").strip()
    if not executor_id:
        raise HTTPException(status_code=401, detail="X-Executor-Id is required")

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Executor bearer token is required")

    secrets = _resolve_secrets()
    if not secrets:
        raise HTTPException(status_code=503, detail="Executor authentication is not configured")

    presented = token.strip()
    for secret in secrets:
        try:
            expected = derive_executor_token(executor_id, secret=secret)
        except ValueError:
            continue
        if hmac.compare_digest(presented, expected):
            return {
                "sub": f"executor:{executor_id}",
                "executor_id": executor_id,
                "auth_method": "derived_hmac_token",
            }

    raise HTTPException(status_code=401, detail="Invalid executor credentials")


__all__ = ["derive_executor_token", "verify_executor_auth"]
