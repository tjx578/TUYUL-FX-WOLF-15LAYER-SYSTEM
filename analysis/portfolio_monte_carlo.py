"""L7 Extension: Portfolio-level Correlated Monte Carlo Simulation.

Simulates joint behaviour of multiple open/candidate pairs using a
correlation matrix, producing portfolio-level risk metrics that feed
into L12 as ADVISORY inputs.

Authority: analysis-only. No execution side-effects.
Zone: analysis/
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────
_DEFAULT_SIMULATIONS = 10_000
_DEFAULT_HORIZON_BARS = 20
_MAX_PORTFOLIO_DRAWDOWN = 0.10  # 10 % advisory threshold


@dataclass(frozen=True)
class PairSpec:
    """Single-pair input for portfolio MC."""

    symbol: str
    win_probability: float  # 0.0-1.0
    avg_win: float  # in account-currency units
    avg_loss: float  # positive magnitude
    current_exposure: float = 0.0  # lots or notional


@dataclass(frozen=True)
class PortfolioMCResult:
    """Output of a correlated multi-pair Monte Carlo run."""

    portfolio_win_rate: float
    portfolio_profit_factor: float
    portfolio_risk_of_ruin: float
    portfolio_max_drawdown: float
    portfolio_expected_value: float
    diversification_ratio: float  # 1.0 = uncorrelated, <1 = concentrated
    pair_contributions: dict[str, float] = field(default_factory=dict)
    correlation_matrix_used: list[list[float]] = field(default_factory=list)
    simulations: int = _DEFAULT_SIMULATIONS
    horizon_bars: int = _DEFAULT_HORIZON_BARS
    advisory_flag: str = "PASS"  # PASS / WARN / BLOCK (advisory, not binding)


def _build_correlation_matrix(
    symbols: list[str],
    historical_correlations: dict[tuple[str, str], float] | None = None,
) -> np.ndarray:
    """Build a symmetric PSD correlation matrix for the given symbols.

    Falls back to identity (uncorrelated) for missing pairs.
    """
    n = len(symbols)
    corr = np.eye(n)

    if historical_correlations:
        sym_idx = {s: i for i, s in enumerate(symbols)}
        for (s1, s2), rho in historical_correlations.items():
            i, j = sym_idx.get(s1), sym_idx.get(s2)
            if i is not None and j is not None and i != j:
                clamped = max(-0.99, min(0.99, rho))
                corr[i, j] = clamped
                corr[j, i] = clamped

    # Ensure PSD via nearest-PSD projection
    eigvals, eigvecs = np.linalg.eigh(corr)
    eigvals = np.maximum(eigvals, 1e-6)
    corr = eigvecs @ np.diag(eigvals) @ eigvecs.T
    # Re-normalize diagonal to 1.0
    d = np.sqrt(np.diag(corr))
    corr = corr / np.outer(d, d)

    return corr


def _simulate_correlated_returns(
    pair_specs: list[PairSpec],
    corr_matrix: np.ndarray,
    n_sims: int,
    horizon: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate correlated Bernoulli trade outcomes for each pair.

    Returns:
        (n_sims, horizon, n_pairs) array of PnL per bar.
    """
    n_pairs = len(pair_specs)
    # Cholesky decomposition for correlated normals
    chol = np.linalg.cholesky(corr_matrix)

    # Generate correlated uniform draws via Gaussian copula
    z = rng.standard_normal((n_sims, horizon, n_pairs))
    correlated_z = z @ chol.T
    # Convert to uniform via CDF
    from scipy.stats import norm  # noqa: PLC0415

    u = norm.cdf(correlated_z)

    # Convert uniform to PnL based on win_probability and avg_win/loss
    pnl = np.zeros_like(u)
    for idx, spec in enumerate(pair_specs):
        wins = u[:, :, idx] < spec.win_probability
        pnl[:, :, idx] = np.where(wins, spec.avg_win, -abs(spec.avg_loss))

    return pnl


