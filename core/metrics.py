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
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    10.0,
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
        super().__init__()
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
        super().__init__()
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
        super().__init__()
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
        super().__init__()
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

    def inc(self, amount: float = 1.0) -> None:
        """Increment labelless gauge."""
        if self._no_label is None:
            raise TypeError("Must call .labels() for labelled gauges")
        self._no_label.inc(amount)

    def dec(self, amount: float = 1.0) -> None:
        """Decrement labelless gauge."""
        if self._no_label is None:
            raise TypeError("Must call .labels() for labelled gauges")
        self._no_label.dec(amount)

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
        super().__init__()
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
            result: list[tuple[float, int]] = []
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
        super().__init__()
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
                    inst._metrics: list[Counter | Gauge | Histogram] = []  # pyright: ignore[reportInvalidTypeForm]
                    inst._names: set[str] = set()  # pyright: ignore[reportInvalidTypeForm]
                    inst._lock = threading.Lock()
                    cls._instance = inst
        return cls._instance

    @classmethod
    def reset_singleton(cls) -> None:
        """Reset singleton instance for test isolation."""
        with cls._init_lock:
            cls._instance = None

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
                val_str = str(int(value)) if value == int(value) and not math.isinf(value) else f"{value:g}"
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


def get_wolf_registry() -> MetricsRegistry:
    """Return the module-level registry that holds all pre-registered Wolf metrics.

    Unlike ``get_registry()``, this always returns the registry captured at
    import time (``_R``), which is guaranteed to contain every metric defined
    in this module even if ``MetricsRegistry.reset_singleton()`` is called
    during tests.
    """
    return _R


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

# Per-layer execution latency (seconds) — observe inside pipeline execute()
LAYER_LATENCY = _R.histogram(
    "wolf_layer_latency_seconds",
    "Per-layer execution latency in seconds",
    label_names=("layer", "symbol"),
)

# End-to-end tick-to-verdict latency (seconds)
TICK_TO_VERDICT_LATENCY = _R.histogram(
    "wolf_tick_to_verdict_seconds",
    "End-to-end latency from last tick timestamp to verdict emission",
    label_names=("symbol",),
)

# Runtime state gauges (refreshed on each /metrics scrape)
PIPELINE_LATENCY_MS = _R.gauge(
    "wolf_pipeline_latency_ms",
    "Latest pipeline execution latency in milliseconds",
)

ACTIVE_PAIRS = _R.gauge(
    "wolf_active_pairs",
    "Number of enabled trading pairs",
)

SYSTEM_HEALTHY = _R.gauge(
    "wolf_system_healthy",
    "System health flag (1=healthy, 0=degraded)",
)

# Signal conditioning observability (per symbol)
SIGNAL_CONDITIONED_SAMPLES = _R.gauge(
    "wolf_signal_conditioned_samples",
    "Number of samples after signal conditioning",
    label_names=("symbol",),
)

SIGNAL_NOISE_RATIO = _R.gauge(
    "wolf_signal_noise_ratio",
    "Estimated microstructure noise ratio removed by conditioning",
    label_names=("symbol",),
)

SIGNAL_QUALITY_SCORE = _R.gauge(
    "wolf_signal_quality_score",
    "Signal conditioning quality score (0-1)",
    label_names=("symbol",),
)

RQI_SCORE = _R.gauge(
    "wolf_reflex_rqi_score",
    "Reflex Quality Index (RQI) score (0-1)",
    label_names=("symbol",),
)

# ── Constitutional observability gauges ───────────────────────────────────

# Sovereignty level per symbol/level (GRANTED/RESTRICTED/REVOKED). Set to 1
# for the active level; the other two levels are set to 0 each pipeline run.
SOVEREIGNTY_LEVEL = _R.gauge(
    "wolf_sovereignty_level",
    "Sovereignty enforcement level (1=active, 0=inactive) per symbol and level",
    label_names=("symbol", "level"),
)

# Reflective drift ratio between Pass-1 and Pass-2 αβγ scores.
REFLECTIVE_DRIFT_RATIO = _R.gauge(
    "wolf_reflective_drift_ratio",
    "Two-pass reflective drift ratio (|pass1_abg - pass2_abg|)",
    label_names=("symbol",),
)

