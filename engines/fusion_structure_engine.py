"""Fusion Structure Engine v2.0.

Role:
  - Market structure and divergence detection.
  - Liquidity zone mapping.
  - Multi-timeframe alignment scoring.

Integration:
  - Compatible with MultiIndicatorDivergenceDetector output.
  - Consumes OHLCV data for real structure analysis.
"""

import logging

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class StructureState(str, Enum):
    BULLISH_STRUCTURE = "BULLISH_STRUCTURE"
    BEARISH_STRUCTURE = "BEARISH_STRUCTURE"
    RANGE_BOUND = "RANGE_BOUND"
    BREAKING_OUT = "BREAKING_OUT"
    BREAKING_DOWN = "BREAKING_DOWN"


@dataclass
class FusionStructure:
    """Result of structure analysis."""

    divergence_present: bool
    divergence_type: str
    liquidity_state: str
    mtf_alignment: float
    structure_state: StructureState
    swing_high: float | None = None
    swing_low: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


class FusionStructureEngine:
    """Analyze market structure, divergence, liquidity, and MTF alignment."""

    def __init__(self, swing_lookback: int = 5) -> None:
        self.swing_lookback = swing_lookback

    def analyze(self, structure: dict[str, Any]) -> FusionStructure:
        """Analyze market structure from raw OHLCV or pre-computed fields."""
        closes = structure.get("closes", structure.get("close", []))
        highs = structure.get("highs", structure.get("high", []))
        lows = structure.get("lows", structure.get("low", []))
        volumes = structure.get("volumes", structure.get("volume", []))
        rsi_series = structure.get("rsi", [])

        if structure.get("divergence") is not None and not closes:
            return FusionStructure(
                divergence_present=bool(structure.get("divergence", False)),
                divergence_type=structure.get("divergence_type", "NONE"),
                liquidity_state=structure.get("liquidity_state", "UNKNOWN"),
                mtf_alignment=float(structure.get("mtf_alignment", 0.5)),
                structure_state=StructureState.RANGE_BOUND,
            )

        if not closes or len(closes) < 20:
            return FusionStructure(
                divergence_present=False,
                divergence_type="NONE",
                liquidity_state="UNKNOWN",
                mtf_alignment=0.5,
                structure_state=StructureState.RANGE_BOUND,
                details={"reason": "insufficient_data"},
            )

        swing_high, swing_low = self._find_swing_points(highs, lows)
        structure_state = self._classify_structure(highs, lows, closes)
        div_present, div_type = self._detect_divergence(closes, rsi_series, lows, highs)
        liq_state = self._assess_liquidity(volumes)

        mtf_scores = structure.get("mtf_scores", {})
        if mtf_scores:
            mtf_alignment = sum(mtf_scores.values()) / len(mtf_scores)
        elif structure.get("mtf_alignment") is not None:
            mtf_alignment = float(structure["mtf_alignment"])
        else:
            mtf_alignment = self._compute_basic_mtf(closes)

        return FusionStructure(
            divergence_present=div_present,
            divergence_type=div_type,
            liquidity_state=liq_state,
            mtf_alignment=round(max(-1.0, min(1.0, mtf_alignment)), 4),
            structure_state=structure_state,
            swing_high=round(swing_high, 5) if swing_high else None,
            swing_low=round(swing_low, 5) if swing_low else None,
            details={
                "mtf_scores": mtf_scores,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    def _find_swing_points(self, highs: list[float], lows: list[float]) -> tuple[float | None, float | None]:
        """Find most recent swing high and low."""
        lb = self.swing_lookback
        last_sh, last_sl = None, None

        for i in range(len(highs) - lb, lb - 1, -1):
            if all(highs[i] >= highs[i - j] for j in range(1, lb + 1)) and all(
                highs[i] >= highs[i + j] for j in range(1, min(lb + 1, len(highs) - i))
            ):
                last_sh = highs[i]
                break

        for i in range(len(lows) - lb, lb - 1, -1):
            if all(lows[i] <= lows[i - j] for j in range(1, lb + 1)) and all(
                lows[i] <= lows[i + j] for j in range(1, min(lb + 1, len(lows) - i))
            ):
                last_sl = lows[i]
                break

        return last_sh, last_sl

    def _classify_structure(
        self, highs: list[float], lows: list[float], closes: list[float]
    ) -> StructureState:
        """Classify structure from recent swing patterns."""
        n = len(closes)
        if n < 30:
            return StructureState.RANGE_BOUND

        shs: list[float] = []
        sls: list[float] = []
        for i in range(n - 25, n - 3):
            if i < 2:
                continue
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                shs.append(highs[i])
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                sls.append(lows[i])

        if len(shs) >= 2 and len(sls) >= 2:
            hh = shs[-1] > shs[-2]
            hl = sls[-1] > sls[-2]
            ll = sls[-1] < sls[-2]
            lh = shs[-1] < shs[-2]

            if hh and hl:
                return StructureState.BULLISH_STRUCTURE
            if ll and lh:
                return StructureState.BEARISH_STRUCTURE

        recent_high = max(highs[-5:])
        lookback_high = max(highs[-30:-5]) if n > 30 else recent_high
        recent_low = min(lows[-5:])
        lookback_low = min(lows[-30:-5]) if n > 30 else recent_low

        if recent_high > lookback_high * 1.002:
            return StructureState.BREAKING_OUT
        if recent_low < lookback_low * 0.998:
            return StructureState.BREAKING_DOWN

        return StructureState.RANGE_BOUND

    def _detect_divergence(
        self,
        closes: list[float],
        rsi: list[float],
        lows: list[float],
        highs: list[float],
    ) -> tuple[bool, str]:
        """Simple RSI-price divergence detection."""
        if not rsi or len(rsi) < 20 or len(closes) < 20:
            return False, "NONE"

        price_ll = lows[-1] < min(lows[-15:-5])
        rsi_hl = rsi[-1] > min(rsi[-15:-5])
        if price_ll and rsi_hl:
            return True, "BULLISH"

        price_hh = highs[-1] > max(highs[-15:-5])
        rsi_lh = rsi[-1] < max(rsi[-15:-5])
        if price_hh and rsi_lh:
            return True, "BEARISH"

        return False, "NONE"

    def _assess_liquidity(self, volumes: list[float]) -> str:
        """Assess liquidity from recent volume profile."""
        if not volumes or len(volumes) < 10:
            return "NORMAL"
        avg = sum(volumes[-20:]) / min(20, len(volumes))
        current = volumes[-1]
        if avg == 0:
            return "THIN"
        ratio = current / avg
        if ratio > 1.5:
            return "HIGH"
        if ratio > 0.7:
            return "NORMAL"
        if ratio > 0.3:
            return "LOW"
        return "THIN"

    def _compute_basic_mtf(self, closes: list[float]) -> float:
        """Compute basic MTF alignment from SMA slopes."""
        if len(closes) < 50:
            return 0.0

        scores: list[float] = []
        for window in [10, 20, 50]:
            if len(closes) >= window + 5:
                sma_now = sum(closes[-window:]) / window
                sma_prev = sum(closes[-window - 5 : -5]) / window
                scores.append(1.0 if sma_now > sma_prev else -1.0)

        return sum(scores) / len(scores) if scores else 0.0

    def export(self, structure: FusionStructure) -> dict[str, Any]:
        """Export dataclass output into a serializable dictionary."""
        return {
            "divergence_present": structure.divergence_present,
            "divergence_type": structure.divergence_type,
            "liquidity_state": structure.liquidity_state,
            "mtf_alignment": structure.mtf_alignment,
            "structure_state": structure.structure_state.value,
            "swing_high": structure.swing_high,
            "swing_low": structure.swing_low,
            "details": structure.details,
        }


__all__ = ["FusionStructure", "FusionStructureEngine", "StructureState"]
