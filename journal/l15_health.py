"""
Layer 15 — System Health & Meta-Governance Monitor
Zone: Monitoring/Dashboard. Observe all layers. NO override of L12.
NO execution side-effects. Report-only.

Monitors:
  - Layer availability (are all 15 layers responding?)
  - Data freshness (stale feeds, missing updates)
  - Internal consistency (do layer outputs agree with each other?)
  - Resource health (memory, latency, queue depth)
  - Constitutional compliance (detect authority boundary violations)

Output is a health report consumed by dashboard. L15 CANNOT:
  - Override or modify any L12 verdict
  - Execute or cancel trades
  - Alter analysis layer weights
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

logger = logging.getLogger(__name__)


class HealthStatus(StrEnum):
    """Aggregate system health status."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    OFFLINE = "OFFLINE"


class LayerStatus(StrEnum):
    """Individual layer health."""
    OK = "OK"
    STALE = "STALE"             # data older than threshold
    ERROR = "ERROR"             # layer returned error on last check
    MISSING = "MISSING"         # no response / not registered
    DISABLED = "DISABLED"       # intentionally disabled


class AlertLevel(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class LayerHealthReport:
    """Health status for a single layer."""
    layer_id: str               # e.g. "L1", "L4", "L12"
    layer_name: str
    status: LayerStatus
    last_update_age_seconds: float | None = None
    error_message: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class HealthAlert:
    """Single health alert for dashboard display."""
    alert_level: AlertLevel
    source_layer: str
    code: str
    message: str
    recommendation: str = ""


@dataclass(frozen=True)
class LayerHealthInput:
    """Input data about a single layer's current state."""
    layer_id: str
    layer_name: str
    is_responding: bool
    last_update_timestamp: str | None = None     # ISO format
    last_error: str | None = None
    is_disabled: bool = False


@dataclass(frozen=True)
class SystemResourceInput:
    """System resource metrics (optional)."""
    memory_usage_mb: float | None = None
    cpu_percent: float | None = None
    redis_connected: bool = True
    redis_latency_ms: float | None = None
    pending_queue_depth: int = 0


@dataclass(frozen=True)
class L15HealthReport:
    """
    Immutable system health report. Consumed by dashboard.
    L15 NEVER overrides L12 or any other layer's output.
    """
    report_id: str
    overall_status: HealthStatus
    layer_reports: tuple[LayerHealthReport, ...]
    alerts: tuple[HealthAlert, ...]
    total_layers: int
    healthy_layers: int
    degraded_layers: int
    critical_layers: int
    stale_data_detected: bool
    constitutional_violation_detected: bool
    timestamp: str
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Configuration thresholds
# ---------------------------------------------------------------------------
STALE_THRESHOLD_SECONDS: float = 300.0          # 5 min
CRITICAL_STALE_SECONDS: float = 900.0           # 15 min
REDIS_LATENCY_WARNING_MS: float = 100.0
REDIS_LATENCY_CRITICAL_MS: float = 500.0
QUEUE_DEPTH_WARNING: int = 50
QUEUE_DEPTH_CRITICAL: int = 200
EXPECTED_LAYERS: int = 15


def _evaluate_layer(
    layer_input: LayerHealthInput,
    now: datetime,
) -> LayerHealthReport:
    """Evaluate health of a single layer. Pure function."""
    if layer_input.is_disabled:
        return LayerHealthReport(
            layer_id=layer_input.layer_id,
            layer_name=layer_input.layer_name,
            status=LayerStatus.DISABLED,
        )

    if not layer_input.is_responding:
        return LayerHealthReport(
            layer_id=layer_input.layer_id,
            layer_name=layer_input.layer_name,
            status=LayerStatus.MISSING if layer_input.last_error is None else LayerStatus.ERROR,
            error_message=layer_input.last_error or "Not responding",
        )

    # Check staleness
    age_seconds: float | None = None
    if layer_input.last_update_timestamp:
        try:
            last_dt = datetime.fromisoformat(layer_input.last_update_timestamp)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=UTC)
            age_seconds = (now - last_dt).total_seconds()
        except (ValueError, TypeError):
            age_seconds = None

    if age_seconds is not None and age_seconds > CRITICAL_STALE_SECONDS:
        return LayerHealthReport(
            layer_id=layer_input.layer_id,
            layer_name=layer_input.layer_name,
            status=LayerStatus.ERROR,
            last_update_age_seconds=age_seconds,
            error_message=f"Critically stale: {age_seconds:.0f}s since last update",
        )

    if age_seconds is not None and age_seconds > STALE_THRESHOLD_SECONDS:
        return LayerHealthReport(
            layer_id=layer_input.layer_id,
            layer_name=layer_input.layer_name,
            status=LayerStatus.STALE,
            last_update_age_seconds=age_seconds,
        )

    if layer_input.last_error:
        return LayerHealthReport(
            layer_id=layer_input.layer_id,
            layer_name=layer_input.layer_name,
            status=LayerStatus.ERROR,
            last_update_age_seconds=age_seconds,
            error_message=layer_input.last_error,
        )

    return LayerHealthReport(
        layer_id=layer_input.layer_id,
        layer_name=layer_input.layer_name,
        status=LayerStatus.OK,
        last_update_age_seconds=age_seconds,
    )


