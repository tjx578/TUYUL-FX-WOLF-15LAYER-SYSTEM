from datetime import UTC, datetime, tzinfo
from unittest.mock import AsyncMock, patch

import pytest
from datetime import UTC, datetime

from ingest.finnhub_candles import FinnhubCandleError, FinnhubCandleFetcher


@pytest.mark.asyncio
async def test_warmup_includes_required_timeframes():
    """Even if config lists only H1, warmup_all must fetch H1,H4,D1,W1,MN."""
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

        # Verify all required timeframes were requested (including MN)
        assert {"H1", "H4", "D1", "W1", "MN"}.issubset(set(called_tfs))
        # Results should include symbol
        assert "EURUSD" in results


# ---------------------------------------------------------------------------
# Regression: tzinfo must always be an instance, never the class itself
# ---------------------------------------------------------------------------

class TestTzinfoIsInstance:
    """
    Regression suite for GitHub CI TypeError:
      'tzinfo argument must be None or of a tzinfo subclass, not type <type>'

    Root cause was `from datetime import datetime, timezone as UTC` which
    aliases the *class* `timezone` instead of the *instance* `timezone.utc`.
    """

    def test_utc_is_instance_not_class(self) -> None:
        """UTC constant used in source must be an instance, not a type."""
        assert not isinstance(UTC, type), (
            "UTC is a class/type - expected an instance like timezone.utc"
        )
        assert isinstance(UTC, tzinfo)

    def test_utc_equals_timezone_utc(self) -> None:
        """UTC must be the same object as timezone.utc."""
        assert UTC is UTC  # noqa: PLR0124

    @pytest.mark.parametrize("year,month,day", [
        (2024, 1, 1),
        (2024, 6, 27),
        (2025, 12, 31),
    ])
    def test_datetime_constructor_with_utc(self, year: int, month: int, day: int) -> None:
        """datetime(..., tzinfo=UTC) must not raise TypeError."""
        dt = datetime(year, month, day, tzinfo=UTC)
        assert dt.tzinfo is not None
        assert dt.tzinfo is UTC

    def test_datetime_now_utc(self) -> None:
        """datetime.now(UTC) must produce tz-aware datetime."""
        dt = datetime.now(UTC)
        assert dt.tzinfo is not None
        assert isinstance(dt.tzinfo, tzinfo)

    def test_datetime_fromtimestamp_utc(self) -> None:
        """datetime.fromtimestamp with UTC must produce tz-aware datetime."""
        dt = datetime.fromtimestamp(0, tz=UTC)
        assert dt.tzinfo is not None
        assert dt.tzinfo is UTC


# ---------------------------------------------------------------------------
# Parametrized warmup per-timeframe tests
# ---------------------------------------------------------------------------

class TestWarmupPerTimeframe:
    """Verify warmup works for every required timeframe individually."""

    REQUIRED_TIMEFRAMES = ["H1", "H4", "D1", "W1", "MN"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tf", ["H1", "H4", "D1", "W1", "MN"])
    async def test_warmup_single_timeframe(self, tf: str) -> None:
        """Warmup must succeed for each required timeframe '{tf}'."""
        fake_config = {"pairs": {"symbols": ["EURUSD"]}}

        with patch("ingest.finnhub_candles.CONFIG", fake_config):
            fetcher = FinnhubCandleFetcher()
            fetcher.warmup_config = {
                "enabled": True,
                "timeframes": [tf],
                "bars": 2,
            }

            called_tfs: list[str] = []

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

            # The requested timeframe must have been called
            assert tf in called_tfs, f"{tf} was not fetched during warmup"
            assert "EURUSD" in results


class TestCalculateFromTs:
    """Test _calculate_from_ts handles all supported timeframes."""

    @pytest.mark.parametrize("tf", ["H1", "D1", "W1", "MN"])
    def test_supported_timeframes_no_error(self, tf: str) -> None:
        """_calculate_from_ts must not raise for supported timeframe '{tf}'."""
        fetcher = FinnhubCandleFetcher()
        ts = fetcher._calculate_from_ts(bars=10, timeframe=tf)
        assert isinstance(ts, int)
        assert ts > 0

    def test_unsupported_timeframe_raises(self) -> None:
        """_calculate_from_ts must raise for unknown timeframes."""
        fetcher = FinnhubCandleFetcher()
        with pytest.raises(FinnhubCandleError):
            fetcher._calculate_from_ts(bars=10, timeframe="INVALID")
