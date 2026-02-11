"""
Unit tests for ingest/dependencies.py - Finnhub WS factory and tick handling.
"""

from unittest.mock import MagicMock, patch

import pytest

from ingest.dependencies import _SYMBOL_REVERSE_MAP, _handle_tick, create_finnhub_ws


class TestSymbolReverseMap:
    """Test symbol reverse mapping."""

    def test_symbol_map_format(self) -> None:
        """Verify reverse map correctly strips prefix and underscore."""
        assert _SYMBOL_REVERSE_MAP["OANDA:EUR_USD"] == "EURUSD"
        assert _SYMBOL_REVERSE_MAP["OANDA:GBP_JPY"] == "GBPJPY"
        assert _SYMBOL_REVERSE_MAP["OANDA:XAU_USD"] == "XAUUSD"

    def test_all_default_symbols_mapped(self) -> None:
        """Verify all default symbols are in the reverse map."""
        expected_symbols = [
            "OANDA:EUR_USD",
            "OANDA:GBP_JPY",
            "OANDA:USD_JPY",
            "OANDA:GBP_USD",
            "OANDA:AUD_USD",
            "OANDA:XAU_USD",
        ]
        for symbol in expected_symbols:
            assert symbol in _SYMBOL_REVERSE_MAP
            assert "_" not in _SYMBOL_REVERSE_MAP[symbol]
            assert ":" not in _SYMBOL_REVERSE_MAP[symbol]


