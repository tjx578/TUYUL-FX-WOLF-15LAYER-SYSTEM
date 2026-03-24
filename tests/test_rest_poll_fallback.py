"""Tests for ingest.rest_poll_fallback – REST polling when WebSocket is down."""

import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset singletons and per-symbol tick tracking before each test."""
    from context.live_context_bus import LiveContextBus

    LiveContextBus.reset_singleton()

    # Seed _pair_last_tick_ts so that silence detector treats symbols as
    # recently active.  Tests that need specific silence behaviour can
    # override this via an explicit patch.
    from ingest.dependencies import _pair_last_tick_ts

    _pair_last_tick_ts.clear()
    yield
    _pair_last_tick_ts.clear()


def _make_candle(symbol: str, timeframe: str, close: float, ts: float = 1700000000.0):
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
        """When WS is connected and all pairs recently ticked, RestPollFallback should idle."""
        # Mark EURUSD as recently active so silence detector does not trigger
        from ingest.dependencies import _pair_last_tick_ts

        _pair_last_tick_ts["EURUSD"] = time.time()

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
            patch(
                "ingest.rest_poll_fallback.load_finnhub",
                return_value={
                    "rest_poll_fallback": {
                        "poll_interval_sec": 0.2,
                        "grace_before_poll_sec": 0.05,
                        "bars": 4,
                        "refresh_h1": False,
                    }
                },
            ),
            patch("ingest.rest_poll_fallback.is_forex_market_open", return_value=True),
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

        # Seed so silence detection does not re-trigger after reconnect
        from ingest.dependencies import _pair_last_tick_ts

        _pair_last_tick_ts["EURUSD"] = time.time()

        with (
            patch("ingest.rest_poll_fallback.FinnhubCandleFetcher") as MockFetcher,  # noqa: N806
            patch(
                "ingest.rest_poll_fallback.load_finnhub",
                return_value={
                    "rest_poll_fallback": {
                        "poll_interval_sec": 0.2,
                        "grace_before_poll_sec": 0.05,
                        "bars": 4,
                        "refresh_h1": False,
                    }
                },
            ),
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

        # Mark EURUSD as recently active so post-reconnect silence check is inert
        from ingest.dependencies import _pair_last_tick_ts

        _pair_last_tick_ts["EURUSD"] = time.time()

        with (
            patch("ingest.rest_poll_fallback.FinnhubCandleFetcher") as MockFetcher,  # noqa: N806
            patch(
                "ingest.rest_poll_fallback.load_finnhub",
                return_value={
                    "rest_poll_fallback": {
                        "poll_interval_sec": 1.0,
                        "grace_before_poll_sec": 0.2,  # Grace longer than reconnect time
                        "bars": 4,
                        "refresh_h1": False,
                    }
                },
            ),
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
            patch(
                "ingest.rest_poll_fallback.load_finnhub",
                return_value={
                    "rest_poll_fallback": {
                        "poll_interval_sec": 0.2,
                        "grace_before_poll_sec": 0.05,
                        "bars": 4,
                        "refresh_h1": True,
                        "h1_bars": 2,
                    }
                },
            ),
            patch("ingest.rest_poll_fallback.is_forex_market_open", return_value=True),
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
            patch(
                "ingest.rest_poll_fallback.load_finnhub",
                return_value={
                    "rest_poll_fallback": {
                        "poll_interval_sec": 0.15,
                        "grace_before_poll_sec": 0.05,
                        "bars": 4,
                        "refresh_h1": False,
                    }
                },
            ),
            patch("ingest.rest_poll_fallback.is_forex_market_open", return_value=True),
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


def _make_raw_finnhub_candle(close: float, ts: float = 1700000000.0) -> dict[str, Any]:
    """Candle dict as returned by FinnhubCandleFetcher.fetch() — no symbol/timeframe fields."""
    return {
        "open": close - 0.001,
        "high": close + 0.001,
        "low": close - 0.002,
        "close": close,
        "volume": 100.0,
        "timestamp": datetime.fromtimestamp(ts, tz=UTC),
        "source": "rest_api",
    }


class TestNormalizeCandles:
    """Unit tests for RestPollFallback._normalize_candles()."""

    def _make_poller(self):
        with patch("ingest.rest_poll_fallback.FinnhubCandleFetcher"), patch(
            "ingest.rest_poll_fallback.load_finnhub", return_value={}
        ):
            from ingest.rest_poll_fallback import RestPollFallback

            return RestPollFallback(ws_connected_fn=lambda: True, symbols=["EURUSD"])

    def test_injects_symbol_and_timeframe_when_missing(self):
        """Raw Finnhub candles (no symbol/timeframe) should get both fields injected."""
        poller = self._make_poller()
        raw = [_make_raw_finnhub_candle(1.09), _make_raw_finnhub_candle(1.10)]

        result = poller._normalize_candles(raw, "EURUSD", "M15")

        assert len(result) == 2
        for candle in result:
            assert candle["symbol"] == "EURUSD"
            assert candle["timeframe"] == "M15"

    def test_preserves_existing_symbol_and_timeframe(self):
        """Candles that already have symbol/timeframe should not be overwritten."""
        poller = self._make_poller()
        candle = _make_raw_finnhub_candle(1.09)
        candle["symbol"] = "XAUUSD"
        candle["timeframe"] = "H1"

        result = poller._normalize_candles([candle], "EURUSD", "M15")

        assert result[0]["symbol"] == "XAUUSD"
        assert result[0]["timeframe"] == "H1"

    def test_does_not_mutate_original_candle_dicts(self):
        """_normalize_candles should perform shallow copies — originals unchanged."""
        poller = self._make_poller()
        raw = [_make_raw_finnhub_candle(1.09)]
        original_keys = set(raw[0].keys())

        poller._normalize_candles(raw, "EURUSD", "M15")

        assert set(raw[0].keys()) == original_keys
        assert "symbol" not in raw[0]
        assert "timeframe" not in raw[0]

    def test_empty_list_returns_empty(self):
        """Empty input should produce empty output."""
        poller = self._make_poller()
        assert poller._normalize_candles([], "EURUSD", "M15") == []

    def test_normalize_applied_for_h4_timeframe(self):
        """H4 candles returned by aggregate_h4 should also be normalized."""
        poller = self._make_poller()
        raw = [_make_raw_finnhub_candle(1.09)]
        result = poller._normalize_candles(raw, "GBPUSD", "H4")
        assert result[0]["symbol"] == "GBPUSD"
        assert result[0]["timeframe"] == "H4"


class TestPushCandlesToRedis:
    """Tests for RestPollFallback._push_candles_to_redis()."""

    def _make_poller_with_redis(self, redis_mock):
        with patch("ingest.rest_poll_fallback.FinnhubCandleFetcher"), patch(
            "ingest.rest_poll_fallback.load_finnhub", return_value={}
        ):
            from ingest.rest_poll_fallback import RestPollFallback

            return RestPollFallback(
                ws_connected_fn=lambda: True,
                symbols=["EURUSD"],
                redis_client=redis_mock,
            )

    @pytest.mark.asyncio
    async def test_writes_normalized_candles_to_redis(self):
        """Candles with symbol+timeframe should be RPUSH'd to the correct Redis key."""
        redis_mock = AsyncMock()
        poller = self._make_poller_with_redis(redis_mock)

        candles = [_make_candle("EURUSD", "M15", 1.09)]
        with patch("ingest.rest_poll_fallback.enqueue_candle_dict"):
            await poller._push_candles_to_redis(candles)

        assert redis_mock.rpush.call_count == 1
        call_args = redis_mock.rpush.call_args[0]
        assert "wolf15:candle_history:EURUSD:M15" in call_args[0]

    @pytest.mark.asyncio
    async def test_publishes_to_pubsub_channel_on_write(self):
        """Each successfully written candle should be published to the candle pub/sub channel."""
        redis_mock = AsyncMock()
        poller = self._make_poller_with_redis(redis_mock)

        candles = [_make_candle("EURUSD", "M15", 1.09)]
        with patch("ingest.rest_poll_fallback.enqueue_candle_dict"):
            await poller._push_candles_to_redis(candles)

        assert redis_mock.publish.call_count == 1
        pub_call = redis_mock.publish.call_args[0]
        assert "candle:EURUSD:M15" in pub_call[0]

    @pytest.mark.asyncio
    async def test_skips_candles_missing_symbol(self):
        """Candles without symbol/timeframe should be skipped — no Redis write occurs."""
        redis_mock = AsyncMock()
        poller = self._make_poller_with_redis(redis_mock)

        # Candle without symbol/timeframe (raw Finnhub dict, un-normalized)
        raw_candle = _make_raw_finnhub_candle(1.09)
        await poller._push_candles_to_redis([raw_candle])

        # Should not write to Redis
        redis_mock.rpush.assert_not_called()
        # Skip counter should be zero (redis IS available; this is a key-miss skip)
        # but redis_writes should also be zero
        assert poller._redis_writes == 0

    @pytest.mark.asyncio
    async def test_increments_redis_writes_counter(self):
        """_redis_writes counter should track successful writes."""
        redis_mock = AsyncMock()
        poller = self._make_poller_with_redis(redis_mock)

        assert poller._redis_writes == 0
        candles = [
            _make_candle("EURUSD", "M15", 1.09),
            _make_candle("EURUSD", "M15", 1.10),
        ]
        with patch("ingest.rest_poll_fallback.enqueue_candle_dict"):
            await poller._push_candles_to_redis(candles)

        assert poller._redis_writes == 2

    @pytest.mark.asyncio
    async def test_increments_redis_skips_counter_when_no_client(self):
        """_redis_skips counter should track skips when redis_client is None."""
        with patch("ingest.rest_poll_fallback.FinnhubCandleFetcher"), patch(
            "ingest.rest_poll_fallback.load_finnhub", return_value={}
        ):
            from ingest.rest_poll_fallback import RestPollFallback

            poller = RestPollFallback(
                ws_connected_fn=lambda: True,
                symbols=["EURUSD"],
                redis_client=None,
            )

        candles = [_make_candle("EURUSD", "M15", 1.09)]
        await poller._push_candles_to_redis(candles)
        assert poller._redis_skips == 1

    @pytest.mark.asyncio
    async def test_end_to_end_raw_candles_written_after_poll_symbol(self):
        """End-to-end: _poll_symbol should normalize and write raw Finnhub candles to Redis."""
        redis_mock = AsyncMock()

        # Simulate raw Finnhub candles (no symbol/timeframe)
        raw_candles = [_make_raw_finnhub_candle(1.09 + i * 0.001) for i in range(4)]

        with (
            patch("ingest.rest_poll_fallback.FinnhubCandleFetcher") as MockFetcher,
            patch("ingest.rest_poll_fallback.load_finnhub", return_value={}),
            patch("ingest.rest_poll_fallback.enqueue_candle_dict"),
            # Guard inside _poll_symbol imports from ingest.finnhub_key_manager at call time
            patch("ingest.finnhub_key_manager.finnhub_keys") as mock_keys,
        ):
            mock_keys.status.return_value = []
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch = AsyncMock(return_value=raw_candles)
            mock_fetcher.aggregate_h4 = MagicMock(return_value=[])

            from ingest.rest_poll_fallback import RestPollFallback

            poller = RestPollFallback(
                ws_connected_fn=lambda: True,
                symbols=["EURUSD"],
                redis_client=redis_mock,
            )
            poller._refresh_h1 = False

            await poller._poll_symbol("EURUSD")

        # All 4 raw candles are batched into a single rpush call (one per unique key)
        assert redis_mock.rpush.call_count == 1
        rpush_call = redis_mock.rpush.call_args
        assert len(rpush_call.args) == 5  # key + 4 serialized candle values
        # Each candle still published individually to pub/sub
        assert redis_mock.publish.call_count == 4


