from __future__ import annotations

from datetime import UTC, date, datetime

from utils.forex_session_calendar import (
    forex_daily_period_from_open,
    latest_expected_forex_daily_period,
    missed_expected_forex_daily_bars,
    next_forex_daily_close,
)


def test_monday_before_rollover_expects_friday_close() -> None:
    period = latest_expected_forex_daily_period(datetime(2026, 8, 3, 12, 51, tzinfo=UTC))

    assert period.open_at_utc == datetime(2026, 7, 30, 21, 0, tzinfo=UTC)
    assert period.close_at_utc == datetime(2026, 7, 31, 21, 0, tzinfo=UTC)


def test_period_open_timestamp_resolves_across_weekend_without_false_staleness() -> None:
    source = forex_daily_period_from_open(datetime(2026, 7, 30, 21, 0, tzinfo=UTC))
    expected = latest_expected_forex_daily_period(datetime(2026, 8, 3, 12, 51, tzinfo=UTC))

    assert source.close_at_utc == expected.close_at_utc
    assert missed_expected_forex_daily_bars(source.close_at_utc, expected.close_at_utc) == 0


def test_rollover_uses_new_york_dst_instead_of_fixed_utc_hour() -> None:
    summer = next_forex_daily_close(datetime(2026, 7, 6, 20, 0, tzinfo=UTC))
    winter = next_forex_daily_close(datetime(2026, 1, 5, 21, 0, tzinfo=UTC))

    assert summer == datetime(2026, 7, 6, 21, 0, tzinfo=UTC)
    assert winter == datetime(2026, 1, 5, 22, 0, tzinfo=UTC)


def test_provider_holiday_can_be_excluded_from_expected_closes() -> None:
    holidays = frozenset({date(2026, 12, 25)})
    period = latest_expected_forex_daily_period(
        datetime(2026, 12, 26, 12, 0, tzinfo=UTC),
        closed_dates=holidays,
    )

    assert period.close_at_utc == datetime(2026, 12, 24, 22, 0, tzinfo=UTC)


def test_missed_bar_count_ignores_weekend() -> None:
    source_close = datetime(2026, 7, 30, 21, 0, tzinfo=UTC)
    expected_close = datetime(2026, 8, 3, 21, 0, tzinfo=UTC)

    assert missed_expected_forex_daily_bars(source_close, expected_close) == 2
