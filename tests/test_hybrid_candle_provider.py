from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from ingest.hybrid_candle_provider import HybridCandleProvider


def _candle(symbol: str, timeframe: str, source: str) -> dict:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "open": 1.0,
        "high": 1.1,
        "low": 0.9,
        "close": 1.05,
        "volume": 100.0,
        "timestamp": datetime(2026, 6, 8, tzinfo=UTC),
        "source": source,
    }


@pytest.mark.asyncio
async def test_default_uses_finnhub_before_substitute_provider_for_all_symbols() -> None:
    finnhub = MagicMock()
    finnhub.fetch = AsyncMock(return_value=[_candle("CHFJPY", "H1", "rest_api")])
    fallback = MagicMock()
    fallback.available_providers = ["twelve_data", "alpha_vantage"]
    fallback.fetch = AsyncMock(return_value=[_candle("CHFJPY", "H1", "twelve_data")])

    provider = HybridCandleProvider(finnhub_fetcher=finnhub, fallback_provider=fallback)
    result = await provider.fetch("CHFJPY", "H1", 5)

    assert result.provider == "finnhub"
    assert result.reason == "finnhub_primary"
    finnhub.fetch.assert_awaited_once_with("CHFJPY", "H1", 5)
    fallback.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_override_can_make_substitute_primary_for_emergency_repair() -> None:
    finnhub = MagicMock()
    finnhub.fetch = AsyncMock(return_value=[_candle("EURUSD", "H1", "rest_api")])
    fallback = MagicMock()
    fallback.available_providers = ["twelve_data", "alpha_vantage"]
    fallback.fetch = AsyncMock(return_value=[_candle("EURUSD", "H1", "twelve_data")])

    provider = HybridCandleProvider(
        finnhub_fetcher=finnhub,
        fallback_provider=fallback,
        substitute_first_symbols={"EURUSD"},
    )
    result = await provider.fetch("EURUSD", "H1", 5)

    assert result.provider == "twelve_data"
    assert result.reason == "substitute_first"
    fallback.fetch.assert_awaited_once_with("EURUSD", "H1", 5, allow_stale_cache=True)
    finnhub.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_forex_falls_back_to_substitute_when_finnhub_fails() -> None:
    finnhub = MagicMock()
    finnhub.fetch = AsyncMock(side_effect=RuntimeError("429"))
    fallback = MagicMock()
    fallback.available_providers = ["twelve_data"]
    fallback.fetch = AsyncMock(return_value=[_candle("EURUSD", "H1", "twelve_data")])

    provider = HybridCandleProvider(finnhub_fetcher=finnhub, fallback_provider=fallback)
    result = await provider.fetch("EURUSD", "H1", 5)

    assert result.provider == "twelve_data"
    assert result.reason == "finnhub_failed_substitute"
    finnhub.fetch.assert_awaited_once_with("EURUSD", "H1", 5)
    fallback.fetch.assert_awaited_once_with("EURUSD", "H1", 5, allow_stale_cache=True)


@pytest.mark.asyncio
async def test_substitute_first_override_can_fall_back_to_finnhub_when_substitute_empty() -> None:
    finnhub = MagicMock()
    finnhub.fetch = AsyncMock(return_value=[_candle("XAUUSD", "D1", "rest_api")])
    fallback = MagicMock()
    fallback.available_providers = ["twelve_data"]
    fallback.fetch = AsyncMock(return_value=[])

    provider = HybridCandleProvider(
        finnhub_fetcher=finnhub,
        fallback_provider=fallback,
        substitute_first_symbols={"XAUUSD"},
    )
    result = await provider.fetch("XAUUSD", "D1", 1)

    assert result.provider == "finnhub"
    assert result.reason == "finnhub_fallback"
    fallback.fetch.assert_awaited_once_with("XAUUSD", "D1", 1, allow_stale_cache=True)
    finnhub.fetch.assert_awaited_once_with("XAUUSD", "D1", 1)
