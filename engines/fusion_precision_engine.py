"""Precision engine for confluence and zone proximity scoring."""

import math

from dataclasses import dataclass
from typing import Any


@dataclass
class PrecisionReport:
    precision_weight: float
    ema_alignment: float
    confluence: float
    details: dict[str, Any]


class FusionPrecisionEngine:
    def evaluate(self, indicators: dict[str, float]) -> PrecisionReport:
        ema8 = float(indicators.get("ema8", 0.0))
        ema21 = float(indicators.get("ema21", 0.0))
        ema55 = float(indicators.get("ema55", 0.0))
        ema100 = float(indicators.get("ema100", 0.0))
        rsi = float(indicators.get("rsi", 50.0))
        macd = float(indicators.get("macd", 0.0))
        atr = max(1e-9, float(indicators.get("atr", 1.0)))
        vwap_gap = float(indicators.get("vwap_gap", 0.0))
        zone_distance = abs(float(indicators.get("zone_distance", atr)))
        volatility = float(indicators.get("volatility", 0.5))

        align_pairs = [(ema8, ema21), (ema21, ema55), (ema55, ema100)]
        aligned = sum(1 for a, b in align_pairs if a >= b)
        ema_alignment = aligned / len(align_pairs)

        rsi_sig = 1.0 if rsi > 55 else 0.0 if rsi < 45 else 0.5
        macd_sig = 1.0 if macd > 0 else 0.0 if macd < 0 else 0.5
        confluence = (ema_alignment + rsi_sig + macd_sig) / 3.0

        tanh_component = math.tanh((ema8 - ema100) / atr)
        vwap_component = math.exp(-abs(vwap_gap) / atr)
        zone_component = max(0.2, 1.0 - zone_distance / (3 * atr))
        vol_damping = 0.85 if volatility > 0.7 else 1.0

        precision = abs(tanh_component) * vwap_component * confluence * zone_component * vol_damping

        return PrecisionReport(
            precision_weight=round(max(0.0, min(1.0, precision)), 4),
            ema_alignment=round(ema_alignment, 4),
            confluence=round(confluence, 4),
            details={
                "vwap_component": round(vwap_component, 6),
                "zone_component": round(zone_component, 6),
                "vol_damping": round(vol_damping, 6),
            },
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class FusionPrecision:
    precision_weight: float
    ema_alignment_score: float


class FusionPrecisionEngine:
    """Estimate entry precision from weighting and EMA agreement."""

    def evaluate(self, state: Mapping[str, Any]) -> FusionPrecision:
        weights = state.get("precision_weights", [0.5, 0.5])
        if not isinstance(weights, list) or not weights:
            weights = [0.5, 0.5]
        mean_weight = sum(float(w) for w in weights) / len(weights)
        ema_fast = float(state.get("ema_fast", 0.0))
        ema_slow = float(state.get("ema_slow", 0.0))
        alignment = max(0.0, min(1.0, 1.0 - min(1.0, abs(ema_fast - ema_slow))))

        return FusionPrecision(
            precision_weight=max(0.0, min(1.0, mean_weight)),
            ema_alignment_score=alignment,
        )
