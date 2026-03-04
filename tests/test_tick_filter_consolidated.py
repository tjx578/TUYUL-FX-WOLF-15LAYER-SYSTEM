"""Tests for consolidated tick filter — per-symbol threshold support."""

from analysis.tick_filter import SpikeFilter, TickFilterConfig


class TestPerSymbolThresholds:
    """Verify SpikeFilter respects per_symbol_spike_pct overrides."""

    def _make_filter(self) -> SpikeFilter:
        config = TickFilterConfig(
            spike_threshold_pct=0.5,  # default
            staleness_seconds=300.0,
            per_symbol_spike_pct={
                "XAUUSD": 2.0,
                "GBPJPY": 1.0,
            },
        )
        return SpikeFilter(config)

    def test_default_threshold_applied(self) -> None:
        sf = self._make_filter()
        sf.check("EURUSD", 1.1000, timestamp=1000.0)
        # 0.6% move — exceeds default 0.5%
        result = sf.check("EURUSD", 1.1066, timestamp=1001.0)
        assert result.accepted is False
        assert result.is_spike is True

    def test_xauusd_uses_wide_threshold(self) -> None:
        sf = self._make_filter()
        sf.check("XAUUSD", 2000.0, timestamp=1000.0)
        # 1.5% move — within XAUUSD's 2% threshold
        result = sf.check("XAUUSD", 2030.0, timestamp=1001.0)
        assert result.accepted is True
        assert result.is_spike is False

    def test_xauusd_rejects_beyond_threshold(self) -> None:
        sf = self._make_filter()
        sf.check("XAUUSD", 2000.0, timestamp=1000.0)
        # 2.5% move — exceeds XAUUSD's 2% threshold
        result = sf.check("XAUUSD", 2050.0, timestamp=1001.0)
        assert result.accepted is False
        assert result.is_spike is True

    def test_gbpjpy_uses_medium_threshold(self) -> None:
        sf = self._make_filter()
        sf.check("GBPJPY", 150.0, timestamp=1000.0)
        # 0.8% move — within GBPJPY's 1% threshold
        result = sf.check("GBPJPY", 151.2, timestamp=1001.0)
        assert result.accepted is True

    def test_gbpjpy_rejects_beyond_threshold(self) -> None:
        sf = self._make_filter()
        sf.check("GBPJPY", 150.0, timestamp=1000.0)
        # 1.2% move — exceeds GBPJPY's 1% threshold
        result = sf.check("GBPJPY", 151.8, timestamp=1001.0)
        assert result.accepted is False

    def test_unknown_symbol_uses_default(self) -> None:
        sf = self._make_filter()
        sf.check("NZDUSD", 0.6000, timestamp=1000.0)
        # 0.6% move — exceeds default 0.5% threshold
        result = sf.check("NZDUSD", 0.6036, timestamp=1001.0)
        assert result.accepted is False

    def test_empty_per_symbol_map_uses_default(self) -> None:
        config = TickFilterConfig(spike_threshold_pct=1.0, per_symbol_spike_pct={})
        sf = SpikeFilter(config)
        sf.check("EURUSD", 1.1000, timestamp=1000.0)
        # 0.8% move — within default 1%
        result = sf.check("EURUSD", 1.1088, timestamp=1001.0)
        assert result.accepted is True
