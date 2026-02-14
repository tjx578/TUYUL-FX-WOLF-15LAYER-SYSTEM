"""
Core Fusion Unified Engine — v7.4r∞

Pipeline Coverage:
  L2  — Fusion Synchronization (FusionIntegrator, MonteCarloConfidence)
  L4  — Energy Field           (PhaseResonanceEngine, QuantumReflectiveEngine)
  L6  — Lorentzian Stab.       (AdaptiveThresholdController)
  L7  — Structural Judgement   (LiquidityZoneMapper, VolumeProfileAnalyzer, DivergenceType)
  L9  — Monte Carlo Prob.      (FTTCMonteCarloEngine)

Production-ready implementation with working EMA, divergence detection, volume profile, etc.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ============================================================================
# CONSTANTS
# ============================================================================

CONF12_REQUIRED = 0.92
DEFAULT_MC_SIMULATIONS = 5000
DEFAULT_FTTC_ITERATIONS = 50000
DEFAULT_MIN_INTEGRITY = 0.96
DEFAULT_META_DRIFT_FREEZE = 0.006
DEFAULT_EMA_FAST = 21
DEFAULT_EMA_SLOW = 50
DEFAULT_RSI_PERIOD = 14
DEFAULT_MACD_FAST = 12
DEFAULT_MACD_SLOW = 26
DEFAULT_MACD_SIGNAL = 9
MTF_TIMEFRAMES = ("H1", "H4", "D1", "W1")

# ============================================================================
# EXCEPTIONS
# ============================================================================

class FusionError(Exception):
    """Base exception for fusion engine errors."""
    pass


class FusionComputeError(FusionError):
    """Raised when computation fails."""
    pass


class FusionInputError(FusionError):
    """Raised when input validation fails."""
    pass


class FusionConfigError(FusionError):
    """Raised when configuration is invalid."""
    pass


# ============================================================================
# ENUMS
# ============================================================================

class FusionBiasMode(Enum):
    """Market bias classification."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class FusionState(Enum):
    """Fusion state classification."""
    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"


class MomentumBand(Enum):
    """Momentum strength bands."""
    EXTREME_HIGH = "EXTREME_HIGH"
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    EXTREME_LOW = "EXTREME_LOW"


class DivergenceType(Enum):
    """Types of price-indicator divergences."""
    REGULAR_BULLISH = "REGULAR_BULLISH"
    REGULAR_BEARISH = "REGULAR_BEARISH"
    HIDDEN_BULLISH = "HIDDEN_BULLISH"
    HIDDEN_BEARISH = "HIDDEN_BEARISH"
    NONE = "NONE"


class DivergenceStrength(Enum):
    """Divergence signal strength."""
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NONE = "NONE"


class FusionAction(Enum):
    """Recommended trading actions."""
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class MarketState(Enum):
    """Overall market condition."""
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"
    CONSOLIDATING = "CONSOLIDATING"


class TransitionState(Enum):
    """Market phase transitions."""
    ACCUMULATION = "ACCUMULATION"
    MARKUP = "MARKUP"
    DISTRIBUTION = "DISTRIBUTION"
    MARKDOWN = "MARKDOWN"
    EQUILIBRIUM = "EQUILIBRIUM"


class LiquidityType(Enum):
    """Liquidity zone classification."""
    BUY_ZONE = "BUY_ZONE"
    SELL_ZONE = "SELL_ZONE"
    BALANCED = "BALANCED"


class LiquidityStatus(Enum):
    """Liquidity health status."""
    HEALTHY = "HEALTHY"
    STRESSED = "STRESSED"
    CRITICAL = "CRITICAL"


class ResonanceState(Enum):
    """Phase resonance alignment."""
    ALIGNED = "ALIGNED"
    DIVERGENT = "DIVERGENT"
    NEUTRAL = "NEUTRAL"


# ============================================================================
# DATACLASSES
# ============================================================================

@dataclass
class MonteCarloResult:
    """Monte Carlo simulation result."""
    confidence: float
    iterations: int
    success_count: int
    mean_return: float
    std_dev: float
    median_return: float
    percentile_95: float
    percentile_5: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LiquidityMapResult:
    """Liquidity zone mapping result."""
    buy_zones: List[Tuple[float, float]]
    sell_zones: List[Tuple[float, float]]
    liquidity_type: LiquidityType
    liquidity_status: LiquidityStatus
    imbalance_ratio: float
    total_volume: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VolumeProfileResult:
    """Volume profile analysis result."""
    poc: float  # Point of Control
    vah: float  # Value Area High
    val: float  # Value Area Low
    hvn_zones: List[Tuple[float, float]]  # High Volume Nodes
    lvn_zones: List[Tuple[float, float]]  # Low Volume Nodes
    value_area_volume_pct: float
    total_volume: float
    price_levels: List[float]
    volume_distribution: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DivergenceResult:
    """Divergence detection result."""
    divergence_type: DivergenceType
    strength: DivergenceStrength
    confidence: float
    price_points: List[Tuple[int, float]]
    indicator_points: List[Tuple[int, float]]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FusionContext:
    """Comprehensive fusion analysis context."""
    symbol: str
    timeframe: str
    timestamp: float
    price: float
    volume: float
    technical_indicators: Dict[str, float] = field(default_factory=dict)
    reflective_metrics: Dict[str, float] = field(default_factory=dict)
    sentiment_scores: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReflectiveEntropy:
    """Reflective entropy measurement."""
    alpha: float  # Fast entropy
    beta: float   # Medium entropy
    gamma: float  # Slow entropy
    total: float
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PhaseResonance:
    """Phase resonance analysis."""
    state: ResonanceState
    alignment_score: float
    phase_diff: float
    timeframes: List[str]
    resonance_strength: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WLWCIResult:
    """Wolf Layer Weighted Confluence Index result."""
    wlwci: float
    layer_contributions: Dict[str, float]
    total_weight: float
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FTTCResult:
    """Fractal Trajectory Temporal Convergence result."""
    convergence_score: float
    trajectory_stability: float
    temporal_consistency: float
    iterations: int
    valid: bool
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RSIAlignment:
    """RSI multi-timeframe alignment."""
    timeframe: str
    rsi: float
    overbought: bool
    oversold: bool
    aligned: bool
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _calculate_ema(data: List[float], period: int) -> List[float]:
    """
    Calculate Exponential Moving Average.
    
    Args:
        data: Price data
        period: EMA period
        
    Returns:
        List of EMA values
    """
    if not data or period <= 0:
        raise FusionInputError("Invalid data or period for EMA calculation")
    
    if len(data) < period:
        raise FusionInputError(f"Insufficient data: need {period}, got {len(data)}")
    
    ema = []
    multiplier = 2.0 / (period + 1)
    
    # Initialize with SMA
    sma = sum(data[:period]) / period
    ema.append(sma)
    
    # Calculate EMA
    for i in range(period, len(data)):
        ema_val = (data[i] - ema[-1]) * multiplier + ema[-1]
        ema.append(ema_val)
    
    # Pad with None for alignment
    result = [None] * (period - 1) + ema
    return result


