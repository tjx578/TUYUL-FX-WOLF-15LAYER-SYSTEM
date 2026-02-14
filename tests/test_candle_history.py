"""
Test candle history functionality in LiveContextBus
"""

import pytest

from context.live_context_bus import LiveContextBus


@pytest.fixture
def context_bus():
    """Get LiveContextBus instance."""
    bus = LiveContextBus()
    # Clear any existing data
    bus._candle_history.clear()
    bus._candle_store.clear()
    return bus


def test_candle_history_empty(context_bus):
    """Test get_candle_history with no data."""
    history = context_bus.get_candle_history("EURUSD", "H1", count=20)
    assert isinstance(history, list)
    assert len(history) == 0


def test_candle_history_single_candle(context_bus):
    """Test get_candle_history with single candle."""
    candle = {
        "symbol": "EURUSD",
        "timeframe": "H1",
        "open": 1.1000,
        "high": 1.1010,
        "low": 1.0990,
        "close": 1.1005,
        "volume": 1000,
        "timestamp": "2024-01-01T00:00:00Z",
    }

    context_bus.update_candle(candle)

    history = context_bus.get_candle_history("EURUSD", "H1", count=20)
    assert len(history) == 1
    assert history[0] == candle


def test_candle_history_multiple_candles(context_bus):
    """Test get_candle_history with multiple candles."""
    candles = []
    for i in range(10):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000 + (i * 0.0001),
            "high": 1.1010 + (i * 0.0001),
            "low": 1.0990 + (i * 0.0001),
            "close": 1.1005 + (i * 0.0001),
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        candles.append(candle)
        context_bus.update_candle(candle)

    history = context_bus.get_candle_history("EURUSD", "H1", count=20)
    assert len(history) == 10
    assert history == candles


def test_candle_history_count_limit(context_bus):
    """Test get_candle_history respects count parameter."""
    # Add 30 candles across multiple days to keep valid timestamps
    for i in range(30):
        day = 1 + i // 24
        hour = i % 24
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000,
            "high": 1.1010,
            "low": 1.0990,
            "close": 1.1005,
            "volume": 1000,
            "timestamp": f"2024-01-{day:02d}T{hour:02d}:00:00Z",
        }
        context_bus.update_candle(candle)

    # Request only 5
    history = context_bus.get_candle_history("EURUSD", "H1", count=5)
    assert len(history) == 5

    # Request only 10
    history = context_bus.get_candle_history("EURUSD", "H1", count=10)
    assert len(history) == 10


def test_candle_history_max_buffer_size(context_bus):
    """Test candle history buffer respects maxlen=250."""
    # Add 300 candles across multiple days to keep valid timestamps
    for i in range(300):
        day = 1 + i // 24
        hour = i % 24
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000,
            "high": 1.1010,
            "low": 1.0990,
            "close": 1.1005,
            "volume": 1000,
            "timestamp": f"2024-01-{day:02d}T{hour:02d}:00:00Z",
        }
        context_bus.update_candle(candle)

    # Should only have last 250 (buffer limit from config)
    history = context_bus.get_candle_history("EURUSD", "H1", count=300)
    assert len(history) == 250


def test_candle_history_multiple_symbols(context_bus):
    """Test candle history for multiple symbols."""
    # Add candles for EURUSD
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

    # Add candles for GBPUSD
    for i in range(3):
        candle = {
            "symbol": "GBPUSD",
            "timeframe": "H1",
            "open": 1.2000,
            "high": 1.2010,
            "low": 1.1990,
            "close": 1.2005,
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)

    eurusd_history = context_bus.get_candle_history("EURUSD", "H1")
    gbpusd_history = context_bus.get_candle_history("GBPUSD", "H1")

    assert len(eurusd_history) == 5
    assert len(gbpusd_history) == 3


def test_candle_history_multiple_timeframes(context_bus):
    """Test candle history for multiple timeframes."""
    # Add H1 candles
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

    # Add M15 candles
    for i in range(3):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "M15",
            "open": 1.1000,
            "high": 1.1010,
            "low": 1.0990,
            "close": 1.1005,
            "volume": 1000,
            "timestamp": f"2024-01-01T00:{i * 15:02d}:00Z",
        }
        context_bus.update_candle(candle)

    h1_history = context_bus.get_candle_history("EURUSD", "H1")
    m15_history = context_bus.get_candle_history("EURUSD", "M15")

    assert len(h1_history) == 5
    assert len(m15_history) == 3
