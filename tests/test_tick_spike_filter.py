"""Tests for tick spike filter, dedup, and rate metrics in ingest dependencies."""

import time

from unittest.mock import patch

from ingest.dependencies import (
    _DEDUP_WINDOW_SECONDS,
    _STALENESS_THRESHOLD_SECONDS,
    SPIKE_THRESHOLDS,
    _dedup_cache,
    _is_duplicate_tick,
    _is_valid_tick,
    _last_prices,
    _last_exchange_ts_ms,
    _last_timestamps,
    tick_metrics,
)


class TestTickSpikeFilter:
    def setup_method(self):
        _last_prices.clear()
        _last_timestamps.clear()
        _last_exchange_ts_ms.clear()
        _dedup_cache.clear()

    def test_first_tick_always_valid(self):
        assert _is_valid_tick("EURUSD", 1.0850) is True

    def test_normal_tick_valid(self):
        _last_prices["EURUSD"] = 1.0850
        assert _is_valid_tick("EURUSD", 1.0855) is True

    def test_spike_rejected(self):
        _last_prices["EURUSD"] = 1.0850
        # 1% deviation > 0.5% threshold
        assert _is_valid_tick("EURUSD", 1.0960) is False

    def test_negative_spike_rejected(self):
        _last_prices["EURUSD"] = 1.0850
        assert _is_valid_tick("EURUSD", 1.0740) is False

    def test_boundary_tick_valid(self):
        _last_prices["EURUSD"] = 1.0000
        # Exactly 0.5% = boundary
        assert _is_valid_tick("EURUSD", 1.0050) is True

    def test_boundary_tick_above_threshold_rejected(self):
        _last_prices["EURUSD"] = 1.0000
        # Just above 0.5% threshold
        assert _is_valid_tick("EURUSD", 1.0051) is False

    def test_multiple_symbols_independent(self):
        _last_prices["EURUSD"] = 1.0850
        _last_prices["GBPUSD"] = 1.2500

        # Valid for both
        assert _is_valid_tick("EURUSD", 1.0855) is True
        assert _is_valid_tick("GBPUSD", 1.2505) is True

        # Spike only for EURUSD
        assert _is_valid_tick("EURUSD", 1.0960) is False
        assert _is_valid_tick("GBPUSD", 1.2505) is True

    def test_xauusd_wider_threshold(self):
        """Gold (XAU_USD) has 2% threshold vs 0.5% default."""
        _last_prices["XAUUSD"] = 2000.0
        now = time.monotonic()
        _last_timestamps["XAUUSD"] = now

        # 0.6% move - would reject EUR/USD but valid for XAU
        assert _is_valid_tick("XAUUSD", 2012.0) is True
        # Reference is now 2012.0 (consolidated SpikeFilter updates on accept)

        # ~0.89% from 2012 - still valid for XAU (< 2% threshold)
        assert _is_valid_tick("XAUUSD", 2030.0) is True
        # Reference is now 2030.0

        # 2.1% from current reference (2030) — exceeds XAU threshold
        assert _is_valid_tick("XAUUSD", 2073.0) is False

    def test_gbpjpy_medium_threshold(self):
        """GBP/JPY has 1% threshold."""
        _last_prices["GBPJPY"] = 150.0
        now = time.monotonic()
        _last_timestamps["GBPJPY"] = now

        # 0.6% move - valid (< 1%)
        assert _is_valid_tick("GBPJPY", 150.9) is True
        # Reference is now 150.9

        # 1.1% from 150.9 — exceeds 1% threshold
        assert _is_valid_tick("GBPJPY", 152.6) is False

    def test_staleness_triggers_baseline_reset(self):
        """After 60s gap, next tick is accepted as new baseline."""
        _last_prices["EURUSD"] = 1.0850
        old_time = time.monotonic() - (_STALENESS_THRESHOLD_SECONDS + 1.0)
        _last_timestamps["EURUSD"] = old_time

        # Price moved 2% during gap - normally rejected, but stale baseline resets
        assert _is_valid_tick("EURUSD", 1.1067) is True
        assert _last_prices["EURUSD"] == 1.1067

    def test_no_staleness_within_threshold(self):
        """Recent tick (< 60s) still enforces spike filter."""
        _last_prices["EURUSD"] = 1.0850
        now = time.monotonic()
        _last_timestamps["EURUSD"] = now - 30.0  # 30s ago

        # 1% spike still rejected (not stale)
        assert _is_valid_tick("EURUSD", 1.0960) is False

    def test_first_tick_sets_baseline_and_timestamp(self):
        """First tick for a symbol sets both price and timestamp."""
        with patch("time.monotonic", return_value=1234.5):
            assert _is_valid_tick("NEWPAIR", 1.5000) is True
            assert _last_prices["NEWPAIR"] == 1.5000
            assert _last_timestamps["NEWPAIR"] == 1234.5

    def test_timestamp_updates_on_valid_tick(self):
        """Timestamp is updated when a valid tick passes."""
        _last_prices["EURUSD"] = 1.0850
        with patch("time.monotonic", return_value=100.0):
            _is_valid_tick("EURUSD", 1.0850)  # Set initial timestamp

        with patch("time.monotonic", return_value=105.0):
            assert _is_valid_tick("EURUSD", 1.0855) is True
            assert _last_timestamps["EURUSD"] == 105.0

    def test_timestamp_not_updated_on_rejected_tick(self):
        """Timestamp stays unchanged when tick is rejected."""
        _last_prices["EURUSD"] = 1.0850
        with patch("time.monotonic", return_value=100.0):
            _is_valid_tick("EURUSD", 1.0850)

        with patch("time.monotonic", return_value=105.0):
            assert _is_valid_tick("EURUSD", 1.0960) is False
            assert _last_timestamps["EURUSD"] == 100.0  # Not updated

    def test_spike_thresholds_loaded_from_config(self):
        """SPIKE_THRESHOLDS should contain entries from finnhub.yaml tick_filter."""
        # At minimum the 6 configured symbols must be present
        for sym in ("XAUUSD", "GBPJPY", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD"):
            assert sym in SPIKE_THRESHOLDS, f"{sym} missing from SPIKE_THRESHOLDS"
        # Values should be float
        assert all(isinstance(v, float) for v in SPIKE_THRESHOLDS.values())


class TestTickDedup:
    """Tests for duplicate tick rejection."""

    def setup_method(self):
        _dedup_cache.clear()

    def test_first_tick_not_duplicate(self):
        assert _is_duplicate_tick("EURUSD", 1.0850, 1000000.0) is False

    def test_identical_tick_within_window_is_duplicate(self):
        now = time.monotonic()
        with patch("ingest.dependencies.time") as mock_time:
            mock_time.monotonic.return_value = now
            assert _is_duplicate_tick("EURUSD", 1.0850, 1000000.0) is False
            # Same tick again immediately
            assert _is_duplicate_tick("EURUSD", 1.0850, 1000000.0) is True

    def test_different_price_not_duplicate(self):
        assert _is_duplicate_tick("EURUSD", 1.0850, 1000000.0) is False
        assert _is_duplicate_tick("EURUSD", 1.0851, 1000000.0) is False

    def test_different_timestamp_not_duplicate(self):
        assert _is_duplicate_tick("EURUSD", 1.0850, 1000000.0) is False
        assert _is_duplicate_tick("EURUSD", 1.0850, 1000001.0) is False

    def test_different_symbol_not_duplicate(self):
        assert _is_duplicate_tick("EURUSD", 1.0850, 1000000.0) is False
        assert _is_duplicate_tick("GBPUSD", 1.0850, 1000000.0) is False

    def test_tick_after_window_not_duplicate(self):
        now = time.monotonic()
        with patch("ingest.dependencies.time") as mock_time:
            mock_time.monotonic.return_value = now
            assert _is_duplicate_tick("EURUSD", 1.0850, 1000000.0) is False

            # Jump past dedup window
            mock_time.monotonic.return_value = now + _DEDUP_WINDOW_SECONDS + 0.01
            assert _is_duplicate_tick("EURUSD", 1.0850, 1000000.0) is False


class TestTickRateMetrics:
    """Tests for per-symbol tick rate tracking."""

    def setup_method(self):
        tick_metrics._timestamps.clear()
        tick_metrics._rejected.clear()
        tick_metrics._duplicates.clear()
        tick_metrics._out_of_order.clear()

    def test_record_and_tps(self):
        now = time.monotonic()
        with patch("ingest.dependencies.time") as mock_time:
            mock_time.monotonic.return_value = now
            for _ in range(10):
                tick_metrics.record("EURUSD")
            tps = tick_metrics.ticks_per_second("EURUSD")
            assert tps == 10 / tick_metrics._window_sec

    def test_no_ticks_returns_zero(self):
        assert tick_metrics.ticks_per_second("NOTEXIST") == 0.0

    def test_rejected_counter(self):
        tick_metrics.record_rejected("EURUSD")
        tick_metrics.record_rejected("EURUSD")
        tick_metrics.snapshot()
        # No accepted ticks, so EURUSD might not appear in snapshot
        assert tick_metrics._rejected["EURUSD"] == 2

    def test_duplicate_counter(self):
        tick_metrics.record_duplicate("GBPUSD")
        assert tick_metrics._duplicates["GBPUSD"] == 1

    def test_snapshot_includes_all_symbols(self):
        tick_metrics.record("EURUSD")
        tick_metrics.record("GBPUSD")
        tick_metrics.record_rejected("EURUSD")
        tick_metrics.record_duplicate("GBPUSD")
        snap = tick_metrics.snapshot()
        assert "EURUSD" in snap
        assert "GBPUSD" in snap
        assert snap["EURUSD"]["rejected"] == 1
        assert snap["GBPUSD"]["duplicates"] == 1
        assert snap["EURUSD"]["ticks_per_sec"] >= 0
        assert snap["GBPUSD"]["ticks_per_sec"] >= 0

