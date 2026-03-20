"""
Liquidity Sweep Scorer — Layer-5 Component
Wolf-15 Layer Analysis System

Identifies and scores liquidity sweep patterns in price action.
Detects stop hunts, liquidity grabs, and institutional sweep patterns
that indicate smart money activity.

This module is analysis-only (L1–L11). No execution side-effects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class SweepType(Enum):
    """Classification of liquidity sweep patterns."""

    BULLISH_SWEEP = "bullish_sweep"
    BEARISH_SWEEP = "bearish_sweep"
    DOUBLE_SWEEP = "double_sweep"
    FAILED_SWEEP = "failed_sweep"
    NO_SWEEP = "no_sweep"


class SweepStrength(Enum):
    """Strength classification for detected sweeps."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    NONE = "none"


@dataclass
class LiquidityLevel:
    """Represents a significant liquidity level."""

    price: float
    level_type: str  # 'high', 'low', 'equal_highs', 'equal_lows'
    strength: float = 0.0
    touch_count: int = 0
    age_bars: int = 0
    volume_at_level: float = 0.0
    swept: bool = False
    sweep_bar_index: int | None = None


@dataclass
class SweepResult:
    """Result of liquidity sweep analysis."""

    sweep_type: SweepType = SweepType.NO_SWEEP
    sweep_strength: SweepStrength = SweepStrength.NONE
    score: float = 0.0
    confidence: float = 0.0
    swept_levels: list[LiquidityLevel] = field(default_factory=lambda: list[LiquidityLevel]())
    sweep_depth: float = 0.0
    reclaim_speed: float = 0.0
    volume_confirmation: bool = False
    details: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())


# Alias used by engines.v11 package __init__ exports
LiquiditySweepResult = SweepResult


@dataclass(frozen=True)
class SweepScoreResult:
    """Frozen result returned by LiquiditySweepScorer.score()."""

    sweep_detected: bool = False
    sweep_quality: float = 0.0
    equal_level_detected: bool = False
    wick_rejection: float = 0.0
    volume_spike: bool = False
    failed_to_close: bool = False
    multi_bar_pattern: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "sweep_detected": self.sweep_detected,
            "sweep_quality": self.sweep_quality,
            "equal_level_detected": self.equal_level_detected,
            "wick_rejection": self.wick_rejection,
            "volume_spike": self.volume_spike,
            "failed_to_close": self.failed_to_close,
            "multi_bar_pattern": self.multi_bar_pattern,
        }


