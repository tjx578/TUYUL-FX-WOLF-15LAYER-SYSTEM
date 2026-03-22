"""Tests: CorrelationRiskEngine integration INTO L6 Capital Firewall.

Verifies that when ``pair_returns`` (multi-pair return dict) is provided,
L6 uses pairwise correlation risk internally to dampen risk_multiplier
and set CORRELATION_STRESS status when correlated pairs are detected.

Updated for L6 v4 API: correlation engine fields are used internally
(not exposed as raw result keys).

Authority: ANALYSIS ZONE only. No execution side-effects.
"""

from __future__ import annotations

import numpy as np

from analysis.layers.L6_risk import L6RiskAnalyzer, _corr_engine

# -- Fixtures -----------------------------------------------------------------


def _multi_pair_low_corr(
    n_pairs: int = 4,
    n_obs: int = 100,
    seed: int = 42,
) -> dict[str, list[float]]:
    """Generate independent (low-correlation) return series per pair."""
    rng = np.random.default_rng(seed)
    pairs = [f"PAIR{i}" for i in range(n_pairs)]
    return {p: [float(x) for x in rng.normal(0, 1, n_obs)] for p in pairs}


def _multi_pair_high_corr(
    n_obs: int = 100,
    seed: int = 42,
) -> dict[str, list[float]]:
    """Generate highly correlated pair returns (simulating USD exposure)."""
    rng = np.random.default_rng(seed)
    base = rng.normal(0, 1, n_obs)
    noise_scale = 0.05  # tiny noise -> near-perfect correlation
    return {
        "EURUSD": [float(x) for x in base + rng.normal(0, noise_scale, n_obs)],
        "GBPUSD": [float(x) for x in base + rng.normal(0, noise_scale, n_obs)],
        "AUDUSD": [float(x) for x in base + rng.normal(0, noise_scale, n_obs)],
    }


# -- Prerequisite -------------------------------------------------------------


class TestPrerequisite:
    def test_engine_loaded(self) -> None:
        assert _corr_engine is not None, "CorrelationRiskEngine must be loaded at module level in L6"


# -- Low correlation: risk unaffected -----------------------------------------


class TestLowCorrelation:
    """Independent pairs -> correlation engine does not reduce risk."""

    def test_passes_with_independent_pairs(self) -> None:
        analyzer = L6RiskAnalyzer()
        result = analyzer.analyze(pair_returns=_multi_pair_low_corr())

        assert result["risk_ok"] is True
        assert result["risk_status"] == "OPTIMAL"

    def test_risk_multiplier_not_reduced(self) -> None:
        analyzer = L6RiskAnalyzer()
        result = analyzer.analyze(pair_returns=_multi_pair_low_corr())
        assert result["risk_multiplier"] == 1.0


# -- High correlation: risk dampened ------------------------------------------


class TestHighCorrelation:
    """Highly correlated pairs -> risk dampened via engine."""

    def test_risk_reduced_with_correlated_pairs(self) -> None:
        analyzer = L6RiskAnalyzer()
        result = analyzer.analyze(pair_returns=_multi_pair_high_corr())

        # Correlation engine should dampen risk_multiplier
        assert result["risk_multiplier"] < 1.0

    def test_correlation_stress_warning(self) -> None:
        analyzer = L6RiskAnalyzer()
        result = analyzer.analyze(pair_returns=_multi_pair_high_corr())

        assert result["risk_status"] == "CORRELATION_STRESS"
        assert any("CORR_ENGINE_BLOCK" in w for w in result["warnings"])


# -- Backward compatibility: no pair_returns -> no corr impact ----------------


class TestBackwardCompat:
    """Without pair_returns, L6 behaves normally."""

    def test_no_pair_returns_optimal(self) -> None:
        result = L6RiskAnalyzer().analyze(rr=2.0)
        assert result["risk_status"] == "OPTIMAL"

    def test_single_pair_skipped(self) -> None:
        """Only 1 pair -> correlation analysis skipped (need >= 2)."""
        result = L6RiskAnalyzer().analyze(
            pair_returns={"EURUSD": [float(x) for x in range(50)]},
        )
        assert result["risk_ok"] is True

    def test_short_series_skipped(self) -> None:
        """Series < 20 observations -> correlation analysis skipped."""
        result = L6RiskAnalyzer().analyze(
            pair_returns={
                "EURUSD": [1.0] * 10,
                "GBPUSD": [2.0] * 10,
            },
        )
        assert result["risk_ok"] is True


# -- Combined: vol clustering + correlation -----------------------------------


class TestCombinedEnrichment:
    """Both vol clustering and correlation can run together."""

    def test_both_enrichments_run(self) -> None:
        rng = np.random.default_rng(7)
        trade_returns = [float(x) for x in rng.normal(0, 1, 50)]
        pair_returns = _multi_pair_low_corr()

        result = L6RiskAnalyzer().analyze(
            trade_returns=trade_returns,
            pair_returns=pair_returns,
        )

        # All core fields present
        assert result["valid"] is True
        assert "risk_multiplier" in result
        assert "lrce" in result
