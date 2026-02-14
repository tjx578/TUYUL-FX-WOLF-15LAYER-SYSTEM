"""Cognitive risk simulation engine."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any


@dataclass
class RiskSimulationResult:
    var_95: float
    cvar_95: float
    max_drawdown: float
    stress_survival_rate: float
    robustness: float


class CognitiveRiskSimulation:
    def __init__(self, iterations: int = 500, seed: int = 7) -> None:
        self.iterations = iterations
        self.rng = Random(seed)

    def simulate(self, returns: list[float], start_equity: float = 1.0) -> RiskSimulationResult:
        if not returns:
            return RiskSimulationResult(0.0, 0.0, 0.0, 0.0, 0.0)
        pnl_paths: list[float] = []
        drawdowns: list[float] = []
        survives = 0
        for _ in range(self.iterations):
            sampled = [self.rng.choice(returns) for _ in returns]
            if self.rng.random() < 0.1:
                sampled[self.rng.randrange(len(sampled))] -= abs(self.rng.gauss(0.03, 0.01))
            equity = start_equity
            peak = equity
            max_dd = 0.0
            for r in sampled:
                stress_r = r * (2.0 if self.rng.random() < 0.2 else 1.0)
                equity *= 1 + stress_r
                peak = max(peak, equity)
                dd = (peak - equity) / peak if peak else 0.0
                max_dd = max(max_dd, dd)
            pnl = equity - start_equity
            pnl_paths.append(pnl)
            drawdowns.append(max_dd)
            if equity > start_equity * 0.8:
                survives += 1
        pnl_paths.sort()
        idx = max(0, int(0.05 * len(pnl_paths)) - 1)
        var_95 = abs(pnl_paths[idx])
        tail = pnl_paths[: max(1, int(0.05 * len(pnl_paths)))]
        cvar_95 = abs(sum(tail) / len(tail))
        avg_dd = sum(drawdowns) / len(drawdowns)
        survival = survives / self.iterations
        robustness = max(0.0, min(1.0, (1 - cvar_95) * 0.5 + (1 - avg_dd) * 0.25 + survival * 0.25))
        return RiskSimulationResult(
            round(var_95, 4),
            round(cvar_95, 4),
            round(avg_dd, 4),
            round(survival, 4),
            round(robustness, 4),
        )

    @staticmethod
    def export(result: RiskSimulationResult) -> dict[str, Any]:
        return result.__dict__
