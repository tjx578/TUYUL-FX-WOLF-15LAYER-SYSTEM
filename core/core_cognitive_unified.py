"""

Core Cognitive Unified Engine — v7.4r∞ Production

Pipeline Coverage:
  L0  — Cognitive Snapshot   (RegimeClassifier, CognitiveState, CognitiveBias)
  L1  — Reflex Context       (ReflexEmotionCore, ReflexState)
  L5  — RGO Governance       (IntegrityEngine)
  L7  — Structural Judgement (SmartMoneyDetector, TWMSCalculator)
  L9  — Monte Carlo Prob.    (montecarlo_validate)
  L11 — Wolf Discipline      (EmotionFeedbackEngine, RiskFeedbackCalibrator)
  L13 — Adaptive Risk        (AdaptiveRiskCalculator, VaultRiskSync)

Production-ready implementation with full exception hierarchy,
comprehensive enums, working classes, and Monte Carlo validation.
"""

from __future__ import annotations

import json
import random
import statistics
import typing

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from pathlib import Path

# ─── Exception Hierarchy ──────────────────────────────────────────────────────

class CognitiveError(Exception):
    """Base exception for all cognitive module errors."""
    pass


class RiskCalculationError(CognitiveError):
    """Raised when risk calculations fail."""
    pass


class ValidationError(CognitiveError):
    """Raised when validation checks fail."""
    pass


class InvalidInputError(CognitiveError):
    """Raised when input parameters are invalid."""
    pass


class TradingError(CognitiveError):
    """Raised when trading-related errors occur."""
    pass


class RiskLimitExceeded(TradingError):
    """Raised when risk limits are exceeded."""
    pass


class VaultError(CognitiveError):
    """Base exception for vault operations."""
    pass


class VaultPathError(VaultError):
    """Raised when vault path is invalid or inaccessible."""
    pass


class CalibrationError(CognitiveError):
    """Raised when calibration operations fail."""
    pass


class EmotionFeedbackError(CognitiveError):
    """Raised when emotion feedback cycle fails."""
    pass


class TWMSCalculationError(CognitiveError):
    """Raised when TWMS calculation fails."""
    pass


class VaultPersistenceError(VaultError):
    """Raised when vault persistence operations fail."""
    pass


# ─── Constants ────────────────────────────────────────────────────────────────

COHERENCE_THRESHOLD: float = 0.90
INTEGRITY_MINIMUM: float = 0.88
REFLEX_GATE_PASS: float = 0.80

TWMS_WEIGHT_D1: float = 0.30
TWMS_WEIGHT_H4: float = 0.40
TWMS_WEIGHT_H1: float = 0.30

META_LEARNING_RATE: float = 0.015
META_RESILIENCE_INDEX: float = 0.93
META_RESONANCE_LIMIT: float = 0.95


# ─── Enums ────────────────────────────────────────────────────────────────────

class CognitiveBias(Enum):
    """L0 — Dominant cognitive bias."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    SIDEWAYS = "SIDEWAYS"


class MarketRegimeType(IntEnum):
    """L0 — Market regime classification (numeric)."""
    RANGE = 0
    TREND = 1
    EXPANSION = 2
    REVERSAL = 3


class MarketRegime(Enum):
    """L0 — Market regime classification (string-based)."""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING_HIGH = "ranging_high"
    RANGING_MID = "ranging_mid"
    RANGING_LOW = "ranging_low"
    TRANSITION_BULL = "transition_bull"
    TRANSITION_BEAR = "transition_bear"
    VOLATILE = "volatile"
    QUIET = "quiet"


class TrendStrength(Enum):
    """L0 — Trend strength classification."""
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NONE = "NONE"


class ReflexState(Enum):
    """L1 — Reflex synchronisation state."""
    SYNCED = "SYNCED"
    DESYNCED = "DESYNCED"
    LOCKOUT = "LOCKOUT"
    REVIEW = "REVIEW"


class ConfidenceLevel(Enum):
    """General confidence classification."""
    VERY_HIGH = "VERY_HIGH"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    VERY_LOW = "VERY_LOW"


class FusionMode(Enum):
    """Fusion operation mode."""
    STRICT = "STRICT"
    MODERATE = "MODERATE"
    LENIENT = "LENIENT"
    ADAPTIVE = "ADAPTIVE"


class ReflectivePhase(Enum):
    """Reflective process phase."""
    ANALYZING = "ANALYZING"
    SYNTHESIZING = "SYNTHESIZING"
    VALIDATING = "VALIDATING"
    COMPLETE = "COMPLETE"


class LayerID(Enum):
    """Pipeline layer identifiers."""
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"
    L6 = "L6"
    L7 = "L7"
    L8 = "L8"
    L9 = "L9"
    L10 = "L10"
    L11 = "L11"
    L12 = "L12"
    L13 = "L13"


class SmartMoneySignal(Enum):
    """L7 — Institutional activity signal."""
    ACCUMULATION = "ACCUMULATION"
    DISTRIBUTION = "DISTRIBUTION"
    NEUTRAL = "NEUTRAL"
    SWEEP = "SWEEP"
    MANIPULATION = "MANIPULATION"


class InstitutionalBias(Enum):
    """L7 — Institutional directional bias."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Timeframe(Enum):
    """Trading timeframes."""
    W1 = "W1"
    D1 = "D1"
    H4 = "H4"
    H1 = "H1"
    M15 = "M15"


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class CognitiveState:
    """L0 — Snapshot of cognitive / regime state."""
    timestamp: datetime
    twms_score: float
    risk_level: float
    emotion_index: float
    discipline_score: float
    confluence_count: int
    regime: MarketRegimeType = MarketRegimeType.RANGE