# TRQ-3D axis gauges (from synthesis.trq3d).
TRQ3D_ALPHA = _R.gauge(
    "wolf_trq3d_alpha",
    "TRQ-3D alpha axis value",
    label_names=("symbol",),
)

TRQ3D_BETA = _R.gauge(
    "wolf_trq3d_beta",
    "TRQ-3D beta axis value",
    label_names=("symbol",),
)

TRQ3D_GAMMA = _R.gauge(
    "wolf_trq3d_gamma",
    "TRQ-3D gamma axis value",
    label_names=("symbol",),
)

# Per-symbol score gauges.
TII_SCORE = _R.gauge(
    "wolf_tii_score",
    "Temporal Integrity Index (TII) score from L8",
    label_names=("symbol",),
)

FRPC_SCORE = _R.gauge(
    "wolf_frpc_score",
    "Fusion Reflex Power Coefficient (FRPC) energy score from L2",
    label_names=("symbol",),
)

CONF12_SCORE = _R.gauge(
    "wolf_conf12_score",
    "L12 configuration confidence score (conf12)",
    label_names=("symbol",),
)

# Account drawdown gauge — set by dashboard/risk layer, NOT by analysis pipeline.
ACCOUNT_DRAWDOWN_PERCENT = _R.gauge(
    "wolf_account_drawdown_percent",
    "Current account drawdown as a percentage of balance",
    label_names=("account_id",),
)

# ── Tick rate per symbol ───────────────────────────────────
wolf_tick_rate_total = Counter(
    "wolf_tick_rate_total",
    "Total ticks received per symbol",
    ["symbol"],
)

# ── WebSocket reconnection events ─────────────────────────
wolf_ws_reconnect_total = Counter(
    "wolf_ws_reconnect_total",
    "WebSocket reconnection events",
    ["source"],
)

# ── Vault health composite score ──────────────────────────
wolf_vault_sync_score = Gauge(
    "wolf_vault_sync_score",
    "Current vault health composite score (0-1)",
    ["symbol"],
)

# ══════════════════════════════════════════════════════════
#  Trading performance metrics
# ══════════════════════════════════════════════════════════

TRADES_TOTAL = _R.counter(
    "wolf_trades_total",
    "Total trades executed by outcome",
    label_names=("symbol", "outcome"),  # outcome: win, loss, breakeven
)

PNL_REALIZED_TOTAL = _R.counter(
    "wolf_pnl_realized_total",
    "Cumulative realized PnL in account currency",
    label_names=("symbol",),
)

PNL_REALIZED_CURRENT = _R.gauge(
    "wolf_pnl_realized_current",
    "Running realized PnL gauge for real-time tracking",
    label_names=("account_id",),
)

WIN_RATE = _R.gauge(
    "wolf_win_rate",
    "Current rolling win rate (0-1)",
    label_names=("symbol",),
)

DRAWDOWN_MAX_PERCENT = _R.gauge(
    "wolf_drawdown_max_percent",
    "Maximum drawdown percentage observed (high-water mark)",
    label_names=("account_id",),
)

DAILY_LOSS_PERCENT = _R.gauge(
    "wolf_daily_loss_percent",
    "Current daily loss as percentage of starting balance",
    label_names=("account_id",),
)

# ══════════════════════════════════════════════════════════
#  Feed health metrics
# ══════════════════════════════════════════════════════════

FEED_STALE_TOTAL = _R.counter(
    "wolf_feed_stale_total",
    "Number of feed stale events detected",
    label_names=("symbol",),
)

FEED_RECONNECT_TOTAL = _R.counter(
    "wolf_feed_reconnect_total",
    "Number of feed reconnection attempts",
    label_names=("source",),  # source: finnhub, forexfactory
)

# Ingest runtime observability (service-level)
INGEST_WS_CONNECTED = _R.gauge(
    "wolf_ingest_ws_connected",
    "Ingest websocket connection status (1=connected, 0=disconnected)",
)

INGEST_HEARTBEAT_AGE_SECONDS = _R.gauge(
    "wolf_ingest_heartbeat_age_seconds",
    "Seconds since last ingest producer heartbeat",
)

INGEST_FRESH_PAIRS = _R.gauge(
    "wolf_ingest_fresh_pairs",
    "Number of symbols with fresh ticks in ingest service",
)

