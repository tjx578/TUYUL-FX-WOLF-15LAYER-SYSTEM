"""Tests for tick spike filter in ingest dependencies."""

import time
from unittest.mock import patch

from ingest.dependencies import (
    MAX_DEVIATION_PCT,
    SPIKE_THRESHOLDS,
    _STALENESS_THRESHOLD_SECONDS,
    _is_valid_tick,
    _last_prices,
    _last_timestamps,
)


class TestTickSpikeFilter:
    def setup_method(self):
        _last_prices.clear()
        _last_timestamps.clear()

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

        # 0.6% move — would reject EUR/USD but valid for XAU
        assert _is_valid_tick("XAUUSD", 2012.0) is True

        # 1.5% move — still valid for XAU (< 2% threshold)
        assert _is_valid_tick("XAUUSD", 2030.0) is True

        # 2.1% move — exceeds XAU threshold
        assert _is_valid_tick("XAUUSD", 2042.0) is False

    def test_gbpjpy_medium_threshold(self):
        """GBP/JPY has 1% threshold."""
        _last_prices["GBPJPY"] = 150.0
        now = time.monotonic()
        _last_timestamps["GBPJPY"] = now

        # 0.6% move — valid (< 1%)
        assert _is_valid_tick("GBPJPY", 150.9) is True

        # 1.1% move — exceeds threshold
        assert _is_valid_tick("GBPJPY", 151.65) is False

    def test_staleness_triggers_baseline_reset(self):
        """After 60s gap, next tick is accepted as new baseline."""
        _last_prices["EURUSD"] = 1.0850
        old_time = time.monotonic() - (_STALENESS_THRESHOLD_SECONDS + 1.0)
        _last_timestamps["EURUSD"] = old_time

        # Price moved 2% during gap — normally rejected, but stale baseline resets
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

