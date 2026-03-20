"""
Prometheus metrics exposition endpoint.

Exposes GET /metrics in Prometheus text exposition format (v0.0.4).
Before each scrape the runtime-state gauges are refreshed from
``RuntimeState`` and ``SystemStateManager`` so that values are always
current without requiring background task polling.

Content-Type: text/plain; version=0.0.4; charset=utf-8
"""

from __future__ import annotations

import json
import logging
import os
import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from core.metrics import (
    ACTIVE_PAIRS,
    ORCHESTRATOR_HEARTBEAT_AGE_SECONDS,
    ORCHESTRATOR_MODE,
    ORCHESTRATOR_READY,
    PIPELINE_LATENCY_MS,
    SYSTEM_HEALTHY,
    get_registry,
)
from infrastructure.redis_client import get_async_redis
from monitoring.pipeline_metrics import evaluate_latency_slo
from state.redis_keys import ORCHESTRATOR_STATE

from .middleware.machine_auth import verify_observability_machine_auth

logger = logging.getLogger(__name__)

router = APIRouter(tags=["observability"], dependencies=[Depends(verify_observability_machine_auth)])

_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _refresh_runtime_gauges() -> None:
    """Pull live values from in-process state into Prometheus gauges."""

    # ── RuntimeState ─────────────────────────────────────────────────────────
    try:
        from context.runtime_state import RuntimeState  # local import avoids cycle

        PIPELINE_LATENCY_MS.set(float(RuntimeState.latency_ms))
        SYSTEM_HEALTHY.set(1.0 if RuntimeState.healthy else 0.0)
    except Exception:
        logger.debug("RuntimeState refresh skipped", exc_info=True)

    # ── Active pairs from SystemStateManager ─────────────────────────────────
    try:
        from context.system_state import SystemStateManager

        mgr = SystemStateManager()
        active = mgr.get_active_symbol_count()  # pyright: ignore[reportAttributeAccessIssue]
        ACTIVE_PAIRS.set(float(active))
    except Exception:
        logger.debug("SystemStateManager active-pairs refresh skipped", exc_info=True)


async def _refresh_orchestrator_gauges() -> None:
    """Pull orchestrator heartbeat/readiness state from Redis into gauges."""
    try:
        redis = await get_async_redis()
        raw = await redis.get(ORCHESTRATOR_STATE)
    except Exception:
        logger.debug("Orchestrator metrics refresh skipped (redis read failed)", exc_info=True)
        ORCHESTRATOR_READY.set(0.0)
        return

    if not raw:
        ORCHESTRATOR_READY.set(0.0)
        return

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        ORCHESTRATOR_READY.set(0.0)
        return

    if not isinstance(payload, dict):
        ORCHESTRATOR_READY.set(0.0)
        return

    ts_raw = payload.get("timestamp")
    age_seconds: float | None = None
    if isinstance(ts_raw, int | float | str):
        try:
            ts = float(ts_raw)
            if ts > 0:
                age_seconds = max(0.0, time.time() - ts)
        except (TypeError, ValueError):
            age_seconds = None

    heartbeat_interval_sec = max(5.0, float(os.getenv("ORCHESTRATOR_HEARTBEAT_INTERVAL_SEC", "30")))
    max_age_sec = max(15.0, heartbeat_interval_sec * 3.0)
    ready = age_seconds is not None and age_seconds <= max_age_sec

    ORCHESTRATOR_READY.set(1.0 if ready else 0.0)
    if age_seconds is not None:
        ORCHESTRATOR_HEARTBEAT_AGE_SECONDS.set(age_seconds)

    mode = str(payload.get("mode", "UNKNOWN")).upper()
    for m in ("NORMAL", "SAFE", "KILL_SWITCH", "UNKNOWN"):
        ORCHESTRATOR_MODE.labels(mode=m).set(1.0 if mode == m else 0.0)


@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus metrics scrape endpoint",
    description=(
        "Returns all Wolf-15 runtime metrics in Prometheus text exposition "
        "format v0.0.4. Suitable for direct Prometheus scrape target or "
        "Grafana Agent."
    ),
    include_in_schema=True,
)
async def prometheus_metrics() -> PlainTextResponse:
    """Expose all registered metrics in Prometheus text format."""
    _refresh_runtime_gauges()
    await _refresh_orchestrator_gauges()
    payload = get_registry().exposition()
    return PlainTextResponse(content=payload, media_type=_CONTENT_TYPE)


@router.get(
    "/metrics/slo",
    summary="SLO status for dashboard and alerting",
    description=(
        "Returns latency SLO status with threshold breach indicators for dashboard " "panels and alert automation."
    ),
    include_in_schema=True,
)
async def metrics_slo(
    latency_threshold_ms: float | None = Query(default=None, ge=1.0, le=10_000.0),
    min_samples: int = Query(default=5, ge=1, le=10_000),
) -> dict:
    """Return SLO status derived from in-process metrics registry."""
    _refresh_runtime_gauges()
    await _refresh_orchestrator_gauges()
    status = evaluate_latency_slo(
        latency_threshold_ms=latency_threshold_ms,
        min_samples=min_samples,
    )
    alerts: list[dict[str, str]] = []
    if not status["healthy"]:
        alerts.append(
            {
                "event": "SLO_THRESHOLD_BREACH",
                "severity": "warning",
                "message": "Pipeline latency SLO breached on one or more stages",
            }
        )
    return {
        "slo": status,
        "alerts": alerts,
    }
