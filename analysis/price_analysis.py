"""
Price analysis utilities — distance metrics, impulse detection, wick analysis.

Zone: analysis/ — L1-L11 support. No execution side-effects.
No market direction computation. Produces metrics only.

Fixes applied:
- _distance_from_mean: guards against ZeroDivisionError when mean == 0.
- Thresholds extracted to PriceAnalysisConfig dataclass.
- Wick calculation: corrected to use max(open, close) for body top,
  min(open, close) for body bottom.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PriceAnalysisConfig:
    """
    Configurable thresholds for price analysis metrics.

    Previously hardcoded — now injectable for backtesting,
    synthetic data, and per-instrument tuning.
    """

    # Distance from mean: flag as extreme if abs(distance) > this ratio
    extreme_distance: float = 0.025

    # Impulse detection: flag as impulse if abs(z-score) > this limit
    impulse_limit: float = 3.0

    # Minimum number of candles required for statistical calculations
    min_candles: int = 5

    # Wick ratio thresholds
    significant_wick_ratio: float = 0.6  # Wick > 60% of range = significant

    def __post_init__(self) -> None:
        if self.extreme_distance <= 0:
            raise ValueError(f"extreme_distance must be positive, got {self.extreme_distance}")
        if self.impulse_limit <= 0:
            raise ValueError(f"impulse_limit must be positive, got {self.impulse_limit}")
        if self.min_candles < 2:
            raise ValueError(f"min_candles must be >= 2, got {self.min_candles}")


@dataclass
class CandleData:
    """Single OHLC candle for analysis input."""

    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise ValueError(f"Candle high ({self.high}) < low ({self.low})")
        if self.high < self.open or self.high < self.close:
            raise ValueError(f"Candle high ({self.high}) must be >= open ({self.open}) and close ({self.close})")
        if self.low > self.open or self.low > self.close:
            raise ValueError(f"Candle low ({self.low}) must be <= open ({self.open}) and close ({self.close})")

    @property
    def body_top(self) -> float:
        """Top of the candle body (higher of open/close)."""
        return max(self.open, self.close)

    @property
    def body_bottom(self) -> float:
        """Bottom of the candle body (lower of open/close)."""
        return min(self.open, self.close)

    @property
    def body_size(self) -> float:
        """Absolute body size."""
        return abs(self.close - self.open)

    @property
    def full_range(self) -> float:
        """Full candle range (high - low)."""
        return self.high - self.low

    @property
    def upper_wick(self) -> float:
        """
        Upper wick length: distance from high to body top.

        Correct formula: high - max(open, close)
        NOT: high - max(close, low)  ← this was the bug
        """
        return self.high - self.body_top

    @property
    def lower_wick(self) -> float:
        """
        Lower wick length: distance from body bottom to low.

        Correct formula: min(open, close) - low
        """
        return self.body_bottom - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def is_doji(self) -> bool:
        """Doji: body is negligible relative to range."""
        rng = self.full_range
        if rng == 0:
            return True
        return self.body_size / rng < 0.05


# ─── Distance from Mean ──────────────────────────────────────


def distance_from_mean(
    value: float,
    mean: float,
) -> float:
    """
    Calculate proportional distance of value from mean.

    Returns (value - mean) / abs(mean), handling zero-mean safely.

    Args:
        value: Current value to measure.
        mean: Reference mean.

    Returns:
        Proportional distance. Returns math.inf (signed) if mean is zero
        and value is non-zero. Returns 0.0 if both are zero.
    """
    if mean == 0.0:
        if value == 0.0:
            return 0.0
        # Non-zero value, zero mean: infinite proportional distance
        return math.copysign(math.inf, value)

    return (value - mean) / abs(mean)


def is_extreme_distance(
    value: float,
    mean: float,
    config: PriceAnalysisConfig | None = None,
) -> bool:
    """
    Check if value is extremely far from mean.

    Args:
        value: Current value.
        mean: Reference mean.
        config: Thresholds. Uses defaults if None.

    Returns:
        True if abs(distance) exceeds extreme_distance threshold.
        Returns False if mean is zero and value is zero.
        Returns True if mean is zero and value is non-zero (infinite distance).
    """
    cfg = config or PriceAnalysisConfig()
    dist = distance_from_mean(value, mean)

    if math.isinf(dist):
        return True

    return abs(dist) > cfg.extreme_distance


# ─── Impulse Detection ───────────────────────────────────────


def compute_zscore(
    value: float,
    values: Sequence[float],
    config: PriceAnalysisConfig | None = None,
) -> float | None:
    """
    Compute z-score of value relative to a series.

    Returns None if insufficient data or zero standard deviation.

    Args:
        value: Value to score.
        values: Historical series.
        config: Min candle count threshold.

    Returns:
        Z-score float, or None if not computable.
    """
    cfg = config or PriceAnalysisConfig()

    if len(values) < cfg.min_candles:
        return None

    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    std = math.sqrt(variance)

    if std == 0.0:
        # All values identical — z-score is undefined
        # If value equals mean, it's not an impulse; if different, it is
        if value == mean:
            return 0.0
        return math.copysign(math.inf, value - mean)

    return (value - mean) / std


def is_impulse(
    value: float,
    values: Sequence[float],
    config: PriceAnalysisConfig | None = None,
) -> bool:
    """
    Detect if value is an impulse (outlier) relative to series.

    Returns False if z-score cannot be computed (insufficient data).
    """
    cfg = config or PriceAnalysisConfig()
    z = compute_zscore(value, values, cfg)

    if z is None:
        return False
    if math.isinf(z):
        return True

    return abs(z) > cfg.impulse_limit


# ─── Wick Analysis (corrected) ───────────────────────────────


@dataclass
class WickAnalysisResult:
    """Result of wick analysis over a series of candles."""

    avg_upper_wick: float
    avg_lower_wick: float
    max_upper_wick: float
    max_lower_wick: float
    avg_upper_wick_ratio: float  # avg(upper_wick / range), skipping zero-range
    avg_lower_wick_ratio: float  # avg(lower_wick / range), skipping zero-range
    significant_upper_count: int  # candles with upper wick ratio > threshold
    significant_lower_count: int  # candles with lower wick ratio > threshold
    candle_count: int


def analyze_wicks(
    candles: Sequence[CandleData],
    config: PriceAnalysisConfig | None = None,
) -> WickAnalysisResult | None:
    """
    Analyze upper and lower wicks across a candle series.

    Wick formulas (corrected):
        upper_wick = high - max(open, close)   → distance from high to body top
        lower_wick = min(open, close) - low     → distance from body bottom to low

    Previous bug: used max(close, low) instead of max(close, open) for upper wick.

    Args:
        candles: Sequence of CandleData.
        config: Analysis thresholds.

    Returns:
        WickAnalysisResult, or None if insufficient candles.
    """
    cfg = config or PriceAnalysisConfig()

    if len(candles) < 1:
        return None

    upper_wicks: list[float] = []
    lower_wicks: list[float] = []
    upper_ratios: list[float] = []
    lower_ratios: list[float] = []
    sig_upper = 0
    sig_lower = 0

    for c in candles:
        uw = c.upper_wick  # high - max(open, close) ← CORRECTED
        lw = c.lower_wick  # min(open, close) - low  ← CORRECTED

        upper_wicks.append(uw)
        lower_wicks.append(lw)

        rng = c.full_range
        if rng > 0:
            ur = uw / rng
            lr = lw / rng
            upper_ratios.append(ur)
            lower_ratios.append(lr)

            if ur > cfg.significant_wick_ratio:
                sig_upper += 1
            if lr > cfg.significant_wick_ratio:
                sig_lower += 1

    n = len(candles)
    return WickAnalysisResult(
        avg_upper_wick=sum(upper_wicks) / n,
        avg_lower_wick=sum(lower_wicks) / n,
        max_upper_wick=max(upper_wicks),
        max_lower_wick=max(lower_wicks),
        avg_upper_wick_ratio=(sum(upper_ratios) / len(upper_ratios)) if upper_ratios else 0.0,
        avg_lower_wick_ratio=(sum(lower_ratios) / len(lower_ratios)) if lower_ratios else 0.0,
        significant_upper_count=sig_upper,
        significant_lower_count=sig_lower,
        candle_count=n,
    )


# ─── Legacy / convenience wrapper (backward compatible) ──────

_default_config = PriceAnalysisConfig()


def check_extreme_distance(value: float, mean: float) -> bool:
    """Legacy wrapper. Prefer is_extreme_distance() with explicit config."""
    return is_extreme_distance(value, mean, _default_config)


def check_impulse(value: float, values: Sequence[float]) -> bool:
    """Legacy wrapper. Prefer is_impulse() with explicit config."""
    return is_impulse(value, values, _default_config)
