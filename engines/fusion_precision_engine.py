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
