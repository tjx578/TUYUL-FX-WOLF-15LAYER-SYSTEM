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