def _calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
    """
    Calculate Relative Strength Index.
    
    Args:
        prices: Price data
        period: RSI period
        
    Returns:
        List of RSI values
    """
    if not prices or period <= 0:
        raise FusionInputError("Invalid prices or period for RSI calculation")
    
    if len(prices) < period + 1:
        return [None] * len(prices)
    
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    rsi_values = [None]  # First value is None
    
    for i in range(period, len(deltas)):
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            rsi_values.append(rsi)
        
        # Update averages
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    # Pad to match input length
    rsi_values = [None] * period + rsi_values
    return rsi_values


def _find_peaks_troughs(data: List[float], window: int = 5) -> Tuple[List[int], List[int]]:
    """
    Find peaks and troughs in data.
    
    Args:
        data: Price or indicator data
        window: Window size for peak/trough detection
        
    Returns:
        Tuple of (peak_indices, trough_indices)
    """
    if not data or len(data) < window * 2 + 1:
        return [], []
    
    peaks = []
    troughs = []
    
    for i in range(window, len(data) - window):
        # Check if peak
        is_peak = all(data[i] >= data[i - j] for j in range(1, window + 1)) and \
                  all(data[i] >= data[i + j] for j in range(1, window + 1))
        
        # Check if trough
        is_trough = all(data[i] <= data[i - j] for j in range(1, window + 1)) and \
                    all(data[i] <= data[i + j] for j in range(1, window + 1))
        
        if is_peak:
            peaks.append(i)
        elif is_trough:
            troughs.append(i)
    
    return peaks, troughs


def _calculate_vwap(prices: List[float], volumes: List[float]) -> float:
    """
    Calculate Volume Weighted Average Price.
    
    Args:
        prices: Price data
        volumes: Volume data
        
    Returns:
        VWAP value
    """
    if not prices or not volumes or len(prices) != len(volumes):
        raise FusionInputError("Invalid prices or volumes for VWAP calculation")
    
    total_pv = sum(p * v for p, v in zip(prices, volumes))
    total_volume = sum(volumes)
    
    if total_volume == 0:
        return prices[-1] if prices else 0.0
    
    return total_pv / total_volume


def resolve_field_context(
    technical: Dict[str, float],
    reflective: Dict[str, float],
    sentiment: Dict[str, float]
) -> Dict[str, float]:
    """
    Resolve and merge field contexts.
    
    Args:
        technical: Technical indicators
        reflective: Reflective metrics
        sentiment: Sentiment scores
        
    Returns:
        Merged field context
    """
    context = {}
    
    # Merge all contexts
    context.update(technical)
    context.update({f"reflective_{k}": v for k, v in reflective.items()})
    context.update({f"sentiment_{k}": v for k, v in sentiment.items()})
    
    # Calculate composite scores
    if technical:
        context["technical_strength"] = np.mean(list(technical.values()))
    
    if reflective:
        context["reflective_strength"] = np.mean(list(reflective.values()))
    
    if sentiment:
        context["sentiment_strength"] = np.mean(list(sentiment.values()))
    
    return context


def sync_field_state(
    current_state: Dict[str, Any],
    new_data: Dict[str, Any],
    decay: float = 0.1
) -> Dict[str, Any]:
    """
    Synchronize field state with exponential decay.
    
    Args:
        current_state: Current field state
        new_data: New incoming data
        decay: Decay factor (0-1)
        
    Returns:
        Synchronized state
    """
    synced = current_state.copy()
    
    for key, value in new_data.items():
        if key in synced and isinstance(value, (int, float)):
            # Apply exponential decay
            synced[key] = synced[key] * (1 - decay) + value * decay
        else:
            synced[key] = value
    
    return synced


def evaluate_fusion_metrics(
    price: float,
    ema_fast: float,
    ema_slow: float,
    vwap: float,
    momentum: float
) -> Dict[str, float]:
    """
    Evaluate fusion metrics from core indicators.
    
    Args:
        price: Current price
        ema_fast: Fast EMA value
        ema_slow: Slow EMA value
        vwap: VWAP value
        momentum: Momentum value
        
    Returns:
        Fusion metrics dictionary
    """
    metrics = {}
    
    # EMA position
    if ema_slow > 0:
        metrics["ema_position"] = (price - ema_slow) / ema_slow
    else:
        metrics["ema_position"] = 0.0
    
    # EMA cross strength
    if ema_slow > 0:
        metrics["ema_cross_strength"] = (ema_fast - ema_slow) / ema_slow
    else:
        metrics["ema_cross_strength"] = 0.0
    
    # VWAP deviation
    if vwap > 0:
        metrics["vwap_deviation"] = (price - vwap) / vwap
    else:
        metrics["vwap_deviation"] = 0.0
    
    # Momentum strength
    metrics["momentum_strength"] = momentum
    
    # Composite fusion score
    metrics["fusion_score"] = (
        metrics["ema_cross_strength"] * 0.3 +
        metrics["vwap_deviation"] * 0.3 +
        momentum * 0.4
    )
    
    return metrics


