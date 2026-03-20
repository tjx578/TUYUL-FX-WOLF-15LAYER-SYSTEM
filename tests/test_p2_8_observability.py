"""
Tests for P2-8: p95/p99 percentile tracker, V11 metrics, execution metrics,
latency-budget alerts, and anomaly-rate alerts.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from alerts.alert_monitor import AlertMonitor

# ═══════════════════════════════════════════════════════════════════════
#  PercentileTracker unit tests
# ═══════════════════════════════════════════════════════════════════════


class TestPercentileTracker:
    def test_empty_summary(self) -> None:
        from monitoring.percentile_tracker import PercentileTracker

        t = PercentileTracker(window_size=100)
        s = t.summary()
        assert s.count == 0
        assert s.p50 == 0.0
        assert s.p95 == 0.0

    def test_single_observation(self) -> None:
        from monitoring.percentile_tracker import PercentileTracker

        t = PercentileTracker(window_size=100)
        t.observe(42.0)
        s = t.summary()
        assert s.count == 1
        assert s.p50 == 42.0
        assert s.p95 == 42.0
        assert s.p99 == 42.0
        assert s.min == 42.0
        assert s.max == 42.0
        assert s.mean == 42.0

    def test_percentiles_with_known_distribution(self) -> None:
        from monitoring.percentile_tracker import PercentileTracker

        t = PercentileTracker(window_size=1000)
        for i in range(1, 101):
            t.observe(float(i))

        s = t.summary()
        assert s.count == 100
        assert s.min == 1.0
        assert s.max == 100.0
        assert s.p50 == 51.0  # int(100 * 0.50) = index 50 → value 51
        assert s.p95 == 96.0  # int(100 * 0.95) = index 95 → value 96
        assert s.p99 == 100.0  # int(100 * 0.99) = index 99 → value 100

    def test_ring_buffer_eviction(self) -> None:
        from monitoring.percentile_tracker import PercentileTracker

        t = PercentileTracker(window_size=10)
        # Fill with 1..10
        for i in range(1, 11):
            t.observe(float(i))
        assert t.summary().count == 10

        # Add 11 — oldest (1.0) evicted
        t.observe(11.0)
        s = t.summary()
        assert s.count == 10
        assert s.min == 2.0
        assert s.max == 11.0

    def test_reset(self) -> None:
        from monitoring.percentile_tracker import PercentileTracker

        t = PercentileTracker(window_size=100)
        t.observe(1.0)
        t.observe(2.0)
        t.reset()
        assert t.summary().count == 0

    def test_to_dict(self) -> None:
        from monitoring.percentile_tracker import PercentileTracker

        t = PercentileTracker(window_size=100)
        t.observe(10.0)
        d = t.summary().to_dict()
        assert isinstance(d, dict)
        assert "p50" in d
        assert "p95" in d
        assert "p99" in d


class TestLabelledPercentileTracker:
    def test_per_label_isolation(self) -> None:
        from monitoring.percentile_tracker import LabelledPercentileTracker

        lt = LabelledPercentileTracker(window_size=100)
        lt.observe("A", 10.0)
        lt.observe("B", 20.0)
        assert lt.summary("A").p50 == 10.0
        assert lt.summary("B").p50 == 20.0

    def test_missing_label_returns_empty(self) -> None:
        from monitoring.percentile_tracker import LabelledPercentileTracker

        lt = LabelledPercentileTracker(window_size=100)
        s = lt.summary("NONEXISTENT")
        assert s.count == 0

    def test_all_summaries(self) -> None:
        from monitoring.percentile_tracker import LabelledPercentileTracker

        lt = LabelledPercentileTracker(window_size=100)
        lt.observe("X", 1.0)
        lt.observe("Y", 2.0)
        all_s = lt.all_summaries()
        assert "X" in all_s
        assert "Y" in all_s


# ═══════════════════════════════════════════════════════════════════════
#  V11 metrics
# ═══════════════════════════════════════════════════════════════════════


class TestV11Metrics:
    def setup_method(self) -> None:
        from monitoring.v11_metrics import reset_v11_metrics

        reset_v11_metrics()

    def test_record_and_summary(self) -> None:
        from monitoring.v11_metrics import record_v11_evaluation, v11_latency_summary

        record_v11_evaluation("EURUSD", 10.0, "pass")
        record_v11_evaluation("EURUSD", 50.0, "pass")
        record_v11_evaluation("EURUSD", 100.0, "veto")

        s = v11_latency_summary("EURUSD")
        assert s.count == 3
        assert s.min == 10.0
        assert s.max == 100.0

    def test_veto_rate(self) -> None:
        from monitoring.v11_metrics import record_v11_evaluation, v11_veto_rate

        for _ in range(7):
            record_v11_evaluation("EURUSD", 10.0, "pass")
        for _ in range(3):
            record_v11_evaluation("EURUSD", 10.0, "veto")

        rate = v11_veto_rate()
        assert abs(rate - 0.30) < 0.01

    def test_error_rate(self) -> None:
        from monitoring.v11_metrics import record_v11_evaluation, v11_error_rate

        for _ in range(9):
            record_v11_evaluation("EURUSD", 10.0, "pass")
        record_v11_evaluation("EURUSD", 10.0, "error")

        rate = v11_error_rate()
        assert abs(rate - 0.10) < 0.01

    def test_budget_exceeded_counter(self) -> None:
        from monitoring.v11_metrics import V11_OUTCOME_TOTAL, record_v11_evaluation

        record_v11_evaluation("EURUSD", 200.0, "pass", budget_ms=100.0)
        # Should have both "pass" and "budget_exceeded" incremented
        # Access through the counter children
        found_exceeded = False
        for key, child in V11_OUTCOME_TOTAL._children.items():
            labels = dict(key)
            if labels.get("outcome") == "budget_exceeded" and labels.get("symbol") == "EURUSD":
                found_exceeded = child.value >= 1
        assert found_exceeded

    def test_all_summaries(self) -> None:
        from monitoring.v11_metrics import record_v11_evaluation, v11_all_latency_summaries

        record_v11_evaluation("EURUSD", 10.0, "pass")
        record_v11_evaluation("GBPUSD", 20.0, "veto")

        all_s = v11_all_latency_summaries()
        assert "EURUSD" in all_s
        assert "GBPUSD" in all_s


# ═══════════════════════════════════════════════════════════════════════
#  Execution metrics
# ═══════════════════════════════════════════════════════════════════════


class TestExecutionMetrics:
    def setup_method(self) -> None:
        from monitoring.execution_metrics import reset_execution_metrics

        reset_execution_metrics()

    def test_record_exec_stage(self) -> None:
        from monitoring.execution_metrics import exec_stage_summary, record_exec_stage

        record_exec_stage("broker_call", 100.0)
        record_exec_stage("broker_call", 200.0)
        record_exec_stage("broker_call", 300.0)

        s = exec_stage_summary("broker_call")
        assert s.count == 3
        assert s.min == 100.0
        assert s.max == 300.0

    def test_l12_reject_rate(self) -> None:
        from monitoring.execution_metrics import l12_reject_rate, record_l12_outcome

        for _ in range(8):
            record_l12_outcome("HOLD")
        for _ in range(2):
            record_l12_outcome("EXECUTE_BUY")

        rate = l12_reject_rate()
        assert abs(rate - 0.80) < 0.01

    def test_l12_ambiguity_rate(self) -> None:
        from monitoring.execution_metrics import l12_ambiguity_rate, record_l12_outcome

        for _ in range(9):
            record_l12_outcome("EXECUTE_SELL")
        record_l12_outcome("UNKNOWN_THING")

        rate = l12_ambiguity_rate()
        assert abs(rate - 0.10) < 0.01

    def test_reconnect_storm_detection(self) -> None:
        from monitoring.execution_metrics import (
            _RECONNECT_STORM_THRESHOLD,
            is_reconnect_storm,
            record_reconnect_event,
            reset_execution_metrics,
        )

        reset_execution_metrics()
        # Below threshold — no storm
        for _ in range(_RECONNECT_STORM_THRESHOLD - 1):
            record_reconnect_event()
        assert not is_reconnect_storm()

        # Hit threshold — storm!
        record_reconnect_event()
        assert is_reconnect_storm()

    def test_freshness_latency_correlation(self) -> None:
        from monitoring.execution_metrics import FRESHNESS_LATENCY_CORR, flag_freshness_latency_correlation

        flag_freshness_latency_correlation("EURUSD", True)
        child = FRESHNESS_LATENCY_CORR._children.get((("symbol", "EURUSD"),))
        assert child is not None
        assert child.value == 1.0

        flag_freshness_latency_correlation("EURUSD", False)
        assert child.value == 0.0


# ═══════════════════════════════════════════════════════════════════════
#  Alert Monitor — new P2-8 checks
# ═══════════════════════════════════════════════════════════════════════


class TestAlertMonitorP28:
    """Tests for V11 latency budget, exec latency budget, and anomaly rate alerts."""

    def _make_monitor(self) -> AlertMonitor:  # noqa: F821
        from alerts.alert_monitor import AlertMonitor
        from alerts.alert_rules import AlertThresholds

        thresholds = AlertThresholds(
            v11_latency_p95_budget_ms=50.0,
            v11_latency_p99_budget_ms=80.0,
            exec_guard_p95_budget_ms=20.0,
            exec_broker_p95_budget_ms=500.0,
            exec_dispatch_p95_budget_ms=1000.0,
            v11_veto_rate_warning=0.30,
            v11_veto_rate_critical=0.50,
            l12_reject_rate_warning=0.80,
            l12_reject_rate_critical=0.95,
            l12_ambiguity_rate_warning=0.10,
            rate_alert_min_samples=5,
        )
        notifier = MagicMock()
        return AlertMonitor(notifier=notifier, thresholds=thresholds)

    def test_v11_latency_budget_warning(self) -> None:
        from monitoring.v11_metrics import record_v11_evaluation, reset_v11_metrics

        reset_v11_metrics()
        monitor = self._make_monitor()

        # 10 evaluations with p95 > 50ms
        for _ in range(10):
            record_v11_evaluation("EURUSD", 60.0, "pass")

        fired = monitor._check_v11_latency_budget()
        types = [a["type"] for a in fired]
        assert "V11_LATENCY_BUDGET" in types
        # severity should be at least WARNING
        assert any(a["severity"] in ("WARNING", "CRITICAL") for a in fired)

    def test_v11_latency_budget_not_fired_below_threshold(self) -> None:
        from monitoring.v11_metrics import record_v11_evaluation, reset_v11_metrics

        reset_v11_metrics()
        monitor = self._make_monitor()

        for _ in range(10):
            record_v11_evaluation("EURUSD", 20.0, "pass")

        fired = monitor._check_v11_latency_budget()
        assert len(fired) == 0

    def test_exec_latency_budget_alert(self) -> None:
        from monitoring.execution_metrics import record_exec_stage, reset_execution_metrics

        reset_execution_metrics()
        monitor = self._make_monitor()

        for _ in range(10):
            record_exec_stage("guard_check", 30.0)  # exceeds 20ms budget

        fired = monitor._check_exec_latency_budget()
        assert any(a["stage"] == "guard_check" for a in fired)

    def test_v11_veto_rate_alert(self) -> None:
        from monitoring.v11_metrics import record_v11_evaluation, reset_v11_metrics

        reset_v11_metrics()
        monitor = self._make_monitor()

        # 60% veto rate > 0.50 critical threshold
        for _ in range(4):
            record_v11_evaluation("EURUSD", 10.0, "pass")
        for _ in range(6):
            record_v11_evaluation("EURUSD", 10.0, "veto")

        fired = monitor._check_anomaly_rates()
        veto_alerts = [a for a in fired if a["type"] == "V11_VETO_RATE_HIGH"]
        assert len(veto_alerts) >= 1
        assert veto_alerts[0]["severity"] == "CRITICAL"

    def test_l12_reject_rate_alert(self) -> None:
        from monitoring.execution_metrics import record_l12_outcome, reset_execution_metrics

        reset_execution_metrics()
        monitor = self._make_monitor()

        # 90% reject rate > 0.80 warning
        for _ in range(9):
            record_l12_outcome("HOLD")
        record_l12_outcome("EXECUTE_BUY")

        fired = monitor._check_anomaly_rates()
        reject_alerts = [a for a in fired if a["type"] == "L12_REJECT_RATE_HIGH"]
        assert len(reject_alerts) >= 1

    def test_l12_ambiguity_rate_alert(self) -> None:
        from monitoring.execution_metrics import record_l12_outcome, reset_execution_metrics

        reset_execution_metrics()
        monitor = self._make_monitor()

        # 20% ambiguity > 0.10 warning
        for _ in range(8):
            record_l12_outcome("EXECUTE_SELL")
        for _ in range(2):
            record_l12_outcome("CONFUSED_VERDICT")

        fired = monitor._check_anomaly_rates()
        ambig_alerts = [a for a in fired if a["type"] == "L12_AMBIGUITY_RATE_HIGH"]
        assert len(ambig_alerts) >= 1

    def test_reconnect_storm_alert(self) -> None:
        from monitoring.execution_metrics import record_reconnect_event, reset_execution_metrics

        reset_execution_metrics()
        monitor = self._make_monitor()

        # Trigger storm
        for _ in range(10):
            record_reconnect_event()

        fired = monitor._check_reconnect_storm()
        assert any(a["type"] == "RECONNECT_STORM" for a in fired)

    def test_no_v11_latency_alert_insufficient_samples(self) -> None:
        from monitoring.v11_metrics import record_v11_evaluation, reset_v11_metrics

        reset_v11_metrics()
        monitor = self._make_monitor()

        # Only 3 samples, min_samples=5
        for _ in range(3):
            record_v11_evaluation("EURUSD", 200.0, "pass")

        fired = monitor._check_v11_latency_budget()
        assert len(fired) == 0


# ═══════════════════════════════════════════════════════════════════════
#  Alert formatter / notifier integration
# ═══════════════════════════════════════════════════════════════════════


class TestAlertFormatterP28:
    def test_v11_latency_format(self) -> None:
        from alerts.alert_formatter import AlertFormatter

        text = AlertFormatter.format_v11_latency_budget("EURUSD", 95.0, 120.0, 100.0, "WARNING")
        assert "V11 LATENCY BUDGET" in text
        assert "EURUSD" in text
        assert "95.0ms" in text

    def test_exec_latency_format(self) -> None:
        from alerts.alert_formatter import AlertFormatter

        text = AlertFormatter.format_exec_latency_budget("broker_call", 3000.0, 5000.0, 2500.0)
        assert "EXECUTION LATENCY BUDGET" in text
        assert "broker_call" in text

    def test_anomaly_rate_format(self) -> None:
        from alerts.alert_formatter import AlertFormatter

        text = AlertFormatter.format_anomaly_rate("v11_veto_rate", 0.45, 0.30, "WARNING", 200)
        assert "ANOMALY RATE" in text
        assert "45.0%" in text

    def test_reconnect_storm_format(self) -> None:
        from alerts.alert_formatter import AlertFormatter

        text = AlertFormatter.format_reconnect_storm()
        assert "RECONNECT STORM" in text
