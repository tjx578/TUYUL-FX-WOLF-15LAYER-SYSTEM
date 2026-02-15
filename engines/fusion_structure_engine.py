"""Fusion Structure Engine — Layer-5 market structure analysis.

Detects key structure levels (support/resistance), break of structure (BOS),
change of character (CHOCH), and order blocks across multiple timeframes.

ANALYSIS-ONLY module. No execution side-effects.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class StructureLevel:
    """A detected support/resistance level."""
    price: float
    level_type: str  # "SUPPORT" | "RESISTANCE"
    strength: float  # 0.0–1.0
    timeframe: str = ""
    touch_count: int = 0
    last_touch_index: int = -1


@dataclass
class StructureResult:
    """Output of the Fusion Structure Engine."""

    # Overall market structure
    structure_bias: str = "NEUTRAL"  # BULLISH | BEARISH | NEUTRAL | RANGING
    structure_score: float = 0.0     # 0.0–1.0

    # Break of structure / Change of character
    bos_detected: bool = False
    bos_direction: str = "NONE"      # BULLISH | BEARISH | NONE
    choch_detected: bool = False
    choch_direction: str = "NONE"

    # Key levels
    levels: list[StructureLevel] = field(default_factory=list)
    nearest_support: float = 0.0
    nearest_resistance: float = 0.0

    # Order blocks
    order_blocks: list[dict[str, Any]] = field(default_factory=list)

    # Swing points
    swing_highs: list[float] = field(default_factory=list)
    swing_lows: list[float] = field(default_factory=list)

    # Multi-timeframe
    mtf_structure_alignment: float = 0.0
    timeframe_biases: dict[str, str] = field(default_factory=dict)

    # Metadata
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.confidence > 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_swing_points(
    highs: np.ndarray,
    lows: np.ndarray,
    lookback: int = 3,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Detect swing highs/lows using N-bar lookback."""
    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []

    for i in range(lookback, len(highs) - lookback):
        # Swing high: higher than surrounding bars
        if all(highs[i] >= highs[i - j] for j in range(1, lookback + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, lookback + 1)):
            swing_highs.append((i, float(highs[i])))

        # Swing low: lower than surrounding bars
        if all(lows[i] <= lows[i - j] for j in range(1, lookback + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, lookback + 1)):
            swing_lows.append((i, float(lows[i])))

    return swing_highs, swing_lows


def _detect_bos(
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
    current_close: float,
) -> tuple[bool, str]:
    """Detect break of structure."""
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return False, "NONE"

    last_sh = swing_highs[-1][1]
    last_sl = swing_lows[-1][1]

    if current_close > last_sh:
        return True, "BULLISH"
    if current_close < last_sl:
        return True, "BEARISH"
    return False, "NONE"


def _detect_choch(
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
) -> tuple[bool, str]:
    """Detect change of character (trend reversal signal)."""
    if len(swing_highs) < 3 or len(swing_lows) < 3:
        return False, "NONE"

    # Bullish CHOCH: lower lows then a higher low
    recent_lows = [sl[1] for sl in swing_lows[-3:]]
    if recent_lows[-2] < recent_lows[-3] and recent_lows[-1] > recent_lows[-2]:
        return True, "BULLISH"

    # Bearish CHOCH: higher highs then a lower high
    recent_highs = [sh[1] for sh in swing_highs[-3:]]
    if recent_highs[-2] > recent_highs[-3] and recent_highs[-1] < recent_highs[-2]:
        return True, "BEARISH"

    return False, "NONE"