class TestGetSilentPairs:
    """Tests for RestPollFallback._get_silent_pairs()."""

    def _make_poller(self):
        with patch("ingest.rest_poll_fallback.FinnhubCandleFetcher"), patch(
            "ingest.rest_poll_fallback.load_finnhub", return_value={}
        ):
            from ingest.rest_poll_fallback import RestPollFallback

            return RestPollFallback(
                ws_connected_fn=lambda: True,
                symbols=["EURUSD", "GBPUSD", "XAUUSD"],
            )

    def test_all_symbols_silent_when_never_ticked(self):
        """All symbols should be silent if they have never received a WS tick."""
        from ingest.dependencies import _pair_last_tick_ts

        _pair_last_tick_ts.clear()
        poller = self._make_poller()
        silent = poller._get_silent_pairs()
        assert set(silent) == {"EURUSD", "GBPUSD", "XAUUSD"}

    def test_recently_ticked_symbol_not_silent(self):
        """A symbol that ticked recently should not appear in silent list."""
        from ingest.dependencies import _pair_last_tick_ts

        _pair_last_tick_ts.clear()
        _pair_last_tick_ts["EURUSD"] = time.time()  # just ticked

        poller = self._make_poller()
        silent = poller._get_silent_pairs()
        assert "EURUSD" not in silent
        assert "GBPUSD" in silent
        assert "XAUUSD" in silent

    def test_stale_tick_symbol_is_silent(self):
        """A symbol whose last tick is older than the threshold should be silent."""
        from ingest.dependencies import PAIR_WS_SILENCE_THRESHOLD_S, _pair_last_tick_ts

        _pair_last_tick_ts.clear()
        # Simulate a tick that happened beyond the threshold
        _pair_last_tick_ts["EURUSD"] = time.time() - PAIR_WS_SILENCE_THRESHOLD_S - 10

        poller = self._make_poller()
        silent = poller._get_silent_pairs()
        assert "EURUSD" in silent

    def test_no_silent_pairs_when_all_recently_ticked(self):
        """No pairs should be silent when all have received recent ticks."""
        from ingest.dependencies import _pair_last_tick_ts

        now = time.time()
        _pair_last_tick_ts["EURUSD"] = now
        _pair_last_tick_ts["GBPUSD"] = now
        _pair_last_tick_ts["XAUUSD"] = now

        poller = self._make_poller()
        assert poller._get_silent_pairs() == []


