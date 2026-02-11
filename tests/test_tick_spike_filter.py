"""Tests for tick spike filter in ingest dependencies."""

from ingest.dependencies import MAX_DEVIATION_PCT, _is_valid_tick, _last_prices


class TestTickSpikeFilter:
    def setup_method(self):
        _last_prices.clear()

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
