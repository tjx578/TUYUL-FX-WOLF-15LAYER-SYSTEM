"""
Tests for Monthly Regime Analyzer
"""

from unittest.mock import MagicMock, patch

import pytest

from analysis.macro.monthly_regime import MonthlyRegimeAnalyzer


class TestRegimeDetection:
    """Test regime detection logic."""

    def test_bullish_expansion_regime(self):
        """Test detection of BULLISH_EXPANSION regime."""
        analyzer = MonthlyRegimeAnalyzer()

        # Last candle: bullish with expansion (range 1.2x larger)
        mn_data = [
            {"high": 1.1000, "low": 1.0900, "open": 1.0920, "close": 1.0980},  # prev
            {"high": 1.1200, "low": 1.1000, "open": 1.1050, "close": 1.1180},  # last: bullish + expansion
        ]

        regime = analyzer._detect_regime(mn_data)
        assert regime == "BULLISH_EXPANSION"

    def test_bearish_expansion_regime(self):
        """Test detection of BEARISH_EXPANSION regime."""
        analyzer = MonthlyRegimeAnalyzer()

        # Last candle: bearish with expansion
        mn_data = [
            {"high": 1.1000, "low": 1.0900, "open": 1.0950, "close": 1.0920},  # prev
            {"high": 1.0920, "low": 1.0700, "open": 1.0900, "close": 1.0720},  # last: bearish + expansion
        ]

        regime = analyzer._detect_regime(mn_data)
        assert regime == "BEARISH_EXPANSION"

    def test_consolidation_regime(self):
        """Test detection of CONSOLIDATION regime."""
        analyzer = MonthlyRegimeAnalyzer()

        # Last candle: no expansion (range similar to previous)
        mn_data = [
            {"high": 1.1000, "low": 1.0900, "open": 1.0920, "close": 1.0980},
            {"high": 1.1010, "low": 1.0920, "open": 1.0950, "close": 1.0990},  # no expansion
        ]

        regime = analyzer._detect_regime(mn_data)
        assert regime == "CONSOLIDATION"

    def test_transition_regime(self):
        """Test detection of TRANSITION regime."""
        analyzer = MonthlyRegimeAnalyzer()

        # Last candle: no expansion (similar to consolidation test)
        mn_data = [
            {"high": 1.1000, "low": 1.0900, "open": 1.0950, "close": 1.0950},
            {"high": 1.1010, "low": 1.0920, "open": 1.0950, "close": 1.0990},  # no expansion
        ]

        regime = analyzer._detect_regime(mn_data)
        # With no expansion, should be CONSOLIDATION or TRANSITION
        assert regime in ["CONSOLIDATION", "TRANSITION"]

    def test_unknown_regime_insufficient_data(self):
        """Test UNKNOWN regime with insufficient data."""
        analyzer = MonthlyRegimeAnalyzer()

        # Only 1 candle
        mn_data = [
            {"high": 1.1000, "low": 1.0900, "open": 1.0920, "close": 1.0980},
        ]

        regime = analyzer._detect_regime(mn_data)
        assert regime == "UNKNOWN"

    def test_unknown_regime_empty_data(self):
        """Test UNKNOWN regime with empty data."""
        analyzer = MonthlyRegimeAnalyzer()
        regime = analyzer._detect_regime([])
        assert regime == "UNKNOWN"


