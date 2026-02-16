"""
Integration test for Wolf 15-Layer System.

Tests the synthesis -> verdict -> reflective pipeline using
build_l12_synthesis + generate_l12_verdict (the constitutional pipeline).
"""

from unittest.mock import Mock, patch

import pytest

from constitution.verdict_engine import generate_l12_verdict
from pipeline.wolf_constitutional_pipeline import build_l12_synthesis

# -- Shared mock layer results for synthesis builder ---------------------

_MOCK_LAYERS = {
    "L1": {"session": "LONDON", "volatility": "NORMAL", "direction": "BUY", "strength": 0.7},
    "L2": {"direction": "BUY", "strength": 0.65, "trend": "BULLISH"},
    "L3": {"direction": "BUY", "strength": 0.6, "rsi": 58, "macd_signal": 0.3},
    "L4": {"direction": "BUY", "score": 70},
    "L6": {"risk_score": 0.6, "volatility": "NORMAL"},
    "L8": {"tii_score": 0.72, "symmetry_index": 0.8},
    "L9": {"smc_bias": "BUY", "order_block": True},
}


def test_pipeline_returns_l12_contract():
    """Test that synthesis builder returns data matching expected structure."""
    synthesis = build_l12_synthesis(_MOCK_LAYERS)

    assert isinstance(synthesis, dict)
    # Check required top-level keys
    for key in ("scores", "layers", "execution", "bias"):
        assert key in synthesis, f"Missing required key: {key}"


def test_pipeline_validates_contract():
    """Test that synthesis is compatible with L12 verdict engine."""
    synthesis = build_l12_synthesis(_MOCK_LAYERS)

    # Synthesis should be processable by L12 verdict engine
    verdict = generate_l12_verdict(synthesis)

    assert "verdict" in verdict
    assert verdict["verdict"] in ["NO_TRADE", "HOLD", "EXECUTE_BUY", "EXECUTE_SELL"]
    assert "confidence" in verdict
    assert "gates" in verdict


def test_l12_verdict_generation():
    """Test L12 verdict generation with synthesis data."""
    synthesis = build_l12_synthesis(_MOCK_LAYERS)
    verdict = generate_l12_verdict(synthesis)

    assert verdict is not None
    assert "verdict" in verdict
    assert verdict["verdict"] in ["NO_TRADE", "HOLD", "EXECUTE_BUY", "EXECUTE_SELL"]
    assert "confidence" in verdict
    assert "gates" in verdict


def test_pipeline_layer_execution():
    """Test that synthesis builder processes layer results correctly."""
    layers_eurusd = dict(_MOCK_LAYERS)
    synthesis = build_l12_synthesis(layers_eurusd)

    assert isinstance(synthesis, dict)
    assert "scores" in synthesis
    assert "execution" in synthesis


@patch("storage.redis_client.redis.Redis.from_url")
def test_imports_no_redis_error(mock_redis):
    """Test that imports work even if Redis is not available."""
    mock_redis.return_value = Mock()

    # These should import without error
    from storage.l12_cache import get_verdict, set_verdict  # noqa: PLC0415
    from storage.snapshot_store import save_snapshot  # noqa: PLC0415

    # Should be callable
    assert callable(set_verdict)
    assert callable(get_verdict)
    assert callable(save_snapshot)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
