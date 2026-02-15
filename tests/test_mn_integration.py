from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]


@pytest.mark.asyncio
@patch("ingest.finnhub_candles.FinnhubCandleFetcher.fetch")
async def test_mn_fetch_in_warmup(mock_fetch):
    mn_candles = [
        {
            "symbol": "XAUUSD",
            "timeframe": "MN",
            "open": 1800.00,
            "high": 2100.00,
            "low": 1750.00,
            "close": 2050.00,
            "volume": 1000000,
            "timestamp": datetime(2024, 1, 31, 23, 59, 59, tzinfo=UTC),
            "source": "rest_api",
        }
    ]

    async def fake_fetch(symbol, timeframe, bars=100):
        if timeframe == "MN":
            return mn_candles
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

    mock_fetch.side_effect = fake_fetch

    from ingest.finnhub_candles import FinnhubCandleFetcher  # noqa: PLC0415

    with patch("ingest.finnhub_candles.CONFIG", {"pairs": {"symbols": ["XAUUSD"]}}):
        fetcher = FinnhubCandleFetcher()
        fetcher.warmup_config = {"enabled": True, "bars": 10, "timeframes": ["H1", "D1", "W1", "MN"]}
        results = await fetcher.warmup_all()

    assert "XAUUSD" in results
    assert "MN" in results["XAUUSD"]
    assert len(results["XAUUSD"]["MN"]) > 0


def test_macro_regime_engine_initialization():
    from analysis.macro.macro_regime_engine import MacroRegimeEngine  # noqa: PLC0415

    mock_redis = MagicMock()
    mock_redis.client.lrange.return_value = [
        '{"open": 1800, "high": 2100, "low": 1750, "close": 2050}',
        '{"open": 1750, "high": 1950, "low": 1700, "close": 1900}',
    ]

    engine = MacroRegimeEngine(redis_client=mock_redis)
    mn_history = engine._load_mn_history("XAUUSD")

    assert len(mn_history) == 2
    assert mn_history[0]["open"] == 1800


def test_l2_mta_with_macro_weighting():
    from analysis.layers.L2_mta import L2MTA  # noqa: PLC0415

    mock_redis = MagicMock()
    mock_redis.hgetall.return_value = {"type": "BULLISH_EXPANSION", "bias": "BULLISH"}

    l2 = L2MTA(redis_client=mock_redis)

    with patch.object(l2, "bus") as mock_bus:
        mock_bus.get_candle.return_value = {"open": 1.1, "close": 1.2}
        result = l2.compute("XAUUSD", "BULLISH")

    assert result["per_tf"]["MN"]["weight"] == 0.35
    assert result["per_tf"]["MN"]["bias"] == "BULLISH"
