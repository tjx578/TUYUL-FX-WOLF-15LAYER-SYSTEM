"""Tests for volatility analysis utilities."""

from analysis.volatility import calculate_atr, volatility_regime


class TestCalculateATR:
    def test_insufficient_data_returns_zero(self):
        assert calculate_atr([]) == 0.0
        assert calculate_atr([{"high": 1.1, "low": 1.0, "close": 1.05}]) == 0.0

    def test_basic_atr_calculation(self):
        candles = [
            {"high": 1.10, "low": 1.00, "close": 1.05},
            {"high": 1.12, "low": 1.01, "close": 1.08},
            {"high": 1.15, "low": 1.03, "close": 1.10},
        ]
        atr = calculate_atr(candles, period=14)
        assert atr > 0

    def test_atr_with_gaps(self):
        # Test with price gap (close to next open)
        candles = [
            {"high": 1.10, "low": 1.00, "close": 1.05},
            {"high": 1.25, "low": 1.15, "close": 1.20},  # Gap up
        ]
        atr = calculate_atr(candles, period=14)
        assert atr > 0.10  # Should capture the gap

    def test_atr_period_respected(self):
        candles = []
        for i in range(20):
            candles.append(
                {
                    "high": 1.0 + i * 0.01,
                    "low": 0.99 + i * 0.01,
                    "close": 0.995 + i * 0.01,
                }
            )

        atr_short = calculate_atr(candles, period=5)
        atr_long = calculate_atr(candles, period=14)
        # Both should be positive
        assert atr_short > 0
        assert atr_long > 0

    def test_atr_stable_market(self):
        # Stable market with small ranges
        candles = []
        for i in range(15):
            candles.append({"high": 1.01, "low": 1.00, "close": 1.005})

        atr = calculate_atr(candles, period=14)
        assert atr > 0
        assert atr < 0.02  # Should be small

    def test_atr_volatile_market(self):
        # Volatile market with large ranges
        candles = []
        for i in range(15):
            candles.append(
                {
                    "high": 1.00 + i * 0.05,
                    "low": 1.00 + i * 0.05 - 0.04,
                    "close": 1.00 + i * 0.05 - 0.02,
                }
            )

        atr = calculate_atr(candles, period=14)
        assert atr > 0.03  # Should be higher


class TestVolatilityRegime:
    def test_normal_regime(self):
        result = volatility_regime(1.0, 1.0)
        assert result["regime"] == "NORMAL"
        assert result["ratio"] == 1.0
        assert result["confidence_multiplier"] == 1.0
        assert result["risk_multiplier"] == 1.0

    def test_expansion_regime(self):
        result = volatility_regime(2.0, 1.0)
        assert result["regime"] == "EXPANSION"
        assert result["ratio"] == 2.0
        assert result["risk_multiplier"] < 1.0  # Reduce position size

    def test_compression_regime(self):
        result = volatility_regime(0.5, 1.0)
        assert result["regime"] == "COMPRESSION"
        assert result["ratio"] == 0.5

    def test_zero_baseline_returns_unknown(self):
        result = volatility_regime(1.0, 0.0)
        assert result["regime"] == "UNKNOWN"
        assert result["ratio"] == 0.0

    def test_negative_baseline_returns_unknown(self):
        result = volatility_regime(1.0, -1.0)
        assert result["regime"] == "UNKNOWN"

    def test_expansion_threshold(self):
        # Just at threshold
        result = volatility_regime(1.5, 1.0)
        # Just above threshold
        result_above = volatility_regime(1.51, 1.0)
        assert result_above["regime"] == "EXPANSION"

    def test_compression_threshold(self):
        # Just at threshold
        result = volatility_regime(0.7, 1.0)
        # Just below threshold
        result_below = volatility_regime(0.69, 1.0)
        assert result_below["regime"] == "COMPRESSION"

    def test_ratio_rounding(self):
        result = volatility_regime(1.23456789, 1.0)
        # Ratio should be rounded to 4 decimal places
        assert result["ratio"] == 1.2346

    def test_multipliers_in_range(self):
        # Test that multipliers are reasonable
        for ratio in [0.5, 0.7, 1.0, 1.5, 2.0]:
            result = volatility_regime(ratio, 1.0)
            assert 0 < result["confidence_multiplier"] <= 1.0
            assert 0 < result["risk_multiplier"] <= 1.0
