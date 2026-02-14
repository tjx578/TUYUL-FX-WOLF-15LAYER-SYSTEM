"""Risk simulation engine using bootstrap Monte Carlo and stress paths."""

import random

from dataclasses import dataclass
from typing import Any


@dataclass
class RiskSimulationReport:
    var_95: float
    cvar_95: float
    max_drawdown: float
    stress_survival: float
    robustness: float
    tail_risk: bool
    details: dict[str, Any]


class CognitiveRiskSimulation:
    def __init__(self, iterations: int = 500) -> None:
        self.iterations = iterations

    def simulate(self, returns: list[float]) -> RiskSimulationReport:
        if len(returns) < 20:
            return RiskSimulationReport(
                0.0, 0.0, 0.0, 0.0, 0.2, True, {"reason": "insufficient_data"}
            )

        pnl_samples: list[float] = []
        drawdowns: list[float] = []
        survival = 0
        sigma = self._stdev(returns)
        for _ in range(self.iterations):
            path = [random.choice(returns) for _ in range(30)]
            if random.random() < 0.2:
                path[random.randrange(len(path))] -= random.uniform(3.0, 5.0) * sigma
            stressed = [r * 2.0 for r in path]
            total = sum(stressed)
            pnl_samples.append(total)
            dd = self._max_drawdown(stressed)
            drawdowns.append(dd)
            if dd > -0.2:
                survival += 1

        sorted_pnl = sorted(pnl_samples)
        idx = max(0, int(0.05 * len(sorted_pnl)) - 1)
        var_95 = sorted_pnl[idx]
        tail = sorted_pnl[: max(1, idx + 1)]
        cvar_95 = sum(tail) / len(tail)
        max_dd = min(drawdowns)
        stress_survival = survival / self.iterations
        robustness = max(0.0, min(1.0, 0.45 + stress_survival * 0.35 + (1.0 + max_dd) * 0.2))

        return RiskSimulationReport(
            var_95=round(var_95, 6),
            cvar_95=round(cvar_95, 6),
            max_drawdown=round(max_dd, 6),
            stress_survival=round(stress_survival, 4),
            robustness=round(robustness, 4),
            tail_risk=cvar_95 < -0.1,
            details={"iterations": self.iterations, "sigma": round(sigma, 6)},
        )

    def _max_drawdown(self, path: list[float]) -> float:
        equity = 1.0
        peak = 1.0
        max_dd = 0.0
        for ret in path:
            equity *= 1.0 + ret
            peak = max(peak, equity)
            dd = (equity - peak) / peak
            max_dd = min(max_dd, dd)
        return max_dd

    def _stdev(self, values: list[float]) -> float:
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return variance**0.5
