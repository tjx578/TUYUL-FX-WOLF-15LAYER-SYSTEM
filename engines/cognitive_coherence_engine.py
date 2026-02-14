"""Cognitive coherence engine for emotional integrity and state assessment.

This module provides trader psychological state evaluation WITHOUT execution authority.
All state values are input metrics for Layer-12 (constitution), not enforcement decisions.
"""
"""Cognitive coherence engine (analysis-only)."""
"""Cognitive coherence engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import fmean, pstdev
from typing import Any


@dataclass
class CoherenceResult:
    coherence_index: float
    stress_score: float
    emotion_delta: float
    gate: str
"""Cognitive coherence engine for emotional integrity and gating."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict
import math


@dataclass
class CoherenceResult:
    valid: bool
    coherence_index: float
    emotion_delta: float
    stress_score: float
    gate: str
    baseline_emotion: float
    volatility_adjustment: float
from enum import Enum
from statistics import pstdev
from typing import Any, Deque, Dict


class CoherenceGate(str, Enum):
    PASS = "PASS"
"""Cognitive coherence engine with adaptive baseline and gate logic."""

import math

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from statistics import pstdev
from typing import Any


class CoherenceState(str, Enum):
    """Trader psychological coherence state levels.

    These are assessment states, not gate decisions. Layer-12 (constitution) makes
    the final execution decision based on these and other inputs.
    """

    PASS = "PASS"  # noqa: S105
    REVIEW = "REVIEW"
    LOCKOUT = "LOCKOUT"


@dataclass
class CoherenceSnapshot:
    coherence_index: float
    emotion_delta: float
    emotion_volatility: float
    stress_score: float
    gate: CoherenceState  # 'gate' for backward compatibility; represents state assessment
    details: dict[str, Any] = field(default_factory=dict)


