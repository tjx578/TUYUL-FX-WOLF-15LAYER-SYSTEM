"""
Unit tests for LiveContextBus.

Tests thread safety, singleton pattern, validation, candle history,
and snapshot functionality.
"""

import threading
from datetime import datetime, timezone


from context.live_context_bus import LiveContextBus


class TestLiveContextBusSingleton:
    """Test singleton pattern implementation."""

    def test_singleton_same_instance(self) -> None:
        """Test that multiple calls return the same instance."""
        bus1 = LiveContextBus()
        bus2 = LiveContextBus()
        assert bus1 is bus2

    def test_singleton_thread_safe(self) -> None:
        """Test singleton is thread-safe."""
        instances = []

        def get_instance():
            instances.append(LiveContextBus())

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # All instances should be the same object
        assert all(inst is instances[0] for inst in instances)


class TestLiveContextBusValidation:
    """Test tick/candle/news validation."""

    def test_valid_tick_accepted(self) -> None:
        """Test that valid ticks are accepted."""
        bus = LiveContextBus()

        tick = {
            "symbol": "EURUSD",
            "bid": 1.0850,
            "ask": 1.0852,
            "timestamp": 1700000000.0,
            "source": "test",
        }

        bus.update_tick(tick)

        # Retrieve and verify
        latest = bus.get_latest_tick("EURUSD")
        assert latest is not None
        assert latest["symbol"] == "EURUSD"
        assert latest["bid"] == 1.0850

    def test_invalid_tick_rejected(self) -> None:
        """Test that invalid ticks are rejected."""
        bus = LiveContextBus()

        # Missing required fields
        invalid_tick = {
            "symbol": "EURUSD",
            "bid": 1.0850,
            # Missing ask, timestamp
        }

        # Should not raise, but should log warning
        bus.update_tick(invalid_tick)

        # Should not be stored
        latest = bus.get_latest_tick("EURUSD")
        assert latest is None or latest != invalid_tick

    def test_valid_candle_accepted(self) -> None:
        """Test that valid candles are accepted."""
        bus = LiveContextBus()

        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.0850,
            "high": 1.0860,
            "low": 1.0840,
            "close": 1.0855,
            "timestamp": datetime.now(timezone.utc),
        }

        bus.update_candle(candle)

        # Retrieve and verify
        retrieved = bus.get_candle("EURUSD", "H1")
        assert retrieved is not None
        assert retrieved["symbol"] == "EURUSD"
        assert retrieved["close"] == 1.0855

    def test_invalid_candle_rejected(self) -> None:
        """Test that invalid candles are rejected."""
        bus = LiveContextBus()

        # Missing required fields
        invalid_candle = {
            "symbol": "GBPUSD",
            "open": 1.0850,
            # Missing high, low, close, timeframe, timestamp
        }

        # Should not raise, but should log warning
        bus.update_candle(invalid_candle)

        # Should not be stored
        retrieved = bus.get_candle("GBPUSD", "H1")
        assert retrieved is None

    def test_valid_news_accepted(self) -> None:
        """Test that valid news is accepted."""
        bus = LiveContextBus()

        news = {
            "events": [
                {
                    "event": "NFP",
                    "country": "US",
                    "impact": "high",
                    "datetime": "2024-01-15T13:30:00Z",
                }
            ],
            "source": "test",
        }

        bus.update_news(news)

        # Retrieve and verify
        retrieved = bus.get_news()
        assert retrieved is not None
        assert retrieved["source"] == "test"


