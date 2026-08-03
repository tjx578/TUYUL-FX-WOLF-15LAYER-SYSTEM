from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analysis.frozen_quote_detector import FrozenQuoteDetector

MONDAY = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)


def test_advancing_live_timestamps_with_unchanged_price_become_frozen() -> None:
    detector = FrozenQuoteDetector(frozen_after_seconds=120, min_unchanged_observations=3)

    first = detector.observe(symbol="EURUSD", price=1.155, observed_at=MONDAY, source="LIVE_TICK_MID")
    second = detector.observe(
        symbol="EURUSD",
        price=1.155,
        observed_at=MONDAY + timedelta(seconds=60),
        source="LIVE_TICK_MID",
    )
    third = detector.observe(
        symbol="EURUSD",
        price=1.155,
        observed_at=MONDAY + timedelta(seconds=120),
        source="LIVE_TICK_MID",
    )

    assert first.status == "INSUFFICIENT_HISTORY"
    assert second.status == "INSUFFICIENT_HISTORY"
    assert third.status == "PRICE_FROZEN"
    assert third.unchanged_seconds == 120
    assert third.execution_blocked is True


def test_price_change_recovers_frozen_quote_to_live() -> None:
    detector = FrozenQuoteDetector(frozen_after_seconds=60, min_unchanged_observations=2)
    detector.observe(symbol="USDJPY", price=150.0, observed_at=MONDAY, source="LIVE_TICK_BID")
    frozen = detector.observe(
        symbol="USDJPY",
        price=150.0,
        observed_at=MONDAY + timedelta(seconds=60),
        source="LIVE_TICK_BID",
    )
    recovered = detector.observe(
        symbol="USDJPY",
        price=150.001,
        observed_at=MONDAY + timedelta(seconds=61),
        source="LIVE_TICK_BID",
    )

    assert frozen.status == "PRICE_FROZEN"
    assert recovered.status == "LIVE"
    assert recovered.execution_blocked is False


def test_weekend_is_market_closed_and_does_not_accumulate_frozen_time() -> None:
    detector = FrozenQuoteDetector(frozen_after_seconds=60, min_unchanged_observations=2)
    friday = datetime(2026, 8, 7, 21, 59, tzinfo=UTC)
    saturday = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    sunday_open = datetime(2026, 8, 9, 22, 0, tzinfo=UTC)
    detector.observe(symbol="GBPUSD", price=1.33, observed_at=friday, source="LIVE_TICK_MID")

    closed = detector.observe(symbol="GBPUSD", price=1.33, observed_at=saturday, source="LIVE_TICK_MID")
    reopened = detector.observe(
        symbol="GBPUSD",
        price=1.33,
        observed_at=sunday_open,
        source="LIVE_TICK_MID",
    )

    assert closed.status == "MARKET_CLOSED"
    assert reopened.status == "INSUFFICIENT_HISTORY"
    assert reopened.unchanged_seconds == 0


def test_closed_candle_source_is_not_subject_to_tick_freeze_detection() -> None:
    detector = FrozenQuoteDetector()

    result = detector.observe(symbol="AUDUSD", price=0.65, observed_at=MONDAY, source="M15_CLOSE")

    assert result.status == "NOT_APPLICABLE"
    assert result.execution_blocked is False
