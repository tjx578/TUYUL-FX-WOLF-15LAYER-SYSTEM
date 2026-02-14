"""Unit tests for Finnhub WebSocket helpers."""

from unittest.mock import patch

import pytest

from ingest.finnhub_ws import FinnhubSymbolMapper, _calculate_backoff


class TestFinnhubSymbolMapper:
    """Bidirectional symbol mapping tests."""

    def test_forex_pair_mapping(self) -> None:
        mapper = FinnhubSymbolMapper(prefix="OANDA")
        result = mapper.register("EURUSD")
        assert result == "OANDA:EUR_USD"

    def test_commodity_mapping(self) -> None:
        mapper = FinnhubSymbolMapper(prefix="OANDA")
        result = mapper.register("XAUUSD")
        assert result == "OANDA:XAU_USD"

    def test_reverse_mapping(self) -> None:
        mapper = FinnhubSymbolMapper(prefix="OANDA")
        mapper.register("GBPJPY")
        assert mapper.to_internal("OANDA:GBP_JPY") == "GBPJPY"

    def test_unknown_reverse_returns_original(self) -> None:
        mapper = FinnhubSymbolMapper(prefix="OANDA")
        assert mapper.to_internal("UNKNOWN:SYM") == "UNKNOWN:SYM"

    @pytest.mark.parametrize(
        "internal, expected",
        [
            ("USDJPY", "OANDA:USD_JPY"),
            ("XAGUSD", "OANDA:XAG_USD"),
            ("NZDUSD", "OANDA:NZD_USD"),
            ("AUDCAD", "OANDA:AUD_CAD"),
        ],
    )
    def test_parametrized_conversions(self, internal: str, expected: str) -> None:
        mapper = FinnhubSymbolMapper(prefix="OANDA")
        assert mapper.register(internal) == expected


class TestBackoff:
    """Backoff helper tests."""

    def test_calculate_backoff_respects_maximum(self) -> None:
        with patch("ingest.finnhub_ws.random.uniform", return_value=0.0):
            assert _calculate_backoff(10, base=1.0, multiplier=2.0, maximum=30.0) == 30.0

    def test_calculate_backoff_floor(self) -> None:
        with patch("ingest.finnhub_ws.random.uniform", return_value=-1.0):
            assert _calculate_backoff(0, base=1.0, multiplier=2.0, maximum=10.0) == 0.1
