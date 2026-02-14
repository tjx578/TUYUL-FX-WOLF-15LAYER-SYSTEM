"""Fusion precision engine."""

from __future__ import annotations

import math

from dataclasses import dataclass


@dataclass
class PrecisionResult:
    precision_weight: float
    ema_alignment: float
    confluence: float
    zone_proximity: float


class FusionPrecisionEngine:
    def evaluate(self, payload: dict[str, float]) -> PrecisionResult:
        ema8 = payload.get("ema8", 0.0)
        ema21 = payload.get("ema21", 0.0)
        ema55 = payload.get("ema55", 0.0)
        ema100 = payload.get("ema100", 0.0)
        rsi = payload.get("rsi", 50.0)
        macd = payload.get("macd", 0.0)
        atr = max(payload.get("atr", 1e-6), 1e-6)
        vwap_delta = payload.get("vwap_delta", 0.0)
        sr_distance = abs(payload.get("sr_distance", atr))
        trend_up = ema8 > ema21 > ema55 > ema100
        trend_down = ema8 < ema21 < ema55 < ema100
        alignment = 1.0 if (trend_up or trend_down) else 0.25
        rsi_bias = 1.0 - min(1.0, abs(rsi - 50.0) / 50.0)
        macd_bias = min(1.0, abs(macd) / atr)
        confluence = max(0.0, min(1.0, (rsi_bias + macd_bias + alignment) / 3.0))
        zone = max(0.2, min(1.0, 1.0 - (sr_distance / (atr * 3.0))))
        damping = 0.85 if atr > payload.get("price", 1.0) * 0.03 else 1.0
        precision = (
            math.tanh(alignment) * math.exp(-abs(vwap_delta) / atr) * confluence * zone * damping
        )
        return PrecisionResult(
            round(precision, 4), round(alignment, 4), round(confluence, 4), round(zone, 4)
"""Precision weighting engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import exp, tanh
from typing import Any, Dict, List


@dataclass
class PrecisionResult:
    precision_weight: float
    ema_alignment: float
    confluence: float
    details: Dict[str, Any] = field(default_factory=dict)


class FusionPrecisionEngine:
    def evaluate(
        self,
        closes: List[float],
        rsi: float,
        macd_hist: float,
        atr_pct: float,
        support: float,
        resistance: float,
    ) -> PrecisionResult:
        if len(closes) < 110:
            return PrecisionResult(0.0, 0.0, 0.0, {"reason": "not_enough_bars"})

        ema8 = self._ema(closes, 8)
        ema21 = self._ema(closes, 21)
        ema55 = self._ema(closes, 55)
        ema100 = self._ema(closes, 100)

        ordered = [ema8 > ema21, ema21 > ema55, ema55 > ema100]
        inv_ordered = [ema8 < ema21, ema21 < ema55, ema55 < ema100]
        ema_alignment = max(sum(ordered), sum(inv_ordered)) / 3

        rsi_sig = 1.0 if 45 <= rsi <= 65 else 0.5
        macd_sig = 1.0 if macd_hist > 0 else 0.6
        trend_sig = 0.5 + 0.5 * ema_alignment
        confluence = (rsi_sig + macd_sig + trend_sig) / 3

        price = closes[-1]
        zone_span = max(1e-8, resistance - support)
        zone_proximity = 1.0 - min(1.0, abs(price - (support + resistance) / 2) / zone_span)
        vol_damping = 0.85 if atr_pct > 0.02 else 1.0

        raw = tanh((ema8 - ema55) / max(price, 1e-8))
        precision = abs(raw) * exp(-abs(price - ema21) / max(price, 1e-8))
        precision = precision * confluence * zone_proximity * vol_damping

        return PrecisionResult(
            precision_weight=round(max(0.0, min(1.0, precision)), 6),
            ema_alignment=round(ema_alignment, 6),
            confluence=round(confluence, 6),
            details={"zone_proximity": round(zone_proximity, 6), "vol_damping": vol_damping},
        )

    @staticmethod
    def _ema(series: List[float], period: int) -> float:
        alpha = 2 / (period + 1)
        ema = series[-period]
        for value in series[-period + 1 :]:
            ema = alpha * value + (1 - alpha) * ema
        return ema

    @staticmethod
    def export(result: PrecisionResult) -> Dict[str, Any]:
        return {
            "precision_weight": result.precision_weight,
            "ema_alignment": result.ema_alignment,
            "confluence": result.confluence,
            "details": result.details,
        }
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
