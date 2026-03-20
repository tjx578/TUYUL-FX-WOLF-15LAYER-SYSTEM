"""
Shared forex market-hours utilities.

Forex trades Sun 22:00 UTC through Fri 22:00 UTC.
Weekend gap: Fri 22:00 UTC → Sun 22:00 UTC (48 hours).

Zone: utils/ — pure stateless helpers, no side-effects.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

# Forex weekend gap: Friday 22:00 UTC → Sunday 22:00 UTC (48 hours)
_WEEKEND_GAP_HOURS = 48

# Friday close: weekday=4, hour=22
_FRIDAY_CLOSE_DOW = 4
_FRIDAY_CLOSE_HOUR = 22

# Sunday open: weekday=6, hour=22
_SUNDAY_OPEN_DOW = 6
_SUNDAY_OPEN_HOUR = 22


def is_forex_market_open(now: datetime | None = None) -> bool:
    """Return True if the forex market is open.

    Forex trades Sun 22:00 UTC through Fri 22:00 UTC.
    Returns False during the weekend gap (Fri 22:00 → Sun 22:00).
    """
    if now is None:
        now = datetime.now(UTC)
    dow = now.weekday()  # Mon=0 … Sun=6
    hour = now.hour
    # Saturday: always closed
    if dow == 5:
        return False
    # Sunday: closed until 22:00 UTC
    if dow == 6:
        return hour >= _SUNDAY_OPEN_HOUR
    # Friday: closed after 22:00 UTC
    if dow == _FRIDAY_CLOSE_DOW:
        return hour < _FRIDAY_CLOSE_HOUR
    # Mon–Thu: always open
    return True


def weekend_gap_seconds(last_update_ts: float, now_ts: float) -> float:
    """Return total seconds of forex weekend closure between two timestamps.

    If the interval [last_update_ts, now_ts] spans a weekend gap
    (Fri 22:00 → Sun 22:00 UTC), the 48-hour gap duration is subtracted
    from effective staleness.  Handles multiple weekends for very stale data.

    Returns 0.0 if no weekend gap falls within the interval.
    """
    if now_ts <= last_update_ts:
        return 0.0

    dt_start = datetime.fromtimestamp(last_update_ts, tz=UTC)
    dt_end = datetime.fromtimestamp(now_ts, tz=UTC)

    total_gap = 0.0

    # Walk from the most recent Friday close at or before dt_start,
    # so we capture any weekend gap that dt_start falls inside of.
    friday_close = _prev_or_current_friday_close(dt_start)

    while friday_close < dt_end:
        sunday_open = friday_close + timedelta(hours=_WEEKEND_GAP_HOURS)

        # Clamp the overlap to [dt_start, dt_end]
        overlap_start = max(friday_close, dt_start)
        overlap_end = min(sunday_open, dt_end)

        if overlap_end > overlap_start:
            total_gap += (overlap_end - overlap_start).total_seconds()

        # Advance to next week's Friday close
        friday_close += timedelta(weeks=1)

    return total_gap


def _prev_or_current_friday_close(dt: datetime) -> datetime:
    """Return the most recent Friday 22:00 UTC at or before *dt*.

    If *dt* is exactly Friday 22:00 or later in the same weekend gap,
    returns that Friday's close so the gap is captured.
    """
    # Days since last Friday (weekday 4)
    days_since_friday = (dt.weekday() - _FRIDAY_CLOSE_DOW) % 7
    candidate = (dt - timedelta(days=days_since_friday)).replace(
        hour=_FRIDAY_CLOSE_HOUR, minute=0, second=0, microsecond=0
    )
    if candidate > dt:
        candidate -= timedelta(weeks=1)
    return candidate
