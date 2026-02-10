"""
Unit tests for FinnhubSymbolMapper and FinnhubWebSocket tick normalization.
"""

import pytest
from typing import cast
from unittest.mock import MagicMock, patch

from ingest.finnhub_ws import FinnhubSymbolMapper, FinnhubWebSocket


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
    def test_parametrized_conversions(
        self, internal: str, expected: str
    ) -> None:
        mapper = FinnhubSymbolMapper(prefix="OANDA")
        assert mapper.register(internal) == expected


class TestFinnhubWebSocketTickHandling:
    """Test tick normalization from Finnhub format."""

    @pytest.fixture
    def mock_ws_instance(self) -> FinnhubWebSocket:
        with (
            patch("ingest.finnhub_ws.load_finnhub") as mock_cfg,
            patch("ingest.finnhub_ws.load_pairs") as mock_pairs,
            patch.dict(
                "os.environ",
                {"FINNHUB_API_KEY": "test_key"},
            ),
        ):
            mock_cfg.return_value = {
                "websocket": {
                    "url": "wss://ws.finnhub.io",
                    "reconnect_interval_sec": 1,
                    "ping_interval_sec": 30,
                },
                "symbols": {"symbol_prefix": "OANDA"},
                "rest": {},
                "news": {},
            }
            mock_pairs.return_value = [
                {"symbol": "EURUSD", "enabled": True},
                {"symbol": "XAUUSD", "enabled": True},
            ]
            instance = FinnhubWebSocket()
            instance._context_bus = MagicMock()
            return instance

    @pytest.mark.asyncio
    async def test_handle_trade_message(
        self, mock_ws_instance: FinnhubWebSocket
    ) -> None:
        msg = {
            "type": "trade",
            "data": [
                {
                    "p": 1.0842,
                    "s": "OANDA:EUR_USD",
                    "t": 1700000000000,
                    "v": 100,
                }
            ],
        }
        await mock_ws_instance._handle_message(msg)

        update_tick_mock = cast(
            MagicMock, mock_ws_instance._context_bus.update_tick
        )
        update_tick_mock.assert_called_once()
        call_args = update_tick_mock.call_args[0][0]
        assert call_args["symbol"] == "EURUSD"
        assert call_args["bid"] == 1.0842
        assert call_args["source"] == "finnhub_ws"
        assert call_args["timestamp"] == 1700000000.0

    @pytest.mark.asyncio
    async def test_ignores_non_trade_messages(
        self, mock_ws_instance: FinnhubWebSocket
    ) -> None:
        msg = {"type": "ping"}
        await mock_ws_instance._handle_message(msg)
        update_tick_mock = cast(
            MagicMock, mock_ws_instance._context_bus.update_tick
        )
        update_tick_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_incomplete_trade_data(
        self, mock_ws_instance: FinnhubWebSocket
    ) -> None:
        msg = {
            "type": "trade",
            "data": [{"s": "OANDA:EUR_USD", "t": None, "p": None}],
        }
        await mock_ws_instance._handle_message(msg)
        update_tick_mock = cast(
            MagicMock, mock_ws_instance._context_bus.update_tick
        )
        update_tick_mock.assert_not_called()
