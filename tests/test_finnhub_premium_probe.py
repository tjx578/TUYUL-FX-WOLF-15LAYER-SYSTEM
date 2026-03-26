"""
Unit tests for FinnhubCandleFetcher.probe_premium_pairs.

Verifies classification of free / premium / error pairs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ingest.finnhub_candles import (
    FinnhubCandleError,
    FinnhubCandleFetcher,
    FinnhubCandlePremiumError,
)


class TestProbePremiumPairs:
    """Test FinnhubCandleFetcher.probe_premium_pairs."""

    @pytest.mark.asyncio
    @patch("ingest.finnhub_candles.CONFIG", {"pairs": {"symbols": ["EURUSD", "XAUUSD"]}})
    async def test_classifies_free_and_premium(self) -> None:
        """Free pair returns candles, premium pair raises 403."""
        fetcher = FinnhubCandleFetcher()

        async def mock_fetch(symbol: str, tf: str, bars: int) -> list:
            if symbol == "XAUUSD":
                raise FinnhubCandlePremiumError("403")
            return [{"symbol": symbol, "close": 1.1}]

        fetcher.fetch = mock_fetch  # type: ignore[method-assign]

        results = await fetcher.probe_premium_pairs()

        assert results["EURUSD"] == "free"
        assert results["XAUUSD"] == "premium"

    @pytest.mark.asyncio
    @patch("ingest.finnhub_candles.CONFIG", {"pairs": {"symbols": ["GBPUSD"]}})
    async def test_classifies_error(self) -> None:
        """Non-403 failure classifies as error."""
        fetcher = FinnhubCandleFetcher()

        async def mock_fetch(symbol: str, tf: str, bars: int) -> list:
            raise FinnhubCandleError("timeout")

        fetcher.fetch = mock_fetch  # type: ignore[method-assign]

        results = await fetcher.probe_premium_pairs()
        assert results["GBPUSD"] == "error"

    @pytest.mark.asyncio
    @patch("ingest.finnhub_candles.CONFIG", {"pairs": {"symbols": []}})
    async def test_empty_symbols(self) -> None:
        """No symbols → empty result."""
        fetcher = FinnhubCandleFetcher()
        results = await fetcher.probe_premium_pairs()
        assert results == {}

    @pytest.mark.asyncio
    async def test_explicit_symbols_override(self) -> None:
        """Passing explicit symbols ignores CONFIG."""
        fetcher = FinnhubCandleFetcher()
        fetcher.fetch = AsyncMock(return_value=[{"close": 1.0}])

        results = await fetcher.probe_premium_pairs(symbols=["USDJPY"])

        assert results == {"USDJPY": "free"}
        fetcher.fetch.assert_called_once_with("USDJPY", "H1", 1)

    @pytest.mark.asyncio
    @patch("ingest.finnhub_candles.CONFIG", {"pairs": {"symbols": ["EURUSD", "XAUUSD", "GBPJPY"]}})
    async def test_probe_counts(self) -> None:
        """Verify the probe returns correct counts."""
        fetcher = FinnhubCandleFetcher()

        async def mock_fetch(symbol: str, tf: str, bars: int) -> list:
            if symbol == "XAUUSD":
                raise FinnhubCandlePremiumError("403")
            return [{"symbol": symbol}]

        fetcher.fetch = mock_fetch  # type: ignore[method-assign]

        results = await fetcher.probe_premium_pairs()

        free_count = sum(1 for v in results.values() if v == "free")
        premium_count = sum(1 for v in results.values() if v == "premium")

        assert free_count == 2
        assert premium_count == 1
