"""
Liquidity Sweep Scorer - 5-Factor Sweep Quality Scorer

Scores liquidity sweep quality (0.0-1.0) using 5 factors:
1. Equal high/low detection (tolerance-based)
2. Wick rejection ratio (proper body = |close-open|, wick = range-body)
3. Volume confirmation (spike above rolling average)
4. Failure to close beyond level
5. Multi-bar sweep pattern (not just single candle)

Returns frozen LiquiditySweepResult with to_dict().

Authority: ANALYSIS-ONLY. No execution side-effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]

from engines.v11.config import get_v11


@dataclass(frozen=True)
class LiquiditySweepResult:
    """Immutable result of liquidity sweep scoring."""
    
    sweep_detected: bool
    sweep_quality: float  # 0.0 - 1.0
    equal_level_detected: bool
    wick_rejection: float
    volume_spike: bool
    failed_to_close: bool
    multi_bar_pattern: bool
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON consumption."""
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
    5-Factor liquidity sweep quality scorer.
    
    Detects and scores liquidity sweeps using:
    1. Equal high/low level detection
    2. Wick rejection strength
    3. Volume spike confirmation
    4. Failed breakout (didn't close beyond level)
    5. Multi-bar sweep pattern
    
    Parameters
    ----------
    equal_level_tolerance : float
        Price tolerance for equal high/low detection (default from config)
    wick_rejection_min : float
        Minimum wick rejection ratio to qualify (default from config)
    volume_spike_threshold : float
        Volume spike multiple threshold (default from config)
    volume_lookback : int
        Lookback period for volume average (default from config)
    pattern_lookback : int
        Lookback for multi-bar pattern detection (default from config)
    """
    
    def __init__(
        self,
        equal_level_tolerance: float | None = None,
        wick_rejection_min: float | None = None,
        volume_spike_threshold: float | None = None,
        volume_lookback: int | None = None,
        pattern_lookback: int | None = None,
    ) -> None:
        self._tolerance = equal_level_tolerance or get_v11(
            "liquidity_sweep.equal_level_tolerance", 0.0002
        )
        self._wick_rejection_min = wick_rejection_min or get_v11(
            "liquidity_sweep.wick_rejection_min", 0.60
        )
        self._volume_threshold = volume_spike_threshold or get_v11(
            "liquidity_sweep.volume_spike_threshold", 1.5
        )
        self._volume_lookback = volume_lookback or get_v11(
            "liquidity_sweep.volume_lookback", 20
        )
        self._pattern_lookback = pattern_lookback or get_v11(
            "liquidity_sweep.pattern_lookback", 5
        )
    
    def score(
        self,
        candles: list[dict[str, Any]],
        direction: str = "bullish",
    ) -> LiquiditySweepResult:
        """
        Score liquidity sweep quality from candle history.
        
        Args:
            candles: List of candles with OHLC + volume data. Each candle should have:
                - open, high, low, close, volume (float/int)
            direction: "bullish" (sweep below lows) or "bearish" (sweep above highs)
        
        Returns:
            LiquiditySweepResult with quality score and factor breakdown
        """
        if not candles or len(candles) < self._pattern_lookback + 1:
            return self._no_sweep_result()
        
        try:
            # Extract data
            highs = np.array([c["high"] for c in candles], dtype=np.float64)
            lows = np.array([c["low"] for c in candles], dtype=np.float64)
            closes = np.array([c["close"] for c in candles], dtype=np.float64)
            opens = np.array([c["open"] for c in candles], dtype=np.float64)
            
            # Get volumes (default to 0 if not present)
            volumes = np.array([c.get("volume", 0) for c in candles], dtype=np.float64)
            
            # Validate data
            if np.any(np.isnan(highs)) or np.any(np.isnan(lows)) or \
               np.any(np.isnan(closes)) or np.any(np.isnan(opens)):
                return self._no_sweep_result()
            
            # Current candle
            current_candle = candles[-1]
            
            # Factor 1: Equal level detection
            equal_level = self._detect_equal_level(highs, lows, direction)
            
            # Factor 2: Wick rejection
            wick_rejection = self._compute_wick_rejection(current_candle, direction)
            
            # Factor 3: Volume spike
            volume_spike = self._detect_volume_spike(volumes)
            
            # Factor 4: Failed to close beyond level
            failed_close = self._detect_failed_close(
                highs, lows, closes, direction
            )
            
            # Factor 5: Multi-bar pattern
            multi_bar = self._detect_multi_bar_pattern(
                highs, lows, closes, direction
            )
            
            # Compute quality score (weighted average of factors)
            quality = self._compute_quality_score(
                equal_level, wick_rejection, volume_spike, failed_close, multi_bar
            )
            
            # Sweep detected if quality above threshold
            sweep_detected = quality >= 0.5  # At least 50% quality
            
            return LiquiditySweepResult(
                sweep_detected=sweep_detected,
                sweep_quality=quality,
                equal_level_detected=equal_level,
                wick_rejection=wick_rejection,
                volume_spike=volume_spike,
                failed_to_close=failed_close,
                multi_bar_pattern=multi_bar,
            )
            
        except Exception:
            return self._no_sweep_result()
    
    def _detect_equal_level(
        self, highs: np.ndarray, lows: np.ndarray, direction: str
    ) -> bool:
        """
        Detect equal highs or lows in recent candles.
        
        For bullish sweep: look for equal lows
        For bearish sweep: look for equal highs
        """
        lookback = self._pattern_lookback + 1
        
        if direction == "bullish":
            # Look for equal lows
            recent_lows = lows[-lookback:]
            min_low = np.min(recent_lows)
            # Count candles touching this low (within tolerance)
            touches = np.sum(np.abs(recent_lows - min_low) <= self._tolerance)
            return touches >= 2
        else:
            # Look for equal highs
            recent_highs = highs[-lookback:]
            max_high = np.max(recent_highs)
            # Count candles touching this high (within tolerance)
            touches = np.sum(np.abs(recent_highs - max_high) <= self._tolerance)
            return touches >= 2
    
    def _compute_wick_rejection(
        self, candle: dict[str, Any], direction: str
    ) -> float:
        """
        Compute wick rejection strength.
        
        Wick rejection = wick_length / total_range
        For bullish: use lower wick
        For bearish: use upper wick
        """
        o = candle["open"]
        h = candle["high"]
        l = candle["low"]
        c = candle["close"]
        
        total_range = h - l
        if total_range == 0:
            return 0.0
        
        if direction == "bullish":
            # Lower wick rejection
            lower_wick = min(o, c) - l
            return lower_wick / total_range
        else:
            # Upper wick rejection
            upper_wick = h - max(o, c)
            return upper_wick / total_range
    
    def _detect_volume_spike(self, volumes: np.ndarray) -> bool:
        """
        Detect volume spike in current candle vs rolling average.
        """
        if len(volumes) < self._volume_lookback + 1:
            return False
        
        # Exclude current candle from average
        historical_volumes = volumes[-(self._volume_lookback + 1):-1]
        current_volume = volumes[-1]
        
        avg_volume = np.mean(historical_volumes)
        
        if avg_volume == 0:
            return False
        
        return current_volume >= (avg_volume * self._volume_threshold)
    
    def _detect_failed_close(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, direction: str
    ) -> bool:
        """
        Detect failed breakout - price swept level but didn't close beyond it.
        
        For bullish: swept below previous low but closed above it
        For bearish: swept above previous high but closed below it
        """
        if len(closes) < 2:
            return False
        
        current_close = closes[-1]
        
        lookback = self._pattern_lookback + 1
        
        if direction == "bullish":
            # Check if swept below previous low
            previous_lows = lows[-lookback:-1]
            min_prev_low = np.min(previous_lows)
            current_low = lows[-1]
            
            # Swept if current low < previous min low
            swept = current_low < min_prev_low
            # Failed if closed above the level
            failed = current_close > min_prev_low
            
            return swept and failed
        else:
            # Check if swept above previous high
            previous_highs = highs[-lookback:-1]
            max_prev_high = np.max(previous_highs)
            current_high = highs[-1]
            
            # Swept if current high > previous max high
            swept = current_high > max_prev_high
            # Failed if closed below the level
            failed = current_close < max_prev_high
            
            return swept and failed
    
    def _detect_multi_bar_pattern(
        self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, direction: str
    ) -> bool:
        """
        Detect multi-bar sweep pattern (not just single candle).
        
        Look for multiple candles testing the same level before sweep.
        """
        lookback = self._pattern_lookback + 1
        
        if len(closes) < lookback:
            return False
        
        if direction == "bullish":
            recent_lows = lows[-lookback:]
            min_low = np.min(recent_lows)
            # Count how many bars tested near this low
            tests = np.sum(np.abs(recent_lows - min_low) <= self._tolerance * 2)
            return tests >= 3
        else:
            recent_highs = highs[-lookback:]
            max_high = np.max(recent_highs)
            # Count how many bars tested near this high
            tests = np.sum(np.abs(recent_highs - max_high) <= self._tolerance * 2)
            return tests >= 3
    
    def _compute_quality_score(
        self,
        equal_level: bool,
        wick_rejection: float,
        volume_spike: bool,
        failed_close: bool,
        multi_bar: bool,
    ) -> float:
        """
        Compute overall sweep quality score (0.0 - 1.0).
        
        Weighted average of all factors.
        """
        # Weights for each factor
        weights = {
            "equal_level": 0.25,
            "wick_rejection": 0.30,
            "volume": 0.20,
            "failed_close": 0.15,
            "multi_bar": 0.10,
        }
        
        score = 0.0
        score += weights["equal_level"] * (1.0 if equal_level else 0.0)
        score += weights["wick_rejection"] * wick_rejection
        score += weights["volume"] * (1.0 if volume_spike else 0.0)
        score += weights["failed_close"] * (1.0 if failed_close else 0.0)
        score += weights["multi_bar"] * (1.0 if multi_bar else 0.0)
        
        return float(np.clip(score, 0.0, 1.0))
    
    def _no_sweep_result(self) -> LiquiditySweepResult:
        """Return result indicating no sweep detected."""
        return LiquiditySweepResult(
            sweep_detected=False,
            sweep_quality=0.0,
            equal_level_detected=False,
            wick_rejection=0.0,
            volume_spike=False,
            failed_to_close=False,
            multi_bar_pattern=False,
        )
