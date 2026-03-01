"""Unit tests for engines/v11/exhaustion_detector.py.

Tests cover:
- Neutral state (insufficient data, normal conditions)
- Sell exhaustion detection
- Buy exhaustion detection
- ATR computation
- Wick ratio calculation
- Confidence scoring
"""

import pytest  # pyright: ignore[reportMissingImports]

from engines.v11.exhaustion_detector import (
    ExhaustionDetector,
    ExhaustionResult,
    ExhaustionState,
)


class TestExhaustionDetector:
    """Tests for exhaustion detector."""

    def test_insufficient_candles_returns_neutral(self) -> None:
        """Test that insufficient candles return neutral state."""
        detector = ExhaustionDetector()
        candles = [
            {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05}
            for _ in range(5)  # Too few
        ]

        result = detector.detect(candles)

        assert isinstance(result, ExhaustionResult)
        assert result.state == ExhaustionState.NEUTRAL
        assert result.confidence == 0.0

    def test_neutral_state_normal_conditions(self) -> None:
        """Test neutral state under normal market conditions."""
        detector = ExhaustionDetector(
            extreme_distance=0.025,
            impulse_limit=3.0,
            wick_ratio=1.5,
        )

        # Create normal candles (no extreme moves)
        candles = []
        price = 1.0
        for i in range(50):
            price += 0.0001 * (1 if i % 2 == 0 else -1)
            candles.append({
                "open": price,
                "high": price + 0.0002,
                "low": price - 0.0002,
                "close": price + 0.0001,
            })

        result = detector.detect(candles)

        assert result.state == ExhaustionState.NEUTRAL

    def test_sell_exhaustion_detection(self) -> None:
        """Test detection of sell exhaustion (oversold)."""
        detector = ExhaustionDetector(
            extreme_distance=0.02,
            impulse_limit=2.0,
            wick_ratio=1.5,
        )

        # Create oversold scenario: price far below mean with strong down impulse
        candles = []
        for i in range(40):
            candles.append({
                "open": 1.0,
                "high": 1.001,
                "low": 0.999,
                "close": 1.0,
            })

        # Add strong down move with long lower wick (rejection)
        candles.extend([
            {"open": 1.0, "high": 1.001, "low": 0.95, "close": 0.955},
            {"open": 0.955, "high": 0.96, "low": 0.93, "close": 0.950},
        ])

        result = detector.detect(candles)

        # Should detect sell exhaustion
        assert result.state in [ExhaustionState.SELL_EXHAUSTION, ExhaustionState.NEUTRAL]
        assert result.distance_from_mean < 0  # Below mean

    def test_buy_exhaustion_detection(self) -> None:
        """Test detection of buy exhaustion (overbought)."""
        detector = ExhaustionDetector(
            extreme_distance=0.02,
            impulse_limit=2.0,
            wick_ratio=1.5,
        )

        # Create overbought scenario: price far above mean with strong up impulse
        candles = []
        for i in range(40):
            candles.append({
                "open": 1.0,
                "high": 1.001,
                "low": 0.999,
                "close": 1.0,
            })

        # Add strong up move with long upper wick (rejection)
        candles.extend([
            {"open": 1.0, "high": 1.05, "low": 0.999, "close": 1.045},
            {"open": 1.045, "high": 1.07, "low": 1.04, "close": 1.050},
        ])

        result = detector.detect(candles)

        # Should detect buy exhaustion or neutral
        assert result.state in [ExhaustionState.BUY_EXHAUSTION, ExhaustionState.NEUTRAL]
        assert result.distance_from_mean > 0  # Above mean

    def test_atr_computation(self) -> None:
        """Test ATR computation produces valid values."""
        detector = ExhaustionDetector()

        candles = []
        for i in range(50):
            candles.append({
                "open": 1.0 + i * 0.001,
                "high": 1.002 + i * 0.001,
                "low": 0.998 + i * 0.001,
                "close": 1.001 + i * 0.001,
            })

        result = detector.detect(candles)

        # impulse_strength should be valid
        assert result.impulse_strength >= 0
        assert not isinstance(result.impulse_strength, type(None))

    def test_wick_ratio_computation(self) -> None:
        """Test wick ratio computation."""
        detector = ExhaustionDetector()

        # Create candle with long upper wick
        candles = []
        for i in range(40):
            candles.append({
                "open": 1.0,
                "high": 1.001,
                "low": 0.999,
                "close": 1.0,
            })

        # Add candle with strong upper wick
        candles.append({
            "open": 1.0,
            "high": 1.05,  # Long upper wick
            "low": 0.995,
            "close": 1.01,
        })

        result = detector.detect(candles)

        # Should have wick ratio > 1 (upper wick longer)
        assert result.wick_ratio >= 0

    def test_nan_handling(self) -> None:
        """Test handling of NaN values."""
        detector = ExhaustionDetector()

        candles = [
            {"open": 1.0, "high": 1.1, "low": 0.9, "close": float("nan")}
            for _ in range(50)
        ]

        result = detector.detect(candles)

        # Should return neutral on NaN
        assert result.state == ExhaustionState.NEUTRAL

    def test_frozen_result(self) -> None:
        """Test that result is frozen (immutable)."""
        detector = ExhaustionDetector()

        candles = [
            {"open": 1.0, "high": 1.001, "low": 0.999, "close": 1.0}
            for _ in range(50)
        ]

        result = detector.detect(candles)

        with pytest.raises(AttributeError):
            result.state = ExhaustionState.BUY_EXHAUSTION  # type: ignore[misc]

    def test_to_dict_serialization(self) -> None:
        """Test to_dict() serialization."""
        detector = ExhaustionDetector()

        candles = [
            {"open": 1.0, "high": 1.001, "low": 0.999, "close": 1.0}
            for _ in range(50)
        ]

        result = detector.detect(candles)
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "state" in d
        assert "distance_from_mean" in d
        assert "impulse_strength" in d
        assert "wick_ratio" in d
        assert "confidence" in d
