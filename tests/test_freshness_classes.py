"""Tests for P0-4: unified freshness thresholds and FreshnessClass classification."""

import time

import pytest

from state.data_freshness import (
    FEED_ADAPTER_STALE_SEC,
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


# ---------------------------------------------------------------------------
# Threshold tier constants
# ---------------------------------------------------------------------------


class TestThresholdTiers:
    """Verify that the centralized threshold constants form a valid hierarchy."""

    def test_live_threshold_positive(self):
        assert FRESHNESS_LIVE_MAX_AGE_SEC > 0

    def test_adapter_stale_positive(self):
        assert FEED_ADAPTER_STALE_SEC > 0  # noqa: F821

    def test_stale_threshold_positive(self):
        assert stale_threshold_seconds() > 0

    def test_live_lte_stale_threshold(self):
        """LIVE boundary must not exceed the overall stale threshold."""
        assert stale_threshold_seconds() >= FRESHNESS_LIVE_MAX_AGE_SEC

    def test_adapter_stale_lte_stale_threshold(self):
        """Adapter health gate should trigger before or at the pipeline stale gate."""
        assert stale_threshold_seconds() >= FEED_ADAPTER_STALE_SEC  # noqa: F821


# ---------------------------------------------------------------------------
# FeedHealth.freshness_class alignment (data_feed.py)
# ---------------------------------------------------------------------------


class TestFeedHealthFreshnessClass:
    """FeedHealth must expose a freshness_class aligned with centralized classification."""

    def test_connected_live(self):
        from analysis.data_feed import FeedHealth, FeedStatus

        h = FeedHealth(
            status=FeedStatus.CONNECTED,
            last_tick_time=time.time(),
            latency_ms=1.0,
            staleness_seconds=5.0,
        )
        assert h.freshness_class == FreshnessClass.LIVE

    def test_connected_degraded(self):
        from analysis.data_feed import FeedHealth, FeedStatus

        h = FeedHealth(
            status=FeedStatus.CONNECTED,
            last_tick_time=time.time(),
            latency_ms=1.0,
            staleness_seconds=FRESHNESS_LIVE_MAX_AGE_SEC + 5.0,
        )
        assert h.freshness_class == FreshnessClass.DEGRADED_BUT_REFRESHING

    def test_connected_stale_preserved(self):
        from analysis.data_feed import FeedHealth, FeedStatus

        h = FeedHealth(
            status=FeedStatus.CONNECTED,
            last_tick_time=time.time(),
            latency_ms=1.0,
            staleness_seconds=stale_threshold_seconds() + 10.0,
        )
        assert h.freshness_class == FreshnessClass.STALE_PRESERVED

    def test_disconnected_no_transport(self):
        from analysis.data_feed import FeedHealth, FeedStatus

        h = FeedHealth(
            status=FeedStatus.DISCONNECTED,
            last_tick_time=0.0,
            latency_ms=0.0,
            staleness_seconds=0.0,
        )
        assert h.freshness_class == FreshnessClass.NO_TRANSPORT

    def test_reconnecting_no_transport(self):
        from analysis.data_feed import FeedHealth, FeedStatus

        h = FeedHealth(
            status=FeedStatus.RECONNECTING,
            last_tick_time=0.0,
            latency_ms=0.0,
            staleness_seconds=0.0,
        )
        assert h.freshness_class == FreshnessClass.NO_TRANSPORT


# ---------------------------------------------------------------------------
# StalenessGuard defaults to centralized constant
# ---------------------------------------------------------------------------


class TestStalenessGuardAligned:
    def test_default_threshold_matches_live_max(self):
        from analysis.data_feed import StalenessGuard

        guard = StalenessGuard()
        assert guard._max_stale == FRESHNESS_LIVE_MAX_AGE_SEC

    def test_explicit_override_still_works(self):
        from analysis.data_feed import StalenessGuard

        guard = StalenessGuard(max_stale_seconds=60.0)
        assert guard._max_stale == 60.0


# ---------------------------------------------------------------------------
# FallbackTickFeedAdapter defaults to centralized constant
# ---------------------------------------------------------------------------


class TestFallbackAdapterAligned:
    def test_default_stale_matches_adapter_constant(self):
        from analysis.data_feed import DataFeedAdapter, FallbackTickFeedAdapter, FeedHealth, FeedStatus

        class _Stub(DataFeedAdapter):
            async def connect(self):
                return True

            async def disconnect(self):
                pass

            async def subscribe(self, symbols, timeframes):
                pass

            def get_health(self):
                return FeedHealth(
                    status=FeedStatus.CONNECTED,
                    last_tick_time=time.time(),
                    latency_ms=0,
                    staleness_seconds=0,
                )

        chain = FallbackTickFeedAdapter([_Stub()])
        assert chain._max_stale == FEED_ADAPTER_STALE_SEC


# ---------------------------------------------------------------------------
# DataQualityReport.freshness_class property
# ---------------------------------------------------------------------------


class TestDataQualityReportFreshnessClass:
    def test_fresh_maps_to_live(self):
        from analysis.data_quality_gate import DataQualityReport

        r = DataQualityReport(
            symbol="X",
            timeframe="M15",
            total_candles=50,
            gap_candles=0,
            gap_ratio=0.0,
            low_tick_candles=0,
            degraded=False,
            confidence_penalty=0.0,
            staleness_seconds=5.0,
            freshness_state="fresh",
            reasons=(),
        )
        assert r.freshness_class == FreshnessClass.LIVE

    def test_stale_preserved_maps(self):
        from analysis.data_quality_gate import DataQualityReport

        r = DataQualityReport(
            symbol="X",
            timeframe="M15",
            total_candles=50,
            gap_candles=0,
            gap_ratio=0.0,
            low_tick_candles=0,
            degraded=True,
            confidence_penalty=0.15,
            staleness_seconds=500.0,
            freshness_state="stale_preserved",
            reasons=("stale",),
        )
        assert r.freshness_class == FreshnessClass.STALE_PRESERVED

    def test_no_producer_maps(self):
        from analysis.data_quality_gate import DataQualityReport

        r = DataQualityReport(
            symbol="X",
            timeframe="M15",
            total_candles=0,
            gap_candles=0,
            gap_ratio=0.0,
            low_tick_candles=0,
            degraded=True,
            confidence_penalty=0.5,
            staleness_seconds=float("inf"),
            freshness_state="no_producer",
            reasons=("no_candles",),
        )
        assert r.freshness_class == FreshnessClass.NO_PRODUCER

    def test_no_transport_maps(self):
        from analysis.data_quality_gate import DataQualityReport

        r = DataQualityReport(
            symbol="X",
            timeframe="M15",
            total_candles=0,
            gap_candles=0,
            gap_ratio=0.0,
            low_tick_candles=0,
            degraded=True,
            confidence_penalty=0.5,
            staleness_seconds=float("inf"),
            freshness_state="no_transport",
            reasons=(),
        )
        assert r.freshness_class == FreshnessClass.NO_TRANSPORT


# ---------------------------------------------------------------------------
# Cross-module agreement: same input → same FreshnessClass
# ---------------------------------------------------------------------------


class TestCrossModuleAgreement:
    """All three modules must agree on classification for identical inputs."""

    @pytest.mark.parametrize(
        "staleness_sec,expected_class",
        [
            (0.0, FreshnessClass.LIVE),
            (5.0, FreshnessClass.LIVE),
            (FRESHNESS_LIVE_MAX_AGE_SEC, FreshnessClass.LIVE),
            (FRESHNESS_LIVE_MAX_AGE_SEC + 0.1, FreshnessClass.DEGRADED_BUT_REFRESHING),
            (60.0, FreshnessClass.DEGRADED_BUT_REFRESHING),
            (299.0, FreshnessClass.DEGRADED_BUT_REFRESHING),
        ],
    )
    def test_classify_and_feed_health_agree(self, staleness_sec, expected_class):
        """classify_feed_freshness and FeedHealth.freshness_class must agree."""
        from analysis.data_feed import FeedHealth, FeedStatus

        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            staleness_seconds=staleness_sec,
        )
        assert snap.freshness_class == expected_class

        h = FeedHealth(
            status=FeedStatus.CONNECTED,
            last_tick_time=time.time(),
            latency_ms=1.0,
            staleness_seconds=staleness_sec,
        )
        assert h.freshness_class == expected_class

    def test_stale_preserved_agreement(self):
        from analysis.data_feed import FeedHealth, FeedStatus

        big = stale_threshold_seconds() + 10.0
        snap = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=True,
            staleness_seconds=big,
        )
        h = FeedHealth(
            status=FeedStatus.CONNECTED,
            last_tick_time=time.time(),
            latency_ms=1.0,
            staleness_seconds=big,
        )
        assert snap.freshness_class == h.freshness_class == FreshnessClass.STALE_PRESERVED
