"""
Integration test for Wolf 15-Layer System main loop.

Updated to use WolfConstitutionalPipeline (single canonical pipeline).
"""

from unittest.mock import Mock, patch

import pytest

from constitution.verdict_engine import generate_l12_verdict
from pipeline import WolfConstitutionalPipeline


def test_pipeline_returns_l12_contract():
    """Test that pipeline returns data matching L12 contract."""
    pipeline = WolfConstitutionalPipeline()
    result = pipeline.execute("XAUUSD")

    # Check result structure
    assert "synthesis" in result
    assert "l12_verdict" in result
    assert "reflective" in result
    assert "sovereignty" in result
    assert "latency_ms" in result

    synthesis = result["synthesis"]

    # Check required keys from L12 contract
    required_keys = ["pair", "scores", "layers", "execution", "risk", "propfirm", "bias", "system"]
    for key in required_keys:
        assert key in synthesis, f"Missing required key: {key}"

    # Check scores structure
    assert "wolf_30_point" in synthesis["scores"]
    assert "f_score" in synthesis["scores"]
    assert "t_score" in synthesis["scores"]

    # Check layers structure
    assert "L8_tii_sym" in synthesis["layers"]
    assert "L8_integrity_index" in synthesis["layers"]
    assert "L7_monte_carlo_win" in synthesis["layers"]

    # Check execution structure
    assert "direction" in synthesis["execution"]
    assert "entry_price" in synthesis["execution"]
    assert "rr_ratio" in synthesis["execution"]


def test_pipeline_validates_contract():
    """Test that pipeline produces valid L12 contract."""
    pipeline = WolfConstitutionalPipeline()
    result = pipeline.execute("XAUUSD")

    synthesis = result["synthesis"]

    # Synthesis should be compatible with L12 verdict engine
    verdict = generate_l12_verdict(synthesis)

    # Check verdict structure
    assert "verdict" in verdict
    assert verdict["verdict"] in ["NO_TRADE", "HOLD", "EXECUTE_BUY", "EXECUTE_SELL"]
    assert "confidence" in verdict
    assert "gates" in verdict


def test_l12_verdict_generation():
    """Test L12 verdict generation with pipeline synthesis."""
    pipeline = WolfConstitutionalPipeline()
    result = pipeline.execute("XAUUSD")

    synthesis = result["synthesis"]
    l12_verdict = result["l12_verdict"]

    # Should not raise exception
    assert l12_verdict is not None

    # Check verdict structure
    assert "verdict" in l12_verdict
    assert l12_verdict["verdict"] in ["NO_TRADE", "HOLD", "EXECUTE_BUY", "EXECUTE_SELL"]
    assert "confidence" in l12_verdict
    assert "gates" in l12_verdict


def test_pipeline_layer_execution():
    """Test that pipeline executes all layers."""
    pipeline = WolfConstitutionalPipeline()
    result = pipeline.execute("EURUSD")

    synthesis = result["synthesis"]

    # Check synthesis has required structure
    assert "pair" in synthesis
    assert synthesis["pair"] == "EURUSD"
    assert "scores" in synthesis
    assert "layers" in synthesis
    assert "execution" in synthesis


@patch("storage.redis_client.redis.Redis.from_url")
def test_imports_no_redis_error(mock_redis):
    """Test that imports work even if Redis is not available."""
    mock_redis.return_value = Mock()

    # These should import without error
    from storage.l12_cache import get_verdict, set_verdict
    from storage.snapshot_store import save_snapshot

    # Should be callable
    assert callable(set_verdict)
    assert callable(get_verdict)
    assert callable(save_snapshot)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
