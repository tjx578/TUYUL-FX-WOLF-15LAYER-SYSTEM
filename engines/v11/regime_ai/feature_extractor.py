"""
Regime AI — Feature Extractor
Wolf-15 Layer Analysis System

Extracts statistical features from price/volume data for regime classification.
Pure analysis module (L1–L11). No execution side-effects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class RegimeFeatures:
    """Feature vector for regime classification."""

    volatility: float = 0.0
    trend_strength: float = 0.0
    mean_reversion: float = 0.0
    volume_profile: float = 0.0
    momentum: float = 0.0
    atr_ratio: float = 0.0
    spread_normalized: float = 0.0
    bar_range_avg: float = 0.0
    close_position_in_range: float = 0.0
    directional_bias: float = 0.0
    extras: dict[str, float] = field(default_factory=lambda: dict[str, float]())

    def to_array(self) -> np.ndarray:
        """Convert core features to numpy array for ML input."""
        return np.array([
            self.volatility,
            self.trend_strength,
            self.mean_reversion,
            self.volume_profile,
            self.momentum,
            self.atr_ratio,
            self.spread_normalized,
            self.bar_range_avg,
            self.close_position_in_range,
            self.directional_bias,
        ])
class FeatureExtractor:
    """
    Extracts statistical features from OHLCV data for regime detection.

    All methods are pure functions operating on numpy arrays.
    No side-effects, no execution logic.
    """
    def __init__(self, atr_period: int = 14, momentum_period: int = 10) -> None:
        """
        Initialize feature extractor.
        Args:
            atr_period: Period for ATR calculation.
            momentum_period: Period for momentum calculation.
        """
        super().__init__()
        self.atr_period = atr_period
        self.momentum_period = momentum_period
    def extract(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray | None = None,
    ) -> RegimeFeatures:
        """
        Extract all features from OHLCV data.
        Args:
            highs: Array of high prices.
            lows: Array of low prices.
            closes: Array of close prices.
            volumes: Optional volume data.
        Returns:
            RegimeFeatures dataclass with computed feature values.
        """
        features = RegimeFeatures()

        if len(closes) < max(self.atr_period, self.momentum_period) + 1:
            logger.warning("Insufficient data for feature extraction")
            return features
        features.volatility = self._calc_volatility(closes)
        features.trend_strength = self._calc_trend_strength(closes)
        features.mean_reversion = self._calc_mean_reversion(closes)
        features.momentum = self._calc_momentum(closes)
        features.atr_ratio = self._calc_atr_ratio(highs, lows, closes)
        features.bar_range_avg = self._calc_bar_range_avg(highs, lows)
        features.close_position_in_range = self._calc_close_position(
            highs, lows, closes
        )
        features.directional_bias = self._calc_directional_bias(closes)

        if volumes is not None and len(volumes) > 0:
            features.volume_profile = self._calc_volume_profile(volumes)
        return features
    def _calc_volatility(self, closes: np.ndarray) -> float:
        """Calculate normalized volatility (std of returns)."""
        if len(closes) < 2:
            return 0.0
        returns = np.diff(np.log(closes))
        return float(np.std(returns))
    def _calc_trend_strength(self, closes: np.ndarray) -> float:
        """Calculate trend strength using linear regression R-squared."""
        n = len(closes)
        if n < 5:
            return 0.0
        x = np.arange(n)
        correlation = np.corrcoef(x, closes)[0, 1]
        return float(correlation**2)  # R-squared
    def _calc_mean_reversion(self, closes: np.ndarray) -> float:
        """Calculate mean reversion tendency (Hurst exponent approximation)."""
        if len(closes) < 20:
            return 0.5
        returns = np.diff(np.log(closes))
        # Simplified variance ratio
        var1 = np.var(returns)
        if var1 == 0:
            return 0.5
        returns_2 = returns[::2][:len(returns) // 2]
        if len(returns_2) < 2:
            return 0.5
        var2 = np.var(returns_2)
        ratio = var2 / (2 * var1) if var1 > 0 else 0.5
        return float(np.clip(ratio, 0.0, 1.0))
    def _calc_momentum(self, closes: np.ndarray) -> float:
        """Calculate normalized momentum."""
        if len(closes) < self.momentum_period + 1:
            return 0.0
        mom = (closes[-1] - closes[-self.momentum_period - 1]) / closes[
            -self.momentum_period - 1
        ]
        return float(mom)
    def _calc_atr_ratio(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
    ) -> float:
        """Calculate ATR as ratio of price."""
        if len(highs) < self.atr_period + 1:
            return 0.0
        tr_values: list[float] = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            tr_values.append(tr)
        if not tr_values:
            return 0.0
        atr = float(np.mean(tr_values[-self.atr_period :]))
        avg_price = float(np.mean(closes[-self.atr_period :]))
        if avg_price == 0:
            return 0.0
        return atr / avg_price
    def _calc_bar_range_avg(
        self, highs: np.ndarray, lows: np.ndarray
    ) -> float:
        """Calculate average bar range normalized."""
        ranges = highs - lows
        avg_range = float(np.mean(ranges))
        avg_price = float(np.mean((highs + lows) / 2))
        if avg_price == 0:
            return 0.0
        return avg_range / avg_price
    def _calc_close_position(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
    ) -> float:
        """Calculate average close position within bar range (0=low, 1=high)."""
        ranges = highs - lows
        mask = ranges > 0
        if not np.any(mask):
            return 0.5
        positions = (closes[mask] - lows[mask]) / ranges[mask]
        return float(np.mean(positions))

    def _calc_directional_bias(self, closes: np.ndarray) -> float:
        """Calculate directional bias (-1 to +1)."""
        if len(closes) < 2:
            return 0.0
        returns = np.diff(closes)
        up = np.sum(returns > 0)
        total = len(returns)
        if total == 0:
            return 0.0
        return float((2 * up / total) - 1.0)
    def _calc_volume_profile(self, volumes: np.ndarray) -> float:
        """Calculate volume profile metric (recent vs historical)."""
        if len(volumes) < 10:
            return 0.0
        recent_avg = float(np.mean(volumes[-5:]))
        historical_avg = float(np.mean(volumes[:-5]))
        if historical_avg == 0:
            return 0.0
        return recent_avg / historical_avg