def _generate_alerts(
    layer_reports: Sequence[LayerHealthReport],
    resources: SystemResourceInput | None,
) -> list[HealthAlert]:
    """Generate alerts from layer reports and resource metrics. Pure function."""
    alerts: list[HealthAlert] = []

    # Layer-level alerts
    for lr in layer_reports:
        if lr.status == LayerStatus.ERROR:
            alerts.append(HealthAlert(
                alert_level=AlertLevel.CRITICAL,
                source_layer=lr.layer_id,
                code="LAYER_ERROR",
                message=f"{lr.layer_id} ({lr.layer_name}): {lr.error_message or 'error state'}",
                recommendation=f"Investigate {lr.layer_id} immediately",
            ))
        elif lr.status == LayerStatus.STALE:
            alerts.append(HealthAlert(
                alert_level=AlertLevel.WARNING,
                source_layer=lr.layer_id,
                code="LAYER_STALE",
                message=f"{lr.layer_id} ({lr.layer_name}): data stale ({lr.last_update_age_seconds:.0f}s)",
                recommendation=f"Check data feed for {lr.layer_id}",
            ))
        elif lr.status == LayerStatus.MISSING:
            alerts.append(HealthAlert(
                alert_level=AlertLevel.CRITICAL,
                source_layer=lr.layer_id,
                code="LAYER_MISSING",
                message=f"{lr.layer_id} ({lr.layer_name}): not responding",
                recommendation=f"Verify {lr.layer_id} is deployed and running",
            ))

    # Coverage alert
    active_layers = [lr for lr in layer_reports if lr.status not in (LayerStatus.DISABLED,)]
    [lr for lr in active_layers if lr.status == LayerStatus.OK]
    if len(active_layers) < EXPECTED_LAYERS:
        alerts.append(HealthAlert(
            alert_level=AlertLevel.WARNING,
            source_layer="L15",
            code="INCOMPLETE_COVERAGE",
            message=f"Only {len(active_layers)}/{EXPECTED_LAYERS} layers active",
            recommendation="Review disabled/missing layers",
        ))

    # Resource alerts
    if resources:
        if not resources.redis_connected:
            alerts.append(HealthAlert(
                alert_level=AlertLevel.CRITICAL,
                source_layer="L15",
                code="REDIS_DISCONNECTED",
                message="Redis connection lost",
                recommendation="Check Redis server and network",
            ))
        elif resources.redis_latency_ms is not None:
            if resources.redis_latency_ms > REDIS_LATENCY_CRITICAL_MS:
                alerts.append(HealthAlert(
                    alert_level=AlertLevel.CRITICAL,
                    source_layer="L15",
                    code="REDIS_LATENCY_CRITICAL",
                    message=f"Redis latency {resources.redis_latency_ms:.0f}ms",
                    recommendation="Investigate Redis performance",
                ))
            elif resources.redis_latency_ms > REDIS_LATENCY_WARNING_MS:
                alerts.append(HealthAlert(
                    alert_level=AlertLevel.WARNING,
                    source_layer="L15",
                    code="REDIS_LATENCY_HIGH",
                    message=f"Redis latency {resources.redis_latency_ms:.0f}ms",
                    recommendation="Monitor Redis load",
                ))

        if resources.pending_queue_depth >= QUEUE_DEPTH_CRITICAL:
            alerts.append(HealthAlert(
                alert_level=AlertLevel.CRITICAL,
                source_layer="L15",
                code="QUEUE_OVERFLOW",
                message=f"Pending queue depth: {resources.pending_queue_depth}",
                recommendation="Scale workers or investigate backpressure",
            ))
        elif resources.pending_queue_depth >= QUEUE_DEPTH_WARNING:
            alerts.append(HealthAlert(
                alert_level=AlertLevel.WARNING,
                source_layer="L15",
                code="QUEUE_DEEP",
                message=f"Pending queue depth: {resources.pending_queue_depth}",
                recommendation="Monitor queue growth rate",
            ))

    return alerts


