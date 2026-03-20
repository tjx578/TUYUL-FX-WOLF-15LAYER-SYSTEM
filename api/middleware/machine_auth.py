"""Machine-auth dependency for observability endpoints.

Separates machine scraping credentials from dashboard user JWT/API-key auth.
This dependency is intended for infrastructure endpoints such as:
  - /metrics
  - /healthz
  - /readyz

Behavior is controlled by env vars:
  - OBSERVABILITY_AUTH_MODE: disabled | optional | required (default: optional)
  - OBSERVABILITY_MACHINE_KEY or MACHINE_OBSERVABILITY_KEY: shared secret

Modes:
  - disabled: never enforce machine auth
  - optional: enforce only when machine key env var is configured
  - required: always enforce, and fail closed when key is missing
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import Header, HTTPException, Request


def _is_production_runtime() -> bool:
    env = os.getenv("APP_ENV", os.getenv("ENV", os.getenv("RAILWAY_ENVIRONMENT", "development"))).strip().lower()
    return env == "production"


def _resolve_active_profile_name() -> str | None:
    try:
        from config.profile_engine import ConfigProfileEngine

        profile = ConfigProfileEngine().get_active_profile().strip().lower()
        return profile or None
    except Exception:
        return None


def _is_production_profile() -> bool:
    active_profile = _resolve_active_profile_name()
    return active_profile in {"production", "prod"}


def _resolve_auth_mode() -> str:
    raw = os.getenv("OBSERVABILITY_AUTH_MODE", "optional").strip().lower()
    mode = raw if raw in {"disabled", "optional", "required"} else "optional"
    if (_is_production_runtime() or _is_production_profile()) and mode != "required":
        return "required"
    return mode


def _resolve_machine_key() -> str:
    return os.getenv("OBSERVABILITY_MACHINE_KEY", "").strip() or os.getenv("MACHINE_OBSERVABILITY_KEY", "").strip()


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def verify_observability_machine_auth(
    request: Request,
    authorization: str | None = Header(default=None),
    x_machine_key: str | None = Header(default=None, alias="X-Machine-Key"),
) -> dict[str, Any]:
    """Authorize machine consumers for observability endpoints only."""
    _ = request
    mode = _resolve_auth_mode()
    if mode == "disabled":
        return {"auth_mode": mode, "machine_authenticated": False}

    expected_key = _resolve_machine_key()
    if not expected_key:
        if mode == "required":
            raise HTTPException(
                status_code=503,
                detail="Observability machine auth misconfigured: missing OBSERVABILITY_MACHINE_KEY",
            )
        return {"auth_mode": mode, "machine_authenticated": False}

    presented = (x_machine_key or "").strip() or (_extract_bearer_token(authorization) or "")
    if not presented or not hmac.compare_digest(presented, expected_key):
        raise HTTPException(status_code=401, detail="Machine auth required")

    return {
        "sub": "machine_observability",
        "auth_method": "machine_key",
        "auth_mode": mode,
        "machine_authenticated": True,
    }