@dataclass(frozen=True)
class EmotionFeedbackCycle:
    """L11 — Output of EmotionFeedbackEngine.run_cycle()."""
    coherence: float
    emotion_delta: float
    gate: str
    psych_confidence: float


@dataclass(frozen=True)
class ReflexEmotionResult:
    """L1 — Output of ReflexEmotionCore.compute_reflex_emotion()."""
    reflex_coherence: float
    emotion_delta: float
    alignment: str
    gate: str
    reflex_state: ReflexState


@dataclass
class RegimeAnalysis:
    """L0 — Output of RegimeClassifier.classify()."""
    regime: MarketRegimeType
    trend_direction: str
    volatility_level: str
    regime_confidence: float
    regime_string: MarketRegime = MarketRegime.RANGING_MID
    trend_strength: TrendStrength = TrendStrength.NONE


@dataclass
class CalibrationSummary:
    """Calibration summary statistics."""
    last_calibration: datetime
    success_rate: float
    avg_adjustment: float
    iterations: int


@dataclass(slots=True)
class RiskAssessment:
    """Risk assessment result."""
    risk_level: float
    max_position_size: float
    recommended_stop: float
    risk_reward_ratio: float
    drawdown_factor: float


@dataclass
class AdaptiveRiskResult:
    """L13 — Adaptive risk calculation result."""
    recommended_lot: float
    risk_amount: float
    position_value: float
    drawdown_multiplier: float
    max_safe_lot: float
    risk_tier: str


@dataclass
class CalibrationResult:
    """Risk feedback calibration result."""
    calibrated_risk: float
    confidence: float
    adjustments: dict[str, float]
    recommendation: str


@dataclass
class SmartMoneyAnalysis:
    """L7 — Output of SmartMoneyDetector.analyze()."""
    signal: SmartMoneySignal
    bias: InstitutionalBias
    strength: float
    confidence: float
    manipulation_detected: bool = False
    liquidity_sweep: bool = False


@dataclass
class TWMSInput:
    """Input for TWMS calculation."""
    symbol: str
    d1_score: float
    h4_score: float
    h1_score: float
    component_scores: dict[str, float] = field(default_factory=dict)


@dataclass
class TWMSResult:
    """L7/L8 — Time-Weighted Multi-Score result v2.2."""
    twms_score: float
    d1_weight: float
    h4_weight: float
    h1_weight: float
    d1_contribution: float
    h4_contribution: float
    h1_contribution: float
    timestamp: datetime = field(default_factory=datetime.now)


# ─── L0: Cognitive Snapshot ───────────────────────────────────────────────────

class RegimeClassifier:
    """
    L0 — Classifies market regime.

    Production implementation with real regime detection logic.
    """

    def __init__(self) -> None:
        self.atr_threshold_low: float = 0.0005
        self.atr_threshold_high: float = 0.0015
        self.trend_threshold: float = 0.002

    def classify(
        self,
        symbol: str,
        timeframe: str = "H1",
        data: dict[str, typing.Any] | None = None
    ) -> RegimeAnalysis:
        """
        Classify market regime based on volatility and trend analysis.

        Args:
            symbol: Trading symbol
            timeframe: Analysis timeframe
            data: Market data (close, high, low, atr, etc.)

        Returns:
            RegimeAnalysis with detected regime
        """
        if data is None:
            data = {}

        close_prices = data.get("close", [100.0] * 20)
        data.get("high", [100.5] * 20)
        data.get("low", [99.5] * 20)
        atr = data.get("atr", 0.001)

        if len(close_prices) < 2:
            return RegimeAnalysis(
                regime=MarketRegimeType.RANGE,
                trend_direction="NEUTRAL",
                volatility_level="LOW",
                regime_confidence=0.5,
                regime_string=MarketRegime.RANGING_MID,
                trend_strength=TrendStrength.NONE
            )

        price_change = close_prices[-1] - close_prices[0]
        price_change_pct = abs(price_change / close_prices[0])

        if atr < self.atr_threshold_low:
            volatility = "LOW"
        elif atr < self.atr_threshold_high:
            volatility = "MEDIUM"
        else:
            volatility = "HIGH"

        if price_change_pct > self.trend_threshold:
            regime_type = MarketRegimeType.TREND
            trend_dir = "BULLISH" if price_change > 0 else "BEARISH"
            regime_str = MarketRegime.TRENDING_UP if price_change > 0 else MarketRegime.TRENDING_DOWN

            if price_change_pct > self.trend_threshold * 2:
                trend_str = TrendStrength.STRONG
            elif price_change_pct > self.trend_threshold * 1.5:
                trend_str = TrendStrength.MODERATE
            else:
                trend_str = TrendStrength.WEAK

            confidence = min(0.95, 0.6 + price_change_pct * 50)

        elif atr > self.atr_threshold_high:
            regime_type = MarketRegimeType.EXPANSION
            trend_dir = "NEUTRAL"
            regime_str = MarketRegime.VOLATILE
            trend_str = TrendStrength.NONE
            confidence = 0.7 + min(0.25, atr * 100)

        else:
            regime_type = MarketRegimeType.RANGE
            trend_dir = "NEUTRAL"

            avg_price = statistics.mean(close_prices[-10:])
            if close_prices[-1] > avg_price * 1.002:
                regime_str = MarketRegime.RANGING_HIGH
            elif close_prices[-1] < avg_price * 0.998:
                regime_str = MarketRegime.RANGING_LOW
            else:
                regime_str = MarketRegime.RANGING_MID

            trend_str = TrendStrength.NONE
            confidence = 0.65 + (1 - price_change_pct * 100) * 0.2

        return RegimeAnalysis(
            regime=regime_type,
            trend_direction=trend_dir,
            volatility_level=volatility,
            regime_confidence=max(0.0, min(1.0, confidence)),
            regime_string=regime_str,
            trend_strength=trend_str
        )


