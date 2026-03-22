"""
Tests for Layer 15 — System Health & Meta-Governance Monitor.
Zone: Monitoring/Dashboard. Observe-only. NO L12 override. NO execution.
"""

from datetime import UTC, datetime, timedelta

import pytest

from journal.l15_health import (
    CRITICAL_STALE_SECONDS,
    STALE_THRESHOLD_SECONDS,
    AlertLevel,
    HealthStatus,
    L15HealthReport,
    LayerHealthInput,
    SystemResourceInput,
    check_health,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_layer_input(
    layer_id: str,
    layer_name: str = "TestLayer",
    is_responding: bool = True,
    age_seconds: float = 10.0,
    last_error: str | None = None,
    is_disabled: bool = False,
) -> LayerHealthInput:
    ts = (datetime.now(UTC) - timedelta(seconds=age_seconds)).isoformat()
    return LayerHealthInput(
        layer_id=layer_id,
        layer_name=layer_name,
        is_responding=is_responding,
        last_update_timestamp=ts,
        last_error=last_error,
        is_disabled=is_disabled,
    )


def _make_all_healthy_layers() -> list[LayerHealthInput]:
    """15 healthy layers."""
    return [_make_layer_input(f"L{i}", f"Layer{i}", age_seconds=5.0) for i in range(1, 16)]


# ---------------------------------------------------------------------------
# All healthy scenario
# ---------------------------------------------------------------------------


class TestAllHealthy:
    def test_all_healthy_returns_healthy(self) -> None:
        layers = _make_all_healthy_layers()
        result = check_health("R001", layers)
        assert result.overall_status == HealthStatus.HEALTHY

    def test_all_healthy_counts(self) -> None:
        layers = _make_all_healthy_layers()
        result = check_health("R001", layers)
        assert result.healthy_layers == 15
        assert result.degraded_layers == 0
        assert result.critical_layers == 0

    def test_no_alerts_when_healthy(self) -> None:
        layers = _make_all_healthy_layers()
        result = check_health("R001", layers)
        assert len(result.alerts) == 0

    def test_returns_l15_report(self) -> None:
        layers = _make_all_healthy_layers()
        result = check_health("R001", layers)
        assert isinstance(result, L15HealthReport)

    def test_result_is_frozen(self) -> None:
        layers = _make_all_healthy_layers()
        result = check_health("R001", layers)
        with pytest.raises(AttributeError):
            result.overall_status = HealthStatus.OFFLINE  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Stale layer detection
# ---------------------------------------------------------------------------


class TestStaleDetection:
    def test_stale_layer_detected(self) -> None:
        layers = _make_all_healthy_layers()
        layers[3] = _make_layer_input("L4", "Scoring", age_seconds=STALE_THRESHOLD_SECONDS + 10)
        result = check_health("R002", layers)
        assert result.stale_data_detected is True
        assert result.degraded_layers >= 1
        # Should have a stale alert
        stale_alerts = [a for a in result.alerts if a.code == "LAYER_STALE"]
        assert len(stale_alerts) >= 1

    def test_critically_stale_is_error(self) -> None:
        layers = _make_all_healthy_layers()
        layers[3] = _make_layer_input("L4", "Scoring", age_seconds=CRITICAL_STALE_SECONDS + 10)
        result = check_health("R003", layers)
        assert result.critical_layers >= 1
        error_alerts = [a for a in result.alerts if a.code == "LAYER_ERROR"]
        assert len(error_alerts) >= 1


# ---------------------------------------------------------------------------
# Layer errors and missing
# ---------------------------------------------------------------------------


class TestLayerErrors:
    def test_non_responding_layer(self) -> None:
        layers = _make_all_healthy_layers()
        layers[0] = LayerHealthInput(
            layer_id="L1",
            layer_name="Market Structure",
            is_responding=False,
        )
        result = check_health("R004", layers)
        assert result.critical_layers >= 1
        missing_alerts = [a for a in result.alerts if a.code == "LAYER_MISSING"]
        assert len(missing_alerts) >= 1

    def test_layer_with_error(self) -> None:
        layers = _make_all_healthy_layers()
        layers[0] = LayerHealthInput(
            layer_id="L1",
            layer_name="Market Structure",
            is_responding=False,
            last_error="Connection timeout",
        )
        result = check_health("R005", layers)
        assert result.critical_layers >= 1
        error_alerts = [a for a in result.alerts if a.code == "LAYER_ERROR"]
        assert len(error_alerts) >= 1

    def test_disabled_layer_not_critical(self) -> None:
        layers = _make_all_healthy_layers()
        layers[14] = _make_layer_input("L15", "Self", is_disabled=True)
        result = check_health("R006", layers)
        # Disabled shouldn't count as critical
        assert result.critical_layers == 0


# ---------------------------------------------------------------------------
# L12 special handling
# ---------------------------------------------------------------------------


class TestL12CriticalHandling:
    """L12 (Constitution) being down must always be CRITICAL."""

    def test_l12_error_forces_critical(self) -> None:
        layers = _make_all_healthy_layers()
        # Replace L12 with error state
        layers[11] = LayerHealthInput(
            layer_id="L12",
            layer_name="Constitution",
            is_responding=False,
            last_error="Verdict engine crash",
        )
        result = check_health("R007", layers)
        assert result.overall_status == HealthStatus.CRITICAL

    def test_l12_missing_forces_critical(self) -> None:
        layers = _make_all_healthy_layers()
        layers[11] = LayerHealthInput(
            layer_id="L12",
            layer_name="Constitution",
            is_responding=False,
        )
        result = check_health("R008", layers)
        assert result.overall_status == HealthStatus.CRITICAL


# ---------------------------------------------------------------------------
# Overall status classification
# ---------------------------------------------------------------------------


class TestOverallStatus:
    def test_multiple_criticals_goes_offline(self) -> None:
        layers = _make_all_healthy_layers()
        for i in range(3):
            layers[i] = LayerHealthInput(
                layer_id=f"L{i + 1}",
                layer_name=f"Layer{i + 1}",
                is_responding=False,
                last_error="Down",
            )
        result = check_health("R009", layers)
        assert result.overall_status == HealthStatus.OFFLINE

    def test_single_warning_is_degraded(self) -> None:
        layers = _make_all_healthy_layers()
        layers[5] = _make_layer_input("L6", "Layer6", age_seconds=STALE_THRESHOLD_SECONDS + 10)
        result = check_health("R010", layers)
        assert result.overall_status == HealthStatus.DEGRADED


# ---------------------------------------------------------------------------
# Resource monitoring
# ---------------------------------------------------------------------------


class TestResourceMonitoring:
    def test_redis_disconnected(self) -> None:
        layers = _make_all_healthy_layers()
        resources = SystemResourceInput(redis_connected=False)
        result = check_health("R011", layers, resources)
        redis_alerts = [a for a in result.alerts if a.code == "REDIS_DISCONNECTED"]
        assert len(redis_alerts) == 1
        assert redis_alerts[0].alert_level == AlertLevel.CRITICAL

    def test_redis_high_latency(self) -> None:
        layers = _make_all_healthy_layers()
        resources = SystemResourceInput(redis_latency_ms=150.0)
        result = check_health("R012", layers, resources)
        latency_alerts = [a for a in result.alerts if "REDIS_LATENCY" in a.code]
        assert len(latency_alerts) >= 1

    def test_queue_overflow(self) -> None:
        layers = _make_all_healthy_layers()
        resources = SystemResourceInput(pending_queue_depth=250)
        result = check_health("R013", layers, resources)
        queue_alerts = [a for a in result.alerts if a.code == "QUEUE_OVERFLOW"]
        assert len(queue_alerts) == 1

    def test_normal_resources_no_alerts(self) -> None:
        layers = _make_all_healthy_layers()
        resources = SystemResourceInput(
            redis_connected=True,
            redis_latency_ms=5.0,
            pending_queue_depth=3,
        )
        result = check_health("R014", layers, resources)
        resource_alerts = [a for a in result.alerts if a.code.startswith("REDIS_") or a.code.startswith("QUEUE_")]
        assert len(resource_alerts) == 0


# ---------------------------------------------------------------------------
# Report integrity
# ---------------------------------------------------------------------------


class TestReportIntegrity:
    def test_report_id_preserved(self) -> None:
        layers = _make_all_healthy_layers()
        result = check_health("R099", layers)
        assert result.report_id == "R099"

    def test_timestamp_populated(self) -> None:
        layers = _make_all_healthy_layers()
        result = check_health("R099", layers)
        assert "2026" in result.timestamp

    def test_metadata_passthrough(self) -> None:
        layers = _make_all_healthy_layers()
        meta = {"trigger": "scheduled", "interval": "60s"}
        result = check_health("R099", layers, metadata=meta)
        assert result.metadata == meta

    def test_total_layers_counted(self) -> None:
        layers = _make_all_healthy_layers()
        result = check_health("R099", layers)
        assert result.total_layers == 15

    def test_alerts_are_tuple(self) -> None:
        layers = _make_all_healthy_layers()
        result = check_health("R099", layers)
        assert isinstance(result.alerts, tuple)

    def test_layer_reports_are_tuple(self) -> None:
        layers = _make_all_healthy_layers()
        result = check_health("R099", layers)
        assert isinstance(result.layer_reports, tuple)


# ---------------------------------------------------------------------------
# Constitutional boundary enforcement
# ---------------------------------------------------------------------------


class TestConstitutionalBoundary:
    """L15 MUST NOT override L12 or trigger execution."""

    def test_no_override_method(self) -> None:
        import journal.l15_health as mod

        public_names = [n for n in dir(mod) if not n.startswith("_")]
        forbidden = {"override_verdict", "execute_trade", "cancel_order", "modify_l12", "force_decision"}
        assert forbidden.isdisjoint(set(public_names))

    def test_result_has_no_decision_field(self) -> None:
        layers = _make_all_healthy_layers()
        result = check_health("R099", layers)
        field_names = set(result.__dataclass_fields__.keys())
        forbidden_fields = {"verdict", "trade_action", "execute", "override_l12"}
        assert forbidden_fields.isdisjoint(field_names)

    def test_health_check_does_not_modify_inputs(self) -> None:
        layers = _make_all_healthy_layers()
        original_ids = [l.layer_id for l in layers]  # noqa: E741
        _ = check_health("R099", layers)
        assert [l.layer_id for l in layers] == original_ids  # noqa: E741
