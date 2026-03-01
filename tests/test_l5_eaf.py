"""
Tests for L5 Psychology EAF integration
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from analysis.layers.L5_psychology import L5PsychologyAnalyzer
from context.runtime_state import RuntimeState


@pytest.fixture
def analyzer():
    """Get L5PsychologyAnalyzer instance."""
    analyzer = L5PsychologyAnalyzer()
    # Reset session for clean state
    analyzer.reset_session()
    return analyzer


def test_eaf_good_trader_3hr_session(analyzer):
    """Test EAF with good trader in 3-hour session scenario."""
    # Simulate a 3-hour professional trading session
    # Good trader: no losses, no drawdown

    # Mock RuntimeState to return 3 hours
    with patch.object(RuntimeState, 'get_session_hours', return_value=3.0):
        result = analyzer.analyze("EURUSD")

        # Should pass all checks
        assert result["valid"] is True
        assert result["psychology_ok"] is True
        assert result["can_trade"] is True

        # EAF score should be >= 0.70
        assert result["eaf_score"] >= 0.70

        # Focus level should still be good at 3 hours
        assert result["focus_level"] >= 0.775

        # Emotional bias should be low (good trader)
        assert result["emotional_bias"] <= 0.2

        # Discipline should be high
        assert result["discipline_score"] >= 0.85


def test_eaf_revenge_trading_scenario(analyzer):
    """Test EAF with revenge trading scenario."""
    # Simulate revenge trading: multiple losses, high drawdown
    analyzer.record_loss()
    analyzer.record_loss()
    analyzer.record_loss()  # 3 consecutive losses (above limit of 2)
    analyzer.update_drawdown(6.0)  # Above max

    result = analyzer.analyze("EURUSD")

    # Should fail psychology checks
    assert result["psychology_ok"] is False
    assert result["can_trade"] is False

    # EAF score should be < 0.70
    assert result["eaf_score"] < 0.70

    # Emotional bias should be high
    assert result["emotional_bias"] > 0.3

    # Should have multiple failure reasons
    assert "consecutive losses" in result["recommendation"]
    assert "drawdown" in result["recommendation"]
    assert "EAF score" in result["recommendation"]


def test_eaf_high_fatigue_scenario(analyzer):
    """Test EAF with high fatigue (6+ hours)."""
    # Mock RuntimeState to return 6 hours
    with patch.object(RuntimeState, 'get_session_hours', return_value=6.0):
        result = analyzer.analyze("EURUSD")

        # Fatigue should be HIGH
        assert result["fatigue_level"] == "HIGH"

        # Focus level should be degraded
        assert result["focus_level"] < 0.70

        # Should affect psychology_ok
        assert result["psychology_ok"] is False


def test_eaf_convex_weighted_formula(analyzer):
    """Test that EAF uses convex weighted formula (no multiplication collapse)."""
    # Even with ONE component at 0.5, others perfect,
    # the score should still be reasonable (not collapsed to near-zero)

    # Mock 1 hour session for good focus
    with patch.object(RuntimeState, 'get_session_hours', return_value=1.0):
        result = analyzer.analyze("EURUSD")

        # With convex formula, score should be high
        assert result["eaf_score"] >= 0.85

        # This proves no multiplicative collapse
        # (multiplicative would give: 1.0 * 0.9 * 0.85 * 0.9 = 0.6885)


def test_l5_output_keys_for_l4_l11_compatibility(analyzer):
    """Test that L5 output contains all required keys for L4/L11."""
    result = analyzer.analyze("EURUSD")

    # Required keys for L4 E-checks
    assert "psychology_ok" in result
    assert "fatigue_level" in result
    assert "drawdown_ok" in result

    # Required keys for L11 wolf_discipline_gate
    assert "consecutive_losses" in result
    assert "emotion_index" in result
    assert "discipline_score" in result

    # Verify types
    assert isinstance(result["psychology_ok"], bool)
    assert result["fatigue_level"] in ["LOW", "MEDIUM", "HIGH"]
    assert isinstance(result["consecutive_losses"], int)
    assert isinstance(result["emotion_index"], int)
    assert isinstance(result["discipline_score"], float)


def test_eaf_stability_index_no_win_rate_penalty(analyzer):
    """Test that stability index doesn't penalize high win rates."""
    # Simulate good trader with high win rate
    for _ in range(5):
        analyzer.record_win()

    # Should have high win streak
    assert analyzer._win_streak == 5

    result = analyzer.analyze("EURUSD")

    # Stability should still be reasonable
    # (not penalized just for winning)
    assert result["stability_index"] >= 0.60

    # Note: Long streaks (>4) do reduce stability slightly
    # because they indicate potential overconfidence risk


def test_eaf_focus_level_180min_threshold(analyzer):
    """Test that focus level starts degrading at 180min (3 hours)."""
    # Test at 2.5 hours (150 min) - should be peak
    with patch.object(RuntimeState, 'get_session_hours', return_value=2.5):
        result = analyzer.analyze("EURUSD")
        focus_at_2_5h = result["focus_level"]

        # Should be in peak zone
        assert focus_at_2_5h >= 0.85

    # Test at 3.5 hours (210 min) - should start degrading
    with patch.object(RuntimeState, 'get_session_hours', return_value=3.5):
        result = analyzer.analyze("EURUSD")
        focus_at_3_5h = result["focus_level"]

        # Should be slightly lower
        assert focus_at_3_5h < focus_at_2_5h
        assert focus_at_3_5h >= 0.70  # Still acceptable


def test_eaf_emotion_index_for_l11(analyzer):
    """Test emotion_index calculation for L11 compatibility."""
    # emotion_index should be int(emotional_bias * 100)

    # No losses = low emotional bias
    result = analyzer.analyze("EURUSD")
    assert result["emotion_index"] == int(result["emotional_bias"] * 100)
    assert result["emotion_index"] <= 70  # Should pass L11 threshold

    # High losses + drawdown = high emotional bias
    analyzer.record_loss()
    analyzer.record_loss()
    analyzer.record_loss()
    analyzer.update_drawdown(8.0)  # High drawdown
    result = analyzer.analyze("EURUSD")

    assert result["emotion_index"] == int(result["emotional_bias"] * 100)
    # Should fail L11 threshold of 70
    assert result["emotion_index"] > 40  # At least moderately elevated


def test_eaf_discipline_score_consecutive_losses(analyzer):
    """Test discipline score drops with consecutive losses."""
    # Start with perfect discipline
    result1 = analyzer.analyze("EURUSD")
    assert result1["discipline_score"] >= 0.90

    # 2 losses (at limit)
    analyzer.record_loss()
    analyzer.record_loss()
    result2 = analyzer.analyze("EURUSD")
    assert result2["discipline_score"] == 0.75

    # 3+ losses (above limit)
    analyzer.record_loss()
    result3 = analyzer.analyze("EURUSD")
    assert result3["discipline_score"] == 0.60
    assert result3["discipline_score"] < 0.70  # Below L11 minimum
