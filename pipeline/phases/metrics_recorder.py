"""
Pipeline Metrics Recorder.

Records Prometheus metrics from a completed pipeline result dict.
Pure observability — no execution side-effects.
"""

from __future__ import annotations

from typing import Any, cast

from core.metrics import (
    CONF12_SCORE,
    EAF_SCORE,
    FRPC_SCORE,
    FTA_SCORE,
    GATE_RESULT,
    L7_PROFIT_FACTOR,
    L7_RISK_OF_RUIN,
    L7_WIN_PROBABILITY,
    PIPELINE_DURATION,
    PIPELINE_ERROR,
    PIPELINE_RUNS,
    REFLECTIVE_DRIFT_RATIO,
    REGIME_CONFIDENCE,
    RQI_SCORE,
    SIGNAL_CONDITIONED_SAMPLES,
    SIGNAL_NOISE_RATIO,
    SIGNAL_QUALITY_SCORE,
    SIGNAL_TOTAL,
    SOVEREIGNTY_LEVEL,
    TII_SCORE,
    TRQ3D_ALPHA,
    TRQ3D_BETA,
    TRQ3D_DRIFT,
    TRQ3D_ENERGY,
    TRQ3D_GAMMA,
    TWMS_SCORE,
    VAULT_SYNC,
    VERDICT_TOTAL,
    WOLF_30PT_SCORE,
)
from services.shared.type_coerce import to_float as _to_float


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

    # P2-8: L12 outcome rate tracking (reject / ambiguity window)
    try:
        from monitoring.execution_metrics import record_l12_outcome  # noqa: PLC0415

        record_l12_outcome(verdict)
    except Exception:
        pass

    if verdict.startswith("EXECUTE_"):
        direction = verdict.replace("EXECUTE_", "")
        SIGNAL_TOTAL.labels(symbol=symbol, direction=direction).inc()

    for err in result.get("errors", []):
        code = "FATAL_ERROR" if err.startswith("FATAL_ERROR") else err
        PIPELINE_ERROR.labels(error_code=code).inc()

    # Signal conditioning observability (if available)
    conditioning = result.get("synthesis", {}).get("system", {}).get("signal_conditioning", {})
    if isinstance(conditioning, dict) and conditioning:
        conditioning_data = cast(dict[str, Any], conditioning)
        SIGNAL_CONDITIONED_SAMPLES.labels(symbol=symbol).set(_to_float(conditioning_data.get("samples_out", 0.0)))
        SIGNAL_NOISE_RATIO.labels(symbol=symbol).set(_to_float(conditioning_data.get("noise_ratio", 0.0)))
        SIGNAL_QUALITY_SCORE.labels(symbol=symbol).set(
            _to_float(conditioning_data.get("microstructure_quality_score", 0.0))
        )

    rqi = result.get("synthesis", {}).get("system", {}).get("rqi")
    if rqi is not None:
        RQI_SCORE.labels(symbol=symbol).set(_to_float(rqi, 0.0))

    # ── Sovereignty / drift observability ────────────────────────────────
    enforcement = result.get("enforcement")
    if isinstance(enforcement, dict):
        drift_ratio = enforcement.get("drift_ratio")
        if drift_ratio is not None:
            REFLECTIVE_DRIFT_RATIO.labels(symbol=symbol).set(_to_float(drift_ratio))

        execution_rights = enforcement.get("execution_rights", "")
        if execution_rights in ("GRANTED", "RESTRICTED", "REVOKED"):
            for level in ("GRANTED", "RESTRICTED", "REVOKED"):
                SOVEREIGNTY_LEVEL.labels(symbol=symbol, level=level).set(1.0 if level == execution_rights else 0.0)

    # ── TRQ-3D axis gauges ───────────────────────────────────────────────
    trq3d = result.get("synthesis", {}).get("trq3d", {})
    if isinstance(trq3d, dict) and trq3d:
        TRQ3D_ALPHA.labels(symbol=symbol).set(_to_float(trq3d.get("alpha", 0.0)))
        TRQ3D_BETA.labels(symbol=symbol).set(_to_float(trq3d.get("beta", 0.0)))
        TRQ3D_GAMMA.labels(symbol=symbol).set(_to_float(trq3d.get("gamma", 0.0)))

    # ── Per-symbol score gauges ──────────────────────────────────────────
    layers_data = result.get("synthesis", {}).get("layers", {})
    if isinstance(layers_data, dict):
        tii_sym = layers_data.get("L8_tii_sym")
        if tii_sym is not None:
            TII_SCORE.labels(symbol=symbol).set(_to_float(tii_sym))
        conf12 = layers_data.get("conf12")
        if conf12 is not None:
            CONF12_SCORE.labels(symbol=symbol).set(_to_float(conf12))

    fusion_frpc = result.get("synthesis", {}).get("fusion_frpc", {})
    if isinstance(fusion_frpc, dict):
        frpc_energy = fusion_frpc.get("frpc_energy")
        if frpc_energy is not None:
            FRPC_SCORE.labels(symbol=symbol).set(_to_float(frpc_energy))

    # ── Monte Carlo observability (L7) ───────────────────────────────────
    synthesis = result.get("synthesis", {})
    mc_win = synthesis.get("layers", {}).get("L7_monte_carlo_win")
    if mc_win is not None:
        L7_WIN_PROBABILITY.labels(symbol=symbol).set(_to_float(mc_win))

    mc_pf = synthesis.get("profit_factor")
    if mc_pf is not None:
        L7_PROFIT_FACTOR.labels(symbol=symbol).set(_to_float(mc_pf))

    mc_ror = synthesis.get("risk_of_ruin")
    if mc_ror is not None:
        L7_RISK_OF_RUIN.labels(symbol=symbol).set(_to_float(mc_ror))

    # ── TIER 2 diagnostic gauges ─────────────────────────────────────────
    trq3d_energy = trq3d.get("mean_energy") if isinstance(trq3d, dict) else None
    if trq3d_energy is not None:
        TRQ3D_ENERGY.labels(symbol=symbol).set(_to_float(trq3d_energy))

    trq3d_drift = trq3d.get("drift") if isinstance(trq3d, dict) else None
    if trq3d_drift is not None:
        TRQ3D_DRIFT.labels(symbol=symbol).set(_to_float(trq3d_drift))

    twms = layers_data.get("L8_twms_score") if isinstance(layers_data, dict) else None
    if twms is not None:
        TWMS_SCORE.labels(symbol=symbol).set(_to_float(twms))

    eaf = synthesis.get("wolf_discipline", {}).get("eaf_score")
    if eaf is not None:
        EAF_SCORE.labels(symbol=symbol).set(_to_float(eaf))

    scores = synthesis.get("scores", {})
    wolf_30pt = scores.get("wolf_30_point")
    if wolf_30pt is not None:
        WOLF_30PT_SCORE.labels(symbol=symbol).set(_to_float(wolf_30pt))

    fta = scores.get("fta_score")
    if fta is not None:
        FTA_SCORE.labels(symbol=symbol).set(_to_float(fta))

    regime_conf = layers_data.get("L1_context_coherence") if isinstance(layers_data, dict) else None
    if regime_conf is not None:
        REGIME_CONFIDENCE.labels(symbol=symbol).set(_to_float(regime_conf))

    vault_sync = (
        result.get("enforcement", {}).get("vault_sync") if isinstance(result.get("enforcement"), dict) else None
    )
    if vault_sync is not None:
        VAULT_SYNC.labels(symbol=symbol).set(_to_float(vault_sync))
