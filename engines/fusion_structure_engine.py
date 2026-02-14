"""Structure and divergence engine."""
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
"""Fusion structure engine."""

from __future__ import annotations

from dataclasses import dataclass
"""Structure and divergence analysis engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence
from typing import Any, Dict, List


@dataclass
class StructureResult:
    valid: bool
    structure: str
    bullish_divergence: bool
    bearish_divergence: bool
    liquidity: str
    mtf_alignment: float
    structure: str
    bullish_divergence: bool
    bearish_divergence: bool
    mtf_alignment: float


class FusionStructureEngine:
    def evaluate(self, payload: dict[str, list[float]]) -> StructureResult:
        closes = payload.get("closes", [])
        rsi = payload.get("rsi", [])
        if len(closes) < 8:
            return StructureResult("UNKNOWN", False, False, 0.0)
        last = closes[-1]
        recent_max = max(closes[-6:-1])
        recent_min = min(closes[-6:-1])
        if last > recent_max:
            structure = "BREAKING_OUT"
        elif last < recent_min:
            structure = "BREAKING_DOWN"
        elif closes[-1] > closes[-4] > closes[-8]:
            structure = "BULLISH"
        elif closes[-1] < closes[-4] < closes[-8]:
            structure = "BEARISH"
        else:
            structure = "RANGE"
        bull_div = bool(len(rsi) >= 6 and closes[-1] < closes[-3] and rsi[-1] > rsi[-3])
        bear_div = bool(len(rsi) >= 6 and closes[-1] > closes[-3] and rsi[-1] < rsi[-3])
        htf_slope = (closes[-1] - closes[-6]) / closes[-6]
        ltf_slope = (closes[-1] - closes[-3]) / closes[-3]
        mtf = 1.0 if htf_slope * ltf_slope > 0 else 0.4
        return StructureResult(structure, bull_div, bear_div, round(mtf, 4))
    liquidity: str
    details: Dict[str, Any] = field(default_factory=dict)


class FusionStructureEngine:
    def evaluate(self, data: Dict[str, Sequence[float] | float]) -> StructureResult:
        closes = list(data.get("close", []))
        highs = list(data.get("high", closes))
        lows = list(data.get("low", closes))
        volumes = list(data.get("volume", [1.0] * len(closes)))
        rsi = list(data.get("rsi_series", []))

        if len(closes) < 50:
            return StructureResult(False, "UNKNOWN", False, False, "UNKNOWN", 0.0, {"reason": "insufficient"})

        highs_idx, lows_idx = self._swings(highs, lows, lookback=2)
        structure = "RANGE"
        if len(highs_idx) >= 2 and len(lows_idx) >= 2:
            hh = highs[highs_idx[-1]] > highs[highs_idx[-2]]
            hl = lows[lows_idx[-1]] > lows[lows_idx[-2]]
            ll = lows[lows_idx[-1]] < lows[lows_idx[-2]]
            lh = highs[highs_idx[-1]] < highs[highs_idx[-2]]
            if hh and hl:
                structure = "BREAKING_OUT"
            elif ll and lh:
                structure = "BREAKING_DOWN"
            elif hh:
                structure = "BULLISH"
            elif ll:
                structure = "BEARISH"

        bull_div = False
        bear_div = False
        if len(rsi) >= len(closes) and len(lows_idx) >= 2 and len(highs_idx) >= 2:
            l1, l2 = lows_idx[-2], lows_idx[-1]
            h1, h2 = highs_idx[-2], highs_idx[-1]
            bull_div = lows[l2] < lows[l1] and rsi[l2] > rsi[l1]
            bear_div = highs[h2] > highs[h1] and rsi[h2] < rsi[h1]

        vol_ratio = volumes[-1] / max(sum(volumes[-20:]) / 20.0, 1e-9)
        liquidity = "HIGH" if vol_ratio > 1.2 else "LOW" if vol_ratio < 0.8 else "NORMAL"

        slope_fast = closes[-1] - closes[-10]
        slope_slow = closes[-1] - closes[-30]
        mtf = 1.0 if slope_fast * slope_slow > 0 else 0.4

        return StructureResult(
            valid=True,
            structure=structure,
            bullish_divergence=bull_div,
            bearish_divergence=bear_div,
            liquidity=liquidity,
            mtf_alignment=round(mtf, 4),
            details={
                "swing_highs": highs_idx[-5:],
                "swing_lows": lows_idx[-5:],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _swings(highs: List[float], lows: List[float], lookback: int) -> tuple[List[int], List[int]]:
        sh: List[int] = []
        sl: List[int] = []
        for i in range(lookback, len(highs) - lookback):
            left_h = highs[i - lookback : i]
            right_h = highs[i + 1 : i + lookback + 1]
            left_l = lows[i - lookback : i]
            right_l = lows[i + 1 : i + lookback + 1]
            if highs[i] > max(left_h + right_h):
                sh.append(i)
            if lows[i] < min(left_l + right_l):
                sl.append(i)
        return sh, sl
    def evaluate(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: List[float],
        rsi_values: List[float],
    ) -> StructureResult:
        if len(closes) < 40:
            return StructureResult("RANGE", False, False, 0.0, "NORMAL", {"reason": "insufficient_data"})

        swings_h = self._swings(highs, is_high=True)
        swings_l = self._swings(lows, is_high=False)
        structure = self._classify(swings_h, swings_l, closes)
        bull_div, bear_div = self._divergence(closes, rsi_values)
        mtf = self._mtf_alignment(closes)
        liq = self._liquidity(volumes)

        return StructureResult(
            structure=structure,
            bullish_divergence=bull_div,
            bearish_divergence=bear_div,
            mtf_alignment=round(mtf, 6),
            liquidity=liq,
            details={"swing_highs": len(swings_h), "swing_lows": len(swings_l)},
        )

    @staticmethod
    def _swings(values: List[float], is_high: bool, lookback: int = 2) -> List[float]:
        swings = []
        for i in range(lookback, len(values) - lookback):
            left = values[i - lookback : i]
            right = values[i + 1 : i + 1 + lookback]
            if is_high and values[i] > max(left + right):
                swings.append(values[i])
            if not is_high and values[i] < min(left + right):
                swings.append(values[i])
        return swings[-4:]

    @staticmethod
    def _classify(swings_h: List[float], swings_l: List[float], closes: List[float]) -> str:
        if len(swings_h) < 2 or len(swings_l) < 2:
            return "RANGE"
        hh = swings_h[-1] > swings_h[-2]
        hl = swings_l[-1] > swings_l[-2]
        ll = swings_l[-1] < swings_l[-2]
        lh = swings_h[-1] < swings_h[-2]
        if hh and hl:
            return "BREAKING_OUT"
        if ll and lh:
            return "BREAKING_DOWN"
        if abs(closes[-1] - closes[-20]) / closes[-20] < 0.004:
            return "RANGE"
        return "BULLISH" if closes[-1] > closes[-20] else "BEARISH"

    @staticmethod
    def _divergence(closes: List[float], rsi: List[float]) -> tuple[bool, bool]:
        if len(closes) < 8 or len(rsi) < 8:
            return False, False
        price_ll = closes[-1] < min(closes[-6:-1])
        rsi_hl = rsi[-1] > min(rsi[-6:-1])
        price_hh = closes[-1] > max(closes[-6:-1])
        rsi_lh = rsi[-1] < max(rsi[-6:-1])
        return price_ll and rsi_hl, price_hh and rsi_lh

    @staticmethod
    def _mtf_alignment(closes: List[float]) -> float:
        sma10 = sum(closes[-10:]) / 10
        sma20 = sum(closes[-20:]) / 20
        sma40 = sum(closes[-40:]) / 40
        up = [sma10 > sma20, sma20 > sma40]
        down = [sma10 < sma20, sma20 < sma40]
        return max(sum(up), sum(down)) / 2

    @staticmethod
    def _liquidity(volumes: List[float]) -> str:
        if len(volumes) < 20:
            return "NORMAL"
        avg = sum(volumes[-20:]) / 20
        ratio = volumes[-1] / avg if avg else 0.0
        if ratio > 1.6:
            return "HIGH"
        if ratio < 0.5:
            return "LOW"
        return "NORMAL"

    @staticmethod
    def export(result: StructureResult) -> Dict[str, Any]:
        return {
            "structure": result.structure,
            "bullish_divergence": result.bullish_divergence,
            "bearish_divergence": result.bearish_divergence,
            "mtf_alignment": result.mtf_alignment,
            "liquidity": result.liquidity,
            "details": result.details,
        }
"""Structure engine with swing and divergence analysis."""

from dataclasses import dataclass
from typing import Any


@dataclass
class StructureReport:
    structure: str
    divergence: str
    liquidity: str
    mtf_alignment: float
    details: dict[str, Any]


class FusionStructureEngine:
    def evaluate(self, market_data: dict[str, list[float] | float]) -> StructureReport:
        closes = list(market_data.get("close", []))
        highs = list(market_data.get("high", closes))
        lows = list(market_data.get("low", closes))
        volumes = list(market_data.get("volume", [1.0] * len(closes)))
        rsi_series = list(market_data.get("rsi", []))
        if len(closes) < 30:
            return StructureReport("RANGE", "NONE", "NORMAL", 0.0, {"reason": "insufficient_data"})

        recent_high = max(highs[-15:])
        recent_low = min(lows[-15:])
        if closes[-1] > recent_high * 0.999:
            structure = "BREAKING_OUT"
        elif closes[-1] < recent_low * 1.001:
            structure = "BREAKING_DOWN"
        elif closes[-1] > sum(closes[-10:]) / 10:
            structure = "BULLISH"
        elif closes[-1] < sum(closes[-10:]) / 10:
            structure = "BEARISH"
        else:
            structure = "RANGE"

        divergence = self._divergence(closes, rsi_series)
        liquidity = self._liquidity(volumes)

        slope_fast = (sum(closes[-10:]) / 10) - (sum(closes[-20:-10]) / 10)
        slope_slow = (sum(closes[-20:]) / 20) - (sum(closes[-40:-20]) / 20)
        mtf_alignment = 1.0 if slope_fast * slope_slow > 0 else 0.5 if slope_fast != 0 else 0.0

        return StructureReport(
            structure=structure,
            divergence=divergence,
            liquidity=liquidity,
            mtf_alignment=round(mtf_alignment, 4),
            details={"recent_high": round(recent_high, 6), "recent_low": round(recent_low, 6)},
        )

    def _divergence(self, closes: list[float], rsi: list[float]) -> str:
        if len(rsi) < 6 or len(closes) < 6:
            return "NONE"
        price_trend = closes[-1] - closes[-6]
        rsi_trend = rsi[-1] - rsi[-6]
        if price_trend > 0 and rsi_trend < 0:
            return "BEARISH"
        if price_trend < 0 and rsi_trend > 0:
            return "BULLISH"
        return "NONE"

    def _liquidity(self, volumes: list[float]) -> str:
        if len(volumes) < 10:
            return "LOW"
        avg = sum(volumes[-10:]) / 10
        if volumes[-1] > avg * 1.4:
            return "HIGH"
        if volumes[-1] < avg * 0.6:
            return "LOW"
        return "NORMAL"
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class StructureState(str, Enum):
    SUPPORTIVE = "supportive"
    CONFLICTED = "conflicted"
    FRAGILE = "fragile"


@dataclass(frozen=True)
class FusionStructure:
    state: StructureState
    divergence_score: float
    liquidity_signal: float
    mtf_alignment: float


class FusionStructureEngine:
    """Assess structural reliability from divergence, liquidity and MTF alignment."""

    def evaluate(self, state: Mapping[str, Any]) -> FusionStructure:
        divergence = max(0.0, min(1.0, float(state.get("divergence_score", 0.4))))
        liquidity = max(0.0, min(1.0, float(state.get("liquidity_signal", 0.5))))
        mtf = max(0.0, min(1.0, float(state.get("mtf_alignment", 0.5))))

        if divergence < 0.3 and mtf > 0.6:
            struct_state = StructureState.SUPPORTIVE
        elif divergence > 0.7 or liquidity < 0.3:
            struct_state = StructureState.FRAGILE
        else:
            struct_state = StructureState.CONFLICTED

        return FusionStructure(
            state=struct_state,
            divergence_score=divergence,
            liquidity_signal=liquidity,
            mtf_alignment=mtf,
        )
