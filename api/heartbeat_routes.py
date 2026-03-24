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

import datetime
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends

from core.redis_keys import ENGINE_HEARTBEAT_SIMPLE, L12_VERDICT_META_PREFIX
from infrastructure.redis_client import get_async_redis
from state.heartbeat_classifier import (
    HeartbeatState,
    read_all_heartbeats,
    read_ingest_health,
)

from .middleware.auth import verify_token

logger = logging.getLogger(__name__)

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


@router.get("/engine")
async def engine_diagnostic() -> dict[str, Any]:
    """Engine operational diagnostics — last heartbeat timestamp and per-pair verdict metadata.

    Response shape::

        {
            "engine_heartbeat_utc": "<ISO UTC string> | null",
            "engine_heartbeat_age_seconds": <float> | null,
            "verdict_meta": {
                "<PAIR>": { "verdict": ..., "confidence": ..., "cached_at": ... },
                ...
            }
        }
    """
    redis = await get_async_redis()

    # Read simple UTC heartbeat key
    engine_hb_raw: str | None = None
    engine_hb_age: float | None = None
    try:
        engine_hb_raw = await redis.get(ENGINE_HEARTBEAT_SIMPLE)
        if engine_hb_raw:
            hb_dt = datetime.datetime.fromisoformat(engine_hb_raw.strip())
            now_dt = datetime.datetime.now(datetime.UTC)
            engine_hb_age = round((now_dt - hb_dt).total_seconds(), 2)
    except Exception as exc:
        logger.warning("[heartbeat/engine] Failed to read ENGINE:HEARTBEAT: %s", exc)

    # Read all L12:VERDICT_META:* keys for per-pair verdict metadata
    verdict_meta: dict[str, Any] = {}
    try:
        pattern = f"{L12_VERDICT_META_PREFIX}*"
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                raw = await redis.get(key)
                if raw:
                    try:
                        pair_meta = json.loads(raw)
                        pair = str(key).replace(L12_VERDICT_META_PREFIX, "")
                        verdict_meta[pair] = pair_meta
                    except (json.JSONDecodeError, TypeError) as exc:
                        logger.debug("[heartbeat/engine] Malformed verdict meta for key %s: %s", key, exc)
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning("[heartbeat/engine] Failed to scan L12:VERDICT_META:*: %s", exc)

    return {
        "engine_heartbeat_utc": engine_hb_raw,
        "engine_heartbeat_age_seconds": engine_hb_age,
        "verdict_meta": verdict_meta,
    }