def aggregate_multi_timeframe_metrics(
    mtf_data: Dict[str, Dict[str, float]]
) -> Dict[str, float]:
    """
    Aggregate metrics across multiple timeframes.
    
    Args:
        mtf_data: Dictionary of timeframe -> metrics
        
    Returns:
        Aggregated metrics
    """
    if not mtf_data:
        return {}
    
    # Weight by timeframe importance
    weights = {
        "H1": 0.15,
        "H4": 0.25,
        "D1": 0.35,
        "W1": 0.25
    }
    
    aggregated = defaultdict(float)
    
    for tf, metrics in mtf_data.items():
        weight = weights.get(tf, 0.25)
        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                aggregated[key] += value * weight
    
    return dict(aggregated)


def calculate_fusion_precision(
    ema_confidence: float,
    vwap_confidence: float,
    reflective_confidence: float
) -> float:
    """
    Calculate overall fusion precision.
    
    Args:
        ema_confidence: EMA-based confidence
        vwap_confidence: VWAP-based confidence
        reflective_confidence: Reflective confidence
        
    Returns:
        Combined precision score
    """
    # Weighted combination
    precision = (
        ema_confidence * 0.35 +
        vwap_confidence * 0.30 +
        reflective_confidence * 0.35
    )
    
    # Apply consistency boost
    if min(ema_confidence, vwap_confidence, reflective_confidence) > 0.8:
        precision *= 1.1
    
    return min(precision, 1.0)


def equilibrium_momentum_fusion_v6(
    prices: List[float],
    volumes: List[float],
    ema_fast: int = DEFAULT_EMA_FAST,
    ema_slow: int = DEFAULT_EMA_SLOW
) -> Dict[str, Any]:
    """
    Core equilibrium momentum fusion algorithm (v6).
    
    Args:
        prices: Price history
        volumes: Volume history
        ema_fast: Fast EMA period
        ema_slow: Slow EMA period
        
    Returns:
        Fusion analysis result with bias, state, momentum
    """
    if not prices or not volumes:
        raise FusionInputError("Empty prices or volumes")
    
    if len(prices) != len(volumes):
        raise FusionInputError("Prices and volumes length mismatch")
    
    if len(prices) < max(ema_fast, ema_slow):
        raise FusionInputError(f"Insufficient data for EMAs")
    
    # Calculate EMAs
    ema_fast_values = _calculate_ema(prices, ema_fast)
    ema_slow_values = _calculate_ema(prices, ema_slow)
    
    # Get current values
    current_price = prices[-1]
    current_ema_fast = ema_fast_values[-1]
    current_ema_slow = ema_slow_values[-1]
    
    # Calculate VWAP
    vwap = _calculate_vwap(prices[-50:], volumes[-50:])
    
    # Determine bias
    if current_ema_fast > current_ema_slow:
        if current_price > vwap:
            bias = FusionBiasMode.BULLISH
        else:
            bias = FusionBiasMode.NEUTRAL
    elif current_ema_fast < current_ema_slow:
        if current_price < vwap:
            bias = FusionBiasMode.BEARISH
        else:
            bias = FusionBiasMode.NEUTRAL
    else:
        bias = FusionBiasMode.NEUTRAL
    
    # Calculate momentum
    if len(prices) >= 10:
        momentum_pct = (prices[-1] - prices[-10]) / prices[-10]
    else:
        momentum_pct = 0.0
    
    # Determine state
    ema_diff = (current_ema_fast - current_ema_slow) / current_ema_slow if current_ema_slow > 0 else 0.0
    
    if ema_diff > 0.02 and momentum_pct > 0.015:
        state = FusionState.STRONG_BULLISH
    elif ema_diff > 0.005 and momentum_pct > 0:
        state = FusionState.BULLISH
    elif ema_diff < -0.02 and momentum_pct < -0.015:
        state = FusionState.STRONG_BEARISH
    elif ema_diff < -0.005 and momentum_pct < 0:
        state = FusionState.BEARISH
    else:
        state = FusionState.NEUTRAL
    
    # Determine momentum band
    abs_momentum = abs(momentum_pct)
    
    if abs_momentum > 0.05:
        momentum_band = MomentumBand.EXTREME_HIGH
    elif abs_momentum > 0.03:
        momentum_band = MomentumBand.HIGH
    elif abs_momentum > 0.015:
        momentum_band = MomentumBand.MODERATE
    elif abs_momentum > 0.005:
        momentum_band = MomentumBand.LOW
    else:
        momentum_band = MomentumBand.EXTREME_LOW
    
    return {
        "bias": bias,
        "state": state,
        "momentum_band": momentum_band,
        "momentum_pct": momentum_pct,
        "ema_fast": current_ema_fast,
        "ema_slow": current_ema_slow,
        "ema_diff": ema_diff,
        "vwap": vwap,
        "price": current_price,
        "price_vs_vwap": (current_price - vwap) / vwap if vwap > 0 else 0.0
    }


def equilibrium_momentum_fusion(
    prices: List[float],
    volumes: List[float],
    **kwargs
) -> Dict[str, Any]:
    """Wrapper for equilibrium momentum fusion v6."""
    return equilibrium_momentum_fusion_v6(prices, volumes, **kwargs)


# ============================================================================
# PRODUCTION CLASSES
# ============================================================================

