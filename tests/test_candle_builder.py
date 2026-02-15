"""
Tests for CandleBuilder — M15/H1 tick-built, H4+ REST-fetched.
"""

from unittest.mock import MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]

from analysis.candle_builder import (
    CandleManager,
    RESTCandleFetcher,
    Tick,
    TickCandleBuilder,
    Timeframe,
)

# ---------------------------------------------------------------------------
# Timeframe classification
# ---------------------------------------------------------------------------

class TestTimeframe:
    def test_tick_built_timeframes(self):
        assert Timeframe.M15.is_tick_built is True
        assert Timeframe.H1.is_tick_built is True
        assert Timeframe.H4.is_tick_built is False
        assert Timeframe.D1.is_tick_built is False

    def test_rest_fetched_timeframes(self):
        assert Timeframe.H4.is_rest_fetched is True
        assert Timeframe.D1.is_rest_fetched is True
        assert Timeframe.W1.is_rest_fetched is True
        assert Timeframe.MN.is_rest_fetched is True
        assert Timeframe.M15.is_rest_fetched is False
        assert Timeframe.H1.is_rest_fetched is False

    def test_seconds(self):
        assert Timeframe.M15.seconds == 900
        assert Timeframe.H1.seconds == 3600
        assert Timeframe.H4.seconds == 14400

    def test_finnhub_resolution(self):
        assert Timeframe.M15.finnhub_resolution == "15"
        assert Timeframe.H1.finnhub_resolution == "60"
        assert Timeframe.H4.finnhub_resolution == "240"
        assert Timeframe.D1.finnhub_resolution == "D"
        assert Timeframe.W1.finnhub_resolution == "W"
        assert Timeframe.MN.finnhub_resolution == "M"


# ---------------------------------------------------------------------------
# TickCandleBuilder — M15
# ---------------------------------------------------------------------------

class TestTickCandleBuilderM15:
    SYMBOL = "OANDA:EUR_USD"

    def _make_tick(self, price: float, ts: float, vol: float = 1.0) -> Tick:
        return Tick(symbol=self.SYMBOL, price=price, volume=vol, timestamp=ts)

    def test_reject_non_tick_timeframe(self):
        with pytest.raises(ValueError, match="not tick-built"):
            TickCandleBuilder(self.SYMBOL, Timeframe.H4)

    def test_first_tick_starts_candle(self):
        builder = TickCandleBuilder(self.SYMBOL, Timeframe.M15)
        # Tick at 2026-02-15 10:02:30 UTC → candle should align to 10:00:00
        ts = 1771056150.0  # arbitrary, alignment tested below
        builder.on_tick(self._make_tick(1.08500, ts))
        c = builder.current_candle
        assert c is not None
        assert c.open == 1.08500
        assert c.is_closed is False
        # Candle timestamp should be floor-aligned to 15-min
        assert c.timestamp == builder._align_to_interval(ts, 900)

    def test_candle_closes_on_boundary_cross(self):
        builder = TickCandleBuilder(self.SYMBOL, Timeframe.M15)

        # Start of a 15-min window (exact boundary)
        base = 1771056000.0  # clean 15-min boundary
        builder.on_tick(self._make_tick(1.08500, base + 1))
        builder.on_tick(self._make_tick(1.08600, base + 120))
        builder.on_tick(self._make_tick(1.08400, base + 500))

        assert builder.current_candle is not None
        assert builder.current_candle.is_closed is False

        # Tick that crosses into next candle
        closed = builder.on_tick(self._make_tick(1.08550, base + 901))
        assert closed is not None
        assert closed.is_closed is True
        assert closed.open == 1.08500
        assert closed.high == 1.08600
        assert closed.low == 1.08400
        assert closed.close == 1.08400  # last tick before boundary
        assert closed.tick_count == 3

        # New candle should be in progress
        assert builder.current_candle is not None
        assert builder.current_candle.open == 1.08550

    def test_force_close(self):
        builder = TickCandleBuilder(self.SYMBOL, Timeframe.M15)
        base = 1771056000.0
        builder.on_tick(self._make_tick(1.08500, base + 1))
        closed = builder.force_close()
        assert closed is not None
        assert closed.is_closed is True
        assert builder.current_candle is None

    def test_callback_fired_on_close(self):
        closed_candles = []
        builder = TickCandleBuilder(
            self.SYMBOL, Timeframe.M15,
            on_candle_closed=closed_candles.append,
        )
        base = 1771056000.0
        builder.on_tick(self._make_tick(1.08500, base + 1))
        builder.on_tick(self._make_tick(1.08550, base + 901))
        assert len(closed_candles) == 1

    def test_ignores_wrong_symbol(self):
        builder = TickCandleBuilder(self.SYMBOL, Timeframe.M15)
        wrong_tick = Tick(
            symbol="OANDA:GBP_USD", price=1.25, volume=1.0, timestamp=1771056001.0
        )
        result = builder.on_tick(wrong_tick)
        assert result is None
        assert builder.current_candle is None


