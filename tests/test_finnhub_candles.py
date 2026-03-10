"""
Unit tests for Finnhub REST candle fetcher.

Tests symbol conversion, resolution mapping, response normalization,
H4 aggregation, and warmup functionality.
"""


from datetime import UTC, datetime, tzinfo
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from ingest.finnhub_candles import FinnhubCandleFetcher

# Real Finnhub response data (20 bars of D1 EURUSD)
REAL_FINNHUB_RESPONSE = {
    "c": [
        1.1127, 1.10701, 1.10655, 1.10489, 1.10146, 1.10325, 1.10078, 1.10054,
        1.10194, 1.10479, 1.10683, 1.10776, 1.10716, 1.10579, 1.10162, 1.10067,
        1.1021, 1.09983, 1.10059, 1.10159
    ],
    "h": [
        1.11749, 1.11397, 1.10923, 1.10912, 1.10549, 1.10425, 1.10379, 1.10198,
        1.10271, 1.10564, 1.10894, 1.10834, 1.10808, 1.10965, 1.10863, 1.10316,
        1.1025, 1.10234, 1.10175, 1.10278
    ],
    "l": [
        1.11242, 1.10631, 1.10638, 1.10353, 1.10146, 1.10152, 1.10019, 1.09948,
        1.09885, 1.1014, 1.10457, 1.10621, 1.10524, 1.10516, 1.10138, 1.10029,
        1.10057, 1.09918, 1.09958, 1.09806
    ],
    "o": [
        1.11674, 1.1127, 1.10737, 1.10655, 1.10483, 1.10215, 1.10325, 1.10081,
        1.10013, 1.10199, 1.10477, 1.10705, 1.10766, 1.10713, 1.10566, 1.10156,
        1.10114, 1.10202, 1.09994, 1.10051
    ],
    "s": "ok",
    "t": [
        1572818400, 1572904800, 1572991200, 1573077600, 1573164000, 1573423200,
        1573509600, 1573596000, 1573682400, 1573768800, 1574028000, 1574114400,
        1574200800, 1574287200, 1574373600, 1574632800, 1574719200, 1574805600,
        1574892000, 1574978400
    ],
    "v": [
        46494, 60926, 46621, 69028, 46822, 31994, 44108, 46795, 44539, 36153,
        39113, 34391, 47213, 44356, 49441, 40379, 40476, 40904, 23875, 36521
    ],
}


class TestSymbolConversion:
    """Test symbol conversion to Finnhub format."""

    def test_eurusd_conversion(self) -> None:
        """Test EURUSD -> OANDA:EUR_USD conversion."""
        fetcher = FinnhubCandleFetcher()
        result = fetcher.convert_symbol("EURUSD")
        assert result == "OANDA:EUR_USD"

    def test_xauusd_conversion(self) -> None:
        """Test XAUUSD -> OANDA:XAU_USD conversion."""
        fetcher = FinnhubCandleFetcher()
        result = fetcher.convert_symbol("XAUUSD")
        assert result == "OANDA:XAU_USD"

    def test_already_prefixed_passthrough(self) -> None:
        """Test already-prefixed symbols pass through unchanged."""
        fetcher = FinnhubCandleFetcher()
        result = fetcher.convert_symbol("OANDA:EUR_USD")
        assert result == "OANDA:EUR_USD"

    def test_gbpjpy_conversion(self) -> None:
        """Test GBPJPY -> OANDA:GBP_JPY conversion."""
        fetcher = FinnhubCandleFetcher()
        result = fetcher.convert_symbol("GBPJPY")
        assert result == "OANDA:GBP_JPY"


