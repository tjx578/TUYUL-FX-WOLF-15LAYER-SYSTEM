"""Calendar-aware forex Daily period helpers.

The canonical forex trading day rolls at 17:00 America/New_York.  Expressing
that boundary in the venue timezone (rather than as a fixed UTC hour) keeps the
period correct across US daylight-saving transitions.  Only Monday-Friday
rollovers close a Daily bar; the Friday close is followed by the Sunday open,
so no Saturday/Sunday Daily close is expected.

The helpers are deliberately pure.  Provider-specific holiday closures can be
supplied as local New-York dates without changing the default 24/5 calendar.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

FOREX_ROLLOVER_TIMEZONE = "America/New_York"
FOREX_ROLLOVER_HOUR_LOCAL = 17
FOREX_DAILY_FRESHNESS_BASIS = "FOREX_17NY_EXPECTED_CLOSED_BAR_V2_PROVIDER_CALENDAR"

_NEW_YORK = ZoneInfo(FOREX_ROLLOVER_TIMEZONE)
_MAX_CALENDAR_SEARCH_DAYS = 370


@dataclass(frozen=True)
class ForexDailyPeriod:
    """One expected closed Daily period expressed in UTC."""

    open_at_utc: datetime
    close_at_utc: datetime


def parse_forex_closed_dates(value: str | Iterable[str] | None) -> frozenset[date]:
    """Parse provider-closure dates expressed in New-York calendar dates.

    Invalid values raise instead of being ignored: silently dropping a provider
    holiday could mark a valid prior Daily candle stale, while accepting an
    ambiguous date could mark genuinely missing data fresh.
    """

    if value is None:
        return frozenset()
    raw_values = value.split(",") if isinstance(value, str) else list(value)
    resolved: set[date] = set()
    for raw in raw_values:
        text = str(raw).strip()
        if not text:
            continue
        try:
            parsed = date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"invalid forex provider closed date: {text!r}") from exc
        resolved.add(parsed)
    return frozenset(resolved)


def _as_utc(value: datetime) -> datetime:
    resolved = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return resolved.astimezone(UTC)


def _rollover(local_date: date) -> datetime:
    local = datetime.combine(
        local_date,
        time(hour=FOREX_ROLLOVER_HOUR_LOCAL),
        tzinfo=_NEW_YORK,
    )
    return local.astimezone(UTC)


def _is_expected_close_date(local_date: date, closed_dates: frozenset[date]) -> bool:
    return local_date.weekday() < 5 and local_date not in closed_dates


def previous_forex_daily_close(
    before: datetime,
    *,
    inclusive: bool = False,
    closed_dates: frozenset[date] = frozenset(),
) -> datetime:
    """Return the latest expected Daily close before ``before``.

    ``inclusive`` permits a value exactly on the rollover boundary to resolve
    to that same close.  Search is bounded so invalid calendar configuration
    fails loudly instead of looping forever.
    """

    reference = _as_utc(before)
    local_date = reference.astimezone(_NEW_YORK).date()
    for offset in range(_MAX_CALENDAR_SEARCH_DAYS):
        candidate_date = local_date - timedelta(days=offset)
        if not _is_expected_close_date(candidate_date, closed_dates):
            continue
        candidate = _rollover(candidate_date)
        if candidate < reference or (inclusive and candidate == reference):
            return candidate
    raise ValueError("no forex Daily close found within calendar search bound")


def next_forex_daily_close(
    after: datetime,
    *,
    closed_dates: frozenset[date] = frozenset(),
) -> datetime:
    """Return the first expected Daily close strictly after ``after``."""

    reference = _as_utc(after)
    local_date = reference.astimezone(_NEW_YORK).date()
    for offset in range(_MAX_CALENDAR_SEARCH_DAYS):
        candidate_date = local_date + timedelta(days=offset)
        if not _is_expected_close_date(candidate_date, closed_dates):
            continue
        candidate = _rollover(candidate_date)
        if candidate > reference:
            return candidate
    raise ValueError("no forex Daily close found within calendar search bound")


def latest_expected_forex_daily_period(
    now: datetime,
    *,
    closed_dates: frozenset[date] = frozenset(),
) -> ForexDailyPeriod:
    """Return the most recent Daily period that must already be closed."""

    close_at = previous_forex_daily_close(now, inclusive=True, closed_dates=closed_dates)
    open_at = previous_forex_daily_close(close_at, closed_dates=closed_dates)
    return ForexDailyPeriod(open_at_utc=open_at, close_at_utc=close_at)


def forex_daily_period_from_open(
    open_at: datetime,
    *,
    closed_dates: frozenset[date] = frozenset(),
) -> ForexDailyPeriod:
    """Resolve a provider PERIOD_OPEN timestamp into canonical period bounds."""

    canonical_open = _as_utc(open_at)
    close_at = next_forex_daily_close(canonical_open, closed_dates=closed_dates)
    return ForexDailyPeriod(open_at_utc=canonical_open, close_at_utc=close_at)


def forex_daily_period_from_close(
    close_at: datetime,
    *,
    closed_dates: frozenset[date] = frozenset(),
) -> ForexDailyPeriod:
    """Resolve a provider PERIOD_END/explicit close into canonical bounds."""

    canonical_close = _as_utc(close_at)
    open_at = previous_forex_daily_close(canonical_close, closed_dates=closed_dates)
    return ForexDailyPeriod(open_at_utc=open_at, close_at_utc=canonical_close)


def missed_expected_forex_daily_bars(
    source_close_at: datetime,
    expected_close_at: datetime,
    *,
    closed_dates: frozenset[date] = frozenset(),
) -> int:
    """Count expected closes after the source through the expected close."""

    source = _as_utc(source_close_at)
    expected = _as_utc(expected_close_at)
    if source >= expected:
        return 0

    cursor = source
    for missed in range(1, _MAX_CALENDAR_SEARCH_DAYS + 1):
        cursor = next_forex_daily_close(cursor, closed_dates=closed_dates)
        if cursor > expected:
            return missed - 1
        if cursor == expected:
            return missed
    raise ValueError("forex Daily missed-bar count exceeded calendar search bound")


__all__ = [
    "FOREX_DAILY_FRESHNESS_BASIS",
    "FOREX_ROLLOVER_HOUR_LOCAL",
    "FOREX_ROLLOVER_TIMEZONE",
    "ForexDailyPeriod",
    "forex_daily_period_from_close",
    "forex_daily_period_from_open",
    "latest_expected_forex_daily_period",
    "missed_expected_forex_daily_bars",
    "next_forex_daily_close",
    "parse_forex_closed_dates",
    "previous_forex_daily_close",
]
