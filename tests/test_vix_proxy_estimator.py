"""
Unit tests for VIX Proxy Estimator.

Tests synthetic VIX estimation from forex candle data.
"""

import numpy as np

from analysis.macro.vix_proxy_estimator import VIXProxyEstimator, VIXProxyState


class TestVIXProxyEstimator:
    """Test VIX proxy estimation functionality."""

    def test_estimate_with_valid_candles(self) -> None:
        """Test VIX proxy estimation with valid candle data."""
        estimator = VIXProxyEstimator()

        # Create synthetic candle data (30 candles)
        candles = []
        for i in range(30):
            candles.append(
                {  # noqa: PERF401
                    "close": 1.1000 + i * 0.0001,
                    "high": 1.1010 + i * 0.0001,
                    "low": 1.0990 + i * 0.0001,
                }
            )

        result = estimator.estimate("EURUSD", candles)

        assert result is not None
        assert isinstance(result, VIXProxyState)
        assert 5.0 <= result.vix_equivalent <= 80.0
        assert 0 <= result.confidence <= 1.0
        assert result.atr_ratio > 0

    def test_estimate_with_insufficient_candles(self) -> None:
        """Test that estimation returns None with insufficient data."""
        estimator = VIXProxyEstimator()

        # Only 10 candles (need 30)
        candles = [{"close": 1.1000, "high": 1.1010, "low": 1.0990} for _ in range(10)]

        result = estimator.estimate("EURUSD", candles)
        assert result is None

    def test_estimate_with_empty_candles(self) -> None:
        """Test that estimation returns None with no data."""
        estimator = VIXProxyEstimator()
        result = estimator.estimate("EURUSD", [])
        assert result is None

    def test_estimate_with_invalid_prices(self) -> None:
        """Test that estimation handles invalid prices gracefully."""
        estimator = VIXProxyEstimator()

        # Candles with zero/negative prices
        candles = [{"close": 0, "high": 0, "low": 0} for _ in range(30)]

        result = estimator.estimate("EURUSD", candles)
        assert result is None

    def test_term_structure_estimation(self) -> None:
        """Test term structure estimation from candles."""
        estimator = VIXProxyEstimator()

        # Create candles with increasing volatility (BACKWARDATION)
        candles = []
        for i in range(30):
            volatility = 0.001 + i * 0.0001
            candles.append(
                {
                    "close": 1.1000 + np.random.normal(0, volatility),
                    "high": 1.1000 + abs(np.random.normal(0, volatility)) + 0.0005,
                    "low": 1.1000 - abs(np.random.normal(0, volatility)) - 0.0005,
                }
            )

        result = estimator.estimate("EURUSD", candles)

        assert result is not None
        assert result.term_structure_estimate in ["CONTANGO", "BACKWARDATION", "FLAT", "UNKNOWN"]

    def test_confidence_calculation(self) -> None:
        """Test confidence calculation with different candle counts."""
        estimator = VIXProxyEstimator()

        # Create candles
        def make_candles(count):
            return [{"close": 1.1000, "high": 1.1010, "low": 1.0990} for _ in range(count)]

        # More candles should give higher confidence
        result_30 = estimator.estimate("EURUSD", make_candles(30))
        result_100 = estimator.estimate("EURUSD", make_candles(100))

        assert result_30 is not None
        assert result_100 is not None
        assert result_100.confidence >= result_30.confidence

    def test_vix_equivalent_clamping(self) -> None:
        """Test that VIX equivalent is clamped to valid range."""
        estimator = VIXProxyEstimator()

        # Create candles with extreme volatility
        candles = []
        for _i in range(30):
            candles.append(
                {  # noqa: PERF401
                    "close": 1.1000 + np.random.normal(0, 0.1),
                    "high": 1.2000,
                    "low": 1.0000,
                }
            )

        result = estimator.estimate("EURUSD", candles)

        assert result is not None
        assert 5.0 <= result.vix_equivalent <= 80.0

    def test_history_storage(self) -> None:
        """Test that VIX history is stored and limited."""
        estimator = VIXProxyEstimator()

        candles = [{"close": 1.1000, "high": 1.1010, "low": 1.0990} for _ in range(30)]

        # Estimate multiple times
        for _ in range(150):
            estimator.estimate("EURUSD", candles)

        # History should be capped at 100
        assert len(estimator._history.get("EURUSD", [])) <= 100
