"""Unit tests for engines/volatility_clustering_model.py.

Tests cover:
    - GARCH-like returns -> clustering detected
    - IID returns -> minimal/no clustering
    - risk_multiplier capped at configured max
    - Insufficient data raises ValueError
    - Multi-lag autocorrelation stored
    - Constant returns -> no crash, no clustering
    - Ljung-Box proxy non-negative
    - Serialization (to_dict)
    - No-clustering -> risk_multiplier == 1.0
    - Sample size tracked
"""

from __future__ import annotations

import numpy as np  # pyright: ignore[reportMissingImports]
import pytest  # pyright: ignore[reportMissingImports]

from engines.volatility_clustering_model import (
    VolatilityClusteringModel,
    VolatilityClusterResult,
)


def _garch_returns(n: int = 300, seed: int = 42) -> list[float]:
    """Simulate GARCH(1,1)-like returns with volatility clustering."""
    rng = np.random.default_rng(seed)
    returns: list[float] = []
    vol = 0.01
    for _ in range(n):
        r = rng.normal(0, vol)
        returns.append(float(r))
        # GARCH(1,1)-style: vol depends on previous return magnitude
        vol = 0.002 + 0.85 * vol + 0.10 * abs(r)
    return returns


def _iid_returns(n: int = 300, seed: int = 42) -> list[float]:
    """IID normal returns -- no autocorrelation in squared returns."""
    rng = np.random.default_rng(seed)
    return [float(rng.normal(0, 0.01)) for _ in range(n)]


class TestVolatilityClusteringModel:
    """Volatility clustering model tests."""

    def test_detects_clustering(self) -> None:
        model = VolatilityClusteringModel()
        result = model.analyze(_garch_returns(300))

        assert isinstance(result, VolatilityClusterResult)
        assert result.clustering_detected is True
        assert result.vol_persistence > 0.20

    def test_iid_no_strong_clustering(self) -> None:
        model = VolatilityClusteringModel()
        result = model.analyze(_iid_returns(300))

        assert result.vol_persistence < 0.30
        assert result.risk_multiplier <= 1.5

    def test_risk_multiplier_capped(self) -> None:
        model = VolatilityClusteringModel(max_risk_multiplier=1.3)
        result = model.analyze(_garch_returns(300))
        assert result.risk_multiplier <= 1.3

    def test_risk_multiplier_one_when_no_clustering(self) -> None:
        model = VolatilityClusteringModel(clustering_threshold=0.99)
        result = model.analyze(_iid_returns(200))
        assert result.risk_multiplier == 1.0

    def test_insufficient_data_raises(self) -> None:
        model = VolatilityClusteringModel(min_returns=20)
        with pytest.raises(ValueError, match="Minimum 20 returns"):
            model.analyze([0.01, -0.02, 0.03])

    def test_multi_lag_autocorrelation(self) -> None:
        model = VolatilityClusteringModel(max_lag=5)
        result = model.analyze(_garch_returns(200))

        assert len(result.per_lag_autocorrelation) >= 1
        for lag, ac in result.per_lag_autocorrelation.items():
            assert isinstance(lag, int)
            assert -1.0 <= ac <= 1.0

    def test_constant_returns_no_crash(self) -> None:
        """Constant returns -> zero variance -> no clustering, no NaN."""
        model = VolatilityClusteringModel(min_returns=5)
        result = model.analyze([0.01] * 50)

        assert result.clustering_detected is False
        assert result.vol_persistence == 0.0
        assert result.risk_multiplier == 1.0
        for ac in result.per_lag_autocorrelation.values():
            assert ac == 0.0

    def test_ljung_box_proxy_nonnegative(self) -> None:
        model = VolatilityClusteringModel()
        for returns_fn in [_garch_returns, _iid_returns]:
            result = model.analyze(returns_fn(200))
            assert result.ljung_box_proxy >= 0.0

    def test_to_dict_schema(self) -> None:
        model = VolatilityClusteringModel()
        d = model.analyze(_garch_returns(100)).to_dict()
        expected_keys = {
            "clustering_detected", "vol_persistence", "risk_multiplier",
            "per_lag_autocorrelation", "ljung_box_proxy", "sample_size",
        }
        assert expected_keys <= set(d.keys())

    def test_sample_size_tracked(self) -> None:
        model = VolatilityClusteringModel(min_returns=5)
        result = model.analyze([0.01, -0.02, 0.03, 0.01, -0.01] * 10)
        assert result.sample_size == 50

    def test_immutable_result(self) -> None:
        model = VolatilityClusteringModel()
        result = model.analyze(_garch_returns(100))
        with pytest.raises(AttributeError):
            result.clustering_detected = False  # type: ignore[misc]

    def test_garch_stronger_than_iid(self) -> None:
        """GARCH returns should show higher Ljung-Box proxy than IID."""
        model = VolatilityClusteringModel()
        garch = model.analyze(_garch_returns(200))
        iid = model.analyze(_iid_returns(200))
        assert garch.ljung_box_proxy > iid.ljung_box_proxy
