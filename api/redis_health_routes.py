"""
TUYUL FX Wolf-15 — Redis Observability Endpoint
================================================
GET /api/v1/redis/health  — PING latency, connected/blocked clients, ops/sec,
                            slowlog length.

Used to diagnose TCP_OVERWINDOW root cause:
  - High ``blocked_clients``  → consumer-starvation (event-loop blockage)
  - Rising ``latency_ms``     → Redis backpressure or slow operations
  - High ``slowlog_len``      → expensive commands stalling the Redis server

All reads go through ``request.app.state.redis`` (the lifecycle-managed async
pool seeded in the FastAPI lifespan), so this endpoint never creates a new
connection.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/redis", tags=["redis"])


@router.get("/health")
async def redis_health(request: Request) -> dict:
    """Redis connectivity and server stats for TCP_OVERWINDOW diagnostics.

    Returns:
        status, latency_ms, blocked_clients, connected_clients,
        ops_per_sec, slowlog_len, checked_at
    """
    r: aioredis.Redis = request.app.state.redis

    t0 = datetime.now(UTC)
    await r.ping()
    latency_ms = (datetime.now(UTC) - t0).total_seconds() * 1000

    clients: dict = await r.info(section="clients")  # type: ignore[assignment]
    stats: dict = await r.info(section="stats")  # type: ignore[assignment]

    try:
        slowlog_len: int | None = await r.slowlog_len()
    except Exception:
        slowlog_len = None

    return {
        "status": "ok",
        "latency_ms": round(latency_ms, 2),
        "blocked_clients": clients.get("blocked_clients"),
        "connected_clients": clients.get("connected_clients"),
        "ops_per_sec": stats.get("instantaneous_ops_per_sec"),
        "slowlog_len": slowlog_len,
        "checked_at": datetime.now(UTC).isoformat(),
    }
