from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class StructureState(str, Enum):
    SUPPORTIVE = "supportive"
    CONFLICTED = "conflicted"
    FRAGILE = "fragile"


@dataclass(frozen=True)
class FusionStructure:
    state: StructureState
    divergence_score: float
    liquidity_signal: float
    mtf_alignment: float


class FusionStructureEngine:
    """Assess structural reliability from divergence, liquidity and MTF alignment."""

    def evaluate(self, state: Mapping[str, Any]) -> FusionStructure:
        divergence = max(0.0, min(1.0, float(state.get("divergence_score", 0.4))))
        liquidity = max(0.0, min(1.0, float(state.get("liquidity_signal", 0.5))))
        mtf = max(0.0, min(1.0, float(state.get("mtf_alignment", 0.5))))

        if divergence < 0.3 and mtf > 0.6:
            struct_state = StructureState.SUPPORTIVE
        elif divergence > 0.7 or liquidity < 0.3:
            struct_state = StructureState.FRAGILE
        else:
            struct_state = StructureState.CONFLICTED

        return FusionStructure(
            state=struct_state,
            divergence_score=divergence,
            liquidity_signal=liquidity,
            mtf_alignment=mtf,
        )
