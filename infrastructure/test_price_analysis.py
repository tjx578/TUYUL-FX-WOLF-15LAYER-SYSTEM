"""
Tests for analysis/price_analysis.py — ZeroDivisionError, thresholds, wick calculation.

Zone: analysis/ tests — no execution, no Layer-12 override.
"""

from __future__ import annotations

import math

import pytest

from analysis.price_analysis import (
    CandleData,
    PriceAnalysisConfig,
    WickAnalysisResult,
    analyze_wicks,
    compute_zscore,
    distance_from_mean,
    is_extreme_distance,
    is_impulse,
)


# ─── CandleData Validation ───────────────────────────────────

class TestCandleDataValidation:
    def test_valid_bullish_candle(self) -> None:
        c = CandleData(open=1.1000, high=1.1050, low=1.0980, close=1.1030)
        assert c.is_bullish is True
        assert c.is_bearish is False

    def test_valid_bearish_candle(self) -> None:
        c = CandleData(open=1.1030, high=1.1050, low=1.0980, close=1.1000)
        assert c.is_bearish is True
        assert c.is_bullish is False

    def test_doji(self) -> None:
        c = CandleData(open=1.1000, high=1.1050, low=1.0950, close=1.1000)
        assert c.is_doji is True

    def test_zero_range_is_doji(self) -> None:
        c = CandleData(open=1.1000, high=1.1000, low=1.1000, close=1.1000)
        assert c.is_doji is True
        assert c.full_range == 0.0

    def test_high_less_than_low_raises(self) -> None:
        with pytest.raises(ValueError, match="high.*< low"):
            CandleData(open=1.1000, high=1.0900, low=1.1100, close=1.1000)

    def test_high_less_than_open_raises(self) -> None:
        with pytest.raises(ValueError, match="high.*must be >= open"):
            CandleData(open=1.1100, high=1.1050, low=1.1000, close=1.1030)

    def test_low_greater_than_close_raises(self) -> None:
        with pytest.raises(ValueError, match="low.*must be <= open"):
            CandleData(open=1.0950, high=1.1050, low=1.0980, close=1.1030)


# ─── CandleData Wick Properties (the bug fix) ────────────────

class TestCandleWicks:
    """
    Critical tests for the corrected wick formula.

    OLD (buggy): upper_wick = high - max(close, low)
    NEW (fixed): upper_wick = high - max(open, close)  → body top
    """

    def test_bullish_candle_wicks(self) -> None:
        # Bullish: open=1.1000, close=1.1030
        # Body top = close = 1.1030, body bottom = open = 1.1000
        c = CandleData(open=1.1000, high=1.1050, low=1.0980, close=1.1030)

        assert c.body_top == 1.1030
        assert c.body_bottom == 1.1000
        assert c.upper_wick == pytest.approx(1.1050 - 1.1030)  # 0.0020
        assert c.lower_wick == pytest.approx(1.1000 - 1.0980)  # 0.0020

    def test_bearish_candle_wicks(self) -> None:
        # Bearish: open=1.1030, close=1.1000
        # Body top = open = 1.1030, body bottom = close = 1.1000
        c = CandleData(open=1.1030, high=1.1050, low=1.0980, close=1.1000)

        assert c.body_top == 1.1030
        assert c.body_bottom == 1.1000
        assert c.upper_wick == pytest.approx(1.1050 - 1.1030)  # 0.0020
        assert c.lower_wick == pytest.approx(1.1000 - 1.0980)  # 0.0020

    def test_bearish_pin_bar_bug_case(self) -> None:
        """
        This is the exact case where the old bug manifested.

        Bearish pin bar: close == low (long upper wick, no lower wick).
        OLD bug: upper_wick = high - max(close, low) = high - close ← accidentally correct here
        But consider: close < low is invalid, so close == low is the edge.

        Real bug case: bearish candle where close > low:
          open=1.1040, high=1.1100, low=1.0980, close=1.1000
          Body top = open = 1.1040
          OLD: upper_wick = 1.1100 - max(1.1000, 1.0980) = 1.1100 - 1.1000 = 0.0100 ← WRONG
          NEW: upper_wick = 1.1100 - max(1.1040, 1.1000) = 1.1100 - 1.1040 = 0.0060 ← CORRECT
        """
        c = CandleData(open=1.1040, high=1.1100, low=1.0980, close=1.1000)

        # Body top is open (bearish candle)
        assert c.body_top == 1.1040

        # CORRECT upper wick: high - body_top
        assert c.upper_wick == pytest.approx(1.1100 - 1.1040)  # 0.0060

        # OLD BUG would have given: 1.1100 - max(1.1000, 1.0980) = 0.0100
        old_buggy_upper = 1.1100 - max(1.1000, 1.0980)  # 0.0100
        assert c.upper_wick != pytest.approx(old_buggy_upper)

        # Lower wick: body_bottom - low
        assert c.lower_wick == pytest.approx(1.1000 - 1.0980)  # 0.0020

    def test_extreme_pin_bar_upper(self) -> None:
        """Long upper wick, tiny body at the bottom."""
        # Bearish: open=1.1010, close=1.1000, high=1.1100, low=1.0990
        c = CandleData(open=1.1010, high=1.1100, low=1.0990, close=1.1000)

        assert c.body_top == 1.1010
        assert c.upper_wick == pytest.approx(1.1100 - 1.1010)  # 0.0090
        assert c.lower_wick == pytest.approx(1.1000 - 1.0990)  # 0.0010
        assert c.body_size == pytest.approx(0.0010)

    def test_extreme_pin_bar_lower(self) -> None:
        """Long lower wick, tiny body at the top."""
        # Bullish: open=1.1000, close=1.1010, high=1.1020, low=1.0900
        c = CandleData(open=1.1000, high=1.1020, low=1.0900, close=1.1010)

        assert c.body_top == 1.1010
        assert c.upper_wick == pytest.approx(1.1020 - 1.1010)  # 0.0010
        assert c.lower_wick == pytest.approx(1.1000 - 1.0900)  # 0.0100

    def test_marubozu_no_wicks(self) -> None:
        """Full body, no wicks."""
        c = CandleData(open=1.1000, high=1.1050, low=1.1000, close=1.1050)
        assert c.upper_wick == 0.0
        assert c.lower_wick == 0.0


