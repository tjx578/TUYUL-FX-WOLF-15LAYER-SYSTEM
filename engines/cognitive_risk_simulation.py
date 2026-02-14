"""Risk simulation engine with bootstrap Monte Carlo and stress metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from statistics import mean
from typing import Any, Dict, List


@dataclass
class RiskSimulationResult:
    var_95: float
    cvar_95: float
    max_drawdown: float
    stress_survival_rate: float
    robustness: float
    details: Dict[str, Any] = field(default_factory=dict)


class CognitiveRiskSimulation:
    def __init__(self, iterations: int = 500, horizon: int = 40, seed: int = 7) -> None:
        self.iterations = iterations
        self.horizon = horizon
        self._rng = Random(seed)

    def simulate(self, returns: List[float]) -> RiskSimulationResult:
        if not returns:
            return RiskSimulationResult(0.0, 0.0, 0.0, 0.0, 0.0, {"reason": "no_returns"})

        terminal, drawdowns, stressed_terminal = [], [], []
        for _ in range(self.iterations):
            path = self._sample_path(returns, stressed=False)
            s_path = self._sample_path(returns, stressed=True)
            terminal.append(path[-1])
            stressed_terminal.append(s_path[-1])
            drawdowns.append(self._max_drawdown(path))

        sorted_terminal = sorted(terminal)
        idx_5 = max(0, int(0.05 * len(sorted_terminal)) - 1)
        var_95 = sorted_terminal[idx_5]
        tail = sorted_terminal[: idx_5 + 1] or [var_95]
        cvar_95 = mean(tail)

        stress_survival = sum(1 for v in stressed_terminal if v > -0.12) / len(stressed_terminal)
        max_dd = max(drawdowns)

        robustness = max(0.0, min(1.0, 1 + cvar_95 - max_dd * 0.8 + stress_survival * 0.2))
        return RiskSimulationResult(
            var_95=round(var_95, 6),
            cvar_95=round(cvar_95, 6),
            max_drawdown=round(max_dd, 6),
            stress_survival_rate=round(stress_survival, 6),
            robustness=round(robustness, 6),
            details={
                "iterations": self.iterations,
                "horizon": self.horizon,
                "stressed_mean": round(mean(stressed_terminal), 6),
            },
        )

    def _sample_path(self, returns: List[float], stressed: bool) -> List[float]:
        level = 0.0
        path = [level]
        sigma_proxy = max(1e-6, (max(returns) - min(returns)) / 6)
        for _ in range(self.horizon):
            base = self._rng.choice(returns)
            shock = base * (2.0 if stressed else 1.0)
            if stressed and self._rng.random() < 0.08:
                shock -= self._rng.uniform(3.0, 5.0) * sigma_proxy
            level += shock
            path.append(level)
        return path

    @staticmethod
    def _max_drawdown(path: List[float]) -> float:
        peak = path[0]
        max_dd = 0.0
        for value in path:
            if value > peak:
                peak = value
            dd = peak - value
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @staticmethod
    def export(result: RiskSimulationResult) -> Dict[str, Any]:
        return {
            "var_95": result.var_95,
            "cvar_95": result.cvar_95,
            "max_drawdown": result.max_drawdown,
            "stress_survival_rate": result.stress_survival_rate,
            "robustness": result.robustness,
            "details": result.details,
        }
