"""
Prometheus-compatible metrics collector for Wolf-15 Layer System.

Zero external dependencies — outputs Prometheus text exposition format
directly, ready for scraping by Prometheus or any compatible agent.

Metric types:
    Counter   — monotonically increasing integer
    Gauge     — value that can go up or down
    Histogram — distribution of observations in configurable buckets

Thread-safe: all mutations are guarded by a single ``threading.Lock`` per
metric instance.

Usage::

    from core.metrics import get_registry

    registry = get_registry()
    MY_COUNTER = registry.counter(
        "wolf_my_counter_total", "A test counter", label_names=("symbol",)
    )
    MY_COUNTER.labels(symbol="EURUSD").inc()

    # Expose at /metrics
    text = registry.exposition()
"""

from __future__ import annotations

import math
import threading

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# ──────────────────────────────────────────────────────────
#  Default histogram buckets (seconds — pipeline latency)
# ──────────────────────────────────────────────────────────

DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.075,
    0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0,
)


# ══════════════════════════════════════════════════════════
#  Label key helpers
# ══════════════════════════════════════════════════════════

def _label_key(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    """Stable hashable key for a label dict."""
    return tuple(sorted(labels.items()))


def _label_str(labels: dict[str, str]) -> str:
    """Format labels for Prometheus text exposition."""
    if not labels:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return "{" + inner + "}"


# ══════════════════════════════════════════════════════════
#  Counter
# ══════════════════════════════════════════════════════════

class _CounterChild:
    """A single labelled counter series."""

    __slots__ = ("_lock", "_value")

    def __init__(self) -> None:
        self._value: float = 0.0
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0) -> None:
        if amount < 0:
            raise ValueError("Counter.inc amount must be >= 0")
        with self._lock:
            self._value += amount

    @property
    def value(self) -> float:
        return self._value


class Counter:
    """Prometheus-style monotonic counter."""

    def __init__(self, name: str, help_text: str, label_names: Sequence[str] = ()) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self._children: dict[tuple[tuple[str, str], ...], _CounterChild] = {}
        self._lock = threading.Lock()
        # Labelless child for counters with no labels
        if not label_names:
            self._no_label = _CounterChild()
        else:
            self._no_label = None

    def labels(self, **kwargs: str) -> _CounterChild:
        key = _label_key(kwargs)
        with self._lock:
            child = self._children.get(key)
            if child is None:
                child = _CounterChild()
                self._children[key] = child
        return child

    def inc(self, amount: float = 1.0) -> None:
        """Increment labelless counter."""
        if self._no_label is None:
            raise TypeError("Must call .labels() for labelled counters")
        self._no_label.inc(amount)

    def collect(self) -> list[tuple[str, dict[str, str], float]]:
        """Return list of (metric_name, labels, value)."""
        samples: list[tuple[str, dict[str, str], float]] = []
        if self._no_label is not None:
            samples.append((self.name, {}, self._no_label.value))
        with self._lock:
            for key, child in self._children.items():
                samples.append((self.name, dict(key), child.value))
        return samples


# ══════════════════════════════════════════════════════════
#  Gauge
# ══════════════════════════════════════════════════════════

class _GaugeChild:
    """A single labelled gauge series."""

    __slots__ = ("_lock", "_value")

    def __init__(self) -> None:
        self._value: float = 0.0
        self._lock = threading.Lock()

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value -= amount

    @property
    def value(self) -> float:
        return self._value


class Gauge:
    """Prometheus-style gauge."""

    def __init__(self, name: str, help_text: str, label_names: Sequence[str] = ()) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self._children: dict[tuple[tuple[str, str], ...], _GaugeChild] = {}
        self._lock = threading.Lock()
        if not label_names:
            self._no_label = _GaugeChild()
        else:
            self._no_label = None

    def labels(self, **kwargs: str) -> _GaugeChild:
        key = _label_key(kwargs)
        with self._lock:
            child = self._children.get(key)
            if child is None:
                child = _GaugeChild()
                self._children[key] = child
        return child

    def set(self, value: float) -> None:
        if self._no_label is None:
            raise TypeError("Must call .labels() for labelled gauges")
        self._no_label.set(value)

    def collect(self) -> list[tuple[str, dict[str, str], float]]:
        samples: list[tuple[str, dict[str, str], float]] = []
        if self._no_label is not None:
            samples.append((self.name, {}, self._no_label.value))
        with self._lock:
            for key, child in self._children.items():
                samples.append((self.name, dict(key), child.value))
        return samples