class CognitiveCoherenceEngine:
    """Tracks trader-state coherence and emits psychological state assessment.

    This engine maintains internal state across evaluations through instance variables:
    - emotion_baseline: Adaptive baseline for emotion tracking
    - coherence_state: Smoothed coherence index
    - emotion_history: Rolling window of emotion values

    **Thread Safety**: This engine is NOT thread-safe. Multiple concurrent calls to
    evaluate() could cause race conditions when updating shared state.

    **Reusability**: Engine instances should not be shared across different trading
    symbols or contexts. Create separate instances for each context.

    **State Management**: Call reset() to clear accumulated state when starting a new
    trading session or switching contexts.

    **Authority Boundaries**: This engine provides INPUT METRICS for Layer-12 decisions.
    It does NOT have execution authority. The state values (PASS/REVIEW/LOCKOUT) are
    assessments of trader psychological coherence, not trading permissions.
    """
    """Tracks behavioral coherence and provides non-execution gate status."""

    def __init__(
        self,
        alpha: float = 0.25,
        history_size: int = 40,
        baseline_alpha: float = 0.07,
    ) -> None:
        self.alpha = alpha
        self.baseline_alpha = baseline_alpha
        self._coherence_ema = 0.8
        self._emotion_baseline = 0.5
        self._history: Deque[float] = deque(maxlen=history_size)

    def evaluate(self, state: Dict[str, Any]) -> CoherenceResult:
        emotion = float(state.get("emotion_level", 0.5))
        loss_stress = float(state.get("loss_stress", 0.0))
        fatigue = float(state.get("fatigue", 0.0))
        market_volatility = float(state.get("market_volatility", 0.2))

        self._history.append(emotion)
        self._emotion_baseline = (
            (1.0 - self.baseline_alpha) * self._emotion_baseline
            + self.baseline_alpha * emotion
        )

        emotion_delta = abs(emotion - self._emotion_baseline)
        emotion_vol = self._stdev(self._history)

        stress_score = min(
            1.0,
            emotion_vol * 0.4 + self._clamp01(loss_stress) * 0.35 + self._clamp01(fatigue) * 0.25,
        )

        raw_coherence = 1.0 - (emotion_delta * 0.6 + stress_score * 0.4)
        self._coherence_ema = (1.0 - self.alpha) * self._coherence_ema + self.alpha * raw_coherence
        coherence = self._clamp01(self._coherence_ema)

        vol_adj = 0.06 if market_volatility > 0.75 else 0.03 if market_volatility > 0.5 else 0.0
        pass_th = 0.77 + vol_adj
        review_th = 0.62 + vol_adj

        gate = "PASS"
        if coherence < review_th:
            gate = "LOCKOUT"
        elif coherence < pass_th:
            gate = "REVIEW"

        return CoherenceResult(
            valid=True,
            coherence_index=round(coherence, 4),
            emotion_delta=round(emotion_delta, 4),
            stress_score=round(stress_score, 4),
            gate=gate,
            baseline_emotion=round(self._emotion_baseline, 4),
            volatility_adjustment=vol_adj,
            details={
                "emotion_volatility": round(emotion_vol, 4),
                "history_samples": len(self._history),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, value))

    @staticmethod
    def _stdev(values: Deque[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return math.sqrt(variance)
    """Tracks trader-state coherence and emits non-execution safety gate."""

    def __init__(
        self,
        smoothing_alpha: float = 0.25,
        baseline_alpha: float = 0.12,
        history_size: int = 64,
    ) -> None:
        self.smoothing_alpha = smoothing_alpha
        self.baseline_alpha = baseline_alpha
        self._emotion_baseline = 0.0
        self._coherence_state = 0.8
        self._emotion_history: deque[float] = deque(maxlen=history_size)

    def evaluate(self, state: dict[str, Any], market_volatility: float = 0.0) -> CoherenceSnapshot:
        emotion = float(state.get("emotion_state", 0.0))
        fatigue = max(0.0, min(1.0, float(state.get("fatigue", 0.0))))
        loss_stress = max(0.0, min(1.0, float(state.get("loss_stress", 0.0))))

        self._emotion_baseline = (
            1 - self.baseline_alpha
        ) * self._emotion_baseline + self.baseline_alpha * emotion
        emotion_delta = abs(emotion - self._emotion_baseline)

        self._emotion_history.append(emotion)
        emotion_vol = pstdev(self._emotion_history) if len(self._emotion_history) > 2 else 0.0
        stress_score = min(1.0, emotion_vol * 0.4 + loss_stress * 0.35 + fatigue * 0.25)

        instantaneous = max(0.0, 1.0 - (emotion_delta * 0.7 + stress_score * 0.6))
        self._coherence_state = (
            1 - self.smoothing_alpha
        ) * self._coherence_state + self.smoothing_alpha * instantaneous

        volatility_penalty = 0.08 if market_volatility > 0.02 else 0.0
        coherence_index = max(0.0, min(1.0, self._coherence_state - volatility_penalty))

        pass_bar = 0.78 + (0.04 if market_volatility > 0.02 else 0.0)
        review_bar = 0.58 + (0.04 if market_volatility > 0.02 else 0.0)

        if coherence_index >= pass_bar:
            coherence_state = CoherenceState.PASS
        elif coherence_index >= review_bar:
            coherence_state = CoherenceState.REVIEW
        else:
            coherence_state = CoherenceState.LOCKOUT

        return CoherenceSnapshot(
            coherence_index=round(coherence_index, 6),
            emotion_delta=round(emotion_delta, 6),
            emotion_volatility=round(emotion_vol, 6),
            stress_score=round(stress_score, 6),
            gate=coherence_state,
            details={"timestamp": datetime.now(UTC).isoformat()},
        )

    def reset(self) -> None:
        """Reset accumulated state. Use when starting a new session or switching contexts."""
        self._emotion_baseline = 0.0
        self._coherence_state = 0.8
        self._emotion_history.clear()

    @staticmethod
    def export(snapshot: CoherenceSnapshot) -> dict[str, Any]:
        return {
            "coherence_index": snapshot.coherence_index,
            "emotion_delta": snapshot.emotion_delta,
            "emotion_volatility": snapshot.emotion_volatility,
            "stress_score": snapshot.stress_score,
            "gate": snapshot.gate.value,
            "details": snapshot.details,
        }
class CognitiveCoherence:
    emotion_delta: float
    reflex_state: ReflexState
    coherence_index: float
    integrity_status: IntegrityStatus
    gate: CoherenceGate
    psych_confidence: float
    details: dict[str, Any] = field(default_factory=dict)


class CognitiveCoherenceEngine:
    def __init__(self, alpha: float = 0.2, window: int = 32) -> None:
        self.alpha = alpha
        self.window = window
        self._smoothed = 0.8
        self._history: list[float] = []

    def evaluate(self, payload: dict[str, Any]) -> CoherenceResult:
        emotion = float(payload.get("emotion_state", 0.5))
        fatigue = float(payload.get("fatigue", 0.0))
        loss_stress = float(payload.get("loss_stress", 0.0))
        mkt_vol = float(payload.get("market_volatility", 0.5))
        self._history.append(emotion)
        self._history = self._history[-self.window :]
        baseline = fmean(self._history)
        emotion_delta = abs(emotion - baseline)
        vol = pstdev(self._history) if len(self._history) > 2 else 0.0
        stress_score = self._clamp(vol * 0.4 + loss_stress * 0.35 + fatigue * 0.25)
        current = self._clamp(1.0 - emotion_delta * 0.7 - stress_score * 0.6)
        self._smoothed = self.alpha * current + (1 - self.alpha) * self._smoothed
        strictness = 0.05 if mkt_vol > 0.6 else 0.0
        if self._smoothed < 0.55 - strictness:
            gate = "LOCKOUT"
        elif self._smoothed < 0.72 - strictness:
            gate = "REVIEW"
        else:
            gate = "PASS"
        return CoherenceResult(
            coherence_index=round(self._smoothed, 4),
            stress_score=round(stress_score, 4),
            emotion_delta=round(emotion_delta, 4),
            gate=gate,
            details={"baseline": round(baseline, 4), "emotion_volatility": round(vol, 4)},
        )

    @staticmethod
    def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, value))
    """Evaluate discipline readiness without execution authority."""

    def __init__(
        self,
        baseline_emotion: float = 0.5,
        smoothing_factor: float = 0.15,
        coherence_threshold: float = 0.75,
        emotion_history_size: int = 50,
    ) -> None:
        self.baseline_emotion = baseline_emotion
        self.smoothing = smoothing_factor
        self.coherence_threshold = coherence_threshold
        self._emotion_history: list[float] = []
        self._max_history = emotion_history_size
        self._last_coherence: float | None = None

    def evaluate(self, system_state: dict[str, Any]) -> CognitiveCoherence:
        emotion_now = float(system_state.get("emotion_now", 0.5))
        focus_index = float(system_state.get("focus_index", 0.7))
        reaction_delay_ms = float(system_state.get("reaction_delay_ms", 200.0))
        consecutive_losses = int(system_state.get("consecutive_losses", 0))
        session_min = float(system_state.get("session_duration_min", 60.0))
        mkt_volatility = float(system_state.get("ohlcv_volatility", 0.5))

        delay_factor = max(0.0, 1.0 - (reaction_delay_ms / 1000.0))
        base_coherence = 0.6 * focus_index + 0.4 * delay_factor
        coherence_index = self._clamp((emotion_now * 0.5 + base_coherence * 0.5), 0.0, 1.0)

        if self._last_coherence is not None:
            coherence_index = (
                self.smoothing * coherence_index + (1.0 - self.smoothing) * self._last_coherence
            )
        self._last_coherence = coherence_index

        adaptive_baseline = self._compute_adaptive_baseline()
        raw_delta = abs(emotion_now - adaptive_baseline)
        emotion_delta = self._clamp(raw_delta * (1.0 - self.smoothing))

        self._emotion_history.append(emotion_now)
        if len(self._emotion_history) > self._max_history:
            self._emotion_history.pop(0)

        emotion_vol = self._compute_emotion_volatility()
        fatigue_factor = min(1.0, session_min / 480.0)
        loss_stress = min(1.0, consecutive_losses * 0.15)
        stress_score = emotion_vol * 0.4 + loss_stress * 0.35 + fatigue_factor * 0.25

        if stress_score < 0.25:
            reflex_state = ReflexState.STABLE
        elif stress_score < 0.55:
            reflex_state = ReflexState.ELEVATED
        else:
            reflex_state = ReflexState.UNSTABLE

        if coherence_index >= 0.85 and emotion_delta <= 0.2:
            integrity_status = IntegrityStatus.PASS
        elif coherence_index >= 0.65 and emotion_delta <= 0.4:
            integrity_status = IntegrityStatus.REVIEW
        else:
            integrity_status = IntegrityStatus.FAIL

        if mkt_volatility > 0.7 and integrity_status == IntegrityStatus.REVIEW:
            integrity_status = IntegrityStatus.FAIL

        gate = self._evaluate_gate(coherence_index, emotion_delta, reflex_state)
        psych_confidence = self._clamp((coherence_index * (1.0 - emotion_delta)) ** 0.8)

        return CognitiveCoherence(
            emotion_delta=round(emotion_delta, 4),
            reflex_state=reflex_state,
            coherence_index=round(coherence_index, 4),
            integrity_status=integrity_status,
            gate=gate,
            psych_confidence=round(psych_confidence, 4),
            details={
                "stress_score": round(stress_score, 4),
                "emotion_volatility": round(emotion_vol, 4),
                "fatigue_factor": round(fatigue_factor, 4),
                "adaptive_baseline": round(adaptive_baseline, 4),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    def _compute_adaptive_baseline(self) -> float:
        if not self._emotion_history:
            return self.baseline_emotion
        recent = self._emotion_history[-20:]
        return sum(recent) / len(recent)

    def _compute_emotion_volatility(self) -> float:
        if len(self._emotion_history) < 3:
            return 0.1
        recent = self._emotion_history[-15:]
        mean = sum(recent) / len(recent)
        variance = sum((x - mean) ** 2 for x in recent) / len(recent)
        return min(1.0, math.sqrt(variance) * 3.0)

    def _evaluate_gate(
        self, coherence: float, emotion_delta: float, reflex: ReflexState
    ) -> CoherenceGate:
        if reflex == ReflexState.UNSTABLE:
            return CoherenceGate.LOCKOUT
        if coherence >= 0.85 and emotion_delta <= 0.25:
            return CoherenceGate.PASS
        if coherence >= 0.70 and emotion_delta <= 0.40:
            return CoherenceGate.REVIEW
        return CoherenceGate.LOCKOUT

    @staticmethod
    def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, value))

    def export(self, coherence: CognitiveCoherence) -> dict[str, Any]:
        return {
            "emotion_delta": coherence.emotion_delta,
            "reflex_state": coherence.reflex_state.value,
            "coherence_index": coherence.coherence_index,
            "integrity_status": coherence.integrity_status.value,
            "gate": coherence.gate.value,
            "psych_confidence": coherence.psych_confidence,
            "details": coherence.details,
        }

    def reset(self) -> None:
        self._emotion_history.clear()
        self._last_coherence = None


