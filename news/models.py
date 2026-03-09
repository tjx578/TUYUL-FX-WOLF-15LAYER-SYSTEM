"""
Canonical EconomicEvent model for the news/calendar subsystem.

This model is provider-agnostic and is the sole data contract
between providers, the service layer, and consumers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ImpactLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    HOLIDAY = "HOLIDAY"
    UNKNOWN = "UNKNOWN"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    REVISED = "REVISED"
    CANCELLED = "CANCELLED"


class SourceConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class EconomicEvent:
    """
    Canonical representation of a single economic calendar event.

    Fields
    ------
    event_id        : Unique row identifier (UUID string), assigned on ingest.
    canonical_id    : Provider-agnostic stable ID built from title+currency+date+time_bucket.
                      Used for deduplication across providers.
    source          : Originating provider name (e.g. 'forexfactory_json').
    source_confidence : Reliability rating of the source ('high'|'medium'|'low').
    title           : Human-readable event name.
    currency        : ISO 4217 currency code this event affects (e.g. 'USD').
    country         : ISO country code where applicable (may be None for FF events).
    impact          : Impact level enum value.
    impact_score    : Numeric impact 0–3 (0=holiday/unknown, 1=low, 2=medium, 3=high).
    date            : Event date string in YYYY-MM-DD format.
    time            : Wall-clock time string (HH:MM or empty for timeless).
    datetime_utc    : UTC-normalised datetime; None when is_timeless=True.
    timezone_source : Timezone label of the original source (e.g. 'America/New_York').
    is_timeless     : True when no precise time is known (All Day / Tentative / empty).
    actual          : Released actual value string (may be None).
    forecast        : Consensus forecast string (may be None).
    previous        : Previous period value string (may be None).
    better_direction: 'higher' | 'lower' | None – expected direction for a "good" reading.
    event_url       : Source URL for the event page (may be None).
    status          : Lifecycle status of the event.
    affected_pairs  : List of symbol strings this event is expected to move.
    fetched_at      : Wall-clock UTC timestamp when this record was fetched.
    raw             : Original raw dict from the provider (for debugging/audit).
    """

    # Identity
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    canonical_id: str = ""
    source: str = ""
    source_confidence: SourceConfidence = SourceConfidence.MEDIUM

    # Content
    title: str = ""
    currency: str = ""
    country: str | None = None
    impact: ImpactLevel = ImpactLevel.UNKNOWN
    impact_score: int = 0

    # Temporal
    date: str = ""
    time: str = ""
    datetime_utc: datetime | None = None
    timezone_source: str = "America/New_York"
    is_timeless: bool = False

    # Values
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None
    better_direction: str | None = None

    # Metadata
    event_url: str | None = None
    status: EventStatus = EventStatus.SCHEDULED
    affected_pairs: list[str] = field(default_factory=list)
    fetched_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON encoding."""
        return {
            "event_id": self.event_id,
            "canonical_id": self.canonical_id,
            "source": self.source,
            "source_confidence": self.source_confidence.value,
            "title": self.title,
            "currency": self.currency,
            "country": self.country,
            "impact": self.impact.value,
            "impact_score": self.impact_score,
            "date": self.date,
            "time": self.time,
            "datetime_utc": self.datetime_utc.isoformat() if self.datetime_utc else None,
            "timezone_source": self.timezone_source,
            "is_timeless": self.is_timeless,
            "actual": self.actual,
            "forecast": self.forecast,
            "previous": self.previous,
            "better_direction": self.better_direction,
            "event_url": self.event_url,
            "status": self.status.value,
            "affected_pairs": self.affected_pairs,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }


@dataclass
class BlockerStatus:
    """
    Result of a blocker engine evaluation.

    is_locked       : Boolean shortcut – True if ANY lock window covers `now`.
    locked_by       : The highest-priority event causing the lock (may be None).
    lock_reason     : Human-readable description of why trading is locked.
    upcoming        : Events within the lookahead horizon sorted by time.
    checked_at      : Timestamp of this evaluation.
    """

    is_locked: bool = False
    locked_by: EconomicEvent | None = None
    lock_reason: str = ""
    upcoming: list[EconomicEvent] = field(default_factory=list)
    checked_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_locked": self.is_locked,
            "locked_by": self.locked_by.to_dict() if self.locked_by else None,
            "lock_reason": self.lock_reason,
            "upcoming_count": len(self.upcoming),
            "upcoming": [e.to_dict() for e in self.upcoming],
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }
