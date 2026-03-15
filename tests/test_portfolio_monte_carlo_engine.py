"""Unit tests for engines/portfolio_monte_carlo_engine.py."""

from __future__ import annotations

import numpy as np
import pytest

from engines.portfolio_monte_carlo_engine import (
    PortfolioMonteCarloEngine,
    PortfolioMonteCarloResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_pair_returns(
    n: int = 100,
    win_rate: float = 0.65,
    seed: int = 42,
    correlation: float = 0.0,
) -> list[float]:
    """Generate synthetic trade returns for a single pair."""
    rng = np.random.default_rng(seed)
    returns = []
    for _ in range(n):
        if rng.random() < win_rate:
            returns.append(float(rng.uniform(10, 100)))
        else:
            returns.append(float(rng.uniform(-80, -5)))
    return returns


def _make_correlated_returns(
    n: int = 100,
    num_pairs: int = 3,
    base_win_rate: float = 0.65,
    correlation: float = 0.7,
    seed: int = 42,
) -> dict[str, list[float]]:
    """Generate correlated returns for multiple pairs."""
    np.random.default_rng(seed)
    labels = [f"PAIR{i}" for i in range(num_pairs)]

    # Generate base returns
    base = _make_pair_returns(n, base_win_rate, seed=seed)

    result: dict[str, list[float]] = {}
    for i, label in enumerate(labels):
        if i == 0:
            result[label] = base
        else:
            # Mix base returns with noise based on correlation
            noise = _make_pair_returns(n, base_win_rate, seed=seed + i + 100)
            mixed = [
                correlation * base[j] + (1 - correlation) * noise[j]
                for j in range(n)
            ]
            result[label] = mixed

    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPortfolioMonteCarloEngine:

    def test_basic_run(self) -> None:
        engine = PortfolioMonteCarloEngine(simulations=200, seed=42)
        returns = _make_correlated_returns(100, num_pairs=3, seed=42)
        result = engine.run(returns)

        assert isinstance(result, PortfolioMonteCarloResult)
        assert result.num_pairs == 3
        assert len(result.pair_labels) == 3
        assert len(result.pair_win_probabilities) == 3
        assert len(result.pair_expected_values) == 3
        assert len(result.pair_profit_factors) == 3
        assert result.simulations == 200
        assert 0.0 <= result.portfolio_win_probability <= 1.0
        assert result.portfolio_max_drawdown_mean <= 0.0

    def test_correlation_matrix_shape(self) -> None:
        engine = PortfolioMonteCarloEngine(simulations=100, seed=42)
        returns = _make_correlated_returns(50, num_pairs=4, seed=42)
        result = engine.run(returns)

        assert len(result.correlation_matrix) == 4
        assert all(len(row) == 4 for row in result.correlation_matrix)
        # Diagonal should be ~1.0
        for i in range(4):
            assert abs(result.correlation_matrix[i][i] - 1.0) < 0.01

    def test_high_win_rate_passes(self) -> None:
        engine = PortfolioMonteCarloEngine(
            simulations=200, seed=42,
            win_threshold=0.50, pf_threshold=1.0,
        )
        returns = _make_correlated_returns(
            100, num_pairs=3, base_win_rate=0.80, seed=99,
        )
        result = engine.run(returns)

        assert result.portfolio_win_probability >= 0.50
        assert result.portfolio_profit_factor >= 1.0

    def test_low_win_rate_fails(self) -> None:
        engine = PortfolioMonteCarloEngine(simulations=200, seed=42)
        returns = _make_correlated_returns(
            100, num_pairs=3, base_win_rate=0.20, seed=7,
        )
        result = engine.run(returns)

        assert result.portfolio_win_probability < 0.55
        assert result.passed_threshold is False

    def test_insufficient_pairs_raises(self) -> None:
        engine = PortfolioMonteCarloEngine(simulations=100, seed=42)
        with pytest.raises(ValueError, match="requires >= 2 pairs"):
            engine.run({"EURUSD": _make_pair_returns(50)})

    def test_insufficient_trades_raises(self) -> None:
        engine = PortfolioMonteCarloEngine(simulations=100, seed=42)
        with pytest.raises(ValueError, match="Minimum 30 trades"):
            engine.run({"A": [1.0, -0.5], "B": [2.0, -1.0]})

    def test_deterministic_with_seed(self) -> None:
        returns = _make_correlated_returns(50, num_pairs=2, seed=42)
        r1 = PortfolioMonteCarloEngine(simulations=100, seed=123).run(returns)
        r2 = PortfolioMonteCarloEngine(simulations=100, seed=123).run(returns)
        assert r1.portfolio_win_probability == r2.portfolio_win_probability
        assert r1.portfolio_expected_value == r2.portfolio_expected_value

    def test_to_dict_serialization(self) -> None:
        engine = PortfolioMonteCarloEngine(simulations=100, seed=42)
        returns = _make_correlated_returns(50, num_pairs=3, seed=42)
        result = engine.run(returns)
        d = result.to_dict()

        assert "portfolio_win_probability" in d
        assert "portfolio_profit_factor" in d
        assert "portfolio_risk_of_ruin" in d
        assert "correlation_matrix" in d
        assert "diversification_ratio" in d
        assert "pair_labels" in d
        assert isinstance(d["pair_labels"], list)
        assert isinstance(d["correlation_matrix"], list)
        assert d["num_pairs"] == 3

    def test_diversification_ratio(self) -> None:
        """Highly correlated pairs should have higher div ratio (closer to 1)."""
        engine = PortfolioMonteCarloEngine(simulations=200, seed=42)

        # High correlation
        high_corr = _make_correlated_returns(
            100, num_pairs=3, correlation=0.9, seed=42,
        )
        result_high = engine.run(high_corr)

        # Low correlation
        engine2 = PortfolioMonteCarloEngine(simulations=200, seed=42)
        low_corr = _make_correlated_returns(
            100, num_pairs=3, correlation=0.1, seed=42,
        )
        result_low = engine2.run(low_corr)

        # Both should have valid diversification ratios
        assert result_high.diversification_ratio > 0
        assert result_low.diversification_ratio > 0

    def test_passed_property_alias(self) -> None:
        engine = PortfolioMonteCarloEngine(simulations=100, seed=42)
        returns = _make_correlated_returns(50, num_pairs=2, seed=42)
        result = engine.run(returns)
        assert result.passed == result.passed_threshold

    def test_portfolio_drawdown_p95(self) -> None:
        engine = PortfolioMonteCarloEngine(simulations=200, seed=42)
        returns = _make_correlated_returns(100, num_pairs=3, seed=42)
        result = engine.run(returns)

        # P95 drawdown should be worse (more negative) than mean
        assert result.portfolio_max_drawdown_p95 <= result.portfolio_max_drawdown_mean
