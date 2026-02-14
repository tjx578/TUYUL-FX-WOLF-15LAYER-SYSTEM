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