# ─── L1: Reflex Context ──────────────────────────────────────────────────────

class ReflexEmotionCore:
    """
    L1 — Computes reflex-emotion coherence.

    Production implementation with real coherence calculations.
    """

    def __init__(self) -> None:
        self.baseline_emotion: float = 0.5
        self.coherence_history: list[float] = []

    def compute_reflex_emotion(
        self,
        market_data: dict[str, typing.Any]
    ) -> ReflexEmotionResult:
        """
        Compute reflex-emotion coherence and alignment.

        Args:
            market_data: Market state data (volatility, momentum, etc.)

        Returns:
            ReflexEmotionResult with coherence and state
        """
        volatility = market_data.get("volatility", 0.01)
        momentum = market_data.get("momentum", 0.0)
        volume_ratio = market_data.get("volume_ratio", 1.0)

        reflex_signal = (momentum * 0.4 + (volume_ratio - 1.0) * 0.3 +
                        (1.0 - volatility * 50) * 0.3)
        reflex_signal = max(-1.0, min(1.0, reflex_signal))

        emotion_signal = self.baseline_emotion + reflex_signal * 0.3
        emotion_signal = max(0.0, min(1.0, emotion_signal))

        delta = abs(reflex_signal - (emotion_signal - self.baseline_emotion))
        coherence = 1.0 - delta

        self.coherence_history.append(coherence)
        if len(self.coherence_history) > 100:
            self.coherence_history.pop(0)

        avg_coherence = statistics.mean(self.coherence_history[-20:])

        if coherence >= REFLEX_GATE_PASS and avg_coherence >= REFLEX_GATE_PASS:
            state = ReflexState.SYNCED
            gate = "OPEN"
            alignment = "ALIGNED"
        elif coherence >= REFLEX_GATE_PASS * 0.8:
            state = ReflexState.REVIEW
            gate = "CONDITIONAL"
            alignment = "PARTIAL"
        elif avg_coherence < REFLEX_GATE_PASS * 0.6:
            state = ReflexState.LOCKOUT
            gate = "LOCKED"
            alignment = "MISALIGNED"
        else:
            state = ReflexState.DESYNCED
            gate = "CLOSED"
            alignment = "NEUTRAL"

        return ReflexEmotionResult(
            reflex_coherence=coherence,
            emotion_delta=delta,
            alignment=alignment,
            gate=gate,
            reflex_state=state
        )


# ─── L5: RGO Governance ───────────────────────────────────────────────────────

