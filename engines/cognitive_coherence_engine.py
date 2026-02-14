"""Cognitive coherence gate with smoothing and adaptive baseline."""

from collections import deque
from dataclasses import dataclass, field
from statistics import pstdev
from typing import Any, Deque, Dict


@dataclass
class CoherenceState:
    coherence_index: float
    stress_score: float
    gate: str
    details: Dict[str, Any] = field(default_factory=dict)


class CognitiveCoherenceEngine:
    def __init__(self, history_size: int = 64, alpha: float = 0.2) -> None:
        self.alpha = alpha
        self._history: Deque[float] = deque(maxlen=history_size)
        self._coherence_ema = 0.8

    def evaluate(self, signal: Dict[str, Any]) -> CoherenceState:
        emotion = float(signal.get("emotion_state", 0.5))
        loss_stress = float(signal.get("loss_stress", 0.0))
        fatigue = float(signal.get("fatigue", 0.0))
        market_vol = float(signal.get("market_volatility", 0.5))

        self._history.append(emotion)
        baseline = sum(self._history) / len(self._history)
        volatility = pstdev(self._history) if len(self._history) > 1 else 0.0
        emotion_delta = abs(emotion - baseline)
        stress_score = (volatility * 0.4) + (loss_stress * 0.35) + (fatigue * 0.25)

        raw = 1.0 - min(1.0, emotion_delta + stress_score)
        self._coherence_ema = (self.alpha * raw) + ((1.0 - self.alpha) * self._coherence_ema)
        integrity_bar = 0.65 + (0.15 if market_vol > 0.7 else 0.0)

        gate = "PASS"
        if self._coherence_ema < integrity_bar:
            gate = "LOCKOUT"
        elif self._coherence_ema < integrity_bar + 0.08:
            gate = "REVIEW"

        return CoherenceState(
            coherence_index=round(self._coherence_ema, 4),
            stress_score=round(stress_score, 4),
            gate=gate,
            details={
                "emotion_delta": round(emotion_delta, 4),
                "emotion_volatility": round(volatility, 4),
                "adaptive_baseline": round(baseline, 4),
                "integrity_bar": round(integrity_bar, 4),
            },
        )


__all__ = ["CoherenceState", "CognitiveCoherenceEngine"]