class TestHandleTick:
    """Test _handle_tick function for tick normalization and routing."""

    @pytest.mark.asyncio
    async def test_handle_tick_normalizes_format(self) -> None:
        """Test that Finnhub tick format is normalized to internal format."""
        with patch("ingest.dependencies.LiveContextBus") as mock_bus_class:
            mock_bus = MagicMock()
            mock_bus_class.return_value = mock_bus

            data = {
                "type": "trade",
                "data": [
                    {
                        "p": 1.0842,
                        "s": "OANDA:EUR_USD",
                        "t": 1700000000000,  # milliseconds
                        "v": 100,
                    }
                ],
            }

            await _handle_tick(data)

            # Verify update_tick was called
            mock_bus.update_tick.assert_called_once()

            # Verify normalized tick format
            call_args = mock_bus.update_tick.call_args[0][0]
            assert call_args["symbol"] == "EURUSD"
            assert call_args["bid"] == 1.0842
            assert call_args["ask"] == 1.0842  # Same as bid for Finnhub
            assert call_args["timestamp"] == 1700000000.0  # Converted to seconds
            assert call_args["source"] == "finnhub_ws"

    @pytest.mark.asyncio
    async def test_handle_tick_ignores_non_trade_messages(self) -> None:
        """Test that non-trade messages are ignored."""
        with patch("ingest.dependencies.LiveContextBus") as mock_bus_class:
            mock_bus = MagicMock()
            mock_bus_class.return_value = mock_bus

            data = {"type": "ping"}
            await _handle_tick(data)

            mock_bus.update_tick.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_tick_skips_incomplete_data(self) -> None:
        """Test that incomplete tick data is skipped."""
        with patch("ingest.dependencies.LiveContextBus") as mock_bus_class:
            mock_bus = MagicMock()
            mock_bus_class.return_value = mock_bus

            # Missing price
            data = {
                "type": "trade",
                "data": [
                    {
                        "s": "OANDA:EUR_USD",
                        "t": 1700000000000,
                        # Missing "p"
                    }
                ],
            }
            await _handle_tick(data)
            mock_bus.update_tick.assert_not_called()

            # Missing symbol
            data = {
                "type": "trade",
                "data": [
                    {
                        "p": 1.0842,
                        "t": 1700000000000,
                        # Missing "s"
                    }
                ],
            }
            await _handle_tick(data)
            mock_bus.update_tick.assert_not_called()

            # Missing timestamp
            data = {
                "type": "trade",
                "data": [
                    {
                        "p": 1.0842,
                        "s": "OANDA:EUR_USD",
                        # Missing "t"
                    }
                ],
            }
            await _handle_tick(data)
            mock_bus.update_tick.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_tick_skips_unmapped_symbols(self) -> None:
        """Test that unmapped symbols (not in our config) are skipped."""
        with patch("ingest.dependencies.LiveContextBus") as mock_bus_class:
            mock_bus = MagicMock()
            mock_bus_class.return_value = mock_bus

            data = {
                "type": "trade",
                "data": [
                    {
                        "p": 1.5000,
                        "s": "OANDA:USD_CAD",  # Not in default symbols
                        "t": 1700000000000,
                        "v": 100,
                    }
                ],
            }

            await _handle_tick(data)

            # Should be skipped
            mock_bus.update_tick.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_tick_processes_multiple_trades(self) -> None:
        """Test that multiple trades in data array are all processed."""
        with patch("ingest.dependencies.LiveContextBus") as mock_bus_class:
            mock_bus = MagicMock()
            mock_bus_class.return_value = mock_bus

            data = {
                "type": "trade",
                "data": [
                    {
                        "p": 1.0842,
                        "s": "OANDA:EUR_USD",
                        "t": 1700000000000,
                        "v": 100,
                    },
                    {
                        "p": 185.50,
                        "s": "OANDA:GBP_JPY",
                        "t": 1700000001000,
                        "v": 200,
                    },
                ],
            }

            await _handle_tick(data)

            # Should be called twice
            assert mock_bus.update_tick.call_count == 2

            # Check first call
            first_call = mock_bus.update_tick.call_args_list[0][0][0]
            assert first_call["symbol"] == "EURUSD"
            assert first_call["bid"] == 1.0842

            # Check second call
            second_call = mock_bus.update_tick.call_args_list[1][0][0]
            assert second_call["symbol"] == "GBPJPY"
            assert second_call["bid"] == 185.50

    @pytest.mark.asyncio
    async def test_handle_tick_handles_invalid_timestamp(self) -> None:
        """Test that invalid timestamp formats are handled gracefully."""
        with patch("ingest.dependencies.LiveContextBus") as mock_bus_class:
            mock_bus = MagicMock()
            mock_bus_class.return_value = mock_bus

            data = {
                "type": "trade",
                "data": [
                    {
                        "p": 1.0842,
                        "s": "OANDA:EUR_USD",
                        "t": "invalid_timestamp",  # String instead of number
                        "v": 100,
                    }
                ],
            }

            await _handle_tick(data)

            # Should skip this tick
            mock_bus.update_tick.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_tick_handles_invalid_data_format(self) -> None:
        """Test that invalid data array format is handled gracefully."""
        with patch("ingest.dependencies.LiveContextBus") as mock_bus_class:
            mock_bus = MagicMock()
            mock_bus_class.return_value = mock_bus

            # data field is not a list
            data = {
                "type": "trade",
                "data": "not_a_list",
            }

            await _handle_tick(data)

            # Should handle gracefully without crashing
            mock_bus.update_tick.assert_not_called()


class TestCreateFinnhubWs:
    """Test create_finnhub_ws factory function."""

    @pytest.mark.asyncio
    async def test_factory_creates_instance_with_defaults(self) -> None:
        """Test factory creates FinnhubWebSocket with default symbols."""
        mock_redis = MagicMock()

        with patch("ingest.dependencies.FinnhubWebSocket") as mock_ws_class:
            await create_finnhub_ws(redis=mock_redis)

            # Verify FinnhubWebSocket was instantiated
            mock_ws_class.assert_called_once()

            # Verify arguments
            call_kwargs = mock_ws_class.call_args[1]
            assert call_kwargs["redis"] is mock_redis
            assert callable(call_kwargs["on_message"])
            assert "OANDA:EUR_USD" in call_kwargs["symbols"]
            assert "OANDA:XAU_USD" in call_kwargs["symbols"]

    @pytest.mark.asyncio
    async def test_factory_accepts_custom_symbols(self) -> None:
        """Test factory accepts custom symbol list."""
        mock_redis = MagicMock()
        custom_symbols = ["OANDA:USD_JPY", "OANDA:GBP_USD"]

        with patch("ingest.dependencies.FinnhubWebSocket") as mock_ws_class:
            await create_finnhub_ws(redis=mock_redis, symbols=custom_symbols)

            call_kwargs = mock_ws_class.call_args[1]
            assert call_kwargs["symbols"] == custom_symbols