class IntegrityEngine:
    """
    L5 — Verifies system-state integrity.


    Production implementation with real verification logic.
    """

    def __init__(self) -> None:
        self.snapshots: list[dict[str, typing.Any]] = []
        self.last_verification: datetime | None = None
        self.coherence_score: float = 1.0
    def evaluate_coherence(
        self,
        fusion_conf: float = 0.0,
        wlwci: float = 0.0,
        rcadj: float = 0.0
    ) -> float:
        """
        Evaluate overall system coherence.
        Returns:
            Coherence score [0.0, 1.0]
        """
        components = [fusion_conf, wlwci, rcadj]
        valid_components = [c for c in components if 0.0 <= c <= 1.0]

        if not valid_components:
            return 0.0

        coherence = statistics.mean(valid_components)
        variance = statistics.stdev(valid_components) if len(valid_components) > 1 else 0.0

        coherence_adjusted = coherence * (1.0 - variance * 0.5)
        self.coherence_score = max(0.0, min(1.0, coherence_adjusted))

        return self.coherence_score

    def validate_integrity(
        self,
        fusion_conf: float,
        wlwci: float,
        rcadj: float,
        ree_integrity: float
    ) -> bool:
        """
        Validate system integrity against thresholds.

        Returns:
            True if integrity checks pass
        """
        coherence = self.evaluate_coherence(fusion_conf, wlwci, rcadj)

        integrity_pass = (
            coherence >= COHERENCE_THRESHOLD and
            ree_integrity >= INTEGRITY_MINIMUM and
            fusion_conf >= 0.75 and
            wlwci >= 0.70
        )

        return integrity_pass

    def save_snapshot(
        self,
        state: dict[str, typing.Any]
    ) -> None:
        """Save system state snapshot."""
        snapshot = {
            "timestamp": datetime.now().isoformat(),  # noqa: DTZ005
            "coherence": self.coherence_score,
            **state
        }
        self.snapshots.append(snapshot)

        if len(self.snapshots) > 1000:

            self.new_method()

    def new_method(self):
        self.snapshots = self.snapshots[-500:]

    def verify_system_state(
        self,
        fusion_conf: float = 0.0,
        wlwci: float = 0.0,
        rcadj: float = 0.0,
        ree_integrity: float = 0.0,
    ) -> dict[str, typing.Any]:
        """
        Comprehensive system state verification.

        Returns:
            Verification result with status and metrics
        """
        self.last_verification = datetime.now()  # noqa: DTZ005

        coherence = self.evaluate_coherence(fusion_conf, wlwci, rcadj)
        is_valid = self.validate_integrity(fusion_conf, wlwci, rcadj, ree_integrity)

        result = {
            "timestamp": self.last_verification.isoformat(),
            "status": "STABLE" if is_valid else "DEGRADED",
            "coherence": coherence,
            "integrity_pass": is_valid,
            "metrics": {
                "fusion_confidence": fusion_conf,
                "wlwci": wlwci,
                "rcadj": rcadj,
                "ree_integrity": ree_integrity
            },
            "thresholds": {
                "coherence": COHERENCE_THRESHOLD,
                "integrity": INTEGRITY_MINIMUM
            }
        }

        self.save_snapshot(result)

        return result

    def is_stable(self) -> bool:
        """
        Check if system is currently stable.

        Returns:
            True if system is stable
        """
        if not self.snapshots:
            return False

        recent = self.snapshots[-5:] if len(self.snapshots) >= 5 else self.snapshots

        stable_count = sum(1 for s in recent if s.get("status") == "STABLE")
        stability_ratio = stable_count / len(recent)

        return stability_ratio >= 0.8 and self.coherence_score >= COHERENCE_THRESHOLD


# ─── L7: Structural Judgement ─────────────────────────────────────────────────

class SmartMoneyDetector:
    """
    L7 — Detects institutional / smart-money activity.

    Production implementation with real detection algorithms.
    """

    def __init__(self) -> None:
        self.volume_threshold: float = 1.5
        self.sweep_threshold: float = 0.003

    def analyze(
        self,
        symbol: str,
        timeframe: str = "H1",
        data: dict[str, typing.Any] | None = None
    ) -> SmartMoneyAnalysis:
        """
        Analyze institutional activity and bias.

        Args:
            symbol: Trading symbol
            timeframe: Analysis timeframe
            data: Market data (volume, price action, etc.)

        Returns:
            SmartMoneyAnalysis with detected signals
        """
        if data is None:
            data = {}

        volume = data.get("volume", [1.0] * 20)
        close = data.get("close", [100.0] * 20)
        high = data.get("high", [100.5] * 20)
        low = data.get("low", [99.5] * 20)

        if len(volume) < 5 or len(close) < 5:
            return SmartMoneyAnalysis(
                signal=SmartMoneySignal.NEUTRAL,
                bias=InstitutionalBias.NEUTRAL,
                strength=0.0,
                confidence=0.5
            )

        avg_volume = statistics.mean(volume[-20:])
        recent_volume = statistics.mean(volume[-5:])
        volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1.0

        price_change = (close[-1] - close[-5]) / close[-5]

        high_breaks = sum(1 for i in range(-5, -1) if high[i] > high[i-1])
        low_breaks = sum(1 for i in range(-5, -1) if low[i] < low[i-1])

        liquidity_sweep = False
        if abs(high[-1] - high[-2]) / high[-2] > self.sweep_threshold:
            liquidity_sweep = True

        manipulation_detected = False
        if volume_ratio > 2.0 and abs(price_change) < 0.001:
            manipulation_detected = True

        if volume_ratio > self.volume_threshold:
            if price_change > 0.001:
                signal = SmartMoneySignal.ACCUMULATION
                bias = InstitutionalBias.BULLISH
                strength = min(1.0, volume_ratio / 3.0)
            elif price_change < -0.001:
                signal = SmartMoneySignal.DISTRIBUTION
                bias = InstitutionalBias.BEARISH
                strength = min(1.0, volume_ratio / 3.0)
            else:
                if manipulation_detected:
                    signal = SmartMoneySignal.MANIPULATION
                else:
                    signal = SmartMoneySignal.NEUTRAL
                bias = InstitutionalBias.NEUTRAL
                strength = 0.5
        elif liquidity_sweep:
            signal = SmartMoneySignal.SWEEP
            bias = InstitutionalBias.BULLISH if high_breaks > low_breaks else InstitutionalBias.BEARISH
            strength = 0.6
        else:
            signal = SmartMoneySignal.NEUTRAL
            bias = InstitutionalBias.NEUTRAL
            strength = 0.3

        confidence = 0.5 + min(0.45, strength * 0.6 + volume_ratio * 0.2)

        return SmartMoneyAnalysis(
            signal=signal,
            bias=bias,
            strength=strength,
            confidence=confidence,
            manipulation_detected=manipulation_detected,
            liquidity_sweep=liquidity_sweep
        )


