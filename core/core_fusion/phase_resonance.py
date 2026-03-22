"""Phase Resonance Engine v1.5."""

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ._types import ResonanceState
from ._utils import _clamp, _clamp01
from .field_sync import resolve_field_context


def phase_resonance_engine_v1_5(
    price_change: float,
    volume_change: float,
    time_delta: float,
    atr: float,
    trq_energy: float = 1.0,
    reflective_intensity: float = 1.0,
    alpha: float = 1.0,
    beta: float = 1.0,
    gamma: float = 1.0,
    alpha_drift: float = 0.0,
    beta_drift: float = 0.0,
    gamma_drift: float = 0.0,
    integrity_index: float = 0.97,
    symbol: str | None = None,
    pair: str | None = None,
    trade_id: str | None = None,
    lambda_esi: float = 0.06,
    field_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate Phase Resonance Index (PRI) and Resonant Field State."""
    base = [price_change, volume_change, time_delta, atr]
    meta = [trq_energy, reflective_intensity, alpha, beta, gamma, alpha_drift, beta_drift, gamma_drift, integrity_index]
    if not (all(math.isfinite(x) for x in base) and all(math.isfinite(x) for x in meta)):
        return {"status": "invalid_input"}
    if any(v <= 0 for v in [abs(price_change), abs(volume_change), abs(time_delta), atr]):
        return {"status": "invalid_input"}

    trq_energy = _clamp(trq_energy, 0.1, 10.0)
    reflective_intensity = _clamp(reflective_intensity, 0.1, 10.0)
    alpha = _clamp(alpha, 0.5, 2.0)
    beta = _clamp(beta, 0.5, 2.0)
    gamma = _clamp(gamma, 0.5, 2.0)
    alpha_drift = _clamp(alpha_drift, -0.5, 0.5)
    beta_drift = _clamp(beta_drift, -0.5, 0.5)
    gamma_drift = _clamp(gamma_drift, -0.5, 0.5)
    integrity_index = _clamp01(integrity_index)

    pe = abs(price_change / atr)
    ve = math.log1p(volume_change)
    te = math.log1p(time_delta)
    eb = (pe + ve + te) / 3
    ib = (abs(pe - ve) + abs(pe - te) + abs(ve - te)) / 3
    df = (abs(alpha_drift) + abs(beta_drift) + abs(gamma_drift)) / 3
    dc = max(0.85, 1.0 - df)
    asn = (alpha + beta + gamma) / 3
    pri = _clamp(eb / (1 + ib) * trq_energy * reflective_intensity * asn * dc, 0.0, 10.0)

    if pri >= 1.3:
        fs = ResonanceState.EXPANSION_RESONANCE.value
    elif pri >= 0.9:
        fs = ResonanceState.EQUILIBRIUM_RESONANCE.value
    elif pri >= 0.7:
        fs = ResonanceState.ADAPTIVE_COMPRESSION.value
    else:
        fs = ResonanceState.PHASE_DRIFT_DETECTED.value

    cs = _clamp((pri / (1 + df)) * integrity_index, 0.0, 10.0)
    fc = resolve_field_context(
        pair=pair or "XAUUSD",
        timeframe="H4",
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        lambda_esi=lambda_esi,
        field_override=field_override,
    )

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "price_energy": round(pe, 3),
        "volume_energy": round(ve, 3),
        "time_energy": round(te, 3),
        "energy_balance": round(eb, 3),
        "imbalance_factor": round(ib, 3),
        "phase_resonance_index": round(pri, 3),
        "resonance_state": fs,
        "alpha": round(alpha, 3),
        "beta": round(beta, 3),
        "gamma": round(gamma, 3),
        "alpha_drift": round(alpha_drift, 4),
        "beta_drift": round(beta_drift, 4),
        "gamma_drift": round(gamma_drift, 4),
        "drift_correction": round(dc, 3),
        "reflective_intensity": round(reflective_intensity, 3),
        "trq_energy": round(trq_energy, 3),
        "integrity_index": round(integrity_index, 3),
        "coherence_score": round(cs, 3),
        "status": "ok",
        "symbol": symbol,
        "pair": pair,
        "trade_id": trade_id,
        "lambda_esi": fc.get("lambda_esi"),
        "field_state": fc.get("field_state"),
        "field_integrity": fc.get("field_integrity"),
    }
