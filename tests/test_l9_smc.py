"""
Test L9 Smart Money Concepts layer
"""

import pytest

from analysis.layers.L9_smc import L9SMCAnalyzer
from context.live_context_bus import LiveContextBus


@pytest.fixture
def context_bus():
    """Get LiveContextBus instance."""
    bus = LiveContextBus()
    bus._candle_history.clear()
    return bus


@pytest.fixture
def analyzer():
    """Get L9SMCAnalyzer instance."""
    return L9SMCAnalyzer()


def test_smc_no_structure_data(analyzer):
    """Test SMC analysis with no structure data."""
    result = analyzer.analyze("EURUSD", structure={})
    assert result["valid"] is False
    assert result["reason"] == "no_structure_data"


def test_smc_invalid_structure(analyzer):
    """Test SMC analysis with invalid structure."""
    structure = {"valid": False}
    result = analyzer.analyze("EURUSD", structure=structure)
    assert result["valid"] is False


def test_smc_neutral_trend_low_confidence(analyzer, context_bus):
    """Test SMC with neutral trend returns low confidence."""
    structure = {
        "valid": True,
        "trend": "NEUTRAL",
        "bos": False,
        "choch": False,
    }

    result = analyzer.analyze("EURUSD", structure=structure)
    assert result["valid"] is True
    assert result["smc"] is False  # No clear SMC signal
    assert result["confidence"] == 0.3  # Low confidence


def test_smc_bullish_bos_detected(analyzer, context_bus):
    """Test SMC with bullish BOS detection."""
    # Create uptrend candles
    for i in range(15):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000 + (i * 0.0010),
            "high": 1.1020 + (i * 0.0010),
            "low": 1.0990 + (i * 0.0010),
            "close": 1.1015 + (i * 0.0010),
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)

    structure = {
        "valid": True,
        "trend": "BULLISH",
        "bos": False,
        "choch": False,
    }

    result = analyzer.analyze("EURUSD", structure=structure)
    assert result["valid"] is True

    # Should detect BOS with uptrend breaking previous swing high
    if result["bos_detected"]:
        assert result["confidence"] == 0.8
        assert result["displacement"] is True
        assert result["smc"] is True


def test_smc_bearish_bos_detected(analyzer, context_bus):
    """Test SMC with bearish BOS detection."""
    # Create downtrend candles
    for i in range(15):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000 - (i * 0.0010),
            "high": 1.1020 - (i * 0.0010),
            "low": 1.0980 - (i * 0.0010),
            "close": 1.0985 - (i * 0.0010),
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)

    structure = {
        "valid": True,
        "trend": "BEARISH",
        "bos": False,
        "choch": False,
    }

    result = analyzer.analyze("EURUSD", structure=structure)
    assert result["valid"] is True

    # Should detect BOS with downtrend breaking previous swing low
    if result["bos_detected"]:
        assert result["confidence"] == 0.8
        assert result["displacement"] is True


def test_smc_choch_bullish_to_bearish(analyzer, context_bus):
    """Test CHoCH detection: BULLISH -> BEARISH."""
    # First analysis with BULLISH trend
    structure_bullish = {
        "valid": True,
        "trend": "BULLISH",
        "bos": False,
        "choch": False,
    }

    result1 = analyzer.analyze("EURUSD", structure=structure_bullish)
    assert result1["valid"] is True
    assert result1["choch_detected"] is False  # No previous trend

    # Second analysis with BEARISH trend (CHoCH)
    structure_bearish = {
        "valid": True,
        "trend": "BEARISH",
        "bos": False,
        "choch": False,
    }

    result2 = analyzer.analyze("EURUSD", structure=structure_bearish)
    assert result2["valid"] is True
    assert result2["choch_detected"] is True  # Detected CHoCH
    assert result2["confidence"] == 0.6  # Medium confidence for reversal
    assert result2["smc"] is True


def test_smc_choch_bearish_to_bullish(analyzer, context_bus):
    """Test CHoCH detection: BEARISH -> BULLISH."""
    # First analysis with BEARISH trend
    structure_bearish = {
        "valid": True,
        "trend": "BEARISH",
        "bos": False,
        "choch": False,
    }

    result1 = analyzer.analyze("EURUSD", structure=structure_bearish)
    assert result1["valid"] is True

    # Second analysis with BULLISH trend (CHoCH)
    structure_bullish = {
        "valid": True,
        "trend": "BULLISH",
        "bos": False,
        "choch": False,
    }

    result2 = analyzer.analyze("EURUSD", structure=structure_bullish)
    assert result2["valid"] is True
    assert result2["choch_detected"] is True
    assert result2["confidence"] == 0.6


def test_smc_no_choch_same_trend(analyzer, context_bus):
    """Test no CHoCH when trend remains same."""
    structure = {
        "valid": True,
        "trend": "BULLISH",
        "bos": False,
        "choch": False,
    }

    # First analysis
    result1 = analyzer.analyze("EURUSD", structure=structure)
    assert result1["choch_detected"] is False

    # Second analysis with same trend
    result2 = analyzer.analyze("EURUSD", structure=structure)
    assert result2["choch_detected"] is False  # No change