class TWMSCalculator:
    """
    L7/L8 — Time-Weighted Multi-Score calculator v2.2.

    Production implementation: D1:30%, H4:40%, H1:30% weighting.
    """

    def __init__(self) -> None:
        self.d1_weight = TWMS_WEIGHT_D1
        self.h4_weight = TWMS_WEIGHT_H4
        self.h1_weight = TWMS_WEIGHT_H1

    def calculate(
        self,
        symbol: str,
        timeframes: list[str] | None = None,
        component_scores: dict[str, float] | None = None
    ) -> TWMSResult:
        """
        Calculate Time-Weighted Multi-Score.

        Args:
            symbol: Trading symbol
            timeframes: Timeframes to analyze (default: ["D1", "H4", "H1"])
            component_scores: Pre-calculated scores per timeframe

        Returns:
            TWMSResult with weighted score

        Raises:
            TWMSCalculationError: If calculation fails
        """
        if component_scores is None:
            component_scores = {}

        if timeframes is None:
            timeframes = ["D1", "H4", "H1"]

        d1_score = component_scores.get("D1", 0.0)
        h4_score = component_scores.get("H4", 0.0)
        h1_score = component_scores.get("H1", 0.0)

        if not all(0.0 <= s <= 1.0 for s in [d1_score, h4_score, h1_score]):
            raise TWMSCalculationError(
                f"Component scores must be in range [0.0, 1.0]: "
                f"D1={d1_score}, H4={h4_score}, H1={h1_score}"
            )

        d1_contrib = d1_score * self.d1_weight
        h4_contrib = h4_score * self.h4_weight
        h1_contrib = h1_score * self.h1_weight

        twms = d1_contrib + h4_contrib + h1_contrib

        return TWMSResult(
            twms_score=twms,
            d1_weight=self.d1_weight,
            h4_weight=self.h4_weight,
            h1_weight=self.h1_weight,
            d1_contribution=d1_contrib,
            h4_contribution=h4_contrib,
            h1_contribution=h1_contrib,
            timestamp=datetime.now()  # noqa: DTZ005
        )


# ─── L9: Monte Carlo Probability ─────────────────────────────────────────────

def montecarlo_validate(
    returns: list[float],
    iterations: int = 5000,
    confidence_level: float = 0.95
) -> dict[str, typing.Any]:
    """
    L9 — Monte Carlo validation with bootstrap simulation.

    Production implementation with deterministic bootstrap,
    Sharpe ratio, max drawdown, VaR, and Expected Shortfall.

    Args:
        returns: Historical returns list
        iterations: Number of Monte Carlo iterations
        confidence_level: Confidence level for VaR/ES (default: 0.95)

    Returns:
        dict with statistical metrics:
            - mean_return: Average return
            - sharpe_ratio: Risk-adjusted return
            - max_drawdown: Maximum drawdown
            - win_probability: Probability of positive return
            - value_at_risk: Value at Risk (VaR)
            - expected_shortfall: Expected Shortfall (CVaR)

    Raises:
        InvalidInputError: If returns list is empty or invalid
    """
    if not returns or len(returns) < 2:
        raise InvalidInputError("Returns list must contain at least 2 values")
    if iterations < 100:
        raise InvalidInputError("Iterations must be at least 100")

    simulated_returns: list[float] = []
    simulated_drawdowns: list[float] = []

    random.seed(42)

    for _ in range(iterations):
        sample = random.choices(returns, k=len(returns))

        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0

        for ret in sample:
            cumulative += ret
            peak = max(peak, cumulative)
            drawdown = peak - cumulative
            max_dd = max(max_dd, drawdown)

        simulated_returns.append(cumulative)
        simulated_drawdowns.append(max_dd)

    mean_return = statistics.mean(simulated_returns)
    std_return = statistics.stdev(simulated_returns) if len(simulated_returns) > 1 else 0.0

    sharpe_ratio = mean_return / std_return if std_return > 0 else 0.0

    max_drawdown = statistics.mean(simulated_drawdowns)

    positive_returns = sum(1 for r in simulated_returns if r > 0)
    win_probability = positive_returns / len(simulated_returns)

    sorted_returns = sorted(simulated_returns)
    var_index = int((1 - confidence_level) * len(sorted_returns))
    value_at_risk = abs(sorted_returns[var_index])

    tail_returns = sorted_returns[:var_index + 1]
    expected_shortfall = abs(statistics.mean(tail_returns)) if tail_returns else 0.0

    return {
        "mean_return": mean_return,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_drawdown,
        "win_probability": win_probability,
        "value_at_risk": value_at_risk,
        "expected_shortfall": expected_shortfall,
        "iterations": iterations,
        "confidence_level": confidence_level
    }


