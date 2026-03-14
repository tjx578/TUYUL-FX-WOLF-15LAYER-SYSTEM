"""
Finnhub normalizer.

Converts raw Finnhub economic calendar event dicts into canonical
``EconomicEvent`` objects.

Key rules
---------
- ``currency`` is the ISO 4217 code from Finnhub's "currency" field.
- ``country`` is set from Finnhub's "country" field only when it is
  a meaningful 2-letter ISO country code; otherwise None.
- Raises ``InvalidEventDateError`` / ``InvalidTimestampError`` on
  unparseable timestamps.
- ``canonical_id`` uses the event ID + date + time bucket so
  same-day duplicates across fetches are collapsed correctly.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from news.datetime_utils import parse_iso_to_utc, parse_unix_to_utc, today_et
from news.exceptions import InvalidEventDateError, InvalidTimestampError
from news.impact_mapper import impact_score, map_finnhub_impact
from news.models import (
    EconomicEvent,
    EventStatus,
    ImpactLevel,
    SourceConfidence,
)
from news.pair_mapper import get_affected_pairs

_SOURCE = "finnhub"
_SOURCE_CONFIDENCE = SourceConfidence.MEDIUM

# Minimal valid country code length (ISO 3166-1 alpha-2)
_MIN_COUNTRY_LEN = 2
_MAX_COUNTRY_LEN = 3


def _is_valid_country(value: str | None) -> bool:
    """Return True if *value* looks like a real ISO country code."""
    if not value:
        return False
    stripped = value.strip()
    return _MIN_COUNTRY_LEN <= len(stripped) <= _MAX_COUNTRY_LEN and stripped.isalpha()


def _build_canonical_id(
    title: str,
    currency: str,
    date_str: str,
    time_bucket: str,
) -> str:
    raw = f"{title.lower().strip()}:{currency.upper()}:{date_str}:{time_bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _datetime_to_time_bucket(dt: datetime) -> str:
    """Round to nearest 5-minute bucket for canonical_id stability."""
    rounded_min = (dt.minute // 5) * 5
    return dt.strftime(f"%H:{rounded_min:02d}")


def normalize_finnhub_event(
    raw: Mapping[str, Any],
    fetched_at: datetime | None = None,
) -> EconomicEvent:
    """
    Normalise a single Finnhub raw event dict.

    Parameters
    ----------
    raw : dict
        Raw event as returned by Finnhub's /calendar/economic endpoint.
    fetched_at : datetime | None
        When this batch was fetched.

    Returns
    -------
    EconomicEvent

    Raises
    ------
    InvalidEventDateError
        If the event timestamp cannot be parsed.
    InvalidTimestampError
        If a Unix timestamp field is malformed.
    """
    fetched_at = fetched_at or datetime.now(UTC)

    # ── Extract fields ─────────────────────────────────────────────────────────
    title: str = (raw.get("event") or raw.get("name") or "").strip()
    currency: str = (raw.get("currency") or "").strip().upper()

    raw_country = raw.get("country")
    country: str | None = str(raw_country).strip().upper() if _is_valid_country(raw_country) else None

    actual_val = raw.get("actual")
    forecast_val = raw.get("estimate") or raw.get("forecast")
    previous_val = raw.get("prev") or raw.get("previous")

    actual: str | None = str(actual_val) if actual_val is not None else None
    forecast: str | None = str(forecast_val) if forecast_val is not None else None
    previous: str | None = str(previous_val) if previous_val is not None else None

    # ── Impact ─────────────────────────────────────────────────────────────────
    impact: ImpactLevel = map_finnhub_impact(raw.get("impact"))
    score: int = impact_score(impact)

    # ── Timestamp parsing ──────────────────────────────────────────────────────
    datetime_utc: datetime | None = None
    is_timeless: bool = False
    date_str: str = str(today_et())
    time_str: str = ""

    raw_time = raw.get("time")  # ISO string, e.g. "2026-03-08T12:30:00+00:00"
    raw_ts = raw.get("timestamp")  # Unix int/float

    if raw_time:
        # Raises InvalidEventDateError if unparseable
        datetime_utc = parse_iso_to_utc(str(raw_time))
        date_str = datetime_utc.strftime("%Y-%m-%d")
        time_str = datetime_utc.strftime("%H:%M")
    elif raw_ts is not None:
        # Raises InvalidTimestampError if malformed
        datetime_utc = parse_unix_to_utc(raw_ts)
        date_str = datetime_utc.strftime("%Y-%m-%d")
        time_str = datetime_utc.strftime("%H:%M")
    else:
        is_timeless = True

    # ── Canonical ID ───────────────────────────────────────────────────────────
    time_bucket = _datetime_to_time_bucket(datetime_utc) if datetime_utc is not None else "timeless"

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
        country=country,
        impact=impact,
        impact_score=score,
        date=date_str,
        time=time_str,
        datetime_utc=datetime_utc,
        timezone_source="UTC",
        is_timeless=is_timeless,
        actual=actual,
        forecast=forecast,
        previous=previous,
        better_direction=None,
        event_url=None,
        status=status,
        affected_pairs=affected,
        fetched_at=fetched_at,
        raw=dict[str, Any](raw),
    )


def normalize_finnhub_events(
    raw_events: list[Mapping[str, Any]],
    fetched_at: datetime | None = None,
) -> list[EconomicEvent]:
    """
    Normalise a list of Finnhub raw events, skipping unparseable entries.
    """
    import logging

    log = logging.getLogger(__name__)

    results: list[EconomicEvent] = []
    for raw in raw_events:
        try:
            results.append(normalize_finnhub_event(raw, fetched_at=fetched_at))
        except (InvalidEventDateError, InvalidTimestampError) as exc:
            log.warning(
                "Skipping Finnhub event due to unparseable datetime: %s | raw=%s",
                exc,
                raw,
            )
    return results
