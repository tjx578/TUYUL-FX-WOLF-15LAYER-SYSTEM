"""Tests for LatencyTracker — tick→candle→analysis latency tracking."""

from __future__ import annotations

import time

import pytest

from analysis.latency_tracker import (
    ANALYSIS_DURATION,
    CANDLE_TO_ANALYSIS_LATENCY,
    END_TO_END_LATENCY,
    TICK_TO_CANDLE_LATENCY,
    LatencyTracker,
)


@pytest.fixture(autouse=True)
def _reset_tracker() -> None:
    """Reset singleton between tests."""
    LatencyTracker.reset_singleton()


class TestLatencyTracker:
    """Tests for the per-symbol latency tracker."""

    def test_singleton(self) -> None:
        a = LatencyTracker()
        b = LatencyTracker()
        assert a is b

    def test_record_tick_stores_timestamp(self) -> None:
        tracker = LatencyTracker()
        tracker.record_tick("EURUSD")
        assert tracker.get_last_tick_ts("EURUSD") > 0

    def test_record_candle_complete_stores_timestamp(self) -> None:
        tracker = LatencyTracker()
        tracker.record_tick("EURUSD")
        tracker.record_candle_complete("EURUSD")
        assert tracker.get_candle_complete_ts("EURUSD") > 0

    def test_tick_to_candle_latency_observed(self) -> None:
        tracker = LatencyTracker()
        tracker.record_tick("EURUSD")
        time.sleep(0.01)  # small delay to produce measurable latency
        tracker.record_candle_complete("EURUSD")

        # Check histogram has observation
        key = (("symbol", "EURUSD"),)
        child = TICK_TO_CANDLE_LATENCY._children.get(key)  # noqa: SLF001
        assert child is not None
        assert child.count >= 1
        assert child.sum > 0  # at least some milliseconds

    def test_candle_to_analysis_latency_observed(self) -> None:
        tracker = LatencyTracker()
        tracker.record_tick("GBPUSD")
        tracker.record_candle_complete("GBPUSD")
        time.sleep(0.01)
        tracker.record_analysis_start("GBPUSD")

        key = (("symbol", "GBPUSD"),)
        child = CANDLE_TO_ANALYSIS_LATENCY._children.get(key)  # noqa: SLF001
        assert child is not None
        assert child.count >= 1

    def test_analysis_duration_observed(self) -> None:
        tracker = LatencyTracker()
        tracker.record_tick("XAUUSD")
        tracker.record_candle_complete("XAUUSD")
        tracker.record_analysis_start("XAUUSD")
        time.sleep(0.01)
        tracker.record_verdict_emit("XAUUSD")

        key = (("symbol", "XAUUSD"),)
        child = ANALYSIS_DURATION._children.get(key)  # noqa: SLF001
        assert child is not None
        assert child.count >= 1

    def test_e2e_latency_observed(self) -> None:
        tracker = LatencyTracker()
        tracker.record_tick("USDJPY")
        tracker.record_candle_complete("USDJPY")
        tracker.record_analysis_start("USDJPY")
        time.sleep(0.01)
        tracker.record_verdict_emit("USDJPY")

        key = (("symbol", "USDJPY"),)
        child = END_TO_END_LATENCY._children.get(key)  # noqa: SLF001
        assert child is not None
        assert child.count >= 1

    def test_no_tick_still_safe(self) -> None:
        """Recording candle/analysis/verdict without tick should not crash."""
        tracker = LatencyTracker()
        tracker.record_candle_complete("AUDUSD")
        tracker.record_analysis_start("AUDUSD")
        tracker.record_verdict_emit("AUDUSD")
        # No assertion needed — just verifying no exceptions

    def test_multiple_symbols_independent(self) -> None:
        tracker = LatencyTracker()
        tracker.record_tick("EURUSD")
        tracker.record_tick("GBPUSD")
        assert tracker.get_last_tick_ts("EURUSD") > 0
        assert tracker.get_last_tick_ts("GBPUSD") > 0
        assert tracker.get_last_tick_ts("XAUUSD") == 0
