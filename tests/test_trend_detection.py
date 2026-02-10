"""
Test trend detection in MarketStructureAnalyzer
"""

import pytest

from analysis.market.structure import MarketStructureAnalyzer
from context.live_context_bus import LiveContextBus


@pytest.fixture
def context_bus():
    """Get LiveContextBus instance."""
    bus = LiveContextBus()
    bus._candle_history.clear()
    bus._candle_store.clear()
    return bus


@pytest.fixture
def analyzer():
    """Get MarketStructureAnalyzer instance."""
    return MarketStructureAnalyzer()


def test_trend_detection_insufficient_data(analyzer, context_bus):
    """Test trend detection with insufficient candle data."""
    # Add only 3 candles (need 5 minimum)
    for i in range(3):
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
    
    trend = analyzer._detect_trend("EURUSD")
    assert trend == "NEUTRAL"


def test_trend_detection_bullish_hh_hl(analyzer, context_bus):
    """Test bullish trend detection (Higher Highs + Higher Lows)."""
    # Create candles with clear uptrend: HH + HL pattern with obvious swing points
    # Use zig-zag pattern: up, pullback, up more, pullback, up even more
    candles_data = [
        (1.1000, 1.1010, 1.0990, 1.1005),  # 0
        (1.1005, 1.1020, 1.0995, 1.1015),  # 1
        (1.1015, 1.1030, 1.1010, 1.1025),  # 2 - first peak
        (1.1025, 1.1028, 1.1005, 1.1010),  # 3 - pullback
        (1.1010, 1.1015, 1.0995, 1.1000),  # 4 - pullback continues (valley)
        (1.1000, 1.1020, 1.0998, 1.1015),  # 5 - bounce back
        (1.1015, 1.1035, 1.1012, 1.1030),  # 6 - higher peak
        (1.1030, 1.1048, 1.1025, 1.1045),  # 7 - even higher
        (1.1045, 1.1050, 1.1025, 1.1030),  # 8 - pullback
        (1.1030, 1.1035, 1.1015, 1.1020),  # 9 - pullback continues (higher valley)
        (1.1020, 1.1040, 1.1018, 1.1035),  # 10 - bounce
        (1.1035, 1.1060, 1.1032, 1.1055),  # 11 - highest peak
    ]
    
    for i, (o, h, l, c) in enumerate(candles_data):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)
    
    trend = analyzer._detect_trend("EURUSD")
    assert trend == "BULLISH"


def test_trend_detection_bearish_lh_ll(analyzer, context_bus):
    """Test bearish trend detection (Lower Highs + Lower Lows)."""
    # Create candles with clear downtrend: LH + LL pattern with obvious swing points
    # Use zig-zag pattern: down, bounce, down more, bounce, down even more
    candles_data = [
        (1.1000, 1.1010, 1.0990, 1.0995),  # 0
        (1.0995, 1.1000, 1.0980, 1.0985),  # 1
        (1.0985, 1.0990, 1.0970, 1.0975),  # 2 - first valley
        (1.0975, 1.0995, 1.0972, 1.0990),  # 3 - bounce
        (1.0990, 1.1005, 1.0988, 1.1000),  # 4 - bounce continues (peak)
        (1.1000, 1.1002, 1.0980, 1.0985),  # 5 - down again
        (1.0985, 1.0990, 1.0960, 1.0965),  # 6 - lower valley
        (1.0965, 1.0970, 1.0950, 1.0955),  # 7 - even lower
        (1.0955, 1.0975, 1.0952, 1.0970),  # 8 - bounce
        (1.0970, 1.0985, 1.0968, 1.0980),  # 9 - bounce continues (lower peak)
        (1.0980, 1.0982, 1.0960, 1.0965),  # 10 - down
        (1.0965, 1.0970, 1.0940, 1.0945),  # 11 - lowest valley
    ]
    
    for i, (o, h, l, c) in enumerate(candles_data):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)
    
    trend = analyzer._detect_trend("EURUSD")
    assert trend == "BEARISH"


def test_trend_detection_neutral_mixed(analyzer, context_bus):
    """Test neutral trend detection with mixed swing points."""
    # Create candles with sideways/choppy price action
    candles_data = [
        (1.1000, 1.1010, 1.0990, 1.1000),  # 0
        (1.1000, 1.1015, 1.0995, 1.1005),  # 1
        (1.1005, 1.1012, 1.0998, 1.1000),  # 2
        (1.1000, 1.1018, 1.0992, 1.1008),  # 3
        (1.1008, 1.1014, 1.0996, 1.1002),  # 4
        (1.1002, 1.1020, 1.0990, 1.1010),  # 5
        (1.1010, 1.1016, 1.0994, 1.1004),  # 6
        (1.1004, 1.1012, 1.0998, 1.1006),  # 7
    ]
    
    for i, (o, h, l, c) in enumerate(candles_data):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)
    
    trend = analyzer._detect_trend("EURUSD")
    assert trend == "NEUTRAL"


def test_swing_highs_detection(analyzer):
    """Test swing high detection logic."""
    highs = [1.10, 1.12, 1.11, 1.15, 1.13, 1.14, 1.16, 1.15, 1.14]
    swing_highs = analyzer._find_swing_highs(highs, window=2)
    
    # With window=2, a swing high needs to be higher than 2 candles before/after
    # 1.12 at index 1 is a swing high (higher than 1.10 and 1.11)
    # 1.15 at index 3 is a swing high (higher than surrounding candles)
    # 1.16 at index 6 is a swing high (higher than surrounding candles)
    assert len(swing_highs) > 0


def test_swing_lows_detection(analyzer):
    """Test swing low detection logic."""
    lows = [1.10, 1.08, 1.09, 1.07, 1.09, 1.08, 1.06, 1.08, 1.09]
    swing_lows = analyzer._find_swing_lows(lows, window=2)
    
    # With window=2, a swing low needs to be lower than 2 candles before/after
    assert len(swing_lows) > 0


def test_analyze_with_valid_structure(analyzer, context_bus):
    """Test analyze method returns valid structure."""
    # Add enough candles for valid analysis
    for i in range(10):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000 + (i * 0.0005),
            "high": 1.1010 + (i * 0.0005),
            "low": 1.0990 + (i * 0.0005),
            "close": 1.1005 + (i * 0.0005),
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)
    
    # Also add current H1 candle
    current_candle = {
        "symbol": "EURUSD",
        "timeframe": "H1",
        "open": 1.1050,
        "high": 1.1060,
        "low": 1.1040,
        "close": 1.1055,
        "volume": 1000,
        "timestamp": "2024-01-01T10:00:00Z",
    }
    context_bus.update_candle(current_candle)
    
    result = analyzer.analyze("EURUSD")
    assert result["valid"] is True
    assert "trend" in result
    assert result["trend"] in ["BULLISH", "BEARISH", "NEUTRAL"]


def test_analyze_no_candle(analyzer, context_bus):
    """Test analyze method with no current candle."""
    result = analyzer.analyze("EURUSD")
    assert result["valid"] is False
    assert result["reason"] == "no_h1_candle"
