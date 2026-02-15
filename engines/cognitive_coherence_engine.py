"""Cognitive coherence engine for emotional integrity and state assessment.

This module provides trader psychological state evaluation WITHOUT execution authority.
All state values are input metrics for Layer-12 (constitution), not enforcement decisions.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from statistics import pstdev
from typing import Any


class CoherenceState(StrEnum):
    """Trader psychological coherence state assessment levels.

    These are assessment states (input), not execution decisions.
    Layer-12 (constitution) makes the final execution verdict based on these and other inputs.
    """

    PASS = "PASS"  # noqa: S105
    REVIEW = "REVIEW"
    LOCKOUT = "LOCKOUT"


@dataclass
class CoherenceSnapshot:
    """Snapshot of trader coherence state for analysis input."""

    coherence_index: float
    emotion_delta: float
    emotion_volatility: float
    stress_score: float
    gate: CoherenceState
    details: dict[str, Any] = field(default_factory=dict)


class CognitiveCoherenceEngine:
    """Tracks trader-state coherence and emits psychological state assessment.

    This engine maintains internal state across evaluations through instance variables:
    - _emotion_baseline: Adaptive baseline for emotion tracking
    - _coherence_state: Smoothed coherence index
    - _emotion_history: Rolling window of emotion values

    **Authority Boundaries**: This engine provides INPUT METRICS for Layer-12 decisions.
    It does NOT have execution authority. The state values (PASS/REVIEW/LOCKOUT) are
    assessments of trader psychological coherence, not trading permissions.

    **Thread Safety**: This engine is NOT thread-safe. One instance per context.

    **State Management**: Call reset() to clear accumulated state when starting a new
    trading session or switching contexts.
    """

    def __init__(
        self,
        smoothing_alpha: float = 0.25,
        baseline_alpha: float = 0.12,
        history_size: int = 64,
    ) -> None:
        """Initialize cognitive coherence engine.

        Args:
            smoothing_alpha: EMA smoothing factor for coherence (0.0–1.0).
            baseline_alpha: Adaptive baseline update rate (0.0–1.0).
            history_size: Rolling window size for emotion history.
        """
        self.smoothing_alpha = smoothing_alpha
        self.baseline_alpha = baseline_alpha
        self._emotion_baseline = 0.0
        self._coherence_state = 0.8
        self._emotion_history: deque[float] = deque(maxlen=history_size)

    def evaluate(
        self, state: dict[str, Any], market_volatility: float = 0.0
    ) -> CoherenceSnapshot:
        """Evaluate trader psychological coherence from state primitives.

        Args:
            state: Input state dict with keys:
                - emotion_state (float, 0–1): Current emotion level.
                - fatigue (float, 0–1): Accumulated fatigue.
                - loss_stress (float, 0–1): Loss-induced stress.
            market_volatility: Current market volatility (0–1). Tightens thresholds.

        Returns:
            CoherenceSnapshot with assessment metrics and gate.
        """
        emotion = float(state.get("emotion_state", 0.0))
        fatigue = max(0.0, min(1.0, float(state.get("fatigue", 0.0))))
        loss_stress = max(0.0, min(1.0, float(state.get("loss_stress", 0.0))))

        # Update adaptive baseline
        self._emotion_baseline = (
            (1 - self.baseline_alpha) * self._emotion_baseline
            + self.baseline_alpha * emotion
        )
        emotion_delta = abs(emotion - self._emotion_baseline)

        # Track emotion history
        self._emotion_history.append(emotion)
        emotion_vol = (
            pstdev(self._emotion_history) if len(self._emotion_history) > 2 else 0.0
        )
        stress_score = min(1.0, emotion_vol * 0.4 + loss_stress * 0.35 + fatigue * 0.25)

        # Compute instantaneous coherence
        instantaneous = max(0.0, 1.0 - (emotion_delta * 0.7 + stress_score * 0.6))
        self._coherence_state = (
            (1 - self.smoothing_alpha) * self._coherence_state
            + self.smoothing_alpha * instantaneous
        )

        # Apply market volatility penalty
        volatility_penalty = 0.08 if market_volatility > 0.02 else 0.0
        coherence_index = max(0.0, min(1.0, self._coherence_state - volatility_penalty))

        # Determine gate thresholds
        pass_bar = 0.78 + (0.04 if market_volatility > 0.02 else 0.0)
        review_bar = 0.58 + (0.04 if market_volatility > 0.02 else 0.0)

        if coherence_index >= pass_bar:
            gate = CoherenceState.PASS
        elif coherence_index >= review_bar:
            gate = CoherenceState.REVIEW
        else:
            gate = CoherenceState.LOCKOUT

        return CoherenceSnapshot(
            coherence_index=round(coherence_index, 6),
            emotion_delta=round(emotion_delta, 6),
            emotion_volatility=round(emotion_vol, 6),
            stress_score=round(stress_score, 6),
            gate=gate,
            details={"timestamp": datetime.now(UTC).isoformat()},
        )

    def reset(self) -> None:
        """Reset accumulated state. Use when starting a new session or switching contexts."""
        self._emotion_baseline = 0.0
        self._coherence_state = 0.8
        self._emotion_history.clear()

    @staticmethod
    def export(snapshot: CoherenceSnapshot) -> dict[str, Any]:
        """Export snapshot as a dictionary for logging or API response."""
        return {
            "coherence_index": snapshot.coherence_index,
            "emotion_delta": snapshot.emotion_delta,
            "emotion_volatility": snapshot.emotion_volatility,
            "stress_score": snapshot.stress_score,
            "gate": snapshot.gate.value,
            "details": snapshot.details,
        }


__all__ = ["CognitiveCoherenceEngine", "CoherenceSnapshot", "CoherenceState"]
