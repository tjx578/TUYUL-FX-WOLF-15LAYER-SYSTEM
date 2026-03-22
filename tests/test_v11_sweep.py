"""Unit tests for engines/v11/liquidity_sweep_scorer.py.

Tests cover:
- No sweep detected (normal conditions)
- Sweep detection (bullish and bearish)
- Equal level detection
- Wick rejection computation
- Volume confirmation
- Multi-bar pattern detection
- Quality score computation
"""

import pytest

from engines.v11.liquidity_sweep_scorer import LiquiditySweepScorer


class TestLiquiditySweepScorer:
    """Tests for liquidity sweep scorer."""

    def test_no_sweep_normal_conditions(self) -> None:
        """Test no sweep detected under normal conditions."""
        scorer = LiquiditySweepScorer()

        # Normal candles with varied prices (no equal levels)
        candles = []
        for i in range(30):
            price = 1.0 + i * 0.0005  # Varied prices
            candles.append(
                {
                    "open": price,
                    "high": price + 0.0003,
                    "low": price - 0.0003,
                    "close": price + 0.0001,
                    "volume": 100,
                }
            )

        result = scorer.score(candles, direction="bullish")

        # With varied prices, should not detect strong sweep
        assert result.sweep_quality < 0.7  # Allow some detection but not strong

    def test_insufficient_candles(self) -> None:
        """Test insufficient candles returns no sweep."""
        scorer = LiquiditySweepScorer(pattern_lookback=5)

        candles = [
            {"open": 1.0, "high": 1.01, "low": 0.99, "close": 1.0, "volume": 100}
            for _ in range(3)  # Too few
        ]

        result = scorer.score(candles, direction="bullish")

        assert not result.sweep_detected
        assert result.sweep_quality == 0.0

    def test_bullish_sweep_detection(self) -> None:
        """Test detection of bullish sweep (below lows)."""
        scorer = LiquiditySweepScorer(
            equal_level_tolerance=0.001,
            wick_rejection_min=0.60,
        )

        # Create equal lows pattern
        candles = []
        for _i in range(20):
            candles.append(
                {
                    "open": 1.0,
                    "high": 1.01,
                    "low": 0.99,  # Equal lows
                    "close": 1.0,
                    "volume": 100,
                }
            )

        # Add sweep candle: breaks below low but closes back above
        candles.append(
            {
                "open": 0.995,
                "high": 1.0,
                "low": 0.98,  # Sweep below
                "close": 0.995,  # Close above the low
                "volume": 200,  # Volume spike
            }
        )

        result = scorer.score(candles, direction="bullish")

        # Should detect some sweep characteristics
        assert result.equal_level_detected or result.volume_spike or result.failed_to_close
        assert result.sweep_quality > 0.0

    def test_bearish_sweep_detection(self) -> None:
        """Test detection of bearish sweep (above highs)."""
        scorer = LiquiditySweepScorer(
            equal_level_tolerance=0.001,
            wick_rejection_min=0.60,
        )

        # Create equal highs pattern
        candles = []
        for _i in range(20):
            candles.append(
                {
                    "open": 1.0,
                    "high": 1.01,  # Equal highs
                    "low": 0.99,
                    "close": 1.0,
                    "volume": 100,
                }
            )

        # Add sweep candle: breaks above high but closes back below
        candles.append(
            {
                "open": 1.005,
                "high": 1.02,  # Sweep above
                "low": 1.0,
                "close": 1.005,  # Close below the high
                "volume": 200,  # Volume spike
            }
        )

        result = scorer.score(candles, direction="bearish")

        # Should detect some sweep characteristics
        assert result.equal_level_detected or result.volume_spike or result.failed_to_close
        assert result.sweep_quality > 0.0

    def test_equal_level_detection(self) -> None:
        """Test equal high/low detection."""
        scorer = LiquiditySweepScorer(equal_level_tolerance=0.0001)

        # Create exact equal lows
        candles = []
        for _i in range(10):
            candles.append(
                {
                    "open": 1.0,
                    "high": 1.01,
                    "low": 0.99,  # Exact same low
                    "close": 1.0,
                    "volume": 100,
                }
            )

        result = scorer.score(candles, direction="bullish")

        assert result.equal_level_detected

    def test_volume_spike_detection(self) -> None:
        """Test volume spike detection."""
        scorer = LiquiditySweepScorer(
            volume_spike_threshold=1.5,
            volume_lookback=10,
        )

        # Normal volume
        candles = []
        for _i in range(15):
            candles.append(
                {
                    "open": 1.0,
                    "high": 1.01,
                    "low": 0.99,
                    "close": 1.0,
                    "volume": 100,
                }
            )

        # Add high volume candle
        candles.append(
            {
                "open": 1.0,
                "high": 1.01,
                "low": 0.99,
                "close": 1.0,
                "volume": 200,  # 2x average
            }
        )

        result = scorer.score(candles, direction="bullish")

        assert result.volume_spike

    def test_wick_rejection_bullish(self) -> None:
        """Test wick rejection calculation for bullish sweep."""
        scorer = LiquiditySweepScorer()

        candles = []
        for _i in range(20):
            candles.append(
                {
                    "open": 1.0,
                    "high": 1.01,
                    "low": 0.99,
                    "close": 1.0,
                    "volume": 100,
                }
            )

        # Add candle with long lower wick (bullish rejection)
        candles.append(
            {
                "open": 1.0,
                "high": 1.01,
                "low": 0.95,  # Long lower wick
                "close": 0.995,
                "volume": 100,
            }
        )

        result = scorer.score(candles, direction="bullish")

        # Should have wick rejection
        assert result.wick_rejection > 0.0

    def test_wick_rejection_bearish(self) -> None:
        """Test wick rejection calculation for bearish sweep."""
        scorer = LiquiditySweepScorer()

        candles = []
        for _i in range(20):
            candles.append(
                {
                    "open": 1.0,
                    "high": 1.01,
                    "low": 0.99,
                    "close": 1.0,
                    "volume": 100,
                }
            )

        # Add candle with long upper wick (bearish rejection)
        candles.append(
            {
                "open": 1.0,
                "high": 1.05,  # Long upper wick
                "low": 0.99,
                "close": 1.005,
                "volume": 100,
            }
        )

        result = scorer.score(candles, direction="bearish")

        # Should have wick rejection
        assert result.wick_rejection > 0.0

    def test_quality_score_range(self) -> None:
        """Test quality score is in valid range."""
        scorer = LiquiditySweepScorer()

        candles = []
        for _i in range(30):
            candles.append(
                {
                    "open": 1.0,
                    "high": 1.01,
                    "low": 0.99,
                    "close": 1.0,
                    "volume": 100,
                }
            )

        result = scorer.score(candles, direction="bullish")

        assert 0.0 <= result.sweep_quality <= 1.0

    def test_frozen_result(self) -> None:
        """Test result is immutable."""
        scorer = LiquiditySweepScorer()

        candles = [{"open": 1.0, "high": 1.01, "low": 0.99, "close": 1.0, "volume": 100} for _ in range(30)]

        result = scorer.score(candles, direction="bullish")

        with pytest.raises(AttributeError):
            result.sweep_detected = True  # type: ignore[misc]

    def test_to_dict_serialization(self) -> None:
        """Test to_dict() serialization."""
        scorer = LiquiditySweepScorer()

        candles = [{"open": 1.0, "high": 1.01, "low": 0.99, "close": 1.0, "volume": 100} for _ in range(30)]

        result = scorer.score(candles, direction="bullish")
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "sweep_detected" in d
        assert "sweep_quality" in d
        assert "equal_level_detected" in d
        assert "wick_rejection" in d
        assert "volume_spike" in d
        assert "failed_to_close" in d
        assert "multi_bar_pattern" in d