# ══════════════════════════════════════════════════════════
#  Histogram
# ══════════════════════════════════════════════════════════

class _HistogramChild:
    """A single labelled histogram series."""

    __slots__ = ("_bucket_counts", "_buckets", "_count", "_lock", "_sum")

    def __init__(self, buckets: tuple[float, ...]) -> None:
        self._buckets = buckets
        self._bucket_counts = [0] * len(buckets)
        self._sum: float = 0.0
        self._count: int = 0
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        with self._lock:
            self._sum += value
            self._count += 1
            for i, bound in enumerate(self._buckets):
                if value <= bound:
                    self._bucket_counts[i] += 1
                    break

    def collect_buckets(self) -> list[tuple[float, int]]:
        """Return (le, cumulative_count) pairs."""
        with self._lock:
            cumulative = 0
            result = []
            for i, bound in enumerate(self._buckets):
                cumulative += self._bucket_counts[i]
                result.append((bound, cumulative))
            result.append((math.inf, self._count))
        return result

    @property
    def sum(self) -> float:
        return self._sum

    @property
    def count(self) -> int:
        return self._count


class Histogram:
    """Prometheus-style histogram."""

    def __init__(
        self,
        name: str,
        help_text: str,
        label_names: Sequence[str] = (),
        buckets: tuple[float, ...] | None = None,
    ) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self._buckets = buckets or DEFAULT_BUCKETS
        self._children: dict[tuple[tuple[str, str], ...], _HistogramChild] = {}
        self._lock = threading.Lock()
        if not label_names:
            self._no_label = _HistogramChild(self._buckets)
        else:
            self._no_label = None

    def labels(self, **kwargs: str) -> _HistogramChild:
        key = _label_key(kwargs)
        with self._lock:
            child = self._children.get(key)
            if child is None:
                child = _HistogramChild(self._buckets)
                self._children[key] = child
        return child

    def observe(self, value: float) -> None:
        """Observe a value on a labelless histogram."""
        if self._no_label is None:
            raise TypeError("Must call .labels() for labelled histograms")
        self._no_label.observe(value)

    def collect(self) -> list[tuple[str, dict[str, str], float]]:
        """Return all samples (bucket, sum, count) for exposition."""
        samples: list[tuple[str, dict[str, str], float]] = []

        def _collect_child(base_labels: dict[str, str], child: _HistogramChild) -> None:
            for le, cum in child.collect_buckets():
                le_str = "+Inf" if math.isinf(le) else f"{le:g}"
                lbl = {**base_labels, "le": le_str}
                samples.append((f"{self.name}_bucket", lbl, float(cum)))
            samples.append((f"{self.name}_sum", base_labels, child.sum))
            samples.append((f"{self.name}_count", base_labels, float(child.count)))

        if self._no_label is not None:
            _collect_child({}, self._no_label)
        with self._lock:
            for key, child in self._children.items():
                _collect_child(dict(key), child)
        return samples


# ══════════════════════════════════════════════════════════
#  MetricsRegistry (singleton)
# ══════════════════════════════════════════════════════════