# ─── L11: Wolf Discipline (Emotion & Calibration) ────────────────────────────

class EmotionFeedbackEngine:
    """
    L11 — Emotion feedback cycle for discipline advisory.

    Production implementation with real coherence computation.
    """

    def __init__(self) -> None:
        self.baseline_coherence: float = 0.85
        self.emotion_memory: list[float] = []

    def run_cycle(
        self,
        current_state: dict[str, typing.Any],
        historical_performance: dict[str, typing.Any] | None = None
    ) -> EmotionFeedbackCycle:
        """
        Run emotion feedback cycle.

        Args:
            current_state: Current market/trading state
            historical_performance: Recent performance metrics

        Returns:
            EmotionFeedbackCycle with coherence and gate status

        Raises:
            EmotionFeedbackError: If cycle computation fails
        """
        if historical_performance is None:
            historical_performance = {}

        try:
            win_rate = historical_performance.get("win_rate", 0.5)
            recent_pnl = historical_performance.get("recent_pnl", 0.0)
            consecutive_losses = historical_performance.get("consecutive_losses", 0)

            market_volatility = current_state.get("volatility", 0.01)

            current_state.get("exposure", 0.0)

            emotion_signal = (
                win_rate * 0.3 +
                (1.0 if recent_pnl > 0 else 0.3) * 0.2 +
                max(0.0, 1.0 - consecutive_losses * 0.15) * 0.3 +
                (1.0 - min(1.0, market_volatility * 50)) * 0.2
            )

            self.emotion_memory.append(emotion_signal)
            if len(self.emotion_memory) > 50:
                self.emotion_memory.pop(0)

            avg_emotion = statistics.mean(self.emotion_memory[-10:])
            emotion_delta = abs(emotion_signal - avg_emotion)

            coherence = self.baseline_coherence * (1.0 - emotion_delta * 0.5)
            coherence = max(0.0, min(1.0, coherence))

            if coherence >= 0.85 and consecutive_losses < 3:
                gate = "OPEN"
                psych_confidence = 0.9
            elif coherence >= 0.75:
                gate = "CONDITIONAL"
                psych_confidence = 0.7
            else:
                gate = "CLOSED"
                psych_confidence = 0.4

            return EmotionFeedbackCycle(
                coherence=coherence,
                emotion_delta=emotion_delta,
                gate=gate,
                psych_confidence=psych_confidence
            )

        except Exception as e:
            raise EmotionFeedbackError(f"Emotion feedback cycle failed: {e}") from e


class RiskFeedbackCalibrator:
    """
    L11 — Risk feedback calibration system.

    Calibrates risk parameters based on performance feedback.
    """

    def __init__(self) -> None:
        self.learning_rate = META_LEARNING_RATE
        self.calibration_history: list[dict[str, typing.Any]] = []

    def calibrate(
        self,
        base_risk: float,
        performance_metrics: dict[str, float]
    ) -> CalibrationResult:
        """
        Calibrate risk parameters based on performance.

        Args:
            base_risk: Base risk percentage
            performance_metrics: Recent performance data

        Returns:
            CalibrationResult with adjusted risk

        Raises:
            CalibrationError: If calibration fails
        """
        if not 0.0 <= base_risk <= 1.0:
            raise CalibrationError(f"Base risk must be in [0.0, 1.0]: {base_risk}")

        win_rate = performance_metrics.get("win_rate", 0.5)
        profit_factor = performance_metrics.get("profit_factor", 1.0)
        sharpe = performance_metrics.get("sharpe", 0.0)

        performance_score = (
            win_rate * 0.3 +
            min(1.0, profit_factor / 2.0) * 0.4 +
            min(1.0, max(0.0, sharpe / 2.0)) * 0.3
        )

        adjustment = (performance_score - 0.5) * self.learning_rate
        calibrated_risk = base_risk * (1.0 + adjustment)
        calibrated_risk = max(0.005, min(0.05, calibrated_risk))

        confidence = 0.5 + min(0.45, abs(adjustment) * 10)

        if performance_score > 0.7:
            recommendation = "INCREASE_EXPOSURE"
        elif performance_score < 0.3:
            recommendation = "REDUCE_EXPOSURE"
        else:
            recommendation = "MAINTAIN"

        adjustments = {
            "performance_score": performance_score,
            "adjustment_factor": adjustment,
            "original_risk": base_risk,
            "calibrated_risk": calibrated_risk
        }

        self.calibration_history.append({
            "timestamp": datetime.now().isoformat(),  # noqa: DTZ005
            **adjustments
        })

        return CalibrationResult(
            calibrated_risk=calibrated_risk,
            confidence=confidence,
            adjustments=adjustments,
            recommendation=recommendation
        )


# ─── L13: Adaptive Risk ──────────────────────────────────────────────────────