def _classify_overall_status(
    layer_reports: Sequence[LayerHealthReport],
    alerts: Sequence[HealthAlert],
) -> HealthStatus:
    """Determine aggregate system status. Pure function."""
    critical_count = sum(1 for a in alerts if a.alert_level == AlertLevel.CRITICAL)
    warning_count = sum(1 for a in alerts if a.alert_level == AlertLevel.WARNING)

    # L12 (Constitution) being down is always CRITICAL
    l12_status = next(
        (lr.status for lr in layer_reports if lr.layer_id == "L12"), None
    )
    if l12_status in (LayerStatus.ERROR, LayerStatus.MISSING):
        return HealthStatus.CRITICAL

    if critical_count >= 3:
        return HealthStatus.OFFLINE
    if critical_count >= 1:
        return HealthStatus.CRITICAL
    if warning_count >= 3:
        return HealthStatus.DEGRADED
    if warning_count >= 1:
        return HealthStatus.DEGRADED
    return HealthStatus.HEALTHY


def check_health(
    report_id: str,
    layer_inputs: Sequence[LayerHealthInput],
    resources: SystemResourceInput | None = None,
    metadata: dict | None = None,
) -> L15HealthReport:
    """
    Main entry point for Layer-15 system health check.

    This is a MONITORING operation — observe and report only.
    L15 NEVER overrides L12 or any other layer.

    Parameters
    ----------
    report_id : str
        Unique identifier for this health check.
    layer_inputs : Sequence[LayerHealthInput]
        Current state of each layer.
    resources : SystemResourceInput, optional
        System resource metrics.
    metadata : dict, optional
        Additional context.

    Returns
    -------
    L15HealthReport
        Immutable health report for dashboard consumption.
    """
    now = datetime.now(UTC)

    layer_reports = [_evaluate_layer(li, now) for li in layer_inputs]
    alerts = _generate_alerts(layer_reports, resources)
    overall = _classify_overall_status(layer_reports, alerts)

    healthy = sum(1 for lr in layer_reports if lr.status == LayerStatus.OK)
    degraded = sum(1 for lr in layer_reports if lr.status == LayerStatus.STALE)
    critical = sum(
        1 for lr in layer_reports
        if lr.status in (LayerStatus.ERROR, LayerStatus.MISSING)
    )
    stale = any(lr.status == LayerStatus.STALE for lr in layer_reports)
    constitutional_violation = False     # placeholder for future compliance checks

    report = L15HealthReport(
        report_id=report_id,
        overall_status=overall,
        layer_reports=tuple(layer_reports),
        alerts=tuple(alerts),
        total_layers=len(layer_reports),
        healthy_layers=healthy,
        degraded_layers=degraded,
        critical_layers=critical,
        stale_data_detected=stale,
        constitutional_violation_detected=constitutional_violation,
        timestamp=now.isoformat(),
        metadata=metadata or {},
    )

    logger.info(
        "L15 [%s] | status=%s | ok=%d degraded=%d critical=%d | %d alerts",
        report_id, overall.value, healthy, degraded, critical, len(alerts),
    )
    return report
