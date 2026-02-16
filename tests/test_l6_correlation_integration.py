"""Tests: CorrelationRiskEngine integration INTO L6 risk analyzer.

Verifies that when ``pair_returns`` (multi-pair return dict) is provided,
L6 evaluates pairwise correlation risk and includes enrichment fields
in its result.  When correlation breaches threshold, risk_status
is downgraded and propfirm_compliant is set False.

Authority: ANALYSIS ZONE only. No execution side-effects.
"""

from __future__ import annotations

import numpy as np  # pyright: ignore[reportMissingImports]

from analysis.layers.L6_risk import L6RiskAnalyzer, _corr_engine

# -- Fixtures -----------------------------------------------------------------


def _multi_pair_low_corr(
    n_pairs: int = 4, n_obs: int = 100, seed: int = 42,
) -> dict[str, list[float]]:
    """Generate independent (low-correlation) return series per pair."""
    rng = np.random.default_rng(seed)
    pairs = [f"PAIR{i}" for i in range(n_pairs)]
    return {
        p: [float(x) for x in rng.normal(0, 1, n_obs)]
        for p in pairs
    }


def _multi_pair_high_corr(
    n_obs: int = 100, seed: int = 42,
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
        assert _corr_engine is not None, (
            "CorrelationRiskEngine must be loaded at module level in L6"
        )


# -- Low correlation: enrichment present, passed = True -----------------------


class TestLowCorrelation:
    """Independent pairs -> correlation risk passes."""

    def test_corr_fields_present(self) -> None:
        analyzer = L6RiskAnalyzer()
        result = analyzer.analyze(pair_returns=_multi_pair_low_corr())

        assert "corr_max_correlation" in result
        assert "corr_avg_correlation" in result
        assert "corr_concentration_risk" in result
        assert "corr_num_pairs" in result
        assert "corr_high_pairs" in result
        assert "corr_passed" in result

    def test_passes_with_independent_pairs(self) -> None:
        analyzer = L6RiskAnalyzer()
        result = analyzer.analyze(pair_returns=_multi_pair_low_corr())

        assert result["corr_passed"] is True
        assert result["risk_status"] == "ACCEPTABLE"
        assert result["propfirm_compliant"] is True

    def test_num_pairs_matches_input(self) -> None:
        pairs = _multi_pair_low_corr(n_pairs=5)
        result = L6RiskAnalyzer().analyze(pair_returns=pairs)
        assert result["corr_num_pairs"] == 5


# -- High correlation: risk downgrade -----------------------------------------


class TestHighCorrelation:
    """Highly correlated pairs -> risk_status WARNING, propfirm False."""

    def test_fails_with_correlated_pairs(self) -> None:
        analyzer = L6RiskAnalyzer()
        result = analyzer.analyze(pair_returns=_multi_pair_high_corr())

        assert result["corr_passed"] is False
        assert result["risk_status"] == "WARNING"
        assert result["propfirm_compliant"] is False

    def test_high_pairs_flagged(self) -> None:
        analyzer = L6RiskAnalyzer()
        result = analyzer.analyze(pair_returns=_multi_pair_high_corr())

        assert len(result["corr_high_pairs"]) > 0
        # High pairs should have human-readable labels
        first = result["corr_high_pairs"][0]
        assert "pair_i" in first
        assert "pair_j" in first
        assert "correlation" in first

    def test_max_correlation_above_threshold(self) -> None:
        analyzer = L6RiskAnalyzer()
        result = analyzer.analyze(pair_returns=_multi_pair_high_corr())

        assert result["corr_max_correlation"] >= 0.85


# -- Backward compatibility: no pair_returns -> no corr fields ----------------


class TestBackwardCompat:
    """Without pair_returns, L6 behaves identically to before."""

    def test_no_pair_returns_no_corr_fields(self) -> None:
        result = L6RiskAnalyzer().analyze(rr=2.0)

        assert "corr_max_correlation" not in result
        assert "corr_passed" not in result
        assert result["risk_status"] == "ACCEPTABLE"

    def test_single_pair_skipped(self) -> None:
        """Only 1 pair -> correlation analysis skipped (need >= 2)."""
        result = L6RiskAnalyzer().analyze(
            pair_returns={"EURUSD": [float(x) for x in range(50)]},
        )
        assert "corr_passed" not in result

    def test_short_series_skipped(self) -> None:
        """Series < 20 observations -> correlation analysis skipped."""
        result = L6RiskAnalyzer().analyze(
            pair_returns={
                "EURUSD": [1.0] * 10,
                "GBPUSD": [2.0] * 10,
            },
        )
        assert "corr_passed" not in result


# -- Combined: vol clustering + correlation -----------------------------------


class TestCombinedEnrichment:
    """Both vol clustering and correlation can run together."""

    def test_both_enrichments_present(self) -> None:
        rng = np.random.default_rng(7)
        trade_returns = [float(x) for x in rng.normal(0, 1, 50)]
        pair_returns = _multi_pair_low_corr()

        result = L6RiskAnalyzer().analyze(
            trade_returns=trade_returns,
            pair_returns=pair_returns,
        )

        # Vol clustering fields
        assert "vol_clustering_detected" in result
        # Correlation fields
        assert "corr_passed" in result
