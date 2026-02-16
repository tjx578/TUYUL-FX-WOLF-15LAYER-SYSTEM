"""Prometheus metrics collector for the Wolf-15 dashboard.

Zone: dashboard (observability). No execution or analysis authority.
Exposes system health, verdict throughput, and risk state counters
for external monitoring (Grafana / Alertmanager / etc.).
"""

from __future__ import annotations

import logging

from typing import Any, cast

logger = logging.getLogger(__name__)

# ── In-process metric store ──────────────────────────────────────────
# Uses prometheus_client if available; falls back to a minimal
# in-memory implementation so the app boots without the dependency.

try:
    from prometheus_client import (  # pyright: ignore[reportMissingImports]
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        Info,
        generate_latest,
    )

    _HAS_PROM = True
except ImportError:  # pragma: no cover
    _HAS_PROM = False
    CONTENT_TYPE_LATEST = "text/plain; charset=utf-8"

    Counter = None  # type: ignore[assignment]
    Gauge = None  # type: ignore[assignment]
    Histogram = None  # type: ignore[assignment]
    Info = None  # type: ignore[assignment]

    def generate_latest(*_: Any) -> bytes:  # type: ignore[misc]
        return b"# prometheus_client not installed\n"


# ── Metric definitions ───────────────────────────────────────────────

VERDICT_TOTAL: Any
VERDICT_LATENCY: Any
GATE_FAILURES: Any
FEED_STALE_TOTAL: Any
ACTIVE_SIGNALS: Any
RISK_GUARD_BLOCKS: Any
WS_CONNECTIONS: Any
POLLING_FALLBACK_TOTAL: Any
BUILD_INFO: Any

if _HAS_PROM:
    VERDICT_TOTAL = cast("type[Any]", Counter)(
        "wolf15_verdict_total",
        "Total L12 verdicts produced",
        ["verdict", "pair"],
    )
    VERDICT_LATENCY = cast("type[Any]", Histogram)(
        "wolf15_verdict_latency_seconds",
        "L12 verdict generation latency",
        buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )
    GATE_FAILURES = cast("type[Any]", Counter)(
        "wolf15_gate_failures_total",
        "Constitutional gate failures",
        ["gate"],
    )
    FEED_STALE_TOTAL = cast("type[Any]", Counter)(
        "wolf15_feed_stale_total",
        "Feed staleness circuit breaker activations",
        ["pair"],
    )
    ACTIVE_SIGNALS = cast("type[Any]", Gauge)(
        "wolf15_active_signals",
        "Currently active (unexpired) L12 signals",
    )
    RISK_GUARD_BLOCKS = cast("type[Any]", Counter)(
        "wolf15_risk_guard_blocks_total",
        "Prop firm risk guard blocks",
        ["code"],
    )
    WS_CONNECTIONS = cast("type[Any]", Gauge)(
        "wolf15_ws_connections",
        "Active WebSocket connections",
    )
    POLLING_FALLBACK_TOTAL = cast("type[Any]", Counter)(
        "wolf15_polling_fallback_total",
        "HTTP polling fallback requests (WS unavailable)",
    )
    BUILD_INFO = cast("type[Any]", Info)(
        "wolf15_build",
        "Build and schema information",
    )
    BUILD_INFO.info({"schema": "v7.4r∞", "system": "wolf-15-layer"})
else:
    # Stub metrics — no-op when prometheus_client is absent
    class _Stub:
        """No-op metric stub."""

        def labels(self, *_: Any, **__: Any) -> _Stub:
            return self

        def inc(self, *_: Any, **__: Any) -> None:
            pass

        def dec(self, *_: Any, **__: Any) -> None:
            pass

        def set(self, *_: Any, **__: Any) -> None:
            pass

        def observe(self, *_: Any, **__: Any) -> None:
            pass

        def info(self, *_: Any, **__: Any) -> None:
            pass

    _stub = _Stub()  # type: ignore[assignment]
    VERDICT_TOTAL = _stub  # type: ignore[assignment]
    VERDICT_LATENCY = _stub  # type: ignore[assignment]
    GATE_FAILURES = _stub  # type: ignore[assignment]
    FEED_STALE_TOTAL = _stub  # type: ignore[assignment]
    ACTIVE_SIGNALS = _stub  # type: ignore[assignment]
    RISK_GUARD_BLOCKS = _stub  # type: ignore[assignment]
    WS_CONNECTIONS = _stub  # type: ignore[assignment]
    POLLING_FALLBACK_TOTAL = _stub  # type: ignore[assignment]
    BUILD_INFO = _stub  # type: ignore[assignment]


# ── Convenience helpers ──────────────────────────────────────────────


def record_verdict(pair: str, verdict: str, latency_s: float) -> None:
    """Record an L12 verdict emission."""
    VERDICT_TOTAL.labels(verdict=verdict, pair=pair).inc()  # type: ignore[union-attr]
    VERDICT_LATENCY.observe(latency_s)  # type: ignore[union-attr]


def record_gate_failure(gate: str) -> None:
    """Record a constitutional gate failure."""
    GATE_FAILURES.labels(gate=gate).inc()  # type: ignore[union-attr]


def record_feed_stale(pair: str) -> None:
    """Record a feed staleness circuit breaker activation."""
    FEED_STALE_TOTAL.labels(pair=pair).inc()  # type: ignore[union-attr]


def record_risk_block(code: str) -> None:
    """Record a prop firm risk guard block."""
    RISK_GUARD_BLOCKS.labels(code=code).inc()  # type: ignore[union-attr]


def get_metrics_bytes() -> tuple[bytes, str]:
    """Return (body, content_type) for the /metrics endpoint."""
    return generate_latest(), CONTENT_TYPE_LATEST  # type: ignore[return-value]
