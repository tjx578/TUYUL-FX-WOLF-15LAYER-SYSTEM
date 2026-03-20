"""
Sliding-window percentile tracker for operational observability.

Computes p50 / p95 / p99 from a bounded ring buffer of recent observations.
Thread-safe; designed for in-process evaluation without PromQL.

Usage::

    from monitoring.percentile_tracker import PercentileTracker

    tracker = PercentileTracker(window_size=500)
    tracker.observe(42.3)
    summary = tracker.summary()
    # {"count": 1, "p50": 42.3, "p95": 42.3, "p99": 42.3, "min": 42.3, "max": 42.3}

Zone: monitoring/ — pure observability, no execution side-effects.
"""

from __future__ import annotations

import bisect
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class PercentileSummary:
    """Immutable snapshot of percentile statistics."""

    count: int
    p50: float
    p95: float
    p99: float
    min: float
    max: float
    mean: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "count": self.count,
            "p50": round(self.p50, 3),
            "p95": round(self.p95, 3),
            "p99": round(self.p99, 3),
            "min": round(self.min, 3),
            "max": round(self.max, 3),
            "mean": round(self.mean, 3),
        }


_EMPTY_SUMMARY = PercentileSummary(count=0, p50=0.0, p95=0.0, p99=0.0, min=0.0, max=0.0, mean=0.0)


class PercentileTracker:
    """Thread-safe sliding-window percentile calculator.

    Maintains a ring buffer of the most recent *window_size* observations
    and a sorted copy for O(1) percentile lookup.

    Parameters
    ----------
    window_size:
        Maximum number of observations to retain.  Oldest values are
        evicted when the buffer is full.
    """

    def __init__(self, window_size: int = 1000) -> None:
        self._window_size = max(1, window_size)
        self._buffer: list[float] = []
        self._sorted: list[float] = []
        self._head: int = 0  # next write position once buffer is full
        self._full: bool = False
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        """Record a single observation."""
        with self._lock:
            if self._full:
                # Evict oldest value from sorted list
                old_val = self._buffer[self._head]
                idx = bisect.bisect_left(self._sorted, old_val)
                if idx < len(self._sorted) and self._sorted[idx] == old_val:
                    self._sorted.pop(idx)
                # Overwrite ring position
                self._buffer[self._head] = value
                self._head = (self._head + 1) % self._window_size
            else:
                self._buffer.append(value)
                if len(self._buffer) == self._window_size:
                    self._full = True
                    self._head = 0
            # Insert into sorted
            bisect.insort(self._sorted, value)

    def summary(self) -> PercentileSummary:
        """Return current percentile snapshot."""
        with self._lock:
            n = len(self._sorted)
            if n == 0:
                return _EMPTY_SUMMARY
            total = sum(self._sorted)
            return PercentileSummary(
                count=n,
                p50=self._sorted[int(n * 0.50)],
                p95=self._sorted[min(int(n * 0.95), n - 1)],
                p99=self._sorted[min(int(n * 0.99), n - 1)],
                min=self._sorted[0],
                max=self._sorted[-1],
                mean=total / n,
            )

    def percentile(self, pct: float) -> float:
        """Return a specific percentile (0–1 range)."""
        with self._lock:
            n = len(self._sorted)
            if n == 0:
                return 0.0
            idx = min(int(n * pct), n - 1)
            return self._sorted[idx]

    def reset(self) -> None:
        """Clear all observations."""
        with self._lock:
            self._buffer.clear()
            self._sorted.clear()
            self._head = 0
            self._full = False


class LabelledPercentileTracker:
    """Per-label percentile tracker (e.g. per-symbol or per-stage).

    Usage::

        tracker = LabelledPercentileTracker(window_size=500)
        tracker.observe("EURUSD", 42.3)
        summary = tracker.summary("EURUSD")
        all_summaries = tracker.all_summaries()
    """

    def __init__(self, window_size: int = 1000) -> None:
        self._window_size = window_size
        self._trackers: dict[str, PercentileTracker] = {}
        self._lock = threading.Lock()

    def _get(self, label: str) -> PercentileTracker:
        t = self._trackers.get(label)
        if t is None:
            with self._lock:
                t = self._trackers.get(label)
                if t is None:
                    t = PercentileTracker(self._window_size)
                    self._trackers[label] = t
        return t

    def observe(self, label: str, value: float) -> None:
        self._get(label).observe(value)

    def summary(self, label: str) -> PercentileSummary:
        t = self._trackers.get(label)
        if t is None:
            return _EMPTY_SUMMARY
        return t.summary()

    def all_summaries(self) -> dict[str, PercentileSummary]:
        with self._lock:
            keys = list(self._trackers.keys())
        return {k: self._trackers[k].summary() for k in keys}

    def reset(self) -> None:
        with self._lock:
            for t in self._trackers.values():
                t.reset()
            self._trackers.clear()