class LiquiditySweepScorer:
    """
    Scores liquidity sweep patterns for the Wolf-15 analysis system.

    Identifies key liquidity levels (swing highs/lows, equal highs/lows)
    and detects when price sweeps through them before reversing,
    indicating institutional order flow.

    Analysis-only: produces scores and metadata, no execution side-effects.
    """

    def __init__(
        self,
        lookback_period: int = 50,
        sweep_threshold_pips: float = 5.0,
        min_reclaim_bars: int = 1,
        max_reclaim_bars: int = 5,
        equal_level_tolerance: float = 0.0003,
        min_touches_for_level: int = 2,
        *,
        pattern_lookback: int | None = None,
        wick_rejection_min: float = 0.50,
        volume_spike_threshold: float = 1.5,
        volume_lookback: int = 10,
    ) -> None:
        """
        Initialize the liquidity sweep scorer.

        Args:
            lookback_period: Number of bars to look back for liquidity levels.
            sweep_threshold_pips: Minimum pip movement beyond level to count as sweep.
            min_reclaim_bars: Minimum bars for price to reclaim after sweep.
            max_reclaim_bars: Maximum bars allowed for reclaim to be valid.
            equal_level_tolerance: Price tolerance for identifying equal highs/lows.
            min_touches_for_level: Minimum touches to confirm a liquidity level.
            pattern_lookback: Alias for lookback_period (used by score()).
            wick_rejection_min: Minimum wick ratio to count as rejection.
            volume_spike_threshold: Multiplier above average vol to flag spike.
            volume_lookback: Bars to average volume over.
        """
        super().__init__()
        self.lookback_period = lookback_period
        self._pattern_lookback = pattern_lookback if pattern_lookback is not None else 5
        self.sweep_threshold_pips = sweep_threshold_pips
        self.min_reclaim_bars = min_reclaim_bars
        self.max_reclaim_bars = max_reclaim_bars
        self.equal_level_tolerance = equal_level_tolerance
        self.min_touches_for_level = min_touches_for_level
        self.wick_rejection_min = wick_rejection_min
        self.volume_spike_threshold = volume_spike_threshold
        self.volume_lookback = volume_lookback

    # ── Public high-level API (candle-dict based) ─────────────────

    def score(
        self,
        candles: list[dict[str, Any]],
        direction: str = "bullish",
    ) -> SweepScoreResult:
        """Score liquidity sweep quality from a list of candle dicts.

        This is the primary entry point called by V11DataAdapter and
        L3_technical.  It accepts raw candle dicts (keys: open, high,
        low, close, volume) and returns a frozen SweepScoreResult.

        Args:
            candles: List of candle dicts with OHLCV keys.
            direction: 'bullish' or 'bearish'.

        Returns:
            Frozen SweepScoreResult.
        """
        if len(candles) < self._pattern_lookback:
            return SweepScoreResult()

        # -- extract arrays --------------------------------------------------
        highs = np.array([float(c["high"]) for c in candles])
        lows = np.array([float(c["low"]) for c in candles])
        np.array([float(c["close"]) for c in candles])
        np.array([float(c["open"]) for c in candles])
        volumes = np.array([float(c.get("volume", 0)) for c in candles])

        lookback = min(self.lookback_period, len(candles))

        # -- equal-level detection -------------------------------------------
        recent_lows = lows[-lookback :]
        recent_highs = highs[-lookback :]

        equal_level = False
        if direction == "bullish":
            equal_level = self._has_equal_levels(recent_lows)
        else:
            equal_level = self._has_equal_levels(recent_highs)

        # -- volume spike ----------------------------------------------------
        vol_spike = False
        if len(volumes) > self.volume_lookback:
            avg_vol = float(np.mean(volumes[-self.volume_lookback - 1 : -1]))
            if avg_vol > 0:
                vol_spike = float(volumes[-1]) >= avg_vol * self.volume_spike_threshold

        # -- wick rejection --------------------------------------------------
        last = candles[-1]
        o, h, l, c = float(last["open"]), float(last["high"]), float(last["low"]), float(last["close"])  # noqa: E741
        candle_range = h - l
        wick = 0.0
        if candle_range > 0:
            if direction == "bullish":
                lower_wick = min(o, c) - l
                wick = lower_wick / candle_range
            else:
                upper_wick = h - max(o, c)
                wick = upper_wick / candle_range

        # -- failed to close beyond level ------------------------------------
        failed_to_close = False
        if direction == "bullish" and len(lows) >= 2:
            prev_low = float(np.min(lows[-lookback : -1]))
            failed_to_close = l < prev_low and c > prev_low
        elif direction == "bearish" and len(highs) >= 2:
            prev_high = float(np.max(highs[-lookback : -1]))
            failed_to_close = h > prev_high and c < prev_high

        # -- multi-bar pattern -----------------------------------------------
        multi_bar = False
        if len(candles) >= 3:
            c3 = candles[-3:]
            if direction == "bullish":
                multi_bar = (
                    float(c3[0]["close"]) > float(c3[0]["open"])
                    and float(c3[1]["low"]) < float(c3[0]["low"])
                    and float(c3[2]["close"]) > float(c3[1]["high"])
                )
            else:
                multi_bar = (
                    float(c3[0]["close"]) < float(c3[0]["open"])
                    and float(c3[1]["high"]) > float(c3[0]["high"])
                    and float(c3[2]["close"]) < float(c3[1]["low"])
                )

        # -- composite quality -----------------------------------------------
        quality = 0.0
        if equal_level:
            quality += 0.25
        if vol_spike:
            quality += 0.20
        if wick >= self.wick_rejection_min:
            quality += 0.25
        if failed_to_close:
            quality += 0.15
        if multi_bar:
            quality += 0.15
        quality = min(quality, 1.0)

        sweep_detected = quality > 0.0

        return SweepScoreResult(
            sweep_detected=sweep_detected,
            sweep_quality=quality,
            equal_level_detected=equal_level,
            wick_rejection=wick,
            volume_spike=vol_spike,
            failed_to_close=failed_to_close,
            multi_bar_pattern=multi_bar,
        )

    def _has_equal_levels(self, prices: np.ndarray) -> bool:
        """Return True if *prices* contain a cluster of equal values."""
        if len(prices) < self.min_touches_for_level:
            return False
        sorted_p = np.sort(prices)
        for i in range(len(sorted_p) - self.min_touches_for_level + 1):
            window = sorted_p[i : i + self.min_touches_for_level]
            if float(window[-1] - window[0]) <= self.equal_level_tolerance:
                return True
        return False

    # ── Low-level numpy API (score_sweep) ─────────────────────────

    def identify_liquidity_levels(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        volumes: np.ndarray | None = None,
    ) -> list[LiquidityLevel]:
        """
        Identify significant liquidity levels from price data.

        Args:
            highs: Array of high prices.
            lows: Array of low prices.
            volumes: Optional array of volume data.

        Returns:
            List of identified liquidity levels sorted by significance.
        """
        levels: list[LiquidityLevel] = []

        if len(highs) < 5 or len(lows) < 5:
            return levels

        # Identify swing highs (local maxima)
        swing_highs = self._find_swing_points(highs, is_high=True)
        for idx, price in swing_highs:
            vol = float(volumes[idx]) if volumes is not None and idx < len(volumes) else 0.0
            levels.append(
                LiquidityLevel(
                    price=price,
                    level_type="high",
                    strength=0.0,
                    touch_count=1,
                    age_bars=len(highs) - 1 - idx,
                    volume_at_level=vol,
                )
            )

        # Identify swing lows (local minima)
        swing_lows = self._find_swing_points(lows, is_high=False)
        for idx, price in swing_lows:
            vol = float(volumes[idx]) if volumes is not None and idx < len(volumes) else 0.0
            levels.append(
                LiquidityLevel(
                    price=price,
                    level_type="low",
                    strength=0.0,
                    touch_count=1,
                    age_bars=len(lows) - 1 - idx,
                    volume_at_level=vol,
                )
            )

        # Identify equal highs / equal lows clusters
        equal_highs = self._find_equal_levels(
            [p for _, p in swing_highs], "equal_highs"
        )
        equal_lows = self._find_equal_levels(
            [p for _, p in swing_lows], "equal_lows"
        )
        levels.extend(equal_highs)
        levels.extend(equal_lows)

        # Score level strength
        self._score_level_strength(levels, highs, lows)

        # Sort by strength descending
        levels.sort(key=lambda lv: lv.strength, reverse=True)

        return levels

    def score_sweep(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray | None = None,
        pip_size: float = 0.0001,
    ) -> SweepResult:
        """
        Score the current candle context for liquidity sweep patterns.

        Args:
            highs: Array of high prices (most recent last).
            lows: Array of low prices (most recent last).
            closes: Array of close prices (most recent last).
            volumes: Optional volume data.
            pip_size: Pip size for the instrument.

        Returns:
            SweepResult with type, strength, score, and details.
        """
        if len(highs) < self.lookback_period:
            return SweepResult(details={"reason": "insufficient_data"})

        # Get liquidity levels from historical data (exclude last few bars)
        hist_end = max(len(highs) - 3, 5)
        levels = self.identify_liquidity_levels(
            highs[:hist_end],
            lows[:hist_end],
            volumes[:hist_end] if volumes is not None else None,
        )

        if not levels:
            return SweepResult(details={"reason": "no_levels_found"})

        # Check recent bars for sweep pattern
        bullish_sweep = self._check_bullish_sweep(
            highs, lows, closes, levels, pip_size
        )
        bearish_sweep = self._check_bearish_sweep(
            highs, lows, closes, levels, pip_size
        )

        # Return the stronger sweep if both detected
        if bullish_sweep.score >= bearish_sweep.score:
            return bullish_sweep
        return bearish_sweep

    def _find_swing_points(
        self, prices: np.ndarray, is_high: bool
    ) -> list[tuple[int, float]]:
        """Find swing highs or lows in price data."""
        swings: list[tuple[int, float]] = []
        if len(prices) < 5:
            return swings

        for i in range(2, len(prices) - 2):
            if is_high:
                if (
                    prices[i] > prices[i - 1]
                    and prices[i] > prices[i - 2]
                    and prices[i] > prices[i + 1]
                    and prices[i] > prices[i + 2]
                ):
                    swings.append((i, float(prices[i])))
            else:
                if (
                    prices[i] < prices[i - 1]
                    and prices[i] < prices[i - 2]
                    and prices[i] < prices[i + 1]
                    and prices[i] < prices[i + 2]
                ):
                    swings.append((i, float(prices[i])))

        return swings

    def _find_equal_levels(
        self, prices: list[float], level_type: str
    ) -> list[LiquidityLevel]:
        """Find clusters of equal highs or equal lows."""
        if len(prices) < 2:
            return []

        clusters: list[LiquidityLevel] = []
        used: set[int] = set()

        for i, p1 in enumerate(prices):
            if i in used:
                continue
            cluster_prices = [p1]
            cluster_indices = {i}

            for j in range(i + 1, len(prices)):
                if j in used:
                    continue
                if abs(p1 - prices[j]) <= self.equal_level_tolerance:
                    cluster_prices.append(prices[j])
                    cluster_indices.add(j)

            if len(cluster_prices) >= self.min_touches_for_level:
                avg_price = sum(cluster_prices) / len(cluster_prices)
                clusters.append(
                    LiquidityLevel(
                        price=avg_price,
                        level_type=level_type,
                        strength=len(cluster_prices) * 0.3,
                        touch_count=len(cluster_prices),
                    )
                )
                used.update(cluster_indices)

        return clusters

    def _score_level_strength(
        self,
        levels: list[LiquidityLevel],
        highs: np.ndarray,
        lows: np.ndarray,
    ) -> None:
        """Score the strength of each liquidity level."""
        for level in levels:
            strength = 0.0

            # Touch count bonus
            strength += min(level.touch_count * 0.2, 1.0)

            # Equal levels are stronger
            if level.level_type in ("equal_highs", "equal_lows"):
                strength += 0.3

            # Volume confirmation
            if level.volume_at_level > 0:
                strength += 0.2

            # Recency bonus (more recent = stronger)
            if level.age_bars < 10:
                strength += 0.2
            elif level.age_bars < 20:
                strength += 0.1

            level.strength = min(strength, 1.0)

    def _check_bullish_sweep(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        levels: list[LiquidityLevel],
        pip_size: float,
    ) -> SweepResult:
        """Check for bullish sweep (sweep below lows then reclaim)."""
        result = SweepResult()
        low_levels = [
            lv for lv in levels if lv.level_type in ("low", "equal_lows")
        ]

        if not low_levels:
            return result

        recent_low = float(np.min(lows[-self.max_reclaim_bars :]))
        recent_close = float(closes[-1])
        swept: list[LiquidityLevel] = []

        for level in low_levels:
            sweep_distance = level.price - recent_low
            if sweep_distance > self.sweep_threshold_pips * pip_size and recent_close > level.price:
                level.swept = True
                swept.append(level)

        if not swept:
            return result

        # Calculate score
        avg_strength = sum(lv.strength for lv in swept) / len(swept)
        sweep_depth = max(
            (lv.price - recent_low) / pip_size for lv in swept
        )
        reclaim_ratio = (recent_close - recent_low) / max(
            float(np.max(highs[-self.max_reclaim_bars :]) - recent_low), pip_size
        )

        score = min(
            (avg_strength * 0.4 + min(sweep_depth / 20, 1.0) * 0.3 + reclaim_ratio * 0.3),
            1.0,
        )

        strength = SweepStrength.NONE
        if score >= 0.7:
            strength = SweepStrength.STRONG
        elif score >= 0.4:
            strength = SweepStrength.MODERATE
        elif score > 0.0:
            strength = SweepStrength.WEAK

        return SweepResult(
            sweep_type=SweepType.BULLISH_SWEEP,
            sweep_strength=strength,
            score=score,
            confidence=score * 0.9,
            swept_levels=swept,
            sweep_depth=sweep_depth,
            reclaim_speed=reclaim_ratio,
            details={
                "num_levels_swept": len(swept),
                "avg_level_strength": avg_strength,
            },
        )

    def _check_bearish_sweep(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        levels: list[LiquidityLevel],
        pip_size: float,
    ) -> SweepResult:
        """Check for bearish sweep (sweep above highs then reclaim)."""
        result = SweepResult()
        high_levels = [
            lv for lv in levels if lv.level_type in ("high", "equal_highs")
        ]

        if not high_levels:
            return result

        recent_high = float(np.max(highs[-self.max_reclaim_bars :]))
        recent_close = float(closes[-1])
        swept: list[LiquidityLevel] = []

        for level in high_levels:
            sweep_distance = recent_high - level.price
            if sweep_distance > self.sweep_threshold_pips * pip_size and recent_close < level.price:
                level.swept = True
                swept.append(level)

        if not swept:
            return result

        # Calculate score
        avg_strength = sum(lv.strength for lv in swept) / len(swept)
        sweep_depth = max(
            (recent_high - lv.price) / pip_size for lv in swept
        )
        reclaim_ratio = (recent_high - recent_close) / max(
            float(recent_high - np.min(lows[-self.max_reclaim_bars :])), pip_size
        )

        score = min(
            (avg_strength * 0.4 + min(sweep_depth / 20, 1.0) * 0.3 + reclaim_ratio * 0.3),
            1.0,
        )

        strength = SweepStrength.NONE
        if score >= 0.7:
            strength = SweepStrength.STRONG
        elif score >= 0.4:
            strength = SweepStrength.MODERATE
        elif score > 0.0:
            strength = SweepStrength.WEAK

        return SweepResult(
            sweep_type=SweepType.BEARISH_SWEEP,
            sweep_strength=strength,
            score=score,
            confidence=score * 0.9,
            swept_levels=swept,
            sweep_depth=sweep_depth,
            reclaim_speed=reclaim_ratio,
            details={
                "num_levels_swept": len(swept),
                "avg_level_strength": avg_strength,
            },
        )
