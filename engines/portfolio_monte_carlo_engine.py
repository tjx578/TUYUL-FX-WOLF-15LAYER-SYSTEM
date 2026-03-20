"""Portfolio Monte Carlo Engine -- Multi-pair correlated simulation.

Extends single-pair Monte Carlo to simulate portfolio-level outcomes
using the empirical correlation structure across instruments.

Pipeline path:
    engines.portfolio_monte_carlo_engine -> L6/L7 risk -> L12 verdict

Uses Cholesky decomposition of the empirical correlation matrix to
generate correlated bootstrap samples, preserving cross-pair dependence.

ANALYSIS-ONLY module. No execution side-effects.
"""

from __future__ import annotations

import math

from dataclasses import dataclass
from typing import Any

import numpy as np


def _normal_cdf(x: np.ndarray) -> np.ndarray:
    """Approximate standard normal CDF using the error function.

    Uses the standard library math.erf -- no scipy needed.
    Accuracy: ~1e-7 (sufficient for bootstrap index generation).
    """
    return 0.5 * (1.0 + np.vectorize(math.erf)(x / np.sqrt(2.0)))


from numpy.typing import NDArray  # noqa: E402


@dataclass(frozen=True)
class PortfolioMonteCarloResult:
    """Result of portfolio-level correlated Monte Carlo simulation."""

    # Per-pair results
    pair_labels: tuple[str, ...]
    pair_win_probabilities: tuple[float, ...]
    pair_expected_values: tuple[float, ...]
    pair_profit_factors: tuple[float, ...]

    # Portfolio-level aggregates
    portfolio_win_probability: float
    portfolio_expected_value: float
    portfolio_profit_factor: float
    portfolio_risk_of_ruin: float
    portfolio_max_drawdown_mean: float
    portfolio_max_drawdown_p95: float

    # Correlation & diversification
    correlation_matrix: tuple[tuple[float, ...], ...]
    diversification_ratio: float  # 1.0 = no diversification, <1 = good

    # Metadata
    simulations: int
    num_pairs: int
    passed_threshold: bool

    @property
    def passed(self) -> bool:
        return self.passed_threshold

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON / pipeline consumption."""
        return {
            "pair_labels": list(self.pair_labels),
            "pair_win_probabilities": list(self.pair_win_probabilities),
            "pair_expected_values": list(self.pair_expected_values),
            "pair_profit_factors": list(self.pair_profit_factors),
            "portfolio_win_probability": self.portfolio_win_probability,
            "portfolio_expected_value": self.portfolio_expected_value,
            "portfolio_profit_factor": self.portfolio_profit_factor,
            "portfolio_risk_of_ruin": self.portfolio_risk_of_ruin,
            "portfolio_max_drawdown_mean": self.portfolio_max_drawdown_mean,
            "portfolio_max_drawdown_p95": self.portfolio_max_drawdown_p95,
            "correlation_matrix": [list(row) for row in self.correlation_matrix],
            "diversification_ratio": self.diversification_ratio,
            "simulations": self.simulations,
            "num_pairs": self.num_pairs,
            "passed_threshold": self.passed_threshold,
        }


class PortfolioMonteCarloEngine:
    """Correlated multi-pair Monte Carlo simulator.

    Generates correlated bootstrap samples using Cholesky decomposition
    of the empirical correlation matrix. Each simulation draws a full
    portfolio trade sequence, preserving cross-pair dependence.

    Parameters
    ----------
    simulations : int
        Number of bootstrap iterations (default 1000).
    seed : int | None
        RNG seed for reproducibility.
    min_trades : int
        Minimum trades per pair required (default 30).
    win_threshold : float
        Minimum portfolio win-rate to pass (default 0.55).
    pf_threshold : float
        Minimum portfolio profit factor to pass (default 1.3).
    ruin_capital_fraction : float
        Fraction of capital for risk-of-ruin (default 0.20).
    max_dd_threshold : float
        Maximum allowed portfolio drawdown (absolute, default 0.15 = 15%).
    """

    def __init__(
        self,
        simulations: int = 1000,
        seed: int | None = 42,
        min_trades: int = 30,
        win_threshold: float = 0.55,
        pf_threshold: float = 1.3,
        ruin_capital_fraction: float = 0.20,
        max_dd_threshold: float = 0.15,
    ) -> None:
        self.simulations = simulations
        self.min_trades = min_trades
        self.win_threshold = win_threshold
        self.pf_threshold = pf_threshold
        self.ruin_capital_fraction = ruin_capital_fraction
        self.max_dd_threshold = max_dd_threshold
        self._rng = np.random.default_rng(seed)

    def run(
        self,
        return_matrix: dict[str, list[float]],
        capital: float = 10_000.0,
    ) -> PortfolioMonteCarloResult:
        """Run correlated portfolio Monte Carlo simulation.

        Args:
            return_matrix: Dict of {pair_label: [trade_returns...]}.
                All pair return series must have the same length.
            capital: Notional portfolio capital for risk-of-ruin.

        Returns:
            PortfolioMonteCarloResult with per-pair and portfolio metrics.

        Raises:
            ValueError: If fewer than 2 pairs or insufficient trades.
        """
        labels = list(return_matrix.keys())
        num_pairs = len(labels)

        if num_pairs < 2:
            raise ValueError(
                f"Portfolio MC requires >= 2 pairs, got {num_pairs}. "
                f"Use MonteCarloEngine for single-pair simulation."
            )

        # Build matrix (num_pairs x num_trades)
        lengths = [len(return_matrix[lbl]) for lbl in labels]
        min_len = min(lengths)

        if min_len < self.min_trades:
            raise ValueError(
                f"Minimum {self.min_trades} trades per pair required, "
                f"shortest series has {min_len}"
            )

        # Truncate all to shortest length for alignment
        mat = np.array(
            [return_matrix[lbl][:min_len] for lbl in labels],
            dtype=np.float64,
        )
        # mat shape: (num_pairs, num_trades)
        n_trades = mat.shape[1]

        # ── Compute empirical correlation ────────────────────────────
        corr_matrix: NDArray[np.float64] = np.atleast_2d(
            np.asarray(np.corrcoef(mat), dtype=np.float64)
        )
        corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)
        # Ensure symmetric positive semi-definite
        corr_matrix = self._nearest_psd(corr_matrix)

        # ── Cholesky decomposition for correlated sampling ───────────
        try:
            cholesky = np.linalg.cholesky(corr_matrix)
        except np.linalg.LinAlgError:
            # Fallback: use eigenvalue adjustment
            corr_matrix = self._nearest_psd(corr_matrix, aggressive=True)
            cholesky = np.linalg.cholesky(corr_matrix)

        # ── Per-pair statistics ──────────────────────────────────────
        mat.mean(axis=1)
        pair_stds = mat.std(axis=1)
        # Protect against zero std
        pair_stds = np.where(pair_stds == 0, 1e-10, pair_stds)

        # ── Run simulations ──────────────────────────────────────────
        portfolio_pnls: list[float] = []
        portfolio_drawdowns: list[float] = []
        portfolio_ruin_flags: list[bool] = []
        pair_sim_pnls = np.zeros((num_pairs, self.simulations), dtype=np.float64)
        pair_win_counts = np.zeros(num_pairs, dtype=np.float64)
        pair_profit_sums = np.zeros(num_pairs, dtype=np.float64)
        pair_loss_sums = np.zeros(num_pairs, dtype=np.float64)
        ruin_threshold = -capital * self.ruin_capital_fraction

        for _ in range(self.simulations):
            # Generate correlated uniform indices via copula approach
            # Draw independent standard normals, then correlate
            z = self._rng.standard_normal(size=(num_pairs, n_trades))
            correlated_z = cholesky @ z  # Apply correlation structure

            # Convert correlated normals to bootstrap indices
            # Use CDF to get uniform, then map to indices
            uniform = _normal_cdf(correlated_z)
            indices = np.clip((uniform * n_trades).astype(int), 0, n_trades - 1)

            # Sample returns using correlated indices
            sampled = np.array([mat[p, indices[p]] for p in range(num_pairs)])
            # sampled shape: (num_pairs, n_trades)

            # Per-pair metrics for this simulation
            for p in range(num_pairs):
                wins = sampled[p][sampled[p] > 0]
                losses = sampled[p][sampled[p] < 0]
                pair_win_counts[p] += len(wins) / len(sampled[p])
                pair_profit_sums[p] += float(wins.sum())
                pair_loss_sums[p] += float(abs(losses.sum()))

            pair_sim_pnls[:, len(portfolio_pnls)] = sampled.sum(axis=1)

            # Portfolio P&L = sum across pairs per time step
            portfolio_returns = sampled.sum(axis=0)
            total_pnl = float(portfolio_returns.sum())
            portfolio_pnls.append(total_pnl)

            # Portfolio drawdown and path-based ruin
            cumulative = np.cumsum(portfolio_returns)
            peak = np.maximum.accumulate(cumulative)
            dd = cumulative - peak
            portfolio_drawdowns.append(float(np.min(dd)))
            portfolio_ruin_flags.append(bool(np.any(cumulative <= ruin_threshold)))

        # ── Aggregate results ────────────────────────────────────────
        pair_win_probs = tuple(
            round(float(pair_win_counts[p] / self.simulations), 4)
            for p in range(num_pairs)
        )
        pair_evs = tuple(
            round(float(pair_profit_sums[p] - pair_loss_sums[p]) / self.simulations, 2)
            for p in range(num_pairs)
        )
        pair_pfs = tuple(
            round(
                (
                    float(pair_profit_sums[p] / pair_loss_sums[p])
                    if pair_loss_sums[p] > 0
                    else (float("inf") if pair_profit_sums[p] > 0 else 0.0)
                ),
                2,
            )
            for p in range(num_pairs)
        )

        portfolio_win_prob = float(
            np.mean([1.0 if pnl > 0 else 0.0 for pnl in portfolio_pnls])
        )
        portfolio_ev = float(np.mean(portfolio_pnls))
        total_portfolio_profit = sum(max(0, p) for p in portfolio_pnls)
        total_portfolio_loss = sum(abs(min(0, p)) for p in portfolio_pnls)
        portfolio_pf = (
            total_portfolio_profit / total_portfolio_loss
            if total_portfolio_loss > 0
            else (float("inf") if total_portfolio_profit > 0 else 0.0)
        )

        portfolio_ror = float(np.mean(portfolio_ruin_flags))

        mean_dd = float(np.mean(portfolio_drawdowns))
        p95_dd = float(np.percentile(np.abs(portfolio_drawdowns), 95))

        # ── Diversification ratio ────────────────────────────────────
        # Ratio of portfolio vol to sum of individual vols
        # < 1.0 means diversification is working
        individual_vols = np.std(pair_sim_pnls, axis=1)
        portfolio_vol = np.std(portfolio_pnls) if len(portfolio_pnls) > 1 else 1e-10
        sum_vols = float(individual_vols.sum())
        div_ratio = round(float(portfolio_vol / sum_vols) if sum_vols > 0 else 1.0, 4)

        # ── Pass/fail ────────────────────────────────────────────────
        passed = (
            portfolio_win_prob >= self.win_threshold
            and portfolio_pf >= self.pf_threshold
            and abs(mean_dd) / capital <= self.max_dd_threshold
        )

        return PortfolioMonteCarloResult(
            pair_labels=tuple(labels),
            pair_win_probabilities=pair_win_probs,
            pair_expected_values=pair_evs,
            pair_profit_factors=pair_pfs,
            portfolio_win_probability=round(portfolio_win_prob, 4),
            portfolio_expected_value=round(portfolio_ev, 2),
            portfolio_profit_factor=round(portfolio_pf, 2),
            portfolio_risk_of_ruin=round(portfolio_ror, 4),
            portfolio_max_drawdown_mean=round(mean_dd, 2),
            portfolio_max_drawdown_p95=round(p95_dd, 2),
            correlation_matrix=tuple(
                tuple(round(float(c), 4) for c in row) for row in corr_matrix
            ),
            diversification_ratio=div_ratio,
            simulations=self.simulations,
            num_pairs=num_pairs,
            passed_threshold=passed,
        )

    @staticmethod
    def _nearest_psd(
        matrix: NDArray[np.float64],
        aggressive: bool = False,
    ) -> NDArray[np.float64]:
        """Adjust correlation matrix to be positive semi-definite.

        Uses eigenvalue clipping. If aggressive=True, uses a larger
        floor for numerical stability with Cholesky.
        """
        eigenvalues, eigenvectors = np.linalg.eigh(matrix)
        floor = 1e-4 if aggressive else 1e-8
        eigenvalues = np.maximum(eigenvalues, floor)
        adjusted = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
        # Renormalize diagonal to 1.0 (correlation matrix)
        d = np.sqrt(np.diag(adjusted))
        d = np.where(d == 0, 1e-10, d)
        adjusted = adjusted / np.outer(d, d)
        np.fill_diagonal(adjusted, 1.0)
        return adjusted
