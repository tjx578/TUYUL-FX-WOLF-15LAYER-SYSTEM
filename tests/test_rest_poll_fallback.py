"""Tests for ingest.rest_poll_fallback – REST polling when WebSocket is down."""

import asyncio
from datetime import UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_singletons():  # pyright: ignore[reportUnusedFunction]
    """Reset singletons before each test."""
    from context.live_context_bus import LiveContextBus

    LiveContextBus.reset_singleton()
    yield


def _make_candle(symbol: str, timeframe: str, close: float, ts: float = 1700000000.0):
    from datetime import datetime

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "open": close - 0.001,
        "high": close + 0.001,
        "low": close - 0.002,
        "close": close,
        "volume": 100.0,
        "timestamp": datetime.fromtimestamp(ts, tz=UTC),
        "source": "rest_api",
    }


class TestRestPollFallback:
    """Unit tests for RestPollFallback scheduler."""

    @pytest.mark.asyncio
    async def test_does_not_poll_when_ws_connected(self):
        """When WS is connected, RestPollFallback should wait — never fetch."""
        with (
            patch("ingest.rest_poll_fallback.FinnhubCandleFetcher") as MockFetcher,  # noqa: N806
            patch("ingest.rest_poll_fallback.load_finnhub", return_value={}),
        ):
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch = AsyncMock(return_value=[])

            from ingest.rest_poll_fallback import RestPollFallback

            ws_connected = True
            poller = RestPollFallback(
                ws_connected_fn=lambda: ws_connected,
                symbols=["EURUSD"],
            )

            # Run for a short time — should just spin in _wait_for_ws_down
            task = asyncio.create_task(poller.run())
            await asyncio.sleep(0.1)
            await poller.stop()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            mock_fetcher.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_polls_when_ws_disconnected(self):
        """When WS is down, RestPollFallback should fetch M15 candles."""
        m15_candles = [_make_candle("EURUSD", "M15", 1.09, 1700000000 + i * 900) for i in range(4)]

        with (
            patch("ingest.rest_poll_fallback.FinnhubCandleFetcher") as MockFetcher,  # noqa: N806
            patch("ingest.rest_poll_fallback.load_finnhub", return_value={
                "rest_poll_fallback": {
                    "poll_interval_sec": 0.2,
                    "grace_before_poll_sec": 0.05,
                    "bars": 4,
                    "refresh_h1": False,
                }
            }),
        ):
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch = AsyncMock(return_value=m15_candles)

            from ingest.rest_poll_fallback import RestPollFallback

            poller = RestPollFallback(
                ws_connected_fn=lambda: False,  # WS always disconnected
                symbols=["EURUSD"],
            )

            task = asyncio.create_task(poller.run())
            # Let it run through grace + at least one poll cycle
            await asyncio.sleep(0.4)
            await poller.stop()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            # Should have called fetch at least once
            assert mock_fetcher.fetch.call_count >= 1
            call_args = mock_fetcher.fetch.call_args_list[0]
            assert call_args[0] == ("EURUSD", "M15", 4)

    @pytest.mark.asyncio
    async def test_stops_polling_when_ws_reconnects(self):
        """RestPollFallback should stop polling as soon as WS reconnects."""
        ws_connected = False

        with (
            patch("ingest.rest_poll_fallback.FinnhubCandleFetcher") as MockFetcher,  # noqa: N806
            patch("ingest.rest_poll_fallback.load_finnhub", return_value={
                "rest_poll_fallback": {
                    "poll_interval_sec": 0.2,
                    "grace_before_poll_sec": 0.05,
                    "bars": 4,
                    "refresh_h1": False,
                }
            }),
        ):
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch = AsyncMock(return_value=[])

            from ingest.rest_poll_fallback import RestPollFallback

            poller = RestPollFallback(
                ws_connected_fn=lambda: ws_connected,
                symbols=["EURUSD"],
            )

            task = asyncio.create_task(poller.run())

            # Let it start polling (WS down)
            await asyncio.sleep(0.3)
            initial_count = mock_fetcher.fetch.call_count

            # Simulate WS reconnection
            ws_connected = True
            await asyncio.sleep(0.3)
            reconnected_count = mock_fetcher.fetch.call_count

            await poller.stop()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            # After WS reconnected, no additional fetches should happen
            # (allow at most 1 extra call for the in-flight cycle)
            assert reconnected_count <= initial_count + 1

    @pytest.mark.asyncio
    async def test_grace_period_skips_poll_if_ws_returns(self):
        """If WS reconnects during grace period, polling should be skipped entirely."""
        reconnect_at = asyncio.get_event_loop().time() + 0.1

        def _ws_connected():
            return asyncio.get_event_loop().time() >= reconnect_at

        with (
            patch("ingest.rest_poll_fallback.FinnhubCandleFetcher") as MockFetcher,  # noqa: N806
            patch("ingest.rest_poll_fallback.load_finnhub", return_value={
                "rest_poll_fallback": {
                    "poll_interval_sec": 1.0,
                    "grace_before_poll_sec": 0.2,  # Grace longer than reconnect time
                    "bars": 4,
                    "refresh_h1": False,
                }
            }),
        ):
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch = AsyncMock(return_value=[])

            from ingest.rest_poll_fallback import RestPollFallback

            poller = RestPollFallback(
                ws_connected_fn=_ws_connected,
                symbols=["EURUSD"],
            )

            task = asyncio.create_task(poller.run())
            await asyncio.sleep(0.5)  # Enough time for grace + check
            await poller.stop()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            # WS came back during grace → no fetches performed
            mock_fetcher.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_h1_refresh_during_poll(self):
        """When refresh_h1=True, RestPollFallback should also fetch H1 candles."""
        m15_candles = [_make_candle("EURUSD", "M15", 1.09)]
        h1_candles = [_make_candle("EURUSD", "H1", 1.09)]

        def _fetch_side_effect(symbol: str, timeframe: str, bars: int) -> list[dict[str, Any]]:
            if timeframe == "M15":
                return m15_candles
            if timeframe == "H1":
                return h1_candles
            return []

        with (
            patch("ingest.rest_poll_fallback.FinnhubCandleFetcher") as MockFetcher,  # noqa: N806
            patch("ingest.rest_poll_fallback.load_finnhub", return_value={
                "rest_poll_fallback": {
                    "poll_interval_sec": 0.2,
                    "grace_before_poll_sec": 0.05,
                    "bars": 4,
                    "refresh_h1": True,
                    "h1_bars": 2,
                }
            }),
        ):
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch = AsyncMock(side_effect=_fetch_side_effect)
            mock_fetcher.aggregate_h4 = MagicMock(return_value=[])

            from ingest.rest_poll_fallback import RestPollFallback

            poller = RestPollFallback(
                ws_connected_fn=lambda: False,
                symbols=["EURUSD"],
            )

            task = asyncio.create_task(poller.run())
            await asyncio.sleep(0.4)
            await poller.stop()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            # Verify both M15 and H1 were fetched
            call_timeframes = [c[0][1] for c in mock_fetcher.fetch.call_args_list]
            assert "M15" in call_timeframes
            assert "H1" in call_timeframes

    @pytest.mark.asyncio
    async def test_fetch_error_does_not_crash_loop(self):
        """Fetch errors should be logged but not kill the polling loop."""
        from ingest.finnhub_candles import FinnhubCandleError

        call_count = 0

        async def _failing_fetch(symbol: str, timeframe: str, bars: int) -> list[dict[str, Any]]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise FinnhubCandleError("rate limited")
            return [_make_candle(symbol, timeframe, 1.09)]

        with (
            patch("ingest.rest_poll_fallback.FinnhubCandleFetcher") as MockFetcher,  # noqa: N806
            patch("ingest.rest_poll_fallback.load_finnhub", return_value={
                "rest_poll_fallback": {
                    "poll_interval_sec": 0.15,
                    "grace_before_poll_sec": 0.05,
                    "bars": 4,
                    "refresh_h1": False,
                }
            }),
        ):
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch = AsyncMock(side_effect=_failing_fetch)

            from ingest.rest_poll_fallback import RestPollFallback

            poller = RestPollFallback(
                ws_connected_fn=lambda: False,
                symbols=["EURUSD"],
            )

            task = asyncio.create_task(poller.run())
            await asyncio.sleep(0.6)
            await poller.stop()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            # Should have retried despite errors — at least 3 calls
            assert call_count >= 3


class TestFinnhubWebSocketIsConnected:
    """Verify the is_connected property on FinnhubWebSocket."""

    def test_initial_state_is_disconnected(self):
        """New FinnhubWebSocket should report is_connected = False."""
        import os
        os.environ.setdefault("FINNHUB_API_KEY", "test_key")

        with patch("ingest.finnhub_ws.Redis"):
            from ingest.finnhub_ws import FinnhubWebSocket

            mock_redis = MagicMock()
            ws = FinnhubWebSocket(
                redis=mock_redis,
                on_message=AsyncMock(),
                symbols=["OANDA:EUR_USD"],
            )
            assert ws.is_connected is False

    def test_connected_flag_set_after_connection(self):
        """Manually setting _connected should reflect in is_connected."""
        import os
        os.environ.setdefault("FINNHUB_API_KEY", "test_key")

        with patch("ingest.finnhub_ws.Redis"):
            from ingest.finnhub_ws import FinnhubWebSocket

            mock_redis = MagicMock()
            ws = FinnhubWebSocket(
                redis=mock_redis,
                on_message=AsyncMock(),
                symbols=["OANDA:EUR_USD"],
            )
            ws.is_connected = True
            assert ws.is_connected is True

            ws.is_connected = False
            assert ws.is_connected is False
