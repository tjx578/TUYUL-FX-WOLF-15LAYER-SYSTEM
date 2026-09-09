"""Tests for Redis TTL enforcement in RedisContextBridge."""

from unittest.mock import MagicMock, patch

import pytest

from context.redis_context_bridge import (
    CANDLE_HASH_TTL_SECONDS,
    LATEST_TICK_TTL_SECONDS,
    RedisContextBridge,
)


@pytest.fixture
def mock_redis():
    """Create mock RedisClient with underlying client."""
    mock = MagicMock()
    mock.client = MagicMock()  # The underlying redis.Redis instance
    return mock


@pytest.fixture
def bridge(mock_redis):
    """Create bridge with mocked Redis."""
    return RedisContextBridge(redis_client=mock_redis)


class TestTickTTL:
    """Verify latest_tick keys get TTL on write."""

    def test_write_tick_sets_ttl_on_latest_tick(self, bridge, mock_redis):
        """HSET on latest_tick must be followed by EXPIRE."""
        tick = {
            "symbol": "EURUSD",
            "bid": 1.0842,
            "ask": 1.0843,
            "timestamp": 1700000000.0,
            "source": "finnhub_ws",
        }

        bridge.write_tick(tick)

        # Verify XADD was called (stream — uses maxlen, not TTL)
        mock_redis.xadd.assert_called_once()

        # Verify HSET was called for latest_tick
        mock_redis.hset.assert_called_once()
        hset_key = mock_redis.hset.call_args[0][0]
        assert hset_key == "wolf15:latest_tick:EURUSD"

        # ✅ KEY CHECK: EXPIRE must be called with 60s
        mock_redis.client.expire.assert_called_once_with(
            "wolf15:latest_tick:EURUSD",
            LATEST_TICK_TTL_SECONDS,
        )

    def test_write_tick_missing_symbol_skips_all(self, bridge, mock_redis):
        """No Redis ops if symbol is missing."""
        bridge.write_tick({"bid": 1.0})
        mock_redis.xadd.assert_not_called()
        mock_redis.hset.assert_not_called()
        mock_redis.client.expire.assert_not_called()


class TestCandleTTL:
    """Verify candle hash keys get TTL on write."""

    def test_write_candle_sets_ttl(self, bridge, mock_redis):
        """HSET on candle must be followed by EXPIRE."""
        candle = {
            "symbol": "CADJPY",
            "timeframe": "M15",
            "open": 110.5,
            "high": 110.8,
            "low": 110.3,
            "close": 110.6,
            "timestamp": 1700000000.0,
        }

        bridge.write_candle(candle)

        # Verify HSET was called
        mock_redis.hset.assert_called_once()
        hset_key = mock_redis.hset.call_args[0][0]
        assert hset_key == "wolf15:candle:CADJPY:M15"

        # ✅ KEY CHECK: EXPIRE must be called with 4h
        mock_redis.client.expire.assert_called_once_with(
            "wolf15:candle:CADJPY:M15",
            CANDLE_HASH_TTL_SECONDS,
        )

    def test_write_candle_missing_fields_skips_all(self, bridge, mock_redis):
        """No Redis ops if symbol or timeframe is missing."""
        bridge.write_candle({"symbol": "CADJPY"})  # missing timeframe
        mock_redis.hset.assert_not_called()
        mock_redis.client.expire.assert_not_called()


class TestNewsTTLAlreadySet:
    """Verify news already has TTL (regression guard)."""

    def test_write_news_uses_set_with_ex(self, bridge, mock_redis):
        """SET with ex=86400 is the existing correct pattern."""
        bridge.write_news({"headline": "NFP report", "impact": "high"})

        mock_redis.set.assert_called_once()
        call_kwargs = mock_redis.set.call_args
        # ex=86400 should be passed
        assert call_kwargs[1].get("ex") == 86400 or call_kwargs[0][2] == 86400
