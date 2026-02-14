"""Risk simulation engine with stressed Monte Carlo and tail metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from random import Random
from typing import Any, Dict, List, Sequence


@dataclass
class RiskSimulationResult:
    valid: bool
    var95: float
    cvar95: float
    max_drawdown: float
    stress_survival_rate: float
    robustness: float
    details: Dict[str, Any] = field(default_factory=dict)


class CognitiveRiskSimulation:
    def __init__(self, iterations: int = 500, horizon: int = 30, seed: int = 7) -> None:
        self.iterations = iterations
        self.horizon = horizon
        self._random = Random(seed)

    def simulate(self, returns: Sequence[float]) -> RiskSimulationResult:
        if len(returns) < 30:
            return RiskSimulationResult(
                valid=False,
                var95=0.0,
                cvar95=0.0,
                max_drawdown=0.0,
                stress_survival_rate=0.0,
                robustness=0.0,
                details={"reason": "insufficient_returns"},
            )

        base_paths = [self._sample_path(returns, 1.0, False) for _ in range(self.iterations)]
        stress_paths = [self._sample_path(returns, 2.0, True) for _ in range(self.iterations)]

        finals = sorted(path[-1] for path in base_paths)
        tail_index = max(1, int(0.05 * len(finals)))
        var95 = 1.0 - finals[tail_index - 1]
        cvar95 = 1.0 - (sum(finals[:tail_index]) / tail_index)

        drawdowns = [self._max_drawdown(path) for path in stress_paths]
        max_dd = sum(drawdowns) / len(drawdowns)
        survival = sum(1 for d in drawdowns if d < 0.25) / len(drawdowns)

        robustness = max(0.0, 1.0 - (0.5 * var95 + 0.3 * cvar95 + 0.2 * max_dd))

        return RiskSimulationResult(
            valid=True,
            var95=round(var95, 4),
            cvar95=round(cvar95, 4),
            max_drawdown=round(max_dd, 4),
            stress_survival_rate=round(survival, 4),
            robustness=round(robustness, 4),
            details={
                "iterations": self.iterations,
                "horizon": self.horizon,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _sample_path(self, returns: Sequence[float], vol_mult: float, gaps: bool) -> List[float]:
        value = 1.0
        peak = 1.0
        path = [value]
        sigma = self._stdev(returns)

        for _ in range(self.horizon):
            r = returns[self._random.randint(0, len(returns) - 1)] * vol_mult
            if gaps and self._random.random() < 0.06:
                r += -sigma * self._random.uniform(3.0, 5.0)
            value *= max(0.1, 1.0 + r)
            peak = max(peak, value)
            path.append(value)
        return path

    @staticmethod
    def _stdev(values: Sequence[float]) -> float:
        mean = sum(values) / max(len(values), 1)
        variance = sum((v - mean) ** 2 for v in values) / max(len(values), 1)
        return variance ** 0.5

    @staticmethod
    def _max_drawdown(path: Sequence[float]) -> float:
        peak = path[0]
        worst = 0.0
        for value in path:
            peak = max(peak, value)
            dd = 1.0 - value / max(peak, 1e-9)
            worst = max(worst, dd)
        return worst