# ─── Distance from Mean (ZeroDivisionError fix) ──────────────

class TestDistanceFromMean:
    def test_normal_positive_mean(self) -> None:
        # 1.05 is 5% above 1.0
        assert distance_from_mean(1.05, 1.0) == pytest.approx(0.05)

    def test_normal_negative_distance(self) -> None:
        assert distance_from_mean(0.95, 1.0) == pytest.approx(-0.05)

    def test_zero_mean_zero_value(self) -> None:
        """Both zero: distance is 0.0 (not ZeroDivisionError)."""
        assert distance_from_mean(0.0, 0.0) == 0.0

    def test_zero_mean_positive_value(self) -> None:
        """Zero mean, positive value: positive infinity."""
        result = distance_from_mean(1.5, 0.0)
        assert math.isinf(result)
        assert result > 0

    def test_zero_mean_negative_value(self) -> None:
        """Zero mean, negative value: negative infinity."""
        result = distance_from_mean(-0.5, 0.0)
        assert math.isinf(result)
        assert result < 0

    def test_negative_mean(self) -> None:
        """Negative mean: uses abs(mean) for denominator."""
        # value=-0.5, mean=-1.0 → (-0.5 - (-1.0)) / abs(-1.0) = 0.5
        assert distance_from_mean(-0.5, -1.0) == pytest.approx(0.5)


class TestIsExtremeDistance:
    def test_within_threshold(self) -> None:
        config = PriceAnalysisConfig(extreme_distance=0.025)
        # 1% from mean — not extreme
        assert is_extreme_distance(1.01, 1.0, config) is False

    def test_beyond_threshold(self) -> None:
        config = PriceAnalysisConfig(extreme_distance=0.025)
        # 3% from mean — extreme
        assert is_extreme_distance(1.03, 1.0, config) is True

    def test_zero_mean_nonzero_value_is_extreme(self) -> None:
        """Infinite distance is always extreme."""
        assert is_extreme_distance(0.001, 0.0) is True

    def test_zero_mean_zero_value_not_extreme(self) -> None:
        assert is_extreme_distance(0.0, 0.0) is False

    def test_custom_threshold(self) -> None:
        tight = PriceAnalysisConfig(extreme_distance=0.005)
        loose = PriceAnalysisConfig(extreme_distance=0.1)

        # 1% from mean
        assert is_extreme_distance(1.01, 1.0, tight) is True
        assert is_extreme_distance(1.01, 1.0, loose) is False


# ─── Impulse Detection ───────────────────────────────────────

class TestZScore:
    def test_normal_zscore(self) -> None:
        values = [10.0, 10.5, 9.8, 10.2, 10.1, 9.9, 10.3]
        z = compute_zscore(10.0, values)
        assert z is not None
        assert abs(z) < 1.0  # 10.0 is near the mean

    def test_insufficient_data(self) -> None:
        config = PriceAnalysisConfig(min_candles=5)
        z = compute_zscore(10.0, [10.0, 10.1, 10.2], config)
        assert z is None

    def test_zero_std_same_value(self) -> None:
        """All values identical, query is same → z-score is 0."""
        values = [5.0, 5.0, 5.0, 5.0, 5.0]
        z = compute_zscore(5.0, values)
        assert z == 0.0

    def test_zero_std_different_value(self) -> None:
        """All values identical, query differs → infinite z-score."""
        values = [5.0, 5.0, 5.0, 5.0, 5.0]
        z = compute_zscore(6.0, values)
        assert z is not None
        assert math.isinf(z)
        assert z > 0

    def test_negative_outlier(self) -> None:
        values = [10.0, 10.1, 9.9, 10.0, 10.2]
        z = compute_zscore(5.0, values)
        assert z is not None
        assert z < -3.0