__all__ = [
    "CognitiveCoherence",
    "CognitiveCoherenceEngine",
    "CoherenceGate",
    "IntegrityStatus",
    "ReflexState",
]
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ReflexState(str, Enum):
    CALM = "calm"
    WATCHFUL = "watchful"
    REACTIVE = "reactive"


class IntegrityStatus(str, Enum):
    STRONG = "strong"
    DEGRADED = "degraded"
    FAILED = "failed"


class CoherenceGate(str, Enum):
    OPEN = "open"
    CAUTION = "caution"
    BLOCK = "block"


@dataclass(frozen=True)
class CognitiveCoherence:
    reflex_state: ReflexState
    integrity_status: IntegrityStatus
    coherence_gate: CoherenceGate
    score: float


class CognitiveCoherenceEngine:
    """Evaluate internal cognitive coherence from state primitives."""

    def evaluate(self, state: Mapping[str, Any]) -> CognitiveCoherence:
        emotion = float(state.get("emotion_balance", 0.5))
        reflex = float(state.get("reflex_pressure", 0.5))
        integrity = float(state.get("integrity_score", 0.5))
        score = max(0.0, min(1.0, (emotion + (1.0 - reflex) + integrity) / 3.0))

        reflex_state = ReflexState.CALM
        if reflex > 0.65:
            reflex_state = ReflexState.REACTIVE
        elif reflex > 0.35:
            reflex_state = ReflexState.WATCHFUL

        integrity_status = IntegrityStatus.STRONG
        if integrity < 0.3:
            integrity_status = IntegrityStatus.FAILED
        elif integrity < 0.6:
            integrity_status = IntegrityStatus.DEGRADED

        gate = CoherenceGate.OPEN
        if score < 0.35:
            gate = CoherenceGate.BLOCK
        elif score < 0.6:
            gate = CoherenceGate.CAUTION

        return CognitiveCoherence(
            reflex_state=reflex_state,
            integrity_status=integrity_status,
            coherence_gate=gate,
            score=score,
        )
