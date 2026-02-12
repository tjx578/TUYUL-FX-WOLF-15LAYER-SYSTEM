import pytest
from unittest.mock import AsyncMock, patch
from datetime import UTC, datetime

from ingest.finnhub_candles import FinnhubCandleFetcher


@pytest.mark.asyncio
async def test_warmup_includes_required_timeframes():
    """Even if config lists only H1, warmup_all must fetch H1,H4,D1,W1."""
    fake_config = {"pairs": {"symbols": ["EURUSD"]}}

    with patch("ingest.finnhub_candles.CONFIG", fake_config):
        fetcher = FinnhubCandleFetcher()
        # Simulate a misconfigured warmup that only lists H1
        fetcher.warmup_config = {"enabled": True, "timeframes": ["H1"], "bars": 2}

        called_tfs = []

        async def fake_fetch(symbol: str, timeframe: str, bars: int = 100):
            called_tfs.append(timeframe)
            return [
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "open": 1.0,
                    "high": 1.1,
                    "low": 0.9,
                    "close": 1.05,
                    "volume": 1,
                    "timestamp": datetime.now(UTC),
                    "source": "rest_api",
                }
            ]

        fetcher.fetch = AsyncMock(side_effect=fake_fetch)

        results = await fetcher.warmup_all()

        # Verify H1, H4, D1, W1 were requested
        assert set(["H1", "H4", "D1", "W1"]).issubset(set(called_tfs))
        # Results should include symbol
        assert "EURUSD" in results