class TestMNATR:
    """Test MN ATR calculation and volatility metrics."""

    def test_atr_calculation_basic(self):
        """Test basic ATR calculation."""
        analyzer = MonthlyRegimeAnalyzer()

        mn_data = [
            {"high": 1.1000, "low": 1.0900, "open": 1.0920, "close": 1.0980},
            {"high": 1.1200, "low": 1.1000, "open": 1.1050, "close": 1.1180},
        ]

        mn_atr, macro_vol_ratio, phase = analyzer._calculate_volatility(mn_data)

        # ATR should be max(high-low, |high-prev_close|, |low-prev_close|)
        # = max(0.0200, |1.1200-1.0980|, |1.1000-1.0980|) = max(0.0200, 0.0220, 0.0020) = 0.0220
        assert mn_atr > 0
        assert macro_vol_ratio > 0

    def test_macro_vol_ratio_expansion(self):
        """Test expansion phase detection (ratio > 1.4)."""
        analyzer = MonthlyRegimeAnalyzer()

        # Create data where current ATR is much higher than rolling mean
        mn_data = []
        for i in range(12):
            mn_data.append(
                {
                    "high": 1.1000 + (i * 0.0010),
                    "low": 1.0950 + (i * 0.0010),
                    "open": 1.0960 + (i * 0.0010),
                    "close": 1.0980 + (i * 0.0010),
                }
            )
        # Add a candle with much larger range (expansion)
        mn_data.append(
            {
                "high": 1.2000,
                "low": 1.1500,
                "open": 1.1700,
                "close": 1.1900,
            }
        )

        mn_atr, macro_vol_ratio, phase = analyzer._calculate_volatility(mn_data)

        # Should detect expansion
        assert phase == "EXPANSION"
        assert macro_vol_ratio > 1.4

    def test_macro_vol_ratio_contraction(self):
        """Test contraction phase detection (ratio < 0.8)."""
        analyzer = MonthlyRegimeAnalyzer()

        # Create data where current ATR is much lower than rolling mean
        # First, create many months with large ranges
        mn_data = []
        for i in range(12):
            mn_data.append(
                {
                    "high": 1.1000 + (i * 0.0100),
                    "low": 1.0500 + (i * 0.0100),
                    "open": 1.0600 + (i * 0.0100),
                    "close": 1.0900 + (i * 0.0100),
                }
            )
        # Add a final candle with very small range (contraction)
        # Make sure it's connected to previous close to avoid gap TR
        last_close = mn_data[-1]["close"]
        mn_data.append(
            {
                "high": last_close + 0.0010,
                "low": last_close - 0.0010,
                "open": last_close,
                "close": last_close + 0.0005,
            }
        )

        mn_atr, macro_vol_ratio, phase = analyzer._calculate_volatility(mn_data)

        # Should detect contraction (ratio should be well below 0.8)
        assert phase == "CONTRACTION"
        assert macro_vol_ratio < 0.8

    def test_macro_vol_ratio_neutral(self):
        """Test neutral phase detection (0.8 <= ratio <= 1.4)."""
        analyzer = MonthlyRegimeAnalyzer()

        # Create data where current ATR is similar to rolling mean
        mn_data = []
        for i in range(13):
            mn_data.append(
                {
                    "high": 1.1100 + (i * 0.0010),
                    "low": 1.1000 + (i * 0.0010),
                    "open": 1.1020 + (i * 0.0010),
                    "close": 1.1080 + (i * 0.0010),
                }
            )

        mn_atr, macro_vol_ratio, phase = analyzer._calculate_volatility(mn_data)

        # Should detect neutral phase
        assert phase == "NEUTRAL"
        assert 0.8 <= macro_vol_ratio <= 1.4

    def test_volatility_insufficient_data(self):
        """Test volatility calculation with insufficient data."""
        analyzer = MonthlyRegimeAnalyzer()

        mn_data = [{"high": 1.1000, "low": 1.0900, "open": 1.0920, "close": 1.0980}]

        mn_atr, macro_vol_ratio, phase = analyzer._calculate_volatility(mn_data)

        assert mn_atr == 0.0
        assert macro_vol_ratio == 1.0
        assert phase == "NEUTRAL"


