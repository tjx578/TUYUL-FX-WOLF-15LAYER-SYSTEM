"""
Unit tests for Redis Context Bridge and integration with LiveContextBus.
"""

import os
from unittest.mock import MagicMock, patch

import orjson
import pytest

from context.live_context_bus import LiveContextBus
from context.redis_context_bridge import RedisContextBridge


class TestRedisContextBridge:
    """Test Redis context bridge operations."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        mock = MagicMock()
        mock.xadd.return_value = "1234567890-0"
        mock.hset.return_value = 1
        mock.publish.return_value = 1
        mock.hget.return_value = None
        mock.get.return_value = None
        return mock

    @pytest.fixture
    def bridge(self, mock_redis):
        """Create RedisContextBridge with mock Redis."""
        with patch("context.redis_context_bridge.RedisClient") as mock_cls:
            mock_cls.return_value = mock_redis
            bridge = RedisContextBridge(redis_client=mock_redis)
            return bridge

    def test_write_tick_success(self, bridge, mock_redis):
        """Test successful tick write to Redis."""
        tick = {
            "symbol": "EURUSD",
            "bid": 1.0842,
            "ask": 1.0843,
            "timestamp": 1700000000.0,
            "source": "finnhub_ws",
        }

        bridge.write_tick(tick)

        # Verify XADD was called
        assert mock_redis.xadd.called
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "wolf15:tick:EURUSD"

        # Verify HSET was called
        assert mock_redis.hset.called
        hset_call = mock_redis.hset.call_args
        assert hset_call[0][0] == "wolf15:latest_tick:EURUSD"

        # Verify PUBLISH was called
        assert mock_redis.publish.called
        publish_call = mock_redis.publish.call_args
        assert publish_call[0][0] == "tick_updates"

    def test_write_tick_missing_symbol(self, bridge, mock_redis):
        """Test tick write with missing symbol."""
        tick = {
            "bid": 1.0842,
            "ask": 1.0843,
            "timestamp": 1700000000.0,
        }

        bridge.write_tick(tick)

        # Should not call Redis operations
        assert not mock_redis.xadd.called
        assert not mock_redis.hset.called
        assert not mock_redis.publish.called

    def test_write_candle_success(self, bridge, mock_redis):
        """Test successful candle write to Redis."""
        candle = {
            "symbol": "EURUSD",
            "timeframe": "M15",
            "open": 1.0840,
            "high": 1.0850,
            "low": 1.0835,
            "close": 1.0845,
            "timestamp": 1700000000.0,
        }

        bridge.write_candle(candle)

        # Verify PUBLISH was called
        assert mock_redis.publish.called
        publish_call = mock_redis.publish.call_args
        assert publish_call[0][0] == "candle:EURUSD:M15"

        # Verify HSET was called
        assert mock_redis.hset.called
        hset_call = mock_redis.hset.call_args
        assert hset_call[0][0] == "wolf15:candle:EURUSD:M15"

    def test_write_candle_missing_fields(self, bridge, mock_redis):
        """Test candle write with missing required fields."""
        candle = {
            "open": 1.0840,
            "high": 1.0850,
        }

        bridge.write_candle(candle)

        # Should not call Redis operations
        assert not mock_redis.publish.called
        assert not mock_redis.hset.called

    def test_write_news_success(self, bridge, mock_redis):
        """Test successful news write to Redis."""
        news = {
            "headline": "Fed raises rates",
            "impact": "HIGH",
            "timestamp": 1700000000.0,
        }

        bridge.write_news(news)

        # Verify PUBLISH was called
        assert mock_redis.publish.called
        publish_call = mock_redis.publish.call_args
        assert publish_call[0][0] == "news_updates"

        # Verify SET was called
        assert mock_redis.set.called
        set_call = mock_redis.set.call_args
        assert set_call[0][0] == "wolf15:latest_news"

    def test_read_latest_tick_success(self, bridge, mock_redis):
        """Test reading latest tick from Redis."""
        tick = {
            "symbol": "EURUSD",
            "bid": 1.0842,
            "ask": 1.0843,
            "timestamp": 1700000000.0,
        }
        tick_json = orjson.dumps(tick).decode("utf-8")
        mock_redis.hget.return_value = tick_json

        result = bridge.read_latest_tick("EURUSD")

        assert result == tick
        assert mock_redis.hget.called
        call_args = mock_redis.hget.call_args
        assert call_args[0][0] == "wolf15:latest_tick:EURUSD"

    def test_read_latest_tick_not_found(self, bridge, mock_redis):
        """Test reading latest tick when not found."""
        mock_redis.hget.return_value = None

        result = bridge.read_latest_tick("EURUSD")

        assert result is None

    def test_read_latest_candle_success(self, bridge, mock_redis):
        """Test reading latest candle from Redis."""
        candle = {
            "symbol": "EURUSD",
            "timeframe": "M15",
            "open": 1.0840,
            "close": 1.0845,
        }
        candle_json = orjson.dumps(candle).decode("utf-8")
        mock_redis.hget.return_value = candle_json

        result = bridge.read_latest_candle("EURUSD", "M15")

        assert result == candle
        assert mock_redis.hget.called

    def test_read_latest_news_success(self, bridge, mock_redis):
        """Test reading latest news from Redis."""
        news = {"headline": "Fed raises rates", "impact": "HIGH"}
        news_json = orjson.dumps(news).decode("utf-8")
        mock_redis.get.return_value = news_json

        result = bridge.read_latest_news()

        assert result == news
        assert mock_redis.get.called


class TestLiveContextBusRedisIntegration:
    """Test LiveContextBus state behavior via current public API."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset LiveContextBus singleton between tests."""
        LiveContextBus.reset_singleton()
        yield
        LiveContextBus.reset_singleton()

    def test_local_mode_by_default(self):
        """Bus starts with empty snapshot state."""
        with patch.dict(os.environ, {}, clear=True):
            bus = LiveContextBus()
            snap = bus.snapshot()
            assert snap["ticks"] == {}
            assert snap["candles"] == {}

    def test_update_tick_stores_latest_tick(self):
        """update_tick should store and expose latest tick by symbol."""
        bus = LiveContextBus()
        tick = {
            "symbol": "EURUSD",
            "bid": 1.0842,
            "ask": 1.0843,
            "timestamp": 1700000000.0,
            "source": "test",
        }

        bus.update_tick(tick)

        latest = bus.get_latest_tick("EURUSD")
        assert latest == tick

    def test_update_candle_appends_history(self):
        """update_candle should append into symbol/timeframe history."""
        bus = LiveContextBus()
        candle = {
            "symbol": "EURUSD",
            "timeframe": "M15",
            "open": 1.0840,
            "high": 1.0850,
            "low": 1.0835,
            "close": 1.0845,
            "timestamp": 1700000000.0,
        }

        bus.update_candle(candle)

        candles = bus.get_candles("EURUSD", "M15")
        assert len(candles) == 1
        assert candles[0] == candle

    def test_update_news_in_memory(self):
        """update_news should persist the latest news payload in bus state."""
        bus = LiveContextBus()
        news = {
            "events": [
                {
                    "headline": "Fed raises rates",
                    "impact": "HIGH",
                    "timestamp": 1700000000.0,
                }
            ],
        }

        bus.update_news(news)

        assert bus.get_news() == news

    def test_snapshot_contains_updates(self):
        """snapshot should expose current ticks and candles."""
        bus = LiveContextBus()
        bus.update_tick({"symbol": "EURUSD", "bid": 1.0842, "ask": 1.0843})
        bus.update_candle(
            {
                "symbol": "EURUSD",
                "timeframe": "M15",
                "open": 1.0840,
                "high": 1.0850,
                "low": 1.0835,
                "close": 1.0845,
                "timestamp": 1700000000.0,
            }
        )

        snap = bus.snapshot()
        assert "EURUSD" in snap["ticks"]
        assert "EURUSD:M15" in snap["candles"]

    def test_reset_state_clears_data(self):
        """reset_state should clear stored ticks/candles/news."""
        bus = LiveContextBus()
        bus.update_tick({"symbol": "EURUSD", "bid": 1.0842, "ask": 1.0843})
        bus.update_candle(
            {
                "symbol": "EURUSD",
                "timeframe": "M15",
                "open": 1.0840,
                "high": 1.0850,
                "low": 1.0835,
                "close": 1.0845,
                "timestamp": 1700000000.0,
            }
        )
        bus.update_news({"events": [{"headline": "Test"}]})

        bus.reset_state()

        assert bus.get_latest_tick("EURUSD") is None
        assert bus.get_candles("EURUSD", "M15") == []
        assert bus.get_news() is None
