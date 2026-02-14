"""Bootstrap and stress risk simulation for robustness and tail exposure."""

from dataclasses import dataclass, field
from random import Random
from typing import Any, Dict, List


@dataclass
class RiskSimulation:
    robustness: float
    var95: float
    cvar95: float
    stress_survival: float
    tail_risk: bool
    details: Dict[str, Any] = field(default_factory=dict)


class CognitiveRiskSimulation:
    def __init__(self, iterations: int = 500, seed: int = 7) -> None:
        self.iterations = iterations
        self.random = Random(seed)

    def evaluate(self, payload: Dict[str, Any]) -> RiskSimulation:
        returns: List[float] = payload.get("returns", [])
        if not returns:
            returns = [0.0]

        sim_results: List[float] = []
        drawdowns: List[float] = []
        survival_count = 0

        sigma = self._stddev(returns)
        for _ in range(self.iterations):
            path = [self.random.choice(returns) for _ in range(max(30, len(returns)))]
            if self.random.random() < 0.1:
                path.append(-self.random.uniform(3.0 * sigma, 5.0 * sigma))
            if self.random.random() < 0.2:
                path = [value * 2.0 for value in path]

            pnl = sum(path)
            dd = self._max_drawdown(path)
            sim_results.append(pnl)
            drawdowns.append(dd)
            if dd > -0.2:
                survival_count += 1

        ordered = sorted(sim_results)
        var_index = max(0, int(0.05 * len(ordered)) - 1)
        var95 = ordered[var_index]
        cvar_tail = ordered[: max(1, int(0.05 * len(ordered)))]
        cvar95 = sum(cvar_tail) / len(cvar_tail)
        stress_survival = survival_count / len(sim_results)
        avg_dd = sum(drawdowns) / len(drawdowns)

        robustness = max(0.0, min(1.0, (stress_survival * 0.6) + ((1.0 + avg_dd) * 0.4)))
        tail_risk = cvar95 < -0.12

        return RiskSimulation(
            robustness=round(robustness, 4),
            var95=round(var95, 6),
            cvar95=round(cvar95, 6),
            stress_survival=round(stress_survival, 4),
            tail_risk=tail_risk,
            details={"avg_drawdown": round(avg_dd, 6), "sigma": round(sigma, 6)},
        )

    def _stddev(self, values: List[float]) -> float:
        if len(values) < 2:
            return 0.01
        mean = sum(values) / len(values)
        var = sum((x - mean) ** 2 for x in values) / len(values)
        return var ** 0.5

    def _max_drawdown(self, values: List[float]) -> float:
        equity = 0.0
        peak = 0.0
        worst = 0.0
        for value in values:
            equity += value
            peak = max(peak, equity)
            drawdown = equity - peak
            worst = min(worst, drawdown)
        return worst


__all__ = ["RiskSimulation", "CognitiveRiskSimulation"]
