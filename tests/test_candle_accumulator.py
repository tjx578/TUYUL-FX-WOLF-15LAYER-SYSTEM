"""Tests for analysis/candle_accumulator.py — gap detection, bounded history, no-assert."""

import pytest

from analysis.candle_accumulator import (
    CandleAccumulator,
    CandleAccumulatorConfig,
    _CandleBuilder,
)


class TestCandleBuilder:
    """Tests for _CandleBuilder invariants (replaces assert with ValueError)."""

    def test_emit_valid(self) -> None:
        b = _CandleBuilder("EURUSD", 1.1000, timestamp=1000.0)
        b.update(1.1010)
        b.update(1.0990)
        candle = b.emit(timestamp_close=1059.0, timeframe_seconds=60.0)

        assert candle.open == 1.1000
        assert candle.high == 1.1010
        assert candle.low == 1.0990
        assert candle.close == 1.0990
        assert candle.tick_count == 3
        assert candle.has_gap is False

    def test_emit_with_gap_flag(self) -> None:
        b = _CandleBuilder("EURUSD", 1.1000, timestamp=1000.0)
        candle = b.emit(timestamp_close=1060.0, timeframe_seconds=60.0, has_gap=True)
        assert candle.has_gap is True

    def test_emit_zero_ticks_raises_valueerror(self) -> None:
        """Ensure assert replacement works — ValueError not stripped by -O."""
        b = _CandleBuilder("EURUSD", 1.1000, timestamp=1000.0)
        b.tick_count = 0  # Force invalid state
        with pytest.raises(ValueError, match="zero ticks"):
            b.emit(timestamp_close=1060.0, timeframe_seconds=60.0)

    def test_emit_high_less_than_low_raises_valueerror(self) -> None:
        b = _CandleBuilder("EURUSD", 1.1000, timestamp=1000.0)
        b.high = 1.0900
        b.low = 1.1100  # Force invalid: high < low
        with pytest.raises(ValueError, match="high.*< low"):
            b.emit(timestamp_close=1060.0, timeframe_seconds=60.0)

    def test_emit_close_before_open_raises_valueerror(self) -> None:
        b = _CandleBuilder("EURUSD", 1.1000, timestamp=1000.0)
        with pytest.raises(ValueError, match="close timestamp.*< open timestamp"):
            b.emit(timestamp_close=999.0, timeframe_seconds=60.0)


class TestCandleAccumulatorConfig:
    def test_invalid_timeframe_raises(self) -> None:
        config = CandleAccumulatorConfig(timeframe_seconds=0)
        with pytest.raises(ValueError, match="timeframe_seconds must be positive"):
            CandleAccumulator("EURUSD", config)

    def test_invalid_max_completed_raises(self) -> None:
        config = CandleAccumulatorConfig(max_completed=0)
        with pytest.raises(ValueError, match="max_completed must be >= 1"):
            CandleAccumulator("EURUSD", config)


class TestGapDetection:
    """Tests that time gaps are properly detected and marked on candles."""

    def _make_acc(
        self,
        timeframe: float = 60.0,
        gap_factor: float = 2.0,
        max_completed: int = 100,
    ) -> CandleAccumulator:
        config = CandleAccumulatorConfig(
            timeframe_seconds=timeframe,
            gap_threshold_factor=gap_factor,
            max_completed=max_completed,
        )
        return CandleAccumulator("EURUSD", config)

    def test_no_gap_normal_ticks(self) -> None:
        acc = self._make_acc(timeframe=60.0)

        # Ticks within same candle
        acc.on_tick(1.1000, timestamp=1000.0)
        acc.on_tick(1.1010, timestamp=1020.0)
        acc.on_tick(1.1005, timestamp=1040.0)

        # Cross to next candle — normal, no gap
        result = acc.on_tick(1.1020, timestamp=1060.0)
        assert result is not None
        assert result.has_gap is False

    def test_gap_detected_after_disconnect(self) -> None:
        acc = self._make_acc(timeframe=60.0, gap_factor=2.0)

        # First candle ticks
        acc.on_tick(1.1000, timestamp=1000.0)
        acc.on_tick(1.1010, timestamp=1030.0)

        # Simulate WS disconnect: next tick arrives 5 minutes later
        # gap_threshold = 60 * 2.0 = 120s; elapsed = 300s > 120s → gap
        result = acc.on_tick(1.1050, timestamp=1330.0)
        assert result is not None
        assert result.has_gap is True
        assert result.symbol == "EURUSD"

    def test_gap_threshold_boundary(self) -> None:
        acc = self._make_acc(timeframe=60.0, gap_factor=2.0)
        # threshold = 120s

        acc.on_tick(1.1000, timestamp=0.0)

        # Exactly at threshold (120s) — NOT a gap (must exceed, not equal)
        # elapsed=120, boundary crossed (tick at 120 is boundary 120, candle was boundary 0)
        result = acc.on_tick(1.1010, timestamp=120.0)
        assert result is not None
        assert result.has_gap is False

        # Now tick at boundary + epsilon over threshold from last tick at 120
        # boundary=120, next tick at 360 → elapsed=240 > 120 → gap
        acc.on_tick(1.1020, timestamp=150.0)
        result2 = acc.on_tick(1.1030, timestamp=360.0)
        assert result2 is not None
        assert result2.has_gap is True

    def test_first_tick_no_gap(self) -> None:
        """First tick ever should not trigger gap detection."""
        acc = self._make_acc()
        result = acc.on_tick(1.1000, timestamp=1000.0)
        # First tick starts a candle, nothing completed yet
        assert result is None


