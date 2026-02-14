"""Risk simulation engine with bootstrap Monte Carlo and stress metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from statistics import mean
from typing import Any


@dataclass
class RiskSimulationResult:
    var_95: float
    cvar_95: float
    max_drawdown: float
    stress_survival_rate: float
    robustness: float
    details: dict[str, Any] = field(default_factory=dict)


class CognitiveRiskSimulation:
    """Bootstrap Monte Carlo risk simulation with configurable stress scenarios.

    Args:
        iterations: Number of Monte Carlo simulation runs (default: 500)
        horizon: Number of steps to project forward (default: 40)
        seed: Random seed for reproducibility. Use None for true randomness in production (default: None)
        stress_multiplier: Multiplier for stressed scenarios (default: 2.0)
        stress_shock_prob: Probability of extreme downside shock in stressed path (default: 0.08)
        stress_shock_range: Range of sigma multiples for extreme shocks (default: (3.0, 5.0))

    Note:
        For production use, consider setting seed=None to avoid deterministic results.
        The default seed=None provides true randomness, while explicit seeds enable reproducible testing.
    """

    def __init__(
        self,
        iterations: int = 500,
        horizon: int = 40,
        seed: int | None = None,
        stress_multiplier: float = 2.0,
        stress_shock_prob: float = 0.08,
        stress_shock_range: tuple[float, float] = (3.0, 5.0),
    ) -> None:
        self.iterations = iterations
        self.horizon = horizon
        self.stress_multiplier = stress_multiplier
        self.stress_shock_prob = stress_shock_prob
        self.stress_shock_range = stress_shock_range
        self._rng = Random(seed)

    def simulate(self, returns: list[float]) -> RiskSimulationResult:
        if not returns:
            return RiskSimulationResult(0.0, 0.0, 0.0, 0.0, 0.0, {"reason": "no_returns"})

        # Validate sufficient data for bootstrap methodology
        min_required = max(20, self.horizon // 2)
        if len(returns) < min_required:
            return RiskSimulationResult(
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                {
                    "reason": "insufficient_returns",
                    "required": min_required,
                    "provided": len(returns),
                },
            )

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

    def _sample_path(self, returns: list[float], stressed: bool) -> list[float]:
        level = 0.0
        path = [level]
        sigma_proxy = max(1e-6, (max(returns) - min(returns)) / 6)
        for _ in range(self.horizon):
            base = self._rng.choice(returns)
            shock = base * (self.stress_multiplier if stressed else 1.0)
            if stressed and self._rng.random() < self.stress_shock_prob:
                shock -= self._rng.uniform(*self.stress_shock_range) * sigma_proxy
            level += shock
            path.append(level)
        return path

    @staticmethod
    def _max_drawdown(path: list[float]) -> float:
        peak = path[0]
        max_dd = 0.0
        for value in path:
            peak = max(peak, value)
            dd = peak - value
            max_dd = max(max_dd, dd)
        return max_dd

    @staticmethod
    def export(result: RiskSimulationResult) -> dict[str, Any]:
        return {
            "var_95": result.var_95,
            "cvar_95": result.cvar_95,
            "max_drawdown": result.max_drawdown,
            "stress_survival_rate": result.stress_survival_rate,
            "robustness": result.robustness,
            "details": result.details,
        }
