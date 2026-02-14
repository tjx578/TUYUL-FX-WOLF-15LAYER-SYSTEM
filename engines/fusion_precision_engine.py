"""Precision scoring using EMA stack, confluence, and zone proximity."""

from dataclasses import dataclass, field
from typing import Any, Dict, List
from __future__ import annotations

from dataclasses import dataclass
from math import exp, tanh
from typing import Any


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    acc = values[0]
    for value in values[1:]:
        acc = value * k + acc * (1 - k)
    return acc


@dataclass
class PrecisionSnapshot:
    valid: bool
    precision_weight: float
    ema_alignment: float
    confluence_score: float
    zone_proximity: float


class FusionPrecisionEngine:
    def evaluate(self, payload: dict[str, Any]) -> PrecisionSnapshot:
        prices = [float(v) for v in payload.get("prices", [])]
        rsi = float(payload.get("rsi", 50.0))
        macd = float(payload.get("macd", 0.0))
        atr = max(1e-9, float(payload.get("atr", 1.0)))
        sr_zone = float(payload.get("sr_zone_distance", atr))
        volatility = float(payload.get("volatility", 0.5))
        if len(prices) < 30:
            return PrecisionSnapshot(False, 0.0, 0.0, 0.0, 0.0)

        ema8 = _ema(prices, 8)
        ema21 = _ema(prices, 21)
        ema55 = _ema(prices, 55)
        ema100 = _ema(prices, 100)

        aligns = [
            ema8 > ema21,
            ema21 > ema55,
            ema55 > ema100,
        ]
        ema_alignment = sum(1 for cond in aligns if cond) / len(aligns)

        rsi_score = 1.0 - abs(rsi - 50.0) / 50.0
        macd_score = min(1.0, abs(macd) / atr)
        confluence = max(0.0, min(1.0, (ema_alignment * 0.5 + rsi_score * 0.3 + macd_score * 0.2)))

        zone_proximity = max(0.0, min(1.0, 1.0 - min(sr_zone / atr, 2.0) / 2.0))

        base = tanh((ema8 - ema21) / atr) * exp(-abs(sr_zone) / (atr * 2.0))
        weight = abs(base) * confluence * (0.5 + zone_proximity * 0.5)
        if volatility > 0.7:
            weight *= 0.85

        return PrecisionSnapshot(
            True,
            round(max(0.0, min(1.0, weight)), 4),
            round(ema_alignment, 4),
            round(confluence, 4),
            round(zone_proximity, 4),
        )

    @staticmethod
    def export(snapshot: PrecisionSnapshot) -> dict[str, Any]:
        return {
            "valid": snapshot.valid,
            "precision_weight": snapshot.precision_weight,
            "ema_alignment": snapshot.ema_alignment,
            "confluence_score": snapshot.confluence_score,
            "zone_proximity": snapshot.zone_proximity,
"""Precision weighting engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Sequence
"""
Fusion Precision Engine v2.0.

Role:
- Compute technical precision weights from indicator alignment.
- EMA ratio + VWAP deviation + volatility normalization.
- Multi-indicator confluence scoring.

Integration:
- Compatible with FusionPrecisionEngine.compute_precision() in core.
- Adds EMA stack analysis and VWAP zone proximity.

NO decision authority - produces weights for downstream consumers.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import math


@dataclass
class PrecisionResult:
    precision_weight: float
    ema_alignment: float
    confluence: float
    valid: bool
    precision_weight: float
    ema_alignment: float
class FusionPrecision:
    """Result of precision weight computation."""

    precision_weight: float
    ema_alignment: float
    vwap_deviation: float
    volatility_adjustment: float
    confluence_score: float
    zone_proximity: float
    details: Dict[str, Any] = field(default_factory=dict)


class FusionPrecisionEngine:
    def evaluate(self, data: Dict[str, Any]) -> PrecisionResult:
        closes: List[float] = data.get("closes", [])
        atr = float(data.get("atr", 0.0))
        rsi = float(data.get("rsi", 50.0))
        macd = float(data.get("macd", 0.0))
        support = data.get("support")
        resistance = data.get("resistance")
    def evaluate(self, data: Dict[str, Sequence[float] | float]) -> PrecisionResult:
        prices = list(data.get("price", []))
        if len(prices) < 120:
            return PrecisionResult(False, 0.0, 0.0, 0.0, 0.0, {"reason": "insufficient"})

        ema8 = self._ema(prices, 8)
        ema21 = self._ema(prices, 21)
        ema55 = self._ema(prices, 55)
        ema100 = self._ema(prices, 100)

        ordered = [ema8 > ema21, ema21 > ema55, ema55 > ema100]
        alignment = sum(1.0 for ok in ordered if ok) / 3.0

        rsi = float(data.get("rsi", 50.0))
        macd = float(data.get("macd", 0.0))
        confluence = 0.0
        if rsi > 52:
            confluence += 0.34
        if macd > 0:
            confluence += 0.33
        if alignment > 0.66:
            confluence += 0.33

        atr = float(data.get("atr", 0.001))
        support = float(data.get("support", prices[-1] - atr * 2))
        resistance = float(data.get("resistance", prices[-1] + atr * 2))
        dist_support = abs(prices[-1] - support)
        dist_resistance = abs(resistance - prices[-1])
        zone_proximity = math.exp(-min(dist_support, dist_resistance) / max(atr * 4, 1e-9))

        vol = float(data.get("volatility", 0.2))
        vol_damp = 0.85 if vol > 0.75 else 1.0

        base = math.tanh((ema8 - ema21) / max(atr, 1e-9))
        weight = abs(base) * confluence * zone_proximity * vol_damp

        return PrecisionResult(
            valid=True,
            precision_weight=round(min(1.0, weight), 4),
            ema_alignment=round(alignment, 4),
            confluence_score=round(confluence, 4),
            zone_proximity=round(zone_proximity, 4),
            details={
                "ema8": round(ema8, 6),
                "ema21": round(ema21, 6),
                "ema55": round(ema55, 6),
                "ema100": round(ema100, 6),
    """
    Computes precision weights using tanh-exponential model:

        precision = tanh(ema_alignment) * exp(-|vwap_dev| / ATR)
                    * confluence_factor * zone_proximity

    This produces a 0-1 weight indicating how precisely aligned
    the current price is with multiple technical factors.
    """

    def __init__(
        self,
        ema_periods: Optional[List[int]] = None,
        vwap_sensitivity: float = 1.0,
    ) -> None:
        self.ema_periods = ema_periods or [8, 21, 55, 100]
        self.vwap_sensitivity = vwap_sensitivity

    def calculate(self, indicators: Dict[str, Any]) -> FusionPrecision:
        """
        Calculate precision from indicator data.

        Args:
            indicators: Dict containing:
                - ema_ratio (float): EMA fast/slow ratio (>1 = bullish)
                - vwap_deviation (float): Distance from VWAP (signed)
                - atr_norm (float): Normalized ATR
                - closes (List[float], optional): For EMA stack computation
                - support_level (float, optional): Nearest support
                - resistance_level (float, optional): Nearest resistance
                - rsi (float, optional): RSI value for confluence
                - macd_signal (float, optional): MACD signal for confluence

        Returns:
            FusionPrecision with computed weights
        """
        ema_ratio = float(indicators.get("ema_ratio", 0.0))
        vwap_dev = float(indicators.get("vwap_deviation", 0.0))
        atr_norm = float(indicators.get("atr_norm", 1.0))
        closes = indicators.get("closes", [])

        if closes and len(closes) >= max(self.ema_periods):
            ema_alignment = self._compute_ema_stack_alignment(closes)
        else:
            ema_alignment = ema_ratio

        atr_safe = max(atr_norm, 1e-6)
        core_precision = (
            math.tanh(ema_alignment)
            * math.exp(-abs(vwap_dev) * self.vwap_sensitivity / atr_safe)
        )

        confluence = self._compute_confluence(indicators)
        zone_prox = self._compute_zone_proximity(indicators, closes)

        precision_weight = self._clamp(
            core_precision * 0.50
            + confluence * 0.30
            + zone_prox * 0.20
        )

        if atr_norm > 2.0:
            precision_weight *= 0.85

        return FusionPrecision(
            precision_weight=round(float(self._clamp(precision_weight)), 4),
            ema_alignment=round(ema_alignment, 4),
            vwap_deviation=round(vwap_dev, 6),
            volatility_adjustment=round(atr_norm, 4),
            confluence_score=round(confluence, 4),
            zone_proximity=round(zone_prox, 4),
            details={
                "core_precision": round(core_precision, 4),
                "ema_periods": self.ema_periods,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _ema(values: Sequence[float], period: int) -> float:
        k = 2.0 / (period + 1.0)
        ema = values[0]
        for value in values[1:]:
            ema = value * k + ema * (1.0 - k)
        return ema
    def _compute_ema_stack_alignment(self, closes: List[float]) -> float:
        """
        Compute EMA stack alignment score.
        Perfect bullish stack: EMA8 > EMA21 > EMA55 > EMA100 -> +1.0
        Perfect bearish stack: reverse -> -1.0
        """
        emas = []
        for period in self.ema_periods:
            if len(closes) >= period:
                emas.append(self._ema(closes, period))
            else:
                return 0.0

        n_pairs = 0
        bullish_pairs = 0
        for i in range(len(emas)):
            for j in range(i + 1, len(emas)):
                n_pairs += 1
                if emas[i] > emas[j]:
                    bullish_pairs += 1

        if n_pairs == 0:
            return 0.0
        return (bullish_pairs / n_pairs) * 2.0 - 1.0

    def _compute_confluence(self, indicators: Dict[str, Any]) -> float:
        """Compute multi-indicator confluence score."""
        signals = []

        rsi = indicators.get("rsi")
        if rsi is not None:
            if rsi > 55:
                signals.append(1.0)
            elif rsi < 45:
                signals.append(-1.0)
            else:
                signals.append(0.0)

        macd = indicators.get("macd_signal")
        if macd is not None:
            signals.append(1.0 if macd > 0 else -1.0)

        ema_r = indicators.get("ema_ratio", 0)
        if ema_r != 0:
            signals.append(1.0 if ema_r > 0 else -1.0)

        if not signals:
            return 0.5

        avg = sum(signals) / len(signals)
        return self._clamp(abs(avg))

    def _compute_zone_proximity(
        self, indicators: Dict[str, Any], closes: List[float]
    ) -> float:
        """Proximity to support/resistance zone (1.0 = at zone, 0 = far)."""
        if not closes:
            return 0.5

        current = closes[-1]
        support = indicators.get("support_level")
        resistance = indicators.get("resistance_level")

        if support is None and resistance is None:
            return 0.5

        proximities = []
        if support is not None and current != 0:
            dist = abs(current - support) / current
            proximities.append(max(0, 1.0 - dist * 50))
        if resistance is not None and current != 0:
            dist = abs(current - resistance) / current
            proximities.append(max(0, 1.0 - dist * 50))

        return max(proximities) if proximities else 0.5

    @staticmethod
    def _ema(data: List[float], period: int) -> float:
        """Compute last EMA value."""
        if len(data) < period:
            return data[-1] if data else 0.0

        k = 2.0 / (period + 1)
        ema = sum(data[:period]) / period
        for value in data[period:]:
            ema = value * k + ema * (1 - k)
        return ema

    @staticmethod
    def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, v))

    def export(self, precision: FusionPrecision) -> Dict[str, Any]:
        """Export result as a serializable dictionary."""
        return {
            "precision_weight": precision.precision_weight,
            "ema_alignment": precision.ema_alignment,
            "vwap_deviation": precision.vwap_deviation,
            "volatility_adjustment": precision.volatility_adjustment,
            "confluence_score": precision.confluence_score,
            "zone_proximity": precision.zone_proximity,
            "details": precision.details,
        }


__all__ = ["FusionPrecision", "FusionPrecisionEngine"]
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

        aligned = [ema8 > ema21, ema21 > ema55, ema55 > ema100]
        ema_alignment = sum(1.0 for item in aligned if item) / len(aligned)

        signal_up = rsi > 50 and macd >= 0 and ema8 > ema21
        signal_down = rsi < 50 and macd < 0 and ema8 < ema21
        confluence = 1.0 if (signal_up or signal_down) else 0.45

        zone_proximity = self._zone_proximity(closes[-1] if closes else 0.0, support, resistance, atr)
        base = math.tanh(abs((ema8 - ema21) / (atr or 1.0))) * math.exp(-abs(macd))

        damping = 0.85 if atr > 0 and closes and (atr / closes[-1]) > 0.03 else 1.0
        weight = max(0.0, min(1.0, base * confluence * zone_proximity * damping))

        return PrecisionResult(
            precision_weight=round(weight, 4),
            ema_alignment=round(ema_alignment, 4),
            confluence=round(confluence, 4),
            zone_proximity=round(zone_proximity, 4),
            details={"ema8": ema8, "ema21": ema21, "ema55": ema55, "ema100": ema100},
        )

    def _ema(self, values: List[float], period: int) -> float:
        if not values:
            return 0.0
        k = 2 / (period + 1)
        ema_value = values[0]
        for value in values[1:]:
            ema_value = (value * k) + (ema_value * (1 - k))
        return ema_value

    def _zone_proximity(self, price: float, support: Any, resistance: Any, atr: float) -> float:
        if not price or support is None or resistance is None or atr <= 0:
            return 0.7
        near_support = abs(price - float(support)) / atr
        near_res = abs(float(resistance) - price) / atr
        score = 1.0 - min(1.0, min(near_support, near_res) / 3.0)
        return max(0.5, score)


__all__ = ["PrecisionResult", "FusionPrecisionEngine"]
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
        # Apply exponential smoothing to remaining values
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