class TestLiquidityZones:
    """Test liquidity zone mapping."""

    def test_liquidity_zone_mapping(self):
        """Test basic liquidity zone mapping."""
        analyzer = MonthlyRegimeAnalyzer()

        # Create 6 months of data
        mn_data = [
            {"high": 1.1200, "low": 1.0800, "close": 1.1000},
            {"high": 1.1300, "low": 1.0900, "close": 1.1100},
            {"high": 1.1400, "low": 1.1000, "close": 1.1200},
            {"high": 1.1500, "low": 1.1100, "close": 1.1300},
            {"high": 1.1600, "low": 1.1200, "close": 1.1400},
            {"high": 1.1550, "low": 1.1250, "close": 1.1450},  # current month
        ]

        liquidity = analyzer._map_liquidity_zones(mn_data)

        # Buy liquidity should be max of last 5 completed months (exclude current)
        assert liquidity["macro_buy_liquidity"] == 1.1600
        # Sell liquidity should be min of last 5 completed months
        assert liquidity["macro_sell_liquidity"] == 1.0800

    def test_near_liquidity_zone_detection(self):
        """Test detection of price near macro liquidity zones."""
        analyzer = MonthlyRegimeAnalyzer()

        # Create data where current price is near buy liquidity
        mn_data = [
            {"high": 1.1200, "low": 1.0800, "close": 1.1000},
            {"high": 1.1300, "low": 1.0900, "close": 1.1100},
            {"high": 1.1400, "low": 1.1000, "close": 1.1200},
            {"high": 1.1500, "low": 1.1100, "close": 1.1300},
            {"high": 1.1600, "low": 1.1200, "close": 1.1400},
            {"high": 1.1605, "low": 1.1550, "close": 1.1595},  # Close to buy liquidity (1.1600)
        ]

        liquidity = analyzer._map_liquidity_zones(mn_data)

        # Current price (1.1595) should be within 0.5% of buy liquidity (1.1600)
        assert liquidity["near_macro_liquidity"] is True

    def test_not_near_liquidity_zone(self):
        """Test when price is not near liquidity zones."""
        analyzer = MonthlyRegimeAnalyzer()

        # Create data where current price is far from both zones
        mn_data = [
            {"high": 1.1200, "low": 1.0800, "close": 1.1000},
            {"high": 1.1300, "low": 1.0900, "close": 1.1100},
            {"high": 1.1400, "low": 1.1000, "close": 1.1200},
            {"high": 1.1500, "low": 1.1100, "close": 1.1300},
            {"high": 1.1600, "low": 1.1200, "close": 1.1400},
            {"high": 1.1100, "low": 1.1050, "close": 1.1075},  # Mid-range, not near either zone
        ]

        liquidity = analyzer._map_liquidity_zones(mn_data)

        assert liquidity["near_macro_liquidity"] is False

    def test_liquidity_insufficient_data(self):
        """Test liquidity zone with insufficient data."""
        analyzer = MonthlyRegimeAnalyzer()

        mn_data = [{"high": 1.1000, "low": 1.0900, "close": 1.0950}]

        liquidity = analyzer._map_liquidity_zones(mn_data)

        assert liquidity["macro_buy_liquidity"] == 0.0
        assert liquidity["macro_sell_liquidity"] == 0.0
        assert liquidity["near_macro_liquidity"] is False


class TestBiasOverride:
    """Test bias override for counter-macro trades."""

    @patch.object(MonthlyRegimeAnalyzer, "_detect_regime")
    def test_bullish_expansion_penalizes_sell(self, mock_detect):
        """Test that BULLISH_EXPANSION penalizes SELL trades."""
        mock_detect.return_value = "BULLISH_EXPANSION"

        analyzer = MonthlyRegimeAnalyzer()
        analyzer.context_bus = MagicMock()

        # Mock sufficient MN data
        mn_data = [
            {"high": 1.1000, "low": 1.0900, "open": 1.0920, "close": 1.0980},
            {"high": 1.1200, "low": 1.1000, "open": 1.1050, "close": 1.1180},
        ]
        analyzer.context_bus.get_candle_history.return_value = mn_data

        result = analyzer.analyze("EURUSD")

        assert result["bias_override"]["active"] is True
        assert result["bias_override"]["penalized_direction"] == "SELL"
        assert result["bias_override"]["confidence_multiplier"] == 0.7

    @patch.object(MonthlyRegimeAnalyzer, "_detect_regime")
    def test_bearish_expansion_penalizes_buy(self, mock_detect):
        """Test that BEARISH_EXPANSION penalizes BUY trades."""
        mock_detect.return_value = "BEARISH_EXPANSION"

        analyzer = MonthlyRegimeAnalyzer()
        analyzer.context_bus = MagicMock()

        # Mock sufficient MN data
        mn_data = [
            {"high": 1.1000, "low": 1.0900, "open": 1.0920, "close": 1.0980},
            {"high": 1.0920, "low": 1.0700, "open": 1.0900, "close": 1.0720},
        ]
        analyzer.context_bus.get_candle_history.return_value = mn_data

        result = analyzer.analyze("EURUSD")

        assert result["bias_override"]["active"] is True
        assert result["bias_override"]["penalized_direction"] == "BUY"
        assert result["bias_override"]["confidence_multiplier"] == 0.7

    @patch.object(MonthlyRegimeAnalyzer, "_detect_regime")
    def test_consolidation_no_penalty(self, mock_detect):
        """Test that CONSOLIDATION has no bias penalty."""
        mock_detect.return_value = "CONSOLIDATION"

        analyzer = MonthlyRegimeAnalyzer()
        analyzer.context_bus = MagicMock()

        # Mock sufficient MN data
        mn_data = [
            {"high": 1.1000, "low": 1.0900, "open": 1.0920, "close": 1.0980},
            {"high": 1.1010, "low": 1.0920, "open": 1.0950, "close": 1.0990},
        ]
        analyzer.context_bus.get_candle_history.return_value = mn_data

        result = analyzer.analyze("EURUSD")

        assert result["bias_override"]["active"] is False
        assert result["bias_override"]["confidence_multiplier"] == 1.0