def _find_structure_levels(
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
    current_close: float,
    tolerance_pct: float = 0.001,
    timeframe: str = "",
) -> list[StructureLevel]:
    """Cluster swing points into support/resistance levels."""
    all_points: list[tuple[float, str]] = []
    for _, price in swing_highs:
        all_points.append((price, "RESISTANCE"))
    for _, price in swing_lows:
        all_points.append((price, "SUPPORT"))

    if not all_points:
        return []

    # Cluster nearby points
    all_points.sort(key=lambda x: x[0])
    levels: list[StructureLevel] = []
    used = [False] * len(all_points)

    for i, (price, ltype) in enumerate(all_points):
        if used[i]:
            continue
        cluster_prices = [price]
        cluster_types = [ltype]
        used[i] = True
        for j in range(i + 1, len(all_points)):
            if used[j]:
                continue
            if abs(all_points[j][0] - price) / max(abs(price), 1e-8) < tolerance_pct:
                cluster_prices.append(all_points[j][0])
                cluster_types.append(all_points[j][1])
                used[j] = True

        avg_price = float(np.mean(cluster_prices))
        touch_count = len(cluster_prices)
        strength = min(1.0, touch_count / 5.0)

        # Determine type relative to current price
        if avg_price > current_close:
            level_type = "RESISTANCE"
        elif avg_price < current_close:
            level_type = "SUPPORT"
        else:
            level_type = cluster_types[0]

        levels.append(StructureLevel(
            price=round(avg_price, 5),
            level_type=level_type,
            strength=strength,
            timeframe=timeframe,
            touch_count=touch_count,
        ))

    return levels


def _detect_order_blocks(
    opens: np.ndarray, closes: np.ndarray,
    highs: np.ndarray, lows: np.ndarray,
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
) -> list[dict[str, Any]]:
    """Detect institutional order blocks near swing points."""
    ob_list: list[dict[str, Any]] = []

    for idx, _price in swing_lows[-5:]:
        if idx < 1 or idx >= len(opens):
            continue
        # Bullish OB: last bearish candle before a bullish swing
        if closes[idx - 1] < opens[idx - 1]:
            ob_list.append({
                "type": "BULLISH",
                "top": float(opens[idx - 1]),
                "bottom": float(closes[idx - 1]),
                "index": idx - 1,
                "strength": 0.7,
            })

    for idx, _price in swing_highs[-5:]:
        if idx < 1 or idx >= len(opens):
            continue
        if closes[idx - 1] > opens[idx - 1]:
            ob_list.append({
                "type": "BEARISH",
                "top": float(closes[idx - 1]),
                "bottom": float(opens[idx - 1]),
                "index": idx - 1,
                "strength": 0.7,
            })

    return ob_list


