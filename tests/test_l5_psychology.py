"""
Test L5 Psychology layer
"""

import pytest

from analysis.layers.L5_psychology import L5PsychologyAnalyzer
from context.runtime_state import RuntimeState


@pytest.fixture
def analyzer():
    """Get L5PsychologyAnalyzer instance."""
    # Reset RuntimeState for each test
    RuntimeState.session_start = None
    return L5PsychologyAnalyzer()


def test_psychology_initial_state(analyzer):
    """Test psychology analyzer initial state."""
    result = analyzer.analyze("EURUSD")

    assert result["valid"] is True
    assert result["psychology_ok"] is True
    assert result["consecutive_losses"] == 0
    assert result["fatigue_level"] == "LOW"
    assert result["session_hours"] >= 0.0


def test_fatigue_level_low(analyzer):
    """Test LOW fatigue level (< 4 hours)."""
    result = analyzer.analyze("EURUSD")

    # Should be LOW since session just started
    assert result["fatigue_level"] == "LOW"
    assert result["psychology_ok"] is True


def test_consecutive_losses_tracking(analyzer):
    """Test consecutive loss tracking."""
    # Record 1 loss
    analyzer.record_loss()

    result = analyzer.analyze("EURUSD")
    assert result["consecutive_losses"] == 1
    assert result["losses_ok"] is True  # Still OK (limit is 2)
    assert result["psychology_ok"] is True


def test_consecutive_losses_limit_reached(analyzer):
    """Test psychology NOT OK when consecutive losses >= 2."""
    # Record 2 losses (at limit)
    analyzer.record_loss()
    analyzer.record_loss()

    result = analyzer.analyze("EURUSD")
    assert result["consecutive_losses"] == 2
    assert result["losses_ok"] is False  # At limit
    assert result["psychology_ok"] is False
    assert "consecutive losses" in result["recommendation"]


def test_consecutive_losses_reset_on_win(analyzer):
    """Test consecutive losses reset on win."""
    # Record 2 losses
    analyzer.record_loss()
    analyzer.record_loss()

    # Record a win
    analyzer.record_win()

    result = analyzer.analyze("EURUSD")
    assert result["consecutive_losses"] == 0
    assert result["losses_ok"] is True


def test_drawdown_tracking(analyzer):
    """Test drawdown tracking."""
    analyzer.update_drawdown(3.5)

    result = analyzer.analyze("EURUSD")
    assert result["drawdown_percent"] == 3.5
    assert result["drawdown_ok"] is True  # Below 5% limit


def test_drawdown_limit_exceeded(analyzer):
    """Test psychology NOT OK when drawdown >= 5%."""
    analyzer.update_drawdown(5.5)

    result = analyzer.analyze("EURUSD")
    assert result["drawdown_percent"] == 5.5
    assert result["drawdown_ok"] is False
    assert result["psychology_ok"] is False
    assert "drawdown" in result["recommendation"]


def test_high_volatility_unstable(analyzer):
    """Test psychology with high volatility profile."""
    volatility_profile = {"profile": "HIGH"}

    result = analyzer.analyze("EURUSD", volatility_profile=volatility_profile)
    assert result["stable"] is False
    assert result["psychology_ok"] is False
    assert "high volatility" in result["recommendation"]


def test_psychology_ok_recommendation(analyzer):
    """Test recommendation when psychology is OK."""
    result = analyzer.analyze("EURUSD")
    assert result["psychology_ok"] is True
    assert result["recommendation"] == "Psychology OK"


def test_psychology_not_ok_multiple_reasons(analyzer):
    """Test recommendation with multiple failure reasons."""
    # Set up multiple failure conditions
    analyzer.record_loss()
    analyzer.record_loss()
    analyzer.record_loss()
    analyzer.update_drawdown(5.5)

    volatility_profile = {"profile": "HIGH"}
    result = analyzer.analyze("EURUSD", volatility_profile=volatility_profile)

    assert result["psychology_ok"] is False
    recommendation = result["recommendation"]
    assert "Psychology NOT OK" in recommendation
    # Should contain multiple reasons
    assert "high volatility" in recommendation or "drawdown" in recommendation


def test_session_reset(analyzer):
    """Test session reset functionality."""
    # Set up some state
    analyzer.record_loss()
    analyzer.record_loss()
    analyzer.update_drawdown(4.0)

    # Get initial session time (should be > 0 if any time has passed)
    result_before = analyzer.analyze("EURUSD")

    # Reset session
    analyzer.reset_session()

    # Verify state is cleared
    result = analyzer.analyze("EURUSD")
    assert result["consecutive_losses"] == 0
    assert result["drawdown_percent"] == 0.0
    # Session hours should be very close to 0 after reset (freshly started)
    assert result["session_hours"] < result_before.get("session_hours", 0.1) + 0.1


def test_runtime_state_integration(analyzer):
    """Test integration with RuntimeState for session hours."""
    # Session hours should come from RuntimeState
    result = analyzer.analyze("EURUSD")

    # RuntimeState.get_session_hours() should be called
    assert result["session_hours"] >= 0.0
    assert "session_hours" in result
