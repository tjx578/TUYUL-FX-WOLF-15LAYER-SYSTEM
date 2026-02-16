"""
Feature Extractor for Regime AI

Computes 6 features from OHLCV:
1. atr_ratio: ATR / price (normalized volatility)
2. entropy: Price distribution entropy
3. slope: Linear trend slope
4. corr_dispersion: Dispersion of O/H/L/C correlations
5. vol_imbalance: Volume imbalance ratio
6. dd_velocity: Drawdown velocity

Authority: ANALYSIS-ONLY. No execution side-effects.
"""

from __future__ import annotations

from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]


class FeatureExtractor:
    """
    Feature extractor for regime classification.
    
    Computes 6 features from OHLCV candle data.
    
    Parameters
    ----------
    window : int
        Lookback window for feature computation
    """
    
    def __init__(self, window: int = 50) -> None:
        self._window = window
    
    def extract(self, candles: list[dict[str, Any]]) -> np.ndarray | None:
        """
        Extract features from candle history.
        
        Args:
            candles: List of OHLCV candles
        
        Returns:
            Feature vector (6 elements) or None if insufficient data
        """
        if len(candles) < self._window:
            return None
        
        try:
            # Get last window candles
            recent = candles[-self._window:]
            
            opens = np.array([c["open"] for c in recent], dtype=np.float64)
            highs = np.array([c["high"] for c in recent], dtype=np.float64)
            lows = np.array([c["low"] for c in recent], dtype=np.float64)
            closes = np.array([c["close"] for c in recent], dtype=np.float64)
            volumes = np.array([c.get("volume", 0) for c in recent], dtype=np.float64)
            
            # Feature 1: ATR ratio
            atr_ratio = self._compute_atr_ratio(highs, lows, closes)
            
            # Feature 2: Entropy
            entropy = self._compute_entropy(closes)
            
            # Feature 3: Slope
            slope = self._compute_slope(closes)
            
            # Feature 4: Correlation dispersion
            corr_dispersion = self._compute_corr_dispersion(opens, highs, lows, closes)
            
            # Feature 5: Volume imbalance
            vol_imbalance = self._compute_vol_imbalance(volumes, closes)
            
            # Feature 6: Drawdown velocity
            dd_velocity = self._compute_dd_velocity(closes)
            
            features = np.array([
                atr_ratio,
                entropy,
                slope,
                corr_dispersion,
                vol_imbalance,
                dd_velocity,
            ], dtype=np.float64)
            
            # Replace NaN/inf with 0
            features = np.nan_to_num(features, nan=0.0, posinf=0.0, neginf=0.0)
            
            return features
            
        except Exception:
            return None
    
    def _compute_atr_ratio(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray
    ) -> float:
        """Compute ATR / price ratio."""
        true_ranges = []
        for i in range(1, len(highs)):
            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i - 1])
            tr3 = abs(lows[i] - closes[i - 1])
            true_ranges.append(max(tr1, tr2, tr3))
        
        if not true_ranges:
            return 0.0
        
        atr = np.mean(true_ranges)
        price = closes[-1]
        
        if price == 0:
            return 0.0
        
        return atr / price
    
    def _compute_entropy(self, closes: np.ndarray) -> float:
        """Compute price distribution entropy."""
        # Bin returns into histogram
        returns = np.diff(closes) / closes[:-1]
        
        if len(returns) == 0:
            return 0.0
        
        # Create histogram (10 bins)
        hist, _ = np.histogram(returns, bins=10)
        
        # Normalize to probabilities
        hist = hist / np.sum(hist)
        
        # Remove zeros
        hist = hist[hist > 0]
        
        # Compute entropy
        entropy = -np.sum(hist * np.log(hist))
        
        return float(entropy)
    
    def _compute_slope(self, closes: np.ndarray) -> float:
        """Compute linear trend slope."""
        x = np.arange(len(closes))
        
        # Linear regression
        mean_x = np.mean(x)
        mean_y = np.mean(closes)
        
        num = np.sum((x - mean_x) * (closes - mean_y))
        den = np.sum((x - mean_x) ** 2)
        
        if den == 0:
            return 0.0
        
        slope = num / den
        
        # Normalize by price
        if mean_y != 0:
            slope = slope / mean_y
        
        return float(slope)
    
    def _compute_corr_dispersion(
        self, opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray
    ) -> float:
        """Compute dispersion of OHLC correlations."""
        # Compute pairwise correlations
        correlations = []
        
        for arr1, arr2 in [
            (opens, highs), (opens, lows), (opens, closes),
            (highs, lows), (highs, closes), (lows, closes)
        ]:
            corr = np.corrcoef(arr1, arr2)[0, 1]
            if not np.isnan(corr):
                correlations.append(corr)
        
        if not correlations:
            return 0.0
        
        # Return standard deviation of correlations
        return float(np.std(correlations))
    
    def _compute_vol_imbalance(self, volumes: np.ndarray, closes: np.ndarray) -> float:
        """Compute volume imbalance ratio."""
        if len(volumes) < 2:
            return 0.0
        
        # Separate up/down volume
        returns = np.diff(closes)
        
        up_vol = np.sum(volumes[1:][returns > 0])
        down_vol = np.sum(volumes[1:][returns < 0])
        
        total_vol = up_vol + down_vol
        
        if total_vol == 0:
            return 0.0
        
        # Imbalance: (up - down) / total
        imbalance = (up_vol - down_vol) / total_vol
        
        return float(imbalance)
    
    def _compute_dd_velocity(self, closes: np.ndarray) -> float:
        """Compute drawdown velocity."""
        # Compute running max
        running_max = np.maximum.accumulate(closes)
        
        # Compute drawdown
        drawdowns = (closes - running_max) / running_max
        
        # Velocity = change in drawdown
        if len(drawdowns) < 2:
            return 0.0
        
        dd_velocity = np.mean(np.diff(drawdowns))
        
        return float(dd_velocity)
