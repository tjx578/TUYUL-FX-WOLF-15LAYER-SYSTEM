"""Cognitive coherence engine for emotional integrity and gating."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
from typing import Any


class ReflexState(str, Enum):
    STABLE = "STABLE"
    ELEVATED = "ELEVATED"
    UNSTABLE = "UNSTABLE"


class IntegrityStatus(str, Enum):
    PASS = "PASS"  # noqa: S105
    REVIEW = "REVIEW"
    FAIL = "FAIL"


class CoherenceGate(str, Enum):
    PASS = "PASS"  # noqa: S105
    REVIEW = "REVIEW"
    LOCKOUT = "LOCKOUT"


@dataclass
class CoherenceSnapshot:
    coherence_index: float
    emotion_delta: float
    emotion_volatility: float
    stress_score: float
    gate: CoherenceGate
    details: Dict[str, Any] = field(default_factory=dict)


class CognitiveCoherenceEngine:
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
        self._emotion_history: Deque[float] = deque(maxlen=history_size)

    def evaluate(self, state: Dict[str, Any], market_volatility: float = 0.0) -> CoherenceSnapshot:
        emotion = float(state.get("emotion_state", 0.0))
        fatigue = max(0.0, min(1.0, float(state.get("fatigue", 0.0))))
        loss_stress = max(0.0, min(1.0, float(state.get("loss_stress", 0.0))))

        self._emotion_baseline = (
            (1 - self.baseline_alpha) * self._emotion_baseline + self.baseline_alpha * emotion
        )
        emotion_delta = abs(emotion - self._emotion_baseline)

        self._emotion_history.append(emotion)
        emotion_vol = pstdev(self._emotion_history) if len(self._emotion_history) > 2 else 0.0
        stress_score = min(1.0, emotion_vol * 0.4 + loss_stress * 0.35 + fatigue * 0.25)

        instantaneous = max(0.0, 1.0 - (emotion_delta * 0.7 + stress_score * 0.6))
        self._coherence_state = (
            (1 - self.smoothing_alpha) * self._coherence_state
            + self.smoothing_alpha * instantaneous
        )

        volatility_penalty = 0.08 if market_volatility > 0.02 else 0.0
        coherence_index = max(0.0, min(1.0, self._coherence_state - volatility_penalty))

        pass_bar = 0.78 + (0.04 if market_volatility > 0.02 else 0.0)
        review_bar = 0.58 + (0.04 if market_volatility > 0.02 else 0.0)

        if coherence_index >= pass_bar:
            gate = CoherenceGate.PASS
        elif coherence_index >= review_bar:
            gate = CoherenceGate.REVIEW
        else:
            gate = CoherenceGate.LOCKOUT

        return CoherenceSnapshot(
            coherence_index=round(coherence_index, 6),
            emotion_delta=round(emotion_delta, 6),
            emotion_volatility=round(emotion_vol, 6),
            stress_score=round(stress_score, 6),
            gate=gate,
            details={"timestamp": datetime.now(timezone.utc).isoformat()},
        )

    @staticmethod
    def export(snapshot: CoherenceSnapshot) -> Dict[str, Any]:
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
