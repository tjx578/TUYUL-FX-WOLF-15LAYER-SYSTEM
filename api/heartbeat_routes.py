"""Heartbeat status endpoint — exposes producer heartbeat ages.

Zones: dashboard (monitoring/ops) — no market logic, no execution authority.

Reads ingest and engine heartbeat keys from Redis and classifies them
so the dashboard and external monitors can distinguish no-producer from
stale-preserved or quiet-market conditions.

The ingest service exposes two independent heartbeat signals:
    * ``ingest:process``  — always written while the service is alive.
    * ``ingest:provider`` — only written when WS provider is connected.

This eliminates weekend false-positives where the service is alive but
the provider is deliberately idle.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends

from infrastructure.redis_client import get_async_redis
from state.heartbeat_classifier import (
    HeartbeatState,
    read_all_heartbeats,
    read_ingest_health,
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
            "ingest_health": "HEALTHY" | "DEGRADED" | "NO_PRODUCER",
            "services": {
                "ingest": { ... },
                "ingest_process": { ... },
                "ingest_provider": { ... },
                "engine": { ... }
            }
        }
    """
    redis = await get_async_redis()
    statuses = await read_all_heartbeats(redis)
    ingest_health = await read_ingest_health(redis)

    services: dict[str, dict[str, Any]] = {}
    for svc_name, status in statuses.items():
        services[svc_name] = {
            "state": status.state.value,
            "age_seconds": status.age_seconds,
            "producer": status.producer,
            "last_ts": status.last_ts,
        }

    # Derive overall status using split ingest health + engine heartbeat
    engine_status = statuses.get("engine")
    engine_alive = engine_status is not None and engine_status.state == HeartbeatState.ALIVE

    if ingest_health.state.value == "HEALTHY" and engine_alive:
        overall = "HEALTHY"
    elif ingest_health.state.value == "NO_PRODUCER" or not engine_alive:
        overall = "NO_PRODUCER"
    else:
        overall = "DEGRADED"

    return {
        "overall": overall,
        "ingest_health": ingest_health.state.value,
        "timestamp": time.time(),
        "services": services,
    }
