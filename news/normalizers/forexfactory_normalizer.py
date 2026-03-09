"""
Forex Factory normalizer.

Converts raw FF JSON/XML event dicts into canonical ``EconomicEvent`` objects.

Key rules
---------
- ``country`` is always set to ``None`` because FF's "country" field is
  actually the affected currency code, not an ISO country code.
- ``currency`` is taken from the "currency" (or "country") FF field.
- Raises ``InvalidEventDateError`` on unparseable date / time values.
- ``canonical_id`` includes a time bucket (rounded to nearest 5 min) so
  same-day same-title events at different times are not collapsed.
- ``is_timeless`` is True for "All Day", "Tentative", empty, etc.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from news.datetime_utils import is_timeless_time, parse_et_to_utc, today_et
from news.exceptions import InvalidEventDateError
from news.impact_mapper import impact_score, map_ff_impact
from news.models import (
    EconomicEvent,
    EventStatus,
    ImpactLevel,
    SourceConfidence,
)
from news.pair_mapper import get_affected_pairs

_SOURCE = "forexfactory"
_SOURCE_CONFIDENCE = SourceConfidence.HIGH


def _build_canonical_id(
    title: str,
    currency: str,
    date_str: str,
    time_bucket: str,
) -> str:
    """
    Build a provider-agnostic canonical ID.

    Format: sha256(title_lower:currency_upper:date:time_bucket)[:16]
    The time_bucket is the raw time string (or 'timeless') rounded to 5-min
    precision so same-day same-title events at distinct times stay separate.
    """
    raw = f"{title.lower().strip()}:{currency.upper()}:{date_str}:{time_bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _round_to_5min(time_str: str) -> str:
    """Round HH:MMam/pm to nearest 5-minute bucket for canonical_id stability."""
    import re
    m = re.match(r"^(\d{1,2}):(\d{2})(am|pm)$", time_str.strip(), re.IGNORECASE)
    if not m:
        return time_str.strip().lower()
    minute = int(m.group(2))
    rounded = (minute // 5) * 5
    return f"{m.group(1)}:{rounded:02d}{m.group(3).lower()}"


def normalize_ff_event(
    raw: dict[str, Any],
    date_str: str | None = None,
    fetched_at: datetime | None = None,
) -> EconomicEvent:
    """
    Normalise a single Forex Factory raw event dict.

    Parameters
    ----------
    raw : dict
        Raw event as returned by the FF JSON or XML provider.
    date_str : str | None
        ISO date string for this event.  If None, today's ET date is used.
    fetched_at : datetime | None
        When this batch was fetched.

    Returns
    -------
    EconomicEvent

    Raises
    ------
    InvalidEventDateError
        If the event date or time cannot be parsed.
    """
    date_str = date_str or str(today_et())
    fetched_at = fetched_at or datetime.now(UTC)

    # ── Extract fields ─────────────────────────────────────────────────────────
    title: str = (raw.get("title") or raw.get("name") or raw.get("event") or "").strip()

    # FF "country" field is actually the currency code
    currency: str = (
        raw.get("currency") or raw.get("country") or ""
    ).strip().upper()

    raw_time: str = (raw.get("time") or raw.get("date") or "").strip()
    raw_impact: str = raw.get("impact", "")

    actual: str | None = raw.get("actual") or None
    forecast: str | None = raw.get("forecast") or raw.get("estimate") or None
    previous: str | None = raw.get("previous") or raw.get("prev") or None
    event_url: str | None = raw.get("url") or None
    better_direction: str | None = raw.get("betterThan") or raw.get("better_than") or None

    # ── Impact ─────────────────────────────────────────────────────────────────
    impact: ImpactLevel = map_ff_impact(raw_impact)
    score: int = impact_score(impact)

    # ── Timeless detection ─────────────────────────────────────────────────────
    timeless: bool = is_timeless_time(raw_time)

    # ── Datetime parsing ───────────────────────────────────────────────────────
    datetime_utc: datetime | None = None
    if not timeless:
        # Raises InvalidEventDateError if date or time is unparseable
        datetime_utc = parse_et_to_utc(date_str, raw_time)

    # ── Canonical ID ───────────────────────────────────────────────────────────
    time_bucket = "timeless" if timeless else _round_to_5min(raw_time)
    canonical_id = _build_canonical_id(title, currency, date_str, time_bucket)

    # ── Affected pairs ─────────────────────────────────────────────────────────
    affected = get_affected_pairs(currency)

    # ── Status ────────────────────────────────────────────────────────────────
    status = EventStatus.RELEASED if actual is not None else EventStatus.SCHEDULED

    return EconomicEvent(
        canonical_id=canonical_id,
        source=_SOURCE,
        source_confidence=_SOURCE_CONFIDENCE,
        title=title,
        currency=currency,
        country=None,  # FF country field is currency code — not a real country
        impact=impact,
        impact_score=score,
        date=date_str,
        time=raw_time if not timeless else "",
        datetime_utc=datetime_utc,
        timezone_source="America/New_York",
        is_timeless=timeless,
        actual=actual,
        forecast=forecast,
        previous=previous,
        better_direction=better_direction,
        event_url=event_url,
        status=status,
        affected_pairs=affected,
        fetched_at=fetched_at,
        raw=raw,
    )


def normalize_ff_events(
    raw_events: list[dict[str, Any]],
    date_str: str | None = None,
    fetched_at: datetime | None = None,
) -> list[EconomicEvent]:
    """
    Normalise a list of FF raw events, skipping unparseable entries.

    Invalid date/time values raise ``InvalidEventDateError`` and are skipped
    with a warning-level log rather than crashing the entire batch.
    """
    import logging
    log = logging.getLogger(__name__)

    results: list[EconomicEvent] = []
    for raw in raw_events:
        try:
            results.append(normalize_ff_event(raw, date_str=date_str, fetched_at=fetched_at))
        except InvalidEventDateError as exc:
            log.warning("Skipping FF event due to unparseable datetime: %s | raw=%s", exc, raw)
    return results
