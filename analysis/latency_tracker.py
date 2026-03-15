"""
Tick-to-candle-to-analysis latency tracker.

Tracks timing across three pipeline stages:
  1. tick_arrival   → candle_complete  (tick_to_candle_ms)
  2. candle_complete → analysis_start  (candle_to_analysis_ms)
  3. analysis_start  → verdict_emit    (analysis_duration_ms)

All observations are recorded on the shared Wolf-15 MetricsRegistry
histograms so they appear alongside existing pipeline metrics at
GET /metrics.

Usage::

    from analysis.latency_tracker import LatencyTracker

    tracker = LatencyTracker()

    # In tick handler
    tracker.record_tick(symbol)

    # When candle completes
    tracker.record_candle_complete(symbol)

    # In pipeline execute()
    tracker.record_analysis_start(symbol)
    tracker.record_verdict_emit(symbol)

Zone: analysis/ — pure observability, no execution side-effects.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from core.metrics import Histogram, get_registry

_R = get_registry()

# Histograms for each stage (milliseconds)
TICK_TO_CANDLE_LATENCY: Histogram = _R.histogram(
    "wolf_tick_to_candle_latency_ms",
    "Latency from last tick arrival to candle completion (ms)",
    label_names=("symbol",),
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)

CANDLE_TO_ANALYSIS_LATENCY: Histogram = _R.histogram(
    "wolf_candle_to_analysis_latency_ms",
    "Latency from candle completion to analysis trigger (ms)",
    label_names=("symbol",),
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000),
)

ANALYSIS_DURATION: Histogram = _R.histogram(
    "wolf_analysis_duration_ms",
    "Duration of analysis pipeline execution (ms)",
    label_names=("symbol",),
    buckets=(10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000),
)

END_TO_END_LATENCY: Histogram = _R.histogram(
    "wolf_tick_to_verdict_e2e_ms",
    "Full end-to-end latency from tick arrival to verdict emit (ms)",
    label_names=("symbol",),
    buckets=(10, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000),
)


@dataclass
class _SymbolTimestamps:
    """Mutable timestamp slots for a single symbol."""

    last_tick_ts: float = 0.0
    candle_complete_ts: float = 0.0
    analysis_start_ts: float = 0.0


class LatencyTracker:
    """Thread-safe per-symbol latency tracker for the tick→verdict pipeline.

    Singleton — one tracker across all pipeline invocations.
    """

    _instance: LatencyTracker | None = None
    _lock: threading.Lock
    _symbols: dict[str, _SymbolTimestamps]

    def __new__(cls) -> LatencyTracker:
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._lock = threading.Lock()
            inst._symbols = {}
            cls._instance = inst
        return cls._instance

    @classmethod
    def reset_singleton(cls) -> None:
        """Reset for testing."""
        cls._instance = None

    def _get(self, symbol: str) -> _SymbolTimestamps:
        ts = self._symbols.get(symbol)
        if ts is None:
            ts = _SymbolTimestamps()
            self._symbols[symbol] = ts
        return ts

    def record_tick(self, symbol: str) -> None:
        """Record timestamp when a tick arrives for a symbol."""
        with self._lock:
            self._get(symbol).last_tick_ts = time.monotonic()

    def record_candle_complete(self, symbol: str) -> None:
        """Record timestamp when a candle completes for a symbol.

        Also observes tick_to_candle latency if a tick was recorded.
        """
        now = time.monotonic()
        with self._lock:
            ts = self._get(symbol)
            ts.candle_complete_ts = now
            if ts.last_tick_ts > 0:
                latency_ms = (now - ts.last_tick_ts) * 1000.0
                TICK_TO_CANDLE_LATENCY.labels(symbol=symbol).observe(latency_ms)

    def record_analysis_start(self, symbol: str) -> None:
        """Record timestamp when analysis begins for a symbol.

        Also observes candle_to_analysis latency.
        """
        now = time.monotonic()
        with self._lock:
            ts = self._get(symbol)
            ts.analysis_start_ts = now
            if ts.candle_complete_ts > 0:
                latency_ms = (now - ts.candle_complete_ts) * 1000.0
                CANDLE_TO_ANALYSIS_LATENCY.labels(symbol=symbol).observe(latency_ms)

    def record_verdict_emit(self, symbol: str) -> None:
        """Record timestamp when verdict is emitted.

        Observes analysis_duration and end-to-end latency.
        """
        now = time.monotonic()
        with self._lock:
            ts = self._get(symbol)
            if ts.analysis_start_ts > 0:
                dur_ms = (now - ts.analysis_start_ts) * 1000.0
                ANALYSIS_DURATION.labels(symbol=symbol).observe(dur_ms)
            if ts.last_tick_ts > 0:
                e2e_ms = (now - ts.last_tick_ts) * 1000.0
                END_TO_END_LATENCY.labels(symbol=symbol).observe(e2e_ms)

    def get_last_tick_ts(self, symbol: str) -> float:
        """Return last tick monotonic timestamp (0 if none)."""
        with self._lock:
            return self._get(symbol).last_tick_ts

    def get_candle_complete_ts(self, symbol: str) -> float:
        """Return last candle completion monotonic timestamp (0 if none)."""
        with self._lock:
            return self._get(symbol).candle_complete_ts
