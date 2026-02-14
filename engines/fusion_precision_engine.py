"""Precision weighting engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import exp, tanh
from typing import Any


@dataclass
class PrecisionResult:
    precision_weight: float
    ema_alignment: float
    confluence: float
    details: dict[str, Any] = field(default_factory=dict)


class FusionPrecisionEngine:
    def evaluate(
        self,
        closes: list[float],
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
    def _ema(series: list[float], period: int) -> float:
        """Compute a standard EMA using SMA of the first `period` values as seed.

        This implementation uses proper EMA calculation by initializing with SMA
        and iterating through all remaining values, rather than a fast approximation.
        """
        if period <= 0:
            raise ValueError("period must be positive for EMA calculation")
        if len(series) < period:
            raise ValueError("series length must be at least `period` for EMA calculation")

        alpha = 2 / (period + 1)
        # Initialize with SMA over the first `period` observations
        ema = sum(series[:period]) / period
        # Then iterate forward through the remaining values
        for value in series[period:]:
            ema = alpha * value + (1 - alpha) * ema
        return ema

    @staticmethod
    def export(result: PrecisionResult) -> dict[str, Any]:
        return {
            "precision_weight": result.precision_weight,
            "ema_alignment": result.ema_alignment,
            "confluence": result.confluence,
            "details": result.details,
        }
