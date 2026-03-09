"""
DST-safe datetime utilities for the news/calendar subsystem.

All Forex Factory times are expressed in US/Eastern (America/New_York),
which observes DST. This module provides:
  - parse_et_time    — parse FF wall-clock time strings into UTC datetimes.
  - is_timeless_time — detect "All Day", "Tentative", empty, etc.
  - utcnow           — timezone-aware UTC now (testable).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timezone
from zoneinfo import ZoneInfo

from news.exceptions import InvalidEventDateError

_ET = ZoneInfo("America/New_York")

# Strings that indicate the event has no fixed time
_TIMELESS_TOKENS: frozenset[str] = frozenset({
    "",
    "all day",
    "tentative",
    "tba",
    "tbd",
    "n/a",
    "na",
    "-",
    "--",
})

# HH:MM am/pm  (e.g. "8:30am", "12:00pm", "1:45pm")
_TIME_PATTERN = re.compile(
    r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})(?P<ampm>am|pm)$",
    re.IGNORECASE,
)


def is_timeless_time(raw_time: str | None) -> bool:
    """Return True if *raw_time* is empty, 'All Day', 'Tentative', or similar."""
    if raw_time is None:
        return True
    return raw_time.strip().lower() in _TIMELESS_TOKENS


def parse_et_to_utc(date_str: str, time_str: str) -> datetime:
    """
    Parse a Forex Factory wall-clock time (ET) into a UTC datetime.

    Parameters
    ----------
    date_str : str
        ISO date string, e.g. "2026-03-08".
    time_str : str
        Wall-clock time string, e.g. "8:30am" or "12:00pm".

    Returns
    -------
    datetime
        Timezone-aware UTC datetime.

    Raises
    ------
    InvalidEventDateError
        If either *date_str* or *time_str* cannot be parsed.
    """
    # Parse date
    try:
        event_date = date.fromisoformat(date_str)
    except ValueError as exc:
        raise InvalidEventDateError(date_str, str(exc)) from exc

    # Parse time
    m = _TIME_PATTERN.match(time_str.strip())
    if not m:
        raise InvalidEventDateError(time_str, "does not match expected HH:MMam/pm format")

    hour = int(m.group("hour"))
    minute = int(m.group("minute"))
    ampm = m.group("ampm").lower()

    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise InvalidEventDateError(
            time_str, f"Out-of-range time components: hour={hour} minute={minute}"
        )

    # Combine into ET-aware datetime (ZoneInfo handles DST automatically)
    naive = datetime.combine(event_date, time(hour, minute))
    et_aware = naive.replace(tzinfo=_ET)

    return et_aware.astimezone(UTC)


def parse_iso_to_utc(iso_str: str) -> datetime:
    """
    Parse an ISO 8601 string (with or without 'Z' suffix) to a UTC datetime.

    Raises
    ------
    InvalidEventDateError
    """
    try:
        normalized = iso_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise InvalidEventDateError(iso_str, str(exc)) from exc


def parse_unix_to_utc(ts: int | float) -> datetime:
    """
    Convert a Unix timestamp (seconds) to a UTC datetime.

    Raises
    ------
    InvalidEventDateError
    """
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC)
    except (ValueError, OSError, OverflowError) as exc:
        raise InvalidEventDateError(str(ts), str(exc)) from exc


def utcnow() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(UTC)


def date_to_iso(d: date) -> str:
    """Return ISO 8601 date string (YYYY-MM-DD)."""
    return d.isoformat()


def today_et() -> date:
    """Return today's date in US/Eastern timezone."""
    return datetime.now(_ET).date()
