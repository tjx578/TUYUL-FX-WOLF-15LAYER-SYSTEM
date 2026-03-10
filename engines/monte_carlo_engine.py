"""Single-pair Monte Carlo Engine for L7 probability validation.

Runs bootstrap simulations over historical per-trade returns and provides
risk and performance estimates consumed by `analysis.layers.L7_probability`.

Authority boundary:
    ANALYSIS-ONLY. No execution side-effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class MonteCarloResult:
    """Immutable output for a Monte Carlo simulation run."""

    win_probability: float
    profit_factor: float
    max_drawdown_mean: float
    max_drawdown_p95: float
    risk_of_ruin: float
    expected_value: float
    simulations: int
    passed_threshold: bool

    @property
    def passed(self) -> bool:
        """Backward-compatible alias used by older callers."""
        return self.passed_threshold

    def to_dict(self) -> dict[str, Any]:
        """Serialize result for pipeline and API payloads."""
        return {
            "win_probability": self.win_probability,
            "profit_factor": self.profit_factor,
            "max_drawdown_mean": self.max_drawdown_mean,
            "max_drawdown_p95": self.max_drawdown_p95,
            "risk_of_ruin": self.risk_of_ruin,
            "expected_value": self.expected_value,
            "simulations": self.simulations,
            "passed_threshold": self.passed_threshold,
        }


class MonteCarloEngine:
    """Bootstrap Monte Carlo simulator for single-symbol trade returns."""

    def __init__(
        self,
        simulations: int = 1000,
        seed: int | None = 42,
        min_trades: int = 30,
        win_threshold: float = 0.60,
        pf_threshold: float = 1.5,
        ruin_capital_fraction: float = 0.20,
    ) -> None:
        super().__init__()
        self.simulations = simulations
        self.min_trades = min_trades
        self.win_threshold = win_threshold
        self.pf_threshold = pf_threshold
        self.ruin_capital_fraction = ruin_capital_fraction
        self._rng = np.random.default_rng(seed)

    def run(self, returns: list[float], capital: float = 10_000.0) -> MonteCarloResult:
        """Run bootstrap MC over historical returns.

        Args:
            returns: Historical per-trade PnL samples.
            capital: Notional capital used for risk-of-ruin thresholding.

        Raises:
            ValueError: If insufficient trade samples are provided.
        """
        if len(returns) < self.min_trades:
            raise ValueError(
                f"Minimum {self.min_trades} trades required, got {len(returns)}"
            )

        arr = np.asarray(returns, dtype=np.float64)
        n = arr.shape[0]

        win_rates: list[float] = []
        profit_sums: list[float] = []
        loss_sums: list[float] = []
        total_pnls: list[float] = []
        min_drawdowns: list[float] = []

        ruin_threshold = -abs(capital * self.ruin_capital_fraction)
        ruin_count = 0

        for _ in range(self.simulations):
            idx: npt.NDArray[np.int64] = self._rng.integers(0, n, size=n)
            sampled = arr[idx]

            wins = sampled[sampled > 0]
            losses = sampled[sampled < 0]

            win_rates.append(float(wins.size / n))
            profit_sums.append(float(wins.sum()))
            loss_sums.append(float(abs(losses.sum())))

            total_pnl = float(sampled.sum())
            total_pnls.append(total_pnl)

            cumulative = np.cumsum(sampled)
            peaks = np.maximum.accumulate(cumulative)
            drawdowns = cumulative - peaks
            min_dd = float(drawdowns.min())
            min_drawdowns.append(min_dd)

            if min_dd <= ruin_threshold:
                ruin_count += 1

        mean_win_prob = float(np.mean(win_rates))
        mean_profit = float(np.mean(profit_sums))
        mean_loss = float(np.mean(loss_sums))
        pf = mean_profit / mean_loss if mean_loss > 0 else 0.0

        max_dd_mean = float(np.mean(min_drawdowns))
        max_dd_p95 = float(np.percentile(min_drawdowns, 5))
        ror = float(ruin_count / self.simulations)
        ev = float(np.mean(total_pnls))

        passed = bool(
            mean_win_prob >= self.win_threshold
            and pf >= self.pf_threshold
        )

        return MonteCarloResult(
            win_probability=round(mean_win_prob, 4),
            profit_factor=round(pf, 2),
            max_drawdown_mean=round(max_dd_mean, 2),
            max_drawdown_p95=round(max_dd_p95, 2),
            risk_of_ruin=round(ror, 4),
            expected_value=round(ev, 2),
            simulations=self.simulations,
            passed_threshold=passed,
        )
