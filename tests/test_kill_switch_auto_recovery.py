"""Tests for GlobalKillSwitch auto-recovery from feed-stale trips.

Validates FIX-2: kill switch death spiral prevention when feed recovers.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _mock_redis(monkeypatch):
    """Prevent real Redis calls in singleton."""
    monkeypatch.setattr("risk.kill_switch.redis_client", MagicMock())
    monkeypatch.setenv("STALE_DATA_THRESHOLD_SEC", "60")


@pytest.fixture()
def kill_switch():
    from risk.kill_switch import GlobalKillSwitch

    ks = GlobalKillSwitch()
    ks.disable("TEST_RESET")
    yield ks
    ks.disable("CLEANUP")


class TestAutoRecoveryFromFeedStale:
    """AUTO_FEED_STALE trips should auto-recover when feed becomes fresh."""

    def test_feed_stale_trips_kill_switch(self, kill_switch):
        result = kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 120.0})
        assert result["enabled"] is True
        assert "AUTO_FEED_STALE" in str(result["reason"])

    def test_auto_recovery_when_feed_fresh(self, kill_switch):
        """Kill switch should auto-disable when feed staleness drops below 50% of threshold."""
        # Trip it first
        kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 120.0})
        assert kill_switch.is_enabled()

        # Feed recovers to 20s (< 60*0.5 = 30s threshold)
        result = kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 20.0})
        assert result["enabled"] is False
        assert "AUTO_RECOVERY" in str(result["reason"])

    def test_no_recovery_when_feed_still_stale(self, kill_switch):
        """Kill switch stays ON if feed is still above hysteresis threshold."""
        kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 120.0})
        assert kill_switch.is_enabled()

        # Feed at 40s — still above 30s hysteresis (60*0.5)
        result = kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 40.0})
        assert result["enabled"] is True

    def test_no_auto_recovery_for_daily_dd_trips(self, kill_switch):
        """DD trips require manual release — auto-recovery must NOT fire."""
        kill_switch.evaluate_and_trip(metrics={"daily_dd_percent": 99.0})
        assert kill_switch.is_enabled()
        assert "AUTO_DAILY_DD" in str(kill_switch.snapshot()["reason"])

        # Even with fresh feed, should stay enabled (DD trip, not feed stale)
        result = kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 0.0, "daily_dd_percent": 0.0})
        assert result["enabled"] is True

    def test_no_auto_recovery_for_rapid_loss_trips(self, kill_switch):
        """Rapid-loss trips require manual release."""
        kill_switch.evaluate_and_trip(metrics={"rapid_loss_percent": 5.0})
        assert kill_switch.is_enabled()

        result = kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 0.0, "rapid_loss_percent": 0.0})
        assert result["enabled"] is True

    def test_hysteresis_prevents_rapid_cycling(self, kill_switch):
        """Feed at exactly 50% of threshold should NOT recover (boundary test)."""
        kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 120.0})
        assert kill_switch.is_enabled()

        # Feed at exactly 30s = 60*0.5 — NOT strictly less than, so no recovery
        result = kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 30.0})
        assert result["enabled"] is True

    def test_recovery_then_retrip_cycle(self, kill_switch):
        """Full cycle: trip → recover → trip again works correctly."""
        # Trip
        kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 120.0})
        assert kill_switch.is_enabled()

        # Recover
        kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 10.0})
        assert not kill_switch.is_enabled()

        # Trip again
        kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 80.0})
        assert kill_switch.is_enabled()

        # Recover again
        result = kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 5.0})
        assert result["enabled"] is False

    def test_custom_stale_threshold_via_env(self, kill_switch, monkeypatch):
        """Custom stale authority env changes both trip and recovery."""
        monkeypatch.setenv("WOLF_STALE_THRESHOLD_SECONDS", "120")

        # 80s < 120 threshold → should NOT trip
        result = kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 80.0})
        assert result["enabled"] is False

        # 130s → trips
        kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 130.0})
        assert kill_switch.is_enabled()

        # 50s < 120*0.5=60 → recovers
        result = kill_switch.evaluate_and_trip(metrics={"feed_stale_seconds": 50.0})
        assert result["enabled"] is False