class TestImpulse:
    def test_normal_value_not_impulse(self) -> None:
        values = [10.0, 10.5, 9.8, 10.2, 10.1, 9.9, 10.3]
        assert is_impulse(10.1, values) is False

    def test_outlier_is_impulse(self) -> None:
        values = [10.0, 10.1, 9.9, 10.0, 10.2, 9.8, 10.1]
        assert is_impulse(15.0, values) is True

    def test_insufficient_data_not_impulse(self) -> None:
        assert is_impulse(100.0, [10.0, 10.1]) is False

    def test_custom_impulse_limit(self) -> None:
        values = [10.0, 10.1, 9.9, 10.0, 10.2]
        tight = PriceAnalysisConfig(impulse_limit=1.0)
        loose = PriceAnalysisConfig(impulse_limit=10.0)

        # Moderate outlier
        assert is_impulse(11.0, values, tight) is True
        assert is_impulse(11.0, values, loose) is False


# ─── Wick Analysis (integration) ─────────────────────────────

class TestWickAnalysis:
    def _make_candles(self) -> list[CandleData]:
        return [
            # Bullish: O=1.10, H=1.105, L=1.098, C=1.103
            CandleData(open=1.1000, high=1.1050, low=1.0980, close=1.1030),
            # Bearish: O=1.104, H=1.110, L=1.098, C=1.100
            CandleData(open=1.1040, high=1.1100, low=1.0980, close=1.1000),
            # Doji-ish: O=1.100, H=1.105, L=1.095, C=1.100
            CandleData(open=1.1000, high=1.1050, low=1.0950, close=1.1000),
        ]

    def test_analyze_wicks_basic(self) -> None:
        candles = self._make_candles()
        result = analyze_wicks(candles)

        assert result is not None
        assert result.candle_count == 3
        assert result.avg_upper_wick > 0
        assert result.avg_lower_wick > 0
        assert result.max_upper_wick >= result.avg_upper_wick
        assert result.max_lower_wick >= result.avg_lower_wick

    def test_analyze_wicks_bearish_correctness(self) -> None:
        """Verify the corrected wick formula on bearish candles."""
        # Single bearish candle: open > close
        candle = CandleData(open=1.1040, high=1.1100, low=1.0980, close=1.1000)
        result = analyze_wicks([candle])

        assert result is not None
        # Upper wick should be high - body_top = 1.1100 - 1.1040 = 0.0060
        assert result.avg_upper_wick == pytest.approx(0.0060)
        # Lower wick should be body_bottom - low = 1.1000 - 1.0980 = 0.0020
        assert result.avg_lower_wick == pytest.approx(0.0020)

    def test_analyze_wicks_marubozu(self) -> None:
        """No wicks at all."""
        candle = CandleData(open=1.1000, high=1.1050, low=1.1000, close=1.1050)
        result = analyze_wicks([candle])

        assert result is not None
        assert result.avg_upper_wick == 0.0
        assert result.avg_lower_wick == 0.0

    def test_analyze_wicks_empty(self) -> None:
        assert analyze_wicks([]) is None

    def test_significant_wick_detection(self) -> None:
        """Candle with upper wick > 60% of range should be flagged."""
        config = PriceAnalysisConfig(significant_wick_ratio=0.6)
        # Upper wick dominant pin bar
        # O=1.100, H=1.110, L=1.099, C=1.101
        # range=0.011, upper_wick=1.110-1.101=0.009, ratio=0.009/0.011≈0.818
        candle = CandleData(open=1.1000, high=1.1100, low=1.0990, close=1.1010)
        result = analyze_wicks([candle], config)

        assert result is not None
        assert result.significant_upper_count == 1
        assert result.significant_lower_count == 0

    def test_wick_ratios_skip_zero_range(self) -> None:
        """Zero-range candles should not cause ZeroDivisionError in ratio calc."""
        candles = [
            CandleData(open=1.1000, high=1.1000, low=1.1000, close=1.1000),
            CandleData(open=1.1000, high=1.1050, low=1.0980, close=1.1030),
        ]
        result = analyze_wicks(candles)

        assert result is not None
        assert result.candle_count == 2
        # Ratios should be computed from the one non-zero-range candle only
        assert result.avg_upper_wick_ratio > 0


# ─── Config Validation ────────────────────────────────────────

class TestPriceAnalysisConfig:
    def test_default_config(self) -> None:
        config = PriceAnalysisConfig()
        assert config.extreme_distance == 0.025
        assert config.impulse_limit == 3.0
        assert config.min_candles == 5

    def test_custom_config(self) -> None:
        config = PriceAnalysisConfig(
            extreme_distance=0.05,
            impulse_limit=2.0,
            min_candles=10,
        )
        assert config.extreme_distance == 0.05
        assert config.impulse_limit == 2.0

    def test_invalid_extreme_distance(self) -> None:
        with pytest.raises(ValueError, match="extreme_distance must be positive"):
            PriceAnalysisConfig(extreme_distance=0.0)

    def test_invalid_impulse_limit(self) -> None:
        with pytest.raises(ValueError, match="impulse_limit must be positive"):
            PriceAnalysisConfig(impulse_limit=-1.0)

    def test_invalid_min_candles(self) -> None:
        with pytest.raises(ValueError, match="min_candles must be >= 2"):
            PriceAnalysisConfig(min_candles=1)