class EMAFusionEngine:
    """EMA-based fusion engine with crossover detection."""
    
    def __init__(self, fast_period: int = DEFAULT_EMA_FAST, slow_period: int = DEFAULT_EMA_SLOW):
        self.fast_period = fast_period
        self.slow_period = slow_period
    
    def calculate(self, prices: List[float]) -> Dict[str, Any]:
        """
        Calculate EMA fusion metrics.
        
        Args:
            prices: Price history
            
        Returns:
            EMA analysis including crossovers
        """
        if len(prices) < self.slow_period:
            raise FusionInputError(f"Need at least {self.slow_period} prices")
        
        ema_fast = _calculate_ema(prices, self.fast_period)
        ema_slow = _calculate_ema(prices, self.slow_period)
        
        current_fast = ema_fast[-1]
        current_slow = ema_slow[-1]
        prev_fast = ema_fast[-2] if len(ema_fast) > 1 else current_fast
        prev_slow = ema_slow[-2] if len(ema_slow) > 1 else current_slow
        
        # Detect crossover
        bullish_cross = prev_fast <= prev_slow and current_fast > current_slow
        bearish_cross = prev_fast >= prev_slow and current_fast < current_slow
        
        # Calculate strength
        if current_slow > 0:
            cross_strength = (current_fast - current_slow) / current_slow
        else:
            cross_strength = 0.0
        
        return {
            "ema_fast": current_fast,
            "ema_slow": current_slow,
            "cross_strength": cross_strength,
            "bullish_cross": bullish_cross,
            "bearish_cross": bearish_cross,
            "confidence": min(abs(cross_strength) * 10, 1.0)
        }


class FusionPrecisionEngine:
    """Calculate fusion precision from multiple signals."""
    
    def __init__(self):
        self.ema_engine = EMAFusionEngine()
    
    def calculate_precision(
        self,
        prices: List[float],
        volumes: List[float],
        reflective_score: float = 0.5
    ) -> float:
        """
        Calculate overall fusion precision.
        
        Args:
            prices: Price history
            volumes: Volume history
            reflective_score: Reflective entropy score
            
        Returns:
            Precision score (0-1)
        """
        if not prices or not volumes:
            return 0.0
        
        # EMA confidence
        ema_result = self.ema_engine.calculate(prices)
        ema_confidence = ema_result["confidence"]
        
        # VWAP confidence
        vwap = _calculate_vwap(prices[-50:], volumes[-50:])
        vwap_dev = abs(prices[-1] - vwap) / vwap if vwap > 0 else 0.0
        vwap_confidence = 1.0 - min(vwap_dev * 5, 1.0)
        
        # Combine
        return calculate_fusion_precision(ema_confidence, vwap_confidence, reflective_score)


class MultiIndicatorDivergenceDetector:
    """Detect divergences between price and indicators."""
    
    def __init__(self, rsi_period: int = DEFAULT_RSI_PERIOD, window: int = 5):
        self.rsi_period = rsi_period
        self.window = window
    
    def detect_rsi_divergence(self, prices: List[float]) -> DivergenceResult:
        """
        Detect RSI divergence.
        
        Args:
            prices: Price history
            
        Returns:
            Divergence result
        """
        if len(prices) < self.rsi_period + self.window * 2:
            return DivergenceResult(
                divergence_type=DivergenceType.NONE,
                strength=DivergenceStrength.NONE,
                confidence=0.0,
                price_points=[],
                indicator_points=[]
            )
        
        # Calculate RSI
        rsi_values = _calculate_rsi(prices, self.rsi_period)
        rsi_clean = [v for v in rsi_values if v is not None]
        
        if len(rsi_clean) < self.window * 2:
            return DivergenceResult(
                divergence_type=DivergenceType.NONE,
                strength=DivergenceStrength.NONE,
                confidence=0.0,
                price_points=[],
                indicator_points=[]
            )
        
        # Find peaks and troughs
        price_peaks, price_troughs = _find_peaks_troughs(prices, self.window)
        rsi_peaks, rsi_troughs = _find_peaks_troughs(rsi_clean, self.window)
        
        # Check for regular bullish divergence (price lower low, RSI higher low)
        if len(price_troughs) >= 2 and len(rsi_troughs) >= 2:
            last_price_trough = price_troughs[-1]
            prev_price_trough = price_troughs[-2]
            
            # Find corresponding RSI troughs
            rsi_last = None
            rsi_prev = None
            
            for rt in reversed(rsi_troughs):
                if rt <= last_price_trough + 5:
                    rsi_last = rt
                    break
            
            for rt in reversed(rsi_troughs):
                if rt <= prev_price_trough + 5:
                    rsi_prev = rt
                    break
            
            if rsi_last is not None and rsi_prev is not None:
                price_lower = prices[last_price_trough] < prices[prev_price_trough]
                rsi_higher = rsi_clean[rsi_last] > rsi_clean[rsi_prev]
                
                if price_lower and rsi_higher:
                    strength_score = abs(rsi_clean[rsi_last] - rsi_clean[rsi_prev]) / 100.0
                    
                    if strength_score > 0.15:
                        strength = DivergenceStrength.STRONG
                    elif strength_score > 0.08:
                        strength = DivergenceStrength.MODERATE
                    else:
                        strength = DivergenceStrength.WEAK
                    
                    return DivergenceResult(
                        divergence_type=DivergenceType.REGULAR_BULLISH,
                        strength=strength,
                        confidence=min(strength_score * 5, 1.0),
                        price_points=[(prev_price_trough, prices[prev_price_trough]),
                                      (last_price_trough, prices[last_price_trough])],
                        indicator_points=[(rsi_prev, rsi_clean[rsi_prev]),
                                          (rsi_last, rsi_clean[rsi_last])]
                    )
        
        # Check for regular bearish divergence (price higher high, RSI lower high)
        if len(price_peaks) >= 2 and len(rsi_peaks) >= 2:
            last_price_peak = price_peaks[-1]
            prev_price_peak = price_peaks[-2]
            
            rsi_last = None
            rsi_prev = None
            
            for rp in reversed(rsi_peaks):
                if rp <= last_price_peak + 5:
                    rsi_last = rp
                    break
            
            for rp in reversed(rsi_peaks):
                if rp <= prev_price_peak + 5:
                    rsi_prev = rp
                    break
            
            if rsi_last is not None and rsi_prev is not None:
                price_higher = prices[last_price_peak] > prices[prev_price_peak]
                rsi_lower = rsi_clean[rsi_last] < rsi_clean[rsi_prev]
                
                if price_higher and rsi_lower:
                    strength_score = abs(rsi_clean[rsi_last] - rsi_clean[rsi_prev]) / 100.0
                    
                    if strength_score > 0.15:
                        strength = DivergenceStrength.STRONG
                    elif strength_score > 0.08:
                        strength = DivergenceStrength.MODERATE
                    else:
                        strength = DivergenceStrength.WEAK
                    
                    return DivergenceResult(
                        divergence_type=DivergenceType.REGULAR_BEARISH,
                        strength=strength,
                        confidence=min(strength_score * 5, 1.0),
                        price_points=[(prev_price_peak, prices[prev_price_peak]),
                                      (last_price_peak, prices[last_price_peak])],
                        indicator_points=[(rsi_prev, rsi_clean[rsi_prev]),
                                          (rsi_last, rsi_clean[rsi_last])]
                    )
        
        return DivergenceResult(
            divergence_type=DivergenceType.NONE,
            strength=DivergenceStrength.NONE,
            confidence=0.0,
            price_points=[],
            indicator_points=[]
        )