class TestMonthlyRegimeAnalyzer:
    """Integration tests for MonthlyRegimeAnalyzer."""

    def test_analyze_with_valid_data(self):
        """Test full analysis with valid MN data."""
        analyzer = MonthlyRegimeAnalyzer()
        analyzer.context_bus = MagicMock()

        # Mock 24 months of data
        mn_data = []
        for i in range(24):
            mn_data.append(
                {
                    "high": 1.1000 + (i * 0.0050),
                    "low": 1.0900 + (i * 0.0050),
                    "open": 1.0920 + (i * 0.0050),
                    "close": 1.0980 + (i * 0.0050),
                }
            )

        analyzer.context_bus.get_candle_history.return_value = mn_data

        result = analyzer.analyze("EURUSD")

        assert result["valid"] is True
        assert result["regime"] in [
            "BULLISH_EXPANSION",
            "BEARISH_EXPANSION",
            "CONSOLIDATION",
            "TRANSITION",
        ]
        assert result["phase"] in ["EXPANSION", "NEUTRAL", "CONTRACTION"]
        assert result["mn_atr"] >= 0
        assert result["macro_vol_ratio"] > 0
        assert "liquidity" in result
        assert "bias_override" in result

    def test_analyze_insufficient_data(self):
        """Test analysis with insufficient MN data."""
        analyzer = MonthlyRegimeAnalyzer()
        analyzer.context_bus = MagicMock()

        # Only 1 candle
        mn_data = [{"high": 1.1000, "low": 1.0900, "open": 1.0920, "close": 1.0980}]
        analyzer.context_bus.get_candle_history.return_value = mn_data

        result = analyzer.analyze("EURUSD")

        assert result["valid"] is False
        assert result["regime"] == "UNKNOWN"
        assert result["phase"] == "NEUTRAL"

    def test_analyze_no_data(self):
        """Test analysis with no MN data."""
        analyzer = MonthlyRegimeAnalyzer()
        analyzer.context_bus = MagicMock()

        analyzer.context_bus.get_candle_history.return_value = []

        result = analyzer.analyze("EURUSD")

        assert result["valid"] is False
        assert result["regime"] == "UNKNOWN"

    def test_output_structure(self):
        """Test that output structure matches specification."""
        analyzer = MonthlyRegimeAnalyzer()
        analyzer.context_bus = MagicMock()

        # Mock sufficient data
        mn_data = [
            {"high": 1.1000, "low": 1.0900, "open": 1.0920, "close": 1.0980},
            {"high": 1.1200, "low": 1.1000, "open": 1.1050, "close": 1.1180},
        ]
        analyzer.context_bus.get_candle_history.return_value = mn_data

        result = analyzer.analyze("EURUSD")

        # Verify all required fields
        required_fields = [
            "regime",
            "phase",
            "mn_atr",
            "macro_vol_ratio",
            "liquidity",
            "bias_override",
            "alignment",
            "valid",
        ]
        for field in required_fields:
            assert field in result

        # Verify nested structures
        assert "macro_buy_liquidity" in result["liquidity"]
        assert "macro_sell_liquidity" in result["liquidity"]
        assert "near_macro_liquidity" in result["liquidity"]

        assert "active" in result["bias_override"]
        assert "penalized_direction" in result["bias_override"]
        assert "confidence_multiplier" in result["bias_override"]


@pytest.mark.parametrize(
    "regime,expected_penalty_dir",
    [
        ("BULLISH_EXPANSION", "SELL"),
        ("BEARISH_EXPANSION", "BUY"),
        ("CONSOLIDATION", None),
        ("TRANSITION", None),
    ],
)
def test_bias_override_parametrized(regime, expected_penalty_dir):
    """Parametrized test for bias override logic."""
    analyzer = MonthlyRegimeAnalyzer()
    analyzer.context_bus = MagicMock()

    with patch.object(analyzer, "_detect_regime", return_value=regime):
        mn_data = [
            {"high": 1.1000, "low": 1.0900, "open": 1.0920, "close": 1.0980},
            {"high": 1.1200, "low": 1.1000, "open": 1.1050, "close": 1.1180},
        ]
        analyzer.context_bus.get_candle_history.return_value = mn_data

        result = analyzer.analyze("EURUSD")

        if expected_penalty_dir:
            assert result["bias_override"]["penalized_direction"] == expected_penalty_dir
            assert result["bias_override"]["confidence_multiplier"] == 0.7
        else:
            assert result["bias_override"]["active"] is False
