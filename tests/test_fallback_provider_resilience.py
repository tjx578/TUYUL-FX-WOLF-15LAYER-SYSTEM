"""Tests for ingest.fallback_provider graceful degradation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from ingest.fallback_provider import _CANDLE_CACHE_KEY_PREFIX, FallbackCandleProvider


def _cached_candle(
    *,
    symbol: str = "EURUSD",
    timeframe: str = "H1",
    close: float = 1.1,
    timestamp: str = "2026-03-14T10:00:00+00:00",
    source: str = "twelve_data",
) -> dict[str, float | str]:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "open": close - 0.001,
        "high": close + 0.001,
        "low": close - 0.002,
        "close": close,
        "volume": 1000.0,
        "timestamp": timestamp,
        "source": source,
    }


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
    async def test_attempts_cache_read_when_redis_provided(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
        monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

        cached_candles = [_cached_candle()]
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_candles))

        provider = FallbackCandleProvider(redis_client=mock_redis)
        result = await provider.fetch("EURUSD", "H1")
        assert len(result) == 1
        assert result[0]["symbol"] == "EURUSD"
        assert result[0]["timeframe"] == "H1"
        assert result[0]["source"] == "twelve_data"
        assert isinstance(result[0]["timestamp"], datetime)

    @pytest.mark.asyncio
    async def test_returns_empty_when_redis_cache_miss(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
        provider._providers = [failing]

        result = await provider.fetch("EURUSD", "H1")
        assert result == []

    @pytest.mark.asyncio
    async def test_falls_back_to_redis_when_all_providers_fail(self) -> None:
        cached_candles = [_cached_candle(close=1.09)]
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_candles))

        provider = FallbackCandleProvider(redis_client=mock_redis)

        failing = MagicMock()
        failing.name = "fake_provider"
        failing.fetch = AsyncMock(side_effect=RuntimeError("403 Forbidden"))
        provider._providers = [failing]

        result = await provider.fetch("EURUSD", "H1")
        assert len(result) == 1
        assert result[0]["symbol"] == "EURUSD"
        assert result[0]["timeframe"] == "H1"
        assert result[0]["source"] == "twelve_data"
        assert isinstance(result[0]["timestamp"], datetime)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_all_fail_and_cache_miss(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        provider = FallbackCandleProvider(redis_client=mock_redis)

        failing = MagicMock()
        failing.name = "fake_provider"
        failing.fetch = AsyncMock(side_effect=RuntimeError("503 provider down"))
        provider._providers = [failing]

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
        provider._providers = [failing]

        result = await provider.fetch("EURUSD", "H1")
        assert result == []


# ══════════════════════════════════════════════════════════════════════
#  Write-through cache on success
# ══════════════════════════════════════════════════════════════════════


class TestWriteThroughCache:
    """Successful fetches should be written to Redis cache."""

    @pytest.mark.asyncio
    async def test_writes_to_cache_on_success(self) -> None:
        fresh_candles = [
            {
                "symbol": "EURUSD",
                "timeframe": "H1",
                "open": 1.099,
                "high": 1.101,
                "low": 1.098,
                "close": 1.1,
                "volume": 1000.0,
                "timestamp": datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC),
                "source": "twelve_data",
            }
        ]

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        provider = FallbackCandleProvider(redis_client=mock_redis)

        succeed = MagicMock()
        succeed.name = "twelve_data"
        succeed.fetch = AsyncMock(return_value=fresh_candles)
        provider._providers = [succeed]

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
        provider._providers = [succeed]

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
        provider._providers = [succeed]

        result = await provider.fetch("USDJPY", "H1")
        assert result == fresh_candles


# ══════════════════════════════════════════════════════════════════════
#  Cache key format
# ══════════════════════════════════════════════════════════════════════


class TestCacheKeyFormat:
    def test_cache_key_matches_expected_pattern(self) -> None:
        key = FallbackCandleProvider._cache_key("EURUSD", "H1")
        assert key == "WOLF15:CANDLE_CACHE:EURUSD:H1"

    def test_cache_key_different_symbol(self) -> None:
        key = FallbackCandleProvider._cache_key("GBPUSD", "D1")
        assert key == "WOLF15:CANDLE_CACHE:GBPUSD:D1"


# ══════════════════════════════════════════════════════════════════════
#  TTL defensive parsing
# ══════════════════════════════════════════════════════════════════════


class TestCancleCacheTtlParsing:
    """_parse_candle_cache_ttl() must handle bad env var values gracefully."""

    def test_valid_days_returns_correct_seconds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WOLF15_CANDLE_CACHE_TTL_DAYS", "3")
        from ingest.fallback_provider import _parse_candle_cache_ttl  # noqa: PLC0415

        assert _parse_candle_cache_ttl() == 3 * 86_400

    def test_non_integer_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WOLF15_CANDLE_CACHE_TTL_DAYS", "not_a_number")
        from ingest.fallback_provider import _parse_candle_cache_ttl  # noqa: PLC0415

        assert _parse_candle_cache_ttl() == 7 * 86_400

    def test_zero_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WOLF15_CANDLE_CACHE_TTL_DAYS", "0")
        from ingest.fallback_provider import _parse_candle_cache_ttl  # noqa: PLC0415

        assert _parse_candle_cache_ttl() == 7 * 86_400

    def test_negative_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WOLF15_CANDLE_CACHE_TTL_DAYS", "-5")
        from ingest.fallback_provider import _parse_candle_cache_ttl  # noqa: PLC0415

        assert _parse_candle_cache_ttl() == 7 * 86_400


# ══════════════════════════════════════════════════════════════════════
#  Timestamp rehydration on cache read
# ══════════════════════════════════════════════════════════════════════


class TestTimestampRehydration:
    """Cached candles with ISO string timestamps must be rehydrated to datetime."""

    @pytest.mark.asyncio
    async def test_iso_string_timestamp_rehydrated_to_datetime(self) -> None:
        from datetime import UTC, datetime  # noqa: PLC0415

        ts = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
        cached = [_cached_candle(timestamp=ts.isoformat())]

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached))

        provider = FallbackCandleProvider(redis_client=mock_redis)
        provider._providers = []  # force cache path

        result = await provider.fetch("EURUSD", "H1")
        assert len(result) == 1
        assert isinstance(result[0]["timestamp"], datetime), "Cached timestamp string must be rehydrated to datetime"
        assert result[0]["timestamp"].tzinfo is not None, "datetime must be timezone-aware"

    @pytest.mark.asyncio
    async def test_candle_without_timestamp_key_returned_unchanged(self) -> None:
        """Malformed cached rows without timestamp must be skipped."""
        cached = [_cached_candle()]
        del cached[0]["timestamp"]

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached))

        provider = FallbackCandleProvider(redis_client=mock_redis)
        provider._providers = []

        result = await provider.fetch("EURUSD", "H1")
        assert result == []

    @pytest.mark.asyncio
    async def test_unparseable_timestamp_string_left_as_is(self) -> None:
        """Malformed cached rows with bad timestamp must be skipped."""
        cached = [_cached_candle(timestamp="not-a-datetime")]

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached))

        provider = FallbackCandleProvider(redis_client=mock_redis)
        provider._providers = []

        result = await provider.fetch("EURUSD", "H1")
        assert result == []
