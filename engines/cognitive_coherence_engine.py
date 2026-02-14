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