class TestResolutionMapping:
    """Test timeframe to resolution mapping."""

    def test_h1_resolution(self) -> None:
        """Test H1 -> 60 mapping."""
        fetcher = FinnhubCandleFetcher()
        assert fetcher.RESOLUTION_MAP["H1"] == "60"

    def test_d1_resolution(self) -> None:
        """Test D1 -> D mapping."""
        fetcher = FinnhubCandleFetcher()
        assert fetcher.RESOLUTION_MAP["D1"] == "D"

    def test_w1_resolution(self) -> None:
        """Test W1 -> W mapping."""
        fetcher = FinnhubCandleFetcher()
        assert fetcher.RESOLUTION_MAP["W1"] == "W"

    def test_h4_not_in_map(self) -> None:
        """Test H4 is not in direct resolution map (requires aggregation)."""
        fetcher = FinnhubCandleFetcher()
        assert "H4" not in fetcher.RESOLUTION_MAP


class TestNormalizeResponse:
    """Test response normalization using real Finnhub data."""

    def test_bar_count(self) -> None:
        """Test normalized response has correct bar count."""
        fetcher = FinnhubCandleFetcher()
        candles = fetcher.normalize_response(REAL_FINNHUB_RESPONSE, "EURUSD", "D1")
        assert len(candles) == 20

    def test_first_bar_ohlcv(self) -> None:
        """Test first bar OHLCV matches."""
        fetcher = FinnhubCandleFetcher()
        candles = fetcher.normalize_response(REAL_FINNHUB_RESPONSE, "EURUSD", "D1")

        first = candles[0]
        assert first["open"] == 1.11674
        assert first["high"] == 1.11749
        assert first["low"] == 1.11242
        assert first["close"] == 1.1127
        assert first["volume"] == 46494

    def test_last_bar_ohlcv(self) -> None:
        """Test last bar OHLCV matches."""
        fetcher = FinnhubCandleFetcher()
        candles = fetcher.normalize_response(REAL_FINNHUB_RESPONSE, "EURUSD", "D1")

        last = candles[-1]
        assert last["open"] == 1.10051
        assert last["high"] == 1.10278
        assert last["low"] == 1.09806
        assert last["close"] == 1.10159
        assert last["volume"] == 36521

    def test_timestamps_utc(self) -> None:
        """Test all timestamps are UTC."""
        fetcher = FinnhubCandleFetcher()
        candles = fetcher.normalize_response(REAL_FINNHUB_RESPONSE, "EURUSD", "D1")

        for candle in candles:
            ts = candle["timestamp"]
            assert isinstance(ts, datetime)
            assert ts.tzinfo == UTC

    def test_tzinfo_is_instance_not_type(self) -> None:
        """Regression: tzinfo must be an instance (e.g. timezone.utc), not the timezone class."""
        fetcher = FinnhubCandleFetcher()
        candles = fetcher.normalize_response(REAL_FINNHUB_RESPONSE, "EURUSD", "D1")

        for candle in candles:
            ts = candle["timestamp"]
            # tzinfo must be an instance, not a class/type
            assert not isinstance(ts.tzinfo, type), (
                f"tzinfo is a type ({ts.tzinfo}), expected an instance like timezone.utc"
            )
            assert isinstance(ts.tzinfo, tzinfo)

    def test_ohlc_validity(self) -> None:
        """Test OHLC relationships are valid (high >= open,close; low <= open,close)."""
        fetcher = FinnhubCandleFetcher()
        candles = fetcher.normalize_response(REAL_FINNHUB_RESPONSE, "EURUSD", "D1")

        for candle in candles:
            assert candle["high"] >= candle["open"]
            assert candle["high"] >= candle["close"]
            assert candle["low"] <= candle["open"]
            assert candle["low"] <= candle["close"]

    def test_no_data_response(self) -> None:
        """Test handling of no_data status."""
        fetcher = FinnhubCandleFetcher()
        no_data_response = {"s": "no_data"}
        candles = fetcher.normalize_response(no_data_response, "EURUSD", "D1")
        assert candles == []

    def test_metadata_fields(self) -> None:
        """Test metadata fields are present."""
        fetcher = FinnhubCandleFetcher()
        candles = fetcher.normalize_response(REAL_FINNHUB_RESPONSE, "EURUSD", "D1")

        first = candles[0]
        assert first["symbol"] == "EURUSD"
        assert first["timeframe"] == "D1"
        assert first["source"] == "rest_api"