class TestHybridSilenceMode:
    """Tests for the per-symbol silence polling path (WS connected but pairs silent)."""

    @pytest.mark.asyncio
    async def test_polls_silent_pairs_when_ws_connected(self):
        """When WS is up but specific pairs are silent, only those pairs should be polled."""
        from ingest.dependencies import PAIR_WS_SILENCE_THRESHOLD_S, _pair_last_tick_ts

        # EURUSD recently ticked, GBPUSD never ticked (silent — timestamp far in the past)
        _pair_last_tick_ts["EURUSD"] = time.time()
        _pair_last_tick_ts["GBPUSD"] = time.time() - PAIR_WS_SILENCE_THRESHOLD_S - 10

        polled_symbols: list[str] = []

        with (
            patch("ingest.rest_poll_fallback.FinnhubCandleFetcher") as MockFetcher,
            patch(
                "ingest.rest_poll_fallback.load_finnhub",
                return_value={
                    "rest_poll_fallback": {
                        "silence_check_interval_sec": 0.05,
                        "poll_interval_sec": 1.0,
                        "grace_before_poll_sec": 0.05,
                        "refresh_h1": False,
                    }
                },
            ),
            patch("ingest.rest_poll_fallback.is_forex_market_open", return_value=True),
        ):
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch = AsyncMock(return_value=[])

            from ingest.rest_poll_fallback import RestPollFallback

            original_poll_symbol = RestPollFallback._poll_symbol

            async def _tracking_poll(self_inner, symbol):
                polled_symbols.append(symbol)
                await original_poll_symbol(self_inner, symbol)

            poller = RestPollFallback(
                ws_connected_fn=lambda: True,  # WS is UP
                symbols=["EURUSD", "GBPUSD"],
            )

            with patch.object(RestPollFallback, "_poll_symbol", _tracking_poll):
                task = asyncio.create_task(poller.run())
                await asyncio.sleep(0.3)
                await poller.stop()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

        # Only GBPUSD should have been polled (EURUSD was recently active)
        assert "GBPUSD" in polled_symbols
        assert "EURUSD" not in polled_symbols

    @pytest.mark.asyncio
    async def test_does_not_poll_when_forex_market_closed(self):
        """Silent pairs should not be polled when forex market is closed."""
        from ingest.dependencies import _pair_last_tick_ts

        _pair_last_tick_ts.clear()  # all symbols silent

        with (
            patch("ingest.rest_poll_fallback.FinnhubCandleFetcher") as MockFetcher,
            patch(
                "ingest.rest_poll_fallback.load_finnhub",
                return_value={
                    "rest_poll_fallback": {
                        "silence_check_interval_sec": 0.05,
                        "poll_interval_sec": 1.0,
                        "grace_before_poll_sec": 0.05,
                        "refresh_h1": False,
                    }
                },
            ),
            patch("ingest.rest_poll_fallback.is_forex_market_open", return_value=False),
        ):
            mock_fetcher = MockFetcher.return_value
            mock_fetcher.fetch = AsyncMock(return_value=[])

            from ingest.rest_poll_fallback import RestPollFallback

            poller = RestPollFallback(
                ws_connected_fn=lambda: True,
                symbols=["EURUSD"],
            )

            task = asyncio.create_task(poller.run())
            await asyncio.sleep(0.2)
            await poller.stop()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        # No fetches despite silence — market is closed
        mock_fetcher.fetch.assert_not_called()