class AdaptiveRiskCalculator:
    """
    L13 — Adaptive risk / position-sizing calculator.

    Production implementation with 5-tier drawdown system:
      0-5%: 100% (1.00)
      5-10%: 80% (0.80)
      10-15%: 60% (0.60)
      15-20%: 40% (0.40)
      >20%: 20% (0.20)
    """

    def __init__(self) -> None:
        self.drawdown_tiers = [
            (0.05, 1.00, "TIER_0"),
            (0.10, 0.80, "TIER_1"),
            (0.15, 0.60, "TIER_2"),
            (0.20, 0.40, "TIER_3"),
            (float('inf'), 0.20, "TIER_4")
        ]

    def calculate(
        self,
        base_risk: float,
        drawdown: float,
        balance: float,
        entry_price: float,
        stop_loss: float
    ) -> AdaptiveRiskResult:
        """
        Calculate adaptive risk-adjusted position size.

        Args:
            base_risk: Base risk percentage (e.g., 0.02 for 2%)
            drawdown: Current drawdown percentage (e.g., 0.08 for 8%)
            balance: Account balance
            entry_price: Entry price
            stop_loss: Stop loss price

        Returns:
            AdaptiveRiskResult with position sizing

        Raises:
            RiskCalculationError: If calculation fails
        """
        if base_risk <= 0 or base_risk > 0.1:
            raise RiskCalculationError(f"Base risk must be in (0.0, 0.1]: {base_risk}")

        if balance <= 0:
            raise RiskCalculationError(f"Balance must be positive: {balance}")

        if entry_price <= 0 or stop_loss <= 0:
            raise RiskCalculationError("Entry and stop loss must be positive")

        if abs(entry_price - stop_loss) < 1e-6:
            raise RiskCalculationError("Entry and stop loss cannot be equal")

        drawdown_multiplier = 1.00
        risk_tier = "TIER_0"

        for threshold, multiplier, tier in self.drawdown_tiers:
            if drawdown < threshold:
                drawdown_multiplier = multiplier
                risk_tier = tier
                break

        adjusted_risk = base_risk * drawdown_multiplier
        risk_amount = balance * adjusted_risk

        stop_distance = abs(entry_price - stop_loss)

        if stop_distance < 1e-6:
            raise RiskCalculationError("Stop distance too small")

        recommended_lot = risk_amount / stop_distance

        max_risk = balance * 0.05
        max_safe_lot = max_risk / stop_distance

        position_value = recommended_lot * entry_price

        return AdaptiveRiskResult(
            recommended_lot=recommended_lot,
            risk_amount=risk_amount,
            position_value=position_value,
            drawdown_multiplier=drawdown_multiplier,
            max_safe_lot=max_safe_lot,
            risk_tier=risk_tier
        )


class VaultRiskSync:
    """
    L13 — Vault persistence for risk parameters.

    Handles loading/saving risk configurations to vault.
    """

    def __init__(self, vault_path: Path | str | None = None) -> None:
        if vault_path is None:
            vault_path = Path.home() / ".wolf15" / "vault" / "risk"

        self.vault_path = Path(vault_path)
        self._ensure_vault_exists()

    def _ensure_vault_exists(self) -> None:
        """Ensure vault directory exists."""
        try:
            self.vault_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise VaultPathError(f"Cannot create vault path {self.vault_path}: {e}") from e

    def save_risk_config(
        self,
        config: dict[str, typing.Any],
        config_name: str = "default"
    ) -> None:
        """
        Save risk configuration to vault.

        Args:
            config: Risk configuration dict
            config_name: Configuration name

        Raises:
            VaultPersistenceError: If save fails
        """
        try:
            file_path = self.vault_path / f"{config_name}_risk.json"

            with open(file_path, 'w') as f:
                json.dump(config, f, indent=2, default=str)

        except Exception as e:
            raise VaultPersistenceError(f"Failed to save risk config: {e}") from e

    def load_risk_config(
        self,
        config_name: str = "default"
    ) -> dict[str, typing.Any]:
        """
        Load risk configuration from vault.

        Args:
            config_name: Configuration name

        Returns:
            Risk configuration dict

        Raises:
            VaultPersistenceError: If load fails
        """
        try:
            file_path = self.vault_path / f"{config_name}_risk.json"

            if not file_path.exists():
                return {}

            with open(file_path ) as f:
                return json.load(f)

        except Exception as e:
            raise VaultPersistenceError(f"Failed to load risk config: {e}") from e


# ─── Helper Functions ─────────────────────────────────────────────────────────

def compute_reflex_emotion(
    volatility: float,
    momentum: float,
    volume_ratio: float = 1.0
) -> float:
    """
    Compute reflex-emotion signal.

    Args:
        volatility: Market volatility
        momentum: Price momentum
        volume_ratio: Volume ratio vs average

    Returns:
        Reflex emotion score [-1.0, 1.0]
    """
    signal = (momentum * 0.4 + (volume_ratio - 1.0) * 0.3 +
             (1.0 - volatility * 50) * 0.3)
    return max(-1.0, min(1.0, signal))


def reflex_check(
    coherence: float,
    threshold: float = REFLEX_GATE_PASS
) -> bool:
    """
    Check if reflex coherence passes gate threshold.

    Args:
        coherence: Coherence score
        threshold: Gate threshold (default: REFLEX_GATE_PASS)

    Returns:
        True if coherence passes threshold
    """
    return coherence >= threshold


