"""
Unit tests for HTFRefreshScheduler — periodic D1/W1 candle refresh.

Tests periodic refresh, Redis RPUSH + PUBLISH, and error handling.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ingest.htf_refresh_scheduler import HTFRefreshScheduler


def _d1_candle(symbol: str = "EURUSD") -> dict:
    return {
        "symbol": symbol,
        "timeframe": "D1",
        "open": 1.1000,
        "high": 1.1050,
        "low": 1.0950,
        "close": 1.1020,
        "volume": 5000,
        "timestamp": datetime(2026, 3, 19, 0, 0, 0, tzinfo=UTC).timestamp(),
    }


def _w1_candle(symbol: str = "EURUSD") -> dict:
    return {
        "symbol": symbol,
        "timeframe": "W1",
        "open": 1.0900,
        "high": 1.1100,
        "low": 1.0850,
        "close": 1.1050,
        "volume": 25000,
        "timestamp": datetime(2026, 3, 15, 22, 0, 0, tzinfo=UTC).timestamp(),
    }


@pytest.fixture
def _patch_deps():
    """Patch external deps for HTFRefreshScheduler."""
    with (
        patch("ingest.htf_refresh_scheduler.FinnhubCandleFetcher") as mock_fetcher_cls,
        patch("ingest.htf_refresh_scheduler.SystemStateManager") as mock_ssm_cls,
        patch("ingest.htf_refresh_scheduler.LiveContextBus") as mock_bus_cls,
        patch(
            "ingest.htf_refresh_scheduler.load_finnhub",
            return_value={
                "candles": {"refresh": {"htf_interval_sec": 14400, "d1_bars": 10, "w1_bars": 8}},
            },
        ),
        patch("ingest.htf_refresh_scheduler.get_enabled_symbols", return_value=["EURUSD", "EURNZD"]),
    ):
        mock_fetcher = MagicMock()
        mock_fetcher_cls.return_value = mock_fetcher
        mock_ssm = MagicMock()
        mock_ssm.is_ready.return_value = True
        mock_ssm_cls.return_value = mock_ssm
        mock_bus = MagicMock()
        mock_bus_cls.return_value = mock_bus

        yield {
            "fetcher": mock_fetcher,
            "bus": mock_bus,
            "ssm": mock_ssm,
        }


class TestHTFRefreshScheduler:
    """Tests for D1/W1 periodic refresh."""

    @pytest.mark.asyncio
    async def test_refresh_fetches_d1_and_w1(self, _patch_deps: dict) -> None:
        """Refresh cycle fetches D1 and W1 for all enabled symbols."""
        fetcher = _patch_deps["fetcher"]
        fetcher.fetch = AsyncMock(
            side_effect=lambda sym, tf, bars: [_d1_candle(sym)] if tf == "D1" else [_w1_candle(sym)]
        )

        scheduler = HTFRefreshScheduler()
        await scheduler.refresh_all_symbols()

        # Should fetch D1 + W1 for each of 2 symbols = 4 calls
        assert fetcher.fetch.call_count == 4
        tfs_called = {call.args[1] for call in fetcher.fetch.call_args_list}
        assert tfs_called == {"D1", "W1"}

    @pytest.mark.asyncio
    async def test_context_bus_updated(self, _patch_deps: dict) -> None:
        """Refreshed candles are pushed to LiveContextBus."""
        fetcher = _patch_deps["fetcher"]
        bus = _patch_deps["bus"]
        fetcher.fetch = AsyncMock(
            side_effect=lambda sym, tf, bars: [_d1_candle(sym)] if tf == "D1" else [_w1_candle(sym)]
        )

        scheduler = HTFRefreshScheduler()
        await scheduler.refresh_all_symbols()

        # 2 symbols × (1 D1 + 1 W1) = 4 update_candle calls
        assert bus.update_candle.call_count == 4

    @pytest.mark.asyncio
    async def test_redis_rpush_and_publish(self, _patch_deps: dict) -> None:
        """Candles are RPUSH'd and PUBLISH'd to Redis."""
        fetcher = _patch_deps["fetcher"]
        fetcher.fetch = AsyncMock(return_value=[_d1_candle("EURUSD")])

        mock_redis = AsyncMock()
        with patch("ingest.htf_refresh_scheduler.enqueue_candle_dict"):
            scheduler = HTFRefreshScheduler(redis_client=mock_redis)
            await scheduler._push_candles_to_redis([_d1_candle("EURUSD")])

        mock_redis.rpush.assert_called_once()
        mock_redis.ltrim.assert_called_once()
        mock_redis.publish.assert_called_once()
        # Verify the pub/sub channel format
        pub_call = mock_redis.publish.call_args
        assert pub_call.args[0] == "candle:EURUSD:D1"

    @pytest.mark.asyncio
    async def test_no_redis_skips_push(self, _patch_deps: dict) -> None:
        """When redis_client is None, push is silently skipped."""
        fetcher = _patch_deps["fetcher"]
        fetcher.fetch = AsyncMock(return_value=[_d1_candle()])

        scheduler = HTFRefreshScheduler(redis_client=None)
        # Should not raise
        await scheduler._push_candles_to_redis([_d1_candle()])

    @pytest.mark.asyncio
    async def test_empty_fetch_logged_not_crashed(self, _patch_deps: dict) -> None:
        """Empty fetch result is handled gracefully."""
        fetcher = _patch_deps["fetcher"]
        fetcher.fetch = AsyncMock(return_value=[])

        scheduler = HTFRefreshScheduler()
        await scheduler.refresh_all_symbols()  # should not raise

    @pytest.mark.asyncio
    async def test_single_symbol_error_does_not_block_others(self, _patch_deps: dict) -> None:
        """If one symbol fails, others still get refreshed."""
        fetcher = _patch_deps["fetcher"]
        call_count = {"n": 0}

        async def _flaky_fetch(sym: str, tf: str, bars: int) -> list:
            call_count["n"] += 1
            if sym == "EURUSD" and tf == "D1":
                raise RuntimeError("API timeout")
            return [_d1_candle(sym)] if tf == "D1" else [_w1_candle(sym)]

        fetcher.fetch = AsyncMock(side_effect=_flaky_fetch)

        scheduler = HTFRefreshScheduler()
        await scheduler.refresh_all_symbols()  # should not raise

        # At least EURNZD calls should have succeeded
        bus = _patch_deps["bus"]
        assert bus.update_candle.call_count >= 2

    @pytest.mark.asyncio
    async def test_config_defaults_applied(self, _patch_deps: dict) -> None:
        """Verify default config values are sane."""
        scheduler = HTFRefreshScheduler()
        assert scheduler.interval_sec == 14400
        assert scheduler.d1_bars == 10
        assert scheduler.w1_bars == 8
