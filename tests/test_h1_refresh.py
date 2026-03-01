"""
Unit tests for H1RefreshScheduler.

Tests periodic refresh, H4 re-aggregation, and price drift detection.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context.system_state import SystemState, SystemStateManager
from ingest.h1_refresh_scheduler import H1RefreshScheduler


class TestPeriodicRefresh:
    """Test periodic refresh functionality."""

    @pytest.mark.asyncio
    @patch("ingest.h1_refresh_scheduler.FinnhubCandleFetcher")
    @patch("ingest.h1_refresh_scheduler.SystemStateManager")
    async def test_refresh_fetches_h1_and_aggregates_h4(
        self, mock_state_manager: MagicMock, mock_fetcher_class: MagicMock
    ) -> None:
        """Test refresh fetches H1 and re-aggregates H4."""
        # Mock system state to be ready
        mock_state_instance = MagicMock()
        mock_state_instance.is_ready.return_value = True
        mock_state_manager.return_value = mock_state_instance

        # Mock fetcher
        mock_fetcher_instance = MagicMock()
        h1_test_candles = [
            {
                "symbol": "EURUSD",
                "timeframe": "H1",
                "open": 1.1000,
                "high": 1.1010,
                "low": 1.0990,
                "close": 1.1005,
                "volume": 100,
                "timestamp": datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
            }
        ]
        h4_test_candles = [
            {
                "symbol": "EURUSD",
                "timeframe": "H4",
                "open": 1.1000,
                "high": 1.1010,
                "low": 1.0990,
                "close": 1.1005,
                "volume": 100,
                "timestamp": datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
            }
        ]

        mock_fetcher_instance.fetch = AsyncMock(return_value=h1_test_candles)
        mock_fetcher_instance._aggregate_h4 = MagicMock(return_value=h4_test_candles)
        mock_fetcher_class.return_value = mock_fetcher_instance

        # Mock context bus
        with patch("ingest.h1_refresh_scheduler.LiveContextBus") as mock_bus_class:
            mock_bus = MagicMock()
            mock_bus.check_price_drift.return_value = {
                "drifted": False,
                "drift_pips": 5.0,
                "rest_close": 1.1005,
                "ws_mid": 1.10055,
            }
            mock_bus_class.return_value = mock_bus

            # Mock CONFIG
            with patch("ingest.h1_refresh_scheduler.CONFIG", {
                "pairs": {"symbols": ["EURUSD"]}
            }):
                scheduler = H1RefreshScheduler()
                await scheduler.refresh_all_symbols()

        # Verify fetch was called
        mock_fetcher_instance.fetch.assert_called()

        # Verify H4 aggregation was called
        mock_fetcher_instance._aggregate_h4.assert_called_with(h1_test_candles)

        # Verify context bus update_candle was called
        assert mock_bus.update_candle.called


class TestPriceDriftDetection:
    """Test price drift detection and degradation."""

    @pytest.mark.asyncio
    @patch("ingest.h1_refresh_scheduler.FinnhubCandleFetcher")
    @patch("ingest.h1_refresh_scheduler.SystemStateManager")
    async def test_drift_exceeds_threshold_marks_degraded(
        self, mock_state_manager: MagicMock, mock_fetcher_class: MagicMock
    ) -> None:
        """Test drift > threshold marks symbol as DEGRADED."""
        # Mock system state
        mock_state_instance = MagicMock()
        mock_state_instance.is_ready.return_value = True
        mock_state_manager.return_value = mock_state_instance

        # Mock fetcher
        mock_fetcher_instance = MagicMock()
        h1_test_candles = [
            {
                "symbol": "EURUSD",
                "timeframe": "H1",
                "open": 1.1000,
                "high": 1.1010,
                "low": 1.0990,
                "close": 1.1005,
                "volume": 100,
                "timestamp": datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
            }
        ]

        mock_fetcher_instance.fetch = AsyncMock(return_value=h1_test_candles)
        mock_fetcher_instance._aggregate_h4 = MagicMock(return_value=[])
        mock_fetcher_class.return_value = mock_fetcher_instance

        # Mock context bus with HIGH drift
        with patch("ingest.h1_refresh_scheduler.LiveContextBus") as mock_bus_class:
            mock_bus = MagicMock()
            mock_bus.check_price_drift.return_value = {
                "drifted": True,
                "drift_pips": 75.0,  # Exceeds threshold
                "rest_close": 1.1005,
                "ws_mid": 1.09975,
            }
            mock_bus_class.return_value = mock_bus

            with patch("ingest.h1_refresh_scheduler.CONFIG", {
                "pairs": {"symbols": ["EURUSD"]}
            }):
                scheduler = H1RefreshScheduler()
                await scheduler.refresh_all_symbols()

        # Verify mark_symbol_degraded was called
        mock_state_instance.mark_symbol_degraded.assert_called()

    @pytest.mark.asyncio
    @patch("ingest.h1_refresh_scheduler.FinnhubCandleFetcher")
    @patch("ingest.h1_refresh_scheduler.SystemStateManager")
    async def test_drift_within_tolerance_keeps_ready(
        self, mock_state_manager: MagicMock, mock_fetcher_class: MagicMock
    ) -> None:
        """Test drift within tolerance keeps symbol READY."""
        # Mock system state
        mock_state_instance = MagicMock()
        mock_state_instance.is_ready.return_value = True
        mock_state_manager.return_value = mock_state_instance

        # Mock fetcher
        mock_fetcher_instance = MagicMock()
        h1_test_candles = [
            {
                "symbol": "EURUSD",
                "timeframe": "H1",
                "open": 1.1000,
                "high": 1.1010,
                "low": 1.0990,
                "close": 1.1005,
                "volume": 100,
                "timestamp": datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
            }
        ]

        mock_fetcher_instance.fetch = AsyncMock(return_value=h1_test_candles)
        mock_fetcher_instance._aggregate_h4 = MagicMock(return_value=[])
        mock_fetcher_class.return_value = mock_fetcher_instance

        # Mock context bus with LOW drift
        with patch("ingest.h1_refresh_scheduler.LiveContextBus") as mock_bus_class:
            mock_bus = MagicMock()
            mock_bus.check_price_drift.return_value = {
                "drifted": False,
                "drift_pips": 5.0,  # Within threshold
                "rest_close": 1.1005,
                "ws_mid": 1.10055,
            }
            mock_bus_class.return_value = mock_bus

            with patch("ingest.h1_refresh_scheduler.CONFIG", {
                "pairs": {"symbols": ["EURUSD"]}
            }):
                scheduler = H1RefreshScheduler()
                await scheduler.refresh_all_symbols()

        # Verify mark_symbol_recovered was called
        mock_state_instance.mark_symbol_recovered.assert_called()


class TestRefreshConfiguration:
    """Test refresh configuration."""

    def test_default_interval(self) -> None:
        """Test default refresh interval is 3600 seconds."""
        with patch("ingest.h1_refresh_scheduler.load_finnhub") as mock_load:
            mock_load.return_value = {
                "candles": {
                    "refresh": {}
                }
            }
            scheduler = H1RefreshScheduler()
            assert scheduler.interval_sec == 3600

    def test_custom_interval(self) -> None:
        """Test custom refresh interval from config."""
        with patch("ingest.h1_refresh_scheduler.load_finnhub") as mock_load:
            mock_load.return_value = {
                "candles": {
                    "refresh": {
                        "h1_interval_sec": 1800
                    }
                }
            }
            scheduler = H1RefreshScheduler()
            assert scheduler.interval_sec == 1800

    def test_default_h1_bars(self) -> None:
        """Test default H1 bars to fetch is 5."""
        with patch("ingest.h1_refresh_scheduler.load_finnhub") as mock_load:
            mock_load.return_value = {
                "candles": {
                    "refresh": {}
                }
            }
            scheduler = H1RefreshScheduler()
            assert scheduler.h1_bars == 5

    def test_custom_max_drift(self) -> None:
        """Test custom max drift from config."""
        with patch("ingest.h1_refresh_scheduler.load_finnhub") as mock_load:
            mock_load.return_value = {
                "candles": {
                    "refresh": {
                        "price_drift_max_pips": 100.0
                    }
                }
            }
            scheduler = H1RefreshScheduler()
            assert scheduler.max_drift_pips == 100.0
