"""
Integration test for Wolf 15-Layer System main loop.
"""

import pytest
from unittest.mock import Mock, patch
from analysis.synthesis import build_synthesis
from analysis.synthesis_adapter import adapt_synthesis
from constitution.verdict_engine import generate_l12_verdict


def test_build_synthesis_returns_l12_contract():
    """Test that build_synthesis returns data matching L12 contract."""
    result = build_synthesis("XAUUSD")

    # Check required keys from L12 contract
    required_keys = ["pair", "scores", "layers", "execution", "risk", "propfirm", "bias", "system"]
    for key in required_keys:
        assert key in result, f"Missing required key: {key}"

    # Check scores structure
    assert "wolf_30_point" in result["scores"]
    assert "f_score" in result["scores"]
    assert "t_score" in result["scores"]

    # Check layers structure
    assert "L8_tii_sym" in result["layers"]
    assert "L8_integrity_index" in result["layers"]
    assert "L7_monte_carlo_win" in result["layers"]

    # Check execution structure
    assert "direction" in result["execution"]
    assert "entry" in result["execution"]
    assert "rr_ratio" in result["execution"]


def test_adapt_synthesis_validates_contract():
    """Test that adapt_synthesis validates L12 contract."""
    valid_data = {
        "pair": "XAUUSD",
        "scores": {},
        "layers": {},
        "execution": {},
        "risk": {},
        "propfirm": {},
        "bias": {},
        "system": {},
    }

    # Should pass validation
    result = adapt_synthesis(valid_data)
    assert result["pair"] == "XAUUSD"

    # Should fail validation with missing key
    invalid_data = {"pair": "XAUUSD"}
    with pytest.raises(ValueError, match="SYNTHESIS CONTRACT ERROR"):
        adapt_synthesis(invalid_data)


def test_l12_verdict_generation():
    """Test L12 verdict generation."""
    synthesis = build_synthesis("XAUUSD")

    # Should not raise exception
    verdict = generate_l12_verdict(synthesis)

    # Check verdict structure
    assert "verdict" in verdict
    assert verdict["verdict"] in ["NO_TRADE", "HOLD", "EXECUTE_BUY", "EXECUTE_SELL"]
    assert "confidence" in verdict
    assert "gates" in verdict


def test_synthesis_engine_layers():
    """Test that SynthesisEngine can build candidate."""
    from analysis.synthesis import SynthesisEngine

    engine = SynthesisEngine()
    candidate = engine.build_candidate("EURUSD")

    # Check candidate has all layers
    assert "symbol" in candidate
    assert candidate["symbol"] == "EURUSD"
    assert "L1" in candidate
    assert "L8" in candidate
    assert "valid" in candidate


@patch("storage.redis_client.redis.Redis.from_url")
def test_imports_no_redis_error(mock_redis):
    """Test that imports work even if Redis is not available."""
    mock_redis.return_value = Mock()

    # These should import without error
    from storage.l12_cache import set_verdict, get_verdict
    from storage.snapshot_store import save_snapshot

    # Should be callable
    assert callable(set_verdict)
    assert callable(get_verdict)
    assert callable(save_snapshot)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
