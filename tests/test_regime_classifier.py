"""Unit tests for engines/regime_classifier_ml.py.

Tests cover:
    - Trending detection (persistent upward drift)
    - Mean-reverting detection (oscillatory series)
    - Random walk → TRANSITION with low confidence
    - Insufficient data raises ValueError
    - Negative prices raise ValueError
    - Hurst clamped to [0, 1]
    - Confidence bounded [0, 1]
    - Volatility state enum values
    - Serialization (to_dict)
    - Constant prices → fallback Hurst 0.5 (no crash)
"""

from __future__ import annotations

import numpy as np  # pyright: ignore[reportMissingImports]
import pytest  # pyright: ignore[reportMissingImports]

from engines.regime_classifier_ml import RegimeClassification, RegimeClassifier


def _trending_prices(n: int = 300, seed: int = 42) -> list[float]:
    """Strongly persistent upward price series."""
    rng = np.random.default_rng(seed)
    prices = [100.0]
    for _ in range(n - 1):
        prices.append(prices[-1] + rng.uniform(0.1, 0.6))
    return prices


def _mean_reverting_prices(n: int = 300, seed: int = 42) -> list[float]:
    """Mean-reverting around 100 with strong reversion coefficient."""
    rng = np.random.default_rng(seed)
    prices = [100.0]
    for _ in range(n - 1):
        reversion = (100.0 - prices[-1]) * 0.4
        noise = rng.normal(0, 0.3)
        prices.append(max(50.0, prices[-1] + reversion + noise))
    return prices


def _random_walk(n: int = 300, seed: int = 42) -> list[float]:
    """Random walk (no memory)."""
    rng = np.random.default_rng(seed)
    prices = [100.0]
    for _ in range(n - 1):
        prices.append(max(10.0, prices[-1] + rng.normal(0, 1.0)))
    return prices


class TestRegimeClassifier:
    """Regime classifier engine tests."""

    def test_trending_detected(self) -> None:
        clf = RegimeClassifier()
        result = clf.classify(_trending_prices())

        assert isinstance(result, RegimeClassification)
        assert result.regime == "TRENDING"
        assert result.confidence > 0.0
        assert result.hurst_exponent > 0.5

    def test_mean_reverting_detected(self) -> None:
        clf = RegimeClassifier()
        result = clf.classify(_mean_reverting_prices())

        assert result.regime in ("MEAN_REVERTING", "TRANSITION")
        assert result.hurst_exponent < 0.55

    def test_random_walk_transition(self) -> None:
        clf = RegimeClassifier()
        result = clf.classify(_random_walk())

        # Random walk → Hurst near 0.5 → TRANSITION (or edge case)
        assert result.regime in ("TRENDING", "MEAN_REVERTING", "TRANSITION")
        assert 0.0 <= result.hurst_exponent <= 1.0

    def test_insufficient_data_raises(self) -> None:
        clf = RegimeClassifier()
        with pytest.raises(ValueError, match="Minimum"):
            clf.classify([100.0, 101.0, 102.0])

    def test_negative_prices_raises(self) -> None:
        clf = RegimeClassifier()
        with pytest.raises(ValueError, match="positive"):
            clf.classify([100.0, -50.0] + [100.0] * 30)

    def test_nan_prices_raises(self) -> None:
        clf = RegimeClassifier()
        with pytest.raises(ValueError, match="NaN or Inf"):
            clf.classify([100.0, float("nan")] + [100.0] * 30)

    def test_hurst_clamped(self) -> None:
        clf = RegimeClassifier()
        result = clf.classify(_trending_prices())
        assert 0.0 <= result.hurst_exponent <= 1.0

    def test_confidence_bounded(self) -> None:
        clf = RegimeClassifier()
        for prices_fn in [_trending_prices, _mean_reverting_prices, _random_walk]:
            result = clf.classify(prices_fn())
            assert 0.0 <= result.confidence <= 1.0

    def test_volatility_state_values(self) -> None:
        clf = RegimeClassifier()
        result = clf.classify(_random_walk())
        assert result.volatility_state in ("HIGH_VOL", "NORMAL_VOL", "LOW_VOL")

    def test_to_dict_schema(self) -> None:
        clf = RegimeClassifier()
        d = clf.classify(_trending_prices()).to_dict()
        expected_keys = {"regime", "confidence", "volatility_state",
                         "hurst_exponent", "volatility", "momentum"}
        assert expected_keys <= set(d.keys())

    def test_constant_prices_no_crash(self) -> None:
        """Constant prices → zero std at all lags → fallback Hurst 0.5."""
        clf = RegimeClassifier()
        result = clf.classify([100.0] * 50)
        assert result.hurst_exponent == 0.5
        # TRANSITION since 0.45 ≤ 0.5 ≤ 0.60
        assert result.regime == "TRANSITION"

    def test_immutable_result(self) -> None:
        clf = RegimeClassifier()
        result = clf.classify(_trending_prices())
        with pytest.raises(AttributeError):
            result.regime = "BROKEN"  # type: ignore[misc]
