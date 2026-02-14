"""
Cognitive Risk Simulation v2.0.

Role:
  - Scenario stress testing (bootstrap Monte Carlo)
  - Tail-risk awareness (VaR/CVaR estimation)
  - Robustness estimation under adverse conditions

Integration:
  - Uses Monte Carlo-style path resampling for return distribution estimation
  - Adds stress-testing scenarios (drawdown, gap events)
  - Produces risk-adjusted robustness score

This module is advisory-only and does not make execution decisions.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import random
import statistics
from typing import Any, Dict, List, Optional


@dataclass
class RiskSimulationResult:
    """Result of risk simulation analysis."""

    robustness_estimate: float
    tail_risk_flag: bool
    var_95: float
    cvar_95: float
    max_drawdown_estimate: float
    stress_survival_rate: float
    notes: str
    details: Dict[str, Any] = field(default_factory=dict)


class CognitiveRiskSimulation:
    """Run lightweight Monte Carlo stress simulations for risk awareness."""

    def __init__(
        self,
        iterations: int = 500,
        stress_multiplier: float = 2.0,
        seed: Optional[int] = None,
        confidence_level: float = 0.95,
    ) -> None:
        self.iterations = max(100, iterations)
        self.stress_multiplier = stress_multiplier
        self.confidence = confidence_level
        self._seed = seed if seed is not None else int(
            datetime.now(timezone.utc).timestamp() * 1000
        ) % (2**31)
        self._rng = random.Random(self._seed)

    def simulate(self, inputs: Dict[str, Any]) -> RiskSimulationResult:
        """Run risk simulation using historical return samples."""
        returns = inputs.get("returns", [])
        if not returns or len(returns) < 5:
            return RiskSimulationResult(
                robustness_estimate=0.0,
                tail_risk_flag=True,
                var_95=0.0,
                cvar_95=0.0,
                max_drawdown_estimate=0.0,
                stress_survival_rate=0.0,
                notes="Insufficient return data (min 5 required)",
            )

        stop_loss_pct = float(inputs.get("stop_loss_pct", 0.02))
        balance = float(inputs.get("account_balance", 10000.0))

        normal_paths = self._bootstrap_paths(returns, self.iterations)
        normal_returns = [sum(path) for path in normal_paths]

        stressed_returns = [value * self.stress_multiplier for value in returns]
        stress_paths = self._bootstrap_paths(stressed_returns, self.iterations // 2)
        stress_returns = [sum(path) for path in stress_paths]

        gap_returns = self._inject_gap_events(returns, self.iterations // 4)

        all_returns = sorted(normal_returns)
        var_index = int(len(all_returns) * (1.0 - self.confidence))
        var_95 = all_returns[var_index] if var_index < len(all_returns) else all_returns[0]
        cvar_95 = (
            statistics.fmean(all_returns[: var_index + 1]) if var_index > 0 else var_95
        )

        max_drawdown = self._estimate_max_drawdown(normal_paths)
        stress_drawdown = self._estimate_max_drawdown(stress_paths)

        survival_threshold = -stop_loss_pct * balance * 3
        survived = sum(1 for value in stress_returns if value > survival_threshold)
        survival_rate = survived / len(stress_returns) if stress_returns else 0.0

        std_dev = statistics.pstdev(normal_returns) if len(normal_returns) > 1 else 1.0
        mean_return = statistics.fmean(normal_returns)
        tail_risk = (abs(cvar_95) > abs(mean_return) + 3 * std_dev) or survival_rate < 0.6

        win_rate = sum(1 for value in normal_returns if value > 0) / len(normal_returns)
        profit_factor = self._profit_factor(normal_returns)
        robustness = self._clamp(
            win_rate * 0.3
            + min(1.0, profit_factor / 3.0) * 0.3
            + survival_rate * 0.25
            + (1.0 - min(1.0, abs(max_drawdown) * 10)) * 0.15
        )

        notes = []
        if tail_risk:
            notes.append("TAIL_RISK_DETECTED")
        if survival_rate < 0.7:
            notes.append(f"LOW_STRESS_SURVIVAL({survival_rate:.0%})")
        if max_drawdown < -0.1:
            notes.append(f"HIGH_DRAWDOWN({max_drawdown:.1%})")
        if not notes:
            notes.append("WITHIN_NORMAL_PARAMETERS")

        return RiskSimulationResult(
            robustness_estimate=round(robustness, 4),
            tail_risk_flag=tail_risk,
            var_95=round(var_95, 6),
            cvar_95=round(cvar_95, 6),
            max_drawdown_estimate=round(max_drawdown, 6),
            stress_survival_rate=round(survival_rate, 4),
            notes=" | ".join(notes),
            details={
                "iterations": self.iterations,
                "win_rate": round(win_rate, 4),
                "profit_factor": round(profit_factor, 4),
                "mean_return": round(mean_return, 6),
                "std_dev": round(std_dev, 6),
                "stress_max_dd": round(stress_drawdown, 6),
                "gap_worst": round(min(gap_returns) if gap_returns else 0.0, 6),
                "seed": self._seed,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def export(self, result: RiskSimulationResult) -> Dict[str, Any]:
        """Serialize result into plain dictionary."""
        return {
            "robustness_estimate": result.robustness_estimate,
            "tail_risk_flag": result.tail_risk_flag,
            "var_95": result.var_95,
            "cvar_95": result.cvar_95,
            "max_drawdown_estimate": result.max_drawdown_estimate,
            "stress_survival_rate": result.stress_survival_rate,
            "notes": result.notes,
            "details": result.details,
        }

    def _bootstrap_paths(self, returns: List[float], n_paths: int) -> List[List[float]]:
        """Generate bootstrap resampled paths."""
        path_len = len(returns)
        return [self._rng.choices(returns, k=path_len) for _ in range(n_paths)]

    def _inject_gap_events(self, returns: List[float], n_scenarios: int) -> List[float]:
        """Simulate gap events (extreme adverse moves)."""
        if not returns:
            return []
        std = statistics.pstdev(returns) if len(returns) > 1 else abs(returns[0])
        gap_results: List[float] = []
        for _ in range(n_scenarios):
            path = self._rng.choices(returns, k=len(returns))
            for _ in range(self._rng.randint(1, 3)):
                idx = self._rng.randint(0, len(path) - 1)
                path[idx] = -abs(self._rng.uniform(3, 5) * std)
            gap_results.append(sum(path))
        return gap_results

    def _estimate_max_drawdown(self, paths: List[List[float]]) -> float:
        """Estimate worst drawdown across all simulated paths."""
        worst_drawdown = 0.0
        for path in paths:
            cumulative = 0.0
            peak = 0.0
            for value in path:
                cumulative += value
                peak = max(peak, cumulative)
                drawdown = (cumulative - peak) / max(abs(peak), 1e-10)
                worst_drawdown = min(worst_drawdown, drawdown)
        return worst_drawdown

    @staticmethod
    def _profit_factor(returns: List[float]) -> float:
        """Compute profit factor (gross profit / gross loss)."""
        gross_profit = sum(value for value in returns if value > 0)
        gross_loss = abs(sum(value for value in returns if value < 0))
        if gross_loss == 0:
            return 10.0 if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    @staticmethod
    def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
        """Clamp a value into [lo, hi]."""
        return max(lo, min(hi, value))


__all__ = ["RiskSimulationResult", "CognitiveRiskSimulation"]
