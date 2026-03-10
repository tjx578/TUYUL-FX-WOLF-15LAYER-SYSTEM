"""Orchestrator state read endpoints for dashboard monitoring.

Reads the orchestrator state from Redis (published by state_manager).
No write authority — mode changes only via orchestrator pub/sub commands.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends

from api.middleware.auth import verify_token
from infrastructure.redis_client import get_async_redis

router = APIRouter(dependencies=[Depends(verify_token)])

_STATE_KEY = "wolf15:orchestrator:state"


@router.get("/api/v1/orchestrator/state")
async def get_orchestrator_state() -> dict[str, Any]:
    """Return the current orchestrator governance state from Redis."""
    redis = await get_async_redis()
    raw = await redis.get(_STATE_KEY)
    if not raw:
        return {
            "mode": "UNKNOWN",
            "reason": "no orchestrator state published yet",
            "compliance_code": "NONE",
        }
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {
            "mode": "UNKNOWN",
            "reason": "invalid orchestrator state in Redis",
            "compliance_code": "PARSE_ERROR",
        }
    return {
        "mode": payload.get("mode", "UNKNOWN"),
        "reason": payload.get("reason", ""),
        "compliance_code": payload.get("compliance_code", ""),
        "updated_at": payload.get("updated_at", ""),
        "event": payload.get("event", ""),
    }
