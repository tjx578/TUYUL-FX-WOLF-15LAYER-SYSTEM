"""Cognitive coherence engine for emotional integrity and state assessment.

This module provides trader psychological state evaluation WITHOUT execution authority.
All state values are input metrics for Layer-12 (constitution), not enforcement decisions.
"""

from __future__ import annotations

from collections import deque
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
    state: CoherenceState  # Renamed from 'gate' to clarify this is state assessment
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
            state=coherence_state,
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
            "gate": snapshot.state.value,  # Keep 'gate' key for backward compatibility
            "details": snapshot.details,
        }