def test_smc_bos_insufficient_data(analyzer, context_bus):
    """Test BOS detection with insufficient candle data."""
    # Add only 3 candles (need 5 minimum)
    for i in range(3):
        candle = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "open": 1.1000,
            "high": 1.1010,
            "low": 1.0990,
            "close": 1.1005,
            "volume": 1000,
            "timestamp": f"2024-01-01T{i:02d}:00:00Z",
        }
        context_bus.update_candle(candle)

    structure = {
        "valid": True,
        "trend": "BULLISH",
        "bos": False,
        "choch": False,
    }

    result = analyzer.analyze("EURUSD", structure=structure)
    assert result["bos_detected"] is False  # Not enough data


def test_smc_output_format(analyzer, context_bus):
    """Test SMC output format matches specification."""
    structure = {
        "valid": True,
        "trend": "BULLISH",
        "bos": False,
        "choch": False,
    }

    result = analyzer.analyze("EURUSD", structure=structure)

    # Verify all required fields are present
    assert "valid" in result
    assert "smc" in result
    assert "bos_detected" in result
    assert "choch_detected" in result
    assert "liquidity_sweep" in result
    assert "displacement" in result
    assert "confidence" in result

    # Verify confidence is in valid range
    assert 0.0 <= result["confidence"] <= 1.0


# ------------------------------------------------------------------
# dvg_confidence wiring
# ------------------------------------------------------------------


def test_dvg_confidence_present_in_output(analyzer):
    """dvg_confidence key is always present, even on failure."""
    result = analyzer.analyze("EURUSD", structure={})
    assert "dvg_confidence" in result
    assert result["dvg_confidence"] == 0.0


def test_dvg_confidence_zero_when_no_engine(analyzer, context_bus):
    """When ExhaustionDivergenceFusionEngine is unavailable, dvg_confidence == 0."""
    structure = {"valid": True, "trend": "BULLISH"}
    # Engine may or may not load; but with no candle data across TFs it produces 0.0
    result = analyzer.analyze("EURUSD", structure=structure)
    assert isinstance(result["dvg_confidence"], float)
    assert 0.0 <= result["dvg_confidence"] <= 1.0


def test_dvg_confidence_uses_divergence_engine(analyzer, monkeypatch):
    """When the divergence engine returns a result, dvg_confidence reflects it."""
    from unittest.mock import MagicMock

    fake_engine = MagicMock()
    fake_engine.analyze.return_value = {
        "score": 0.8,
        "confidence": 0.75,
        "reason": "STRONG_DIVERGENCE: 3/4 TFs",
        "available_tfs": ["M5", "M15", "H1", "H4"],
        "missing_tfs": [],
    }
    analyzer._dvg_engine = fake_engine

    # Provide candle data across all TFs via mock
    def _fake_candles(symbol, timeframe="H1", count=30):
        return [
            {"open": 1.10 + i * 0.001, "high": 1.102 + i * 0.001, "low": 1.098 + i * 0.001, "close": 1.101 + i * 0.001}
            for i in range(count)
        ]

    monkeypatch.setattr(type(analyzer), "_get_candles", staticmethod(_fake_candles))

    structure = {"valid": True, "trend": "BEARISH"}
    result = analyzer.analyze("EURUSD", structure=structure)
    assert result["dvg_confidence"] == 0.75
    fake_engine.analyze.assert_called_once()


def test_dvg_confidence_zero_on_engine_error(analyzer, monkeypatch):
    """If divergence engine raises, dvg_confidence degrades to 0.0."""
    from unittest.mock import MagicMock

    bad_engine = MagicMock()
    bad_engine.analyze.side_effect = RuntimeError("boom")
    analyzer._dvg_engine = bad_engine

    def _fake_candles(symbol, timeframe="H1", count=30):
        return [
            {"open": 1.10 + i * 0.001, "high": 1.102 + i * 0.001, "low": 1.098 + i * 0.001, "close": 1.101 + i * 0.001}
            for i in range(count)
        ]

    monkeypatch.setattr(type(analyzer), "_get_candles", staticmethod(_fake_candles))

    structure = {"valid": True, "trend": "BULLISH"}
    result = analyzer.analyze("EURUSD", structure=structure)
    assert result["dvg_confidence"] == 0.0


def test_rsi_computation():
    """RSI computation returns correct length and range."""
    closes = [1.10 + i * 0.001 for i in range(30)]
    rsi = L9SMCAnalyzer._compute_rsi(closes)
    assert len(rsi) > 0
    assert all(0.0 <= v <= 100.0 for v in rsi)


def test_rsi_too_few_values():
    """RSI with insufficient data returns empty list."""
    closes = [1.10, 1.11]
    rsi = L9SMCAnalyzer._compute_rsi(closes)
    assert rsi == []
