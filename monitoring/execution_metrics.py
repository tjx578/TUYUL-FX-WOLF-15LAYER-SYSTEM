"""
Execution-path stage latency instrumentation — p95/p99.

Tracks wall-clock time for each execution stage:
    - guard_check   — ExecutionGuard.execute() / validate_scope()
    - queue_wait    — time in EAManager queue before dispatch
    - broker_call   — BrokerExecutor HTTP round-trip
    - dispatch_total — submit → result (guard + queue + broker)

Also tracks L12 verdict outcome rates (reject / ambiguity) and provides
a freshness–latency correlation gauge for reconnect-storm detection.

Zone: monitoring/ — pure observability, no execution side-effects.
"""

from __future__ import annotations

import threading
import time

from core.metrics import get_registry
from monitoring.percentile_tracker import LabelledPercentileTracker, PercentileSummary

_R = get_registry()

# ═══════════════════════════════════════════════════════════════════════
#  Histograms (Prometheus-compatible)
# ═══════════════════════════════════════════════════════════════════════

EXEC_STAGE_LATENCY_MS = _R.histogram(
    "wolf_execution_stage_latency_ms",
    "Execution path stage latency in milliseconds",
    label_names=("stage",),
    # stage: guard_check | queue_wait | broker_call | dispatch_total
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)

EXEC_OUTCOME_TOTAL = _R.counter(
    "wolf_execution_outcome_total",
    "Execution request outcomes",
    label_names=("outcome",),
    # outcome: success | broker_error | guard_rejected | queue_overload | timeout
)

# ── L12 verdict rate tracking ────────────────────────────────────────

L12_OUTCOME_TOTAL = _R.counter(
    "wolf_l12_outcome_total",
    "L12 verdict outcome totals for rate computation",
    label_names=("outcome",),
    # outcome: execute | hold | no_trade | abort | ambiguous | reject
)

# ── Freshness–latency correlation ────────────────────────────────────

FRESHNESS_LATENCY_CORR = _R.gauge(
    "wolf_freshness_latency_correlation",
    "Recent correlation flag: 1 if high latency coincides with stale feeds",
    label_names=("symbol",),
)

RECONNECT_STORM_FLAG = _R.gauge(
    "wolf_reconnect_storm_active",
    "Reconnect storm detector (1=storm, 0=calm)",
)

# ═══════════════════════════════════════════════════════════════════════
#  Sliding-window percentile trackers
# ═══════════════════════════════════════════════════════════════════════

_exec_latency_pct = LabelledPercentileTracker(window_size=500)

# ── L12 reject/ambiguity rate windows ────────────────────────────────

_L12_RATE_WINDOW = 200


class _RateCounter:
    """Thread-safe sliding boolean counter."""

    __slots__ = ("_buf", "_head", "_full", "_lock", "_size")

    def __init__(self, size: int) -> None:
        self._size = size
        self._buf: list[bool] = []
        self._head = 0
        self._full = False
        self._lock = threading.Lock()

    def record(self, hit: bool) -> None:
        with self._lock:
            if self._full:
                self._buf[self._head] = hit
                self._head = (self._head + 1) % self._size
            else:
                self._buf.append(hit)
                if len(self._buf) == self._size:
                    self._full = True
                    self._head = 0

    def rate(self) -> float:
        with self._lock:
            n = len(self._buf)
            return (sum(1 for b in self._buf if b) / n) if n else 0.0

    def count(self) -> int:
        with self._lock:
            return len(self._buf)


_l12_reject_window = _RateCounter(_L12_RATE_WINDOW)
_l12_ambiguity_window = _RateCounter(_L12_RATE_WINDOW)

# ── Reconnect storm detector ────────────────────────────────────────

_RECONNECT_STORM_WINDOW_SEC = 60.0
_RECONNECT_STORM_THRESHOLD = 5  # N reconnects in window → storm


class _ReconnectStormDetector:
    """Detects rapid reconnect bursts."""

    __slots__ = ("_timestamps", "_lock")

    def __init__(self) -> None:
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def record_reconnect(self) -> bool:
        """Record a reconnect event. Returns True if storm is active."""
        now = time.monotonic()
        with self._lock:
            cutoff = now - _RECONNECT_STORM_WINDOW_SEC
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            self._timestamps.append(now)
            is_storm = len(self._timestamps) >= _RECONNECT_STORM_THRESHOLD
            if is_storm:
                RECONNECT_STORM_FLAG.set(1.0)
            else:
                RECONNECT_STORM_FLAG.set(0.0)
            return is_storm

    def is_storm(self) -> bool:
        now = time.monotonic()
        with self._lock:
            cutoff = now - _RECONNECT_STORM_WINDOW_SEC
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            active = len(self._timestamps) >= _RECONNECT_STORM_THRESHOLD
            RECONNECT_STORM_FLAG.set(1.0 if active else 0.0)
            return active

    def reset(self) -> None:
        with self._lock:
            self._timestamps.clear()
            RECONNECT_STORM_FLAG.set(0.0)