class TestM15Rejection:
    """Test M15 timeframe behaviour (REST fallback is now allowed)."""

    def test_m15_in_resolution_map(self) -> None:
        """M15 resolution is '15' in the RESOLUTION_MAP."""
        assert FinnhubCandleFetcher.RESOLUTION_MAP["M15"] == "15"


class TestH4Aggregation:
    """Test H1 to H4 aggregation (4:1)."""

    def test_four_h1_to_one_h4(self) -> None:
        """Test 4 H1 bars aggregate to 1 H4 bar."""
        fetcher = FinnhubCandleFetcher()

        # Create 4 H1 bars aligned to 00:00, 01:00, 02:00, 03:00 UTC
        h1_bars = [
            {
                "symbol": "EURUSD",
                "timeframe": "H1",
                "open": 1.1000,
                "high": 1.1010,
                "low": 1.0990,
                "close": 1.1005,
                "volume": 100,
                "timestamp": datetime(2024, 1, 15, 1, 0, 0, tzinfo=UTC),
                "source": "rest_api",
            },
            {
                "symbol": "EURUSD",
                "timeframe": "H1",
                "open": 1.1005,
                "high": 1.1020,
                "low": 1.1000,
                "close": 1.1015,
                "volume": 150,
                "timestamp": datetime(2024, 1, 15, 2, 0, 0, tzinfo=UTC),
                "source": "rest_api",
            },
            {
                "symbol": "EURUSD",
                "timeframe": "H1",
                "open": 1.1015,
                "high": 1.1030,
                "low": 1.1010,
                "close": 1.1025,
                "volume": 120,
                "timestamp": datetime(2024, 1, 15, 3, 0, 0, tzinfo=UTC),
                "source": "rest_api",
            },
            {
                "symbol": "EURUSD",
                "timeframe": "H1",
                "open": 1.1025,
                "high": 1.1035,
                "low": 1.1020,
                "close": 1.1030,
                "volume": 130,
                "timestamp": datetime(2024, 1, 15, 4, 0, 0, tzinfo=UTC),
                "source": "rest_api",
            },
        ]

        h4_bars = fetcher.aggregate_h4(h1_bars)

        assert len(h4_bars) == 1
        h4 = h4_bars[0]

        # Open from first H1
        assert h4["open"] == 1.1000
        # High from all H1s
        assert h4["high"] == 1.1035
        # Low from all H1s
        assert h4["low"] == 1.0990
        # Close from last H1
        assert h4["close"] == 1.1030
        # Volume sum
        assert h4["volume"] == 500
        # Timeframe
        assert h4["timeframe"] == "H4"
        # Source
        assert h4["source"] == "h1_aggregated"

    def test_h4_alignment(self) -> None:
        """Test H4 bars align to 00:00, 04:00, 08:00, etc."""
        fetcher = FinnhubCandleFetcher()

        # Create H1 bars spanning multiple H4 periods
        h1_bars = [
            {
                "symbol": "EURUSD",
                "timeframe": "H1",
                "open": 1.1000 + hour * 0.001,
                "high": 1.1010 + hour * 0.001,
                "low": 1.0990 + hour * 0.001,
                "close": 1.1005 + hour * 0.001,
                "volume": 100,
                "timestamp": datetime(2024, 1, 15, hour + 1, 0, 0, tzinfo=UTC),
                "source": "rest_api",
            }
            for hour in range(8)
        ]

        h4_bars = fetcher.aggregate_h4(h1_bars)

        # Should produce 2 H4 bars: 00:00-04:00 and 04:00-08:00
        assert len(h4_bars) == 2


