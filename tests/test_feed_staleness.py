"""Tests for feed staleness monitoring."""

import time

from context.live_context_bus import LiveContextBus


class TestFeedStaleness:
    def setup_method(self):
        # Reset singleton for clean test
        LiveContextBus.reset_singleton()
        self.bus = LiveContextBus()

    def test_no_data_is_stale(self):
        assert self.bus.is_feed_stale("EURUSD") is True

    def test_fresh_tick_not_stale(self):
        tick = {
            "symbol": "EURUSD",
            "bid": 1.0850,
            "ask": 1.0852,
            "timestamp": time.time(),
            "source": "test",
        }
        self.bus.update_tick(tick)
        assert self.bus.is_feed_stale("EURUSD") is False

    def test_feed_status_connected(self):
        tick = {
            "symbol": "EURUSD",
            "bid": 1.0850,
            "ask": 1.0852,
            "timestamp": time.time(),
            "source": "test",
        }
        self.bus.update_tick(tick)
        assert self.bus.get_feed_status("EURUSD") == "CONNECTED"

    def test_feed_status_no_data(self):
        assert self.bus.get_feed_status("UNKNOWN_PAIR") == "NO_DATA"

    def test_get_feed_age_none_when_no_data(self):
        assert self.bus.get_feed_age("UNKNOWN_PAIR") is None

    def test_get_feed_age_returns_float(self):
        tick = {
            "symbol": "EURUSD",
            "bid": 1.0850,
            "ask": 1.0852,
            "timestamp": time.time(),
            "source": "test",
        }
        self.bus.update_tick(tick)
        age = self.bus.get_feed_age("EURUSD")
        assert age is not None
        assert age >= 0.0

    def test_feed_age_increases_over_time(self):
        tick = {
            "symbol": "EURUSD",
            "bid": 1.0850,
            "ask": 1.0852,
            "timestamp": time.time(),
            "source": "test",
        }
        self.bus.update_tick(tick)
        age1 = self.bus.get_feed_age("EURUSD")
        time.sleep(0.1)  # Wait 100ms
        age2 = self.bus.get_feed_age("EURUSD")
        assert age2 is not None
        assert age1 is not None
        assert age2 > age1

    def test_custom_staleness_threshold(self):
        tick = {
            "symbol": "EURUSD",
            "bid": 1.0850,
            "ask": 1.0852,
            "timestamp": time.time(),
            "source": "test",
        }
        self.bus.update_tick(tick)
        # Should not be stale with high threshold
        assert self.bus.is_feed_stale("EURUSD", threshold_sec=60.0) is False

    def test_multiple_symbols_independent_staleness(self):
        tick1 = {
            "symbol": "EURUSD",
            "bid": 1.0850,
            "ask": 1.0852,
            "timestamp": time.time(),
            "source": "test",
        }
        self.bus.update_tick(tick1)

        # EURUSD should be fresh
        assert self.bus.is_feed_stale("EURUSD") is False
        # GBPUSD should be stale (no data)
        assert self.bus.is_feed_stale("GBPUSD") is True
