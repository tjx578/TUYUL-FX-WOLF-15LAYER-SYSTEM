"""Unit tests for engines/v11/validation/edge_validator.py.

Tests cover:
- Binomial test computation
- Wilson score confidence interval
- Profit factor calculation
- Insufficient data handling
- Edge determination via validate_edge()
"""

import dataclasses

from engines.v11.validation.edge_validator import (
    EdgeStatus,
    EdgeValidator,
)

SETUP = "breakout_pullback"


def _feed_results(
    validator: EdgeValidator,
    n_wins: int,
    n_losses: int,
    win_pnl: float = 2.0,
    loss_pnl: float = -1.0,
    setup_type: str = SETUP,
) -> None:
    """Helper: record n_wins wins and n_losses losses."""
    for _ in range(n_wins):
        validator.record_result(setup_type, win_pnl)
    for _ in range(n_losses):
        validator.record_result(setup_type, loss_pnl)


class TestEdgeValidator:
    """Tests for edge validator."""

    def test_no_trades_insufficient_data(self) -> None:
        """Test zero trades returns INSUFFICIENT_DATA status."""
        validator = EdgeValidator()

        result = validator.validate_edge(SETUP)

        assert result.status == EdgeStatus.INSUFFICIENT_DATA
        assert result.metrics.sample_size == 0
        assert result.metrics.p_value == 1.0

    def test_high_win_rate_has_edge(self) -> None:
        """Test high win rate with sufficient trades yields VALID edge."""
        validator = EdgeValidator(
            min_win_rate=0.60,
            significance_level=0.05,
            min_sample_size=30,
        )

        # 80% win rate over 50 trades
        _feed_results(validator, n_wins=40, n_losses=10)

        result = validator.validate_edge(SETUP)

        assert result.metrics.win_rate == 0.80
        assert result.metrics.profit_factor > 1.0
        assert result.status == EdgeStatus.VALID

    def test_low_win_rate_no_edge(self) -> None:
        """Test low win rate results in non-VALID status."""
        validator = EdgeValidator(
            min_win_rate=0.75,
            significance_level=0.05,
            min_sample_size=30,
        )

        # Only 50% win rate
        _feed_results(validator, n_wins=25, n_losses=25)

        result = validator.validate_edge(SETUP)

        assert result.metrics.win_rate == 0.50
        assert result.status != EdgeStatus.VALID

    def test_insufficient_trades_no_edge(self) -> None:
        """Test insufficient sample size returns INSUFFICIENT_DATA."""
        validator = EdgeValidator(
            min_win_rate=0.60,
            significance_level=0.05,
            min_sample_size=30,
        )

        # Good win rate but only 10 trades (below min_sample_size=30)
        _feed_results(validator, n_wins=8, n_losses=2)

        result = validator.validate_edge(SETUP)

        assert result.status == EdgeStatus.INSUFFICIENT_DATA
        assert result.metrics.sample_size == 10

    def test_profit_factor_calculation(self) -> None:
        """Test profit factor = gross_profit / gross_loss."""
        validator = EdgeValidator(min_sample_size=30)

        # 30 wins @ +2.0 = 60.0, 20 losses @ -1.0 = 20.0 → PF = 3.0
        _feed_results(validator, n_wins=30, n_losses=20, win_pnl=2.0, loss_pnl=-1.0)

        result = validator.validate_edge(SETUP)
        assert result.metrics.win_rate == 0.60
        assert abs(result.metrics.profit_factor - 3.0) < 0.01

    def test_negative_profit_factor_no_edge(self) -> None:
        """Test losing strategy does not produce a VALID edge."""
        validator = EdgeValidator(min_sample_size=30)

        # 20 wins @ +1.0 = 20.0, 30 losses @ -1.0 = 30.0 → PF = 0.67
        _feed_results(validator, n_wins=20, n_losses=30, win_pnl=1.0, loss_pnl=-1.0)

        result = validator.validate_edge(SETUP)
        assert result.metrics.profit_factor < 1.0
        assert result.status != EdgeStatus.VALID

    def test_wilson_score_interval(self) -> None:
        """Test Wilson score confidence interval bounds are valid."""
        validator = EdgeValidator(min_sample_size=30)

        _feed_results(validator, n_wins=30, n_losses=20)

        result = validator.validate_edge(SETUP)
        ci_lower, ci_upper = result.metrics.confidence_interval

        assert 0.0 <= ci_lower <= 1.0
        assert 0.0 <= ci_upper <= 1.0
        assert ci_lower <= result.metrics.win_rate <= ci_upper

    def test_binomial_test_p_value(self) -> None:
        """Test binomial test produces a valid p-value in [0, 1]."""
        validator = EdgeValidator(min_sample_size=30)

        _feed_results(validator, n_wins=30, n_losses=20)

        result = validator.validate_edge(SETUP)

        assert 0.0 <= result.metrics.p_value <= 1.0

    def test_degradation_warnings_populated(self) -> None:
        """Test that failing thresholds produce degradation warnings."""
        validator = EdgeValidator(
            min_win_rate=0.90,
            min_profit_factor=5.0,
            significance_level=0.05,
            min_sample_size=30,
        )

        # Modest stats: 60% WR, PF≈3 — below the high thresholds
        _feed_results(validator, n_wins=30, n_losses=20)

        result = validator.validate_edge(SETUP)

        assert result.status == EdgeStatus.DEGRADED
        assert len(result.degradation_warnings) > 0

    def test_details_dict_contains_metrics(self) -> None:
        """Test details dict contains metric fields."""
        validator = EdgeValidator(min_sample_size=30)

        _feed_results(validator, n_wins=30, n_losses=20)

        result = validator.validate_edge(SETUP)

        assert isinstance(result.details, dict)
        assert "win_rate" in result.details
        assert "p_value" in result.details
        assert "confidence_interval" in result.details
        assert "profit_factor" in result.details

    def test_result_is_dataclass(self) -> None:
        """Test EdgeValidationResult is a proper dataclass."""
        validator = EdgeValidator(min_sample_size=30)

        _feed_results(validator, n_wins=30, n_losses=20)

        result = validator.validate_edge(SETUP)

        assert dataclasses.is_dataclass(result)
        d = dataclasses.asdict(result)
        assert isinstance(d, dict)
        assert "status" in d
        assert "metrics" in d
        assert "score" in d