class TestWarmup:
    """Test warmup functionality."""

    @pytest.mark.asyncio
    @patch("ingest.finnhub_candles.FinnhubCandleFetcher.fetch")
    async def test_warmup_seeds_context_bus(self, mock_fetch: AsyncMock) -> None:
        """Test warmup seeds LiveContextBus with candles."""
        # Mock fetch to return test candles
        test_candles = [
            {
                "symbol": "EURUSD",
                "timeframe": "H1",
                "open": 1.1000,
                "high": 1.1010,
                "low": 1.0990,
                "close": 1.1005,
                "volume": 100,
                "timestamp": datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
                "source": "rest_api",
            }
        ]

        mock_fetch.return_value = test_candles

        fetcher = FinnhubCandleFetcher()

        # Patch CONFIG to have a single test symbol
        with patch("ingest.finnhub_candles.CONFIG", {"pairs": {"symbols": ["EURUSD"]}}), \
             patch.object(fetcher, "warmup_config", {
                "enabled": True,
                "bars": 10,
                "timeframes": ["H1"],
            }):
            results = await fetcher.warmup_all()

        # Check results structure
        assert "EURUSD" in results
        assert "H1" in results["EURUSD"]

        # Verify fetch was called
        assert mock_fetch.called


class TestPremiumFallback:
    """Test that premium-blocked symbols fall back to alternative providers."""

    @pytest.mark.asyncio
    @patch("ingest.finnhub_candles.FinnhubCandleFetcher.try_fallback")
    @patch("ingest.finnhub_candles.FinnhubCandleFetcher.fetch")
    async def test_premium_error_triggers_fallback(
        self, mock_fetch: AsyncMock, mock_fallback: AsyncMock
    ) -> None:
        """When fetch raises FinnhubCandlePremiumError, _try_fallback is invoked."""
        from ingest.finnhub_candles import FinnhubCandlePremiumError

        mock_fetch.side_effect = FinnhubCandlePremiumError("403 premium required")

        fallback_candles = [
            {
                "symbol": "XAGUSD",
                "timeframe": "D1",
                "open": 30.00,
                "high": 30.50,
                "low": 29.80,
                "close": 30.25,
                "volume": 500,
                "timestamp": datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC),
                "source": "twelve_data",
            }
        ]
        mock_fallback.return_value = fallback_candles

        fetcher = FinnhubCandleFetcher()
        results: dict[str, dict[str, list[dict[str, Any]]]] = {}

        await fetcher.warmup_symbol_tf("XAGUSD", "D1", 10, results)

        mock_fallback.assert_awaited_once_with("XAGUSD", "D1", 10)
        assert "XAGUSD" in results
        assert results["XAGUSD"]["D1"] == fallback_candles

    @pytest.mark.asyncio
    @patch("ingest.finnhub_candles.FinnhubCandleFetcher.try_fallback")
    @patch("ingest.finnhub_candles.FinnhubCandleFetcher.fetch")
    async def test_premium_no_fallback_available(
        self, mock_fetch: AsyncMock, mock_fallback: AsyncMock
    ) -> None:
        """When fallback returns empty, results stay empty and no crash."""
        from ingest.finnhub_candles import FinnhubCandlePremiumError

        mock_fetch.side_effect = FinnhubCandlePremiumError("403")
        mock_fallback.return_value = []

        fetcher = FinnhubCandleFetcher()
        results: dict[str, dict[str, list[dict[str, Any]]]] = {}

        await fetcher.warmup_symbol_tf("XAGUSD", "D1", 10, results)

        mock_fallback.assert_awaited_once()
        assert "XAGUSD" not in results

    @pytest.mark.asyncio
    @patch("ingest.finnhub_candles.FinnhubCandleFetcher.fetch")
    async def test_try_fallback_no_providers(self, mock_fetch: AsyncMock) -> None:
        """_try_fallback returns [] when no fallback providers are configured."""
        from ingest.finnhub_candles import FinnhubCandlePremiumError

        mock_fetch.side_effect = FinnhubCandlePremiumError("403")

        fetcher = FinnhubCandleFetcher()

        with patch("ingest.fallback_provider.FallbackCandleProvider") as MockProvider:  # noqa: N806
            MockProvider.return_value.available_providers = []
            result = await fetcher.try_fallback("XAGUSD", "D1", 10)

        assert result == []
