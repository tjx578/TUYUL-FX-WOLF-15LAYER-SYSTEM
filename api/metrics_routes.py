"""
Prometheus metrics exposition endpoint.

Exposes GET /metrics in Prometheus text exposition format (v0.0.4).
Before each scrape the runtime-state gauges are refreshed from
``RuntimeState`` and ``SystemStateManager`` so that values are always
current without requiring background task polling.

Content-Type: text/plain; version=0.0.4; charset=utf-8
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from core.metrics import (
    ACTIVE_PAIRS,
    PIPELINE_LATENCY_MS,
    SYSTEM_HEALTHY,
    get_registry,
)
from monitoring.pipeline_metrics import evaluate_latency_slo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["observability"])

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
        active = mgr.get_active_symbol_count() # pyright: ignore[reportAttributeAccessIssue]
        ACTIVE_PAIRS.set(float(active))
    except Exception:
        logger.debug("SystemStateManager active-pairs refresh skipped", exc_info=True)


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
    payload = get_registry().exposition()
    return PlainTextResponse(content=payload, media_type=_CONTENT_TYPE)


@router.get(
    "/metrics/slo",
    summary="SLO status for dashboard and alerting",
    description=(
        "Returns latency SLO status with threshold breach indicators for dashboard "
        "panels and alert automation."
    ),
    include_in_schema=True,
)
async def metrics_slo(
    latency_threshold_ms: float | None = Query(default=None, ge=1.0, le=10_000.0),
    min_samples: int = Query(default=5, ge=1, le=10_000),
) -> dict:
    """Return SLO status derived from in-process metrics registry."""
    _refresh_runtime_gauges()
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