class FusionIntegrator:
    """Integrate technical, reflective, and sentiment contexts."""
    
    def __init__(self):
        self.history = deque(maxlen=100)
    
    def fuse_reflective_context(
        self,
        technical: Dict[str, float],
        reflective: Dict[str, float],
        sentiment: Dict[str, float]
    ) -> FusionContext:
        """
        Fuse multiple context layers.
        
        Args:
            technical: Technical indicators
            reflective: Reflective metrics
            sentiment: Sentiment scores
            
        Returns:
            Integrated fusion context
        """
        # Resolve contexts
        field_context = resolve_field_context(technical, reflective, sentiment)
        
        # Calculate composite scores
        tech_score = np.mean(list(technical.values())) if technical else 0.5
        refl_score = np.mean(list(reflective.values())) if reflective else 0.5
        sent_score = np.mean(list(sentiment.values())) if sentiment else 0.5
        
        # Weighted fusion
        fusion_score = tech_score * 0.4 + refl_score * 0.35 + sent_score * 0.25
        
        context = FusionContext(
            symbol="UNKNOWN",
            timeframe="UNKNOWN",
            timestamp=0.0,
            price=technical.get("price", 0.0),
            volume=technical.get("volume", 0.0),
            technical_indicators=technical,
            reflective_metrics=reflective,
            sentiment_scores=sentiment,
            metadata={
                "fusion_score": fusion_score,
                "field_context": field_context
            }
        )
        
        self.history.append(context)
        return context


class AdaptiveThresholdController:
    """Adaptive threshold control with Lorentzian stabilization."""
    
    def __init__(self, base_threshold: float = 0.85, stability_window: int = 20):
        self.base_threshold = base_threshold
        self.stability_window = stability_window
        self.history = deque(maxlen=stability_window)
    
    def recompute(self, current_signal: float, market_volatility: float) -> float:
        """
        Recompute adaptive threshold with Lorentzian stabilization.
        
        Args:
            current_signal: Current signal strength
            market_volatility: Market volatility measure
            
        Returns:
            Adjusted threshold
        """
        self.history.append(current_signal)
        
        if len(self.history) < 3:
            return self.base_threshold
        
        # Calculate stability using Lorentzian function
        # L(x) = 1 / (1 + x²)
        signal_variance = np.var(list(self.history))
        stability = 1.0 / (1.0 + signal_variance)
        
        # Adjust threshold based on stability and volatility
        volatility_factor = 1.0 + market_volatility * 0.5
        threshold = self.base_threshold * volatility_factor * stability
        
        # Clamp
        return max(0.7, min(threshold, 0.98))


class MonteCarloConfidence:
    """Monte Carlo simulation for confidence estimation."""
    
    def __init__(self, simulations: int = DEFAULT_MC_SIMULATIONS):
        self.simulations = simulations
    
    def run(
        self,
        signal_strength: float,
        market_data: List[float],
        volatility: float
    ) -> MonteCarloResult:
        """
        Run Monte Carlo simulation.
        
        Args:
            signal_strength: Input signal strength
            market_data: Historical market data
            volatility: Market volatility
            
        Returns:
            Monte Carlo result
        """
        if not market_data:
            raise FusionInputError("Empty market data for Monte Carlo")
        
        returns = []
        success_count = 0
        
        mean_return = np.mean(market_data[-20:]) if len(market_data) >= 20 else market_data[-1]
        
        for _ in range(self.simulations):
            # Simulate price movement
            random_shock = random.gauss(0, volatility)
            simulated_return = mean_return * (1 + random_shock)
            
            # Apply signal strength
            weighted_return = simulated_return * signal_strength
            returns.append(weighted_return)
            
            # Count successes (positive returns)
            if weighted_return > 0:
                success_count += 1
        
        returns_array = np.array(returns)
        
        return MonteCarloResult(
            confidence=success_count / self.simulations,
            iterations=self.simulations,
            success_count=success_count,
            mean_return=float(np.mean(returns_array)),
            std_dev=float(np.std(returns_array)),
            median_return=float(np.median(returns_array)),
            percentile_95=float(np.percentile(returns_array, 95)),
            percentile_5=float(np.percentile(returns_array, 5))
        )


