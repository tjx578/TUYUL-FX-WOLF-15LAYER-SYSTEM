"""
Pipeline Metrics Recorder.

Records Prometheus metrics from a completed pipeline result dict.
Pure observability — no execution side-effects.
"""

from __future__ import annotations

from typing import Any

from core.metrics import (
    GATE_RESULT,
    PIPELINE_DURATION,
    PIPELINE_ERROR,
    PIPELINE_RUNS,
    SIGNAL_TOTAL,
    VERDICT_TOTAL,
)


def record_pipeline_metrics(symbol: str, result: dict[str, Any]) -> None:
    """Record Prometheus metrics from a pipeline result.

    Covers: latency histogram, gate pass/fail, verdict counter,
    error counters, and actionable-signal counter.

    This is pure observability -- no execution side-effects.
    """
    PIPELINE_RUNS.labels(symbol=symbol).inc()

    latency_s = result.get("latency_ms", 0.0) / 1000.0
    PIPELINE_DURATION.labels(symbol=symbol).observe(latency_s)

    gates = result.get("l12_verdict", {}).get("gates_v74", {})
    for gate_key in (
        "gate_1_tii",
        "gate_2_montecarlo",
        "gate_3_frpc",
        "gate_4_conf12",
        "gate_5_rr",
        "gate_6_integrity",
        "gate_7_propfirm",
        "gate_8_drawdown",
        "gate_9_latency",
    ):
        gate_val = gates.get(gate_key, "FAIL")
        GATE_RESULT.labels(gate=gate_key, result=gate_val).inc()

    verdict = result.get("l12_verdict", {}).get("verdict", "HOLD")
    VERDICT_TOTAL.labels(symbol=symbol, verdict=verdict).inc()

    if verdict.startswith("EXECUTE_"):
        direction = verdict.replace("EXECUTE_", "")
        SIGNAL_TOTAL.labels(symbol=symbol, direction=direction).inc()

    for err in result.get("errors", []):
        code = "FATAL_ERROR" if err.startswith("FATAL_ERROR") else err
        PIPELINE_ERROR.labels(error_code=code).inc()
