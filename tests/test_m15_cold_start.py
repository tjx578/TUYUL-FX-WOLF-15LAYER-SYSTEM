"""
Unit tests for M15 cold-start recovery.

Verifies that:
- cold_start_m15 fetches M15 bars from REST and seeds LiveContextBus
- H1RefreshScheduler detects cold symbols and triggers recovery
- M15 resolution mapping is correct
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ingest.finnhub_candles import FinnhubCandleFetcher


class TestM15ResolutionMap:
    """Verify M15 is in the Finnhub resolution map."""

    def test_m15_resolution_is_15(self) -> None:
        assert FinnhubCandleFetcher.RESOLUTION_MAP["M15"] == "15"


class TestColdStartM15:
    """Test FinnhubCandleFetcher.cold_start_m15."""

    @pytest.mark.asyncio
    @patch("ingest.finnhub_candles.CONFIG", {"pairs": {"symbols": ["EURUSD", "GBPUSD"]}})
    async def test_cold_start_seeds_context_bus(self) -> None:
        """cold_start_m15 fetches and seeds candles to LiveContextBus."""
        fetcher = FinnhubCandleFetcher()

        fake_candles = [
            {
                "symbol": "EURUSD",
                "timeframe": "M15",
                "open": 1.1000,
                "high": 1.1010,
                "low": 1.0990,
                "close": 1.1005,
                "volume": 50,
                "timestamp": datetime(2024, 1, 15, 10, 0, tzinfo=UTC),
            },
            {
                "symbol": "EURUSD",
                "timeframe": "M15",
                "open": 1.1005,
                "high": 1.1015,
                "low": 1.0995,
                "close": 1.1010,
                "volume": 60,
                "timestamp": datetime(2024, 1, 15, 10, 15, tzinfo=UTC),
            },
        ]

        fetcher.fetch = AsyncMock(return_value=fake_candles)
        mock_bus = MagicMock()
        fetcher.context_bus = mock_bus

        result = await fetcher.cold_start_m15(symbols=["EURUSD"], bars=50)

        assert result == {"EURUSD": 2}
        assert mock_bus.update_candle.call_count == 2
        fetcher.fetch.assert_called_once_with("EURUSD", "M15", 50)

    @pytest.mark.asyncio
    @patch("ingest.finnhub_candles.CONFIG", {"pairs": {"symbols": ["EURUSD"]}})
    async def test_cold_start_uses_all_symbols_by_default(self) -> None:
        """When no symbols are passed, cold_start_m15 uses CONFIG pairs."""
        fetcher = FinnhubCandleFetcher()
        fetcher.fetch = AsyncMock(return_value=[])
        fetcher.context_bus = MagicMock()

        await fetcher.cold_start_m15()

        fetcher.fetch.assert_called_once_with("EURUSD", "M15", 100)

    @pytest.mark.asyncio
    @patch("ingest.finnhub_candles.CONFIG", {"pairs": {"symbols": []}})
    async def test_cold_start_empty_symbols(self) -> None:
        """No symbols → empty result."""
        fetcher = FinnhubCandleFetcher()
        fetcher.context_bus = MagicMock()

        result = await fetcher.cold_start_m15()
        assert result == {}


class TestSchedulerM15ColdStartDetection:
    """Test H1RefreshScheduler._check_m15_cold_start."""

    @pytest.mark.asyncio
    @patch("ingest.h1_refresh_scheduler.FinnhubCandleFetcher")
    @patch("ingest.h1_refresh_scheduler.SystemStateManager")
    async def test_triggers_when_m15_bars_below_threshold(
        self, mock_state_class: MagicMock, mock_fetcher_class: MagicMock
    ) -> None:
        """Scheduler triggers cold_start_m15 for symbols with < min_bars M15 data."""
        from ingest.h1_refresh_scheduler import H1RefreshScheduler

        mock_state_inst = MagicMock()
        mock_state_inst.is_ready.return_value = True
        mock_state_class.return_value = mock_state_inst

        mock_fetcher_inst = MagicMock()
        mock_fetcher_inst.cold_start_m15 = AsyncMock(return_value={"EURUSD": 50})
        mock_fetcher_inst.fetch = AsyncMock(return_value=[])
        mock_fetcher_inst.aggregate_h4 = MagicMock(return_value=[])
        mock_fetcher_class.return_value = mock_fetcher_inst

        with patch("ingest.h1_refresh_scheduler.LiveContextBus") as mock_bus_class:
            mock_bus = MagicMock()
            # M15 bar count below threshold (10)
            mock_bus.get_warmup_bar_count.return_value = 3
            mock_bus.check_price_drift.return_value = {
                "drifted": False,
                "drift_pips": 0.0,
                "rest_close": None,
                "ws_mid": None,
            }
            mock_bus_class.return_value = mock_bus

            with patch(
                "ingest.h1_refresh_scheduler.load_finnhub",
                return_value={
                    "pairs": {"symbols": ["EURUSD"]},
                    "candles": {"refresh": {}},
                },
            ):
                scheduler = H1RefreshScheduler()
                await scheduler.refresh_all_symbols()

        mock_fetcher_inst.cold_start_m15.assert_called_once()
        call_args = mock_fetcher_inst.cold_start_m15.call_args
        assert "EURUSD" in call_args.kwargs.get("symbols", call_args.args[0] if call_args.args else [])

    @pytest.mark.asyncio
    @patch("ingest.h1_refresh_scheduler.FinnhubCandleFetcher")
    @patch("ingest.h1_refresh_scheduler.SystemStateManager")
    async def test_no_recovery_when_m15_sufficient(
        self, mock_state_class: MagicMock, mock_fetcher_class: MagicMock
    ) -> None:
        """No cold_start_m15 when M15 bars are above threshold."""
        from ingest.h1_refresh_scheduler import H1RefreshScheduler

        mock_state_inst = MagicMock()
        mock_state_inst.is_ready.return_value = True
        mock_state_class.return_value = mock_state_inst

        mock_fetcher_inst = MagicMock()
        mock_fetcher_inst.cold_start_m15 = AsyncMock(return_value={})
        mock_fetcher_inst.fetch = AsyncMock(return_value=[])
        mock_fetcher_inst.aggregate_h4 = MagicMock(return_value=[])
        mock_fetcher_class.return_value = mock_fetcher_inst

        with patch("ingest.h1_refresh_scheduler.LiveContextBus") as mock_bus_class:
            mock_bus = MagicMock()
            # M15 bar count above threshold
            mock_bus.get_warmup_bar_count.return_value = 50
            mock_bus.check_price_drift.return_value = {
                "drifted": False,
                "drift_pips": 0.0,
                "rest_close": None,
                "ws_mid": None,
            }
            mock_bus_class.return_value = mock_bus

            with patch(
                "ingest.h1_refresh_scheduler.load_finnhub",
                return_value={
                    "pairs": {"symbols": ["EURUSD"]},
                    "candles": {"refresh": {}},
                },
            ):
                scheduler = H1RefreshScheduler()
                await scheduler.refresh_all_symbols()

        mock_fetcher_inst.cold_start_m15.assert_not_called()
