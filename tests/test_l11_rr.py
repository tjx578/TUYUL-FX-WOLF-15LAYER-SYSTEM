"""
Test L11 Risk/Reward layer
"""

import pytest

from analysis.layers.L11_rr import L11RRAnalyzer
from context.live_context_bus import LiveContextBus


@pytest.fixture
def context_bus():
    """Get LiveContextBus instance."""
    bus = LiveContextBus()
    bus._candle_history.clear()
    return bus


@pytest.fixture
def analyzer():
    """Get L11RRAnalyzer instance."""
    return L11RRAnalyzer()


def test_rr_insufficient_data(analyzer, context_bus):
    """Test RR calculation with insufficient candle data."""
    # Add only 5 candles (need 14 minimum)
    for i in range(5):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000,
            "high": 1.1010,
            "low": 1.0990,
            "close": 1.1005,
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)

    result = analyzer.calculate_rr("EURUSD", "BUY")
    assert result["valid"] is False
    assert result["reason"] == "no_data"


def test_rr_buy_direction(analyzer, context_bus):
    """Test RR calculation for BUY direction."""
    # Add 20 candles with upward price movement
    for i in range(20):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000 + (i * 0.0005),
            "high": 1.1015 + (i * 0.0005),
            "low": 1.0990 + (i * 0.0005),
            "close": 1.1010 + (i * 0.0005),
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)

    result = analyzer.calculate_rr("EURUSD", "BUY")

    assert "entry" in result
    assert "sl" in result
    assert "tp1" in result
    assert "atr" in result
    assert "rr" in result
    assert result["direction"] == "BUY"

    # For BUY: SL should be below entry, TP should be above entry
    if result.get("valid"):
        assert result["sl"] < result["entry"]
        assert result["tp1"] > result["entry"]


def test_rr_sell_direction(analyzer, context_bus):
    """Test RR calculation for SELL direction."""
    # Add 20 candles with downward price movement
    for i in range(20):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000 - (i * 0.0005),
            "high": 1.1015 - (i * 0.0005),
            "low": 1.0990 - (i * 0.0005),
            "close": 1.1000 - (i * 0.0005),
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)

    result = analyzer.calculate_rr("EURUSD", "SELL")

    assert "entry" in result
    assert "sl" in result
    assert "tp1" in result
    assert result["direction"] == "SELL"

    # For SELL: SL should be above entry, TP should be below entry
    if result.get("valid"):
        assert result["sl"] > result["entry"]
        assert result["tp1"] < result["entry"]


def test_rr_custom_entry(analyzer, context_bus):
    """Test RR calculation with custom entry price."""
    # Add 20 candles
    for i in range(20):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000,
            "high": 1.1020,
            "low": 1.0990,
            "close": 1.1010,
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)

    custom_entry = 1.1050
    result = analyzer.calculate_rr("EURUSD", "BUY", entry=custom_entry)

    if result.get("valid"):
        assert result["entry"] == custom_entry


def test_rr_minimum_ratio_requirement(analyzer, context_bus):
    """Test RR meets minimum 1.5 ratio requirement."""
    # Add 20 candles with good volatility
    for i in range(20):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000,
            "high": 1.1050,
            "low": 1.0950,
            "close": 1.1020,
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)

    result = analyzer.calculate_rr("EURUSD", "BUY")

    # Should have valid RR with good volatility
    # RR should be >= 1.5 or marked as invalid
    if result.get("valid"):
        assert result["rr"] >= 1.5
        assert result["reason"] == "rr_ok"
    else:
        assert result["reason"] == "rr_too_low"


def test_rr_invalid_direction(analyzer, context_bus):
    """Test RR calculation with invalid direction."""
    # Add 20 candles
    for i in range(20):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000,
            "high": 1.1010,
            "low": 1.0990,
            "close": 1.1005,
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)

    result = analyzer.calculate_rr("EURUSD", "INVALID")
    assert result["valid"] is False
    assert result["reason"] == "invalid_direction"


def test_rr_output_format(analyzer, context_bus):
    """Test RR output format matches specification."""
    # Add 20 candles
    for i in range(20):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000 + (i * 0.0002),
            "high": 1.1020 + (i * 0.0002),
            "low": 1.0990 + (i * 0.0002),
            "close": 1.1010 + (i * 0.0002),
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)

    result = analyzer.calculate_rr("EURUSD", "BUY")

    # Verify all required fields are present
    assert "valid" in result
    assert "reason" in result

    if result["valid"]:
        assert "rr" in result
        assert "entry" in result
        assert "sl" in result
        assert "tp1" in result
        assert "direction" in result
        assert "atr" in result

        # Verify numeric fields are properly rounded
        assert isinstance(result["entry"], (int, float))
        assert isinstance(result["sl"], (int, float))
        assert isinstance(result["tp1"], (int, float))
        assert isinstance(result["atr"], (int, float))
        assert isinstance(result["rr"], (int, float))


def test_rr_legacy_calculate_method(analyzer):
    """Test legacy calculate method for backward compatibility."""
    result = analyzer.calculate(entry=1.1000, sl=1.0950, tp=1.1100)

    assert "valid" in result
    assert "rr" in result

    # RR = |1.1100 - 1.1000| / |1.1000 - 1.0950| = 0.0100 / 0.0050 = 2.0
    if result["valid"]:
        assert result["rr"] == 2.0


def test_rr_legacy_calculate_invalid_params(analyzer):
    """Test legacy calculate method with invalid params."""
    result = analyzer.calculate(entry=None, sl=None, tp=None)
    assert result["valid"] is False


def test_rr_atr_fallback(analyzer, context_bus):
    """Test RR calculation with ATR fallback to simple range."""
    # Add 20 candles with very low volatility to test fallback
    for i in range(20):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000,
            "high": 1.1002,
            "low": 1.0998,
            "close": 1.1000,
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)

    result = analyzer.calculate_rr("EURUSD", "BUY")

    # Should still calculate even with low volatility
    assert "atr" in result