class LiquidityZoneMapper:
    """Map liquidity zones from price and volume data."""
    
    def __init__(self, zone_threshold: float = 1.5):
        self.zone_threshold = zone_threshold
    
    def map_liquidity(
        self,
        prices: List[float],
        volumes: List[float]
    ) -> LiquidityMapResult:
        """
        Map liquidity zones.
        
        Args:
            prices: Price history
            volumes: Volume history
            
        Returns:
            Liquidity mapping result
        """
        if not prices or not volumes or len(prices) != len(volumes):
            raise FusionInputError("Invalid prices or volumes for liquidity mapping")
        
        # Calculate volume threshold
        avg_volume = np.mean(volumes)
        threshold = avg_volume * self.zone_threshold
        
        buy_zones = []
        sell_zones = []
        
        # Find high volume zones
        i = 0
        while i < len(volumes):
            if volumes[i] > threshold:
                # Start of zone
                zone_start = prices[i]
                zone_volume = volumes[i]
                j = i + 1
                
                # Extend zone
                while j < len(volumes) and volumes[j] > threshold:
                    zone_volume += volumes[j]
                    j += 1
                
                zone_end = prices[j - 1] if j > i else prices[i]
                
                # Classify as buy or sell zone
                price_change = zone_end - zone_start
                if price_change > 0:
                    buy_zones.append((min(zone_start, zone_end), max(zone_start, zone_end)))
                else:
                    sell_zones.append((min(zone_start, zone_end), max(zone_start, zone_end)))
                
                i = j
            else:
                i += 1
        
        # Calculate imbalance
        total_buy_volume = sum(v for i, v in enumerate(volumes) if i < len(buy_zones))
        total_sell_volume = sum(v for i, v in enumerate(volumes) if i < len(sell_zones))
        total_volume = sum(volumes)
        
        if total_volume > 0:
            imbalance_ratio = (total_buy_volume - total_sell_volume) / total_volume
        else:
            imbalance_ratio = 0.0
        
        # Determine liquidity type
        if imbalance_ratio > 0.15:
            liquidity_type = LiquidityType.BUY_ZONE
        elif imbalance_ratio < -0.15:
            liquidity_type = LiquidityType.SELL_ZONE
        else:
            liquidity_type = LiquidityType.BALANCED
        
        # Determine status
        if abs(imbalance_ratio) < 0.1:
            status = LiquidityStatus.HEALTHY
        elif abs(imbalance_ratio) < 0.3:
            status = LiquidityStatus.STRESSED
        else:
            status = LiquidityStatus.CRITICAL
        
        return LiquidityMapResult(
            buy_zones=buy_zones,
            sell_zones=sell_zones,
            liquidity_type=liquidity_type,
            liquidity_status=status,
            imbalance_ratio=imbalance_ratio,
            total_volume=total_volume
        )


class VolumeProfileAnalyzer:
    """Analyze volume profile and value areas."""
    
    def __init__(self, num_bins: int = 50, value_area_pct: float = 0.70):
        self.num_bins = num_bins
        self.value_area_pct = value_area_pct
    
    def analyze(
        self,
        prices: List[float],
        volumes: List[float]
    ) -> VolumeProfileResult:
        """
        Analyze volume profile.
        
        Args:
            prices: Price history
            volumes: Volume history
            
        Returns:
            Volume profile result
        """
        if not prices or not volumes or len(prices) != len(volumes):
            raise FusionInputError("Invalid prices or volumes")
        
        # Create price bins
        min_price = min(prices)
        max_price = max(prices)
        price_range = max_price - min_price
        
        if price_range == 0:
            # All prices are the same
            return VolumeProfileResult(
                poc=prices[0],
                vah=prices[0],
                val=prices[0],
                hvn_zones=[],
                lvn_zones=[],
                value_area_volume_pct=1.0,
                total_volume=sum(volumes),
                price_levels=[prices[0]],
                volume_distribution=[sum(volumes)]
            )
        
        bin_size = price_range / self.num_bins
        
        # Initialize bins
        volume_at_price = defaultdict(float)
        
        for price, volume in zip(prices, volumes):
            bin_idx = int((price - min_price) / bin_size)
            bin_idx = min(bin_idx, self.num_bins - 1)
            bin_price = min_price + bin_idx * bin_size + bin_size / 2
            volume_at_price[bin_price] += volume
        
        # Sort by volume
        sorted_levels = sorted(volume_at_price.items(), key=lambda x: x[1], reverse=True)
        
        if not sorted_levels:
            return VolumeProfileResult(
                poc=prices[-1],
                vah=prices[-1],
                val=prices[-1],
                hvn_zones=[],
                lvn_zones=[],
                value_area_volume_pct=0.0,
                total_volume=sum(volumes),
                price_levels=[],
                volume_distribution=[]
            )
        
        # Point of Control (highest volume)
        poc = sorted_levels[0][0]
        
        # Calculate value area
        total_volume = sum(volumes)
        target_volume = total_volume * self.value_area_pct
        
        accumulated_volume = 0.0
        value_area_prices = []
        
        for price, vol in sorted_levels:
            if accumulated_volume < target_volume:
                value_area_prices.append(price)
                accumulated_volume += vol
            else:
                break
        
        if value_area_prices:
            val = min(value_area_prices)
            vah = max(value_area_prices)
        else:
            val = min_price
            vah = max_price
        
        # Find HVN and LVN zones
        avg_volume = total_volume / len(volume_at_price)
        
        hvn_zones = []
        lvn_zones = []
        
        sorted_by_price = sorted(volume_at_price.items())
        
        for i, (price, vol) in enumerate(sorted_by_price):
            if vol > avg_volume * 1.5:
                # High Volume Node
                zone_start = price - bin_size / 2
                zone_end = price + bin_size / 2
                hvn_zones.append((zone_start, zone_end))
            elif vol < avg_volume * 0.5:
                # Low Volume Node
                zone_start = price - bin_size / 2
                zone_end = price + bin_size / 2
                lvn_zones.append((zone_start, zone_end))
        
        price_levels = [p for p, _ in sorted_by_price]
        volume_distribution = [v for _, v in sorted_by_price]
        
        return VolumeProfileResult(
            poc=poc,
            vah=vah,
            val=val,
            hvn_zones=hvn_zones,
            lvn_zones=lvn_zones,
            value_area_volume_pct=accumulated_volume / total_volume if total_volume > 0 else 0.0,
            total_volume=total_volume,
            price_levels=price_levels,
            volume_distribution=volume_distribution
        )


