from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class AdvisorySignal(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class RiskPosture(str, Enum):
    AGGRESSIVE = "aggressive"
    BALANCED = "balanced"
    DEFENSIVE = "defensive"


@dataclass(frozen=True)
class AdvisorySummary:
    signal: AdvisorySignal
    risk_posture: RiskPosture
    confidence: float


class QuantumAdvisoryEngine:
    """Synthesize cross-engine outcomes into final advisory guidance."""

    def evaluate(self, state: Mapping[str, Any]) -> AdvisorySummary:
        probability = float(state.get("probability", 0.5))
        bias = float(state.get("bias", 0.0))
        risk = float(state.get("tail_risk", 0.5))

        signal = AdvisorySignal.HOLD
        if probability > 0.6 and bias > 0.1:
            signal = AdvisorySignal.BUY
        elif probability < 0.4 and bias < -0.1:
            signal = AdvisorySignal.SELL

        posture = RiskPosture.BALANCED
        if risk > 0.7:
            posture = RiskPosture.DEFENSIVE
        elif risk < 0.3:
            posture = RiskPosture.AGGRESSIVE

        confidence = max(0.0, min(1.0, abs(probability - 0.5) * 2.0 * (1.0 - risk)))
        return AdvisorySummary(signal=signal, risk_posture=posture, confidence=confidence)
