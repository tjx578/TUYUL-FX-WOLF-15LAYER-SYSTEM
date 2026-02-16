"""
Exhaustion Detector - Structural Exhaustion State Classifier

Detects BUY_EXHAUSTION / SELL_EXHAUSTION / NEUTRAL by computing:
- Distance from rolling mean (normalized by mean)
- Impulse strength (price displacement / ATR)
- Wick pressure ratio (upper vs lower wicks using proper OHLC body/wick separation)

Self-computes ATR from candle history (no external dependency).
Returns frozen ExhaustionResult dataclass with to_dict().

Authority: ANALYSIS-ONLY. No execution side-effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]

from engines.v11.config import get_v11


class ExhaustionState(str, Enum):
    """Exhaustion state enum."""
    BUY_EXHAUSTION = "BUY_EXHAUSTION"
    SELL_EXHAUSTION = "SELL_EXHAUSTION"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class ExhaustionResult:
    """Immutable result of exhaustion detection."""
    
    state: ExhaustionState
    distance_from_mean: float
    impulse_strength: float
    wick_ratio: float
    confidence: float
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON consumption."""
        return {
            "state": self.state.value,
            "distance_from_mean": self.distance_from_mean,
            "impulse_strength": self.impulse_strength,
            "wick_ratio": self.wick_ratio,
            "confidence": self.confidence,
        }


