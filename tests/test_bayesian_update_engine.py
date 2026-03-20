"""Unit tests for engines/bayesian_update_engine.py."""

from __future__ import annotations

import pytest

from engines.bayesian_update_engine import (
    BayesianProbabilityEngine,
    BayesianResult,
)


class TestBayesianProbabilityEngine:

    def test_basic_update(self) -> None:
        engine = BayesianProbabilityEngine(seed=42)
        result = engine.update(prior_wins=10, prior_losses=5, new_evidence_score=0.7)

        assert isinstance(result, BayesianResult)
        assert 0.0 <= result.posterior_win_probability <= 1.0
        assert result.confidence_interval_low <= result.posterior_win_probability
        assert result.confidence_interval_high >= result.posterior_win_probability

    def test_strong_evidence_shifts_posterior(self) -> None:
        engine = BayesianProbabilityEngine(seed=42)
        weak = engine.update(prior_wins=5, prior_losses=5, new_evidence_score=0.2)
        strong = engine.update(prior_wins=5, prior_losses=5, new_evidence_score=0.9)

        assert strong.posterior_win_probability > weak.posterior_win_probability

    def test_zero_priors(self) -> None:
        engine = BayesianProbabilityEngine(seed=42)
        result = engine.update(prior_wins=0, prior_losses=0, new_evidence_score=0.5)
        # With uninformative prior + neutral evidence -> near 0.5
        assert 0.3 <= result.posterior_win_probability <= 0.7

    def test_negative_priors_raises(self) -> None:
        engine = BayesianProbabilityEngine(seed=42)
        with pytest.raises(ValueError, match="Invalid prior counts"):
            engine.update(prior_wins=-1, prior_losses=5, new_evidence_score=0.5)

    def test_evidence_out_of_range_raises(self) -> None:
        engine = BayesianProbabilityEngine(seed=42)
        with pytest.raises(ValueError, match="Evidence score must be in"):
            engine.update(prior_wins=5, prior_losses=5, new_evidence_score=1.5)

    def test_deterministic_with_seed(self) -> None:
        r1 = BayesianProbabilityEngine(seed=99).update(10, 5, 0.6)
        r2 = BayesianProbabilityEngine(seed=99).update(10, 5, 0.6)
        assert r1.posterior_win_probability == r2.posterior_win_probability
        assert r1.confidence_interval_low == r2.confidence_interval_low

    def test_to_dict(self) -> None:
        engine = BayesianProbabilityEngine(seed=42)
        result = engine.update(prior_wins=8, prior_losses=3, new_evidence_score=0.75)
        d = result.to_dict()

        assert "posterior_win_probability" in d
        assert "alpha" in d
        assert "beta" in d
        assert isinstance(d["posterior_win_probability"], float)
