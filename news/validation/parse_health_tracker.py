"""
Parse health tracker — monitors provider parsing failure rates.

Tracks success/failure counts per provider with sliding time windows.
Emits alerts when failure rate exceeds configurable thresholds.

Zone: monitoring/ -- observability only, no execution side-effects.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ParseHealthSnapshot:
    """Point-in-time health snapshot for a single provider."""

    provider: str
    total_attempts: int
    success_count: int
    failure_count: int
    failure_rate: float  # 0.0 to 1.0
    status: str  # "healthy", "degraded", "critical"
    last_success: datetime | None
    last_failure: datetime | None
    last_error: str | None
    window_seconds: int
    checked_at: datetime


@dataclass
class _ParseEvent:
    """Internal record of a parse attempt."""

    success: bool
    timestamp: datetime
    error: str | None = None


class ParseHealthTracker:
    """
    Tracks parsing success/failure rates per provider with a sliding window.

    Thread-safe. Designed to be a singleton shared across the news subsystem.

    Parameters
    ----------
    window_seconds : int
        Sliding window duration in seconds (default: 1 hour).
    degraded_threshold : float
        Failure rate above which status becomes "degraded" (default: 0.10).
    critical_threshold : float
        Failure rate above which status becomes "critical" (default: 0.30).
    alert_callback : callable | None
        Optional async callback called when a provider transitions to
        "degraded" or "critical" status. Signature: (provider, snapshot) -> None.
    """

    def __init__(
        self,
        window_seconds: int = 3600,
        degraded_threshold: float = 0.10,
        critical_threshold: float = 0.30,
        alert_callback: Any = None,
    ) -> None:
        self._window_seconds = window_seconds
        self._degraded_threshold = degraded_threshold
        self._critical_threshold = critical_threshold
        self._alert_callback = alert_callback
        self._events: dict[str, deque[_ParseEvent]] = {}
        self._last_status: dict[str, str] = {}
        self._lock = threading.Lock()

    def record_success(self, provider: str) -> None:
        """Record a successful parse attempt."""
        self._record(provider, success=True)

    def record_failure(self, provider: str, error: str = "") -> None:
        """Record a failed parse attempt."""
        self._record(provider, success=False, error=error)

    def _record(self, provider: str, success: bool, error: str | None = None) -> None:
        now = datetime.now(UTC)
        event = _ParseEvent(success=success, timestamp=now, error=error)

        with self._lock:
            if provider not in self._events:
                self._events[provider] = deque()
            self._events[provider].append(event)
            self._prune(provider, now)

        # Check for status transition and alert
        snapshot = self.get_snapshot(provider)
        with self._lock:
            old_status = self._last_status.get(provider, "healthy")
            new_status = snapshot.status
            self._last_status[provider] = new_status

        if new_status != old_status and new_status in ("degraded", "critical"):
            logger.warning(
                "Provider '%s' parse health: %s → %s (failure_rate=%.2f, failures=%d/%d in %ds window)",
                provider,
                old_status,
                new_status,
                snapshot.failure_rate,
                snapshot.failure_count,
                snapshot.total_attempts,
                self._window_seconds,
            )
            if self._alert_callback is not None:
                try:
                    self._alert_callback(provider, snapshot)
                except Exception:
                    logger.debug("Alert callback failed", exc_info=True)

    def _prune(self, provider: str, now: datetime) -> None:
        """Remove events outside the sliding window (caller must hold lock)."""
        cutoff = now - timedelta(seconds=self._window_seconds)
        events = self._events.get(provider)
        if events:
            while events and events[0].timestamp < cutoff:
                events.popleft()

    def get_snapshot(self, provider: str, now: datetime | None = None) -> ParseHealthSnapshot:
        """Get current health snapshot for a provider."""
        now = now or datetime.now(UTC)

        with self._lock:
            self._prune(provider, now)
            events = list(self._events.get(provider, []))

        total = len(events)
        successes = sum(1 for e in events if e.success)
        failures = total - successes
        failure_rate = failures / total if total > 0 else 0.0

        if failure_rate >= self._critical_threshold:
            status = "critical"
        elif failure_rate >= self._degraded_threshold:
            status = "degraded"
        else:
            status = "healthy"

        last_success = None
        last_failure = None
        last_error = None
        for e in reversed(events):
            if e.success and last_success is None:
                last_success = e.timestamp
            if not e.success and last_failure is None:
                last_failure = e.timestamp
                last_error = e.error
            if last_success and last_failure:
                break

        return ParseHealthSnapshot(
            provider=provider,
            total_attempts=total,
            success_count=successes,
            failure_count=failures,
            failure_rate=round(failure_rate, 4),
            status=status,
            last_success=last_success,
            last_failure=last_failure,
            last_error=last_error,
            window_seconds=self._window_seconds,
            checked_at=now,
        )

    def get_all_snapshots(self, now: datetime | None = None) -> dict[str, ParseHealthSnapshot]:
        """Get health snapshots for all tracked providers."""
        now = now or datetime.now(UTC)
        with self._lock:
            providers = list(self._events.keys())
        return {p: self.get_snapshot(p, now) for p in providers}

    def reset(self, provider: str | None = None) -> None:
        """Reset tracking for a specific provider or all providers."""
        with self._lock:
            if provider:
                self._events.pop(provider, None)
                self._last_status.pop(provider, None)
            else:
                self._events.clear()
                self._last_status.clear()
