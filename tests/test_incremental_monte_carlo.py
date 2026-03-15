"""Tests for analysis/incremental_monte_carlo.py — Cache-aware MC engine."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from analysis.incremental_monte_carlo import (
    IncrementalDelta,
    IncrementalMonteCarlo,
    MCCacheEntry,
)
from analysis.portfolio_monte_carlo import PairSpec, PortfolioMCResult


def _pair(symbol: str, win_prob: float = 0.55, avg_win: float = 100.0, avg_loss: float = 80.0) -> PairSpec:
    return PairSpec(
        symbol=symbol,
        win_probability=win_prob,
        avg_win=avg_win,
        avg_loss=avg_loss,
    )


def _fake_mc_result() -> PortfolioMCResult:
    return PortfolioMCResult(
        portfolio_win_rate=0.55,
        portfolio_profit_factor=1.3,
        portfolio_risk_of_ruin=0.05,
        portfolio_max_drawdown=-0.08,
        portfolio_expected_value=100.0,
        diversification_ratio=0.7,
        advisory_flag="PASS",
    )


@pytest.fixture(autouse=True)
def _mock_mc_engine():
    """Mock the underlying MC simulation to avoid scipy dependency."""
    with patch(
        "analysis.incremental_monte_carlo.run_portfolio_monte_carlo",
        side_effect=lambda *a, **kw: _fake_mc_result(),
    ):
        yield


class TestFullRun:
    """Full MC run and caching."""

    def test_full_run_returns_result(self):
        mc = IncrementalMonteCarlo(n_simulations_full=500)
        result = mc.run_full(
            [_pair("EURUSD"), _pair("GBPUSD")],
            seed=42,
        )
        assert isinstance(result, PortfolioMCResult)
        assert result.advisory_flag in ("PASS", "WARN", "BLOCK")

    def test_full_run_populates_cache(self):
        mc = IncrementalMonteCarlo(n_simulations_full=500)
        mc.run_full([_pair("EURUSD")], seed=42)
        cache = mc.get_cached()
        assert cache is not None
        assert cache.is_incremental is False

    def test_empty_specs_returns_block(self):
        mc = IncrementalMonteCarlo(n_simulations_full=500)
        result = mc.run_full([], seed=42)
        assert result.advisory_flag == "BLOCK"
        assert result.portfolio_risk_of_ruin == 1.0


class TestIncrementalAdd:
    """Incremental pair addition."""

    def test_add_pair_with_fresh_cache(self):
        mc = IncrementalMonteCarlo(
            n_simulations_full=500,
            n_simulations_incremental=200,
            staleness_seconds=600,
        )
        mc.run_full([_pair("EURUSD")], seed=42)

        result, delta = mc.add_pair(_pair("GBPUSD"), seed=42)
        assert isinstance(result, PortfolioMCResult)
        assert delta is not None
        assert isinstance(delta, IncrementalDelta)
        assert delta.delta_type == "ADD"
        assert delta.symbol == "GBPUSD"

    def test_add_pair_with_stale_cache_runs_full(self):
        mc = IncrementalMonteCarlo(
            n_simulations_full=500,
            n_simulations_incremental=200,
            staleness_seconds=0,  # Immediately stale
        )
        mc.run_full([_pair("EURUSD")], seed=42)
        # Force staleness
        time.sleep(0.01)

        result, delta = mc.add_pair(_pair("GBPUSD"), seed=42)
        assert isinstance(result, PortfolioMCResult)
        assert delta is None  # Full rerun, no delta

    def test_add_pair_without_cache_runs_full(self):
        mc = IncrementalMonteCarlo(n_simulations_full=500)
        result, delta = mc.add_pair(_pair("EURUSD"), seed=42)
        assert isinstance(result, PortfolioMCResult)
        assert delta is None  # No prior cache → full run


class TestIncrementalRemove:
    """Incremental pair removal (trade close)."""

    def test_remove_pair_returns_updated_result(self):
        mc = IncrementalMonteCarlo(
            n_simulations_full=500,
            n_simulations_incremental=200,
        )
        mc.run_full([_pair("EURUSD"), _pair("GBPUSD")], seed=42)

        result, delta = mc.remove_pair("EURUSD", seed=42)
        assert isinstance(result, PortfolioMCResult)
        assert delta is not None
        assert delta.delta_type == "REMOVE"
        assert delta.symbol == "EURUSD"

    def test_remove_last_pair_returns_empty(self):
        mc = IncrementalMonteCarlo(n_simulations_full=500)
        mc.run_full([_pair("EURUSD")], seed=42)

        result, delta = mc.remove_pair("EURUSD", seed=42)
        assert result.portfolio_risk_of_ruin == 0.0
        assert result.advisory_flag == "PASS"

    def test_remove_nonexistent_pair(self):
        mc = IncrementalMonteCarlo(n_simulations_full=500)
        mc.run_full([_pair("EURUSD"), _pair("GBPUSD")], seed=42)

        # Removing a pair not in the portfolio just returns same result
        result, delta = mc.remove_pair("XAUUSD", seed=42)
        assert isinstance(result, PortfolioMCResult)


class TestCacheInvalidation:
    """Manual cache invalidation."""

    def test_invalidate_clears_cache(self):
        mc = IncrementalMonteCarlo(n_simulations_full=500)
        mc.run_full([_pair("EURUSD")], seed=42)
        assert mc.get_cached() is not None

        mc.invalidate()
        assert mc.get_cached() is None

    def test_invalidate_forces_full_rerun(self):
        mc = IncrementalMonteCarlo(
            n_simulations_full=500,
            n_simulations_incremental=200,
        )
        mc.run_full([_pair("EURUSD")], seed=42)
        mc.invalidate()

        # Next add should be full run (no delta)
        result, delta = mc.add_pair(_pair("GBPUSD"), seed=42)
        assert delta is None


class TestStalenessInfo:
    """Cache staleness reporting."""

    def test_no_cache_returns_stale(self):
        mc = IncrementalMonteCarlo()
        info = mc.get_staleness_info()
        assert info["has_cache"] is False
        assert info["is_stale"] is True

    def test_fresh_cache_reports_age(self):
        mc = IncrementalMonteCarlo(
            n_simulations_full=500,
            staleness_seconds=600,
        )
        mc.run_full([_pair("EURUSD")], seed=42)
        info = mc.get_staleness_info()
        assert info["has_cache"] is True
        assert info["is_stale"] is False
        assert info["age_seconds"] < 5.0


class TestMCCacheEntry:
    """MCCacheEntry properties."""

    def test_age_increases(self):
        result = PortfolioMCResult(
            portfolio_win_rate=0.55,
            portfolio_profit_factor=1.2,
            portfolio_risk_of_ruin=0.05,
            portfolio_max_drawdown=-0.08,
            portfolio_expected_value=100.0,
            diversification_ratio=0.7,
        )
        entry = MCCacheEntry(
            result=result,
            computed_at=time.time() - 100,
            pair_hash="abc123",
            n_simulations=1000,
        )
        assert entry.age_seconds >= 100.0

    def test_staleness_detection(self):
        result = PortfolioMCResult(
            portfolio_win_rate=0.55,
            portfolio_profit_factor=1.2,
            portfolio_risk_of_ruin=0.05,
            portfolio_max_drawdown=-0.08,
            portfolio_expected_value=100.0,
            diversification_ratio=0.7,
        )
        # Fresh
        entry = MCCacheEntry(
            result=result,
            computed_at=time.time(),
            pair_hash="abc",
            n_simulations=1000,
        )
        assert not entry.is_stale

        # Stale
        old_entry = MCCacheEntry(
            result=result,
            computed_at=time.time() - 999,
            pair_hash="abc",
            n_simulations=1000,
        )
        assert old_entry.is_stale