class HybridReflectiveCore:
    """Hybrid reflective evaluation core."""
    
    def __init__(self):
        self.fusion_engine = EMAFusionEngine()
        self.monte_carlo = MonteCarloConfidence()
        self.threshold_controller = AdaptiveThresholdController()
    
    def evaluate(
        self,
        prices: List[float],
        volumes: List[float],
        volatility: float = 0.02
    ) -> Dict[str, Any]:
        """
        Evaluate hybrid reflective metrics.
        
        Args:
            prices: Price history
            volumes: Volume history
            volatility: Market volatility
            
        Returns:
            Evaluation result
        """
        # EMA fusion
        ema_result = self.fusion_engine.calculate(prices)
        signal_strength = ema_result["confidence"]
        
        # Monte Carlo
        mc_result = self.monte_carlo.run(signal_strength, prices, volatility)
        
        # Adaptive threshold
        threshold = self.threshold_controller.recompute(signal_strength, volatility)
        
        # Combined evaluation
        passes_threshold = mc_result.confidence >= threshold
        
        return {
            "signal_strength": signal_strength,
            "mc_confidence": mc_result.confidence,
            "threshold": threshold,
            "passes": passes_threshold,
            "ema_result": ema_result,
            "mc_result": mc_result
        }


class QuantumReflectiveEngine:
    """Quantum reflective entropy engine."""
    
    def __init__(self):
        self.alpha_window = 5
        self.beta_window = 15
        self.gamma_window = 30
    
    def evaluate_reflective_entropy(
        self,
        prices: List[float],
        timestamp: float
    ) -> ReflectiveEntropy:
        """
        Evaluate reflective entropy across multiple scales.
        
        Args:
            prices: Price history
            timestamp: Current timestamp
            
        Returns:
            Reflective entropy measurement
        """
        if len(prices) < self.gamma_window:
            raise FusionInputError(f"Need at least {self.gamma_window} prices")
        
        # Calculate entropy for each scale
        alpha = self._calculate_entropy(prices[-self.alpha_window:])
        beta = self._calculate_entropy(prices[-self.beta_window:])
        gamma = self._calculate_entropy(prices[-self.gamma_window:])
        
        # Weighted total
        total = alpha * 0.5 + beta * 0.3 + gamma * 0.2
        
        return ReflectiveEntropy(
            alpha=alpha,
            beta=beta,
            gamma=gamma,
            total=total,
            timestamp=timestamp
        )
    
    def _calculate_entropy(self, data: List[float]) -> float:
        """Calculate entropy of price changes."""
        if len(data) < 2:
            return 0.0
        
        changes = [data[i] - data[i - 1] for i in range(1, len(data))]
        
        if not changes:
            return 0.0
        
        # Normalize
        abs_changes = [abs(c) for c in changes]
        total = sum(abs_changes)
        
        if total == 0:
            return 0.0
        
        probs = [c / total for c in abs_changes]
        
        # Shannon entropy
        entropy = -sum(p * math.log(p + 1e-10) for p in probs if p > 0)
        
        # Normalize to 0-1
        max_entropy = math.log(len(probs))
        if max_entropy > 0:
            return entropy / max_entropy
        return 0.0


class WLWCICalculator:
    """Wolf Layer Weighted Confluence Index calculator."""
    
    def __init__(self):
        self.layer_weights = {
            "L1": 0.05,
            "L2": 0.10,
            "L3": 0.08,
            "L4": 0.12,
            "L5": 0.10,
            "L6": 0.15,
            "L7": 0.15,
            "L8": 0.10,
            "L9": 0.15
        }
    
    def calculate(self, layer_scores: Dict[str, float]) -> WLWCIResult:
        """
        Calculate WLWCI.
        
        Args:
            layer_scores: Dictionary of layer scores
            
        Returns:
            WLWCI result
        """
        wlwci = 0.0
        contributions = {}
        total_weight = 0.0
        
        for layer, score in layer_scores.items():
            weight = self.layer_weights.get(layer, 0.0)
            contribution = score * weight
            contributions[layer] = contribution
            wlwci += contribution
            total_weight += weight
        
        # Normalize
        if total_weight > 0:
            wlwci /= total_weight
        
        # Calculate confidence
        confidence = min(len(layer_scores) / len(self.layer_weights), 1.0)
        
        return WLWCIResult(
            wlwci=wlwci,
            layer_contributions=contributions,
            total_weight=total_weight,
            confidence=confidence
        )


class PhaseResonanceEngine:
    """Detect phase resonance across timeframes."""
    
    def __init__(self):
        self.timeframes = list(MTF_TIMEFRAMES)
    
    def detect(
        self,
        mtf_data: Dict[str, List[float]]
    ) -> PhaseResonance:
        """
        Detect phase resonance.
        
        Args:
            mtf_data: Multi-timeframe price data
            
        Returns:
            Phase resonance result
        """
        if not mtf_data:
            return PhaseResonance(
                state=ResonanceState.NEUTRAL,
                alignment_score=0.0,
                phase_diff=0.0,
                timeframes=[],
                resonance_strength=0.0
            )
        
        # Calculate momentum for each timeframe
        momentums = {}
        for tf, prices in mtf_data.items():
            if len(prices) >= 10:
                momentum = (prices[-1] - prices[-10]) / prices[-10]
                momentums[tf] = momentum
        
        if not momentums:
            return PhaseResonance(
                state=ResonanceState.NEUTRAL,
                alignment_score=0.0,
                phase_diff=0.0,
                timeframes=[],
                resonance_strength=0.0
            )
        
        # Check alignment
        mom_values = list(momentums.values())
        all_positive = all(m > 0 for m in mom_values)
        all_negative = all(m < 0 for m in mom_values)
        
        if all_positive or all_negative:
            state = ResonanceState.ALIGNED
            alignment_score = 1.0
        else:
            positive_count = sum(1 for m in mom_values if m > 0)
            alignment_score = abs(positive_count / len(mom_values) - 0.5) * 2
            
            if alignment_score > 0.6:
                state = ResonanceState.ALIGNED
            elif alignment_score < 0.3:
                state = ResonanceState.DIVERGENT
            else:
                state = ResonanceState.NEUTRAL
        
        # Calculate phase difference
        phase_diff = np.std(mom_values) if len(mom_values) > 1 else 0.0
        
        # Resonance strength
        avg_momentum = np.mean([abs(m) for m in mom_values])
        resonance_strength = alignment_score * avg_momentum
        
        return PhaseResonance(
            state=state,
            alignment_score=alignment_score,
            phase_diff=float(phase_diff),
            timeframes=list(momentums.keys()),
            resonance_strength=resonance_strength
        )


