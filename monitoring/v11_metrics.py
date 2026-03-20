"""
V11 Sniper Filter — p95/p99 latency and outcome tracking.

Provides:
    - Histogram for V11 gate evaluation latency (ms)
    - Counters for V11 outcomes (pass / veto / skip / error)
    - Sliding-window percentile tracker for budget alerting
    - Rate computation helpers (veto_rate, error_rate)

Zone: monitoring/ — pure observability, no execution side-effects.
"""

from __future__ import annotations

import threading

from core.metrics import get_registry
from monitoring.percentile_tracker import LabelledPercentileTracker, PercentileSummary

_R = get_registry()

# ── Histogram (Prometheus-compatible, for /metrics scrape) ────────────

V11_LATENCY_MS = _R.histogram(
    "wolf_v11_gate_latency_ms",
    "V11 sniper-filter evaluation latency in milliseconds",
    label_names=("symbol",),
    buckets=(1, 2, 5, 10, 25, 50, 75, 100, 150, 250, 500),
)

# ── Counters ─────────────────────────────────────────────────────────

V11_OUTCOME_TOTAL = _R.counter(
    "wolf_v11_outcome_total",
    "V11 evaluation outcomes",
    label_names=("symbol", "outcome"),
    # outcome: pass | veto | skip | error | disabled | budget_exceeded
)

# ── Sliding-window percentile tracker ────────────────────────────────

_v11_latency_pct = LabelledPercentileTracker(window_size=500)

# ── Veto-rate sliding window ─────────────────────────────────────────

_RATE_WINDOW = 200  # last N evaluations


class _RateWindow:
    """Thread-safe sliding boolean counter for rate computation."""

    __slots__ = ("_buffer", "_head", "_full", "_lock", "_size")

    def __init__(self, size: int) -> None:
        self._size = size
        self._buffer: list[bool] = []
        self._head = 0
        self._full = False
        self._lock = threading.Lock()

    def record(self, hit: bool) -> None:
        with self._lock:
            if self._full:
                self._buffer[self._head] = hit
                self._head = (self._head + 1) % self._size
            else:
                self._buffer.append(hit)
                if len(self._buffer) == self._size:
                    self._full = True
                    self._head = 0

    def rate(self) -> float:
        with self._lock:
            n = len(self._buffer)
            if n == 0:
                return 0.0
            return sum(1 for b in self._buffer if b) / n

    def count(self) -> int:
        with self._lock:
            return len(self._buffer)


_v11_veto_window = _RateWindow(_RATE_WINDOW)
_v11_error_window = _RateWindow(_RATE_WINDOW)


# ═══════════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════════


def record_v11_evaluation(
    symbol: str,
    latency_ms: float,
    outcome: str,
    budget_ms: float = 100.0,
) -> None:
    """Record a V11 evaluation with latency and outcome.

    Parameters
    ----------
    symbol:
        Trading pair (e.g. ``"EURUSD"``).
    latency_ms:
        Wall-clock time for V11 gate evaluation.
    outcome:
        One of ``"pass"``, ``"veto"``, ``"skip"``, ``"error"``, ``"disabled"``.
    budget_ms:
        Latency budget — if *latency_ms* exceeds this, a
        ``budget_exceeded`` counter is also incremented.
    """
    V11_LATENCY_MS.labels(symbol=symbol).observe(latency_ms)
    V11_OUTCOME_TOTAL.labels(symbol=symbol, outcome=outcome).inc()
    _v11_latency_pct.observe(symbol, latency_ms)

    if latency_ms > budget_ms:
        V11_OUTCOME_TOTAL.labels(symbol=symbol, outcome="budget_exceeded").inc()

    _v11_veto_window.record(outcome == "veto")
    _v11_error_window.record(outcome == "error")


def v11_latency_summary(symbol: str) -> PercentileSummary:
    """Return p50/p95/p99 latency summary for *symbol*."""
    return _v11_latency_pct.summary(symbol)


def v11_all_latency_summaries() -> dict[str, PercentileSummary]:
    """Return latency summaries for all observed symbols."""
    return _v11_latency_pct.all_summaries()


def v11_veto_rate() -> float:
    """Return rolling veto rate over last N evaluations (0–1)."""
    return _v11_veto_window.rate()


def v11_error_rate() -> float:
    """Return rolling error rate over last N evaluations (0–1)."""
    return _v11_error_window.rate()


def v11_veto_window_count() -> int:
    """Return number of evaluations in the veto rate window."""
    return _v11_veto_window.count()


# ── Reset (for testing) ──────────────────────────────────────────────


def reset_v11_metrics() -> None:
    """Reset all V11 percentile/rate state. For testing only."""
    global _v11_veto_window, _v11_error_window
    _v11_latency_pct.reset()
    _v11_veto_window = _RateWindow(_RATE_WINDOW)
    _v11_error_window = _RateWindow(_RATE_WINDOW)
