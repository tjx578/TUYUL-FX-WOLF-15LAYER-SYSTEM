"""Heatmap utilities for calendar event intensity visualization."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, TypedDict

from news.models import EconomicEvent


class HeatmapBucket(TypedDict):
    hour: str
    high: int
    medium: int
    low: int
    total: int
    score: int


class HeatmapPayload(TypedDict):
    timezone: str
    buckets: list[HeatmapBucket]
    max_score: int
    generated_at: str


def _event_hour(event: EconomicEvent | dict[str, Any]) -> int | None:
    if isinstance(event, EconomicEvent):
        if event.datetime_utc is not None:
            return event.datetime_utc.astimezone(UTC).hour
        raw_time = event.time
    else:
        dt_raw = event.get("datetime_utc")
        if dt_raw:
            try:
                return datetime.fromisoformat(dt_raw).astimezone(UTC).hour
            except (ValueError, TypeError):
                return None
        raw_time = str(event.get("time") or "")

    if not raw_time:
        return None
    parts = raw_time.split(":")
    if not parts:
        return None
    try:
        hour = int(parts[0])
    except ValueError:
        return None
    return hour if 0 <= hour <= 23 else None


def _impact_weight(impact: str) -> int:
    normalized = impact.upper().strip()
    if normalized == "HIGH":
        return 3
    if normalized == "MEDIUM":
        return 2
    if normalized == "LOW":
        return 1
    return 0


def build_news_heatmap(events: Sequence[EconomicEvent | dict[str, Any]]) -> HeatmapPayload:
    """Build a UTC hourly heatmap payload from event list."""
    buckets: list[HeatmapBucket] = [
        {
            "hour": f"{hour:02d}:00",
            "high": 0,
            "medium": 0,
            "low": 0,
            "total": 0,
            "score": 0,
        }
        for hour in range(24)
    ]

    for event in events:
        hour = _event_hour(event)
        if hour is None:
            continue

        impact = event.impact.value if isinstance(event, EconomicEvent) else str(event.get("impact") or "UNKNOWN")

        weight = _impact_weight(impact)
        bucket = buckets[hour]
        bucket["total"] += 1
        bucket["score"] += weight

        normalized = impact.upper().strip()
        if normalized == "HIGH":
            bucket["high"] += 1
        elif normalized == "MEDIUM":
            bucket["medium"] += 1
        elif normalized == "LOW":
            bucket["low"] += 1

    return {
        "timezone": "UTC",
        "buckets": buckets,
        "max_score": max((b["score"] for b in buckets), default=0),
        "generated_at": datetime.now(UTC).isoformat(),
    }
