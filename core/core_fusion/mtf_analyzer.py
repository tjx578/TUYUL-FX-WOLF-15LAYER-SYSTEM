"""MTF Alignment Analyzer + Coherence Auditor."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from ._types import MTF_TIMEFRAMES, CoherenceAudit
from ._utils import _clamp01


def multi_timeframe_alignment_analyzer(
    biases: dict[str, float],
    rsi_values: dict[str, float],
    reflective_intensity: float = 1.0,
    trq_energy: float = 1.0,
    alpha: float = 1.0,
    beta: float = 1.0,
    gamma: float = 1.0,
    integrity_index: float = 0.97,
    symbol: str | None = None,
    pair: str | None = None,
    trade_id: str | None = None,
) -> dict[str, Any]:
    """Analyze cross-timeframe bias alignment."""
    err = _validate_mtf_inputs(biases, rsi_values, MTF_TIMEFRAMES)
    if err:
        return {"status": "Invalid timeframe data", "detail": err}

    anchor = biases["H4"]
    aligned = [tf for tf in MTF_TIMEFRAMES if biases[tf] == anchor]
    ar = len(aligned) / len(MTF_TIMEFRAMES)

    rsi_s = [float(rsi_values[tf]) for tf in MTF_TIMEFRAMES]
    rv = statistics.pstdev(rsi_s) if len(rsi_s) > 1 else 0.0
    rc = max(0.0, 1.0 - (rv / 25))

    bs = ar * rc * reflective_intensity * trq_energy * ((alpha + beta + gamma) / 3)
    if bs >= 0.85:
        rs = "Strong Alignment"
    elif bs >= 0.65:
        rs = "Moderate Alignment"
    elif bs >= 0.45:
        rs = "Weak Alignment"
    else:
        rs = "Disaligned"

    tci = (bs * integrity_index) / (1 + rv / 50)

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "alignment_ratio": round(ar, 3),
        "rsi_variance": round(rv, 3),
        "rsi_coherence": round(rc, 3),
        "bias_strength": round(bs, 3),
        "meta_sync": round((alpha + beta + gamma) / 3, 3),
        "reflective_intensity": round(reflective_intensity, 3),
        "trq_energy": round(trq_energy, 3),
        "integrity_index": round(integrity_index, 3),
        "time_coherence_index": round(tci, 3),
        "regime_state": rs,
        "status": "ok",
        "symbol": symbol,
        "pair": pair,
        "trade_id": trade_id,
    }


def _validate_mtf_inputs(
    biases: dict[str, float], rsi_values: dict[str, float], timeframes: Iterable[str]
) -> str | None:
    tfs = list(timeframes)
    mb = [tf for tf in tfs if tf not in biases]
    mr = [tf for tf in tfs if tf not in rsi_values]
    if mb or mr:
        return f"Missing data for: {mb + mr}"
    if not all(isinstance(biases[tf], (int, float)) and math.isfinite(biases[tf]) for tf in tfs):
        return "Bias values must be finite numbers."
    if not all(isinstance(rsi_values[tf], (int, float)) and math.isfinite(rsi_values[tf]) for tf in tfs):
        return "RSI values must be finite numbers."
    return None


def audit_reflective_coherence(
    *,
    mtf_data: list[dict[str, Any]] | None = None,
    lookback: int = 64,
    divergence_threshold: float = 0.22,
    gate_threshold: float = 0.96,
) -> dict[str, Any]:
    """Audit reflective coherence from MTF alignment data."""
    ts = datetime.now(UTC).isoformat()
    default = CoherenceAudit(
        timestamp=ts,
        lookback=lookback,
        reflective_coherence=0.97,
        divergence_window=False,
        divergence_alert="✅ Default Stable",
        stability_state="Stable",
        gate_threshold=gate_threshold,
        gate_pass=True,
    ).as_dict()

    if not mtf_data or len(mtf_data) < lookback:
        return default

    recent = mtf_data[-lookback:]
    bs = [float(x.get("bias_strength", 0.0)) for x in recent if "bias_strength" in x]
    ci = [float(x.get("time_coherence_index", 0.0)) for x in recent if "time_coherence_index" in x]
    if not ci:
        default["divergence_alert"] = "✅ No data"
        return default

    avg_s = statistics.mean(bs) if bs else 0.0
    var_s = statistics.pstdev(bs) if len(bs) > 1 else 0.0
    avg_c = statistics.mean(ci)

    dw = var_s > divergence_threshold
    rc = avg_c
    if rc > 1.5:
        rc = rc / 100.0
    rc = _clamp01(rc)

    result = CoherenceAudit(
        timestamp=ts,
        lookback=lookback,
        reflective_coherence=round(rc, 4),
        divergence_window=dw,
        divergence_alert="⚠️ MTF Divergence Detected" if dw else "✅ Stable Alignment",
        stability_state="Stable" if rc >= gate_threshold else "Degraded",
        gate_threshold=gate_threshold,
        gate_pass=rc >= gate_threshold,
    ).as_dict()
    result["avg_bias_strength"] = round(avg_s, 4)
    result["bias_strength_std"] = round(var_s, 4)
    return result
