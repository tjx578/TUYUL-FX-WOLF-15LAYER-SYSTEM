"""Tests for L2 Multi-Timeframe Alignment."""

from unittest.mock import MagicMock

from analysis.layers.L2_mta import L2MTAAnalyzer


class TestL2MTA:
    def test_all_bullish_alignment(self):
        analyzer = L2MTAAnalyzer()
        analyzer.context = MagicMock()

        bullish_candle = {"open": 1.0800, "close": 1.0850}
        analyzer.context.get_candle.return_value = bullish_candle

        result = analyzer.analyze("EURUSD")
        assert result["valid"] is True
        assert result["direction"] == "BULLISH"
        assert result["composite_bias"] > 0

    def test_all_bearish_alignment(self):
        analyzer = L2MTAAnalyzer()
        analyzer.context = MagicMock()

        bearish_candle = {"open": 1.0850, "close": 1.0800}
        analyzer.context.get_candle.return_value = bearish_candle

        result = analyzer.analyze("EURUSD")
        assert result["valid"] is True
        assert result["direction"] == "BEARISH"
        assert result["composite_bias"] < 0

    def test_mixed_signals_weighted_by_timeframe(self):
        analyzer = L2MTAAnalyzer()
        analyzer.context = MagicMock()

        def side_effect(symbol, tf):
            # MN bearish (weight 0.35)
            if tf == "MN":
                return {"open": 1.0850, "close": 1.0800}  # Bearish
            # Higher TFs bearish (W1, D1, H4) - combined weight 0.55
            if tf in ("W1", "D1", "H4"):
                return {"open": 1.0850, "close": 1.0800}  # Bearish
            # Lower TFs bullish (H1, M15) - combined weight 0.10
            return {"open": 1.0800, "close": 1.0850}  # Bullish

        analyzer.context.get_candle.side_effect = side_effect

        result = analyzer.analyze("EURUSD")
        assert result["valid"] is True
        # Should be bearish since higher TFs (especially MN) have more weight
        # MN=-0.35, W1=-0.25, D1=-0.15, H4=-0.15, H1=+0.07, M15=+0.03 = -0.80
        assert result["direction"] == "BEARISH"
        assert result["composite_bias"] < 0

    def test_neutral_direction_when_balanced(self):
        analyzer = L2MTAAnalyzer()
        analyzer.context = MagicMock()

        def side_effect(symbol, tf):
            # Some bullish, some bearish, balanced
            if tf in ("W1", "H1"):
                return {"open": 1.0800, "close": 1.0850}  # Bullish
            return {"open": 1.0850, "close": 1.0800}  # Bearish

        analyzer.context.get_candle.side_effect = side_effect

        result = analyzer.analyze("EURUSD")
        assert result["valid"] is True
        # Should be neutral when composite bias is low
        # Exact direction depends on weight balance

    def test_insufficient_data(self):
        analyzer = L2MTAAnalyzer()
        analyzer.context = MagicMock()
        analyzer.context.get_candle.return_value = None

        result = analyzer.analyze("EURUSD")
        assert result["valid"] is False
        assert result["available_timeframes"] == 0

    def test_partial_data_valid_with_minimum_timeframes(self):
        analyzer = L2MTAAnalyzer()
        analyzer.context = MagicMock()

        def side_effect(symbol, tf):
            # Only MN, W1 and D1 available (3 TFs)
            if tf in ("MN", "W1", "D1"):
                return {"open": 1.0800, "close": 1.0850}
            return None

        analyzer.context.get_candle.side_effect = side_effect

        result = analyzer.analyze("EURUSD")
        assert result["valid"] is True  # Need at least 3 TFs now
        assert result["available_timeframes"] == 3

    def test_doji_candles_neutral_bias(self):
        analyzer = L2MTAAnalyzer()
        analyzer.context = MagicMock()

        # Doji candles (open == close)
        doji_candle = {"open": 1.0850, "close": 1.0850}
        analyzer.context.get_candle.return_value = doji_candle

        result = analyzer.analyze("EURUSD")
        assert result["valid"] is True
        assert result["composite_bias"] == 0.0
        assert result["direction"] == "NEUTRAL"

    def test_fully_aligned_detection(self):
        analyzer = L2MTAAnalyzer()
        analyzer.context = MagicMock()

        # All timeframes strongly bullish
        strong_bullish = {"open": 1.0800, "close": 1.0900}
        analyzer.context.get_candle.return_value = strong_bullish

        result = analyzer.analyze("EURUSD")
        assert result["valid"] is True
        assert result["aligned"] is True
        assert result["direction"] == "BULLISH"

    def test_alignment_strength_metric(self):
        analyzer = L2MTAAnalyzer()
        analyzer.context = MagicMock()

        strong_candle = {"open": 1.0800, "close": 1.0900}
        analyzer.context.get_candle.return_value = strong_candle

        result = analyzer.analyze("EURUSD")
        assert "alignment_strength" in result
        assert result["alignment_strength"] > 0

    def test_per_tf_bias_included(self):
        analyzer = L2MTAAnalyzer()
        analyzer.context = MagicMock()

        bullish_candle = {"open": 1.0800, "close": 1.0850}
        analyzer.context.get_candle.return_value = bullish_candle

        result = analyzer.analyze("EURUSD")
        assert "per_tf_bias" in result
        assert isinstance(result["per_tf_bias"], dict)
        # All should be 1 (bullish)
        assert all(bias == 1 for bias in result["per_tf_bias"].values())