class TestFinnhubWebSocketIsConnected:
    """Verify the is_connected property on FinnhubWebSocket."""

    def _make_ws(self):
        """Helper: create a FinnhubWebSocket with key manager mocked."""
        from ingest.finnhub_ws import FinnhubWebSocket

        mock_keys = MagicMock()
        mock_keys.current_key.return_value = "test_key"

        with patch("ingest.finnhub_key_manager.finnhub_keys", mock_keys), patch("ingest.finnhub_ws.Redis"):
            ws = FinnhubWebSocket(
                redis=MagicMock(),
                on_message=AsyncMock(),
                symbols=["OANDA:EUR_USD"],
            )
        return ws

    def test_initial_state_is_disconnected(self):
        """New FinnhubWebSocket should report is_connected = False."""
        ws = self._make_ws()
        assert ws.is_connected is False

    def test_connected_flag_set_after_connection(self):
        """Manually setting _connected should reflect in is_connected."""
        ws = self._make_ws()
        ws.is_connected = True
        assert ws.is_connected is True

        ws.is_connected = False
        assert ws.is_connected is False


class TestIsForexMarketOpen:
    """Tests for the is_forex_market_open helper in finnhub_ws."""

    @pytest.mark.parametrize(
        "dow,hour,expected",
        [
            # Monday–Thursday: always open
            (0, 0, True),  # Mon 00:00
            (0, 12, True),  # Mon 12:00
            (1, 23, True),  # Tue 23:00
            (3, 5, True),  # Thu 05:00
            # Friday: open until 22:00
            (4, 0, True),  # Fri 00:00
            (4, 21, True),  # Fri 21:00
            (4, 22, False),  # Fri 22:00 — closed
            (4, 23, False),  # Fri 23:00 — closed
            # Saturday: always closed
            (5, 0, False),
            (5, 12, False),
            (5, 23, False),
            # Sunday: closed until 22:00
            (6, 0, False),  # Sun 00:00
            (6, 21, False),  # Sun 21:00
            (6, 22, True),  # Sun 22:00 — open
            (6, 23, True),  # Sun 23:00 — open
        ],
    )
    def test_market_hours(self, dow: int, hour: int, expected: bool):
        from datetime import datetime

        from ingest.finnhub_ws import is_forex_market_open

        # Build a datetime for the given weekday/hour.
        # 2026-01-05 is a Monday (weekday=0).
        base_monday = datetime(2026, 1, 5, tzinfo=UTC)
        dt = base_monday.replace(day=5 + dow, hour=hour, minute=0, second=0)
        assert dt.weekday() == dow
        assert is_forex_market_open(dt) is expected