def _classify_structure_bias(
    swing_highs: list[tuple[int, float]],
    swing_lows: list[tuple[int, float]],
) -> tuple[str, float]:
    """Classify market structure bias with confidence."""
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "NEUTRAL", 0.0

    hh = swing_highs[-1][1] > swing_highs[-2][1]
    hl = swing_lows[-1][1] > swing_lows[-2][1]
    lh = swing_highs[-1][1] < swing_highs[-2][1]
    ll = swing_lows[-1][1] < swing_lows[-2][1]

    if hh and hl:
        return "BULLISH", 0.8
    if lh and ll:
        return "BEARISH", 0.8
    if hh and ll:
        return "RANGING", 0.5
    if lh and hl:
        return "RANGING", 0.5
    return "NEUTRAL", 0.3


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class FusionStructureEngine:
    """Fusion Structure Engine — pure analysis, no execution.

    Parameters
    ----------
    swing_lookback : int
        N-bar lookback for swing point detection.
    level_cluster_pct : float
        Percentage tolerance for clustering levels.
    """

    def __init__(
        self,
        swing_lookback: int = 3,
        level_cluster_pct: float = 0.001,
        **_extra: Any,
    ) -> None:
        self.swing_lookback = swing_lookback
        self.level_cluster_pct = level_cluster_pct

    def analyze(
        self,
        candles: dict[str, list[dict[str, Any]]],
        symbol: str = "",
    ) -> StructureResult:
        """Analyse market structure across multiple timeframes."""
        if not candles:
            logger.warning("FusionStructureEngine: empty candles")
            return StructureResult(metadata={"symbol": symbol, "error": "no_candles"})

        tf_biases: dict[str, str] = {}
        all_levels: list[StructureLevel] = []
        primary_tf = self._select_primary(candles)
        primary_result: dict[str, Any] = {}

        for tf_name, tf_candles in candles.items():
            try:
                result = self._analyze_tf(tf_candles, tf_name)
                tf_biases[tf_name] = result.get("bias", "NEUTRAL")
                all_levels.extend(result.get("levels", []))
                if tf_name == primary_tf:
                    primary_result = result
            except Exception as exc:
                logger.warning("Structure engine TF %s error: %s", tf_name, exc)

        if not primary_result:
            return StructureResult(metadata={"symbol": symbol, "error": "no_primary"})

        # MTF alignment
        bias_values = list(tf_biases.values())
        if bias_values:
            dominant = max(set(bias_values), key=bias_values.count)
            mtf_alignment = bias_values.count(dominant) / len(bias_values)
        else:
            dominant = "NEUTRAL"
            mtf_alignment = 0.0

        current_close = primary_result.get("current_close", 0.0)
        supports = [l.price for l in all_levels if l.level_type == "SUPPORT" and l.price < current_close]  # noqa: E741
        resistances = [l.price for l in all_levels if l.level_type == "RESISTANCE" and l.price > current_close]  # noqa: E741

        return StructureResult(
            structure_bias=primary_result.get("bias", "NEUTRAL"),
            structure_score=primary_result.get("bias_score", 0.0),
            bos_detected=primary_result.get("bos", (False, "NONE"))[0],
            bos_direction=primary_result.get("bos", (False, "NONE"))[1],
            choch_detected=primary_result.get("choch", (False, "NONE"))[0],
            choch_direction=primary_result.get("choch", (False, "NONE"))[1],
            levels=all_levels,
            nearest_support=max(supports) if supports else 0.0,
            nearest_resistance=min(resistances) if resistances else 0.0,
            order_blocks=primary_result.get("order_blocks", []),
            swing_highs=primary_result.get("swing_high_prices", []),
            swing_lows=primary_result.get("swing_low_prices", []),
            mtf_structure_alignment=mtf_alignment,
            timeframe_biases=tf_biases,
            confidence=min(1.0, primary_result.get("bias_score", 0.0) * 0.5 + mtf_alignment * 0.5),
            metadata={"symbol": symbol, "primary_tf": primary_tf},
        )

    def _analyze_tf(self, tf_candles: list[dict[str, Any]], tf_name: str) -> dict[str, Any]:
        if len(tf_candles) < 10:
            return {"bias": "NEUTRAL", "bias_score": 0.0}

        opens = np.array([c.get("open", 0.0) for c in tf_candles], dtype=np.float64)
        highs = np.array([c.get("high", 0.0) for c in tf_candles], dtype=np.float64)
        lows = np.array([c.get("low", 0.0) for c in tf_candles], dtype=np.float64)
        closes = np.array([c.get("close", 0.0) for c in tf_candles], dtype=np.float64)

        swing_highs, swing_lows = _detect_swing_points(highs, lows, self.swing_lookback)
        current_close = float(closes[-1])

        bias, bias_score = _classify_structure_bias(swing_highs, swing_lows)
        bos = _detect_bos(swing_highs, swing_lows, current_close)
        choch = _detect_choch(swing_highs, swing_lows)
        levels = _find_structure_levels(swing_highs, swing_lows, current_close, self.level_cluster_pct, tf_name)
        order_blocks = _detect_order_blocks(opens, closes, highs, lows, swing_highs, swing_lows)

        return {
            "bias": bias,
            "bias_score": bias_score,
            "bos": bos,
            "choch": choch,
            "levels": levels,
            "order_blocks": order_blocks,
            "swing_high_prices": [sh[1] for sh in swing_highs],
            "swing_low_prices": [sl[1] for sl in swing_lows],
            "current_close": current_close,
        }

    @staticmethod
    def _select_primary(candles: dict[str, list[dict[str, Any]]]) -> str:
        for tf in ["H1", "M15", "H4", "D1"]:
            if tf in candles and len(candles[tf]) >= 20:
                return tf
        return max(candles, key=lambda k: len(candles[k]))