_reconnect_detector = _ReconnectStormDetector()


# ═══════════════════════════════════════════════════════════════════════
#  Public API — Execution Stage Timing
# ═══════════════════════════════════════════════════════════════════════


def record_exec_stage(stage: str, latency_ms: float) -> None:
    """Record latency for an execution stage."""
    EXEC_STAGE_LATENCY_MS.labels(stage=stage).observe(latency_ms)
    _exec_latency_pct.observe(stage, latency_ms)


def record_exec_outcome(outcome: str) -> None:
    """Record an execution outcome (success / broker_error / ...)."""
    EXEC_OUTCOME_TOTAL.labels(outcome=outcome).inc()


def exec_stage_summary(stage: str) -> PercentileSummary:
    """Return p50/p95/p99 for a specific execution stage."""
    return _exec_latency_pct.summary(stage)


def exec_all_stage_summaries() -> dict[str, PercentileSummary]:
    """Return summaries for all observed execution stages."""
    return _exec_latency_pct.all_summaries()


# ═══════════════════════════════════════════════════════════════════════
#  Public API — L12 Rate Tracking
# ═══════════════════════════════════════════════════════════════════════


def record_l12_outcome(verdict: str) -> None:
    """Record an L12 verdict for rate tracking.

    Maps verdict strings to canonical categories:
    - ``EXECUTE*`` → execute
    - ``HOLD`` → reject
    - ``NO_TRADE`` → reject
    - ``ABORT`` → reject
    - anything else → ambiguous
    """
    v = verdict.upper() if verdict else "UNKNOWN"
    if v.startswith("EXECUTE"):
        cat = "execute"
        _l12_reject_window.record(False)
        _l12_ambiguity_window.record(False)
    elif v in {"HOLD", "NO_TRADE", "ABORT"}:
        cat = "reject"
        _l12_reject_window.record(True)
        _l12_ambiguity_window.record(False)
    else:
        cat = "ambiguous"
        _l12_reject_window.record(False)
        _l12_ambiguity_window.record(True)

    L12_OUTCOME_TOTAL.labels(outcome=cat).inc()


def l12_reject_rate() -> float:
    """Return rolling L12 reject rate (HOLD/NO_TRADE/ABORT) over last N verdicts."""
    return _l12_reject_window.rate()


def l12_ambiguity_rate() -> float:
    """Return rolling L12 ambiguity rate over last N verdicts."""
    return _l12_ambiguity_window.rate()


def l12_rate_window_count() -> int:
    """Number of verdicts in the rate window."""
    return _l12_reject_window.count()


# ═══════════════════════════════════════════════════════════════════════
#  Public API — Freshness / Reconnect correlation
# ═══════════════════════════════════════════════════════════════════════


def record_reconnect_event() -> bool:
    """Record a feed reconnect. Returns True if reconnect storm detected."""
    return _reconnect_detector.record_reconnect()


def is_reconnect_storm() -> bool:
    """Check if a reconnect storm is currently active."""
    return _reconnect_detector.is_storm()


def flag_freshness_latency_correlation(symbol: str, is_correlated: bool) -> None:
    """Set the freshness–latency correlation flag for a symbol.

    Call this when high pipeline latency is observed alongside stale feeds.
    """
    FRESHNESS_LATENCY_CORR.labels(symbol=symbol).set(1.0 if is_correlated else 0.0)


# ═══════════════════════════════════════════════════════════════════════
#  Reset (for testing)
# ═══════════════════════════════════════════════════════════════════════


def reset_execution_metrics() -> None:
    """Reset all sliding-window state. For testing only."""
    global _l12_reject_window, _l12_ambiguity_window
    _exec_latency_pct.reset()
    _l12_reject_window = _RateCounter(_L12_RATE_WINDOW)
    _l12_ambiguity_window = _RateCounter(_L12_RATE_WINDOW)
    _reconnect_detector.reset()