ORCHESTRATOR_HEARTBEAT_AGE_SECONDS = _R.gauge(
    "wolf_orchestrator_heartbeat_age_seconds",
    "Seconds since last orchestrator heartbeat/state publish",
)

ORCHESTRATOR_READY = _R.gauge(
    "wolf_orchestrator_ready",
    "Orchestrator readiness derived from heartbeat age (1=ready, 0=not ready)",
)

ORCHESTRATOR_MODE = _R.gauge(
    "wolf_orchestrator_mode",
    "Orchestrator mode one-hot gauge (label=mode)",
    label_names=("mode",),
)

INGEST_CACHE_MODE = _R.gauge(
    "wolf_ingest_cache_mode",
    "Ingest startup cache mode as one-hot gauge by mode label",
    label_names=("mode",),
)

CIRCUIT_BREAKER_STATE = _R.gauge(
    "wolf_circuit_breaker_state",
    "Circuit breaker state (0=CLOSED, 1=HALF_OPEN, 2=OPEN)",
    label_names=("name",),
)

CIRCUIT_BREAKER_TRIPS = _R.counter(
    "wolf_circuit_breaker_trips_total",
    "Number of circuit breaker trip events (CLOSED→OPEN)",
    label_names=("name",),
)

# ══════════════════════════════════════════════════════════
#  Kill switch metrics
# ══════════════════════════════════════════════════════════

KILL_SWITCH_ACTIVE = _R.gauge(
    "wolf_kill_switch_active",
    "Kill switch status (1=tripped, 0=normal)",
)

KILL_SWITCH_TRIPS_TOTAL = _R.counter(
    "wolf_kill_switch_trips_total",
    "Number of times kill switch has been tripped",
    label_names=("reason",),
)

# ══════════════════════════════════════════════════════════
#  Monte Carlo observability gauges (L7)
# ══════════════════════════════════════════════════════════

L7_WIN_PROBABILITY = _R.gauge(
    "wolf_l7_win_probability",
    "L7 Monte Carlo bootstrap win probability (0-1)",
    label_names=("symbol",),
)

L7_PROFIT_FACTOR = _R.gauge(
    "wolf_l7_profit_factor",
    "L7 Monte Carlo profit factor (gross_profit / gross_loss)",
    label_names=("symbol",),
)

L7_RISK_OF_RUIN = _R.gauge(
    "wolf_l7_risk_of_ruin",
    "L7 Monte Carlo risk of ruin fraction (0-1)",
    label_names=("symbol",),
)

# ══════════════════════════════════════════════════════════
#  TIER 2 diagnostic gauges
# ══════════════════════════════════════════════════════════

TRQ3D_ENERGY = _R.gauge(
    "wolf_trq3d_energy",
    "TRQ-3D mean energy (mean|delta_price| / ATR)",
    label_names=("symbol",),
)

TRQ3D_DRIFT = _R.gauge(
    "wolf_trq3d_drift",
    "TRQ-3D drift (|price - VWAP| / price)",
    label_names=("symbol",),
)

TWMS_SCORE = _R.gauge(
    "wolf_twms_score",
    "Triple Wolf Momentum Score (MFI+CCI+RSI+Momentum composite, 0-1)",
    label_names=("symbol",),
)

EAF_SCORE = _R.gauge(
    "wolf_eaf_score",
    "Emotional Awareness Factor ((1-bias)*stability*focus*discipline, 0-1)",
    label_names=("symbol",),
)

WOLF_30PT_SCORE = _R.gauge(
    "wolf_30pt_score",
    "Wolf 30-Point discipline checklist score (0-30)",
    label_names=("symbol",),
)

FTA_SCORE = _R.gauge(
    "wolf_fta_score",
    "FTA composite score (f_score * t_score * fta_multiplier)",
    label_names=("symbol",),
)

REGIME_CONFIDENCE = _R.gauge(
    "wolf_regime_confidence",
    "L1 market regime detection confidence (0-1)",
    label_names=("symbol",),
)

VAULT_SYNC = _R.gauge(
    "wolf_vault_sync",
    "Vault sync composite score from sovereignty enforcement (0-1)",
    label_names=("symbol",),
)
