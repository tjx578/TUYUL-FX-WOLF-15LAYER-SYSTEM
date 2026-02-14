from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Any


@dataclass
class CoherenceSnapshot:
    valid: bool
    coherence_index: float
    psych_confidence: float
    stress_score: float
    gate: str
    emotion_volatility: float


class CognitiveCoherenceEngine:
    """Tracks behavioral coherence with an adaptive baseline and gate policy."""

    def __init__(self, alpha: float = 0.2, history_size: int = 30) -> None:
        self.alpha = alpha
        self.emotion_history: deque[float] = deque(maxlen=history_size)
        self.smoothed_coherence = 0.75

    def analyze(self, payload: dict[str, Any]) -> CoherenceSnapshot:
        emotion = float(payload.get("emotion_state", 0.5))
        loss_stress = float(payload.get("loss_stress", 0.0))
        fatigue = float(payload.get("fatigue", 0.0))
        market_vol = float(payload.get("market_volatility", 0.5))

        self.emotion_history.append(emotion)
        baseline = fmean(self.emotion_history) if self.emotion_history else 0.5
        vol = pstdev(self.emotion_history) if len(self.emotion_history) > 1 else 0.0

        stress_score = min(1.0, vol * 0.4 + loss_stress * 0.35 + fatigue * 0.25)
        coherence_now = max(0.0, 1.0 - abs(emotion - baseline) - stress_score * 0.5)
        self.smoothed_coherence = (
            self.alpha * coherence_now + (1 - self.alpha) * self.smoothed_coherence
        )

        strictness = 0.05 if market_vol > 0.7 else 0.0
        lockout_bar = 0.45 + strictness
        review_bar = 0.65 + strictness

        if self.smoothed_coherence < lockout_bar:
            gate = "LOCKOUT"
        elif self.smoothed_coherence < review_bar:
            gate = "REVIEW"
        else:
            gate = "PASS"

        psych_conf = max(0.0, min(1.0, 1.0 - stress_score))

        return CoherenceSnapshot(
            valid=True,
            coherence_index=round(self.smoothed_coherence, 4),
            psych_confidence=round(psych_conf, 4),
            stress_score=round(stress_score, 4),
            gate=gate,
            emotion_volatility=round(vol, 4),
        )

    @staticmethod
    def export(snapshot: CoherenceSnapshot) -> dict[str, Any]:
        return {
            "valid": snapshot.valid,
            "coherence_index": snapshot.coherence_index,
            "psych_confidence": snapshot.psych_confidence,
            "stress_score": snapshot.stress_score,
            "gate": snapshot.gate,
            "emotion_volatility": snapshot.emotion_volatility,
        }
