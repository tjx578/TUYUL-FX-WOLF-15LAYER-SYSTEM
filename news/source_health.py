"""Source health helpers for calendar provider observability."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

_HEALTHY = "healthy"
_DEGRADED = "degraded"
_DOWN = "down"
_STALE = "stale"
_UNKNOWN = "unknown"


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def evaluate_source_health(
    record: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    stale_after_minutes: int = 30,
) -> dict[str, Any]:
    """Evaluate one source health record into a normalized status payload."""
    now = now or datetime.now(UTC)
    if not record:
        return {"status": _UNKNOWN, "healthy": False, "reason": "missing_record"}

    healthy = bool(record.get("healthy"))
    last_checked = _parse_iso(record.get("last_checked"))
    _parse_iso(record.get("last_success"))
    last_error = record.get("last_error")

    if not healthy:
        return {
            "status": _DOWN,
            "healthy": False,
            "reason": last_error or "last_check_failed",
            "last_checked": record.get("last_checked"),
            "last_success": record.get("last_success"),
            "last_error": last_error,
        }

    if last_checked is None:
        return {
            "status": _UNKNOWN,
            "healthy": False,
            "reason": "invalid_last_checked",
            "last_checked": record.get("last_checked"),
            "last_success": record.get("last_success"),
            "last_error": last_error,
        }

    stale_cutoff = now - timedelta(minutes=stale_after_minutes)
    if last_checked < stale_cutoff:
        return {
            "status": _STALE,
            "healthy": False,
            "reason": "stale_check",
            "last_checked": record.get("last_checked"),
            "last_success": record.get("last_success"),
            "last_error": last_error,
        }

    status = _HEALTHY if not last_error else _DEGRADED
    return {
        "status": status,
        "healthy": status == _HEALTHY,
        "reason": None,
        "last_checked": record.get("last_checked"),
        "last_success": record.get("last_success"),
        "last_error": last_error,
    }


def summarize_source_health(
    records: dict[str, dict[str, Any]],
    *,
    now: datetime | None = None,
    stale_after_minutes: int = 30,
) -> dict[str, Any]:
    """Return aggregate and per-source normalized health details."""
    now = now or datetime.now(UTC)
    evaluated: dict[str, dict[str, Any]] = {}

    counts = {
        _HEALTHY: 0,
        _DEGRADED: 0,
        _DOWN: 0,
        _STALE: 0,
        _UNKNOWN: 0,
    }

    for source, record in records.items():
        normalized = evaluate_source_health(
            record,
            now=now,
            stale_after_minutes=stale_after_minutes,
        )
        evaluated[source] = {"source": source, **normalized}
        status = normalized["status"]
        counts[status] = counts.get(status, 0) + 1

    return {
        "summary": {
            "total": len(records),
            "healthy": counts[_HEALTHY],
            "degraded": counts[_DEGRADED],
            "down": counts[_DOWN],
            "stale": counts[_STALE],
            "unknown": counts[_UNKNOWN],
        },
        "sources": evaluated,
        "checked_at": now.isoformat(),
    }
