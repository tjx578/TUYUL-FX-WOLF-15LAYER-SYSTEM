"""Monte Carlo Engine -- Layer-7 probability simulation.

Runs bootstrap Monte Carlo simulations over historical trade returns
to estimate win probability, profit factor, risk of ruin, and drawdown.

IMPORTANT: This is the Monte Carlo engine that feeds L12 verdicts.
    Pipeline path: engines.monte_carlo_engine -> analysis.layers.L7_probability -> L12
    Sibling engine: core/core_fusion/monte_carlo.py (FTTC confidence simulation,
                    used by the core fusion layer -- NOT the L7->L12 path).

ANALYSIS-ONLY module. No execution side-effects.
"""  # noqa: N999

from __future__ import annotations

from dataclasses import dataclass

import numpy as np  # pyright: ignore[reportMissingImports]


@dataclass
class MonteCarloResult:
    """Result of Monte Carlo probability simulation."""

    win_probability: float
    expected_value: float
    profit_factor: float
    risk_of_ruin: float
    max_drawdown_mean: float
    simulations: int
    passed_threshold: bool

    # ------------------------------------------------------------
    # Backward Compatibility Alias
    # ------------------------------------------------------------

    @property
    def passed(self):
        return self.passed_threshold

    def to_dict(self) -> dict[str, float | int | bool]:
        return {
            "win_probability": self.win_probability,
            "expected_value": self.expected_value,
            "profit_factor": self.profit_factor,
            "risk_of_ruin": self.risk_of_ruin,
            "max_drawdown_mean": self.max_drawdown_mean,
            "simulations": self.simulations,
            "passed_threshold": self.passed_threshold,
        }


class MonteCarloEngine:
    """Bootstrap Monte Carlo simulator for trade return sequences.

    Parameters
    ----------
    simulations : int
        Number of bootstrap iterations (default 1000).
    seed : int | None
        RNG seed for reproducibility.
    min_trades : int
        Minimum trade count required to run (default 30).
    win_threshold : float
        Minimum mean win-rate to pass (default 0.60).
    pf_threshold : float
        Minimum profit factor to pass (default 1.5).
    ruin_capital_fraction : float
        Fraction of capital used for risk-of-ruin calc (default 0.20).
    """

    def __init__(
        self,
        simulations: int = 1000,
        seed: int | None = 42,
        min_trades: int = 30,
        win_threshold: float = 0.60,
        pf_threshold: float = 1.5,
        ruin_capital_fraction: float = 0.20,
    ) -> None:
        self.simulations = simulations
        self.min_trades = min_trades
        self.win_threshold = win_threshold
        self.pf_threshold = pf_threshold
        self.ruin_capital_fraction = ruin_capital_fraction
        self._rng = np.random.default_rng(seed)

    def run(
        self,
        trade_returns: list[float],
        capital: float = 10000.0,
    ) -> MonteCarloResult:
        """Run Monte Carlo bootstrap simulation.

        Args:
            trade_returns: List of per-trade P&L values.
            capital: Notional capital for risk-of-ruin calculation.

        Returns:
            MonteCarloResult with aggregated statistics.

        Raises:
            ValueError: If fewer than ``min_trades`` returns provided.
        """
        if len(trade_returns) < self.min_trades:
            raise ValueError(
                f"Minimum {self.min_trades} trades required for Monte Carlo simulation, "
                f"got {len(trade_returns)}"
            )

        arr = np.asarray(trade_returns, dtype=np.float64)
        n = len(arr)

        win_rate_list: list[float] = []
        drawdowns: list[float] = []
        total_profits: list[float] = []
        profit_factors: list[float] = []

        for _ in range(self.simulations):
            indices = self._rng.integers(0, n, size=n)
            sample = arr[indices]

            wins = sample[sample > 0]
            losses = sample[sample < 0]

            win_rate = float(len(wins) / len(sample))
            win_rate_list.append(win_rate)

            gross_profit = float(wins.sum())
            gross_loss = float(abs(losses.sum()))

            pf = gross_profit / gross_loss if gross_loss > 0 else 0.0
            profit_factors.append(pf)

            cumulative = np.cumsum(sample)
            peak = np.maximum.accumulate(cumulative)
            dd = cumulative - peak
            drawdowns.append(float(np.min(dd)))

            total_profits.append(float(sample.sum()))

        mean_win_prob = float(np.mean(win_rate_list))
        mean_drawdown = float(np.mean(drawdowns))
        expected_value = float(np.mean(total_profits))
        mean_pf = float(np.mean(profit_factors))

        ruin_threshold = -capital * self.ruin_capital_fraction
        risk_of_ruin = float(np.mean(np.asarray(total_profits) < ruin_threshold))

        passed = mean_win_prob >= self.win_threshold and mean_pf >= self.pf_threshold

        return MonteCarloResult(
            win_probability=round(mean_win_prob, 4),
            expected_value=round(expected_value, 2),
            profit_factor=round(mean_pf, 2),
            risk_of_ruin=round(risk_of_ruin, 4),
            max_drawdown_mean=round(mean_drawdown, 2),
            simulations=self.simulations,
            passed_threshold=passed,
        )