class ExhaustionDetector:
    """
    Structural exhaustion state classifier.
    
    Detects price exhaustion using:
    1. Distance from rolling mean (normalized)
    2. Impulse strength (price displacement / ATR)
    3. Wick pressure ratio (upper vs lower wicks)
    
    Parameters
    ----------
    extreme_distance : float
        Distance threshold for exhaustion detection (default from config)
    impulse_limit : float
        Impulse strength threshold (default from config)
    wick_ratio : float
        Wick pressure ratio threshold (default from config)
    lookback_mean : int
        Lookback period for rolling mean (default from config)
    lookback_atr : int
        Lookback period for ATR calculation (default from config)
    """
    
    def __init__(
        self,
        extreme_distance: float | None = None,
        impulse_limit: float | None = None,
        wick_ratio: float | None = None,
        lookback_mean: int | None = None,
        lookback_atr: int | None = None,
    ) -> None:
        self._extreme_distance = extreme_distance or get_v11("exhaustion.extreme_distance", 0.025)
        self._impulse_limit = impulse_limit or get_v11("exhaustion.impulse_limit", 3.0)
        self._wick_ratio = wick_ratio or get_v11("exhaustion.wick_ratio", 1.5)
        self._lookback_mean = lookback_mean or get_v11("exhaustion.lookback_mean", 20)
        self._lookback_atr = lookback_atr or get_v11("exhaustion.lookback_atr", 14)
    
    def detect(self, candles: list[dict[str, Any]]) -> ExhaustionResult:
        """
        Detect exhaustion state from candle history.
        
        Args:
            candles: List of candles with OHLC data. Each candle should have:
                - open, high, low, close (float)
                Required minimum: max(lookback_mean, lookback_atr) + 1
        
        Returns:
            ExhaustionResult with state, metrics, and confidence
        """
        if not candles:
            return self._neutral_result("No candles provided")
        
        min_required = max(self._lookback_mean, self._lookback_atr) + 1
        if len(candles) < min_required:
            return self._neutral_result(f"Insufficient candles: {len(candles)} < {min_required}")
        
        try:
            # Extract OHLC
            closes = np.array([c["close"] for c in candles], dtype=np.float64)
            opens = np.array([c["open"] for c in candles], dtype=np.float64)
            highs = np.array([c["high"] for c in candles], dtype=np.float64)
            lows = np.array([c["low"] for c in candles], dtype=np.float64)
            
            # Validate data
            if np.any(np.isnan(closes)) or np.any(np.isnan(opens)) or \
               np.any(np.isnan(highs)) or np.any(np.isnan(lows)):
                return self._neutral_result("NaN values in candle data")
            
            # Current price
            current_close = closes[-1]
            
            # 1. Distance from rolling mean
            mean_lookback = closes[-self._lookback_mean:]
            rolling_mean = np.mean(mean_lookback)
            
            if rolling_mean == 0:
                return self._neutral_result("Zero rolling mean")
            
            distance = (current_close - rolling_mean) / rolling_mean
            
            # 2. Impulse strength (price displacement / ATR)
            atr = self._compute_atr(highs, lows, closes)
            
            if atr == 0:
                return self._neutral_result("Zero ATR")
            
            price_displacement = abs(current_close - closes[-2])
            impulse = price_displacement / atr
            
            # 3. Wick pressure ratio
            current_candle = candles[-1]
            wick_ratio = self._compute_wick_ratio(current_candle)
            
            # Detect exhaustion state
            state = self._classify_state(distance, impulse, wick_ratio)
            
            # Compute confidence (0-1)
            confidence = self._compute_confidence(distance, impulse, wick_ratio, state)
            
            return ExhaustionResult(
                state=state,
                distance_from_mean=distance,
                impulse_strength=impulse,
                wick_ratio=wick_ratio,
                confidence=confidence,
            )
            
        except Exception as e:
            return self._neutral_result(f"Error during detection: {str(e)}")
    
    def _compute_atr(self, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> float:
        """
        Compute Average True Range (ATR).
        
        ATR = mean(True Range over lookback period)
        True Range = max(high - low, |high - prev_close|, |low - prev_close|)
        """
        lookback = self._lookback_atr
        
        # Need at least lookback + 1 for previous close
        if len(closes) < lookback + 1:
            return 0.0
        
        # Get last N candles for ATR computation
        highs_atr = highs[-(lookback + 1):]
        lows_atr = lows[-(lookback + 1):]
        closes_atr = closes[-(lookback + 1):]
        
        true_ranges = []
        for i in range(1, len(highs_atr)):
            tr1 = highs_atr[i] - lows_atr[i]
            tr2 = abs(highs_atr[i] - closes_atr[i - 1])
            tr3 = abs(lows_atr[i] - closes_atr[i - 1])
            true_ranges.append(max(tr1, tr2, tr3))
        
        if not true_ranges:
            return 0.0
        
        return float(np.mean(true_ranges))
    
    def _compute_wick_ratio(self, candle: dict[str, Any]) -> float:
        """
        Compute wick pressure ratio: upper_wick / lower_wick.
        
        Body = |close - open|
        Upper wick = high - max(open, close)
        Lower wick = min(open, close) - low
        
        Returns ratio or 0 if lower wick is zero.
        """
        o = candle["open"]
        h = candle["high"]
        l = candle["low"]
        c = candle["close"]
        
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        
        if lower_wick == 0:
            return 0.0 if upper_wick == 0 else float('inf')
        
        return upper_wick / lower_wick
    
    def _classify_state(
        self, distance: float, impulse: float, wick_ratio: float
    ) -> ExhaustionState:
        """
        Classify exhaustion state based on metrics.
        
        BUY_EXHAUSTION: Price far above mean + strong impulse up + long upper wick
        SELL_EXHAUSTION: Price far below mean + strong impulse down + long lower wick
        NEUTRAL: Otherwise
        """
        # Check for BUY exhaustion (overextended upward)
        if (
            distance > self._extreme_distance and
            impulse > self._impulse_limit and
            wick_ratio > self._wick_ratio
        ):
            return ExhaustionState.BUY_EXHAUSTION
        
        # Check for SELL exhaustion (overextended downward)
        if (
            distance < -self._extreme_distance and
            impulse > self._impulse_limit and
            wick_ratio < (1.0 / self._wick_ratio)
        ):
            return ExhaustionState.SELL_EXHAUSTION
        
        return ExhaustionState.NEUTRAL
    
    def _compute_confidence(
        self, distance: float, impulse: float, wick_ratio: float, state: ExhaustionState
    ) -> float:
        """
        Compute confidence score (0-1) based on how extreme the metrics are.
        
        Higher values = stronger exhaustion signal.
        """
        if state == ExhaustionState.NEUTRAL:
            return 0.0
        
        # Normalize each metric to [0, 1] range
        distance_score = min(abs(distance) / self._extreme_distance, 1.0)
        impulse_score = min(impulse / self._impulse_limit, 1.0)
        
        if state == ExhaustionState.BUY_EXHAUSTION:
            wick_score = min(wick_ratio / self._wick_ratio, 1.0)
        else:  # SELL_EXHAUSTION
            wick_score = min((1.0 / wick_ratio) / (1.0 / self._wick_ratio), 1.0)
        
        # Average of normalized scores
        confidence = (distance_score + impulse_score + wick_score) / 3.0
        
        return float(np.clip(confidence, 0.0, 1.0))
    
    def _neutral_result(self, reason: str = "") -> ExhaustionResult:
        """Return neutral result with zero metrics."""
        return ExhaustionResult(
            state=ExhaustionState.NEUTRAL,
            distance_from_mean=0.0,
            impulse_strength=0.0,
            wick_ratio=0.0,
            confidence=0.0,
        )
