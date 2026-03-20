"""
Unit tests for LiveContextBus.check_price_drift.

Verifies that drift detection correctly compares REST H1 close
against WS tick mid-price and flags when pips exceed threshold.
"""

from __future__ import annotations

import pytest

from context.live_context_bus import LiveContextBus


@pytest.fixture(autouse=True)
def _reset_bus():
    """Reset singleton state between tests."""
    bus = LiveContextBus()
    bus.reset_state()
    bus._ticks.clear()
    yield
    bus.reset_state()
    bus._ticks.clear()


class TestCheckPriceDrift:
    """Test check_price_drift in LiveContextBus."""

    def test_no_data_returns_no_drift(self) -> None:
        """No REST candle and no tick → drifted=False, drift_pips=0."""
        bus = LiveContextBus()
        result = bus.check_price_drift("EURUSD", 50.0)
        assert result["drifted"] is False
        assert result["drift_pips"] == 0.0
        assert result["rest_close"] is None
        assert result["ws_mid"] is None

    def test_rest_only_no_tick_returns_no_drift(self) -> None:
        """REST close present but no WS tick → no drift."""
        bus = LiveContextBus()
        bus.push_candle({
            "symbol": "EURUSD",
            "timeframe": "H1",
            "close": 1.1000,
            "open": 1.0990,
            "high": 1.1010,
            "low": 1.0980,
        })
        result = bus.check_price_drift("EURUSD", 50.0)
        assert result["drifted"] is False
        assert result["rest_close"] == 1.1000
        assert result["ws_mid"] is None

    def test_tick_only_no_rest_returns_no_drift(self) -> None:
        """WS tick present but no REST candles → no drift."""
        bus = LiveContextBus()
        bus.update_tick({"symbol": "EURUSD", "bid": 1.1000, "ask": 1.1002})
        result = bus.check_price_drift("EURUSD", 50.0)
        assert result["drifted"] is False
        assert result["rest_close"] is None
        assert result["ws_mid"] == pytest.approx(1.1001)

    def test_within_threshold_not_drifted(self) -> None:
        """5-pip difference on EURUSD (pip mult 10000) → 5 pips < 50 threshold."""
        bus = LiveContextBus()
        bus.push_candle({
            "symbol": "EURUSD",
            "timeframe": "H1",
            "close": 1.10000,
            "open": 1.09900,
            "high": 1.10100,
            "low": 1.09800,
        })
        # 5 pips away: 1.10000 - 1.09950 = 0.0005 → 5 pips
        bus.update_tick({"symbol": "EURUSD", "bid": 1.09940, "ask": 1.09960})
        result = bus.check_price_drift("EURUSD", 50.0)
        assert result["drifted"] is False
        assert result["drift_pips"] == pytest.approx(5.0, abs=0.5)

    def test_exceeds_threshold_drifted(self) -> None:
        """75-pip diff on EURUSD → drifted=True."""
        bus = LiveContextBus()
        bus.push_candle({
            "symbol": "EURUSD",
            "timeframe": "H1",
            "close": 1.10000,
            "open": 1.09900,
            "high": 1.10100,
            "low": 1.09800,
        })
        # 75 pips away: 1.10000 - 1.09250 = 0.0075 → 75 pips
        bus.update_tick({"symbol": "EURUSD", "bid": 1.09240, "ask": 1.09260})
        result = bus.check_price_drift("EURUSD", 50.0)
        assert result["drifted"] is True
        assert result["drift_pips"] == pytest.approx(75.0, abs=0.5)

    def test_jpy_pair_multiplier(self) -> None:
        """USDJPY uses 100× multiplier. 0.30 raw diff → 30 pips."""
        bus = LiveContextBus()
        bus.push_candle({
            "symbol": "USDJPY",
            "timeframe": "H1",
            "close": 150.000,
            "open": 149.800,
            "high": 150.100,
            "low": 149.700,
        })
        # 30 pips away: (150.000 - 149.700) * 100 = 30
        bus.update_tick({"symbol": "USDJPY", "bid": 149.695, "ask": 149.705})
        result = bus.check_price_drift("USDJPY", 50.0)
        assert result["drifted"] is False
        assert result["drift_pips"] == pytest.approx(30.0, abs=1.0)

    def test_gold_multiplier(self) -> None:
        """XAUUSD uses 10× multiplier. $6.0 raw diff → 60 pips."""
        bus = LiveContextBus()
        bus.push_candle({
            "symbol": "XAUUSD",
            "timeframe": "H1",
            "close": 2000.00,
            "open": 1998.00,
            "high": 2002.00,
            "low": 1997.00,
        })
        # $6.0 away → 6.0 * 10 = 60 pips
        bus.update_tick({"symbol": "XAUUSD", "bid": 1993.90, "ask": 1994.10})
        result = bus.check_price_drift("XAUUSD", 50.0)
        assert result["drifted"] is True
        assert result["drift_pips"] == pytest.approx(60.0, abs=1.0)

    def test_tick_with_price_field_fallback(self) -> None:
        """Tick using 'price' instead of bid/ask still works."""
        bus = LiveContextBus()
        bus.push_candle({
            "symbol": "EURUSD",
            "timeframe": "H1",
            "close": 1.10000,
            "open": 1.09900,
            "high": 1.10100,
            "low": 1.09800,
        })
        bus.update_tick({"symbol": "EURUSD", "price": 1.09950})
        result = bus.check_price_drift("EURUSD", 50.0)
        assert result["drifted"] is False
        assert result["ws_mid"] == pytest.approx(1.09950)
        assert result["drift_pips"] == pytest.approx(5.0, abs=0.5)

    def test_unknown_pair_uses_default_multiplier(self) -> None:
        """Unknown pair falls back to 10000 multiplier."""
        bus = LiveContextBus()
        bus.push_candle({
            "symbol": "TRYMXN",
            "timeframe": "H1",
            "close": 1.50000,
            "open": 1.49000,
            "high": 1.51000,
            "low": 1.48000,
        })
        bus.update_tick({"symbol": "TRYMXN", "price": 1.49000})
        result = bus.check_price_drift("TRYMXN", 50.0)
        # 0.01 * 10000 = 100 pips with default multiplier
        assert result["drifted"] is True
        assert result["drift_pips"] == pytest.approx(100.0, abs=1.0)
