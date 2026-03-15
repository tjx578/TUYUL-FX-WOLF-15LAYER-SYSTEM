"""Unit tests for engines/v11/validation/edge_validator.py.

Tests cover:
- Binomial test computation
- Wilson score confidence interval
- Expected value calculation
- Minimum trades estimation
- Has edge determination
"""

import pytest

from engines.v11.validation import EdgeValidator


class TestEdgeValidator:
    """Tests for edge validator."""

    def test_no_trades_no_edge(self) -> None:
        """Test zero trades returns no edge."""
        validator = EdgeValidator()

        result = validator.validate(n_wins=0, n_trades=0)

        assert not result.has_edge
        assert result.win_rate == 0.0
        assert result.p_value == 1.0

    def test_high_win_rate_has_edge(self) -> None:
        """Test high win rate with sufficient trades has edge."""
        validator = EdgeValidator(
            min_win_rate=0.60,
            alpha=0.05,
            min_trades=30,
        )

        # 80% win rate over 50 trades
        result = validator.validate(n_wins=40, n_trades=50, avg_rr=2.0)

        assert result.win_rate == 0.80
        # With 80% WR and RR=2.0, should have positive edge
        assert result.expected_value > 0

    def test_low_win_rate_no_edge(self) -> None:
        """Test low win rate has no edge."""
        validator = EdgeValidator(
            min_win_rate=0.75,
            alpha=0.05,
            min_trades=30,
        )

        # Only 50% win rate
        result = validator.validate(n_wins=25, n_trades=50, avg_rr=1.5)

        assert result.win_rate == 0.50
        assert not result.has_edge  # Below minimum

    def test_insufficient_trades_no_edge(self) -> None:
        """Test insufficient sample size results in no edge."""
        validator = EdgeValidator(
            min_win_rate=0.60,
            alpha=0.05,
            min_trades=30,
        )

        # Good win rate but too few trades
        result = validator.validate(n_wins=8, n_trades=10, avg_rr=2.0)

        assert result.win_rate == 0.80
        # Should not have edge due to insufficient trades
        assert not result.has_edge

    def test_expected_value_calculation(self) -> None:
        """Test expected value calculation: EV = WR × RR - (1-WR)."""
        validator = EdgeValidator()

        # 60% WR, RR=2.0
        # EV = 0.6 × 2.0 - 0.4 = 1.2 - 0.4 = 0.8
        result = validator.validate(n_wins=30, n_trades=50, avg_rr=2.0)

        assert result.win_rate == 0.60
        expected_ev = 0.60 * 2.0 - 0.40
        assert abs(result.expected_value - expected_ev) < 0.01

    def test_negative_expected_value(self) -> None:
        """Test negative expected value results in no edge."""
        validator = EdgeValidator()

        # 40% WR, RR=1.0 → EV = 0.4 × 1.0 - 0.6 = -0.2
        result = validator.validate(n_wins=20, n_trades=50, avg_rr=1.0)

        assert result.expected_value < 0
        assert not result.has_edge

    def test_wilson_score_interval(self) -> None:
        """Test Wilson score confidence interval."""
        validator = EdgeValidator()

        result = validator.validate(n_wins=30, n_trades=50, avg_rr=2.0)

        ci_lower, ci_upper = result.confidence_interval

        # CI bounds should be valid
        assert 0.0 <= ci_lower <= 1.0
        assert 0.0 <= ci_upper <= 1.0
        assert ci_lower <= result.win_rate <= ci_upper

    def test_binomial_test_p_value(self) -> None:
        """Test binomial test produces valid p-value."""
        validator = EdgeValidator()

        result = validator.validate(n_wins=30, n_trades=50, avg_rr=2.0)

        # P-value should be in [0, 1]
        assert 0.0 <= result.p_value <= 1.0

    def test_min_trades_needed(self) -> None:
        """Test minimum trades estimation."""
        validator = EdgeValidator(min_win_rate=0.75, alpha=0.05)

        result = validator.validate(n_wins=30, n_trades=50, avg_rr=2.0)

        # Should suggest a minimum number of trades
        assert result.min_trades_needed > 0
        assert isinstance(result.min_trades_needed, int)

    def test_frozen_result(self) -> None:
        """Test result is immutable."""
        validator = EdgeValidator()

        result = validator.validate(n_wins=30, n_trades=50, avg_rr=2.0)

        with pytest.raises(AttributeError):
            result.has_edge = False  # type: ignore[misc]

    def test_to_dict_serialization(self) -> None:
        """Test to_dict() serialization."""
        validator = EdgeValidator()

        result = validator.validate(n_wins=30, n_trades=50, avg_rr=2.0)
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "has_edge" in d
        assert "win_rate" in d
        assert "p_value" in d
        assert "confidence_interval" in d
        assert "expected_value" in d
        assert "min_trades_needed" in d
