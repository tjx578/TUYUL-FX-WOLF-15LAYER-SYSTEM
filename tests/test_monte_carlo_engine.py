"""Unit tests for engines/monte_carlo_engine.py."""

from __future__ import annotations

import numpy as np
import pytest

from engines.monte_carlo_engine import (
    MonteCarloEngine,
    MonteCarloResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_returns(n: int = 100, win_rate: float = 0.65, seed: int = 42) -> list[float]:
    """Generate synthetic trade returns."""
    rng = np.random.default_rng(seed)
    returns = []
    for _ in range(n):
        if rng.random() < win_rate:
            returns.append(float(rng.uniform(10, 100)))
        else:
            returns.append(float(rng.uniform(-80, -5)))
    return returns


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMonteCarloEngine:

    def test_basic_run(self) -> None:
        engine = MonteCarloEngine(simulations=500, seed=42)
        returns = _make_returns(100, win_rate=0.65)
        result = engine.run(returns)

        assert isinstance(result, MonteCarloResult)
        assert 0.0 <= result.win_probability <= 1.0
        assert result.simulations == 500
        assert result.max_drawdown_mean <= 0.0  # drawdown is negative

    def test_high_win_rate_passes(self) -> None:
        engine = MonteCarloEngine(simulations=500, seed=42)
        # Strongly positive returns
        returns = _make_returns(100, win_rate=0.80, seed=99)
        result = engine.run(returns)

        assert result.win_probability >= 0.60
        assert result.profit_factor >= 1.0

    def test_low_win_rate_fails(self) -> None:
        engine = MonteCarloEngine(simulations=500, seed=42)
        returns = _make_returns(100, win_rate=0.20, seed=7)
        result = engine.run(returns)

        assert result.win_probability < 0.60
        assert result.passed_threshold is False

    def test_insufficient_trades_raises(self) -> None:
        engine = MonteCarloEngine(simulations=100, seed=42)
        with pytest.raises(ValueError, match="Minimum 30 trades"):
            engine.run([1.0, -0.5, 2.0])

    def test_deterministic_with_seed(self) -> None:
        returns = _make_returns(50)
        r1 = MonteCarloEngine(simulations=200, seed=123).run(returns)
        r2 = MonteCarloEngine(simulations=200, seed=123).run(returns)
        assert r1.win_probability == r2.win_probability
        assert r1.expected_value == r2.expected_value

    def test_to_dict(self) -> None:
        engine = MonteCarloEngine(simulations=100, seed=42)
        returns = _make_returns(50)
        result = engine.run(returns)
        d = result.to_dict()

        assert "win_probability" in d
        assert "profit_factor" in d
        assert "risk_of_ruin" in d
        assert isinstance(d["simulations"], int)

    def test_custom_thresholds(self) -> None:
        engine = MonteCarloEngine(
            simulations=200,
            seed=42,
            win_threshold=0.70,
            pf_threshold=2.0,
        )
        returns = _make_returns(50, win_rate=0.65)
        result = engine.run(returns)
        # With higher thresholds, likely won't pass
        assert isinstance(result.passed_threshold, bool)
