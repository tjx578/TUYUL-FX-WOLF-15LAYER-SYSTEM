"""Tests for data -1 sentinel guard across all pipeline layers.

Covers:
- Fix 1: normalize_response() rejects sentinel -1 and OHLC violations
- Fix 2: _calculate_from_ts() weekend alignment
- Fix 3: warmup_symbol_tf() increments WARMUP_FAILURES metric
- Fix 4: _seed_redis_candle_history() pre-seed validation drops dirty candles
- Fix 5: aggregate_h4() filters invalid H1 bars before aggregation
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finnhub_response(
    candles: list[tuple[float, float, float, float, float, int]],
    *,
    status: str = "ok",
) -> dict[str, Any]:
    """Build a Finnhub-style parallel-array response.

    Each candle tuple: (open, high, low, close, volume, unix_ts).
    """
    return {
        "s": status,
        "o": [c[0] for c in candles],
        "h": [c[1] for c in candles],
        "l": [c[2] for c in candles],
        "c": [c[3] for c in candles],
        "v": [c[4] for c in candles],
        "t": [c[5] for c in candles],
    }


def _make_h1_candle(
    close: float = 1.1000,
    open_: float = 1.0990,
    high: float = 1.1010,
    low: float = 1.0980,
    volume: float = 100.0,
    hour: int = 1,
) -> dict[str, Any]:
    """Build a minimal H1 candle dict."""
    ts = datetime(2026, 3, 16, hour, 0, 0, tzinfo=UTC)  # Monday
    return {
        "symbol": "EURUSD",
        "timeframe": "H1",
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "timestamp": ts,
        "source": "rest_api",
    }


def _unix(year: int = 2026, month: int = 3, day: int = 16, hour: int = 1) -> int:
    return int(datetime(year, month, day, hour, 0, 0, tzinfo=UTC).timestamp())


# ---------------------------------------------------------------------------
# Test suite for Fix 1: normalize_response()
# ---------------------------------------------------------------------------


class TestNormalizeResponseGuard:
    """normalize_response must reject candles with sentinel -1 or OHLC violations."""

    @pytest.fixture(autouse=True)
    def _fetcher(self):
        from ingest.finnhub_candles import FinnhubCandleFetcher

        with patch.object(FinnhubCandleFetcher, "__init__", lambda self: None):
            self.fetcher = FinnhubCandleFetcher.__new__(FinnhubCandleFetcher)

    def test_clean_data_passes(self):
        resp = _make_finnhub_response(
            [
                (1.0990, 1.1010, 1.0980, 1.1000, 100, _unix(hour=1)),
                (1.1000, 1.1020, 1.0990, 1.1010, 200, _unix(hour=2)),
            ]
        )
        result = self.fetcher.normalize_response(resp, "EURUSD", "H1")
        assert len(result) == 2
        assert result[0]["close"] == 1.1000
        assert result[1]["close"] == 1.1010

    def test_no_data_status_returns_empty(self):
        resp = {"s": "no_data", "c": [-1], "h": [-1], "l": [-1], "o": [-1], "t": [-1], "v": [-1]}
        result = self.fetcher.normalize_response(resp, "EURUSD", "H1")
        assert result == []

    def test_sentinel_neg1_candle_rejected(self):
        """A candle with all -1 OHLC must be filtered out."""
        resp = _make_finnhub_response(
            [
                (1.0990, 1.1010, 1.0980, 1.1000, 100, _unix(hour=1)),  # valid
                (-1, -1, -1, -1, -1, -1),  # sentinel
            ]
        )
        result = self.fetcher.normalize_response(resp, "EURUSD", "H1")
        assert len(result) == 1
        assert result[0]["close"] == 1.1000

    def test_partial_neg1_rejected(self):
        """A candle with only close=-1 must be rejected even if others are valid."""
        resp = _make_finnhub_response(
            [
                (1.0990, 1.1010, 1.0980, -1, 100, _unix(hour=1)),  # close=-1
            ]
        )
        result = self.fetcher.normalize_response(resp, "EURUSD", "H1")
        assert result == []

    def test_zero_price_rejected(self):
        """Candles with 0 OHLC values are rejected (v <= 0 guard)."""
        resp = _make_finnhub_response(
            [
                (0, 0, 0, 0, 0, _unix(hour=1)),
            ]
        )
        result = self.fetcher.normalize_response(resp, "EURUSD", "H1")
        assert result == []

    def test_ohlc_violation_high_lt_low(self):
        """high < low is physically impossible; must be rejected."""
        resp = _make_finnhub_response(
            [
                (1.1000, 1.0900, 1.1100, 1.1000, 100, _unix(hour=1)),  # high < low
            ]
        )
        result = self.fetcher.normalize_response(resp, "EURUSD", "H1")
        assert result == []

    def test_ohlc_violation_high_lt_close(self):
        """high < close violates OHLC invariant."""
        resp = _make_finnhub_response(
            [
                (1.1000, 1.1005, 1.0980, 1.1010, 100, _unix(hour=1)),  # close > high
            ]
        )
        result = self.fetcher.normalize_response(resp, "EURUSD", "H1")
        assert result == []

    def test_mixed_valid_and_invalid(self):
        """Only valid candles survive; invalid are silently dropped."""
        resp = _make_finnhub_response(
            [
                (1.0990, 1.1010, 1.0980, 1.1000, 100, _unix(hour=1)),  # valid
                (-1, -1, -1, -1, -1, -1),  # sentinel
                (1.1000, 1.1020, 1.0990, 1.1010, 200, _unix(hour=3)),  # valid
                (1.1000, 1.0900, 1.1100, 1.1000, 100, _unix(hour=4)),  # high < low
            ]
        )
        result = self.fetcher.normalize_response(resp, "EURUSD", "H1")
        assert len(result) == 2

    def test_neg1_timestamp_rejected(self):
        """Candle with timestamp=-1 must be rejected."""
        resp = _make_finnhub_response(
            [
                (1.0990, 1.1010, 1.0980, 1.1000, 100, -1),  # ts=-1
            ]
        )
        result = self.fetcher.normalize_response(resp, "EURUSD", "H1")
        assert result == []

    def test_mismatched_length_returns_empty(self):
        resp = {"s": "ok", "o": [1.0], "h": [1.1], "l": [1.0], "c": [1.05, 1.06], "v": [100], "t": [_unix()]}
        result = self.fetcher.normalize_response(resp, "EURUSD", "H1")
        assert result == []

    def test_empty_arrays_returns_empty(self):
        resp = {"s": "ok", "o": [], "h": [], "l": [], "c": [], "v": [], "t": []}
        result = self.fetcher.normalize_response(resp, "EURUSD", "H1")
        assert result == []


# ---------------------------------------------------------------------------
# Test suite for Fix 2: _calculate_from_ts() weekend alignment
# ---------------------------------------------------------------------------


class TestCalculateFromTsWeekend:
    """_calculate_from_ts should rewind Saturday/Sunday to Friday."""

    @pytest.fixture(autouse=True)
    def _fetcher(self):
        from ingest.finnhub_candles import FinnhubCandleFetcher

        with patch.object(FinnhubCandleFetcher, "__init__", lambda self: None):
            self.fetcher = FinnhubCandleFetcher.__new__(FinnhubCandleFetcher)

    def test_weekday_no_adjustment(self):
        """Monday-Friday: no adjustment to 'now'."""
        # Wednesday 2026-03-18 12:00 UTC
        wed = datetime(2026, 3, 18, 12, 0, 0, tzinfo=UTC)
        with patch("ingest.finnhub_candles.datetime") as mock_dt:
            mock_dt.now.return_value = wed
            mock_dt.fromtimestamp = datetime.fromtimestamp
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from_ts = self.fetcher._calculate_from_ts(100, "H1")
        # from_ts should be roughly 100 * 1.40 hours before Wednesday
        expected_from = wed - timedelta(hours=int(100 * 1.40))
        assert abs(from_ts - int(expected_from.timestamp())) < 3600  # within 1h tolerance

    def test_saturday_rewinds_to_friday(self):
        """Saturday should rewind to Friday before calculating range."""
        sat = datetime(2026, 3, 21, 10, 0, 0, tzinfo=UTC)  # Saturday
        fri = sat - timedelta(days=1)
        with patch("ingest.finnhub_candles.datetime") as mock_dt:
            mock_dt.now.return_value = sat
            mock_dt.fromtimestamp = datetime.fromtimestamp
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from_ts = self.fetcher._calculate_from_ts(100, "H1")
        expected_from = fri - timedelta(hours=int(100 * 1.40))
        assert abs(from_ts - int(expected_from.timestamp())) < 3600

    def test_sunday_rewinds_to_friday(self):
        """Sunday should rewind 2 days to Friday."""
        sun = datetime(2026, 3, 22, 10, 0, 0, tzinfo=UTC)  # Sunday
        fri = sun - timedelta(days=2)
        with patch("ingest.finnhub_candles.datetime") as mock_dt:
            mock_dt.now.return_value = sun
            mock_dt.fromtimestamp = datetime.fromtimestamp
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from_ts = self.fetcher._calculate_from_ts(100, "H1")
        expected_from = fri - timedelta(hours=int(100 * 1.40))
        assert abs(from_ts - int(expected_from.timestamp())) < 3600

    def test_buffer_is_40_percent(self):
        """Buffer multiplier should be 1.40 (40%)."""
        mon = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)  # Monday
        with patch("ingest.finnhub_candles.datetime") as mock_dt:
            mock_dt.now.return_value = mon
            mock_dt.fromtimestamp = datetime.fromtimestamp
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            from_ts = self.fetcher._calculate_from_ts(100, "D1")
        expected_from = mon - timedelta(days=int(100 * 1.40))
        assert abs(from_ts - int(expected_from.timestamp())) < 86400


# ---------------------------------------------------------------------------
# Test suite for Fix 3: warmup_symbol_tf() Prometheus counter
# ---------------------------------------------------------------------------


class TestWarmupFailureMetric:
    """warmup_symbol_tf must increment WARMUP_FAILURES on empty/error results."""

    @pytest.fixture(autouse=True)
    def _fetcher(self):
        from ingest.finnhub_candles import FinnhubCandleFetcher

        with patch.object(FinnhubCandleFetcher, "__init__", lambda self: None):
            self.fetcher = FinnhubCandleFetcher.__new__(FinnhubCandleFetcher)
            self.fetcher.context_bus = MagicMock()

    @pytest.mark.asyncio
    async def test_empty_fetch_increments_counter(self):
        from core.metrics import WARMUP_FAILURES

        self.fetcher.fetch = AsyncMock(return_value=[])
        results: dict = {}
        initial = WARMUP_FAILURES.labels(symbol="EURUSD", tf="H1", reason="empty").value
        await self.fetcher.warmup_symbol_tf("EURUSD", "H1", 100, results)
        assert WARMUP_FAILURES.labels(symbol="EURUSD", tf="H1", reason="empty").value > initial

    @pytest.mark.asyncio
    async def test_api_error_increments_counter(self):
        from core.metrics import WARMUP_FAILURES
        from ingest.finnhub_candles import FinnhubCandleError

        self.fetcher.fetch = AsyncMock(side_effect=FinnhubCandleError("test"))
        results: dict = {}
        initial = WARMUP_FAILURES.labels(symbol="GBPUSD", tf="D1", reason="api_error").value
        await self.fetcher.warmup_symbol_tf("GBPUSD", "D1", 100, results)
        assert WARMUP_FAILURES.labels(symbol="GBPUSD", tf="D1", reason="api_error").value > initial

    @pytest.mark.asyncio
    async def test_successful_fetch_no_increment(self):
        from core.metrics import WARMUP_FAILURES

        candle = _make_h1_candle()
        self.fetcher.fetch = AsyncMock(return_value=[candle])
        results: dict = {}
        initial_empty = WARMUP_FAILURES.labels(symbol="AUDUSD", tf="H1", reason="empty").value
        initial_api = WARMUP_FAILURES.labels(symbol="AUDUSD", tf="H1", reason="api_error").value
        await self.fetcher.warmup_symbol_tf("AUDUSD", "H1", 100, results)
        assert WARMUP_FAILURES.labels(symbol="AUDUSD", tf="H1", reason="empty").value == initial_empty
        assert WARMUP_FAILURES.labels(symbol="AUDUSD", tf="H1", reason="api_error").value == initial_api


# ---------------------------------------------------------------------------
# Test suite for Fix 4: _seed_redis_candle_history() pre-seed validation
#
# The validation predicate is tested directly to avoid importing the heavy
# ingest_service module (which has blocking top-level I/O dependencies).
# ---------------------------------------------------------------------------


def _is_clean_candle(c: dict[str, Any]) -> bool:
    """Replicate the exact filter predicate from _seed_redis_candle_history."""
    return all(c.get(k, -1) > 0 for k in ("open", "high", "low", "close")) and c["high"] >= c["low"]


class TestSeedRedisValidation:
    """Validates the candle filter predicate used by _seed_redis_candle_history."""

    def test_clean_candles_pass(self):
        candles = [
            _make_h1_candle(close=1.1000),
            _make_h1_candle(close=1.1010, hour=2),
        ]
        clean = [c for c in candles if _is_clean_candle(c)]
        assert len(clean) == 2

    def test_dirty_sentinel_rejected(self):
        candles = [
            _make_h1_candle(close=1.1000),  # valid
            _make_h1_candle(close=-1, hour=2),  # sentinel
        ]
        clean = [c for c in candles if _is_clean_candle(c)]
        assert len(clean) == 1
        assert clean[0]["close"] == 1.1000

    def test_all_dirty_returns_empty(self):
        candles = [
            _make_h1_candle(close=-1),
            _make_h1_candle(close=-1, hour=2),
        ]
        clean = [c for c in candles if _is_clean_candle(c)]
        assert clean == []

    def test_high_lt_low_rejected(self):
        candles = [
            _make_h1_candle(high=1.0900, low=1.1100),  # high < low
        ]
        clean = [c for c in candles if _is_clean_candle(c)]
        assert clean == []

    def test_zero_ohlc_rejected(self):
        candles = [_make_h1_candle(close=0, open_=0, high=0, low=0)]
        clean = [c for c in candles if _is_clean_candle(c)]
        assert clean == []

    def test_partial_sentinel_rejected(self):
        """One bad field is enough to reject."""
        candles = [_make_h1_candle(open_=-1)]
        clean = [c for c in candles if _is_clean_candle(c)]
        assert clean == []


# ---------------------------------------------------------------------------
# Test suite for Fix 5: aggregate_h4() guard
# ---------------------------------------------------------------------------


class TestAggregateH4Guard:
    """aggregate_h4 must filter invalid H1 bars before aggregation."""

    @pytest.fixture(autouse=True)
    def _fetcher(self):
        from ingest.finnhub_candles import FinnhubCandleFetcher

        with patch.object(FinnhubCandleFetcher, "__init__", lambda self: None):
            self.fetcher = FinnhubCandleFetcher.__new__(FinnhubCandleFetcher)

    def test_all_valid_h1(self):
        h1s = [_make_h1_candle(hour=h) for h in range(1, 5)]
        result = self.fetcher.aggregate_h4(h1s)
        assert len(result) >= 1
        for c in result:
            assert c["close"] > 0

    def test_all_neg1_h1_returns_empty(self):
        h1s = [_make_h1_candle(close=-1, open_=-1, high=-1, low=-1, hour=h) for h in range(1, 5)]
        result = self.fetcher.aggregate_h4(h1s)
        assert result == []

    def test_mixed_valid_invalid_h1(self):
        h1s = [
            _make_h1_candle(hour=1),  # valid
            _make_h1_candle(close=-1, open_=-1, high=-1, low=-1, hour=2),  # sentinel
            _make_h1_candle(hour=3),  # valid
            _make_h1_candle(hour=4),  # valid
        ]
        result = self.fetcher.aggregate_h4(h1s)
        # Should aggregate the 3 valid candles, no -1 values in output
        assert len(result) >= 1
        for c in result:
            assert c["high"] > 0
            assert c["low"] > 0
            assert c["close"] > 0

    def test_high_lt_low_h1_dropped(self):
        """H1 with high < low should be dropped."""
        h1s = [
            _make_h1_candle(hour=1),
            _make_h1_candle(high=1.0900, low=1.1100, hour=2),  # invalid
            _make_h1_candle(hour=3),
            _make_h1_candle(hour=4),
        ]
        result = self.fetcher.aggregate_h4(h1s)
        assert len(result) >= 1
        for c in result:
            assert c["high"] >= c["low"]

    def test_empty_input(self):
        assert self.fetcher.aggregate_h4([]) == []
