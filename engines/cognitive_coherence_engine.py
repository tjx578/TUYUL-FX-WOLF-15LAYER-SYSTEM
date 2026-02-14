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