def run_portfolio_monte_carlo(
    pair_specs: list[PairSpec],
    historical_correlations: dict[tuple[str, str], float] | None = None,
    n_simulations: int = _DEFAULT_SIMULATIONS,
    horizon_bars: int = _DEFAULT_HORIZON_BARS,
    ruin_threshold: float = -0.20,
    seed: int | None = None,
) -> PortfolioMCResult:
    """Run correlated multi-pair Monte Carlo simulation.

    This is an ANALYSIS function — it produces advisory metrics for L12.
    It has NO execution authority and NO side-effects.

    Args:
        pair_specs: List of per-pair inputs (symbol, win_prob, avg_win/loss).
        historical_correlations: Pairwise correlation overrides.
            Key is (symbol_a, symbol_b), value is Pearson rho [-1, 1].
            Missing pairs default to 0 (uncorrelated).
        n_simulations: Number of MC paths.
        horizon_bars: Bars per simulation path.
        ruin_threshold: Cumulative return below which a path is "ruined".
        seed: RNG seed for reproducibility (tests).

    Returns:
        PortfolioMCResult with portfolio-level metrics.
    """
    if not pair_specs:
        return PortfolioMCResult(
            portfolio_win_rate=0.0,
            portfolio_profit_factor=0.0,
            portfolio_risk_of_ruin=1.0,
            portfolio_max_drawdown=0.0,
            portfolio_expected_value=0.0,
            diversification_ratio=1.0,
            advisory_flag="BLOCK",
        )

    symbols = [p.symbol for p in pair_specs]
    rng = np.random.default_rng(seed)

    # ── Build correlation matrix ─────────────────────────────────────
    corr_matrix = _build_correlation_matrix(symbols, historical_correlations)

    # ── Simulate ─────────────────────────────────────────────────────
    pnl = _simulate_correlated_returns(pair_specs, corr_matrix, n_simulations, horizon_bars, rng)

    # ── Aggregate portfolio PnL per path ─────────────────────────────
    # Sum across pairs for each (sim, bar) → (n_sims, horizon)
    portfolio_pnl = pnl.sum(axis=2)
    cumulative = np.cumsum(portfolio_pnl, axis=1)

    # ── Metrics ──────────────────────────────────────────────────────
    final_values = cumulative[:, -1]
    winning_paths = (final_values > 0).sum()
    portfolio_win_rate = float(winning_paths / n_simulations)

    total_wins = float(portfolio_pnl[portfolio_pnl > 0].sum())
    total_losses = float(abs(portfolio_pnl[portfolio_pnl < 0].sum()))
    portfolio_pf = (total_wins / total_losses) if total_losses > 0 else float("inf")

    # Drawdown per path
    running_max = np.maximum.accumulate(cumulative, axis=1)
    drawdowns = cumulative - running_max
    max_dd_per_path = drawdowns.min(axis=1)
    portfolio_max_dd = float(np.median(max_dd_per_path))

    # Risk of ruin: fraction of paths that hit ruin_threshold
    ruin_count = (max_dd_per_path < ruin_threshold).sum()
    portfolio_ror = float(ruin_count / n_simulations)

    portfolio_ev = float(np.mean(final_values))

    # ── Diversification ratio ────────────────────────────────────────
    # Compare portfolio vol to sum of individual vols
    pair_vols = [float(pnl[:, :, i].std()) for i in range(len(pair_specs))]
    sum_individual_vol = sum(pair_vols)
    portfolio_vol = float(portfolio_pnl.std())
    div_ratio = portfolio_vol / sum_individual_vol if sum_individual_vol > 0 else 1.0

    # ── Per-pair contribution to portfolio EV ────────────────────────
    pair_contributions = {}
    for i, spec in enumerate(pair_specs):
        pair_ev = float(np.mean(np.sum(pnl[:, :, i], axis=1)))
        pair_contributions[spec.symbol] = round(pair_ev, 4)

    # ── Advisory flag ────────────────────────────────────────────────
    if portfolio_ror >= 0.20 or portfolio_max_dd < -_MAX_PORTFOLIO_DRAWDOWN:
        advisory_flag = "BLOCK"
    elif portfolio_ror >= 0.10 or div_ratio > 0.85:
        advisory_flag = "WARN"
    else:
        advisory_flag = "PASS"

    result = PortfolioMCResult(
        portfolio_win_rate=round(portfolio_win_rate, 4),
        portfolio_profit_factor=round(min(portfolio_pf, 99.99), 2),
        portfolio_risk_of_ruin=round(portfolio_ror, 4),
        portfolio_max_drawdown=round(portfolio_max_dd, 4),
        portfolio_expected_value=round(portfolio_ev, 2),
        diversification_ratio=round(div_ratio, 4),
        pair_contributions=pair_contributions,
        correlation_matrix_used=corr_matrix.tolist(),
        simulations=n_simulations,
        horizon_bars=horizon_bars,
        advisory_flag=advisory_flag,
    )

    logger.info(
        "Portfolio MC complete: %d pairs, %d sims, advisory=%s",
        len(pair_specs),
        n_simulations,
        advisory_flag,
    )

    return result
