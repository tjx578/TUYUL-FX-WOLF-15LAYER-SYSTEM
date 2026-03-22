"""Unit tests for engines/correlation_risk_engine.py.

Tests cover:
    - High correlation -> fail
    - Low correlation -> pass
    - Single pair raises ValueError
    - Insufficient observations raises ValueError
    - Concentration risk bounded [0, 1]
    - High-correlation pairs flagged
    - NaN in return matrix doesn't crash
    - num_pairs tracked
    - Serialization (to_dict)
    - 1D input raises ValueError
    - Identical series -> max correlation ≈ 1
"""

from __future__ import annotations

import numpy as np
import pytest

from engines.correlation_risk_engine import (
    CorrelationRiskEngine,
    CorrelationRiskResult,
)


def _correlated_matrix(
    n_pairs: int = 4,
    n_obs: int = 100,
    corr: float = 0.9,
    seed: int = 42,
) -> list[list[float]]:
    """Return matrix where all pairs share a correlated base signal."""
    rng = np.random.default_rng(seed)
    base = rng.normal(0, 0.01, n_obs)
    return [(base * corr + rng.normal(0, 0.01, n_obs) * (1 - corr)).tolist() for _ in range(n_pairs)]


def _uncorrelated_matrix(
    n_pairs: int = 4,
    n_obs: int = 100,
    seed: int = 42,
) -> list[list[float]]:
    """Return matrix with independent series."""
    rng = np.random.default_rng(seed)
    return [rng.normal(0, 0.01, n_obs).tolist() for _ in range(n_pairs)]


class TestCorrelationRiskEngine:
    """Correlation risk engine tests."""

    def test_high_correlation_fails(self) -> None:
        engine = CorrelationRiskEngine(max_corr_threshold=0.85)
        result = engine.evaluate(_correlated_matrix(4, 100, corr=0.95))

        assert isinstance(result, CorrelationRiskResult)
        assert result.max_correlation > 0.85
        assert result.passed is False

    def test_low_correlation_passes(self) -> None:
        engine = CorrelationRiskEngine(max_corr_threshold=0.85)
        result = engine.evaluate(_uncorrelated_matrix(4, 100))

        assert result.max_correlation < 0.85
        assert result.passed is True

    def test_single_pair_raises(self) -> None:
        engine = CorrelationRiskEngine()
        with pytest.raises(ValueError, match="Minimum 2 pairs"):
            engine.evaluate([[0.01, -0.02, 0.03] * 10])

    def test_insufficient_observations_raises(self) -> None:
        engine = CorrelationRiskEngine(min_observations=20)
        with pytest.raises(ValueError, match="Minimum 20 observations"):
            engine.evaluate([[0.01, -0.02], [0.03, -0.01]])

    def test_concentration_risk_bounded(self) -> None:
        engine = CorrelationRiskEngine()
        for mat_fn in [
            lambda: _correlated_matrix(5, 100),
            lambda: _uncorrelated_matrix(5, 100),
        ]:
            result = engine.evaluate(mat_fn())
            assert 0.0 <= result.concentration_risk <= 1.0

    def test_high_pairs_flagged(self) -> None:
        engine = CorrelationRiskEngine(high_corr_flag=0.50)
        result = engine.evaluate(_correlated_matrix(3, 100, corr=0.9))
        assert len(result.high_correlation_pairs) > 0

    def test_no_pairs_flagged_when_uncorrelated(self) -> None:
        engine = CorrelationRiskEngine(high_corr_flag=0.70)
        result = engine.evaluate(_uncorrelated_matrix(4, 100))
        # Should have few or no flagged pairs
        assert all(abs(c) >= 0.70 for _, _, c in result.high_correlation_pairs)

    def test_nan_handling(self) -> None:
        engine = CorrelationRiskEngine(min_observations=5)
        mat = [
            [0.01, float("nan"), 0.03, -0.01, 0.02, 0.01, 0.0],
            [0.02, -0.01, float("nan"), 0.01, -0.02, 0.03, 0.01],
        ]
        result = engine.evaluate(mat)
        assert isinstance(result, CorrelationRiskResult)

    def test_num_pairs_tracked(self) -> None:
        engine = CorrelationRiskEngine()
        result = engine.evaluate(_uncorrelated_matrix(6, 50))
        assert result.num_pairs == 6

    def test_to_dict_schema(self) -> None:
        engine = CorrelationRiskEngine()
        d = engine.evaluate(_uncorrelated_matrix(3, 50)).to_dict()
        expected_keys = {
            "max_correlation",
            "average_correlation",
            "concentration_risk",
            "num_pairs",
            "high_correlation_pairs",
            "passed",
        }
        assert expected_keys <= set(d.keys())

    def test_1d_input_raises(self) -> None:
        engine = CorrelationRiskEngine()
        with pytest.raises(ValueError, match="2D"):
            engine.evaluate([0.01, 0.02, 0.03])  # type: ignore[arg-type]

    def test_identical_series_max_corr(self) -> None:
        """Two identical series -> correlation ≈ 1.0."""
        series = [0.01, -0.02, 0.03, -0.01, 0.02] * 10
        engine = CorrelationRiskEngine(min_observations=10)
        result = engine.evaluate([series, series])
        assert result.max_correlation >= 0.99

    def test_immutable_result(self) -> None:
        engine = CorrelationRiskEngine()
        result = engine.evaluate(_uncorrelated_matrix(3, 50))
        with pytest.raises(AttributeError):
            result.passed = True  # type: ignore[misc]

    def test_invalid_threshold_raises(self) -> None:
        with pytest.raises(ValueError, match="max_corr_threshold"):
            CorrelationRiskEngine(max_corr_threshold=0.0)
