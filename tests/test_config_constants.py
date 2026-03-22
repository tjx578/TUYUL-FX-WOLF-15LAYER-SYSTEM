"""
Tests for config.constants module
"""

from config.constants import CONSTITUTION_THRESHOLDS, get_all_thresholds, get_threshold


def test_get_threshold_top_level():
    """Test getting top-level threshold values."""
    tii_min = get_threshold("tii_min")
    assert tii_min == 0.93

    integrity_min = get_threshold("integrity_min")
    assert integrity_min == 0.97

    rr_min = get_threshold("rr_min")
    assert rr_min == 2.0


def test_get_threshold_nested():
    """Test getting nested threshold values with dot notation."""
    tii_const_min = get_threshold("tii.constitutional_min")
    assert tii_const_min == 0.93

    wolf_min = get_threshold("wolf_discipline.minimum")
    assert wolf_min == 0.75

    drift_safe = get_threshold("drift.safe")
    assert drift_safe == 0.003


def test_get_threshold_with_default():
    """Test getting threshold with default value."""
    # Non-existent key should return default
    value = get_threshold("nonexistent.key", 99.9)
    assert value == 99.9

    # Existing key should ignore default
    value = get_threshold("tii_min", 99.9)
    assert value == 0.93


def test_get_threshold_deeply_nested():
    """Test getting deeply nested values."""
    tech_min = get_threshold("wolf_30_point.sub_thresholds.technical_min")
    assert tech_min == 9

    max_losses = get_threshold("wolf_discipline.emotion.max_consecutive_losses")
    assert max_losses == 2


def test_backward_compatibility():
    """Test that CONSTITUTION_THRESHOLDS works for legacy code."""
    # Should be able to access top-level keys
    assert CONSTITUTION_THRESHOLDS["tii_min"] == 0.93
    assert CONSTITUTION_THRESHOLDS["integrity_min"] == 0.97
    assert CONSTITUTION_THRESHOLDS["rr_min"] == 2.0

    # Should be able to access nested structures
    assert "tii" in CONSTITUTION_THRESHOLDS
    assert CONSTITUTION_THRESHOLDS["tii"]["constitutional_min"] == 0.93


def test_get_all_thresholds():
    """Test getting complete configuration."""
    config = get_all_thresholds()

    assert isinstance(config, dict)
    assert "tii_min" in config
    assert "tii" in config
    assert "wolf_discipline" in config

    # Should be a copy, not the original
    config["test_key"] = "test_value"
    config2 = get_all_thresholds()
    assert "test_key" not in config2


def test_threshold_values_reconciled():
    """Test that conflicting values are reconciled."""
    # TII: top-level should match nested
    assert get_threshold("tii_min") == get_threshold("tii.constitutional_min")

    # Integrity: should be 0.97 (reconciled value)
    assert get_threshold("integrity_min") == 0.97

    # Monte Carlo: should be 0.55 (reconciled value)
    assert get_threshold("monte_min") == 0.55

    # Max drawdown: should be 5.0 (reconciled value)
    assert get_threshold("max_drawdown") == 5.0


def test_eaf_thresholds():
    """Test EAF configuration thresholds."""
    eaf_min = get_threshold("eaf.min_for_trade")
    assert eaf_min == 0.70

    weights = get_threshold("eaf.weights")
    assert weights["emotional_bias"] == 0.30
    assert weights["stability_index"] == 0.25
    assert weights["focus_level"] == 0.25
    assert weights["discipline_score"] == 0.20

    # Sum of weights should be 1.0
    assert sum(weights.values()) == 1.0


def test_pipeline_thresholds():
    """Test pipeline configuration."""
    maxlen = get_threshold("pipeline.candle_history_maxlen")
    assert maxlen == 250
    assert maxlen > 200  # Must support EMA200


def test_l11_rr_by_regime():
    """Test L11 RR regime thresholds."""
    rr_by_regime = get_threshold("rr.by_regime")

    assert rr_by_regime["HIGH"] == 2.5
    assert rr_by_regime["NORMAL"] == 2.0
    assert rr_by_regime["LOW"] == 1.5
    assert rr_by_regime["TRENDING"] == 2.0
    assert rr_by_regime["RANGING"] == 1.8