class TestBoundedHistory:
    """Tests that _completed deque respects maxlen."""

    def test_completed_respects_maxlen(self) -> None:
        config = CandleAccumulatorConfig(
            timeframe_seconds=10.0,
            max_completed=5,
        )
        acc = CandleAccumulator("EURUSD", config)

        # Generate 10 completed candles
        base_ts = 0.0
        for i in range(11):
            # Each tick in a new candle period
            acc.on_tick(1.1000 + i * 0.0001, timestamp=base_ts + i * 10.0)

        # Should have at most 5 completed candles
        assert acc.completed_count <= 5

    def test_oldest_candles_evicted(self) -> None:
        config = CandleAccumulatorConfig(
            timeframe_seconds=10.0,
            max_completed=3,
        )
        acc = CandleAccumulator("EURUSD", config)

        # Create 6 candles (1 tick per candle)
        for i in range(7):
            acc.on_tick(1.1000 + i * 0.001, timestamp=i * 10.0)

        completed = acc.completed
        assert len(completed) <= 3

        # The most recent candles should be present
        if len(completed) > 0:
            # Last completed should have a relatively late open timestamp
            last = completed[-1]
            assert last.timestamp_open >= 30.0  # At minimum the 4th candle

    def test_completed_returns_list_copy(self) -> None:
        """Ensure .completed returns a copy, not the internal deque."""
        config = CandleAccumulatorConfig(timeframe_seconds=10.0, max_completed=10)
        acc = CandleAccumulator("EURUSD", config)

        acc.on_tick(1.1000, timestamp=0.0)
        acc.on_tick(1.1010, timestamp=10.0)

        list1 = acc.completed
        list2 = acc.completed
        assert list1 is not list2  # Different list objects
        assert isinstance(list1, list)


class TestNormalOperation:
    """Regression tests for basic candle building."""

    def _make_acc(self, timeframe: float = 60.0) -> CandleAccumulator:
        config = CandleAccumulatorConfig(timeframe_seconds=timeframe, max_completed=100)
        return CandleAccumulator("EURUSD", config)

    def test_single_candle_tick_sequence(self) -> None:
        acc = self._make_acc(timeframe=60.0)

        assert acc.on_tick(1.1000, timestamp=1000.0) is None
        assert acc.on_tick(1.1050, timestamp=1010.0) is None
        assert acc.on_tick(1.0980, timestamp=1020.0) is None
        assert acc.on_tick(1.1030, timestamp=1050.0) is None

        # Cross boundary
        candle = acc.on_tick(1.1040, timestamp=1060.0)
        assert candle is not None
        assert candle.open == 1.1000
        assert candle.high == 1.1050
        assert candle.low == 1.0980
        assert candle.close == 1.1030
        assert candle.tick_count == 4

    def test_flush_returns_current_candle(self) -> None:
        acc = self._make_acc()
        acc.on_tick(1.1000, timestamp=1000.0)
        acc.on_tick(1.1010, timestamp=1010.0)

        candle = acc.flush(timestamp=1055.0)
        assert candle is not None
        assert candle.tick_count == 2
        assert candle.has_gap is False

    def test_flush_empty_returns_none(self) -> None:
        acc = self._make_acc()
        assert acc.flush() is None

    def test_invalid_price_raises(self) -> None:
        acc = self._make_acc()
        with pytest.raises(ValueError, match="positive"):
            acc.on_tick(0.0, timestamp=1000.0)
        with pytest.raises(ValueError, match="positive"):
            acc.on_tick(-1.5, timestamp=1000.0)

    def test_reset_clears_all_state(self) -> None:
        acc = self._make_acc(timeframe=10.0)
        acc.on_tick(1.1000, timestamp=0.0)
        acc.on_tick(1.1010, timestamp=10.0)  # completes first candle
        acc.on_tick(1.1020, timestamp=15.0)  # starts second candle

        assert acc.completed_count == 1
        assert acc.current_builder is not None

        acc.reset()

        assert acc.completed_count == 0
        assert acc.current_builder is None

    def test_symbol_property(self) -> None:
        acc = self._make_acc()
        assert acc.symbol == "EURUSD"
