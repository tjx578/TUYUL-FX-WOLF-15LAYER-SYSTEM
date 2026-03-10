"""
Pipeline observability metrics — real-time tick/WS telemetry.

All metrics are registered against the shared wolf-15 MetricsRegistry
(prometheus-compatible) and exposed via GET /metrics.

Metrics
-------
wolf_ticks_received_total               — every raw tick that enters ingest
wolf_ticks_rejected_spike_total         — ticks dropped by SpikeFilter
wolf_ticks_rejected_dedup_total         — ticks dropped by DedupCache
wolf_ws_connections_active              — current open WS connections (gauge)
wolf_redis_stream_lag_seconds           — consumer group read lag (histogram)
wolf_ingest_pipeline_latency_ms         — ingest tick→context latency per stage

Usage (ingest path)
-------------------
    from monitoring.pipeline_metrics import (
        tick_received,
        tick_rejected_spike,
        tick_rejected_dedup,
        ws_connection_opened,
        ws_connection_closed,
        record_redis_lag,
        record_pipeline_latency,
    )

    tick_received(symbol="EURUSD")
    tick_rejected_spike(symbol="EURUSD")
    tick_rejected_dedup(symbol="EURUSD")
    ws_connection_opened()
    ws_connection_closed()
    record_redis_lag(stream="tick_stream", lag_sec=0.012)
    record_pipeline_latency(stage="tick_to_context", latency_ms=42.3)
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.constants import get_max_latency_ms

from core.metrics import Counter, Gauge, Histogram, get_registry

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_R = get_registry()

# ── Tick counters ──────────────────────────────────────────────────────────

TICKS_RECEIVED: Counter = _R.counter(
    "wolf_ticks_received_total",
    "Total raw ticks received by the ingest pipeline",
    label_names=("symbol",),
)

TICKS_REJECTED_SPIKE: Counter = _R.counter(
    "wolf_ticks_rejected_spike_total",
    "Ticks dropped by SpikeFilter (anomalous price movement)",
    label_names=("symbol",),
)

TICKS_REJECTED_DEDUP: Counter = _R.counter(
    "wolf_ticks_rejected_dedup_total",
    "Ticks dropped by DedupCache (duplicate within TTL window)",
    label_names=("symbol",),
)

# ── WebSocket connections ──────────────────────────────────────────────────

WS_CONNECTIONS_ACTIVE: Gauge = _R.gauge(
    "wolf_ws_connections_active",
    "Number of currently open WebSocket connections",
    label_names=(),
)

# ── Redis stream lag ───────────────────────────────────────────────────────

REDIS_STREAM_LAG: Histogram = _R.histogram(
    "wolf_redis_stream_lag_seconds",
    "Consumer group read lag for Redis streams (seconds behind tip)",
    label_names=("stream",),
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# ── Pipeline latency ───────────────────────────────────────────────────────

PIPELINE_LATENCY: Histogram = _R.histogram(
    "wolf_ingest_pipeline_latency_ms",
    "End-to-end latency per pipeline stage in milliseconds",
    label_names=("stage",),
    # stage examples: "tick_to_context", "context_to_verdict", "verdict_to_ws"
    buckets=(1, 5, 10, 25, 50, 100, 200, 500, 1000, 2000, 5000),
)

SLO_BREACH_TOTAL: Counter = _R.counter(
    "wolf_slo_breach_total",
    "Number of SLO threshold breaches by metric and stage",
    label_names=("metric", "stage"),
)

# ---------------------------------------------------------------------------
# Helper functions (call-site convenience)
# ---------------------------------------------------------------------------


def tick_received(symbol: str = "UNKNOWN") -> None:
    """Record one incoming tick for *symbol*."""
    TICKS_RECEIVED.labels(symbol=symbol.upper()).inc()


def tick_rejected_spike(symbol: str = "UNKNOWN") -> None:
    """Record one spike-filtered tick for *symbol*."""
    TICKS_REJECTED_SPIKE.labels(symbol=symbol.upper()).inc()


def tick_rejected_dedup(symbol: str = "UNKNOWN") -> None:
    """Record one deduplicated tick for *symbol*."""
    TICKS_REJECTED_DEDUP.labels(symbol=symbol.upper()).inc()


def ws_connection_opened() -> None:
    """Increment active WebSocket connections gauge."""
    WS_CONNECTIONS_ACTIVE.labels().inc()


def ws_connection_closed() -> None:
    """Decrement active WebSocket connections gauge (floor = 0)."""
    WS_CONNECTIONS_ACTIVE.labels().dec()


def record_redis_lag(stream: str, lag_sec: float) -> None:
    """Record consumer-group read lag for *stream* in seconds."""
    REDIS_STREAM_LAG.labels(stream=stream).observe(lag_sec)


def record_pipeline_latency(stage: str, latency_ms: float) -> None:
    """Record end-to-end latency for a named pipeline *stage* in milliseconds."""
    PIPELINE_LATENCY.labels(stage=stage).observe(latency_ms)


@dataclass(frozen=True)
class SLOStageStatus:
    stage: str
    samples: int
    avg_latency_ms: float
    threshold_ms: float
    breach: bool


def evaluate_latency_slo(
    latency_threshold_ms: float | None = None,
    min_samples: int = 5,
) -> dict[str, object]:
    """Compute per-stage latency SLO status from the histogram state."""
    threshold = float(latency_threshold_ms or get_max_latency_ms())
    results: list[SLOStageStatus] = []
    breaches = 0

    for key, child in PIPELINE_LATENCY._children.items():  # noqa: SLF001
        labels = dict(key)
        stage = labels.get("stage", "unknown")
        samples = int(child.count)
        if samples < max(1, min_samples):
            continue

        avg_latency = float(child.sum / samples) if samples else 0.0
        breach = avg_latency > threshold
        if breach:
            breaches += 1
            SLO_BREACH_TOTAL.labels(metric="pipeline_latency_ms", stage=stage).inc()

        results.append(
            SLOStageStatus(
                stage=stage,
                samples=samples,
                avg_latency_ms=round(avg_latency, 3),
                threshold_ms=threshold,
                breach=breach,
            )
        )

    results.sort(key=lambda item: item.stage)
    return {
        "metric": "pipeline_latency_ms",
        "threshold_ms": threshold,
        "min_samples": max(1, min_samples),
        "breaches": breaches,
        "healthy": breaches == 0,
        "stages": [
            {
                "stage": row.stage,
                "samples": row.samples,
                "avg_latency_ms": row.avg_latency_ms,
                "threshold_ms": row.threshold_ms,
                "breach": row.breach,
            }
            for row in results
        ],
    }
