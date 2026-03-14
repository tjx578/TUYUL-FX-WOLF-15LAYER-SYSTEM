"""Tests for ingest.fallback_provider graceful degradation."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from ingest.fallback_provider import _CANDLE_CACHE_KEY_PREFIX, FallbackCandleProvider

# ══════════════════════════════════════════════════════════════════════
#  No providers configured
# ══════════════════════════════════════════════════════════════════════

class TestNoProvidersConfigured:
    """When no provider API keys are set, fetch() must not raise."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_without_redis(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
        monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

        provider = FallbackCandleProvider()
        result = await provider.fetch("EURUSD", "H1")
        assert result == []

    @pytest.mark.asyncio
    async def test_attempts_cache_read_when_redis_provided(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
        monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

        cached_candles = [{"symbol": "EURUSD", "close": 1.1, "source": "twelve_data"}]
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_candles))

        provider = FallbackCandleProvider(redis_client=mock_redis)
        result = await provider.fetch("EURUSD", "H1")
        assert result == cached_candles

    @pytest.mark.asyncio
    async def test_returns_empty_when_redis_cache_miss(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
        monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        provider = FallbackCandleProvider(redis_client=mock_redis)
        result = await provider.fetch("EURUSD", "H1")
        assert result == []


# ══════════════════════════════════════════════════════════════════════
#  All providers fail — fallback to Redis cache
# ══════════════════════════════════════════════════════════════════════

class TestAllProvidersFail:
    """When all providers raise, fetch() must return cache or empty list."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_all_fail_no_redis(self) -> None:
        provider = FallbackCandleProvider()

        # inject a failing provider
        failing = MagicMock()
        failing.name = "fake_provider"
        failing.fetch = AsyncMock(side_effect=RuntimeError("503 provider down"))
        provider._providers = [failing]  # pyright: ignore[reportPrivateUsage]

        result = await provider.fetch("EURUSD", "H1")
        assert result == []

    @pytest.mark.asyncio
    async def test_falls_back_to_redis_when_all_providers_fail(self) -> None:
        cached_candles = [{"symbol": "EURUSD", "close": 1.09, "source": "twelve_data"}]
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_candles))

        provider = FallbackCandleProvider(redis_client=mock_redis)

        failing = MagicMock()
        failing.name = "fake_provider"
        failing.fetch = AsyncMock(side_effect=RuntimeError("403 Forbidden"))
        provider._providers = [failing]  # pyright: ignore[reportPrivateUsage]

        result = await provider.fetch("EURUSD", "H1")
        assert result == cached_candles

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_all_fail_and_cache_miss(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        provider = FallbackCandleProvider(redis_client=mock_redis)

        failing = MagicMock()
        failing.name = "fake_provider"
        failing.fetch = AsyncMock(side_effect=RuntimeError("503 provider down"))
        provider._providers = [failing]  # pyright: ignore[reportPrivateUsage]

        result = await provider.fetch("EURUSD", "H1")
        assert result == []

    @pytest.mark.asyncio
    async def test_does_not_raise_on_redis_error(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("redis timeout"))

        provider = FallbackCandleProvider(redis_client=mock_redis)

        failing = MagicMock()
        failing.name = "fake_provider"
        failing.fetch = AsyncMock(side_effect=RuntimeError("403"))
        provider._providers = [failing]  # pyright: ignore[reportPrivateUsage]

        result = await provider.fetch("EURUSD", "H1")
        assert result == []


# ══════════════════════════════════════════════════════════════════════
#  Write-through cache on success
# ══════════════════════════════════════════════════════════════════════

class TestWriteThroughCache:
    """Successful fetches should be written to Redis cache."""

    @pytest.mark.asyncio
    async def test_writes_to_cache_on_success(self) -> None:
        fresh_candles = [{"symbol": "EURUSD", "close": 1.1, "source": "twelve_data"}]

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        provider = FallbackCandleProvider(redis_client=mock_redis)

        succeed = MagicMock()
        succeed.name = "twelve_data"
        succeed.fetch = AsyncMock(return_value=fresh_candles)
        provider._providers = [succeed]  # pyright: ignore[reportPrivateUsage]

        result = await provider.fetch("EURUSD", "H1")
        assert result == fresh_candles

        # Verify Redis write was called with the correct key
        expected_key = f"{_CANDLE_CACHE_KEY_PREFIX}:EURUSD:H1"
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == expected_key

    @pytest.mark.asyncio
    async def test_cache_write_failure_does_not_affect_return(self) -> None:
        """A Redis write failure must not cause fetch() to raise or return empty."""
        fresh_candles = [{"symbol": "GBPUSD", "close": 1.25}]

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=ConnectionError("redis write failed"))

        provider = FallbackCandleProvider(redis_client=mock_redis)

        succeed = MagicMock()
        succeed.name = "twelve_data"
        succeed.fetch = AsyncMock(return_value=fresh_candles)
        provider._providers = [succeed]  # pyright: ignore[reportPrivateUsage]

        result = await provider.fetch("GBPUSD", "H1")
        assert result == fresh_candles

    @pytest.mark.asyncio
    async def test_no_cache_write_when_no_redis_client(self) -> None:
        """Without a Redis client, fetch() should still return candles normally."""
        fresh_candles = [{"symbol": "USDJPY", "close": 150.0}]

        provider = FallbackCandleProvider()  # no redis_client

        succeed = MagicMock()
        succeed.name = "twelve_data"
        succeed.fetch = AsyncMock(return_value=fresh_candles)
        provider._providers = [succeed]  # pyright: ignore[reportPrivateUsage]

        result = await provider.fetch("USDJPY", "H1")
        assert result == fresh_candles


# ══════════════════════════════════════════════════════════════════════
#  Cache key format
# ══════════════════════════════════════════════════════════════════════

class TestCacheKeyFormat:
    def test_cache_key_matches_expected_pattern(self) -> None:
        key = FallbackCandleProvider._cache_key("EURUSD", "H1")  # pyright: ignore[reportPrivateUsage]
        assert key == "WOLF15:CANDLE_CACHE:EURUSD:H1"

    def test_cache_key_different_symbol(self) -> None:
        key = FallbackCandleProvider._cache_key("GBPUSD", "D1")  # pyright: ignore[reportPrivateUsage]
        assert key == "WOLF15:CANDLE_CACHE:GBPUSD:D1"
