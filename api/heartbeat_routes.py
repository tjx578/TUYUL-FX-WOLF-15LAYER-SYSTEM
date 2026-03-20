"""Heartbeat status endpoint — exposes producer heartbeat ages.

Zones: dashboard (monitoring/ops) — no market logic, no execution authority.

Reads ingest and engine heartbeat keys from Redis and classifies them
so the dashboard and external monitors can distinguish no-producer from
stale-preserved or quiet-market conditions.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends

from infrastructure.redis_client import get_async_redis
from state.heartbeat_classifier import (
    HeartbeatState,
    read_all_heartbeats,
)

from .middleware.auth import verify_token

router = APIRouter(prefix="/api/v1/heartbeat", tags=["heartbeat"], dependencies=[Depends(verify_token)])


@router.get("/status")
async def heartbeat_status() -> dict[str, Any]:
    """Return heartbeat age and classification for all known producers.

    Response shape::

        {
            "overall": "HEALTHY" | "DEGRADED" | "NO_PRODUCER",
            "timestamp": <epoch>,
            "services": {
                "ingest": {
                    "state": "ALIVE" | "STALE" | "MISSING",
                    "age_seconds": 4.21,
                    "producer": "finnhub_ws",
                    "last_ts": 1711929600.12
                },
                "engine": { ... }
            }
        }
    """
    redis = await get_async_redis()
    statuses = await read_all_heartbeats(redis)

    services: dict[str, dict[str, Any]] = {}
    for svc_name, status in statuses.items():
        services[svc_name] = {
            "state": status.state.value,
            "age_seconds": status.age_seconds,
            "producer": status.producer,
            "last_ts": status.last_ts,
        }

    # Derive overall status
    states = {s.state for s in statuses.values()}
    if all(s == HeartbeatState.ALIVE for s in states):
        overall = "HEALTHY"
    elif HeartbeatState.MISSING in states:
        overall = "NO_PRODUCER"
    else:
        overall = "DEGRADED"

    return {
        "overall": overall,
        "timestamp": time.time(),
        "services": services,
    }
