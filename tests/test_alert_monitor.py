"""Tests for AlertMonitor — threshold evaluation and alert dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from alerts.alert_monitor import AlertMonitor, _AlertCooldown
from alerts.alert_rules import ALERT_RULES, DEFAULT_THRESHOLDS, AlertThresholds
from core.metrics import (
    CIRCUIT_BREAKER_STATE,
    DAILY_LOSS_PERCENT,
    DRAWDOWN_MAX_PERCENT,
    FEED_AGE,
    KILL_SWITCH_ACTIVE,
)


@pytest.fixture(autouse=True)
def _reset_metrics():
    """Reset metric children between tests to avoid cross-contamination."""
    # Clear labelled children (gauges track state from prior tests)
    for metric in [FEED_AGE, DAILY_LOSS_PERCENT, DRAWDOWN_MAX_PERCENT, CIRCUIT_BREAKER_STATE, KILL_SWITCH_ACTIVE]:
        with metric._lock:
            metric._children.clear()
        if metric._no_label is not None:
            metric._no_label.set(0.0)
    yield


@pytest.fixture()
def mock_notifier():
    return MagicMock()


@pytest.fixture()
def monitor(mock_notifier):
    return AlertMonitor(notifier=mock_notifier)


# ═══════════════════════════════════════════════════════════════════════════
#  Cooldown
# ═══════════════════════════════════════════════════════════════════════════


class TestCooldown:
    def test_first_fire_allowed(self):
        cd = _AlertCooldown(cooldown_seconds=60.0)
        assert cd.should_fire("test_key")

    def test_second_fire_blocked(self):
        cd = _AlertCooldown(cooldown_seconds=60.0)
        assert cd.should_fire("test_key")
        assert not cd.should_fire("test_key")

    def test_different_keys_independent(self):
        cd = _AlertCooldown(cooldown_seconds=60.0)
        assert cd.should_fire("key_a")
        assert cd.should_fire("key_b")

    def test_fire_after_cooldown(self):
        cd = _AlertCooldown(cooldown_seconds=0.0)
        assert cd.should_fire("test_key")
        assert cd.should_fire("test_key")


# ═══════════════════════════════════════════════════════════════════════════
#  Feed staleness alerts
# ═══════════════════════════════════════════════════════════════════════════


class TestFeedStaleness:
    def test_no_alert_when_fresh(self, monitor, mock_notifier):
        FEED_AGE.labels(symbol="EURUSD").set(5.0)
        fired = monitor.evaluate()
        assert len(fired) == 0
        mock_notifier.on_feed_stale.assert_not_called()

    def test_warning_at_threshold(self, monitor, mock_notifier):
        FEED_AGE.labels(symbol="EURUSD").set(20.0)
        fired = monitor.evaluate()
        assert len(fired) == 1
        assert fired[0]["severity"] == "WARNING"
        mock_notifier.on_feed_stale.assert_called_once_with("EURUSD", 20.0)

    def test_critical_at_threshold(self, monitor, mock_notifier):
        FEED_AGE.labels(symbol="GBPUSD").set(45.0)
        fired = monitor.evaluate()
        stale_alerts = [a for a in fired if a["type"] == "FEED_STALE"]
        assert len(stale_alerts) == 1
        assert stale_alerts[0]["severity"] == "CRITICAL"
        mock_notifier.on_feed_stale.assert_called_once_with("GBPUSD", 45.0)

    def test_multiple_symbols(self, monitor, mock_notifier):
        FEED_AGE.labels(symbol="EURUSD").set(20.0)
        FEED_AGE.labels(symbol="GBPUSD").set(45.0)
        fired = monitor.evaluate()
        stale_alerts = [a for a in fired if a["type"] == "FEED_STALE"]
        assert len(stale_alerts) == 2

    def test_disabled_rule(self, mock_notifier):
        original = ALERT_RULES["FEED_STALE"]
        try:
            ALERT_RULES["FEED_STALE"] = False
            monitor = AlertMonitor(notifier=mock_notifier)
            FEED_AGE.labels(symbol="EURUSD").set(45.0)
            fired = monitor.evaluate()
            stale_alerts = [a for a in fired if a["type"] == "FEED_STALE"]
            assert len(stale_alerts) == 0
        finally:
            ALERT_RULES["FEED_STALE"] = original


# ═══════════════════════════════════════════════════════════════════════════
#  Drawdown alerts
# ═══════════════════════════════════════════════════════════════════════════


class TestDrawdown:
    def test_no_alert_below_threshold(self, monitor, mock_notifier):
        DAILY_LOSS_PERCENT.labels(account_id="test").set(1.0)
        fired = monitor.evaluate()
        dd_alerts = [a for a in fired if "DAILY_LOSS" in a.get("type", "")]
        assert len(dd_alerts) == 0

    def test_daily_loss_warning(self, monitor, mock_notifier):
        DAILY_LOSS_PERCENT.labels(account_id="ftmo1").set(3.5)
        fired = monitor.evaluate()
        dd_alerts = [a for a in fired if a["type"] == "DAILY_LOSS_WARNING"]
        assert len(dd_alerts) == 1
        mock_notifier.on_daily_loss_alert.assert_called_once_with("ftmo1", 3.5, "WARNING")

    def test_daily_loss_critical(self, monitor, mock_notifier):
        DAILY_LOSS_PERCENT.labels(account_id="ftmo1").set(4.5)
        fired = monitor.evaluate()
        dd_alerts = [a for a in fired if a["type"] == "DAILY_LOSS_CRITICAL"]
        assert len(dd_alerts) == 1
        mock_notifier.on_daily_loss_alert.assert_called_once_with("ftmo1", 4.5, "CRITICAL")

    def test_max_drawdown_warning(self, monitor, mock_notifier):
        DRAWDOWN_MAX_PERCENT.labels(account_id="ftmo1").set(7.0)
        fired = monitor.evaluate()
        dd_alerts = [a for a in fired if a["type"] == "DRAWDOWN_WARNING"]
        assert len(dd_alerts) == 1

    def test_max_drawdown_critical(self, monitor, mock_notifier):
        DRAWDOWN_MAX_PERCENT.labels(account_id="ftmo1").set(9.0)
        fired = monitor.evaluate()
        dd_alerts = [a for a in fired if a["type"] == "DRAWDOWN_CRITICAL"]
        assert len(dd_alerts) == 1
        mock_notifier.on_drawdown_alert.assert_called_once()

    def test_custom_thresholds(self, mock_notifier):
        custom = AlertThresholds(daily_loss_warning_percent=1.0, daily_loss_critical_percent=2.0)
        monitor = AlertMonitor(notifier=mock_notifier, thresholds=custom)
        DAILY_LOSS_PERCENT.labels(account_id="t1").set(1.5)
        fired = monitor.evaluate()
        dd_alerts = [a for a in fired if a["type"] == "DAILY_LOSS_WARNING"]
        assert len(dd_alerts) == 1


# ═══════════════════════════════════════════════════════════════════════════
#  Kill switch alerts
# ═══════════════════════════════════════════════════════════════════════════


class TestKillSwitch:
    def test_no_alert_when_normal(self, monitor, mock_notifier):
        KILL_SWITCH_ACTIVE.set(0.0)
        fired = monitor.evaluate()
        ks_alerts = [a for a in fired if a.get("type") == "KILL_SWITCH_TRIPPED"]
        assert len(ks_alerts) == 0

    def test_alert_when_tripped(self, monitor, mock_notifier):
        KILL_SWITCH_ACTIVE.set(1.0)
        fired = monitor.evaluate()
        ks_alerts = [a for a in fired if a.get("type") == "KILL_SWITCH_TRIPPED"]
        assert len(ks_alerts) == 1
        mock_notifier.on_kill_switch.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
#  Circuit breaker alerts
# ═══════════════════════════════════════════════════════════════════════════


class TestCircuitBreakerAlerts:
    def test_no_alert_when_closed(self, monitor, mock_notifier):
        CIRCUIT_BREAKER_STATE.labels(name="finnhub").set(0)
        fired = monitor.evaluate()
        cb_alerts = [a for a in fired if "CIRCUIT_BREAKER" in a.get("type", "")]
        assert len(cb_alerts) == 0

    def test_alert_when_open(self, monitor, mock_notifier):
        CIRCUIT_BREAKER_STATE.labels(name="finnhub").set(2)
        fired = monitor.evaluate()
        cb_alerts = [a for a in fired if a["type"] == "CIRCUIT_BREAKER_OPEN"]
        assert len(cb_alerts) == 1
        mock_notifier.on_circuit_breaker.assert_called_once_with("finnhub", "OPEN", 0)

    def test_alert_when_half_open(self, monitor, mock_notifier):
        CIRCUIT_BREAKER_STATE.labels(name="ff").set(1)
        fired = monitor.evaluate()
        cb_alerts = [a for a in fired if a["type"] == "CIRCUIT_BREAKER_HALF_OPEN"]
        assert len(cb_alerts) == 1


# ═══════════════════════════════════════════════════════════════════════════
#  Alert rules & thresholds
# ═══════════════════════════════════════════════════════════════════════════


class TestAlertRules:
    def test_all_rule_keys_are_bool(self):
        for key, val in ALERT_RULES.items():
            assert isinstance(val, bool), f"{key} should be bool, got {type(val)}"

    def test_new_rules_exist(self):
        expected = [
            "FEED_STALE",
            "FEED_RECONNECT",
            "DRAWDOWN_CRITICAL",
            "DAILY_LOSS_WARNING",
            "DAILY_LOSS_CRITICAL",
            "KILL_SWITCH_TRIPPED",
            "CIRCUIT_BREAKER_OPEN",
            "PIPELINE_LATENCY_HIGH",
        ]
        for key in expected:
            assert key in ALERT_RULES, f"Missing rule: {key}"

    def test_default_thresholds_reasonable(self):
        t = DEFAULT_THRESHOLDS
        assert 10 < t.feed_stale_warning_seconds < t.feed_stale_critical_seconds
        assert 0 < t.daily_loss_warning_percent < t.daily_loss_critical_percent
        assert 0 < t.max_drawdown_warning_percent < t.max_drawdown_critical_percent

    def test_threshold_immutability(self):
        with pytest.raises(AttributeError):
            DEFAULT_THRESHOLDS.feed_stale_critical_seconds = 999  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════
#  Alert formatter
# ═══════════════════════════════════════════════════════════════════════════


class TestAlertFormatter:
    def test_format_feed_stale(self):
        from alerts.alert_formatter import AlertFormatter

        msg = AlertFormatter.format_feed_stale("EURUSD", 45.0)
        assert "EURUSD" in msg
        assert "45.0s" in msg
        assert "CRITICAL" in msg

    def test_format_feed_stale_warning(self):
        from alerts.alert_formatter import AlertFormatter

        msg = AlertFormatter.format_feed_stale("GBPJPY", 20.0)
        assert "WARNING" in msg

    def test_format_drawdown_alert(self):
        from alerts.alert_formatter import AlertFormatter

        msg = AlertFormatter.format_drawdown_alert("ftmo1", 7.5, 3.2, "WARNING")
        assert "ftmo1" in msg
        assert "7.50%" in msg
        assert "3.20%" in msg

    def test_format_kill_switch(self):
        from alerts.alert_formatter import AlertFormatter

        msg = AlertFormatter.format_kill_switch("Max drawdown exceeded")
        assert "KILL SWITCH" in msg
        assert "Max drawdown exceeded" in msg

    def test_format_circuit_breaker(self):
        from alerts.alert_formatter import AlertFormatter

        msg = AlertFormatter.format_circuit_breaker("finnhub", "OPEN", 5)
        assert "finnhub" in msg
        assert "OPEN" in msg

    def test_format_pipeline_latency(self):
        from alerts.alert_formatter import AlertFormatter

        msg = AlertFormatter.format_pipeline_latency(3.456, "tick_to_context")
        assert "3.456s" in msg
        assert "tick_to_context" in msg