# ---------------------------------------------------------------------------
# TickCandleBuilder — H1
# ---------------------------------------------------------------------------

class TestTickCandleBuilderH1:
    SYMBOL = "OANDA:EUR_USD"

    def _make_tick(self, price: float, ts: float, vol: float = 1.0) -> Tick:
        return Tick(symbol=self.SYMBOL, price=price, volume=vol, timestamp=ts)

    def test_h1_candle_aligns_to_hour(self):
        builder = TickCandleBuilder(self.SYMBOL, Timeframe.H1)
        # Tick at some mid-hour time
        ts = 1771056500.0
        builder.on_tick(self._make_tick(1.08500, ts))
        c = builder.current_candle
        assert c is not None
        expected_boundary = builder._align_to_interval(ts, 3600)
        assert c.timestamp == expected_boundary

    def test_h1_closes_after_one_hour(self):
        builder = TickCandleBuilder(self.SYMBOL, Timeframe.H1)
        base = 1771056000.0  # clean hour boundary
        builder.on_tick(self._make_tick(1.08500, base + 10))
        builder.on_tick(self._make_tick(1.08700, base + 1800))

        # Cross into next hour
        closed = builder.on_tick(self._make_tick(1.08600, base + 3601))
        assert closed is not None
        assert closed.is_closed is True
        assert closed.high == 1.08700
        assert closed.tick_count == 2


# ---------------------------------------------------------------------------
# RESTCandleFetcher
# ---------------------------------------------------------------------------

class TestRESTCandleFetcher:
    def test_reject_tick_timeframe(self):
        fetcher = RESTCandleFetcher(api_key="test_key")
        with pytest.raises(ValueError, match="built from ticks"):
            fetcher.fetch_candles("OANDA:EUR_USD", Timeframe.M15)

        with pytest.raises(ValueError, match="built from ticks"):
            fetcher.fetch_candles("OANDA:EUR_USD", Timeframe.H1)

    def test_requires_api_key(self):
        with pytest.raises(ValueError, match="API key is required"):
            RESTCandleFetcher(api_key="")

    @patch("analysis.candle_builder.requests")
    def test_fetch_h4_candles(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "s": "ok",
            "t": [1771056000, 1771070400],
            "o": [1.085, 1.086],
            "h": [1.087, 1.088],
            "l": [1.083, 1.084],
            "c": [1.086, 1.087],
            "v": [1000, 1200],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        fetcher = RESTCandleFetcher(api_key="premium_key", rate_limit_delay=0)
        candles = fetcher.fetch_candles("OANDA:EUR_USD", Timeframe.H4, count=2)

        assert len(candles) == 2
        assert candles[0].timeframe == Timeframe.H4
        assert candles[0].open == 1.085
        assert candles[0].is_closed is True
        assert candles[1].close == 1.087

    @patch("analysis.candle_builder.requests")
    def test_fetch_no_data(self, mock_requests):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"s": "no_data"}
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        fetcher = RESTCandleFetcher(api_key="premium_key", rate_limit_delay=0)
        candles = fetcher.fetch_candles("OANDA:EUR_USD", Timeframe.D1, count=10)
        assert candles == []


# ---------------------------------------------------------------------------
# CandleManager — Integration
# ---------------------------------------------------------------------------

class TestCandleManager:
    SYMBOL = "OANDA:EUR_USD"

    def _make_tick(self, price: float, ts: float) -> Tick:
        return Tick(symbol=self.SYMBOL, price=price, volume=1.0, timestamp=ts)

    def test_tick_feeds_both_m15_and_h1(self):
        mgr = CandleManager(
            symbols=[self.SYMBOL],
            api_key="test_key",
        )
        base = 1771056000.0
        mgr.on_tick(self._make_tick(1.085, base + 1))

        m15 = mgr.get_current_candle(self.SYMBOL, Timeframe.M15)
        h1 = mgr.get_current_candle(self.SYMBOL, Timeframe.H1)
        assert m15 is not None
        assert h1 is not None

    def test_rest_timeframe_raises_on_tick_access(self):
        mgr = CandleManager(symbols=[self.SYMBOL], api_key="test_key")
        # get_current_candle for REST TF returns None (no builder)
        assert mgr.get_current_candle(self.SYMBOL, Timeframe.H4) is None

    def test_fetch_rest_rejects_tick_tf(self):
        mgr = CandleManager(symbols=[self.SYMBOL], api_key="test_key")
        with pytest.raises(ValueError):
            mgr.fetch_rest_candles(self.SYMBOL, Timeframe.M15)

    def test_force_close_all(self):
        mgr = CandleManager(symbols=[self.SYMBOL], api_key="test_key")
        base = 1771056000.0
        mgr.on_tick(self._make_tick(1.085, base + 1))
        closed = mgr.force_close_all()
        # Should close both M15 and H1
        assert len(closed) == 2
        tfs = {c.timeframe for c in closed}
        assert Timeframe.M15 in tfs
        assert Timeframe.H1 in tfs
