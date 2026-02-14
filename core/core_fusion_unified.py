"""
core_fusion_unified.py - TUYUL FX ULTIMATE HYBRID AGI 🧠💹
==========================================================

Unified Core Fusion Module v7.0r∞
Menggabungkan seluruh komponen fusion analysis untuk sistem trading.

Komponen yang digabungkan:
- Field Sync (Context resolution and synchronization)
- EMA Fusion Engine (EMA-based fusion signals)
- Fusion Metrics Analyzer (Evaluation and analysis)
- Fusion Precision Engine (Precision weight calculation)
- Equilibrium Momentum Fusion (Momentum balance analysis)
- Multi-Indicator Divergence Detector (RSI/MACD/CCI/MFI divergence)
- Adaptive Threshold Controller (Dynamic threshold management)
- Fusion Integrator (Core Layer 12 integration)

Author: TUYUL FX Dev Division 🐺
Version: v7.0r∞ Unified
Codename: Alpha Wolf Quantum Reflective AGI
"""

from __future__ import annotations

import json
import logging
import math
import random
import statistics

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

Dict = dict
List = list
Tuple = tuple

# Optional numpy import with fallback
try:
    import numpy as np  # type: ignore

    HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore
    HAS_NUMPY = False

# Logger
logger = logging.getLogger(__name__)

# =============================================================================
# ⚠️ SECTION 1: EXCEPTION HIERARCHY
# =============================================================================


class FusionError(Exception):
    """Base exception for all fusion module errors."""


class FusionComputeError(FusionError):
    """Raised when fusion computation fails."""


class FusionInputError(FusionError):
    """Raised when fusion input validation fails."""


class FusionConfigError(FusionError):
    """Raised when fusion configuration is invalid."""


# =============================================================================
# 📊 SECTION 2: ENUMERATIONS
# =============================================================================


class FusionBiasMode(Enum):
    """Fusion bias direction modes."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class FusionState(Enum):
    """Fusion state indicators."""

    STRONG_BULLISH = "strong_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    STRONG_BEARISH = "strong_bearish"


class MomentumBand(Enum):
    """Momentum band classifications."""

    HYPER = "hyper"
    STRONG = "strong"
    BALANCED = "balanced"
    CALM = "calm"


class DivergenceType(Enum):
    """Types of divergence."""

    REGULAR_BULLISH = "regular_bullish"
    REGULAR_BEARISH = "regular_bearish"
    HIDDEN_BULLISH = "hidden_bullish"
    HIDDEN_BEARISH = "hidden_bearish"
    NONE = "none"


class DivergenceStrength(Enum):
    """Divergence strength levels."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


class FusionAction(Enum):
    """Fusion action recommendations."""

    EXECUTE = "EXECUTE"
    MONITOR = "MONITOR"
    WAIT = "WAIT"


class MarketState(Enum):
    """Market states for FTTC transitions."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"


class TransitionState(Enum):
    """States for Q-Matrix transitions."""

    STRONG_BULLISH = "STRONG_BULLISH"
    WEAK_BULLISH = "WEAK_BULLISH"
    NEUTRAL = "NEUTRAL"
    WEAK_BEARISH = "WEAK_BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"


class LiquidityType(Enum):
    """Types of liquidity zones."""

    BUY_SIDE = "buy_side"
    SELL_SIDE = "sell_side"
    EQUAL_HIGHS = "equal_highs"
    EQUAL_LOWS = "equal_lows"
    SWING_HIGH = "swing_high"
    SWING_LOW = "swing_low"
    SESSION_HIGH = "session_high"
    SESSION_LOW = "session_low"


class LiquidityStatus(Enum):
    """Status of liquidity zone."""

    UNTAPPED = "untapped"
    PARTIALLY_SWEPT = "partially_swept"
    FULLY_SWEPT = "swept"


class ResonanceState(Enum):
    """Phase resonance states."""

    EXPANSION_RESONANCE = "Expansion Resonance"
    EQUILIBRIUM_RESONANCE = "Equilibrium Resonance"
    ADAPTIVE_COMPRESSION = "Adaptive Compression"
    PHASE_DRIFT_DETECTED = "Phase Drift Detected"


# =============================================================================
# ⚙️ SECTION 3: CONSTANTS & CONFIGURATION
# =============================================================================

# Fusion Precision Defaults
DEFAULT_EMA_FAST: Final[int] = 21
DEFAULT_EMA_SLOW: Final[int] = 50
DEFAULT_PRECISION_WEIGHT_MIN: Final[float] = 0.70
DEFAULT_PRECISION_WEIGHT_MAX: Final[float] = 1.30

# Threshold Controller Defaults
DEFAULT_META_DRIFT_FREEZE: Final[float] = 0.006
DEFAULT_MIN_INTEGRITY: Final[float] = 0.96

# Divergence Detector Defaults
DEFAULT_LOOKBACK_BARS: Final[int] = 50
DEFAULT_MIN_BARS_APART: Final[int] = 5
DEFAULT_MAX_BARS_APART: Final[int] = 30
DEFAULT_MIN_CONFLUENCE: Final[int] = 2

# Monte Carlo Defaults
DEFAULT_MC_SIMULATIONS: Final[int] = 5000
DEFAULT_MC_MIN_SIMULATIONS: Final[int] = 500

# FTTC Defaults
DEFAULT_FTTC_ITERATIONS: Final[int] = 50000
DEFAULT_FTTC_HORIZON_DAYS: Final[int] = 180
DEFAULT_FTTC_CONFIDENCE: Final[float] = 0.95

# MTF Timeframes
MTF_TIMEFRAMES: Final[Tuple[str, ...]] = ("H1", "H4", "D1", "W1")

# Liquidity Defaults
DEFAULT_SWING_LOOKBACK: Final[int] = 20
DEFAULT_EQUAL_LEVEL_TOLERANCE: Final[float] = 0.0005


# =============================================================================
# 🛠️ SECTION 4: UTILITY FUNCTIONS
# =============================================================================


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp value between low and high bounds."""
    if math.isnan(value):
        return low
    return max(low, min(high, value))