class MetricsRegistry:
    """Central registry holding all registered metrics.

    Provides helpers to create Counter / Gauge / Histogram instances and
    exposes a single ``exposition()`` method that returns the complete
    Prometheus text-format payload.
    """

    _instance: MetricsRegistry | None = None
    _init_lock = threading.Lock()
    _metrics: list[Counter | Gauge | Histogram]
    _names: set[str]
    _lock: threading.Lock

    def __new__(cls) -> MetricsRegistry:
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._metrics: list[Counter | Gauge | Histogram] = [] # pyright: ignore[reportInvalidTypeForm]
                    inst._names: set[str] = set() # pyright: ignore[reportInvalidTypeForm]
                    inst._lock = threading.Lock()
                    cls._instance = inst
        return cls._instance

    # ── factory methods ──────────────────────────────────

    def counter(
        self,
        name: str,
        help_text: str,
        label_names: Sequence[str] = (),
    ) -> Counter:
        with self._lock:
            if name in self._names:
                # return already-registered metric
                for m in self._metrics:
                    if m.name == name:
                        return m  # type: ignore[return-value]
            c = Counter(name, help_text, label_names)
            self._metrics.append(c)
            self._names.add(name)
            return c

    def gauge(
        self,
        name: str,
        help_text: str,
        label_names: Sequence[str] = (),
    ) -> Gauge:
        with self._lock:
            if name in self._names:
                for m in self._metrics:
                    if m.name == name:
                        return m  # type: ignore[return-value]
            g = Gauge(name, help_text, label_names)
            self._metrics.append(g)
            self._names.add(name)
            return g

    def histogram(
        self,
        name: str,
        help_text: str,
        label_names: Sequence[str] = (),
        buckets: tuple[float, ...] | None = None,
    ) -> Histogram:
        with self._lock:
            if name in self._names:
                for m in self._metrics:
                    if m.name == name:
                        return m  # type: ignore[return-value]
            h = Histogram(name, help_text, label_names, buckets)
            self._metrics.append(h)
            self._names.add(name)
            return h

    # ── exposition ───────────────────────────────────────

    def exposition(self) -> str:
        """Render all registered metrics in Prometheus text exposition format.

        Returns:
            UTF-8 string ready to return as ``text/plain; version=0.0.4``.
        """
        lines: list[str] = []
        with self._lock:
            metrics_snapshot = list(self._metrics)

        for metric in metrics_snapshot:
            mtype = "counter"
            if isinstance(metric, Gauge):
                mtype = "gauge"
            elif isinstance(metric, Histogram):
                mtype = "histogram"

            lines.append(f"# HELP {metric.name} {metric.help_text}")
            lines.append(f"# TYPE {metric.name} {mtype}")

            for sample_name, labels, value in metric.collect():
                label_str = _label_str(labels)
                # Format: integer if whole number, else float
                if value == int(value) and not math.isinf(value):
                    val_str = str(int(value))
                else:
                    val_str = f"{value:g}"
                lines.append(f"{sample_name}{label_str} {val_str}")

        lines.append("")  # trailing newline
        return "\n".join(lines)

    def reset(self) -> None:
        """Clear all metrics — primarily for testing."""
        with self._lock:
            self._metrics.clear()
            self._names.clear()


def get_registry() -> MetricsRegistry:
    """Return the singleton ``MetricsRegistry``."""
    return MetricsRegistry()


# ══════════════════════════════════════════════════════════
#  Pre-registered Wolf metrics
# ══════════════════════════════════════════════════════════
#
#  Importing this module automatically registers the standard
#  Wolf metrics.  Other modules should import them from here.
# ══════════════════════════════════════════════════════════

_R = get_registry()

# Pipeline execution latency (seconds)
PIPELINE_DURATION = _R.histogram(
    "wolf_pipeline_duration_seconds",
    "Pipeline execution latency in seconds",
    label_names=("symbol",),
)

# 9-gate pass / fail counter
GATE_RESULT = _R.counter(
    "wolf_pipeline_gate_result_total",
    "Gate evaluation results",
    label_names=("gate", "result"),
)

# L12 verdict counter
VERDICT_TOTAL = _R.counter(
    "wolf_pipeline_verdict_total",
    "L12 verdict outcomes",
    label_names=("symbol", "verdict"),
)

# Pipeline error counter (by error code)
PIPELINE_ERROR = _R.counter(
    "wolf_pipeline_error_total",
    "Pipeline errors by code",
    label_names=("error_code",),
)

# Per-symbol feed age gauge (seconds since last tick)
FEED_AGE = _R.gauge(
    "wolf_feed_age_seconds",
    "Seconds since last tick for each symbol",
    label_names=("symbol",),
)

# Trade signal frequency (only EXECUTE_BUY / EXECUTE_SELL verdicts)
SIGNAL_TOTAL = _R.counter(
    "wolf_signal_total",
    "Actionable trade signals emitted",
    label_names=("symbol", "direction"),
)

# Pipeline executions counter (overall)
PIPELINE_RUNS = _R.counter(
    "wolf_pipeline_runs_total",
    "Total pipeline executions",
    label_names=("symbol",),
)

# Warmup gate block counter
WARMUP_BLOCKED = _R.counter(
    "wolf_warmup_blocked_total",
    "Pipeline runs blocked by warmup gate",
    label_names=("symbol",),
)

# Signal throttle counter (verdict downgraded EXECUTE → HOLD)
SIGNAL_THROTTLED = _R.counter(
    "wolf_signal_throttled_total",
    "EXECUTE verdicts downgraded to HOLD by signal rate throttle",
    label_names=("symbol",),
)
