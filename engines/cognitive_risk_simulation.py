from __future__ import annotations

import random

from dataclasses import dataclass
from statistics import fmean
from typing import Any


@dataclass
class RiskSimulationResult:
    valid: bool
    var_95: float
    cvar_95: float
    max_drawdown: float
    stress_survival_rate: float
    robustness_estimate: float
    tail_risk_flag: bool


class CognitiveRiskSimulation:
    def __init__(self, n_iter: int = 500, seed: int = 17) -> None:
        self.n_iter = n_iter
        self.rng = random.Random(seed)

    def simulate(self, returns: list[float]) -> RiskSimulationResult:
        if len(returns) < 20:
            return RiskSimulationResult(False, 0.0, 0.0, 0.0, 0.0, 0.0, True)

        pnl = []
        drawdowns = []
        stress_ok = 0
        for _ in range(self.n_iter):
            path = [self.rng.choice(returns) for _ in range(50)]
            if self.rng.random() < 0.08:
                gap = abs(fmean(returns)) + max(0.01, self.rng.uniform(0.03, 0.05))
                path[self.rng.randint(0, 49)] -= gap
            if self.rng.random() < 0.2:
                path = [step * 2.0 for step in path]

            equity = 1.0
            peak = 1.0
            max_dd = 0.0
            for step in path:
                equity *= 1.0 + step
                peak = max(peak, equity)
                dd = (peak - equity) / max(peak, 1e-9)
                max_dd = max(max_dd, dd)
            pnl.append(equity - 1.0)
            drawdowns.append(max_dd)
            if max_dd < 0.2:
                stress_ok += 1

        pnl_sorted = sorted(pnl)
        idx = max(0, int(0.05 * len(pnl_sorted)) - 1)
        var_95 = -pnl_sorted[idx]
        tail = pnl_sorted[: max(1, int(0.05 * len(pnl_sorted)))]
        cvar_95 = -fmean(tail)

        max_drawdown = max(drawdowns)
        survival = stress_ok / self.n_iter

        robustness = max(0.0, min(1.0, 1.0 - (var_95 * 0.4 + cvar_95 * 0.4 + max_drawdown * 0.2)))
        tail_flag = cvar_95 > 0.2 or max_drawdown > 0.35

        return RiskSimulationResult(
            valid=True,
            var_95=round(var_95, 4),
            cvar_95=round(cvar_95, 4),
            max_drawdown=round(max_drawdown, 4),
            stress_survival_rate=round(survival, 4),
            robustness_estimate=round(robustness, 4),
            tail_risk_flag=tail_flag,
        )

    @staticmethod
    def export(result: RiskSimulationResult) -> dict[str, Any]:
        return {
            "valid": result.valid,
            "var_95": result.var_95,
            "cvar_95": result.cvar_95,
            "max_drawdown": result.max_drawdown,
            "stress_survival_rate": result.stress_survival_rate,
            "robustness_estimate": result.robustness_estimate,
            "tail_risk_flag": result.tail_risk_flag,
        }