def calculate_risk(
    balance: float,
    risk_percent: float,
    entry: float,
    stop: float
) -> float:
    """
    Calculate position size based on risk parameters.

    Args:
        balance: Account balance
        risk_percent: Risk percentage
        entry: Entry price
        stop: Stop loss price

    Returns:
        Position size (lot size)

    Raises:
        RiskCalculationError: If calculation invalid
    """
    if balance <= 0:
        raise RiskCalculationError("Balance must be positive")

    if not 0.0 < risk_percent <= 0.1:
        raise RiskCalculationError("Risk percent must be in (0.0, 0.1]")

    risk_amount = balance * risk_percent
    stop_distance = abs(entry - stop)

    if stop_distance < 1e-6:
        raise RiskCalculationError("Stop distance too small")

    return risk_amount / stop_distance


def calibrate_risk(
    base_risk: float,
    win_rate: float,
    profit_factor: float
) -> float:
    """
    Calibrate risk based on performance.

    Args:
        base_risk: Base risk percentage
        win_rate: Historical win rate
        profit_factor: Profit factor

    Returns:
        Calibrated risk percentage
    """
    performance_score = win_rate * 0.5 + min(1.0, profit_factor / 2.0) * 0.5
    adjustment = (performance_score - 0.5) * META_LEARNING_RATE

    calibrated = base_risk * (1.0 + adjustment)
    return max(0.005, min(0.05, calibrated))


def calculate_confluence_score(
    signals: list[bool],
    weights: list[float] | None = None
) -> float:
    """
    Calculate confluence score from multiple signals.

    Args:
        signals: List of boolean signals
        weights: Optional weights for each signal

    Returns:
        Confluence score [0.0, 1.0]
    """
    if not signals:
        return 0.0

    if weights is None:
        weights = [1.0] * len(signals)

    if len(weights) != len(signals):
        weights = [1.0] * len(signals)

    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0

    weighted_sum = sum(w for s, w in zip(signals, weights, strict=False) if s)

    return weighted_sum / total_weight


def validate_cognitive_thresholds(
    coherence: float,
    integrity: float
) -> bool:
    """
    Validate cognitive thresholds.

    Args:
        coherence: Coherence score
        integrity: Integrity score

    Returns:
        True if thresholds pass
    """
    return (coherence >= COHERENCE_THRESHOLD and
            integrity >= INTEGRITY_MINIMUM)


def calculate_risk_adjusted_score(
    base_score: float,
    risk_factor: float,
    confidence: float
) -> float:
    """
    Calculate risk-adjusted score.

    Args:
        base_score: Base score
        risk_factor: Risk adjustment factor
        confidence: Confidence level

    Returns:
        Risk-adjusted score
    """
    adjusted = base_score * (1.0 - risk_factor * 0.3) * confidence
    return max(0.0, min(1.0, adjusted))


# ─── Exports ──────────────────────────────────────────────────────────────────

__all__ = [
    # Constants
    "COHERENCE_THRESHOLD",
    "INTEGRITY_MINIMUM",
    "META_LEARNING_RATE",
    "META_RESILIENCE_INDEX",
    "META_RESONANCE_LIMIT",
    "REFLEX_GATE_PASS",
    "TWMS_WEIGHT_D1",
    "TWMS_WEIGHT_H1",
    "TWMS_WEIGHT_H4",
    "AdaptiveRiskCalculator",
    "AdaptiveRiskResult",
    "CalibrationError",
    "CalibrationResult",
    "CalibrationSummary",
    # Enums
    "CognitiveBias",
    # Exceptions
    "CognitiveError",
    # Dataclasses
    "CognitiveState",
    "ConfidenceLevel",
    "EmotionFeedbackCycle",
    "EmotionFeedbackEngine",
    "EmotionFeedbackError",
    "FusionMode",
    "InstitutionalBias",
    "IntegrityEngine",
    "InvalidInputError",
    "LayerID",
    "MarketRegime",
    "MarketRegimeType",
    "ReflectivePhase",
    "ReflexEmotionCore",
    "ReflexEmotionResult",
    "ReflexState",
    "RegimeAnalysis",
    # Classes
    "RegimeClassifier",
    "RiskAssessment",
    "RiskCalculationError",
    "RiskFeedbackCalibrator",
    "RiskLimitExceeded",
    "SmartMoneyAnalysis",
    "SmartMoneyDetector",
    "SmartMoneySignal",
    "TWMSCalculationError",
    "TWMSCalculator",
    "TWMSInput",
    "TWMSResult",
    "Timeframe",
    "TradingError",
    "TrendStrength",
    "ValidationError",
    "VaultError",
    "VaultPathError",
    "VaultPersistenceError",
    "VaultRiskSync",
    "calculate_confluence_score",
    "calculate_risk",
    "calculate_risk_adjusted_score",
    "calibrate_risk",
    "compute_reflex_emotion",
    # Functions
    "montecarlo_validate",
    "reflex_check",
    "validate_cognitive_thresholds",
]
