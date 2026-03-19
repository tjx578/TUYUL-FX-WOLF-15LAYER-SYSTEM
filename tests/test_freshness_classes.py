"""Tests for P0-4: unified freshness thresholds and FreshnessClass classification."""

import time

import pytest

from state.data_freshness import (
    FRESHNESS_LIVE_MAX_AGE_SEC,
    FreshnessClass,
    classify_feed_freshness,
    stale_threshold_seconds,
)

# ---------------------------------------------------------------------------
# FreshnessClass enum basics
# ---------------------------------------------------------------------------


class TestFreshnessClassEnum:
    def test_all_approved_values_exist(self):
        expected = {"LIVE", "DEGRADED_BUT_REFRESHING", "STALE_PRESERVED", "NO_PRODUCER", "NO_TRANSPORT", "CONFIG_ERROR"}
        assert {c.value for c in FreshnessClass} == expected

    def test_is_str_enum(self):
        assert isinstance(FreshnessClass.LIVE, str)
        assert FreshnessClass.LIVE == "LIVE"


# ---------------------------------------------------------------------------
# freshness_class property on FeedFreshnessSnapshot
# ---------------------------------------------------------------------------


class TestFreshnessClassProperty:
    def test_live_when_staleness_within_live_threshold(self):
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            staleness_seconds=5.0,
        )
        assert snap.freshness_class == FreshnessClass.LIVE

    def test_live_at_boundary(self):
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            staleness_seconds=FRESHNESS_LIVE_MAX_AGE_SEC,
        )
        assert snap.freshness_class == FreshnessClass.LIVE

    def test_degraded_just_past_live_threshold(self):
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            staleness_seconds=FRESHNESS_LIVE_MAX_AGE_SEC + 0.1,
        )
        assert snap.freshness_class == FreshnessClass.DEGRADED_BUT_REFRESHING

    def test_degraded_within_stale_threshold(self):
        threshold = stale_threshold_seconds()
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            staleness_seconds=threshold - 1.0,
        )
        assert snap.freshness_class == FreshnessClass.DEGRADED_BUT_REFRESHING

    def test_stale_preserved_past_stale_threshold(self):
        threshold = stale_threshold_seconds()
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            staleness_seconds=threshold + 1.0,
        )
        assert snap.freshness_class == FreshnessClass.STALE_PRESERVED

    def test_no_producer(self):
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=False,
        )
        assert snap.freshness_class == FreshnessClass.NO_PRODUCER

    def test_no_transport(self):
        snap = classify_feed_freshness(
            transport_ok=False,
            has_producer_signal=True,
        )
        assert snap.freshness_class == FreshnessClass.NO_TRANSPORT

    def test_config_error(self):
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            config_ok=False,
        )
        assert snap.freshness_class == FreshnessClass.CONFIG_ERROR


# ---------------------------------------------------------------------------
# Boundary transitions using last_seen_ts
# ---------------------------------------------------------------------------


class TestFreshnessClassFromTimestamp:
    def test_recent_ts_is_live(self):
        now = time.time()
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            last_seen_ts=now - 5.0,
            now_ts=now,
        )
        assert snap.freshness_class == FreshnessClass.LIVE
        assert snap.staleness_seconds == pytest.approx(5.0, abs=0.5)

    def test_ts_in_degraded_range(self):
        now = time.time()
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            last_seen_ts=now - 60.0,
            now_ts=now,
        )
        assert snap.freshness_class == FreshnessClass.DEGRADED_BUT_REFRESHING

    def test_ts_beyond_stale_threshold(self):
        now = time.time()
        threshold = stale_threshold_seconds()
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            last_seen_ts=now - threshold - 10.0,
            now_ts=now,
        )
        assert snap.freshness_class == FreshnessClass.STALE_PRESERVED


# ---------------------------------------------------------------------------
# LiveContextBus integration with unified freshness
# ---------------------------------------------------------------------------


class TestLiveContextBusFreshness:
    def setup_method(self):
        from context.live_context_bus import LiveContextBus

        LiveContextBus.reset_singleton()
        self.bus = LiveContextBus()

    def test_fresh_tick_returns_live(self):
        self.bus.update_tick({"symbol": "EURUSD", "bid": 1.08, "ask": 1.09, "timestamp": time.time()})
        assert self.bus.get_feed_status("EURUSD") == FreshnessClass.LIVE.value

    def test_no_tick_returns_no_producer(self):
        assert self.bus.get_feed_status("NOPAIR") == FreshnessClass.NO_PRODUCER.value

    def test_all_feed_status_uses_freshness_class(self):
        self.bus.update_tick({"symbol": "EURUSD", "bid": 1.08, "ask": 1.09, "timestamp": time.time()})
        statuses = self.bus.get_all_feed_status()
        assert statuses["EURUSD"]["status"] == FreshnessClass.LIVE.value

    def test_is_feed_stale_uses_central_threshold(self):
        """is_feed_stale default should be centralized stale_threshold_seconds(), not hardcoded 30s."""
        self.bus.update_tick({"symbol": "EURUSD", "bid": 1.08, "ask": 1.09, "timestamp": time.time()})
        # Default threshold is 300s — a just-received tick should not be stale
        assert self.bus.is_feed_stale("EURUSD") is False
