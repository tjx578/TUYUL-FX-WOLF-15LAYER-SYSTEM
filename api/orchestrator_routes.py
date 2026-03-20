"""Orchestrator state read endpoints for dashboard monitoring.

Reads the orchestrator state from Redis (published by state_manager).
No write authority — mode changes only via orchestrator pub/sub commands.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from fastapi import APIRouter, Depends

from infrastructure.redis_client import get_async_redis
from state.redis_keys import ORCHESTRATOR_STATE

from .middleware.auth import verify_token

router = APIRouter(dependencies=[Depends(verify_token)])


def _parse_orchestrator_health(payload: dict[str, Any]) -> tuple[float | None, bool]:
    """Return (heartbeat_age_seconds, ready) derived from orchestrator payload."""
    now = time.time()
    heartbeat_interval_sec = max(5.0, float(os.getenv("ORCHESTRATOR_HEARTBEAT_INTERVAL_SEC", "30")))
    max_age_sec = max(15.0, heartbeat_interval_sec * 3.0)

    ts_raw = payload.get("timestamp")
    if ts_raw is None:
        return None, False
    try:
        ts = float(ts_raw)
    except (TypeError, ValueError):
        return None, False

    if ts <= 0:
        return None, False

    age = max(0.0, now - ts)
    return round(age, 2), age <= max_age_sec


@router.get("/api/v1/orchestrator/state")
async def get_orchestrator_state() -> dict[str, Any]:
    """Return the current orchestrator governance state from Redis."""
    redis = await get_async_redis()
    raw = await redis.get(ORCHESTRATOR_STATE)
    if not raw:
        return {
            "mode": "UNKNOWN",
            "reason": "no orchestrator state published yet",
            "compliance_code": "NONE",
            "orchestrator_heartbeat_age_seconds": None,
            "orchestrator_ready": False,
        }
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {
            "mode": "UNKNOWN",
            "reason": "invalid orchestrator state in Redis",
            "compliance_code": "PARSE_ERROR",
            "orchestrator_heartbeat_age_seconds": None,
            "orchestrator_ready": False,
        }

    heartbeat_age_seconds, orchestrator_ready = _parse_orchestrator_health(payload)
    return {
        "mode": payload.get("mode", "UNKNOWN"),
        "reason": payload.get("reason", ""),
        "compliance_code": payload.get("compliance_code", ""),
        "updated_at": payload.get("updated_at", ""),
        "event": payload.get("event", ""),
        "orchestrator_heartbeat_age_seconds": heartbeat_age_seconds,
        "orchestrator_ready": orchestrator_ready,
    }
