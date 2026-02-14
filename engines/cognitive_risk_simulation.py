from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RiskSimulationResult:
    stress_loss_pct: float
    tail_risk_score: float
    pass_gate: bool


class CognitiveRiskSimulation:
    """Simple stress and tail risk simulation over normalized inputs."""

    def evaluate(self, state: Mapping[str, Any]) -> RiskSimulationResult:
        leverage = float(state.get("effective_leverage", 1.0))
        volatility = float(state.get("volatility", 0.5))
        gap_risk = float(state.get("gap_risk", 0.3))

        stress_loss = max(0.0, min(1.0, leverage * volatility * 0.18 + gap_risk * 0.25))
        tail = max(0.0, min(1.0, volatility * 0.6 + gap_risk * 0.4))
        pass_gate = stress_loss < 0.2 and tail < 0.7

        return RiskSimulationResult(
            stress_loss_pct=stress_loss,
            tail_risk_score=tail,
            pass_gate=pass_gate,
        )
