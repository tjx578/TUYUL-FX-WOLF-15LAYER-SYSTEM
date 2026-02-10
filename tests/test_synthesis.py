"""
Unit tests for synthesis engine.

Tests build_synthesis() and adapt_synthesis() with various contexts.
"""

import pytest
from unittest.mock import MagicMock, patch

from analysis.synthesis import build_synthesis
from analysis.synthesis_adapter import adapt_synthesis


class TestBuildSynthesis:
    """Test build_synthesis() function."""

    @patch("analysis.synthesis.SynthesisEngine")
    def test_build_synthesis_with_empty_context(
        self, mock_engine_class: MagicMock
    ) -> None:
        """Test build_synthesis with empty LiveContextBus."""
        # Mock the engine to return safe defaults
        mock_engine = MagicMock()
        mock_engine_class.return_value = mock_engine
        
        # Mock all layer outputs to return {"valid": False}
        mock_engine.build_candidate.return_value = {
            "l1": {"valid": False},
            "l2": {"valid": False},
            "l3": {"valid": False},
            "l4": {"valid": False},
            "l5": {"valid": False},
            "l6": {"valid": False},
            "l7": {"valid": False},
            "l8": {"valid": False},
            "l9": {"valid": False},
            "l10": {"valid": False},
            "l11": {"valid": False},
        }
        
        result = build_synthesis("EURUSD")
        
        # Should return a result even with empty context
        assert result is not None
        assert isinstance(result, dict)

    @patch("analysis.synthesis.SynthesisEngine")
    def test_build_synthesis_with_populated_data(
        self, mock_engine_class: MagicMock
    ) -> None:
        """Test build_synthesis with populated candle data."""
        # Mock the engine to return valid data
        mock_engine = MagicMock()
        mock_engine_class.return_value = mock_engine
        
        mock_engine.build_candidate.return_value = {
            "L1": {"valid": True, "regime": "TRENDING"},
            "L2": {"valid": True, "alignment": "BULLISH"},
            "L3": {"valid": True, "bias": "BULLISH", "trend": "BULLISH"},
            "L4": {"valid": True, "score": 75, "technical_score": 75, "fundamental_score": 60},
            "L5": {"valid": True, "stable": True},
            "L6": {"valid": True, "risk": "LOW"},
            "L7": {"valid": True, "probability": 0.75, "win_probability": 75},
            "L8": {"valid": True, "integrity": 0.85, "tii_sym": 0.85},
            "L9": {"valid": True, "confidence": 0.80},
            "L10": {"valid": True, "size": 0.02},
            "L11": {"valid": True, "rr": 2.5},
        }
        
        result = build_synthesis("EURUSD")
        
        # Should return valid synthesis
        assert result is not None
        assert isinstance(result, dict)
        # Check for contract fields instead of raw layer data
        assert "pair" in result
        assert "scores" in result
        assert "layers" in result
        assert "execution" in result


class TestAdaptSynthesis:
    """Test adapt_synthesis() contract validation."""

    def test_adapt_synthesis_with_valid_input(self) -> None:
        """Test adapt_synthesis with valid synthesis input."""
        raw_synthesis = {
            "pair": "EURUSD",
            "layers": {
                "L1": {"valid": True},
                "L2": {"valid": True},
                "L3": {"valid": True},
            },
            "scores": {
                "wolf_30_point": 25,
                "f_score": 8,
                "t_score": 9,
            },
            "execution": {
                "rr_ratio": 2.0,
                "entry": 1.0850,
            },
            "risk": {
                "current_drawdown": 2.0,
            },
            "propfirm": {
                "compliant": True,
            },
            "bias": {
                "technical": "BULLISH",
                "fundamental": "NEUTRAL",
            },
            "system": {
                "latency_ms": 50,
            },
        }
        
        result = adapt_synthesis(raw_synthesis)
        
        # Should return adapted contract
        assert result is not None
        assert isinstance(result, dict)
        assert "pair" in result
        assert "layers" in result
        assert "scores" in result

    def test_adapt_synthesis_with_missing_critical_key(self) -> None:
        """Test adapt_synthesis raises ValueError for missing critical keys."""
        # Missing pair (critical)
        raw_synthesis = {
            "layers": {},
            "scores": {},
            "execution": {},
            "risk": {},
            "propfirm": {},
            "bias": {},
            "system": {},
        }
        
        # Should raise ValueError
        with pytest.raises(ValueError, match="pair"):
            adapt_synthesis(raw_synthesis)

    def test_adapt_synthesis_preserves_valid_data(self) -> None:
        """Test adapt_synthesis preserves valid input data."""
        raw_synthesis = {
            "pair": "XAUUSD",
            "layers": {
                "L1": {"valid": True, "regime": "TRENDING"},
            },
            "scores": {
                "wolf_30_point": 28,
            },
            "execution": {
                "rr_ratio": 2.5,
            },
            "risk": {
                "current_drawdown": 1.5,
            },
            "propfirm": {
                "compliant": True,
            },
            "bias": {
                "technical": "BEARISH",
            },
            "system": {
                "latency_ms": 100,
            },
        }
        
        result = adapt_synthesis(raw_synthesis)
        
        # Verify data is preserved
        assert result["pair"] == "XAUUSD"
        assert result["layers"]["L1"]["regime"] == "TRENDING"
        assert result["scores"]["wolf_30_point"] == 28
        assert result["bias"]["technical"] == "BEARISH"

    def test_adapt_synthesis_contract_has_required_fields(self) -> None:
        """Test adapted contract has all required fields."""
        raw_synthesis = {
            "pair": "GBPJPY",
            "layers": {},
            "scores": {},
            "execution": {},
            "risk": {},
            "propfirm": {},
            "bias": {},
            "system": {},
        }
        
        result = adapt_synthesis(raw_synthesis)
        
        # Check required top-level fields
        required_fields = [
            "pair", "layers", "scores", "bias", "system",
            "execution", "risk", "propfirm"
        ]
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"