class TestLiveContextBusCandleHistory:
    """Test candle history buffer functionality."""

    def test_candle_history_stored(self) -> None:
        """Test that candles are stored in history buffer."""
        bus = LiveContextBus()

        # Add 5 candles
        for i in range(5):
            candle = {
                "symbol": "EURUSD",
                "timeframe": "H1",
                "open": 1.0850 + i * 0.0001,
                "high": 1.0860 + i * 0.0001,
                "low": 1.0840 + i * 0.0001,
                "close": 1.0855 + i * 0.0001,
                "timestamp": datetime.now(timezone.utc),
            }
            bus.update_candle(candle)

        # Get history
        history = bus.get_candle_history("EURUSD", "H1", count=5)
        assert len(history) == 5

        # Verify order (oldest to newest)
        assert abs(history[0]["close"] - 1.0855) < 0.0001
        assert abs(history[-1]["close"] - 1.0859) < 0.0001

    def test_candle_history_limited_to_50(self) -> None:
        """Test that history buffer is limited to 50 candles."""
        bus = LiveContextBus()

        # Add 60 candles
        for i in range(60):
            candle = {
                "symbol": "EURUSD",
                "timeframe": "H1",
                "open": 1.0850,
                "high": 1.0860,
                "low": 1.0840,
                "close": 1.0855,
                "timestamp": datetime.now(timezone.utc),
            }
            bus.update_candle(candle)

        # Get history - should only have 50
        history = bus.get_candle_history("EURUSD", "H1", count=100)
        assert len(history) <= 50

    def test_candle_history_per_timeframe(self) -> None:
        """Test that history is separate per timeframe."""
        bus = LiveContextBus()

        # Use a unique symbol to avoid interference from other tests
        symbol = "NZDUSD"

        # Add M15 candles
        for i in range(3):
            candle = {
                "symbol": symbol,
                "timeframe": "M15",
                "open": 1.0850,
                "high": 1.0860,
                "low": 1.0840,
                "close": 1.0855,
                "timestamp": datetime.now(timezone.utc),
            }
            bus.update_candle(candle)

        # Add H1 candles
        for i in range(5):
            candle = {
                "symbol": symbol,
                "timeframe": "H1",
                "open": 1.0850,
                "high": 1.0860,
                "low": 1.0840,
                "close": 1.0855,
                "timestamp": datetime.now(timezone.utc),
            }
            bus.update_candle(candle)

        # Get histories
        m15_history = bus.get_candle_history(symbol, "M15", count=10)
        h1_history = bus.get_candle_history(symbol, "H1", count=10)

        assert len(m15_history) == 3
        assert len(h1_history) == 5

    def test_candle_history_empty_when_none(self) -> None:
        """Test that history returns empty list when no candles."""
        bus = LiveContextBus()

        history = bus.get_candle_history("UNKNOWN", "H1", count=10)
        assert history == []


class TestLiveContextBusThreadSafety:
    """Test thread safety of concurrent operations."""

    def test_concurrent_tick_writes(self) -> None:
        """Test concurrent tick writes are thread-safe."""
        bus = LiveContextBus()

        def write_ticks(thread_id: int):
            for i in range(100):
                tick = {
                    "symbol": f"PAIR{thread_id}",
                    "bid": 1.0850 + i * 0.0001,
                    "ask": 1.0852 + i * 0.0001,
                    "timestamp": 1700000000.0 + i,
                    "source": "test",
                }
                bus.update_tick(tick)

        threads = [
            threading.Thread(target=write_ticks, args=(i,))
            for i in range(10)
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Verify all ticks were written (at least some from each thread)
        snapshot = bus.snapshot()
        ticks = snapshot.get("ticks", [])
        assert len(ticks) > 0

    def test_concurrent_candle_writes(self) -> None:
        """Test concurrent candle writes are thread-safe."""
        bus = LiveContextBus()

        def write_candles(thread_id: int):
            for i in range(50):
                candle = {
                    "symbol": f"PAIR{thread_id}",
                    "timeframe": "H1",
                    "open": 1.0850,
                    "high": 1.0860,
                    "low": 1.0840,
                    "close": 1.0855,
                    "timestamp": datetime.now(timezone.utc),
                }
                bus.update_candle(candle)

        threads = [
            threading.Thread(target=write_candles, args=(i,))
            for i in range(5)
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Verify candles were written
        snapshot = bus.snapshot()
        candles = snapshot.get("candles", {})
        assert len(candles) > 0


class TestLiveContextBusSnapshot:
    """Test snapshot functionality."""

    def test_snapshot_returns_correct_structure(self) -> None:
        """Test that snapshot returns correct data structure."""
        bus = LiveContextBus()

        # Add some data
        tick = {
            "symbol": "EURUSD",
            "bid": 1.0850,
            "ask": 1.0852,
            "timestamp": 1700000000.0,
            "source": "test",
        }
        bus.update_tick(tick)

        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.0850,
            "high": 1.0860,
            "low": 1.0840,
            "close": 1.0855,
            "timestamp": datetime.now(timezone.utc),
        }
        bus.update_candle(candle)

        # Get snapshot
        snapshot = bus.snapshot()

        # Verify structure
        assert "ticks" in snapshot
        assert "candles" in snapshot
        assert "news" in snapshot
        assert "meta" in snapshot

        # Verify data
        assert len(snapshot["ticks"]) > 0
        assert len(snapshot["candles"]) > 0

    def test_snapshot_is_read_only_copy(self) -> None:
        """Test that snapshot doesn't affect internal state."""
        bus = LiveContextBus()

        tick = {
            "symbol": "EURUSD",
            "bid": 1.0850,
            "ask": 1.0852,
            "timestamp": 1700000000.0,
            "source": "test",
        }
        bus.update_tick(tick)

        # Get snapshot and modify it
        snapshot = bus.snapshot()
        snapshot["ticks"].clear()

        # Verify internal state unchanged
        snapshot2 = bus.snapshot()
        assert len(snapshot2["ticks"]) > 0
