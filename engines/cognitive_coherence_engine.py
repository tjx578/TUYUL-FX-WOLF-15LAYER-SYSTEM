"""Cognitive coherence engine (analysis-only)."""

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
    details: Dict[str, Any] = field(default_factory=dict)


class CognitiveCoherenceEngine:
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