def _clamp01(value: float) -> float:
    """Clamp value between 0 and 1."""
    return _clamp(value, 0.0, 1.0)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float."""
    try:
        result = float(value)
        if not math.isfinite(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def _inputs_valid(*values: float) -> bool:
    """Check if all values are valid finite numbers."""
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def _last_numeric(values: Sequence[Any] | None) -> float | None:
    """Get last numeric value from sequence."""
    if not values:
        return None
    try:
        return float(values[-1])
    except (TypeError, ValueError):
        return None


def _min_numeric(values: Sequence[Any] | None) -> float | None:
    """Get minimum numeric value from sequence."""
    if not values:
        return None
    numeric_values = []
    for value in values:
        try:
            numeric_values.append(float(value))
        except (TypeError, ValueError):
            continue
    return min(numeric_values) if numeric_values else None


def _average_numeric(values: Sequence[Any] | None) -> float | None:
    """Get average of numeric values in sequence."""
    if not values:
        return None
    numeric_values = []
    for value in values:
        try:
            numeric_values.append(float(value))
        except (TypeError, ValueError):
            continue
    if not numeric_values:
        return None
    return sum(numeric_values) / len(numeric_values)


# =============================================================================
# 📦 SECTION 5: DATACLASSES
# =============================================================================


@dataclass
class FieldContext:
    """Field context for fusion analysis."""

    pair: str
    timeframe: str
    field_state: str
    coherence: float
    resonance: float
    phase: str
    timestamp: str
    alpha: float = 1.0
    beta: float = 1.0
    gamma: float = 1.0
    lambda_esi: float = 0.06
    field_integrity: float = 0.95

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FusionPrecisionResult:
    """Result from fusion precision calculation."""

    timestamp: str
    fusion_strength: float
    bias_mode: str
    precision_weight: float
    precision_confidence_hint: float
    details: Dict[str, Any]
    symbol: str | None = None
    pair: str | None = None
    trade_id: str | None = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EquilibriumResult:
    """Result from equilibrium momentum fusion."""

    timestamp: str
    price_momentum: float
    volume_factor: float
    time_factor: float
    equilibrium: float
    imbalance: float
    fusion_score: float
    fusion_score_signed: float
    reflective_confidence: float
    bias: str
    state: str
    momentum_band: str
    status: str = "ok"

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DivergenceSignal:
    """A single divergence signal."""

    indicator: str
    divergence_type: DivergenceType
    strength: DivergenceStrength
    price_start: float
    price_end: float
    indicator_start: float
    indicator_end: float
    bars_apart: int
    confidence: float


@dataclass
class MultiDivergenceResult:
    """Result of multi-indicator divergence analysis."""

    timestamp: datetime
    pair: str
    timeframe: str
    rsi_divergence: DivergenceSignal | None
    macd_divergence: DivergenceSignal | None
    cci_divergence: DivergenceSignal | None
    mfi_divergence: DivergenceSignal | None
    confluence_count: int
    overall_signal: DivergenceType
    overall_strength: DivergenceStrength
    confidence: float


@dataclass
class AdaptiveUpdate:
    """Result from adaptive threshold update."""

    timestamp: str
    meta_drift: float
    integrity_index: float
    mean_energy: float
    freeze_thresholds: bool
    reason: str
    proposed: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConfidenceLineage:
    """Tracks confidence calculation lineage."""

    raw: float
    weighted: float
    final: float
    precision_weight: float
    gate_threshold: float
    gate_pass: bool
    authority: str
    notes: str
    lambda_esi: float = 0.06
    field_state: str | None = None
    field_integrity: float | None = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MonteCarloResult:
    """Result from Monte Carlo confidence simulation."""

    conf12_raw: float
    reliability_score: float
    stability_index: float
    total_simulations: int
    bias_mean: float
    volatility_mean: float
    reflective_integrity: float
    timestamp: str

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FTTCConfig:
    """Configuration for FTTC Monte Carlo Engine."""

    iterations: int = DEFAULT_FTTC_ITERATIONS
    horizon_days: int = DEFAULT_FTTC_HORIZON_DAYS
    confidence_threshold: float = DEFAULT_FTTC_CONFIDENCE
    min_frpc: float = 0.96
    min_tii: float = 0.92
    target_drift: float = 0.004
    alpha: float = 0.45
    beta: float = 0.35
    gamma: float = 0.20


@dataclass
class FTTCResult:
    """Result container for FTTC simulation."""

    win_probability: float
    expected_return: float
    max_drawdown_probability: float
    optimal_position_size: float
    confidence_interval: Tuple[float, float]
    transition_probabilities: Dict[str, float]
    escape_rates: Dict[str, float]
    meta_drift: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QMatrixConfig:
    """Configuration for Q-Matrix generation."""

    base_transition_rate: float = 0.1
    volatility_sensitivity: float = 0.5
    trend_sensitivity: float = 0.3
    momentum_sensitivity: float = 0.2
    regularization: float = 0.01


@dataclass
class LiquidityZone:
    """Represents a liquidity zone."""

    zone_type: LiquidityType
    status: LiquidityStatus
    price_level: float
    price_range: Tuple[float, float]
    strength: float
    touch_count: int
    created_at: datetime
    last_tested: datetime | None
    timeframe: str


@dataclass
class LiquidityMapResult:
    """Result of liquidity zone mapping."""

    timestamp: datetime
    pair: str
    buy_side_zones: List[LiquidityZone]
    sell_side_zones: List[LiquidityZone]
    nearest_buy_liquidity: float | None
    nearest_sell_liquidity: float | None
    liquidity_imbalance: float


@dataclass
class CoherenceAudit:
    """Result from coherence audit."""

    timestamp: str
    lookback: int
    reflective_coherence: float
    divergence_window: bool
    divergence_alert: str
    stability_state: str
    gate_threshold: float
    gate_pass: bool

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# 🔄 SECTION 6: FIELD SYNC
# =============================================================================


def resolve_field_context(
    pair: str = "XAUUSD",
    timeframe: str = "H4",
    field_state: str | None = None,
    alpha: float = 1.0,
    beta: float = 1.0,
    gamma: float = 1.0,
    lambda_esi: float = 0.06,
    field_override: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Resolve field context for fusion analysis.

    Args:
        pair: Trading pair symbol
        timeframe: Analysis timeframe
        field_state: Optional field state override
        alpha: Alpha coefficient
        beta: Beta coefficient
        gamma: Gamma coefficient
        lambda_esi: ESI lambda parameter
        field_override: Optional complete override

    Returns:
        Dict with field context data
    """
    if field_override:
        context = dict(field_override)
        context.setdefault("pair", pair)
        context.setdefault("timeframe", timeframe)
        context.setdefault("lambda_esi", lambda_esi)
        return context

    # Calculate field integrity from coefficients
    field_integrity = _clamp01((alpha + beta + gamma) / 3.0)

    return {
        "pair": pair,
        "timeframe": timeframe,
        "field_state": field_state or "neutral",
        "coherence": 0.95,
        "resonance": 0.88,
        "phase": "stable",
        "alpha": alpha,
        "beta": beta,
        "gamma": gamma,
        "lambda_esi": lambda_esi,
        "field_integrity": round(field_integrity, 4),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def sync_field_state(
    source_state: Dict[str, Any],
    target_state: Dict[str, Any],
) -> Dict[str, Any]:
    """Synchronize field states between layers.

    Args:
        source_state: Source field state
        target_state: Target field state

    Returns:
        Merged synchronized state
    """
    merged = {**target_state, **source_state}
    merged["sync_timestamp"] = datetime.now(UTC).isoformat()
    return merged


# =============================================================================
# 📈 SECTION 7: EMA FUSION ENGINE
# =============================================================================


class EMAFusionEngine:
    """Engine for computing EMA-based fusion signals."""

    def __init__(
        self,
        periods: List[int] | None = None,
        smoothing: float = 2.0,
    ) -> None:
        """Initialize EMA Fusion Engine.

        Args:
            periods: EMA periods to compute (default: [21, 55, 100])
            smoothing: EMA smoothing factor
        """
        self.periods = sorted(set(periods or [21, 55, 100]))
        if not self.periods:
            self.periods = [21, 55, 100]
        self.smoothing = smoothing
        self._cache: Dict[str, Any] = {}

    def compute(self, prices: List[float]) -> Dict[str, Any]:
        """Compute EMA fusion from price series.

        Args:
            prices: List of price values

        Returns:
            Dict with EMA values and fusion metrics
        """
        if not prices or len(prices) < max(self.periods):
            return self._empty_result()

        emas = {}
        for period in self.periods:
            emas[f"ema{period}"] = self._calculate_ema(prices, period)

        direction = self._determine_direction(emas)
        strength = self._calculate_strength(emas, prices[-1])

        return {
            **emas,
            "direction": direction,
            "fusion_strength": strength,
            "price": prices[-1],
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate EMA for given period."""
        if len(prices) < period:
            return prices[-1] if prices else 0.0

        multiplier = self.smoothing / (period + 1)
        ema = sum(prices[:period]) / period

        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))

        return round(ema, 5)

    def _determine_direction(self, emas: Dict[str, float]) -> str:
        """Determine trend direction from EMA alignment."""
        values = [emas.get(f"ema{p}", 0.0) for p in self.periods]
        if len(values) < 2:
            return "NEUTRAL"

        if all(values[i] >= values[i + 1] for i in range(len(values) - 1)):
            return "BULL"
        if all(values[i] <= values[i + 1] for i in range(len(values) - 1)):
            return "BEAR"
        return "NEUTRAL"

    def _calculate_strength(self, emas: Dict[str, float], current_price: float) -> float:
        """Calculate fusion strength based on EMA deviation."""
        if not emas:
            return 0.5

        avg_ema = sum(emas.values()) / len(emas)
        if avg_ema == 0:
            return 0.5

        deviation = abs(current_price - avg_ema) / avg_ema
        strength = min(1.0, 0.5 + deviation * 10)
        return round(strength, 3)

    def _empty_result(self) -> Dict[str, Any]:
        """Return empty result when computation not possible."""
        result: Dict[str, Any] = {f"ema{p}": 0.0 for p in self.periods}
        result.update(
            {
                "direction": "NEUTRAL",
                "fusion_strength": 0.5,
                "price": 0.0,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        return result


# =============================================================================
# 📊 SECTION 8: FUSION METRICS ANALYZER
# =============================================================================


def evaluate_fusion_metrics(
    fusion_data: Dict[str, Any],
    threshold: float = 0.75,
) -> Dict[str, Any]:
    """Evaluate fusion metrics and return analysis.

    Args:
        fusion_data: Raw fusion data from engine
        threshold: Confidence threshold for signals

    Returns:
        Dict with evaluated metrics and recommendations
    """
    confidence = fusion_data.get("fusion_strength", 0.5)
    direction = fusion_data.get("direction", "NEUTRAL")

    signal_valid = confidence >= threshold and direction != "NEUTRAL"
    score = _calculate_composite_score(fusion_data)

    if signal_valid and score >= 0.8:
        action = FusionAction.EXECUTE.value
    elif signal_valid and score >= 0.6:
        action = FusionAction.MONITOR.value
    else:
        action = FusionAction.WAIT.value

    return {
        "confidence": confidence,
        "direction": direction,
        "signal_valid": signal_valid,
        "composite_score": score,
        "action": action,
        "threshold": threshold,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _calculate_composite_score(fusion_data: Dict[str, Any]) -> float:
    """Calculate composite fusion score."""
    weights = {
        "fusion_strength": 0.4,
        "coherence": 0.3,
        "resonance": 0.2,
        "integrity": 0.1,
    }

    score = 0.0
    for key, weight in weights.items():
        value = fusion_data.get(key, 0.5)
        score += _safe_float(value, 0.5) * weight

    return round(_clamp01(score), 3)


def aggregate_multi_timeframe_metrics(
    metrics_list: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Aggregate metrics from multiple timeframes.

    Args:
        metrics_list: List of metrics from different timeframes

    Returns:
        Aggregated metrics
    """
    if not metrics_list:
        return {
            "aggregated_score": 0.5,
            "consensus_direction": "NEUTRAL",
            "timeframes_analyzed": 0,
        }

    scores = [m.get("composite_score", 0.5) for m in metrics_list]
    directions = [m.get("direction", "NEUTRAL") for m in metrics_list]

    direction_counts: Dict[str, int] = {}
    for d in directions:
        direction_counts[d] = direction_counts.get(d, 0) + 1

    consensus = max(direction_counts.keys(), key=lambda k: direction_counts[k])
    consensus_strength = direction_counts[consensus] / len(directions)

    return {
        "aggregated_score": round(sum(scores) / len(scores), 3),
        "consensus_direction": consensus,
        "consensus_strength": round(consensus_strength, 2),
        "timeframes_analyzed": len(metrics_list),
        "timestamp": datetime.now(UTC).isoformat(),
    }


# =============================================================================
# 🎯 SECTION 9: FUSION PRECISION ENGINE
# =============================================================================


class FusionPrecisionEngine:
    """Main precision engine combining EMA, VWAP, reflex factors."""

    def __init__(
        self,
        ema_fast: int = DEFAULT_EMA_FAST,
        ema_slow: int = DEFAULT_EMA_SLOW,
    ) -> None:
        """Initialize Fusion Precision Engine.

        Args:
            ema_fast: Fast EMA period
            ema_slow: Slow EMA period
        """
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow

    def compute_precision(  # noqa: PLR0913
        self,
        *,
        price: float,
        ema_fast_val: float,
        ema_slow_val: float,
        vwap: float,
        atr: float,
        reflex_strength: float,
        volatility: float,
        rsi: float,
        symbol: str | None = None,
        pair: str | None = None,
        trade_id: str | None = None,
    ) -> FusionPrecisionResult:
        """Compute precision strength and map into precision_weight.

        Args:
            price: Current price
            ema_fast_val: Fast EMA value
            ema_slow_val: Slow EMA value
            vwap: VWAP value
            atr: ATR value
            reflex_strength: Reflex strength factor
            volatility: Volatility measure
            rsi: RSI value
            symbol: Optional symbol
            pair: Optional pair
            trade_id: Optional trade ID

        Returns:
            FusionPrecisionResult with precision metrics
        """
        timestamp = datetime.now(UTC).isoformat()

        if not _inputs_valid(
            price, ema_fast_val, ema_slow_val, vwap, atr, reflex_strength, volatility, rsi
        ):
            return FusionPrecisionResult(
                timestamp=timestamp,
                fusion_strength=0.0,
                bias_mode="NEUTRAL",
                precision_weight=1.0,
                precision_confidence_hint=0.0,
                details={"status": "invalid_input"},
                symbol=symbol,
                pair=pair,
                trade_id=trade_id,
            )

        if atr <= 0:
            return FusionPrecisionResult(
                timestamp=timestamp,
                fusion_strength=0.0,
                bias_mode="NEUTRAL",
                precision_weight=1.0,
                precision_confidence_hint=0.0,
                details={"status": "invalid_atr"},
                symbol=symbol,
                pair=pair,
                trade_id=trade_id,
            )

        # Calculate EMA strength
        ema_diff = ema_fast_val - ema_slow_val
        ema_ratio = ema_diff / (ema_slow_val + 1e-6)
        ema_strength = math.tanh(ema_ratio * 5.0)

        # Calculate VWAP signal
        vwap_dev = (price - vwap) / (atr + 1e-6)
        vwap_signal = math.tanh(vwap_dev * 0.8)

        # Reflex weight
        reflex_weight = _clamp(reflex_strength, 0.0, 1.0)

        # Volatility adjustment
        volatility_adj = _clamp(1.0 - (volatility / (atr * 2.5)), 0.4, 1.0)

        # Fusion calculation
        fusion_raw = (ema_strength * 0.45) + (vwap_signal * 0.35) + (reflex_weight * 0.2)
        fusion_strength = float(fusion_raw * volatility_adj)

        # Determine bias mode
        if fusion_strength > 0.25:
            bias_mode = FusionBiasMode.BULLISH.value
        elif fusion_strength < -0.25:
            bias_mode = FusionBiasMode.BEARISH.value
        else:
            bias_mode = FusionBiasMode.NEUTRAL.value

        # Confidence hint (conservative)
        hint = _clamp(abs(fusion_strength) * 0.85, 0.0, 1.0)

        # RSI bonus
        rsi_bonus = 0.0
        if (rsi >= 65 and fusion_strength > 0) or (rsi <= 35 and fusion_strength < 0):
            rsi_bonus = 0.10

        # Precision weight calculation
        base_w = 1.0 + (_clamp(abs(fusion_strength), 0.0, 1.0) - 0.35) * 0.45 + rsi_bonus
        precision_weight = _clamp(
            base_w, DEFAULT_PRECISION_WEIGHT_MIN, DEFAULT_PRECISION_WEIGHT_MAX
        )

        return FusionPrecisionResult(
            timestamp=timestamp,
            fusion_strength=round(fusion_strength, 6),
            bias_mode=bias_mode,
            precision_weight=round(float(precision_weight), 4),
            precision_confidence_hint=round(float(hint), 4),
            details={
                "ema_strength": round(float(ema_strength), 6),
                "vwap_signal": round(float(vwap_signal), 6),
                "reflex_strength": round(float(reflex_weight), 6),
                "volatility_adj": round(float(volatility_adj), 6),
                "rsi": float(rsi),
            },
            symbol=symbol,
            pair=pair,
            trade_id=trade_id,
        )


def calculate_fusion_precision(market_data: Dict[str, Any]) -> Dict[str, Any]:
    """Backward-compatible wrapper for fusion precision calculation.

    Args:
        market_data: Market data dictionary

    Returns:
        Dict with precision metrics
    """
    engine = FusionPrecisionEngine()
    res = engine.compute_precision(
        price=_safe_float(market_data.get("price", 0.0)),
        ema_fast_val=_safe_float(
            market_data.get("ema_fast_val", market_data.get("ema_fast", 0.0))
        ),
        ema_slow_val=_safe_float(
            market_data.get("ema_slow_val", market_data.get("ema_slow", 0.0))
        ),
        vwap=_safe_float(market_data.get("vwap", 0.0)),
        atr=_safe_float(market_data.get("atr", 0.0)),
        reflex_strength=_safe_float(market_data.get("reflex_strength", 0.0)),
        volatility=_safe_float(market_data.get("volatility", 0.0)),
        rsi=_safe_float(market_data.get("rsi", 50.0)),
        symbol=market_data.get("symbol"),
        pair=market_data.get("pair"),
        trade_id=market_data.get("trade_id"),
    )
    payload = res.as_dict()
    bias_map = {"BULLISH": "Bullish", "BEARISH": "Bearish", "NEUTRAL": "Neutral"}
    payload["bias"] = bias_map.get(payload.get("bias_mode", ""), "Neutral")
    payload["CONF12"] = max(
        0.95, min(1.0, float(payload.get("precision_weight", 1.0)) * 0.98)
    )
    return payload


# =============================================================================
# ⚖️ SECTION 10: EQUILIBRIUM MOMENTUM FUSION
# =============================================================================


def equilibrium_momentum_fusion_v6(  # noqa: PLR0913
    price_change: float,
    volume_change: float,
    time_weight: float,
    atr: float,
    trq_energy: float = 1.0,
    reflective_intensity: float = 1.0,
    alpha: float = 1.0,
    beta: float = 1.0,
    gamma: float = 1.0,
    integrity_index: float = 0.97,
    direction_hint: float = 1.0,
    symbol: str | None = None,
    pair: str | None = None,
    trade_id: str | None = None,
    lambda_esi: float = 0.06,
    field_override: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Calculate reflective equilibrium momentum across dimensions.

    Args:
        price_change: Price change value
        volume_change: Volume change value
        time_weight: Time weight factor
        atr: ATR value
        trq_energy: TRQ energy factor
        reflective_intensity: Reflective intensity
        alpha: Alpha coefficient
        beta: Beta coefficient
        gamma: Gamma coefficient
        integrity_index: Integrity index
        direction_hint: Direction hint (-1 to 1)
        symbol: Optional symbol
        pair: Optional pair
        trade_id: Optional trade ID
        lambda_esi: ESI lambda parameter
        field_override: Optional field override

    Returns:
        Dict with equilibrium momentum results
    """
    values = [price_change, volume_change, time_weight, atr]
    meta_values = [
        trq_energy,
        reflective_intensity,
        alpha,
        beta,
        gamma,
        integrity_index,
        direction_hint,
    ]

    if price_change == 0 or atr <= 0 or volume_change <= 0 or time_weight <= 0:
        return {"status": "invalid_input"}
    if not (
        all(math.isfinite(x) for x in values)
        and all(math.isfinite(x) for x in meta_values)
    ):
        return {"status": "invalid_input"}

    # Clamp inputs
    direction_hint = _clamp(direction_hint, -1.0, 1.0)
    trq_energy = _clamp(trq_energy, 0.1, 10.0)
    reflective_intensity = _clamp(reflective_intensity, 0.1, 10.0)
    alpha = _clamp(alpha, 0.5, 2.0)
    beta = _clamp(beta, 0.5, 2.0)
    gamma = _clamp(gamma, 0.5, 2.0)
    integrity_index = _clamp01(integrity_index)

    # Calculate momentum factors
    price_momentum = abs(price_change / atr)
    volume_factor = math.log1p(abs(volume_change))
    time_factor = math.log1p(abs(time_weight))

    equilibrium = (price_momentum + volume_factor + time_factor) / 3
    imbalance = abs(price_momentum - volume_factor) + abs(volume_factor - time_factor)

    trq_sync = trq_energy * reflective_intensity
    alpha_sync = (alpha + beta + gamma) / 3

    fusion_score = (
        (equilibrium / (1 + imbalance)) * trq_sync * alpha_sync * integrity_index
    )
    signed_score = fusion_score * math.copysign(1.0, direction_hint)

    # Determine bias
    if signed_score >= 1.25:
        bias = "Bullish Reflective Phase"
        state = FusionState.STRONG_BULLISH.value
    elif signed_score >= 0.75:
        bias = "Bullish Phase"
        state = FusionState.BULLISH.value
    elif signed_score <= -1.25:
        bias = "Bearish Reflective Phase"
        state = FusionState.STRONG_BEARISH.value
    elif signed_score <= -0.75:
        bias = "Bearish Phase"
        state = FusionState.BEARISH.value
    else:
        bias = "Neutral Reflective Phase"
        state = FusionState.NEUTRAL.value

    confidence = _clamp01(abs(signed_score) / 1.5)

    # Determine momentum band
    magnitude = abs(signed_score)
    if magnitude >= 1.75:
        momentum_band = MomentumBand.HYPER.value
    elif magnitude >= 1.25:
        momentum_band = MomentumBand.STRONG.value
    elif magnitude >= 0.75:
        momentum_band = MomentumBand.BALANCED.value
    else:
        momentum_band = MomentumBand.CALM.value

    field_context = resolve_field_context(
        pair=pair or "XAUUSD",
        timeframe="H4",
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        lambda_esi=lambda_esi,
        field_override=field_override,
    )

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "price_momentum": round(price_momentum, 3),
        "volume_factor": round(volume_factor, 3),
        "time_factor": round(time_factor, 3),
        "equilibrium": round(equilibrium, 3),
        "imbalance": round(imbalance, 3),
        "fusion_score": round(fusion_score, 3),
        "fusion_score_signed": round(signed_score, 3),
        "reflective_confidence": round(confidence, 3),
        "bias": bias,
        "state": state,
        "equilibrium_state": state,
        "momentum_band": momentum_band,
        "trq_energy": round(trq_energy, 3),
        "reflective_intensity": round(reflective_intensity, 3),
        "alpha": round(alpha, 3),
        "beta": round(beta, 3),
        "gamma": round(gamma, 3),
        "integrity_index": round(integrity_index, 3),
        "lambda_esi": field_context.get("lambda_esi"),
        "field_state": field_context.get("field_state"),
        "field_integrity": field_context.get("field_integrity"),
        "status": "ok",
        "symbol": symbol,
        "pair": pair,
        "trade_id": trade_id,
    }


def equilibrium_momentum_fusion(  # noqa: PLR0913
    vwap_val: float,
    ema_fusion_data: Mapping[str, Any],
    reflex_strength: float,
    trq_energy: float = 1.0,
    reflective_intensity: float = 1.0,
    alpha: float = 1.0,
    beta: float = 1.0,
    gamma: float = 1.0,
    integrity_index: float = 0.97,
    symbol: str | None = None,
    pair: str | None = None,
    trade_id: str | None = None,
    lambda_esi: float = 0.06,
    field_override: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """High-level equilibrium fusion for Ultra Fusion pipeline.

    Args:
        vwap_val: Current VWAP value
        ema_fusion_data: Dict with ema50, fusion_strength, cross_state
        reflex_strength: Reflex coherence
        trq_energy: TRQ energy
        reflective_intensity: Reflective intensity
        alpha: Alpha coefficient
        beta: Beta coefficient
        gamma: Gamma coefficient
        integrity_index: Integrity index
        symbol: Optional symbol
        pair: Optional pair
        trade_id: Optional trade ID
        lambda_esi: ESI lambda
        field_override: Optional field override

    Returns:
        Enriched equilibrium fusion result
    """
    ema50 = _safe_float(ema_fusion_data.get("ema50", 0.0))
    fusion_strength = _safe_float(ema_fusion_data.get("fusion_strength", 0.0))
    cross_state = str(ema_fusion_data.get("cross_state", "neutral")).lower()

    if not math.isfinite(vwap_val):
        return {"status": "invalid input"}

    price_change = vwap_val - ema50
    direction_hint = (
        1.0 if cross_state == "bullish" else -1.0 if cross_state == "bearish" else 0.0
    )
    direction_hint = direction_hint or math.copysign(1.0, price_change or 1.0)

    # Estimate ATR proxy
    base_scale = max(abs(vwap_val), abs(ema50), 1e-6)
    deviation = abs(vwap_val - ema50)
    atr_proxy = max(deviation * 1.25, base_scale * 0.0008, 1e-6)

    fusion_output = equilibrium_momentum_fusion_v6(
        price_change=price_change,
        volume_change=max(0.01, fusion_strength),
        time_weight=max(0.01, abs(reflex_strength)),
        atr=atr_proxy,
        trq_energy=trq_energy,
        reflective_intensity=reflective_intensity,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        integrity_index=integrity_index,
        direction_hint=direction_hint,
        symbol=symbol,
        pair=pair,
        trade_id=trade_id,
        lambda_esi=lambda_esi,
        field_override=field_override,
    )

    if fusion_output.get("status") == "invalid_input":
        return fusion_output

    fusion_output.update(
        {
            "vwap": round(vwap_val, 6),
            "ema50": round(ema50, 6),
            "fusion_strength_input": round(fusion_strength, 4),
            "reflex_strength": round(reflex_strength, 4),
            "cross_state": cross_state,
            "atr_proxy": round(atr_proxy, 6),
        }
    )

    return fusion_output


# =============================================================================
# 📊 SECTION 11: MULTI-INDICATOR DIVERGENCE DETECTOR
# =============================================================================


class MultiIndicatorDivergenceDetector:
    """Detects divergences across multiple indicators for high-probability signals.

    Supported indicators:
    - RSI (Relative Strength Index)
    - MACD (Moving Average Convergence Divergence)
    - CCI (Commodity Channel Index)
    - MFI (Money Flow Index)
    """

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """Initialize Multi-Indicator Divergence Detector.

        Args:
            config: Configuration parameters
        """
        self.config = config or self._default_config()

    def _default_config(self) -> Dict[str, Any]:
        """Return default configuration."""
        return {
            "rsi_period": 14,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "cci_period": 20,
            "mfi_period": 14,
            "lookback_bars": DEFAULT_LOOKBACK_BARS,
            "min_bars_apart": DEFAULT_MIN_BARS_APART,
            "max_bars_apart": DEFAULT_MAX_BARS_APART,
            "price_tolerance": 0.001,
            "min_confluence": DEFAULT_MIN_CONFLUENCE,
        }

    def analyze(
        self,
        ohlcv_data: List[Dict[str, Any]],
        pair: str,
        timeframe: str,
        indicators: Dict[str, List[float]] | None = None,
    ) -> MultiDivergenceResult:
        """Analyze for divergences across all indicators.

        Args:
            ohlcv_data: List of OHLCV candles
            pair: Trading pair
            timeframe: Timeframe of analysis
            indicators: Pre-calculated indicator values (optional)

        Returns:
            MultiDivergenceResult
        """
        timestamp = datetime.now(UTC)

        if indicators is None:
            indicators = self._calculate_indicators(ohlcv_data)

        highs = [c.get("high", 0) for c in ohlcv_data]
        lows = [c.get("low", 0) for c in ohlcv_data]
        closes = [c.get("close", 0) for c in ohlcv_data]

        rsi_div = self._detect_divergence(
            highs, lows, closes, indicators.get("rsi", []), "RSI"
        )
        macd_div = self._detect_divergence(
            highs, lows, closes, indicators.get("macd_histogram", []), "MACD"
        )
        cci_div = self._detect_divergence(
            highs, lows, closes, indicators.get("cci", []), "CCI"
        )
        mfi_div = self._detect_divergence(
            highs, lows, closes, indicators.get("mfi", []), "MFI"
        )

        divergences = [rsi_div, macd_div, cci_div, mfi_div]
        valid_divergences = [d for d in divergences if d is not None]
        confluence_count = len(valid_divergences)

        overall_signal, overall_strength = self._determine_overall_signal(
            valid_divergences
        )
        confidence = self._calculate_confidence(valid_divergences, confluence_count)

        return MultiDivergenceResult(
            timestamp=timestamp,
            pair=pair,
            timeframe=timeframe,
            rsi_divergence=rsi_div,
            macd_divergence=macd_div,
            cci_divergence=cci_div,
            mfi_divergence=mfi_div,
            confluence_count=confluence_count,
            overall_signal=overall_signal,
            overall_strength=overall_strength,
            confidence=confidence,
        )

    def _calculate_indicators(
        self, ohlcv_data: List[Dict[str, Any]]
    ) -> Dict[str, List[float]]:
        """Calculate all required indicators from raw OHLCV data.

        Implements:
        - RSI (14-period Wilder smoothing)
        - MACD histogram (12/26/9)
        - CCI (20-period)
        - MFI (14-period)
        """
        if len(ohlcv_data) < 30:
            return {"rsi": [], "macd_histogram": [], "cci": [], "mfi": []}

        closes = [c.get("close", 0.0) for c in ohlcv_data]
        highs = [c.get("high", 0.0) for c in ohlcv_data]
        lows = [c.get("low", 0.0) for c in ohlcv_data]
        volumes = [c.get("volume", 1.0) for c in ohlcv_data]

        # RSI-14 (Wilder smoothing)
        rsi_period = self.config.get("rsi_period", 14)
        rsi_values = self._calc_rsi(closes, rsi_period)

        # MACD histogram
        fast = self.config.get("macd_fast", 12)
        slow = self.config.get("macd_slow", 26)
        sig = self.config.get("macd_signal", 9)
        macd_hist = self._calc_macd_histogram(closes, fast, slow, sig)

        # CCI-20
        cci_period = self.config.get("cci_period", 20)
        cci_values = self._calc_cci(highs, lows, closes, cci_period)

        # MFI-14
        mfi_period = self.config.get("mfi_period", 14)
        mfi_values = self._calc_mfi(highs, lows, closes, volumes, mfi_period)

        return {
            "rsi": rsi_values,
            "macd_histogram": macd_hist,
            "cci": cci_values,
            "mfi": mfi_values,
        }

    @staticmethod
    def _calc_rsi(closes: List[float], period: int) -> List[float]:
        """Calculate RSI using Wilder smoothing."""
        if len(closes) < period + 1:
            return []
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(0, d) for d in deltas]
        losses = [max(0, -d) for d in deltas]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        rsi_list: List[float] = []

        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0:
                rsi_list.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_list.append(100.0 - (100.0 / (1.0 + rs)))
        # Pad front so length matches closes
        pad = [50.0] * (len(closes) - len(rsi_list))
        return pad + rsi_list

    @staticmethod
    def _calc_ema(values: List[float], period: int) -> List[float]:
        """Calculate Exponential Moving Average."""
        if len(values) < period:
            return values[:]
        k = 2.0 / (period + 1)
        ema = [sum(values[:period]) / period]
        for v in values[period:]:
            ema.append(v * k + ema[-1] * (1 - k))
        pad = values[:period - 1] if period > 1 else []
        return pad + ema

    def _calc_macd_histogram(
        self, closes: List[float], fast: int, slow: int, signal: int
    ) -> List[float]:
        """Calculate MACD histogram (MACD line - signal line)."""
        if len(closes) < slow + signal:
            return []
        ema_fast = self._calc_ema(closes, fast)
        ema_slow = self._calc_ema(closes, slow)
        macd_line = [f - s for f, s in zip(ema_fast, ema_slow, strict=False)]
        signal_line = self._calc_ema(macd_line, signal)
        histogram = [m - s for m, s in zip(macd_line, signal_line, strict=False)]
        # Pad to match length
        pad = [0.0] * (len(closes) - len(histogram))
        return pad + histogram

    @staticmethod
    def _calc_cci(
        highs: List[float], lows: List[float], closes: List[float], period: int
    ) -> List[float]:
        """Calculate Commodity Channel Index."""
        if len(closes) < period:
            return []
        typical = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes, strict=False)]  # noqa: E741
        cci_values: List[float] = []
        for i in range(period - 1, len(typical)):
            window = typical[i - period + 1: i + 1]
            sma = sum(window) / period
            mean_dev = sum(abs(v - sma) for v in window) / period
            if mean_dev == 0:
                cci_values.append(0.0)
            else:
                cci_values.append((typical[i] - sma) / (0.015 * mean_dev))
        pad = [0.0] * (len(closes) - len(cci_values))
        return pad + cci_values

    @staticmethod
    def _calc_mfi(
        highs: List[float], lows: List[float], closes: List[float],
        volumes: List[float], period: int,
    ) -> List[float]:
        """Calculate Money Flow Index."""
        if len(closes) < period + 1:
            return []
        typical = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes, strict=False)]  # noqa: E741
        mfi_values: List[float] = []
        for i in range(period, len(typical)):
            pos_flow = 0.0
            neg_flow = 0.0
            for j in range(i - period + 1, i + 1):
                raw_mf = typical[j] * volumes[j]
                if typical[j] > typical[j - 1]:
                    pos_flow += raw_mf
                else:
                    neg_flow += raw_mf
            if neg_flow == 0:
                mfi_values.append(100.0)
            else:
                mr = pos_flow / neg_flow
                mfi_values.append(100.0 - (100.0 / (1.0 + mr)))
        pad = [50.0] * (len(closes) - len(mfi_values))
        return pad + mfi_values

    def _detect_divergence(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        indicator_values: List[float],
        indicator_name: str,
    ) -> DivergenceSignal | None:
        """Detect divergence between price and indicator."""
        if len(indicator_values) < self.config["lookback_bars"]:
            return None

        min_bars = self.config["min_bars_apart"]
        max_bars = self.config["max_bars_apart"]
        lookback = self.config["lookback_bars"]

        price_highs = self._find_swing_points(highs, lookback, "high")
        price_lows = self._find_swing_points(lows, lookback, "low")
        ind_highs = self._find_swing_points(indicator_values, lookback, "high")
        ind_lows = self._find_swing_points(indicator_values, lookback, "low")

        bullish_div = self._check_regular_bullish(
            price_lows, ind_lows, lows, indicator_values, min_bars, max_bars
        )
        if bullish_div:
            return DivergenceSignal(
                indicator=indicator_name,
                divergence_type=DivergenceType.REGULAR_BULLISH,
                strength=self._calculate_divergence_strength(bullish_div),
                price_start=bullish_div["price_start"],
                price_end=bullish_div["price_end"],
                indicator_start=bullish_div["ind_start"],
                indicator_end=bullish_div["ind_end"],
                bars_apart=bullish_div["bars"],
                confidence=bullish_div.get("confidence", 0.7),
            )

        bearish_div = self._check_regular_bearish(
            price_highs, ind_highs, highs, indicator_values, min_bars, max_bars
        )
        if bearish_div:
            return DivergenceSignal(
                indicator=indicator_name,
                divergence_type=DivergenceType.REGULAR_BEARISH,
                strength=self._calculate_divergence_strength(bearish_div),
                price_start=bearish_div["price_start"],
                price_end=bearish_div["price_end"],
                indicator_start=bearish_div["ind_start"],
                indicator_end=bearish_div["ind_end"],
                bars_apart=bearish_div["bars"],
                confidence=bearish_div.get("confidence", 0.7),
            )

        return None

    def _find_swing_points(
        self, values: List[float], lookback: int, point_type: str
    ) -> List[Tuple[int, float]]:
        """Find swing high or low points."""
        swings = []
        window = 5

        for i in range(window, len(values) - window):
            is_swing = True
            current = values[i]

            for j in range(i - window, i + window + 1):
                if j != i:
                    if point_type == "high" and values[j] > current:
                        is_swing = False
                        break
                    if point_type == "low" and values[j] < current:
                        is_swing = False
                        break

            if is_swing:
                swings.append((i, current))

        return swings

    def _check_regular_bullish(
        self,
        price_lows: List[Tuple[int, float]],
        ind_lows: List[Tuple[int, float]],
        lows: List[float],
        indicator_values: List[float],
        min_bars: int,
        max_bars: int,
    ) -> Dict[str, Any] | None:
        """Check for regular bullish divergence."""
        if len(price_lows) < 2 or len(ind_lows) < 2:
            return None

        for i in range(len(price_lows) - 1, 0, -1):
            for j in range(i - 1, -1, -1):
                idx1, price1 = price_lows[j]
                idx2, price2 = price_lows[i]

                bars_apart = idx2 - idx1
                if not (min_bars <= bars_apart <= max_bars):
                    continue

                if price2 >= price1:
                    continue

                if idx1 < len(indicator_values) and idx2 < len(indicator_values):
                    ind1 = indicator_values[idx1]
                    ind2 = indicator_values[idx2]

                    if ind2 > ind1:
                        return {
                            "price_start": price1,
                            "price_end": price2,
                            "ind_start": ind1,
                            "ind_end": ind2,
                            "bars": bars_apart,
                            "confidence": 0.75,
                        }

        return None

    def _check_regular_bearish(
        self,
        price_highs: List[Tuple[int, float]],
        ind_highs: List[Tuple[int, float]],
        highs: List[float],
        indicator_values: List[float],
        min_bars: int,
        max_bars: int,
    ) -> Dict[str, Any] | None:
        """Check for regular bearish divergence."""
        if len(price_highs) < 2 or len(ind_highs) < 2:
            return None

        for i in range(len(price_highs) - 1, 0, -1):
            for j in range(i - 1, -1, -1):
                idx1, price1 = price_highs[j]
                idx2, price2 = price_highs[i]

                bars_apart = idx2 - idx1
                if not (min_bars <= bars_apart <= max_bars):
                    continue

                if price2 <= price1:
                    continue

                if idx1 < len(indicator_values) and idx2 < len(indicator_values):
                    ind1 = indicator_values[idx1]
                    ind2 = indicator_values[idx2]

                    if ind2 < ind1:
                        return {
                            "price_start": price1,
                            "price_end": price2,
                            "ind_start": ind1,
                            "ind_end": ind2,
                            "bars": bars_apart,
                            "confidence": 0.75,
                        }

        return None

    def _calculate_divergence_strength(
        self, divergence_data: Dict[str, Any]
    ) -> DivergenceStrength:
        """Calculate strength of divergence."""
        bars = divergence_data["bars"]

        if bars > 20:
            return DivergenceStrength.STRONG
        if bars > 10:
            return DivergenceStrength.MODERATE
        return DivergenceStrength.WEAK

    def _determine_overall_signal(
        self, divergences: List[DivergenceSignal]
    ) -> Tuple[DivergenceType, DivergenceStrength]:
        """Determine overall signal from multiple divergences."""
        if not divergences:
            return DivergenceType.NONE, DivergenceStrength.WEAK

        bullish_count = sum(
            1
            for d in divergences
            if d.divergence_type
            in [DivergenceType.REGULAR_BULLISH, DivergenceType.HIDDEN_BULLISH]
        )
        bearish_count = sum(
            1
            for d in divergences
            if d.divergence_type
            in [DivergenceType.REGULAR_BEARISH, DivergenceType.HIDDEN_BEARISH]
        )

        if bullish_count > bearish_count:
            signal_type = DivergenceType.REGULAR_BULLISH
        elif bearish_count > bullish_count:
            signal_type = DivergenceType.REGULAR_BEARISH
        else:
            signal_type = DivergenceType.NONE

        if len(divergences) >= 3:
            strength = DivergenceStrength.STRONG
        elif len(divergences) >= 2:
            strength = DivergenceStrength.MODERATE
        else:
            strength = DivergenceStrength.WEAK

        return signal_type, strength

    def _calculate_confidence(
        self, divergences: List[DivergenceSignal], confluence_count: int
    ) -> float:
        """Calculate overall confidence."""
        if confluence_count == 0:
            return 0.0

        confidence = 0.5 + (confluence_count * 0.15)
        strong_count = sum(
            1 for d in divergences if d.strength == DivergenceStrength.STRONG
        )
        confidence += strong_count * 0.05

        return min(1.0, confidence)


# =============================================================================
# ⚙️ SECTION 12: ADAPTIVE THRESHOLD CONTROLLER
# =============================================================================


class AdaptiveThresholdController:
    """Adaptive Threshold Controller for dynamic threshold management.

    Freezes adaptive thresholds when meta_drift (|gradient|) > 0.006.
    """

    VERSION = "6.0"

    def __init__(
        self,
        *,
        meta_drift_freeze: float = DEFAULT_META_DRIFT_FREEZE,
        min_integrity: float = DEFAULT_MIN_INTEGRITY,
    ) -> None:
        """Initialize Adaptive Threshold Controller.

        Args:
            meta_drift_freeze: Threshold for freezing (default: 0.006)
            min_integrity: Minimum integrity index (default: 0.96)
        """
        self.meta_drift_freeze = float(meta_drift_freeze)
        self.min_integrity = float(min_integrity)
        self._state: Dict[str, Any] = {}

    def recompute(
        self, frpc_data: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """Recompute adaptive thresholds.

        Args:
            frpc_data: FRPC/TRQ3D-like payload with gradient, mean_energy, integrity_index

        Returns:
            AdaptiveUpdate as dict
        """
        ts = datetime.now(UTC).isoformat()

        if not frpc_data:
            return AdaptiveUpdate(
                timestamp=ts,
                meta_drift=0.0,
                integrity_index=1.0,
                mean_energy=0.0,
                freeze_thresholds=True,
                reason="FRPC data missing -> freeze",
                proposed={},
            ).as_dict()

        required_fields = {"gradient", "mean_energy", "integrity_index"}
        if not required_fields.issubset(frpc_data):
            missing = sorted(required_fields - set(frpc_data))
            return AdaptiveUpdate(
                timestamp=ts,
                meta_drift=0.0,
                integrity_index=1.0,
                mean_energy=0.0,
                freeze_thresholds=True,
                reason=f"missing fields: {missing}",
                proposed={},
            ).as_dict()

        try:
            meta_drift = abs(_safe_float(frpc_data.get("gradient", 0.0)))
            mean_energy = _safe_float(frpc_data.get("mean_energy", 0.0))
            integrity_index = _safe_float(frpc_data.get("integrity_index", 1.0))
        except (TypeError, ValueError):
            return AdaptiveUpdate(
                timestamp=ts,
                meta_drift=0.0,
                integrity_index=1.0,
                mean_energy=0.0,
                freeze_thresholds=True,
                reason="invalid numeric fields",
                proposed={},
            ).as_dict()

        if not all(
            math.isfinite(v) for v in [meta_drift, mean_energy, integrity_index]
        ):
            return AdaptiveUpdate(
                timestamp=ts,
                meta_drift=0.0,
                integrity_index=1.0,
                mean_energy=0.0,
                freeze_thresholds=True,
                reason="non-finite fields",
                proposed={},
            ).as_dict()

        meta_drift = max(meta_drift, 0.0)
        integrity_index = _clamp01(integrity_index)
        mean_energy = max(mean_energy, 0.0)

        freeze = False
        reason = "ok"
        if meta_drift > self.meta_drift_freeze:
            freeze = True
            reason = f"meta_drift={meta_drift:.6f} > freeze={self.meta_drift_freeze:.6f}"
        elif integrity_index < self.min_integrity:
            freeze = True
            reason = f"integrity_index={integrity_index:.4f} < min_integrity={self.min_integrity:.4f}"

        # Calculate adjustment factor
        adjustment_factor = 1.0 + (meta_drift * 12.0) - (
            max(0.0, integrity_index - 0.96) * 2.0
        )
        adjustment_factor = _clamp(adjustment_factor, 0.85, 1.15)

        proposed = {
            "adjustment_factor": round(adjustment_factor, 4),
            "meta_drift": round(meta_drift, 6),
            "mean_energy": round(mean_energy, 6),
            "integrity_index": round(integrity_index, 6),
        }

        update = AdaptiveUpdate(
            timestamp=ts,
            meta_drift=meta_drift,
            integrity_index=integrity_index,
            mean_energy=mean_energy,
            freeze_thresholds=freeze,
            reason=reason,
            proposed=proposed,
        )

        self._state = update.as_dict()
        return self._state

    def get_state(self) -> Dict[str, Any]:
        """Get current controller state."""
        return self._state.copy()


# =============================================================================
# 🔗 SECTION 13: FUSION INTEGRATOR
# =============================================================================


class FusionIntegrator:
    """Core Reflective Fusion Integrator (Layer 12).

    Key features:
    - Hard Gate: reflective_coherence < 0.96 => ABORT
    - Single Confidence Authority: conf12_raw from MonteCarloConfidence
    - Precision as WEIGHT only
    """

    VERSION = "5.3.3+"

    def __init__(
        self,
        *,
        gate_threshold: float = 0.96,
    ) -> None:
        """Initialize Fusion Integrator.

        Args:
            gate_threshold: Coherence gate threshold
        """
        self.gate_threshold = float(gate_threshold)

    def fuse_reflective_context(
        self,
        *,
        market_data: Dict[str, Any] | None = None,
        coherence_audit: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Fuse reflective context with market data.

        Args:
            market_data: Market data for precision calculation
            coherence_audit: Pre-computed coherence audit

        Returns:
            Fusion result with confidence lineage
        """
        market_data = market_data or {}

        alpha = _safe_float(market_data.get("alpha", 1.0), 1.0)
        beta = _safe_float(market_data.get("beta", 1.0), 1.0)
        gamma = _safe_float(market_data.get("gamma", 1.0), 1.0)
        lambda_esi = _safe_float(market_data.get("lambda_esi", 0.06), 0.06)

        field_context = resolve_field_context(
            pair=market_data.get("pair", "XAUUSD"),
            timeframe=market_data.get("timeframe", "H4"),
            alpha=alpha,
            beta=beta,
            gamma=gamma,
            lambda_esi=lambda_esi,
            field_override=market_data.get("field_override"),
        )

        fusion_output = {
            "timestamp": datetime.now(UTC).isoformat(),
            "fusion_version": self.VERSION,
            "field_context": field_context,
        }

        # Coherence gate check
        if coherence_audit is None:
            coherence_audit = self._default_coherence_audit()

        reflective_coherence = _safe_float(
            coherence_audit.get("reflective_coherence", 0.0)
        )
        gate_pass = bool(coherence_audit.get("gate_pass", False))

        if not gate_pass or reflective_coherence < self.gate_threshold:
            return {
                "status": "ABORTED",
                "reason": f"Reflective Coherence below gate ({reflective_coherence:.4f} < {self.gate_threshold:.2f})",
                "fusion_output": fusion_output,
                "coherence_audit": coherence_audit,
                "confidence_lineage": ConfidenceLineage(
                    raw=0.0,
                    weighted=0.0,
                    final=0.0,
                    precision_weight=1.0,
                    gate_threshold=self.gate_threshold,
                    gate_pass=False,
                    authority="FusionIntegrator",
                    notes="ABORTED by reflective hard gate",
                    lambda_esi=field_context.get("lambda_esi", 0.06),
                    field_state=field_context.get("field_state"),
                    field_integrity=field_context.get("field_integrity"),
                ).as_dict(),
            }

        # Calculate precision
        precision = calculate_fusion_precision(market_data)
        precision_weight = _clamp(
            _safe_float(precision.get("precision_weight", 1.0), 1.0),
            DEFAULT_PRECISION_WEIGHT_MIN,
            DEFAULT_PRECISION_WEIGHT_MAX,
        )

        # Calculate confidence
        base_bias = _safe_float(market_data.get("base_bias", 0.5), 0.5)
        conf12_raw = _clamp01(reflective_coherence * base_bias)
        conf12_weighted = _clamp01(conf12_raw * precision_weight)
        conf12_final = conf12_weighted

        lineage = ConfidenceLineage(
            raw=round(conf12_raw, 4),
            weighted=round(conf12_weighted, 4),
            final=round(conf12_final, 4),
            precision_weight=round(precision_weight, 4),
            gate_threshold=self.gate_threshold,
            gate_pass=True,
            authority="FusionIntegrator",
            notes="final = clamp(raw * precision_weight)",
            lambda_esi=field_context.get("lambda_esi", 0.06),
            field_state=field_context.get("field_state"),
            field_integrity=field_context.get("field_integrity"),
        )

        # Evaluate metrics
        metrics = evaluate_fusion_metrics(
            {**market_data, "fusion_strength": conf12_final}
        )

        return {
            "status": "OK",
            "fusion_output": fusion_output,
            "coherence_audit": coherence_audit,
            "precision": precision,
            "confidence_lineage": lineage.as_dict(),
            "conf12_final": round(conf12_final, 4),
            "metrics": metrics,
        }

    def _default_coherence_audit(self) -> Dict[str, Any]:
        """Return default coherence audit."""
        return {
            "reflective_coherence": 0.97,
            "gate_pass": True,
            "gate_threshold": self.gate_threshold,
        }


def integrate_fusion_layers(market_data: Dict[str, Any]) -> Dict[str, Any]:
    """Lightweight integration wrapper for fusion layers.

    Args:
        market_data: Market data dictionary

    Returns:
        Integrated fusion result
    """
    precision = calculate_fusion_precision(market_data)
    metrics = evaluate_fusion_metrics(market_data)

    precision_weight = _safe_float(precision.get("precision_weight", 1.0), 1.0)
    wlwci = _clamp01(0.96 + abs(precision_weight - 1.0) * 0.02)
    rc_adj = _clamp(
        (precision_weight - 1.0) * 0.05,
        -0.02,
        0.02,
    )

    return {
        "status": "Integrated",
        "WLWCI": round(wlwci, 3),
        "RCAdj": round(rc_adj, 4),
        "precision": precision,
        "metrics": metrics,
    }


# =============================================================================
# 🎲 SECTION 14: MONTE CARLO CONFIDENCE ENGINE
# =============================================================================


class MonteCarloConfidence:
    """Monte Carlo simulation for reflective bias consistency assessment.

    Single Source of Truth for CONF₁₂ (RAW) based on simulation.
    """

    def __init__(self, simulations: int = DEFAULT_MC_SIMULATIONS, seed: int | None = None) -> None:
        """Initialize Monte Carlo Confidence Engine.

        Args:
            simulations: Number of simulations (minimum 500)
            seed: Random seed for reproducibility
        """
        if simulations < DEFAULT_MC_MIN_SIMULATIONS:
            raise ValueError(f"simulations too small; minimum {DEFAULT_MC_MIN_SIMULATIONS}")
        self.simulations = simulations
        self._random = random.Random(seed)

    def run(
        self,
        *,
        base_bias: float,
        coherence: float,
        volatility_index: float,
        confidence_weight: float = 1.0,
    ) -> MonteCarloResult:
        """Run Monte Carlo simulation.

        Args:
            base_bias: Bias from bias-neutralizer (0-1)
            coherence: Coherence value (0-100)
            volatility_index: VIX-like index (10-40)
            confidence_weight: Legacy scalar (bounded)

        Returns:
            MonteCarloResult with simulation metrics
        """
        base_bias = _clamp01(float(base_bias))
        coherence01 = _clamp01(float(coherence) / 100.0)
        vix_norm = _clamp01((float(volatility_index) - 10.0) / 30.0)
        confidence_weight = _clamp(float(confidence_weight), 0.85, 1.15)

        samples: List[float] = []
        vol_samples: List[float] = []

        noise_sigma = 0.35 * (0.4 + 0.6 * vix_norm) * (0.7 + 0.3 * (1.0 - coherence01))

        for _ in range(self.simulations):
            b = base_bias + self._random.gauss(0.0, noise_sigma)
            b = _clamp01(b)

            decisiveness = abs(b - 0.5) * 2.0
            reliability = (0.55 * coherence01) + (0.45 * decisiveness)
            reliability = _clamp01(reliability)

            vol_penalty = 0.35 * vix_norm
            conf = reliability * (1.0 - vol_penalty)

            samples.append(_clamp01(conf))
            vol_samples.append(vix_norm)

        conf_mean = sum(samples) / len(samples)
        var = sum((x - conf_mean) ** 2 for x in samples) / len(samples)
        std = math.sqrt(var)
        stability_index = _clamp01(1.0 - std * 1.35)

        reliability_score = _clamp01(conf_mean)
        reflective_integrity = _clamp01((0.6 * coherence01) + (0.4 * stability_index))
        conf12_raw = _clamp01(conf_mean * confidence_weight)

        return MonteCarloResult(
            conf12_raw=float(conf12_raw),
            reliability_score=float(reliability_score),
            stability_index=float(stability_index),
            total_simulations=int(self.simulations),
            bias_mean=float(base_bias),
            volatility_mean=float(sum(vol_samples) / len(vol_samples)),
            reflective_integrity=float(reflective_integrity),
            timestamp=datetime.now(UTC).isoformat(),
        )


# =============================================================================
# 📈 SECTION 15: MULTI EMA FUSION
# =============================================================================


class MultiEMAFusion:
    """Multi-EMA Fusion Engine - Hybrid Reflective Mode.

    Builds Fusion Strength Index (FSI) and cross-timeframe trend confluence.
    """

    def __init__(self, ema_periods: List[int] | None = None) -> None:
        """Initialize Multi EMA Fusion.

        Args:
            ema_periods: EMA periods (default: [20, 50, 100, 200])
        """
        self.ema_periods = ema_periods or [20, 50, 100, 200]

    def calculate_ema(self, closes: List[float], period: int) -> List[float]:
        """Calculate EMA applied to close prices."""
        if not closes:
            return []

        alpha = 2 / (period + 1)
        ema = [closes[0]]

        for i in range(1, len(closes)):
            ema_val = (closes[i] * alpha) + (ema[i - 1] * (1 - alpha))
            ema.append(ema_val)

        return ema

    def integrate(self, closes: List[float], wlwci: float = 0.88) -> Dict[str, Any]:
        """Calculate all EMAs, slopes, and Fusion Strength Index (FSI)."""
        if not closes:
            return {"status": "no_data", "fusion_strength": 0.5}

        ema_results: Dict[str, Any] = {}
        slopes: List[float] = []

        for period in self.ema_periods:
            ema_values = self.calculate_ema(closes, period)
            ema_key = f"ema_{period}"

            if ema_values:
                ema_results[ema_key] = round(ema_values[-1], 5)

                if len(ema_values) > 1 and ema_values[-2] != 0:
                    slope = (ema_values[-1] - ema_values[-2]) / ema_values[-2]
                    ema_results[f"{ema_key}_slope"] = round(slope, 6)
                    slopes.append(slope)
                else:
                    ema_results[f"{ema_key}_slope"] = 0.0
            else:
                ema_results[ema_key] = 0.0
                ema_results[f"{ema_key}_slope"] = 0.0

        avg_slope = sum(slopes) / len(slopes) if slopes else 0.0
        fusion_strength = _clamp01(avg_slope * 0.5 + wlwci * 0.5)

        ema_results["fusion_strength"] = round(fusion_strength, 3)
        ema_results["wlwci"] = round(wlwci, 3)
        ema_results["trend_bias"] = (
            "Bullish" if avg_slope > 0 else "Bearish" if avg_slope < 0 else "Neutral"
        )

        return ema_results


# =============================================================================
# 📊 SECTION 16: MTF ALIGNMENT ANALYZER
# =============================================================================


def multi_timeframe_alignment_analyzer(  # noqa: PLR0913
    biases: Mapping[str, float],
    rsi_values: Mapping[str, float],
    reflective_intensity: float = 1.0,
    trq_energy: float = 1.0,
    alpha: float = 1.0,
    beta: float = 1.0,
    gamma: float = 1.0,
    integrity_index: float = 0.97,
    symbol: str | None = None,
    pair: str | None = None,
    trade_id: str | None = None,
) -> Dict[str, Any]:
    """Analyze cross-timeframe bias alignment.

    Args:
        biases: Dict { "H1": 1/-1, "H4": 1/-1, "D1": 1/-1, "W1": 1/-1 }
        rsi_values: Dict { "H1": val, "H4": val, "D1": val, "W1": val }
        reflective_intensity: Reflective intensity factor
        trq_energy: TRQ energy factor
        alpha, beta, gamma: Field coefficients
        integrity_index: Integrity index
        symbol: Optional symbol
        pair: Optional pair
        trade_id: Optional trade ID

    Returns:
        MTF alignment analysis result
    """
    validation_error = _validate_mtf_inputs(biases, rsi_values, MTF_TIMEFRAMES)
    if validation_error:
        return {"status": "Invalid timeframe data", "detail": validation_error}

    alignment_anchor = biases["H4"]
    aligned = [tf for tf in MTF_TIMEFRAMES if biases[tf] == alignment_anchor]
    alignment_ratio = len(aligned) / len(MTF_TIMEFRAMES)

    rsi_sample = [float(rsi_values[tf]) for tf in MTF_TIMEFRAMES]
    rsi_var = statistics.pstdev(rsi_sample) if len(rsi_sample) > 1 else 0.0
    rsi_coherence = max(0.0, 1.0 - (rsi_var / 25))

    bias_strength = alignment_ratio * rsi_coherence * reflective_intensity * trq_energy
    meta_sync = (alpha + beta + gamma) / 3
    bias_strength *= meta_sync

    if bias_strength >= 0.85:
        regime_state = "Strong Alignment"
    elif 0.65 <= bias_strength < 0.85:
        regime_state = "Moderate Alignment"
    elif 0.45 <= bias_strength < 0.65:
        regime_state = "Weak Alignment"
    else:
        regime_state = "Disaligned"

    time_coherence_index = (bias_strength * integrity_index) / (1 + rsi_var / 50)

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "alignment_ratio": round(alignment_ratio, 3),
        "rsi_variance": round(rsi_var, 3),
        "rsi_coherence": round(rsi_coherence, 3),
        "bias_strength": round(bias_strength, 3),
        "meta_sync": round(meta_sync, 3),
        "reflective_intensity": round(reflective_intensity, 3),
        "trq_energy": round(trq_energy, 3),
        "integrity_index": round(integrity_index, 3),
        "time_coherence_index": round(time_coherence_index, 3),
        "regime_state": regime_state,
        "status": "ok",
        "symbol": symbol,
        "pair": pair,
        "trade_id": trade_id,
    }


def _validate_mtf_inputs(
    biases: Mapping[str, float],
    rsi_values: Mapping[str, float],
    timeframes: Iterable[str],
) -> str | None:
    """Validate MTF analyzer inputs."""
    timeframes_list = list(timeframes)
    missing_biases = [tf for tf in timeframes_list if tf not in biases]
    missing_rsi = [tf for tf in timeframes_list if tf not in rsi_values]

    if missing_biases or missing_rsi:
        return f"Missing data for: {missing_biases + missing_rsi}"

    if not all(isinstance(biases[tf], (int, float)) for tf in timeframes_list):
        return "Bias values must be numeric."
    if not all(isinstance(rsi_values[tf], (int, float)) for tf in timeframes_list):
        return "RSI values must be numeric."
    if not all(math.isfinite(biases[tf]) for tf in timeframes_list):
        return "Bias values must be finite."
    if not all(math.isfinite(rsi_values[tf]) for tf in timeframes_list):
        return "RSI values must be finite."

    return None


# =============================================================================
# 🌌 SECTION 17: PHASE RESONANCE ENGINE
# =============================================================================


def phase_resonance_engine_v1_5(  # noqa: PLR0913
    price_change: float,
    volume_change: float,
    time_delta: float,
    atr: float,
    trq_energy: float = 1.0,
    reflective_intensity: float = 1.0,
    alpha: float = 1.0,
    beta: float = 1.0,
    gamma: float = 1.0,
    alpha_drift: float = 0.0,
    beta_drift: float = 0.0,
    gamma_drift: float = 0.0,
    integrity_index: float = 0.97,
    symbol: str | None = None,
    pair: str | None = None,
    trade_id: str | None = None,
    lambda_esi: float = 0.06,
    field_override: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Calculate Phase Resonance Index (PRI) and Resonant Field State.

    Args:
        price_change: Price change value
        volume_change: Volume change value
        time_delta: Time delta
        atr: ATR value
        trq_energy: TRQ energy factor
        reflective_intensity: Reflective intensity
        alpha, beta, gamma: Field coefficients
        alpha_drift, beta_drift, gamma_drift: Drift values
        integrity_index: Integrity index
        symbol: Optional symbol
        pair: Optional pair
        trade_id: Optional trade ID
        lambda_esi: ESI lambda
        field_override: Optional field override

    Returns:
        Phase resonance analysis result
    """
    base_values = [price_change, volume_change, time_delta, atr]
    meta_values = [
        trq_energy, reflective_intensity, alpha, beta, gamma,
        alpha_drift, beta_drift, gamma_drift, integrity_index,
    ]

    if not (
        all(math.isfinite(x) for x in base_values)
        and all(math.isfinite(x) for x in meta_values)
    ):
        return {"status": "invalid_input"}

    if any(v <= 0 for v in [abs(price_change), abs(volume_change), abs(time_delta), atr]):
        return {"status": "invalid_input"}

    # Clamp meta parameters
    trq_energy = _clamp(trq_energy, 0.1, 10.0)
    reflective_intensity = _clamp(reflective_intensity, 0.1, 10.0)
    alpha = _clamp(alpha, 0.5, 2.0)
    beta = _clamp(beta, 0.5, 2.0)
    gamma = _clamp(gamma, 0.5, 2.0)
    alpha_drift = _clamp(alpha_drift, -0.5, 0.5)
    beta_drift = _clamp(beta_drift, -0.5, 0.5)
    gamma_drift = _clamp(gamma_drift, -0.5, 0.5)
    integrity_index = _clamp01(integrity_index)

    price_energy = abs(price_change / atr)
    volume_energy = math.log1p(volume_change)
    time_energy = math.log1p(time_delta)

    energy_balance = (price_energy + volume_energy + time_energy) / 3
    imbalance_factor = (
        abs(price_energy - volume_energy)
        + abs(price_energy - time_energy)
        + abs(volume_energy - time_energy)
    ) / 3

    drift_factor = (abs(alpha_drift) + abs(beta_drift) + abs(gamma_drift)) / 3
    drift_correction = max(0.85, 1.0 - drift_factor)

    alpha_sync = (alpha + beta + gamma) / 3
    pri = (
        energy_balance
        / (1 + imbalance_factor)
        * trq_energy
        * reflective_intensity
        * alpha_sync
        * drift_correction
    )
    pri = _clamp(pri, 0.0, 10.0)

    if pri >= 1.3:
        field_state = ResonanceState.EXPANSION_RESONANCE.value
    elif 0.9 <= pri < 1.3:
        field_state = ResonanceState.EQUILIBRIUM_RESONANCE.value
    elif 0.7 <= pri < 0.9:
        field_state = ResonanceState.ADAPTIVE_COMPRESSION.value
    else:
        field_state = ResonanceState.PHASE_DRIFT_DETECTED.value

    coherence_score = _clamp((pri / (1 + drift_factor)) * integrity_index, 0.0, 10.0)

    field_context = resolve_field_context(
        pair=pair or "XAUUSD",
        timeframe="H4",
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        lambda_esi=lambda_esi,
        field_override=field_override,
    )

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "price_energy": round(price_energy, 3),
        "volume_energy": round(volume_energy, 3),
        "time_energy": round(time_energy, 3),
        "energy_balance": round(energy_balance, 3),
        "imbalance_factor": round(imbalance_factor, 3),
        "phase_resonance_index": round(pri, 3),
        "resonance_state": field_state,
        "alpha": round(alpha, 3),
        "beta": round(beta, 3),
        "gamma": round(gamma, 3),
        "alpha_drift": round(alpha_drift, 4),
        "beta_drift": round(beta_drift, 4),
        "gamma_drift": round(gamma_drift, 4),
        "drift_correction": round(drift_correction, 3),
        "reflective_intensity": round(reflective_intensity, 3),
        "trq_energy": round(trq_energy, 3),
        "integrity_index": round(integrity_index, 3),
        "coherence_score": round(coherence_score, 3),
        "status": "ok",
        "symbol": symbol,
        "pair": pair,
        "trade_id": trade_id,
        "lambda_esi": field_context.get("lambda_esi"),
        "field_state": field_context.get("field_state"),
        "field_integrity": field_context.get("field_integrity"),
    }


# =============================================================================
# ⚛️ SECTION 18: Q-MATRIX GENERATOR
# =============================================================================


class QMatrixGenerator:
    """Generator for Q-Matrix used in FTTC Monte Carlo.

    Q-Matrix defines transition rates between market states.
    Diagonal elements are negative sum of escape rates.
    """

    def __init__(self, config: QMatrixConfig | None = None) -> None:
        """Initialize Q-Matrix Generator.

        Args:
            config: Optional configuration
        """
        self.config = config or QMatrixConfig()
        self.states = list(TransitionState)
        self.n_states = len(self.states)
        self.state_to_idx = {state: i for i, state in enumerate(self.states)}
        self.q_matrix: List[List[float]] | None = None

    def _calculate_base_rates(self) -> List[List[float]]:
        """Calculate base transition rates between states."""
        rates = [[0.0] * self.n_states for _ in range(self.n_states)]

        base_transitions = {
            (TransitionState.STRONG_BULLISH, TransitionState.WEAK_BULLISH): 0.25,
            (TransitionState.STRONG_BULLISH, TransitionState.NEUTRAL): 0.10,
            (TransitionState.STRONG_BULLISH, TransitionState.HIGH_VOLATILITY): 0.05,
            (TransitionState.WEAK_BULLISH, TransitionState.STRONG_BULLISH): 0.20,
            (TransitionState.WEAK_BULLISH, TransitionState.NEUTRAL): 0.30,
            (TransitionState.WEAK_BULLISH, TransitionState.WEAK_BEARISH): 0.15,
            (TransitionState.NEUTRAL, TransitionState.WEAK_BULLISH): 0.25,
            (TransitionState.NEUTRAL, TransitionState.WEAK_BEARISH): 0.25,
            (TransitionState.NEUTRAL, TransitionState.LOW_VOLATILITY): 0.10,
            (TransitionState.WEAK_BEARISH, TransitionState.STRONG_BEARISH): 0.20,
            (TransitionState.WEAK_BEARISH, TransitionState.NEUTRAL): 0.30,
            (TransitionState.WEAK_BEARISH, TransitionState.WEAK_BULLISH): 0.15,
            (TransitionState.STRONG_BEARISH, TransitionState.WEAK_BEARISH): 0.25,
            (TransitionState.STRONG_BEARISH, TransitionState.NEUTRAL): 0.10,
            (TransitionState.STRONG_BEARISH, TransitionState.HIGH_VOLATILITY): 0.05,
            (TransitionState.HIGH_VOLATILITY, TransitionState.STRONG_BULLISH): 0.15,
            (TransitionState.HIGH_VOLATILITY, TransitionState.STRONG_BEARISH): 0.15,
            (TransitionState.HIGH_VOLATILITY, TransitionState.NEUTRAL): 0.20,
            (TransitionState.LOW_VOLATILITY, TransitionState.NEUTRAL): 0.30,
            (TransitionState.LOW_VOLATILITY, TransitionState.WEAK_BULLISH): 0.15,
            (TransitionState.LOW_VOLATILITY, TransitionState.WEAK_BEARISH): 0.15,
        }

        for (from_state, to_state), rate in base_transitions.items():
            i = self.state_to_idx[from_state]
            j = self.state_to_idx[to_state]
            rates[i][j] = rate * self.config.base_transition_rate

        return rates

    def generate(self, market_data: Dict[str, float]) -> List[List[float]]:
        """Generate Q-Matrix for given market conditions.

        Args:
            market_data: Dict with volatility, trend_strength, momentum

        Returns:
            Q-Matrix as 2D list
        """
        rates = self._calculate_base_rates()
        volatility = market_data.get("volatility", 1.0)
        trend_strength = market_data.get("trend_strength", 0.0)

        vol_factor = 1 + (volatility - 1) * self.config.volatility_sensitivity
        hv_idx = self.state_to_idx[TransitionState.HIGH_VOLATILITY]
        lv_idx = self.state_to_idx[TransitionState.LOW_VOLATILITY]

        if volatility > 1.5:
            for i in range(self.n_states):
                rates[i][hv_idx] *= vol_factor
                rates[lv_idx][i] *= vol_factor
        elif volatility < 0.5:
            for i in range(self.n_states):
                rates[i][lv_idx] *= (2 - vol_factor)
                rates[hv_idx][i] *= (2 - vol_factor)

        if trend_strength > 0.5:
            sb_idx = self.state_to_idx[TransitionState.STRONG_BULLISH]
            for i in range(self.n_states):
                rates[i][sb_idx] *= (1 + trend_strength * self.config.trend_sensitivity)
        elif trend_strength < -0.5:
            sbe_idx = self.state_to_idx[TransitionState.STRONG_BEARISH]
            for i in range(self.n_states):
                rates[i][sbe_idx] *= (1 + abs(trend_strength) * self.config.trend_sensitivity)

        # Add regularization and set diagonal
        for i in range(self.n_states):
            row_sum = 0.0
            for j in range(self.n_states):
                if i != j:
                    rates[i][j] += self.config.regularization
                    row_sum += rates[i][j]
            rates[i][i] = -row_sum

        self.q_matrix = rates
        return rates

    def get_escape_rate(self, state: TransitionState) -> float:
        """Get escape rate Γᵢ for a given state."""
        if self.q_matrix is None:
            raise ValueError("Q-Matrix not generated. Call generate() first.")
        idx = self.state_to_idx[state]
        return -self.q_matrix[idx][idx]

    def get_transition_probability(
        self, from_state: TransitionState, to_state: TransitionState
    ) -> float:
        """Get transition probability P(i → j) = Qᵢⱼ / Γᵢ"""
        if self.q_matrix is None:
            raise ValueError("Q-Matrix not generated. Call generate() first.")
        if from_state == to_state:
            return 0.0

        i = self.state_to_idx[from_state]
        j = self.state_to_idx[to_state]
        escape_rate = self.get_escape_rate(from_state)

        if escape_rate == 0:
            return 0.0
        return self.q_matrix[i][j] / escape_rate

    def export_matrix(self) -> Dict[str, Any]:
        """Export Q-Matrix as dictionary."""
        if self.q_matrix is None:
            return {}

        return {
            "states": [s.value for s in self.states],
            "matrix": self.q_matrix,
            "escape_rates": {s.value: self.get_escape_rate(s) for s in self.states},
        }


# =============================================================================
# 🔍 SECTION 19: MTF COHERENCE AUDITOR
# =============================================================================


def audit_reflective_coherence(
    *,
    mtf_data: List[Dict[str, Any]] | None = None,
    lookback: int = 64,
    divergence_threshold: float = 0.22,
    gate_threshold: float = 0.96,
) -> Dict[str, Any]:
    """Audit reflective coherence from MTF alignment data.

    Args:
        mtf_data: List of MTF alignment records
        lookback: Number of records to analyze
        divergence_threshold: Threshold for divergence detection
        gate_threshold: Threshold for gate pass

    Returns:
        CoherenceAudit result as dict
    """
    if not mtf_data or len(mtf_data) < lookback:
        return CoherenceAudit(
            timestamp=datetime.now(UTC).isoformat(),
            lookback=lookback,
            reflective_coherence=0.97,
            divergence_window=False,
            divergence_alert="✅ Default Stable",
            stability_state="Stable",
            gate_threshold=gate_threshold,
            gate_pass=True,
        ).as_dict()

    recent = mtf_data[-lookback:]

    bias_strengths = [
        float(x.get("bias_strength", 0.0)) for x in recent if "bias_strength" in x
    ]
    coherence_indices = [
        float(x.get("time_coherence_index", 0.0))
        for x in recent
        if "time_coherence_index" in x
    ]

    if not coherence_indices:
        return CoherenceAudit(
            timestamp=datetime.now(UTC).isoformat(),
            lookback=lookback,
            reflective_coherence=0.97,
            divergence_window=False,
            divergence_alert="✅ No data",
            stability_state="Stable",
            gate_threshold=gate_threshold,
            gate_pass=True,
        ).as_dict()

    avg_strength = statistics.mean(bias_strengths) if bias_strengths else 0.0
    var_strength = statistics.pstdev(bias_strengths) if len(bias_strengths) > 1 else 0.0
    avg_coherence = statistics.mean(coherence_indices)

    divergence_window = var_strength > divergence_threshold
    divergence_alert = (
        "⚠️ MTF Divergence Detected" if divergence_window else "✅ Stable Alignment"
    )

    reflective_coherence = avg_coherence
    if reflective_coherence > 1.5:
        reflective_coherence = reflective_coherence / 100.0
    reflective_coherence = _clamp01(reflective_coherence)

    stability_state = "Stable" if reflective_coherence >= gate_threshold else "Degraded"
    gate_pass = reflective_coherence >= gate_threshold

    result = CoherenceAudit(
        timestamp=datetime.now(UTC).isoformat(),
        lookback=lookback,
        reflective_coherence=round(reflective_coherence, 4),
        divergence_window=divergence_window,
        divergence_alert=divergence_alert,
        stability_state=stability_state,
        gate_threshold=gate_threshold,
        gate_pass=gate_pass,
    ).as_dict()

    result["avg_bias_strength"] = round(avg_strength, 4)
    result["bias_strength_std"] = round(var_strength, 4)

    return result


# =============================================================================
# 🎲 SECTION 20: FTTC MONTE CARLO ENGINE
# =============================================================================


class ReflectiveMonteCarlo:
    """FTTC Event-Driven Monte Carlo Engine.

    Implements Faster Than The Clock methodology for probabilistic
    trade outcome simulation with reflective integrity integration.
    """

    def __init__(self, config: FTTCConfig | None = None, seed: int | None = None) -> None:
        """Initialize FTTC Monte Carlo Engine.

        Args:
            config: Optional FTTC configuration
            seed: Optional random seed for reproducibility. If None, uses
                  time-based seed but logs it for post-hoc reproducibility.
        """
        self.config = config or FTTCConfig()
        self.states = list(MarketState)
        if seed is None:
            seed = int(datetime.now(UTC).timestamp() * 1000) % (2**31)
        self._seed = seed
        self._rng = random.Random(seed)

    def calculate_waiting_time(self, escape_rate: float) -> float:
        """Calculate waiting time using exponential distribution."""
        if escape_rate <= 0:
            return float("inf")
        return self._rng.expovariate(escape_rate)

    def calculate_meta_drift(
        self,
        frpc_gradient: float,
        tii_feedback: float,
        win_rate_mean: float,
    ) -> float:
        """Calculate meta drift for αβγ optimization.

        ΔR = (α × FRPC_gradient) + (β × TII_feedback) + (γ × WR_mean)
        """
        return (
            self.config.alpha * frpc_gradient
            + self.config.beta * tii_feedback
            + self.config.gamma * win_rate_mean
        )

    def run_simulation(
        self,
        initial_state: MarketState,
        market_data: Mapping[str, Any],
        signal_direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> FTTCResult:
        """Run full FTTC Monte Carlo simulation.

        Args:
            initial_state: Current market state
            market_data: Market data dict
            signal_direction: 'BUY' or 'SELL'
            entry_price: Trade entry price
            stop_loss: Stop loss price
            take_profit: Take profit price

        Returns:
            FTTCResult with simulation outcomes
        """
        wins = 0
        returns: List[float] = []
        max_drawdowns: List[float] = []

        for _ in range(self.config.iterations):
            outcome = self._simulate_trade_outcome(
                initial_state, signal_direction, entry_price, stop_loss, take_profit
            )

            if outcome["won"]:
                wins += 1
                returns.append(outcome["return"])
            else:
                returns.append(-outcome["loss"])

            max_drawdowns.append(outcome["max_drawdown"])

        win_probability = wins / self.config.iterations
        expected_return = sum(returns) / len(returns)
        max_dd_prob = sum(1 for dd in max_drawdowns if dd > 0.05) / len(max_drawdowns)

        sorted_returns = sorted(returns)
        ci_lower = sorted_returns[int(len(sorted_returns) * 0.025)]
        ci_upper = sorted_returns[int(len(sorted_returns) * 0.975)]

        escape_rates = {state.value: 0.5 for state in self.states}
        transition_probs = {state.value: 0.2 for state in self.states if state != initial_state}

        frpc_gradient = market_data.get("frpc_gradient", 0.01)
        tii_feedback = market_data.get("tii_feedback", 0.02)
        meta_drift = self.calculate_meta_drift(frpc_gradient, tii_feedback, win_probability)

        # Simplified Kelly criterion
        if win_probability > 0:
            positive_returns = [r for r in returns if r > 0]
            negative_returns = [r for r in returns if r < 0]
            avg_win = sum(positive_returns) / len(positive_returns) if positive_returns else 0
            avg_loss = abs(sum(negative_returns) / len(negative_returns)) if negative_returns else 1

            if avg_loss > 0 and avg_win > 0:
                kelly = (win_probability * avg_win - (1 - win_probability) * avg_loss) / avg_win
                optimal_size = _clamp(kelly * 0.5, 0.0, 0.02)
            else:
                optimal_size = 0.01
        else:
            optimal_size = 0.01

        return FTTCResult(
            win_probability=round(win_probability, 4),
            expected_return=round(expected_return, 6),
            max_drawdown_probability=round(max_dd_prob, 4),
            optimal_position_size=round(optimal_size, 4),
            confidence_interval=(round(ci_lower, 6), round(ci_upper, 6)),
            transition_probabilities=transition_probs,
            escape_rates=escape_rates,
            meta_drift=round(meta_drift, 6),
        )

    def _simulate_trade_outcome(
        self,
        initial_state: MarketState,
        direction: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
    ) -> Dict[str, Any]:
        """Simulate single trade outcome."""
        favorable = initial_state in (
            {MarketState.BULLISH} if direction == "BUY" else {MarketState.BEARISH}
        )
        base_win_prob = 0.6 if favorable else 0.4

        won = self._rng.random() < base_win_prob
        risk = abs(entry - stop_loss)
        reward = abs(take_profit - entry)

        return {
            "won": won,
            "return": reward / entry if won else 0,
            "loss": risk / entry if not won else 0,
            "max_drawdown": self._rng.uniform(0.01, 0.08),
        }

    def validate_signal(
        self,
        signal: Dict[str, Any],
        market_data: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Validate trading signal using FTTC simulation.

        Returns approval status and confidence metrics.
        """
        regime = market_data.get("regime", "RANGING")
        try:
            initial_state = MarketState(regime)
        except ValueError:
            initial_state = MarketState.RANGING

        result = self.run_simulation(
            initial_state=initial_state,
            market_data=market_data,
            signal_direction=signal.get("direction", "BUY"),
            entry_price=signal.get("entry", 1.0),
            stop_loss=signal.get("stop_loss", 0.99),
            take_profit=signal.get("take_profit", 1.02),
        )

        approved = (
            result.win_probability >= 0.65
            and result.meta_drift <= self.config.target_drift
            and result.max_drawdown_probability < 0.30
        )

        return {
            "approved": approved,
            "win_probability": result.win_probability,
            "expected_return": result.expected_return,
            "optimal_position_size": result.optimal_position_size,
            "confidence_interval": result.confidence_interval,
            "meta_drift": result.meta_drift,
            "recommendation": "EXECUTE" if approved else "WAIT",
            "timestamp": result.timestamp,
        }


def create_fttc_engine(config: Dict[str, Any] | None = None) -> ReflectiveMonteCarlo:
    """Factory function to create FTTC Monte Carlo engine."""
    if config:
        fttc_config = FTTCConfig(**config)
    else:
        fttc_config = FTTCConfig()
    return ReflectiveMonteCarlo(fttc_config)


# =============================================================================
# 💧 SECTION 21: LIQUIDITY ZONE MAPPER
# =============================================================================


class LiquidityZoneMapper:
    """Maps liquidity zones for smart money concept trading.

    Identifies where stop losses are likely clustered (liquidity)
    and tracks when institutions hunt these levels.
    """

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """Initialize Liquidity Zone Mapper.

        Args:
            config: Configuration parameters
        """
        self.config = config or self._default_config()
        self._zones: List[LiquidityZone] = []

    def _default_config(self) -> Dict[str, Any]:
        """Return default configuration."""
        return {
            "swing_lookback": DEFAULT_SWING_LOOKBACK,
            "equal_level_tolerance": DEFAULT_EQUAL_LEVEL_TOLERANCE,
            "min_touches_for_equal": 2,
            "zone_expiry_bars": 100,
            "strength_decay_rate": 0.95,
        }

    def map_liquidity(
        self,
        ohlcv_data: List[Dict[str, Any]],
        pair: str,
        timeframe: str,
        current_price: float,
    ) -> LiquidityMapResult:
        """Map liquidity zones from price data.

        Args:
            ohlcv_data: List of OHLCV candles
            pair: Trading pair
            timeframe: Timeframe of analysis
            current_price: Current market price

        Returns:
            LiquidityMapResult
        """
        timestamp = datetime.now(UTC)

        swing_highs = self._identify_swing_highs(ohlcv_data)
        swing_lows = self._identify_swing_lows(ohlcv_data)

        equal_highs = self._find_equal_levels(swing_highs, "high")
        equal_lows = self._find_equal_levels(swing_lows, "low")

        buy_side_zones = self._build_buy_side_zones(swing_highs, equal_highs, timeframe)
        sell_side_zones = self._build_sell_side_zones(swing_lows, equal_lows, timeframe)

        nearest_buy = self._find_nearest_zone(buy_side_zones, current_price, "above")
        nearest_sell = self._find_nearest_zone(sell_side_zones, current_price, "below")

        imbalance = self._calculate_liquidity_imbalance(
            buy_side_zones, sell_side_zones, current_price
        )

        return LiquidityMapResult(
            timestamp=timestamp,
            pair=pair,
            buy_side_zones=buy_side_zones,
            sell_side_zones=sell_side_zones,
            nearest_buy_liquidity=nearest_buy,
            nearest_sell_liquidity=nearest_sell,
            liquidity_imbalance=imbalance,
        )

    def _identify_swing_highs(
        self, ohlcv_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Identify swing high points."""
        swing_highs = []
        lookback = self.config["swing_lookback"]

        for i in range(lookback, len(ohlcv_data) - lookback):
            current_high = ohlcv_data[i].get("high", 0)
            is_swing_high = True

            for j in range(i - lookback, i + lookback + 1):
                if j != i and ohlcv_data[j].get("high", 0) > current_high:
                    is_swing_high = False
                    break

            if is_swing_high:
                swing_highs.append({"price": current_high, "index": i})

        return swing_highs

    def _identify_swing_lows(
        self, ohlcv_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Identify swing low points."""
        swing_lows = []
        lookback = self.config["swing_lookback"]

        for i in range(lookback, len(ohlcv_data) - lookback):
            current_low = ohlcv_data[i].get("low", 0)
            is_swing_low = True

            for j in range(i - lookback, i + lookback + 1):
                if j != i and ohlcv_data[j].get("low", 0) < current_low:
                    is_swing_low = False
                    break

            if is_swing_low:
                swing_lows.append({"price": current_low, "index": i})

        return swing_lows

    def _find_equal_levels(
        self, swings: List[Dict[str, Any]], level_type: str
    ) -> List[Dict[str, Any]]:
        """Find equal highs or equal lows."""
        equal_levels = []
        tolerance = self.config["equal_level_tolerance"]
        min_touches = self.config["min_touches_for_equal"]

        used_indices: set = set()

        for i, swing in enumerate(swings):
            if i in used_indices:
                continue

            similar_swings = [swing]

            for j, other_swing in enumerate(swings):
                if j != i and j not in used_indices:
                    if swing["price"] != 0:
                        price_diff = abs(swing["price"] - other_swing["price"])
                        if price_diff / swing["price"] < tolerance:
                            similar_swings.append(other_swing)
                            used_indices.add(j)

            if len(similar_swings) >= min_touches:
                avg_price = sum(s["price"] for s in similar_swings) / len(similar_swings)
                equal_levels.append(
                    {"price": avg_price, "touches": len(similar_swings)}
                )
                used_indices.add(i)

        return equal_levels

    def _build_buy_side_zones(
        self,
        swing_highs: List[Dict[str, Any]],
        equal_highs: List[Dict[str, Any]],
        timeframe: str,
    ) -> List[LiquidityZone]:
        """Build buy side liquidity zones."""
        zones = []
        timestamp = datetime.now(UTC)

        for swing in swing_highs:
            zone = LiquidityZone(
                zone_type=LiquidityType.SWING_HIGH,
                status=LiquidityStatus.UNTAPPED,
                price_level=swing["price"],
                price_range=(swing["price"], swing["price"] * 1.001),
                strength=60.0,
                touch_count=1,
                created_at=timestamp,
                last_tested=None,
                timeframe=timeframe,
            )
            zones.append(zone)

        for eq in equal_highs:
            zone = LiquidityZone(
                zone_type=LiquidityType.EQUAL_HIGHS,
                status=LiquidityStatus.UNTAPPED,
                price_level=eq["price"],
                price_range=(eq["price"], eq["price"] * 1.001),
                strength=80.0 + min(20, eq["touches"] * 5),
                touch_count=eq["touches"],
                created_at=timestamp,
                last_tested=None,
                timeframe=timeframe,
            )
            zones.append(zone)

        return zones

    def _build_sell_side_zones(
        self,
        swing_lows: List[Dict[str, Any]],
        equal_lows: List[Dict[str, Any]],
        timeframe: str,
    ) -> List[LiquidityZone]:
        """Build sell side liquidity zones."""
        zones = []
        timestamp = datetime.now(UTC)

        for swing in swing_lows:
            zone = LiquidityZone(
                zone_type=LiquidityType.SWING_LOW,
                status=LiquidityStatus.UNTAPPED,
                price_level=swing["price"],
                price_range=(swing["price"] * 0.999, swing["price"]),
                strength=60.0,
                touch_count=1,
                created_at=timestamp,
                last_tested=None,
                timeframe=timeframe,
            )
            zones.append(zone)

        for eq in equal_lows:
            zone = LiquidityZone(
                zone_type=LiquidityType.EQUAL_LOWS,
                status=LiquidityStatus.UNTAPPED,
                price_level=eq["price"],
                price_range=(eq["price"] * 0.999, eq["price"]),
                strength=80.0 + min(20, eq["touches"] * 5),
                touch_count=eq["touches"],
                created_at=timestamp,
                last_tested=None,
                timeframe=timeframe,
            )
            zones.append(zone)

        return zones

    def _find_nearest_zone(
        self,
        zones: List[LiquidityZone],
        current_price: float,
        direction: str,
    ) -> float | None:
        """Find nearest liquidity zone in given direction."""
        if not zones:
            return None

        valid_zones = []

        for zone in zones:
            if zone.status != LiquidityStatus.FULLY_SWEPT:
                if (direction == "above" and zone.price_level > current_price) or (direction == "below" and zone.price_level < current_price):
                    valid_zones.append(zone)

        if not valid_zones:
            return None

        if direction == "above":
            return min(z.price_level for z in valid_zones)
        return max(z.price_level for z in valid_zones)

    def _calculate_liquidity_imbalance(
        self,
        buy_side: List[LiquidityZone],
        sell_side: List[LiquidityZone],
        current_price: float,
    ) -> float:
        """Calculate liquidity imbalance.

        Returns:
            Positive = more buy side liquidity above
            Negative = more sell side liquidity below
        """
        buy_strength = sum(
            z.strength
            for z in buy_side
            if z.price_level > current_price and z.status != LiquidityStatus.FULLY_SWEPT
        )

        sell_strength = sum(
            z.strength
            for z in sell_side
            if z.price_level < current_price and z.status != LiquidityStatus.FULLY_SWEPT
        )

        total = buy_strength + sell_strength
        if total == 0:
            return 0.0

        return (buy_strength - sell_strength) / total


# =============================================================================
# 📋 SECTION 22: PUBLIC API
# =============================================================================

# =============================================================================
# 🛠️ SECTION 17: FUSION UTILITIES (from utils.py)
# =============================================================================


def validate_price_data(
    prices: Sequence[float],
    min_length: int = 10,
    allow_zero: bool = False,
) -> bool:
    """Validate price data sequence.

    Args:
        prices: Sequence of price values
        min_length: Minimum required length
        allow_zero: Whether to allow zero values

    Returns:
        True if valid, False otherwise
    """
    if not prices or len(prices) < min_length:
        return False

    for price in prices:
        if price is None:
            return False
        if not allow_zero and price <= 0:
            return False
        if not isinstance(price, (int, float)):
            return False

    return True


def normalize_timeframe(timeframe: str) -> str:
    """Normalize timeframe string to standard format.

    Args:
        timeframe: Input timeframe (e.g., "1h", "H1", "1H", "60")

    Returns:
        Normalized timeframe string (e.g., "H1")
    """
    tf = str(timeframe).upper().strip()

    mappings = {
        "1M": "M1",
        "5M": "M5",
        "15M": "M15",
        "30M": "M30",
        "1H": "H1",
        "4H": "H4",
        "1D": "D1",
        "1W": "W1",
        "60": "H1",
        "240": "H4",
        "1440": "D1",
        "MINUTE": "M1",
        "HOUR": "H1",
        "DAY": "D1",
        "WEEK": "W1",
    }

    return mappings.get(tf, tf)


def calculate_rr_ratio(
    entry: float,
    stop_loss: float,
    take_profit: float,
) -> float:
    """Calculate risk-reward ratio.

    Args:
        entry: Entry price
        stop_loss: Stop loss price
        take_profit: Take profit price

    Returns:
        Risk-reward ratio (e.g., 2.0 for 1:2)
    """
    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)

    if risk == 0:
        return 0.0

    return round(reward / risk, 2)


def timestamp_now() -> str:
    """Get current UTC timestamp as ISO string."""
    return datetime.now(UTC).isoformat()


def write_jsonl_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Atomically append JSON line to file.

    Args:
        path: Path to JSONL file
        data: Dictionary to write as JSON line
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(path, "a", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.write("\n")
    except OSError:
        pass


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Atomically write JSON to file.

    Args:
        path: Path to JSON file
        data: Dictionary to write as JSON
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")

    try:
        tmp_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError:
        if tmp_path.exists():
            tmp_path.unlink()


def moving_average(values: List[float], period: int) -> float | None:
    """Calculate simple moving average.

    Args:
        values: List of values
        period: MA period

    Returns:
        Moving average or None if insufficient data
    """
    if not values or len(values) < period:
        return None

    return sum(values[-period:]) / period


def exponential_moving_average(
    values: List[float],
    period: int,
    smoothing: float = 2.0,
) -> float | None:
    """Calculate exponential moving average.

    Args:
        values: List of values
        period: EMA period
        smoothing: Smoothing factor (default 2.0)

    Returns:
        EMA value or None if insufficient data
    """
    if not values or len(values) < period:
        return None

    multiplier = smoothing / (period + 1)
    ema = sum(values[:period]) / period

    for price in values[period:]:
        ema = (price * multiplier) + (ema * (1 - multiplier))

    return ema


# =============================================================================
# 🏦 SECTION 18: VAULT MACRO ENGINE (from vault_macro_engine.py)
# =============================================================================


class VaultMacroLayer:
    """Vault Macro Engine (EMA + SMA).

    Sistem "Reflective Gravity Anchor" yang menjaga stabilitas jangka panjang
    terhadap bias entry dan coherence dari seluruh Layer-12.
    """

    def __init__(
        self, ema_period: int = 200, sma_periods: List[int] | None = None
    ) -> None:
        self.ema_period = ema_period
        self.sma_periods = sma_periods or [200, 800]

    def calculate_ema(self, closes: List[float], period: int) -> float:
        """Calculate EMA (Exponential Moving Average) applied to close."""
        if not closes:
            return 0.0
        alpha = 2 / (period + 1)
        ema = closes[0]
        for price in closes[1:]:
            ema = (price * alpha) + (ema * (1 - alpha))
        return round(float(ema), 5)

    def calculate_sma(self, closes: List[float], period: int) -> float:
        """Calculate SMA (Simple Moving Average) applied to close."""
        if not closes:
            return 0.0
        if len(closes) < period:
            return round(float(sum(closes) / len(closes)), 5)
        sma = sum(closes[-period:]) / period
        return round(float(sma), 5)

    def derive_macro_bias(self, closes: List[float]) -> Dict[str, Any]:
        """Derive macro bias dari EMA-200, SMA-200, dan SMA-800.

        Args:
            closes: List harga penutupan (close prices)

        Returns:
            Dict berisi semua nilai MA, macro_bias, dan distance_pct
        """
        if not closes:
            return {"error": "No price data"}

        ema200 = self.calculate_ema(closes, self.ema_period)
        sma_results = {
            f"sma_{p}": self.calculate_sma(closes, p) for p in self.sma_periods
        }

        price_now = float(closes[-1])

        macro_bias = "Bullish" if price_now > ema200 else "Bearish"

        sma_ref = sma_results.get("sma_800", ema200)
        distance_pct = (
            round(((price_now - sma_ref) / sma_ref) * 100, 3) if sma_ref != 0 else 0.0
        )

        structural_alignment = self._check_structural_alignment(
            ema200, sma_results, price_now
        )

        return {
            "ema_200": ema200,
            **sma_results,
            "price_now": round(price_now, 5),
            "macro_bias": macro_bias,
            "distance_pct": distance_pct,
            "structural_alignment": structural_alignment,
        }

    def _check_structural_alignment(
        self, ema200: float, sma_results: Dict[str, float], price_now: float
    ) -> str:
        """Check structural alignment antara price, EMA-200, SMA-200, dan SMA-800."""
        sma200 = sma_results.get("sma_200", ema200)
        sma800 = sma_results.get("sma_800", ema200)

        if price_now > ema200 > sma200 > sma800:
            return "Strong_Bullish"
        if price_now < ema200 < sma200 < sma800:
            return "Strong_Bearish"
        if price_now > ema200 > sma200:
            return "Bullish"
        if price_now < ema200 < sma200:
            return "Bearish"
        return "Neutral"

    def get_reflective_gravity_score(self, closes: List[float]) -> Dict[str, Any]:
        """Hitung Reflective Gravity Score berdasarkan jarak dari SMA-800."""
        macro_data = self.derive_macro_bias(closes)
        if "error" in macro_data:
            return macro_data

        distance = abs(macro_data["distance_pct"])

        if distance <= 0.5:
            gravity_score = 1.0
        elif distance <= 1.0:
            gravity_score = 0.9
        elif distance <= 2.0:
            gravity_score = 0.8
        elif distance <= 5.0:
            gravity_score = 0.6
        else:
            gravity_score = 0.4

        return {
            **macro_data,
            "gravity_score": round(gravity_score, 3),
            "gravity_status": (
                "Strong"
                if gravity_score >= 0.8
                else "Moderate" if gravity_score >= 0.6 else "Weak"
            ),
        }


# =============================================================================
# 📊 SECTION 19: VOLUME PROFILE ANALYZER (from volume_profile_analyzer.py)
# =============================================================================


class VolumeZoneType(Enum):
    """Volume zone classifications."""

    HIGH_VOLUME_NODE = "hvn"
    LOW_VOLUME_NODE = "lvn"
    POC = "poc"
    VAH = "vah"
    VAL = "val"


@dataclass
class VolumeProfileResult:
    """Result of volume profile analysis."""

    timestamp: datetime
    pair: str
    timeframe: str
    poc_price: float
    vah_price: float
    val_price: float
    value_area_percent: float
    volume_nodes: List[Dict[str, Any]]
    total_volume: float
    profile_shape: str


@dataclass
class VolumeZone:
    """A significant volume zone."""

    zone_type: VolumeZoneType
    price_low: float
    price_high: float
    volume: float
    relative_strength: float


class VolumeProfileAnalyzer:
    """Analyzes volume at price to identify institutional activity zones.

    Key concepts:
    - POC (Point of Control): Price with highest volume
    - VAH (Value Area High): Upper boundary of 70% volume
    - VAL (Value Area Low): Lower boundary of 70% volume
    - HVN (High Volume Node): Areas of high trading interest
    - LVN (Low Volume Node): Areas price moves through quickly
    """

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        self.config = config or self._default_config()

    def _default_config(self) -> Dict[str, Any]:
        return {
            "value_area_percent": 0.70,
            "price_bins": 100,
            "hvn_threshold": 1.5,
            "lvn_threshold": 0.5,
            "min_volume_significance": 0.01,
        }

    def analyze(
        self, ohlcv_data: List[Dict[str, Any]], pair: str, timeframe: str
    ) -> VolumeProfileResult:
        """Analyze volume profile for price data."""
        timestamp = datetime.now(UTC)

        profile = self._build_profile(ohlcv_data)
        poc_price = self._calculate_poc(profile)
        vah_price, val_price = self._calculate_value_area(profile)
        volume_nodes = self._identify_volume_nodes(profile)
        profile_shape = self._determine_profile_shape(profile, poc_price)
        total_volume = sum(v for _, v in profile)
        va_volume = self._calculate_value_area_volume(profile, val_price, vah_price)
        value_area_percent = va_volume / total_volume if total_volume > 0 else 0

        return VolumeProfileResult(
            timestamp=timestamp,
            pair=pair,
            timeframe=timeframe,
            poc_price=poc_price,
            vah_price=vah_price,
            val_price=val_price,
            value_area_percent=value_area_percent,
            volume_nodes=volume_nodes,
            total_volume=total_volume,
            profile_shape=profile_shape,
        )

    def _build_profile(
        self, ohlcv_data: List[Dict[str, Any]]
    ) -> List[Tuple[float, float]]:
        """Build volume-at-price profile."""
        if not ohlcv_data:
            return []

        all_prices = []
        for candle in ohlcv_data:
            all_prices.extend([candle.get("high", 0), candle.get("low", 0)])

        if not all_prices:
            return []

        price_min = min(all_prices)
        price_max = max(all_prices)

        if price_max == price_min:
            return [(price_min, sum(c.get("volume", 0) for c in ohlcv_data))]

        num_bins = self.config["price_bins"]
        bin_size = (price_max - price_min) / num_bins
        volume_bins: Dict[int, float] = dict.fromkeys(range(num_bins), 0.0)

        for candle in ohlcv_data:
            candle_high = candle.get("high", 0)
            candle_low = candle.get("low", 0)
            candle_volume = candle.get("volume", 0)

            if candle_volume == 0:
                continue

            low_bin = int((candle_low - price_min) / bin_size)
            high_bin = int((candle_high - price_min) / bin_size)

            low_bin = max(0, min(num_bins - 1, low_bin))
            high_bin = max(0, min(num_bins - 1, high_bin))

            bins_covered = high_bin - low_bin + 1
            volume_per_bin = candle_volume / bins_covered

            for b in range(low_bin, high_bin + 1):
                volume_bins[b] += volume_per_bin

        profile = []
        for i in range(num_bins):
            price = price_min + (i + 0.5) * bin_size
            profile.append((price, volume_bins[i]))

        return profile

    def _calculate_poc(self, profile: List[Tuple[float, float]]) -> float:
        """Calculate Point of Control (highest volume price)."""
        if not profile:
            return 0.0

        max_volume = 0.0
        poc_price = profile[0][0]

        for price, volume in profile:
            if volume > max_volume:
                max_volume = volume
                poc_price = price

        return poc_price

    def _calculate_value_area(
        self, profile: List[Tuple[float, float]]
    ) -> Tuple[float, float]:
        """Calculate Value Area High and Low (70% of volume)."""
        if not profile:
            return 0.0, 0.0

        total_volume = sum(v for _, v in profile)
        target_volume = total_volume * self.config["value_area_percent"]

        sorted_profile = sorted(profile, key=lambda x: x[1], reverse=True)

        cumulative_volume = 0.0
        included_prices = []

        for price, volume in sorted_profile:
            cumulative_volume += volume
            included_prices.append(price)

            if cumulative_volume >= target_volume:
                break

        if not included_prices:
            return profile[-1][0], profile[0][0]

        vah = max(included_prices)
        val = min(included_prices)

        return vah, val

    def _calculate_value_area_volume(
        self, profile: List[Tuple[float, float]], val: float, vah: float
    ) -> float:
        """Calculate total volume within value area."""
        return sum(v for p, v in profile if val <= p <= vah)

    def _identify_volume_nodes(
        self, profile: List[Tuple[float, float]]
    ) -> List[Dict[str, Any]]:
        """Identify High Volume Nodes and Low Volume Nodes."""
        if not profile:
            return []

        total_volume = sum(v for _, v in profile)
        avg_volume = total_volume / len(profile) if profile else 0

        hvn_threshold = avg_volume * self.config["hvn_threshold"]
        lvn_threshold = avg_volume * self.config["lvn_threshold"]

        nodes = []

        for price, volume in profile:
            if volume > hvn_threshold:
                nodes.append(
                    {
                        "type": VolumeZoneType.HIGH_VOLUME_NODE.value,
                        "price": price,
                        "volume": volume,
                        "strength": volume / avg_volume if avg_volume > 0 else 0,
                    }
                )
            elif 0 < volume < lvn_threshold:
                nodes.append(
                    {
                        "type": VolumeZoneType.LOW_VOLUME_NODE.value,
                        "price": price,
                        "volume": volume,
                        "strength": volume / avg_volume if avg_volume > 0 else 0,
                    }
                )

        return nodes

    def _determine_profile_shape(
        self, profile: List[Tuple[float, float]], poc: float
    ) -> str:
        """Determine volume profile shape."""
        if not profile:
            return "normal"

        prices = [p for p, v in profile]
        price_range = max(prices) - min(prices)

        if price_range == 0:
            return "normal"

        poc_position = (poc - min(prices)) / price_range

        if poc_position > 0.7:
            return "p"
        if poc_position < 0.3:
            return "b"
        return "d"

    def validate_entry_at_level(
        self, price: float, profile_result: VolumeProfileResult, direction: str
    ) -> Dict[str, Any]:
        """Validate if an entry at a price level is supported by volume profile."""
        validation: Dict[str, Any] = {
            "valid": False,
            "score": 0,
            "reasons": [],
            "warnings": [],
        }

        poc_distance = (
            abs(price - profile_result.poc_price) / profile_result.poc_price
            if profile_result.poc_price
            else 0
        )
        if poc_distance < 0.001:
            validation["reasons"].append("Entry at POC - high volume support")
            validation["score"] += 30

        if profile_result.val_price <= price <= profile_result.vah_price:
            validation["reasons"].append("Entry within Value Area")
            validation["score"] += 20

        if direction == "buy" and profile_result.val_price:
            val_distance = (
                abs(price - profile_result.val_price) / profile_result.val_price
            )
            if val_distance < 0.002:
                validation["reasons"].append("Buy at VAL - institutional demand zone")
                validation["score"] += 25

        if direction == "sell" and profile_result.vah_price:
            vah_distance = (
                abs(price - profile_result.vah_price) / profile_result.vah_price
            )
            if vah_distance < 0.002:
                validation["reasons"].append("Sell at VAH - institutional supply zone")
                validation["score"] += 25

        for node in profile_result.volume_nodes:
            node_price = node["price"]
            node_distance = abs(price - node_price) / node_price if node_price else 0

            if node_distance < 0.002:
                if node["type"] == VolumeZoneType.HIGH_VOLUME_NODE.value:
                    validation["reasons"].append("At HVN - strong support/resistance")
                    validation["score"] += 15
                elif node["type"] == VolumeZoneType.LOW_VOLUME_NODE.value:
                    validation["warnings"].append("At LVN - price may move quickly")

        validation["valid"] = validation["score"] >= 50

        return validation


# =============================================================================
# ⚙️ SECTION 20: WLWCI CONFIGURATION (from wlwci_weights.yaml)
# =============================================================================

WLWCI_CONFIG: Final[Dict[str, Any]] = {
    "version": "7.1.0",
    "weights": {
        "twms_macro": 0.42,
        "trend_fusion": 0.28,
        "twms_micro": 0.18,
        "volatility_penalty": 0.12,
    },
    "micro_bounds": {
        "twms_micro_max": 0.30,
        "twms_micro_min": -0.30,
        "volatility_cap": 0.50,
        "min_confidence_multiplier": 0.70,
    },
    "volatility_regimes": {
        "low": {"threshold": 0.15, "confidence_boost": 1.05},
        "medium": {"threshold": 0.35, "confidence_boost": 1.00},
        "high": {"threshold": 0.55, "confidence_boost": 0.85},
        "extreme": {"threshold": 1.00, "confidence_boost": 0.70},
    },
    "orchestrator_thresholds": {
        "entry_min": 0.65,
        "strong_signal": 0.78,
        "exit_warning": 0.45,
        "emergency_exit": 0.30,
    },
    "micro_rules": {
        "require_macro_alignment": True,
        "macro_alignment_threshold": 0.50,
        "disable_on_extreme_vol": True,
        "conflict_decay_factor": 0.50,
    },
    "fallback": {
        "no_micro_weights": {
            "twms_macro": 0.55,
            "trend_fusion": 0.45,
            "volatility_penalty": 0.00,
        },
        "no_trend_weights": {
            "twms_macro": 0.70,
            "twms_micro": 0.30,
            "volatility_penalty": 0.15,
        },
    },
}


def get_wlwci_config() -> Dict[str, Any]:
    """Get WLWCI configuration dictionary."""
    return WLWCI_CONFIG.copy()


def calculate_wlwci(
    twms_macro: float,
    trend_fusion: float,
    twms_micro: float,
    volatility: float,
    config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Calculate WLWCI (Weighted Layered Wave-Context Index).

    Formula:
        WLWCI = (w_macro × TWMS_macro)
              + (w_trend × TrendFusion)
              + (w_micro × TWMS_micro)
              - (w_vol_penalty × MicroVolatilityPenalty)

    Args:
        twms_macro: TWMS from higher timeframes (H1/H4/D1)
        trend_fusion: EMA/VWAP/DVG trend fusion
        twms_micro: TWMS micro (realtime tick-based)
        volatility: Current volatility measure
        config: Optional configuration override

    Returns:
        Dict with WLWCI value and components
    """
    cfg = config or WLWCI_CONFIG
    weights = cfg["weights"]
    bounds = cfg["micro_bounds"]
    regimes = cfg["volatility_regimes"]

    # Clamp micro signal
    twms_micro_clamped = _clamp(twms_micro, bounds["twms_micro_min"], bounds["twms_micro_max"])

    # Determine volatility regime
    vol_boost = 1.0
    regime = "medium"
    for regime_name, regime_cfg in regimes.items():
        if volatility <= regime_cfg["threshold"]:
            vol_boost = regime_cfg["confidence_boost"]
            regime = regime_name
            break

    # Calculate volatility penalty
    vol_penalty = min(volatility, bounds["volatility_cap"])

    # Calculate WLWCI
    wlwci_raw = (
        weights["twms_macro"] * twms_macro
        + weights["trend_fusion"] * trend_fusion
        + weights["twms_micro"] * twms_micro_clamped
        - weights["volatility_penalty"] * vol_penalty
    )

    # Apply regime adjustment
    wlwci_adjusted = wlwci_raw * vol_boost

    # Clamp final value
    wlwci_final = _clamp01(wlwci_adjusted)

    return {
        "wlwci": round(wlwci_final, 4),
        "wlwci_raw": round(wlwci_raw, 4),
        "volatility_regime": regime,
        "confidence_boost": vol_boost,
        "components": {
            "twms_macro_contrib": round(weights["twms_macro"] * twms_macro, 4),
            "trend_fusion_contrib": round(weights["trend_fusion"] * trend_fusion, 4),
            "twms_micro_contrib": round(weights["twms_micro"] * twms_micro_clamped, 4),
            "vol_penalty_contrib": round(weights["volatility_penalty"] * vol_penalty, 4),
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }


# =============================================================================
# 📈 SECTION 21: RSI ALIGNMENT ENGINE (from rsi_alignment_engine.py)
# =============================================================================


def rsi_alignment_engine(
    *,
    rsi_w1: float,
    rsi_d1: float,
    rsi_h4: float,
    rsi_h1: float,
) -> Dict[str, Any]:
    """Calculate RSI alignment across multiple timeframes.

    Args:
        rsi_w1: RSI Weekly
        rsi_d1: RSI Daily
        rsi_h4: RSI 4H
        rsi_h1: RSI 1H

    Returns:
        dict: Alignment score, bias, and confidence
    """

    def get_bias(rsi: float) -> str:
        if rsi >= 60:
            return "BULLISH"
        if rsi <= 40:
            return "BEARISH"
        return "NEUTRAL"

    tf_bias = {
        "W1": get_bias(rsi_w1),
        "D1": get_bias(rsi_d1),
        "H4": get_bias(rsi_h4),
        "H1": get_bias(rsi_h1),
    }

    bullish_count = list(tf_bias.values()).count("BULLISH")
    bearish_count = list(tf_bias.values()).count("BEARISH")

    if bullish_count >= 3:
        momentum_bias = "BULLISH"
    elif bearish_count >= 3:
        momentum_bias = "BEARISH"
    else:
        momentum_bias = "NEUTRAL"

    alignment_score = round((max(bullish_count, bearish_count) / 4) * 100, 2)

    rsi_values = [rsi_w1, rsi_d1, rsi_h4, rsi_h1]
    avg_rsi = sum(rsi_values) / 4
    rsi_range = max(rsi_values) - min(rsi_values)
    coherence_factor = max(0.0, 1 - (rsi_range / 50))
    confidence = round(alignment_score * coherence_factor, 2)

    return {
        "alignment_score": alignment_score,
        "momentum_bias": momentum_bias,
        "confidence": confidence,
        "rsi_mean": round(avg_rsi, 2),
        "rsi_range": round(rsi_range, 2),
        "detail": tf_bias,
    }


# =============================================================================
# 💹 SECTION 22: SMART MONEY COUNTER ZONE (from smart_money_counter_zone_v3_5_reflective.py)
# =============================================================================


@dataclass
class CounterZoneContext:
    """Context for Smart Money counter-zone detection."""

    price: float
    vwap: float
    atr: float
    rsi: float
    mfi: float
    cci50: float
    rsi_h4: float
    trq_energy: float = 1.0
    reflective_intensity: float = 1.0
    alpha: float = 1.0
    beta: float = 1.0
    gamma: float = 1.0
    integrity_index: float = 0.97
    journal_path: Path | None = None
    symbol: str | None = None
    pair: str | None = None
    trade_id: str | None = None


def _compute_counter_zone_confidence(ctx: CounterZoneContext) -> float:
    """Compute confidence for counter-zone signal."""
    energy_score = _clamp(ctx.trq_energy / 2.5, 0.0, 1.0)
    reflective_score = _clamp((ctx.reflective_intensity + ctx.integrity_index) / 2, 0.0, 1.0)
    gradient_score = _clamp((ctx.alpha + ctx.beta + ctx.gamma) / 3, 0.0, 1.0)
    momentum_score = _clamp(
        (
            abs(ctx.rsi - 50.0) / 50.0
            + abs(ctx.mfi - 50.0) / 50.0
            + min(abs(ctx.cci50) / 200.0, 1.0)
            + abs(ctx.rsi_h4 - 50.0) / 50.0
        )
        / 4,
        0.0,
        1.0,
    )

    confidence = 0.35
    confidence += 0.25 * energy_score
    confidence += 0.2 * reflective_score
    confidence += 0.1 * gradient_score
    confidence += 0.1 * momentum_score

    return round(_clamp(confidence, 0.0, 1.0), 3)


def _derive_counter_zone_direction(ctx: CounterZoneContext) -> str:
    """Derive direction for counter-zone signal."""
    if ctx.price > ctx.vwap and ctx.rsi >= 60.0:
        return "SELL"
    if ctx.price < ctx.vwap and ctx.rsi <= 40.0:
        return "BUY"
    if ctx.mfi <= 45.0 and ctx.price <= ctx.vwap:
        return "BUY"
    if ctx.rsi_h4 >= 65.0:
        return "SELL"
    return "BUY" if ctx.price <= ctx.vwap else "SELL"


def smart_money_counter_v3_5_reflective(
    context: CounterZoneContext | None = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Detect reflective counter-zones using VWAP, TRQ-3D, and αβγ gradients.

    Args:
        context: Optional pre-built CounterZoneContext
        **kwargs: Backward-compatible keyword fields for CounterZoneContext

    Returns:
        Dict with counter-zone signal data
    """
    if context is not None and kwargs:
        return {
            "status": "invalid_input",
            "detail": "Provide either context or keyword fields, not both.",
        }

    if context is None:
        required_fields = ("price", "vwap", "atr", "rsi", "mfi", "cci50", "rsi_h4")
        missing_fields = [field for field in required_fields if field not in kwargs]
        if missing_fields:
            return {
                "status": "invalid_input",
                "detail": f"missing required fields: {missing_fields}",
            }

        try:
            ctx = CounterZoneContext(
                price=float(kwargs["price"]),
                vwap=float(kwargs["vwap"]),
                atr=float(kwargs["atr"]),
                rsi=float(kwargs["rsi"]),
                mfi=float(kwargs["mfi"]),
                cci50=float(kwargs["cci50"]),
                rsi_h4=float(kwargs["rsi_h4"]),
                trq_energy=float(kwargs.get("trq_energy", 1.0)),
                reflective_intensity=float(kwargs.get("reflective_intensity", 1.0)),
                alpha=float(kwargs.get("alpha", 1.0)),
                beta=float(kwargs.get("beta", 1.0)),
                gamma=float(kwargs.get("gamma", 1.0)),
                integrity_index=float(kwargs.get("integrity_index", 0.97)),
                journal_path=kwargs.get("journal_path"),
                symbol=kwargs.get("symbol"),
                pair=kwargs.get("pair"),
                trade_id=kwargs.get("trade_id"),
            )
        except (TypeError, ValueError):
            return {"status": "invalid_input"}
    else:
        ctx = context

    numeric_fields = {
        "price": ctx.price,
        "vwap": ctx.vwap,
        "atr": ctx.atr,
        "rsi": ctx.rsi,
        "mfi": ctx.mfi,
        "cci50": ctx.cci50,
        "rsi_h4": ctx.rsi_h4,
        "trq_energy": ctx.trq_energy,
        "reflective_intensity": ctx.reflective_intensity,
        "alpha": ctx.alpha,
        "beta": ctx.beta,
        "gamma": ctx.gamma,
        "integrity_index": ctx.integrity_index,
    }

    if not all(math.isfinite(v) for v in numeric_fields.values()):
        return {"status": "invalid_input"}
    if ctx.atr <= 0:
        return {"status": "invalid_atr"}

    # Thresholds
    vwap_deviation_factor = 1.2
    spread_threshold = 55.0
    reflective_energy_min = 0.85

    vwap_dev = abs(ctx.price - ctx.vwap)
    spread = abs(ctx.mfi - ctx.cci50)
    vwap_thr = vwap_deviation_factor * ctx.atr
    reflective_energy = ctx.trq_energy * ctx.reflective_intensity

    effective_spread_threshold = min(spread_threshold, 40.0)
    is_valid = (
        vwap_dev >= vwap_thr
        and spread >= effective_spread_threshold
        and reflective_energy >= reflective_energy_min
    )

    if not is_valid:
        return {
            "status": "No valid counter-zone",
            "confidence": 0.0,
            "counter_zone": False,
        }

    direction = _derive_counter_zone_direction(ctx)
    risk_buffer = max(ctx.atr * 1.6, 0.0008)
    target_buffer = max(ctx.atr * 1.8, 0.0012)

    if direction == "BUY":
        entry = round(ctx.price - ctx.atr * 0.1, 5)
        sl = round(entry - risk_buffer, 5)
        tp = round(entry + target_buffer, 5)
    else:
        entry = round(ctx.price + ctx.atr * 0.1, 5)
        sl = round(entry + risk_buffer, 5)
        tp = round(entry - target_buffer, 5)

    result: Dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "type": direction,
        "confidence": _compute_counter_zone_confidence(ctx),
        "spread": round(spread, 2),
        "deviation": round(vwap_dev, 5),
        "note": "Smart Money VWAP Counter-Zone v3.5 (Reflective Adaptive Mode)",
        "meta": {
            "trq_energy": round(ctx.trq_energy, 6),
            "reflective_intensity": round(ctx.reflective_intensity, 6),
            "alpha": round(ctx.alpha, 6),
            "beta": round(ctx.beta, 6),
            "gamma": round(ctx.gamma, 6),
            "integrity_index": round(ctx.integrity_index, 6),
        },
        "status": "ok",
        "counter_zone": True,
        "symbol": ctx.symbol,
        "pair": ctx.pair,
        "trade_id": ctx.trade_id,
    }

    if ctx.journal_path:
        write_jsonl_atomic(ctx.journal_path, result)

    return result


# =============================================================================
# 🌐 SECTION 23: ULTRA FUSION ORCHESTRATOR (from ultra_fusion_orchestrator_v6_production.py)
# =============================================================================


class UltraFusionOrchestrator:
    """Main orchestrator for TUYUL FX Ultimate Fusion Pipeline (L8-L11).

    Integrates:
    - EMA Fusion → Precision Fusion → Equilibrium → Reflective Propagation
    """

    VERSION = "6.0"

    def __init__(self) -> None:
        self.ema_engine = EMAFusionEngine()
        self.precision_engine = FusionPrecisionEngine()

    def execute_pipeline(
        self,
        symbol: str,
        prices: List[float],
        vwap_val: float,
        atr_val: float,
        reflex_strength: float,
        volatility: float,
        rsi_val: float,
        ema50_val: float,
        ema100_val: float,
        rc_adjusted: float,
    ) -> Dict[str, Any]:
        """Run multi-layer fusion analysis for a symbol.

        Args:
            symbol: Trading symbol
            prices: Price series
            vwap_val: VWAP value
            atr_val: ATR value
            reflex_strength: Reflex strength
            volatility: Volatility
            rsi_val: RSI value
            ema50_val: EMA50 value
            ema100_val: EMA100 value
            rc_adjusted: RC adjusted value

        Returns:
            Complete fusion pipeline result
        """
        timestamp = datetime.now(UTC).isoformat()

        # Layer 8: EMA Fusion
        ema_fusion = self.ema_engine.compute(prices)
        ema_fusion["timestamp"] = timestamp

        # Layer 9: Fusion Precision
        precision_result = self.precision_engine.compute_precision(
            price=prices[-1] if prices else 0.0,
            ema_fast_val=ema_fusion.get("ema21", 0.0),
            ema_slow_val=ema_fusion.get("ema55", 0.0),
            vwap=vwap_val,
            atr=atr_val,
            reflex_strength=reflex_strength,
            volatility=volatility,
            rsi=rsi_val,
            symbol=symbol,
        )
        precision = precision_result.as_dict()

        # Layer 10: Equilibrium Fusion
        equilibrium = equilibrium_momentum_fusion(
            vwap_val=vwap_val,
            ema_fusion_data={
                "ema50": ema50_val,
                "fusion_strength": precision.get("fusion_strength", 0.0),
                "cross_state": (
                    "bullish" if ema_fusion.get("direction") == "BULL" else "bearish"
                ),
            },
            reflex_strength=reflex_strength,
            lambda_esi=precision.get("details", {}).get("lambda_esi", 0.06),
        )

        # Layer 11: Reflective Propagation (simplified)
        frpc_output = {
            "fusion_strength": precision.get("fusion_strength", 0.0),
            "reflex_strength": reflex_strength,
            "rc_adjusted": rc_adjusted,
            "equilibrium_state": equilibrium.get("state", "NEUTRAL"),
            "propagation_index": round(
                (precision.get("fusion_strength", 0.0) + reflex_strength + rc_adjusted)
                / 3,
                4,
            ),
            "timestamp": timestamp,
        }

        fusion_payload = {
            "symbol": symbol,
            "timestamp": timestamp,
            "ema_layer": ema_fusion,
            "precision_layer": precision,
            "equilibrium_layer": equilibrium,
            "reflective_layer": frpc_output,
        }

        logger.info(f"[☁️] ULTRA FUSION pipeline synced → {symbol}")

        return fusion_payload


# Backward-compatible alias
UltraFusionOrchestratorV6 = UltraFusionOrchestrator


# =============================================================================
# 🔌 SECTION 24: MICRO ADAPTER (from micro_adapter.py)
# =============================================================================


class VolatilityRegime(Enum):
    """Market volatility classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class MicroBounds:
    """Safety bounds for micro signals."""

    def __init__(
        self,
        twms_max: float = 0.30,
        twms_min: float = -0.30,
        vol_cap: float = 0.50,
        min_confidence: float = 0.70,
    ) -> None:
        self.twms_max = twms_max
        self.twms_min = twms_min
        self.vol_cap = vol_cap
        self.min_confidence = min_confidence


@dataclass
class NormalizedMicro:
    """Normalized micro signal ready for WLWCI consumption."""

    twms_micro: float
    vol_penalty: float
    regime: VolatilityRegime
    confidence_multiplier: float
    is_valid: bool
    conflict_detected: bool
    raw_twms_micro: float
    raw_volatility: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "twms_micro": self.twms_micro,
            "vol_penalty": self.vol_penalty,
            "regime": self.regime.value,
            "confidence_multiplier": self.confidence_multiplier,
            "is_valid": self.is_valid,
            "conflict_detected": self.conflict_detected,
            "raw_twms_micro": self.raw_twms_micro,
            "raw_volatility": self.raw_volatility,
        }


class MicroAdapter:
    """Adapter for normalizing microstructure signals for WLWCI.

    CRITICAL SAFETY FEATURES:
    1. TWMS micro is capped to ±0.3 (cannot dominate)
    2. Volatility penalty is capped to 0.5 (cannot zero-out WLWCI)
    3. Conflict detection when micro opposes macro
    4. Graceful handling of missing/invalid data

    This adapter ensures microstructure ENHANCES but never OVERRIDES
    the primary TWMS macro signal.
    """

    # Volatility regime thresholds
    VOL_LOW: float = 0.15
    VOL_MEDIUM: float = 0.35
    VOL_HIGH: float = 0.55

    # Confidence multipliers per regime
    CONFIDENCE_MULTIPLIERS: Dict[VolatilityRegime, float] = {
        VolatilityRegime.LOW: 1.05,
        VolatilityRegime.MEDIUM: 1.00,
        VolatilityRegime.HIGH: 0.85,
        VolatilityRegime.EXTREME: 0.70,
    }

    def __init__(self, bounds: MicroBounds | None = None) -> None:
        """Initialize adapter with safety bounds.

        Args:
            bounds: Custom bounds, or use defaults
        """
        self.bounds = bounds or MicroBounds()

    def normalize(
        self,
        micro: Dict[str, Any],
        macro_direction: float | None = None,
    ) -> NormalizedMicro:
        """Normalize micro signal with safety bounds.

        Args:
            micro: Raw micro signal dict with keys:
                   - twms_micro: float (-1 to 1)
                   - volatility OR micro_volatility: float (0 to 1)
                   - momentum (optional): float
            macro_direction: TWMS macro score for conflict detection

        Returns:
            NormalizedMicro with bounded values
        """
        # Extract values with fallbacks
        raw_twms = self._extract_twms(micro)
        raw_vol = self._extract_volatility(micro)

        # Validate
        if raw_twms is None or raw_vol is None:
            return self._invalid_result(raw_twms, raw_vol)

        # Apply bounds
        bounded_twms = self._bound_twms(raw_twms)
        bounded_vol = self._bound_volatility(raw_vol)

        # Determine regime
        regime = self._classify_regime(raw_vol)

        # Get confidence multiplier
        confidence_multiplier = self.CONFIDENCE_MULTIPLIERS.get(
            regime, 1.0
        )

        # Detect conflict with macro
        conflict_detected = self._detect_conflict(bounded_twms, macro_direction)

        # Apply conflict dampening if detected
        if conflict_detected:
            bounded_twms = bounded_twms * 0.5  # Dampen conflicting signal

        return NormalizedMicro(
            twms_micro=round(bounded_twms, 4),
            vol_penalty=round(bounded_vol, 4),
            regime=regime,
            confidence_multiplier=confidence_multiplier,
            is_valid=True,
            conflict_detected=conflict_detected,
            raw_twms_micro=raw_twms,
            raw_volatility=raw_vol,
        )

    def _extract_twms(self, micro: Dict[str, Any]) -> float | None:
        """Extract TWMS micro value from input dict."""
        for key in ["twms_micro", "micro_twms", "twms", "micro"]:
            if key in micro:
                try:
                    value = float(micro[key])
                    if math.isfinite(value):
                        return value
                except (TypeError, ValueError):
                    continue
        return None

    def _extract_volatility(self, micro: Dict[str, Any]) -> float | None:
        """Extract volatility value from input dict."""
        for key in ["volatility", "micro_volatility", "vol", "micro_vol"]:
            if key in micro:
                try:
                    value = float(micro[key])
                    if math.isfinite(value) and value >= 0:
                        return value
                except (TypeError, ValueError):
                    continue
        return None

    def _bound_twms(self, raw_twms: float) -> float:
        """Apply safety bounds to TWMS micro signal."""
        return _clamp(raw_twms, self.bounds.twms_min, self.bounds.twms_max)

    def _bound_volatility(self, raw_vol: float) -> float:
        """Apply cap to volatility penalty."""
        return min(raw_vol, self.bounds.vol_cap)

    def _classify_regime(self, volatility: float) -> VolatilityRegime:
        """Classify volatility into regime categories."""
        if volatility <= self.VOL_LOW:
            return VolatilityRegime.LOW
        if volatility <= self.VOL_MEDIUM:
            return VolatilityRegime.MEDIUM
        if volatility <= self.VOL_HIGH:
            return VolatilityRegime.HIGH
        return VolatilityRegime.EXTREME

    def _detect_conflict(
        self,
        micro_twms: float,
        macro_direction: float | None,
    ) -> bool:
        """Detect if micro signal conflicts with macro direction.

        Conflict occurs when:
        - micro is positive but macro is negative (or vice versa)
        - AND both signals are significant (abs > 0.1)
        """
        if macro_direction is None:
            return False

        micro_sign = 1 if micro_twms > 0 else -1 if micro_twms < 0 else 0
        macro_sign = 1 if macro_direction > 0 else -1 if macro_direction < 0 else 0

        # Both must have significant magnitude
        micro_significant = abs(micro_twms) > 0.1
        macro_significant = abs(macro_direction) > 0.1

        return (
            micro_sign != 0
            and macro_sign not in (0, micro_sign)
            and micro_significant
            and macro_significant
        )

    def _invalid_result(
        self,
        raw_twms: float | None,
        raw_vol: float | None,
    ) -> NormalizedMicro:
        """Return an invalid/fallback result."""
        return NormalizedMicro(
            twms_micro=0.0,
            vol_penalty=0.0,
            regime=VolatilityRegime.MEDIUM,
            confidence_multiplier=1.0,
            is_valid=False,
            conflict_detected=False,
            raw_twms_micro=raw_twms if raw_twms is not None else 0.0,
            raw_volatility=raw_vol if raw_vol is not None else 0.0,
        )

    def apply_to_wlwci(
        self,
        wlwci_base: float,
        normalized: NormalizedMicro,
        weights: Dict[str, float] | None = None,
    ) -> Dict[str, Any]:
        """Apply normalized micro signal to WLWCI calculation.

        Args:
            wlwci_base: Base WLWCI value (from macro + trend)
            normalized: Normalized micro signal
            weights: Optional weight overrides

        Returns:
            Dict with adjusted WLWCI and metadata
        """
        default_weights = {
            "twms_micro": 0.18,
            "volatility_penalty": 0.12,
        }
        w = weights or default_weights

        if not normalized.is_valid:
            return {
                "wlwci": round(wlwci_base, 4),
                "adjusted": False,
                "reason": "invalid_micro_data",
                "normalized": normalized.to_dict(),
            }

        # Apply micro contribution
        micro_contrib = w["twms_micro"] * normalized.twms_micro
        vol_penalty = w["volatility_penalty"] * normalized.vol_penalty

        # Calculate adjusted WLWCI
        wlwci_adjusted = wlwci_base + micro_contrib - vol_penalty

        # Apply confidence multiplier
        wlwci_final = wlwci_adjusted * normalized.confidence_multiplier

        # Ensure bounds
        wlwci_final = _clamp01(wlwci_final)

        return {
            "wlwci": round(wlwci_final, 4),
            "wlwci_base": round(wlwci_base, 4),
            "micro_contrib": round(micro_contrib, 4),
            "vol_penalty": round(vol_penalty, 4),
            "confidence_multiplier": normalized.confidence_multiplier,
            "regime": normalized.regime.value,
            "adjusted": True,
            "conflict_detected": normalized.conflict_detected,
            "normalized": normalized.to_dict(),
        }


# =============================================================================
# ⚛️ SECTION 25: HYBRID VAULT QUANTUM ENGINE (from hybrid_vault_quantum_engine.py)
# =============================================================================


class QuantumReflectiveEngine:
    """Quantum Reflective Engine - Entropy-based reflective field analysis.

    Menghitung:
    - Alpha-Beta-Gamma gradient (αβγ)
    - Reflective Energy (stabilitas)
    - Flux State (Stable / High_Flux / Transitional)
    """

    def __init__(
        self,
        alpha_weight: float = 0.4,
        beta_weight: float = 0.35,
        gamma_weight: float = 0.25,
    ) -> None:
        self.alpha_weight = alpha_weight
        self.beta_weight = beta_weight
        self.gamma_weight = gamma_weight

    def evaluate_reflective_entropy(self, closes: List[float]) -> Dict[str, Any]:
        """Evaluate reflective entropy dari price series.

        Args:
            closes: List/array harga penutupan

        Returns:
            Dict berisi alpha_beta_gamma, reflective_energy, flux_state
        """
        if len(closes) < 20:
            return {
                "alpha": 0.0,
                "beta": 0.0,
                "gamma": 0.0,
                "alpha_beta_gamma": 0.0,
                "reflective_energy": 0.5,
                "flux_state": "Insufficient_Data",
            }

        # Calculate returns
        returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] != 0:
                returns.append((closes[i] - closes[i - 1]) / closes[i - 1])  # noqa: PERF401

        if not returns:
            return {
                "alpha": 0.0,
                "beta": 0.0,
                "gamma": 0.0,
                "alpha_beta_gamma": 0.0,
                "reflective_energy": 0.5,
                "flux_state": "Insufficient_Data",
            }

        # Alpha: Short-term momentum (last 5 periods)
        alpha = self._std(returns[-5:]) if len(returns) >= 5 else 0.0

        # Beta: Medium-term volatility (last 20 periods)
        beta = self._std(returns[-20:]) if len(returns) >= 20 else 0.0

        # Gamma: Long-term drift (trend strength)
        if len(returns) >= 50:
            gamma = abs(sum(returns[-50:]) / 50)
        else:
            gamma = abs(sum(returns) / len(returns)) if returns else 0.0

        # Alpha-Beta-Gamma Gradient
        alpha_beta_gamma = round(
            (alpha * self.alpha_weight)
            + (beta * self.beta_weight)
            + (gamma * self.gamma_weight),
            6,
        )

        # Reflective Energy: Inverse of entropy (higher = more stable)
        entropy = alpha_beta_gamma * 100  # Scale up
        reflective_energy = round(max(0.0, min(1.0, 1.0 - entropy)), 3)

        # Flux State determination
        if alpha_beta_gamma <= 0.0015 and reflective_energy >= 0.95:
            flux_state = "Stable"
        elif alpha_beta_gamma <= 0.0025 and reflective_energy >= 0.90:
            flux_state = "High_Flux"
        else:
            flux_state = "Transitional"

        return {
            "alpha": round(alpha, 6),
            "beta": round(beta, 6),
            "gamma": round(gamma, 6),
            "alpha_beta_gamma": alpha_beta_gamma,
            "reflective_energy": reflective_energy,
            "flux_state": flux_state,
        }

    def _std(self, values: List[float]) -> float:
        """Calculate standard deviation."""
        if not values or len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return math.sqrt(variance)


class HybridReflectiveCore:
    """Hybrid Layer-9 Engine: Quantum ↔ Fusion (Vault Macro).

    Menggabungkan kekuatan:
    - Quantum Reflective Entropy Field (intuitif, meta-energetik)
    - Vault Macro Fusion (empiris, data harga riil)

    Optimal Coefficients:
    - quantum_weight: 0.4 (persepsi reflektif / intuisi)
    - macro_weight: 0.6 (data makro / disiplin)

    Architecture:
    ┌────────────────────────────┐
    │ L9_HYBRID_REFLECTIVE_CORE  │
    ├──────────────┬─────────────┤
    │ Quantum Core │ Vault Macro │
    │ αβγ, RFA, QEΔ│ EMA/SMA Bias│
    └───────┬──────┴───────┬─────┘
            │ Weighted Fusion
            ▼
     Reflective Macro Coherence (RMC)
    """

    def __init__(
        self,
        ema_period: int = 200,
        sma_periods: List[int] | None = None,
        quantum_weight: float = 0.4,
        macro_weight: float = 0.6,
    ) -> None:
        self.quantum = QuantumReflectiveEngine()
        self.vault = VaultMacroLayer(
            ema_period=ema_period, sma_periods=sma_periods or [200, 800]
        )
        self.quantum_weight = quantum_weight
        self.macro_weight = macro_weight

    def integrate(self, closes: List[float]) -> Dict[str, Any]:
        """Gabungkan data Quantum Field dan Vault Macro menjadi satu refleksi hybrid.

        Args:
            closes: List harga penutupan

        Returns:
            Dict berisi semua metric quantum + macro + hybrid strength/bias
        """
        if not closes:
            return {"error": "No price data"}

        # --- 1️⃣ Hitung field quantum ---
        qfield = self.quantum.evaluate_reflective_entropy(closes)

        # --- 2️⃣ Hitung field makro empiris ---
        vmacro = self.vault.get_reflective_gravity_score(closes)

        if "error" in vmacro:
            return vmacro

        # --- 3️⃣ Fusion logika reflektif hybrid ---
        # Normalize EMA ratio untuk komparasi
        price_now = closes[-1]
        ema_ratio = vmacro["ema_200"] / price_now if price_now != 0 else 1.0
        ema_normalized = min(1.0, max(0.5, ema_ratio))  # Clamp 0.5-1.0

        # Hybrid Reflective Strength = weighted combination
        reflective_strength = (qfield["reflective_energy"] * self.quantum_weight) + (
            ema_normalized * self.macro_weight
        )
        reflective_strength = round(min(1.0, max(0.0, reflective_strength)), 3)

        # --- 4️⃣ Hybrid Bias determination ---
        hybrid_bias = vmacro["macro_bias"]

        # Override bias jika quantum flux tidak stabil dan strength rendah
        if qfield["flux_state"] == "Transitional" and reflective_strength < 0.85:
            hybrid_bias = "Transitional"
        elif qfield["flux_state"] == "High_Flux" and reflective_strength < 0.90:
            hybrid_bias = "Cautious_" + vmacro["macro_bias"]

        # --- 5️⃣ Reflective Macro Coherence (RMC) ---
        rmc = self._calculate_rmc(qfield, vmacro, reflective_strength)

        # --- 6️⃣ Integrasi output ---
        return {
            # Quantum metrics
            "alpha": qfield["alpha"],
            "beta": qfield["beta"],
            "gamma": qfield["gamma"],
            "alpha_beta_gamma": qfield["alpha_beta_gamma"],
            "reflective_energy": qfield["reflective_energy"],
            "flux_state": qfield["flux_state"],
            # Vault Macro metrics
            "ema_200": vmacro["ema_200"],
            "sma_200": vmacro.get("sma_200", 0.0),
            "sma_800": vmacro.get("sma_800", 0.0),
            "macro_bias": vmacro["macro_bias"],
            "distance_pct": vmacro["distance_pct"],
            "structural_alignment": vmacro["structural_alignment"],
            "gravity_score": vmacro["gravity_score"],
            # Hybrid metrics
            "hybrid_reflective_strength": reflective_strength,
            "hybrid_bias": hybrid_bias,
            "reflective_macro_coherence": rmc,
            "quantum_weight": self.quantum_weight,
            "macro_weight": self.macro_weight,
        }

    def _calculate_rmc(
        self, qfield: Dict[str, Any], vmacro: Dict[str, Any], hybrid_strength: float
    ) -> float:
        """Calculate Reflective Macro Coherence (RMC).

        RMC = weighted average of:
        - Reflective Energy (quantum)
        - Gravity Score (macro)
        - Hybrid Strength
        """
        rmc = (
            (qfield["reflective_energy"] * 0.3)
            + (vmacro["gravity_score"] * 0.3)
            + (hybrid_strength * 0.4)
        )
        return round(min(1.0, max(0.0, rmc)), 3)

    def get_execution_status(
        self, closes: List[float], tii_threshold: float = 0.93
    ) -> Dict[str, Any]:
        """Determine execution status berdasarkan hybrid analysis.

        Args:
            closes: List harga penutupan
            tii_threshold: Minimum TII untuk EXECUTE

        Returns:
            Dict berisi execution decision dan reasoning
        """
        hybrid_data = self.integrate(closes)

        if "error" in hybrid_data:
            return {
                **hybrid_data,
                "pseudo_tii": 0.0,
                "execution_decision": "HOLD",
                "execution_reason": "Error in hybrid analysis",
            }

        # Calculate pseudo-TII dari hybrid metrics
        pseudo_tii = (
            (hybrid_data["reflective_energy"] * 0.4)
            + (hybrid_data["gravity_score"] * 0.3)
            + (hybrid_data["hybrid_reflective_strength"] * 0.3)
        )
        pseudo_tii = round(pseudo_tii, 3)

        # Decision logic
        if pseudo_tii >= tii_threshold and hybrid_data["flux_state"] == "Stable":
            decision = "EXECUTE"
            reason = f"TII={pseudo_tii} >= {tii_threshold}, Flux=Stable"
        elif pseudo_tii >= 0.90 and hybrid_data["flux_state"] in [
            "Stable",
            "High_Flux",
        ]:
            decision = "WAIT"
            reason = (
                f"TII={pseudo_tii}, Flux={hybrid_data['flux_state']} - Pending confirmation"
            )
        else:
            decision = "HOLD"
            reason = f"TII={pseudo_tii} < threshold or Flux={hybrid_data['flux_state']}"

        return {
            **hybrid_data,
            "pseudo_tii": pseudo_tii,
            "execution_decision": decision,
            "execution_reason": reason,
        }


# =============================================================================
# 📋 SECTION 26: PUBLIC API
# =============================================================================

__all__ = [
    "WLWCI_CONFIG",
    "AdaptiveThresholdController",
    "AdaptiveUpdate",
    "CoherenceAudit",
    "ConfidenceLineage",
    "CounterZoneContext",
    "DivergenceSignal",
    "DivergenceStrength",
    "DivergenceType",
    "EMAFusionEngine",
    "EquilibriumResult",
    "FTTCConfig",
    "FTTCResult",
    "FieldContext",
    "FusionAction",
    "FusionBiasMode",
    "FusionComputeError",
    "FusionConfigError",
    "FusionError",
    "FusionInputError",
    "FusionIntegrator",
    "FusionPrecisionEngine",
    "FusionPrecisionResult",
    "FusionState",
    "HybridReflectiveCore",
    "LiquidityMapResult",
    "LiquidityStatus",
    "LiquidityType",
    "LiquidityZone",
    "LiquidityZoneMapper",
    "MarketState",
    "MicroAdapter",
    "MicroBounds",
    "MomentumBand",
    "MonteCarloConfidence",
    "MonteCarloResult",
    "MultiDivergenceResult",
    "MultiEMAFusion",
    "MultiIndicatorDivergenceDetector",
    "NormalizedMicro",
    "QMatrixConfig",
    "QMatrixGenerator",
    "QuantumReflectiveEngine",
    "ReflectiveMonteCarlo",
    "ResonanceState",
    "TransitionState",
    "UltraFusionOrchestrator",
    "UltraFusionOrchestratorV6",
    "VaultMacroLayer",
    "VolatilityRegime",
    "VolumeProfileAnalyzer",
    "VolumeProfileResult",
    "VolumeZone",
    "VolumeZoneType",
    "aggregate_multi_timeframe_metrics",
    "audit_reflective_coherence",
    "calculate_fusion_precision",
    "calculate_rr_ratio",
    "calculate_wlwci",
    "create_fttc_engine",
    "equilibrium_momentum_fusion",
    "equilibrium_momentum_fusion_v6",
    "evaluate_fusion_metrics",
    "exponential_moving_average",
    "get_wlwci_config",
    "integrate_fusion_layers",
    "moving_average",
    "multi_timeframe_alignment_analyzer",
    "normalize_timeframe",
    "phase_resonance_engine_v1_5",
    "resolve_field_context",
    "rsi_alignment_engine",
    "smart_money_counter_v3_5_reflective",
    "sync_field_state",
    "timestamp_now",
    "validate_price_data",
    "write_json_atomic",
    "write_jsonl_atomic",
]


# =============================================================================
# 🧪 SECTION 23: CLI / DEBUG UTILITY
# =============================================================================

if __name__ == "__main__":
    """
    print("🧠 TUYUL FX AGI - Core Fusion Unified v7.0r∞ EXPANDED")
    print("=" * 60)

    # Test Field Sync
    print("\n🔄 Testing Field Sync...")
    field_ctx = resolve_field_context(
        pair="XAUUSD",
        timeframe="H4",
        alpha=1.05,
        beta=0.98,
        gamma=1.02,
    )
    print(f"Field State: {field_ctx['field_state']}")
    print(f"Field Integrity: {field_ctx['field_integrity']}")

    # Test EMA Fusion Engine
    print("\n📈 Testing EMA Fusion Engine...")
    ema_engine = EMAFusionEngine(periods=[21, 55, 100])
    prices = [100 + i * 0.1 for i in range(120)]
    ema_result = ema_engine.compute(prices)
    print(f"Direction: {ema_result['direction']}")
    print(f"Fusion Strength: {ema_result['fusion_strength']}")

    # Test Fusion Metrics
    print("\n📊 Testing Fusion Metrics Analyzer...")
    metrics = evaluate_fusion_metrics(
        {"fusion_strength": 0.85, "direction": "BULL", "coherence": 0.92}
    )
    print(f"Action: {metrics['action']}")
    print(f"Composite Score: {metrics['composite_score']}")

    # Test Fusion Precision Engine
    print("\n🎯 Testing Fusion Precision Engine...")
    precision_engine = FusionPrecisionEngine()
    precision_result = precision_engine.compute_precision(
        price=1.0875,
        ema_fast_val=1.0854,
        ema_slow_val=1.0838,
        vwap=1.0860,
        atr=0.0018,
        reflex_strength=0.42,
        volatility=0.0015,
        rsi=62.0,
    )
    print(f"Fusion Strength: {precision_result.fusion_strength}")
    print(f"Bias Mode: {precision_result.bias_mode}")
    print(f"Precision Weight: {precision_result.precision_weight}")

    # Test Equilibrium Momentum
    print("\n⚖️ Testing Equilibrium Momentum Fusion...")
    eq_result = equilibrium_momentum_fusion_v6(
        price_change=0.0025,
        volume_change=1500.0,
        time_weight=0.85,
        atr=0.0018,
        trq_energy=1.2,
        reflective_intensity=1.1,
        integrity_index=0.97,
        direction_hint=1.0,
    )
    print(f"Status: {eq_result.get('status')}")
    print(f"State: {eq_result.get('state')}")
    print(f"Momentum Band: {eq_result.get('momentum_band')}")

    # Test Divergence Detector
    print("\n📊 Testing Multi-Indicator Divergence Detector...")
    div_detector = MultiIndicatorDivergenceDetector()
    ohlcv_data = [
        {"high": 100 + i * 0.1, "low": 99 + i * 0.1, "close": 99.5 + i * 0.1}
        for i in range(60)
    ]
    div_result = div_detector.analyze(ohlcv_data, "XAUUSD", "H4")
    print(f"Confluence Count: {div_result.confluence_count}")
    print(f"Overall Signal: {div_result.overall_signal.value}")

    # Test Adaptive Threshold Controller
    print("\n⚙️ Testing Adaptive Threshold Controller...")
    threshold_ctrl = AdaptiveThresholdController()
    adaptive_result = threshold_ctrl.recompute(
        {"gradient": 0.003, "mean_energy": 0.85, "integrity_index": 0.97}
    )
    print(f"Freeze: {adaptive_result['freeze_thresholds']}")
    print(f"Reason: {adaptive_result['reason']}")

    # Test Fusion Integrator
    print("\n🔗 Testing Fusion Integrator...")
    integrator = FusionIntegrator()
    fusion_result = integrator.fuse_reflective_context(
        market_data={
            "price": 1.0875,
            "ema_fast_val": 1.0854,
            "ema_slow_val": 1.0838,
            "vwap": 1.0860,
            "atr": 0.0018,
            "reflex_strength": 0.42,
            "volatility": 0.0015,
            "rsi": 62.0,
            "base_bias": 0.58,
        },
        coherence_audit={"reflective_coherence": 0.97, "gate_pass": True},
    )
    print(f"Status: {fusion_result['status']}")
    print(f"CONF12 Final: {fusion_result.get('conf12_final')}")

    # Test Monte Carlo Confidence
    print("\n🎲 Testing Monte Carlo Confidence Engine...")
    mc_engine = MonteCarloConfidence(simulations=1000, seed=42)
    mc_result = mc_engine.run(
        base_bias=0.58,
        coherence=83.5,
        volatility_index=18.7,
    )
    print(f"CONF12 Raw: {mc_result.conf12_raw:.4f}")
    print(f"Reliability: {mc_result.reliability_score:.4f}")
    print(f"Stability: {mc_result.stability_index:.4f}")

    # Test Multi EMA Fusion
    print("\n📈 Testing Multi EMA Fusion...")
    multi_ema = MultiEMAFusion(ema_periods=[20, 50, 100, 200])
    closes = [100 + i * 0.05 + (i % 10) * 0.02 for i in range(250)]
    multi_ema_result = multi_ema.integrate(closes, wlwci=0.92)
    print(f"Trend Bias: {multi_ema_result.get('trend_bias')}")
    print(f"Fusion Strength: {multi_ema_result.get('fusion_strength')}")

    # Test MTF Alignment Analyzer
    print("\n📊 Testing MTF Alignment Analyzer...")
    biases = {"H1": 1, "H4": 1, "D1": 1, "W1": -1}
    rsi_values = {"H1": 55, "H4": 58, "D1": 52, "W1": 48}
    mtf_result = multi_timeframe_alignment_analyzer(biases, rsi_values)
    print(f"Regime State: {mtf_result.get('regime_state')}")
    print(f"Alignment Ratio: {mtf_result.get('alignment_ratio')}")

    # Test Phase Resonance Engine
    print("\n🌌 Testing Phase Resonance Engine...")
    phase_result = phase_resonance_engine_v1_5(
        price_change=0.0035,
        volume_change=2500.0,
        time_delta=4.0,
        atr=0.0022,
        trq_energy=1.15,
        reflective_intensity=1.08,
    )
    print(f"Status: {phase_result.get('status')}")
    print(f"Resonance State: {phase_result.get('resonance_state')}")
    print(f"PRI: {phase_result.get('phase_resonance_index')}")

    # Test Q-Matrix Generator
    print("\n⚛️ Testing Q-Matrix Generator...")
    q_gen = QMatrixGenerator()
    q_matrix = q_gen.generate({"volatility": 1.3, "trend_strength": 0.6})
    print(f"Matrix Size: {len(q_matrix)}x{len(q_matrix[0])}")
    print(f"Escape Rate (NEUTRAL): {q_gen.get_escape_rate(TransitionState.NEUTRAL):.4f}")

    # Test MTF Coherence Auditor
    print("\n🔍 Testing MTF Coherence Auditor...")
    # Create sample MTF data
    sample_mtf_data = [
        {"bias_strength": 0.85 + i * 0.01, "time_coherence_index": 0.92 + i * 0.005}
        for i in range(70)
    ]
    coherence_result = audit_reflective_coherence(mtf_data=sample_mtf_data)
    print(f"Gate Pass: {coherence_result.get('gate_pass')}")
    print(f"Coherence: {coherence_result.get('reflective_coherence')}")

    # Test FTTC Monte Carlo
    print("\n🎲 Testing FTTC Monte Carlo Engine...")
    fttc_engine = create_fttc_engine({"iterations": 500})
    signal = {"direction": "BUY", "entry": 1.0850, "stop_loss": 1.0800, "take_profit": 1.0950}
    market_data = {"volatility": 1.2, "regime": "BULLISH"}
    fttc_result = fttc_engine.validate_signal(signal, market_data)
    print(f"Approved: {fttc_result.get('approved')}")
    print(f"Win Probability: {fttc_result.get('win_probability'):.2%}")
    print(f"Recommendation: {fttc_result.get('recommendation')}")

    # Test Liquidity Zone Mapper
    print("\n💧 Testing Liquidity Zone Mapper...")
    liq_mapper = LiquidityZoneMapper()
    ohlcv_liq = [
        {"high": 100 + i * 0.1 + (i % 5) * 0.05, "low": 99 + i * 0.1, "close": 99.5 + i * 0.1}
        for i in range(60)
    ]
    liq_result = liq_mapper.map_liquidity(ohlcv_liq, "XAUUSD", "H4", current_price=102.5)
    print(f"Buy Side Zones: {len(liq_result.buy_side_zones)}")
    print(f"Sell Side Zones: {len(liq_result.sell_side_zones)}")
    print(f"Liquidity Imbalance: {liq_result.liquidity_imbalance:.3f}")

    # === NEW COMPONENT TESTS ===

    # Test Vault Macro Layer
    print("\n🏦 Testing Vault Macro Layer...")
    vault_macro = VaultMacroLayer()
    closes_macro = [100 + i * 0.1 + (i % 20) * 0.05 for i in range(250)]
    macro_result = vault_macro.derive_macro_bias(closes_macro)
    print(f"Macro Bias: {macro_result.get('macro_bias')}")
    print(f"Structural Alignment: {macro_result.get('structural_alignment')}")
    gravity_result = vault_macro.get_reflective_gravity_score(closes_macro)
    print(f"Gravity Score: {gravity_result.get('gravity_score')}")

    # Test Volume Profile Analyzer
    print("\n📊 Testing Volume Profile Analyzer...")
    vol_analyzer = VolumeProfileAnalyzer()
    ohlcv_vol = [
        {
            "high": 100 + i * 0.1 + (i % 5) * 0.05,
            "low": 99 + i * 0.1,
            "close": 99.5 + i * 0.1,
            "volume": 1000 + (i % 10) * 100,
        }
        for i in range(60)
    ]
    vol_result = vol_analyzer.analyze(ohlcv_vol, "XAUUSD", "H4")
    print(f"POC Price: {vol_result.poc_price:.2f}")
    print(f"Profile Shape: {vol_result.profile_shape}")
    print(f"Volume Nodes: {len(vol_result.volume_nodes)}")

    # Test WLWCI Calculator
    print("\n⚙️ Testing WLWCI Calculator...")
    wlwci_result = calculate_wlwci(
        twms_macro=0.75,
        trend_fusion=0.68,
        twms_micro=0.15,
        volatility=0.25,
    )
    print(f"WLWCI: {wlwci_result['wlwci']}")
    print(f"Volatility Regime: {wlwci_result['volatility_regime']}")

    # Test RSI Alignment Engine
    print("\n📈 Testing RSI Alignment Engine...")
    rsi_result = rsi_alignment_engine(
        rsi_w1=63.2,
        rsi_d1=61.5,
        rsi_h4=57.9,
        rsi_h1=59.1,
    )
    print(f"Alignment Score: {rsi_result['alignment_score']}")
    print(f"Momentum Bias: {rsi_result['momentum_bias']}")
    print(f"Confidence: {rsi_result['confidence']}")

    # Test Smart Money Counter Zone
    print("\n💹 Testing Smart Money Counter Zone...")
    sm_result = smart_money_counter_v3_5_reflective(
        price=1.0875,
        vwap=1.0850,
        atr=0.0025,
        rsi=72.5,
        mfi=68.0,
        cci50=120.0,
        rsi_h4=65.0,
        trq_energy=1.2,
        reflective_intensity=1.1,
    )
    print(f"Status: {sm_result.get('status')}")
    print(f"Counter Zone: {sm_result.get('counter_zone')}")
    if sm_result.get('counter_zone'):
        print(f"Direction: {sm_result.get('type')}")
        print(f"Confidence: {sm_result.get('confidence')}")

    # Test Ultra Fusion Orchestrator
    print("\n🌐 Testing Ultra Fusion Orchestrator...")
    orchestrator = UltraFusionOrchestrator()
    orchestrator_prices = [1.0800 + i * 0.0002 for i in range(120)]
    orch_result = orchestrator.execute_pipeline(
        symbol="EURUSD",
        prices=orchestrator_prices,
        vwap_val=1.0860,
        atr_val=0.0018,
        reflex_strength=0.42,
        volatility=0.0015,
        rsi_val=62.3,
        ema50_val=1.0855,
        ema100_val=1.0839,
        rc_adjusted=0.76,
    )
    print(f"Symbol: {orch_result['symbol']}")
    print(f"EMA Direction: {orch_result['ema_layer'].get('direction')}")
    print(f"Propagation Index: {orch_result['reflective_layer'].get('propagation_index')}")

    # Test Micro Adapter
    print("\n🔌 Testing Micro Adapter...")
    adapter = MicroAdapter()
    micro_data = {"twms_micro": 0.25, "volatility": 0.28}
    normalized = adapter.normalize(micro_data, macro_direction=0.65)
    print(f"TWMS Micro (bounded): {normalized.twms_micro}")
    print(f"Volatility Regime: {normalized.regime.value}")
    print(f"Conflict Detected: {normalized.conflict_detected}")
    print(f"Is Valid: {normalized.is_valid}")

    # Test apply_to_wlwci
    wlwci_result = adapter.apply_to_wlwci(wlwci_base=0.72, normalized=normalized)
    print(f"WLWCI Adjusted: {wlwci_result['wlwci']}")

    # Test Quantum Reflective Engine
    print("\n⚛️ Testing Quantum Reflective Engine...")
    quantum_engine = QuantumReflectiveEngine()
    quantum_closes = [100 + i * 0.05 + (i % 10) * 0.02 for i in range(100)]
    qfield = quantum_engine.evaluate_reflective_entropy(quantum_closes)
    print(f"Alpha-Beta-Gamma: {qfield['alpha_beta_gamma']}")
    print(f"Reflective Energy: {qfield['reflective_energy']}")
    print(f"Flux State: {qfield['flux_state']}")

    # Test Hybrid Reflective Core
    print("\n🔮 Testing Hybrid Reflective Core...")
    hybrid_core = HybridReflectiveCore()
    hybrid_closes = [100 + i * 0.08 + (i % 15) * 0.03 for i in range(250)]
    hybrid_result = hybrid_core.integrate(hybrid_closes)
    print(f"Hybrid Bias: {hybrid_result['hybrid_bias']}")
    print(f"Hybrid Reflective Strength: {hybrid_result['hybrid_reflective_strength']}")
    print(f"Reflective Macro Coherence: {hybrid_result['reflective_macro_coherence']}")

    # Test Execution Status
    exec_status = hybrid_core.get_execution_status(hybrid_closes)
    print(f"Pseudo TII: {exec_status['pseudo_tii']}")
    print(f"Execution Decision: {exec_status['execution_decision']}")

    print("\n" + "=" * 60)
    print(f"✅ All {len(__all__)} components tested successfully! 🐺")
    """
    logger.info("CLI debug utility is disabled in production; run tests instead.")
