"""
Unit tests for LiveContextBus.check_price_drift.

Verifies that drift detection requires aligned REST and WS-built closed H1
candles. The current WS mid remains observational evidence only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest
from loguru import logger

from context.live_context_bus import LiveContextBus

_OPEN_TIME = datetime(2026, 9, 3, 4, 0, tzinfo=UTC)
_CLOSE_TIME = datetime(2026, 9, 3, 5, 0, tzinfo=UTC)


def _push_closed_h1(
    bus: LiveContextBus,
    *,
    symbol: str,
    close: float,
    ws_built: bool = False,
    open_time: datetime = _OPEN_TIME,
    close_time: datetime = _CLOSE_TIME,
) -> None:
    bus.push_candle(
        {
            "symbol": symbol,
            "timeframe": "H1",
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "open_time": open_time,
            "close_time": close_time,
            "complete": True,
            "provider": "wolf15_tick_builder" if ws_built else "finnhub",
            "provider_feed": "finnhub_ws" if ws_built else "oanda_rest",
        }
    )


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
        assert result["comparable"] is False
        assert result["reason"] == "MISSING_REST_H1"
        assert result["drifted"] is False
        assert result["drift_pips"] == 0.0
        assert result["rest_close"] is None
        assert result["ws_mid"] is None

    def test_rest_only_no_tick_returns_no_drift(self) -> None:
        """REST close present but no WS tick → no drift."""
        bus = LiveContextBus()
        _push_closed_h1(bus, symbol="EURUSD", close=1.1000)
        result = bus.check_price_drift("EURUSD", 50.0)
        assert result["comparable"] is False
        assert result["reason"] == "MISSING_ALIGNED_WS_CLOSED_H1"
        assert result["drifted"] is False
        assert result["rest_close"] == 1.1000
        assert result["ws_mid"] is None

    def test_tick_only_no_rest_returns_no_drift(self) -> None:
        """WS tick present but no REST candles → no drift."""
        bus = LiveContextBus()
        bus.update_tick({"symbol": "EURUSD", "bid": 1.1000, "ask": 1.1002})
        result = bus.check_price_drift("EURUSD", 50.0)
        assert result["comparable"] is False
        assert result["drifted"] is False
        assert result["rest_close"] is None
        assert result["ws_mid"] == pytest.approx(1.1001)

    def test_within_threshold_not_drifted(self) -> None:
        """5-pip difference on EURUSD (pip mult 10000) → 5 pips < 50 threshold."""
        bus = LiveContextBus()
        _push_closed_h1(bus, symbol="EURUSD", close=1.10000)
        _push_closed_h1(bus, symbol="EURUSD", close=1.09950, ws_built=True)
        result = bus.check_price_drift("EURUSD", 50.0)
        assert result["comparable"] is True
        assert result["drifted"] is False
        assert result["drift_pips"] == pytest.approx(5.0, abs=0.5)

    def test_exceeds_threshold_drifted(self) -> None:
        """75-pip diff on EURUSD → drifted=True."""
        bus = LiveContextBus()
        _push_closed_h1(bus, symbol="EURUSD", close=1.10000)
        _push_closed_h1(bus, symbol="EURUSD", close=1.09250, ws_built=True)
        result = bus.check_price_drift("EURUSD", 50.0)
        assert result["comparable"] is True
        assert result["drifted"] is True
        assert result["drift_pips"] == pytest.approx(75.0, abs=0.5)

    def test_jpy_pair_multiplier(self) -> None:
        """USDJPY uses 100× multiplier. 0.30 raw diff → 30 pips."""
        bus = LiveContextBus()
        _push_closed_h1(bus, symbol="USDJPY", close=150.000)
        _push_closed_h1(bus, symbol="USDJPY", close=149.700, ws_built=True)
        result = bus.check_price_drift("USDJPY", 50.0)
        assert result["drifted"] is False
        assert result["drift_pips"] == pytest.approx(30.0, abs=1.0)

    def test_gold_multiplier(self) -> None:
        """XAUUSD uses 10× multiplier. $6.0 raw diff → 60 pips."""
        bus = LiveContextBus()
        _push_closed_h1(bus, symbol="XAUUSD", close=2000.00)
        _push_closed_h1(bus, symbol="XAUUSD", close=1994.00, ws_built=True)
        result = bus.check_price_drift("XAUUSD", 50.0)
        assert result["drifted"] is True
        assert result["drift_pips"] == pytest.approx(60.0, abs=1.0)

    def test_tick_with_price_field_fallback(self) -> None:
        """Tick using 'price' instead of bid/ask still works."""
        bus = LiveContextBus()
        _push_closed_h1(bus, symbol="EURUSD", close=1.10000)
        bus.update_tick({"symbol": "EURUSD", "price": 1.09950})
        result = bus.check_price_drift("EURUSD", 50.0)
        assert result["comparable"] is False
        assert result["drifted"] is False
        assert result["ws_mid"] == pytest.approx(1.09950)
        assert result["drift_pips"] == 0.0
        assert result["observed_live_gap_pips"] == pytest.approx(5.0, abs=0.5)

    def test_unknown_pair_uses_default_multiplier(self) -> None:
        """Unknown pair falls back to 10000 multiplier."""
        bus = LiveContextBus()
        _push_closed_h1(bus, symbol="TRYMXN", close=1.50000)
        _push_closed_h1(bus, symbol="TRYMXN", close=1.49000, ws_built=True)
        result = bus.check_price_drift("TRYMXN", 50.0)
        # 0.01 * 10000 = 100 pips with default multiplier
        assert result["drifted"] is True
        assert result["drift_pips"] == pytest.approx(100.0, abs=1.0)

    def test_large_rest_close_vs_live_mid_gap_is_not_a_drift_verdict(self) -> None:
        """The incident shape remains observable but cannot degrade the symbol."""
        bus = LiveContextBus()
        _push_closed_h1(bus, symbol="XAUUSD", close=4437.405)
        bus.update_tick({"symbol": "XAUUSD", "bid": 4428.155, "ask": 4428.355})

        result = bus.check_price_drift("XAUUSD", 50.0)

        assert result["comparable"] is False
        assert result["reason"] == "MISSING_ALIGNED_WS_CLOSED_H1"
        assert result["drifted"] is False
        assert result["drift_pips"] == 0.0
        assert result["observed_live_gap_pips"] == pytest.approx(91.5)

    def test_closed_h1_with_different_close_time_is_not_comparable(self) -> None:
        bus = LiveContextBus()
        _push_closed_h1(bus, symbol="XAUUSD", close=4437.405)
        _push_closed_h1(
            bus,
            symbol="XAUUSD",
            close=4428.255,
            ws_built=True,
            open_time=_OPEN_TIME + timedelta(hours=1),
            close_time=_CLOSE_TIME + timedelta(hours=1),
        )

        result = bus.check_price_drift("XAUUSD", 50.0)

        assert result["comparable"] is False
        assert result["reason"] == "MISSING_ALIGNED_WS_CLOSED_H1"
        assert result["drifted"] is False

    def test_not_evaluated_warning_uses_loguru_formatting(self) -> None:
        """Incident logs render symbol, values, threshold, and reason."""
        bus = LiveContextBus()
        _push_closed_h1(bus, symbol="XAUUSD", close=4437.405)
        bus.update_tick({"symbol": "XAUUSD", "bid": 4428.155, "ask": 4428.355})
        output = StringIO()
        sink_id = logger.add(output, format="{message}")
        try:
            bus.check_price_drift("XAUUSD", 50.0)
        finally:
            logger.remove(sink_id)

        rendered = output.getvalue()
        assert "%s" not in rendered
        assert "XAUUSD" in rendered
        assert "observed_gap=91.5 pips" in rendered
        assert "max=50.0" in rendered
        assert "reason=MISSING_ALIGNED_WS_CLOSED_H1" in rendered
