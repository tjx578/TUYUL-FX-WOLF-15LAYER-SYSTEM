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