class RSIAlignmentEngine:
    """RSI multi-timeframe alignment engine."""
    
    def __init__(self, rsi_period: int = DEFAULT_RSI_PERIOD):
        self.rsi_period = rsi_period
    
    def calculate(
        self,
        mtf_data: Dict[str, List[float]]
    ) -> List[RSIAlignment]:
        """
        Calculate RSI alignment across timeframes.
        
        Args:
            mtf_data: Multi-timeframe price data
            
        Returns:
            List of RSI alignments
        """
        alignments = []
        
        for tf, prices in mtf_data.items():
            if len(prices) < self.rsi_period + 1:
                continue
            
            rsi_values = _calculate_rsi(prices, self.rsi_period)
            rsi_clean = [v for v in rsi_values if v is not None]
            
            if not rsi_clean:
                continue
            
            current_rsi = rsi_clean[-1]
            
            overbought = current_rsi > 70
            oversold = current_rsi < 30
            aligned = 30 <= current_rsi <= 70
            
            alignment = RSIAlignment(
                timeframe=tf,
                rsi=current_rsi,
                overbought=overbought,
                oversold=oversold,
                aligned=aligned
            )
            
            alignments.append(alignment)
        
        return alignments


class FTTCMonteCarloEngine:
    """Fractal Trajectory Temporal Convergence Monte Carlo engine."""
    
    def __init__(self, iterations: int = DEFAULT_FTTC_ITERATIONS):
        self.iterations = iterations
    
    def validate_signal(
        self,
        signal_strength: float,
        market_data: List[float],
        min_integrity: float = DEFAULT_MIN_INTEGRITY
    ) -> FTTCResult:
        """
        Validate signal using FTTC Monte Carlo.
        
        Args:
            signal_strength: Input signal strength
            market_data: Historical market data
            min_integrity: Minimum integrity threshold
            
        Returns:
            FTTC result
        """
        if not market_data:
            raise FusionInputError("Empty market data for FTTC")
        
        convergence_count = 0
        trajectory_scores = []
        temporal_scores = []
        
        volatility = np.std(market_data[-50:]) if len(market_data) >= 50 else np.std(market_data)
        mean_price = np.mean(market_data[-20:]) if len(market_data) >= 20 else market_data[-1]
        
        for _ in range(self.iterations):
            # Simulate trajectory
            trajectory = [mean_price]
            
            for step in range(10):
                noise = random.gauss(0, volatility)
                next_price = trajectory[-1] * (1 + noise + signal_strength * 0.01)
                trajectory.append(next_price)
            
            # Check convergence
            final_return = (trajectory[-1] - trajectory[0]) / trajectory[0]
            
            if signal_strength > 0 and final_return > 0:
                convergence_count += 1
            elif signal_strength < 0 and final_return < 0:
                convergence_count += 1
            
            # Calculate trajectory stability
            traj_volatility = np.std(trajectory)
            trajectory_scores.append(1.0 / (1.0 + traj_volatility / mean_price))
            
            # Calculate temporal consistency
            changes = [trajectory[i] - trajectory[i-1] for i in range(1, len(trajectory))]
            consistency = 1.0 - abs(np.std(changes) / (volatility + 1e-10))
            temporal_scores.append(max(0, consistency))
        
        convergence_score = convergence_count / self.iterations
        trajectory_stability = np.mean(trajectory_scores)
        temporal_consistency = np.mean(temporal_scores)
        
        valid = convergence_score >= min_integrity
        
        return FTTCResult(
            convergence_score=convergence_score,
            trajectory_stability=float(trajectory_stability),
            temporal_consistency=float(temporal_consistency),
            iterations=self.iterations,
            valid=valid
        )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Constants
    "CONF12_REQUIRED",
    "DEFAULT_MC_SIMULATIONS",
    "DEFAULT_FTTC_ITERATIONS",
    "DEFAULT_MIN_INTEGRITY",
    "DEFAULT_META_DRIFT_FREEZE",
    "DEFAULT_EMA_FAST",
    "DEFAULT_EMA_SLOW",
    "DEFAULT_RSI_PERIOD",
    "DEFAULT_MACD_FAST",
    "DEFAULT_MACD_SLOW",
    "DEFAULT_MACD_SIGNAL",
    "MTF_TIMEFRAMES",
    
    # Exceptions
    "FusionError",
    "FusionComputeError",
    "FusionInputError",
    "FusionConfigError",
    
    # Enums
    "FusionBiasMode",
    "FusionState",
    "MomentumBand",
    "DivergenceType",
    "DivergenceStrength",
    "FusionAction",
    "MarketState",
    "TransitionState",
    "LiquidityType",
    "LiquidityStatus",
    "ResonanceState",
    
    # Dataclasses
    "MonteCarloResult",
    "LiquidityMapResult",
    "VolumeProfileResult",
    "DivergenceResult",
    "FusionContext",
    "ReflectiveEntropy",
    "PhaseResonance",
    "WLWCIResult",
    "FTTCResult",
    "RSIAlignment",
    
    # Helper functions
    "_calculate_ema",
    "_calculate_rsi",
    "_find_peaks_troughs",
    "_calculate_vwap",
    "resolve_field_context",
    "sync_field_state",
    "evaluate_fusion_metrics",
    "aggregate_multi_timeframe_metrics",
    "calculate_fusion_precision",
    "equilibrium_momentum_fusion_v6",
    "equilibrium_momentum_fusion",
    
    # Classes
    "EMAFusionEngine",
    "FusionPrecisionEngine",
    "MultiIndicatorDivergenceDetector",
    "FusionIntegrator",
    "AdaptiveThresholdController",
    "MonteCarloConfidence",
    "LiquidityZoneMapper",
    "VolumeProfileAnalyzer",
    "HybridReflectiveCore",
    "QuantumReflectiveEngine",
    "WLWCICalculator",
    "PhaseResonanceEngine",
    "RSIAlignmentEngine",
    "FTTCMonteCarloEngine",
]
