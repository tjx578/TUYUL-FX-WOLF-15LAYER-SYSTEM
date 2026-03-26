"""Equilibrium Momentum Fusion -- v6 + high-level wrapper."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ._types import FusionState, MomentumBand
from ._utils import _clamp, _clamp01, _safe_float
from .field_sync import resolve_field_context


def equilibrium_momentum_fusion_v6(
    price_change: float,
    volume_change: float,
    time_weight: float,
    atr: float,
    trq_energy: float = 1.0,
    reflective_intensity: float = 1.0,
    alpha: float = 1.0,
    beta: float = 1.0,
    gamma: float = 1.0,
    integrity_index: float = 0.97,
    direction_hint: float = 1.0,
    symbol: str | None = None,
    pair: str | None = None,
    trade_id: str | None = None,
    lambda_esi: float = 0.06,
    field_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate reflective equilibrium momentum across dimensions."""
    values = [price_change, volume_change, time_weight, atr]
    meta = [trq_energy, reflective_intensity, alpha, beta, gamma, integrity_index, direction_hint]

    if price_change == 0 or atr <= 0 or volume_change <= 0 or time_weight <= 0:
        return {"status": "invalid_input"}
    if not (all(math.isfinite(x) for x in values) and all(math.isfinite(x) for x in meta)):
        return {"status": "invalid_input"}

    direction_hint = _clamp(direction_hint, -1.0, 1.0)
    trq_energy = _clamp(trq_energy, 0.1, 10.0)
    reflective_intensity = _clamp(reflective_intensity, 0.1, 10.0)
    alpha = _clamp(alpha, 0.5, 2.0)
    beta = _clamp(beta, 0.5, 2.0)
    gamma = _clamp(gamma, 0.5, 2.0)
    integrity_index = _clamp01(integrity_index)

    price_momentum = abs(price_change / atr)
    volume_factor = math.log1p(abs(volume_change))
    time_factor = math.log1p(abs(time_weight))

    equilibrium = (price_momentum + volume_factor + time_factor) / 3
    imbalance = abs(price_momentum - volume_factor) + abs(volume_factor - time_factor)

    trq_sync = trq_energy * reflective_intensity
    alpha_sync = (alpha + beta + gamma) / 3

    fusion_score = (equilibrium / (1 + imbalance)) * trq_sync * alpha_sync * integrity_index
    signed_score = fusion_score * math.copysign(1.0, direction_hint)

    if signed_score >= 1.25:
        bias, state = "Bullish Reflective Phase", FusionState.STRONG_BULLISH.value
    elif signed_score >= 0.75:
        bias, state = "Bullish Phase", FusionState.BULLISH.value
    elif signed_score <= -1.25:
        bias, state = "Bearish Reflective Phase", FusionState.STRONG_BEARISH.value
    elif signed_score <= -0.75:
        bias, state = "Bearish Phase", FusionState.BEARISH.value
    else:
        bias, state = "Neutral Reflective Phase", FusionState.NEUTRAL.value

    confidence = _clamp01(abs(signed_score) / 1.5)
    magnitude = abs(signed_score)
    if magnitude >= 1.75:
        momentum_band = MomentumBand.HYPER.value
    elif magnitude >= 1.25:
        momentum_band = MomentumBand.STRONG.value
    elif magnitude >= 0.75:
        momentum_band = MomentumBand.BALANCED.value
    else:
        momentum_band = MomentumBand.CALM.value

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
        "price_momentum": round(price_momentum, 3),
        "volume_factor": round(volume_factor, 3),
        "time_factor": round(time_factor, 3),
        "equilibrium": round(equilibrium, 3),
        "imbalance": round(imbalance, 3),
        "fusion_score": round(fusion_score, 3),
        "fusion_score_signed": round(signed_score, 3),
        "reflective_confidence": round(confidence, 3),
        "bias": bias,
        "state": state,
        "equilibrium_state": state,
        "momentum_band": momentum_band,
        "trq_energy": round(trq_energy, 3),
        "reflective_intensity": round(reflective_intensity, 3),
        "alpha": round(alpha, 3),
        "beta": round(beta, 3),
        "gamma": round(gamma, 3),
        "integrity_index": round(integrity_index, 3),
        "lambda_esi": fc.get("lambda_esi"),
        "field_state": fc.get("field_state"),
        "field_integrity": fc.get("field_integrity"),
        "status": "ok",
        "symbol": symbol,
        "pair": pair,
        "trade_id": trade_id,
    }


def equilibrium_momentum_fusion(
    vwap_val: float,
    ema_fusion_data: Mapping[str, Any],
    reflex_strength: float,
    trq_energy: float = 1.0,
    reflective_intensity: float = 1.0,
    alpha: float = 1.0,
    beta: float = 1.0,
    gamma: float = 1.0,
    integrity_index: float = 0.97,
    symbol: str | None = None,
    pair: str | None = None,
    trade_id: str | None = None,
    lambda_esi: float = 0.06,
    field_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """High-level equilibrium fusion for Ultra Fusion pipeline."""
    ema50 = _safe_float(ema_fusion_data.get("ema50", 0.0))
    fusion_strength = _safe_float(ema_fusion_data.get("fusion_strength", 0.0))
    cross_state = str(ema_fusion_data.get("cross_state", "neutral")).lower()

    if not math.isfinite(vwap_val):
        return {"status": "invalid input"}

    price_change = vwap_val - ema50
    direction_hint = 1.0 if cross_state == "bullish" else -1.0 if cross_state == "bearish" else 0.0
    direction_hint = direction_hint or math.copysign(1.0, price_change or 1.0)

    base_scale = max(abs(vwap_val), abs(ema50), 1e-6)
    deviation = abs(vwap_val - ema50)
    atr_proxy = max(deviation * 1.25, base_scale * 0.0008, 1e-6)

    output = equilibrium_momentum_fusion_v6(
        price_change=price_change,
        volume_change=max(0.01, fusion_strength),
        time_weight=max(0.01, abs(reflex_strength)),
        atr=atr_proxy,
        trq_energy=trq_energy,
        reflective_intensity=reflective_intensity,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        integrity_index=integrity_index,
        direction_hint=direction_hint,
        symbol=symbol,
        pair=pair,
        trade_id=trade_id,
        lambda_esi=lambda_esi,
        field_override=field_override,
    )

    if output.get("status") == "invalid_input":
        return output

    output.update(
        {
            "vwap": round(vwap_val, 6),
            "ema50": round(ema50, 6),
            "fusion_strength_input": round(fusion_strength, 4),
            "reflex_strength": round(reflex_strength, 4),
            "cross_state": cross_state,
            "atr_proxy": round(atr_proxy, 6),
        }
    )
    return output
