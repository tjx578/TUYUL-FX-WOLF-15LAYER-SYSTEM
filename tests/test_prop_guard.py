"""
Tests for prop firm guard — critical for live trading safety.
"""

import pytest  # pyright: ignore[reportMissingImports]

from risk.enhanced_prop_guard import (
    FTMO_PROFILE,
    AccountSnapshot,
    EnhancedPropGuard,
    GuardCode,
    PropFirmProfile,
)


@pytest.fixture
def ftmo_guard():
    return EnhancedPropGuard(FTMO_PROFILE)


@pytest.fixture
def healthy_account():
    return AccountSnapshot(
        balance=100_000.0,
        equity=99_500.0,
        floating_pnl=-500.0,
        closed_pnl_today=-200.0,
        open_position_count=2,
        day_start_balance=100_000.0,
        highest_balance=100_000.0,
    )


@pytest.fixture
def stressed_account():
    return AccountSnapshot(
        balance=100_000.0,
        equity=95_200.0,  # Already 4.8% daily loss
        floating_pnl=-4_800.0,
        closed_pnl_today=-3_000.0,
        open_position_count=5,
        day_start_balance=100_000.0,
        highest_balance=100_500.0,
    )


class TestDailyLossGuard:
    def test_allows_trade_within_limits(self, ftmo_guard, healthy_account):
        result = ftmo_guard.check(healthy_account, trade_risk_usd=500.0, lot_size=0.5)
        assert result.allowed is True
        assert result.code == GuardCode.ALLOWED

    def test_blocks_trade_exceeding_daily_limit(self, ftmo_guard, stressed_account):
        # Account already at 4.8% daily loss, trying to risk another $500
        result = ftmo_guard.check(stressed_account, trade_risk_usd=500.0, lot_size=0.5)
        assert result.allowed is False
        assert result.code == GuardCode.DAILY_LOSS_LIMIT

    def test_blocks_at_exact_threshold(self, ftmo_guard):
        account = AccountSnapshot(
            balance=100_000.0,
            equity=95_500.0,
            floating_pnl=-4_500.0,
            closed_pnl_today=-4_000.0,
            open_position_count=1,
            day_start_balance=100_000.0,
        )
        # At 4.5% daily loss + 250 risk = 4.75% -> 95% of 5% = 4.75%, should block
        result = ftmo_guard.check(account, trade_risk_usd=250.0, lot_size=0.2)
        assert result.allowed is False


class TestMaxDrawdownGuard:
    def test_blocks_near_max_drawdown(self):
        profile = PropFirmProfile(
            name="TestFirm",
            max_daily_loss_pct=5.0,
            max_total_drawdown_pct=10.0,
            max_lot_per_trade=10.0,
            max_open_positions=20,
            initial_balance=100_000.0,
        )
        guard = EnhancedPropGuard(profile)
        account = AccountSnapshot(
            balance=91_000.0,
            equity=90_500.0,
            floating_pnl=-500.0,
            closed_pnl_today=-200.0,
            open_position_count=1,
            day_start_balance=91_000.0,
            highest_balance=100_000.0,
        )
        # At 9.5% DD, adding 500 risk -> projected ~10% BLOCK
        result = guard.check(account, trade_risk_usd=500.0, lot_size=0.3)
        assert result.allowed is False
        assert result.code == GuardCode.MAX_DRAWDOWN


class TestLotSizeGuard:
    def test_blocks_oversized_lot(self, ftmo_guard, healthy_account):
        result = ftmo_guard.check(healthy_account, trade_risk_usd=100.0, lot_size=25.0)
        assert result.allowed is False
        assert result.code == GuardCode.LOT_SIZE_EXCEEDED

    def test_blocks_undersized_lot(self, ftmo_guard, healthy_account):
        result = ftmo_guard.check(healthy_account, trade_risk_usd=10.0, lot_size=0.001)
        assert result.allowed is False
        assert result.code == GuardCode.LOT_SIZE_EXCEEDED


class TestPositionCountGuard:
    def test_blocks_at_max_positions(self):
        profile = PropFirmProfile(
            name="TestFirm",
            max_daily_loss_pct=5.0,
            max_total_drawdown_pct=10.0,
            max_lot_per_trade=10.0,
            max_open_positions=3,
        )
        guard = EnhancedPropGuard(profile)
        account = AccountSnapshot(
            balance=100_000.0,
            equity=99_900.0,
            floating_pnl=-100.0,
            closed_pnl_today=0.0,
            open_position_count=3,  # At max
            day_start_balance=100_000.0,
        )
        result = guard.check(account, trade_risk_usd=100.0, lot_size=0.1)
        assert result.allowed is False
        assert result.code == GuardCode.MAX_POSITIONS


class TestMaxSafeLotComputation:
    def test_computes_safe_lot(self, ftmo_guard, healthy_account):
        max_lot = ftmo_guard.compute_max_safe_lot(
            account=healthy_account,
            sl_pips=30.0,
            pip_value_per_lot=10.0,
        )
        # Remaining daily budget: 5000 - 500 = 4500, safe: 4050
        # Max from daily: 4050 / (30 * 10) = 13.5
        # Cap by FTMO max: 20
        assert max_lot > 0
        assert max_lot <= FTMO_PROFILE.max_lot_per_trade

    def test_returns_min_lot_when_budget_exhausted(self, ftmo_guard, stressed_account):
        max_lot = ftmo_guard.compute_max_safe_lot(
            account=stressed_account,
            sl_pips=30.0,
            pip_value_per_lot=10.0,
        )
        assert max_lot == FTMO_PROFILE.min_lot


class TestConstitutionalBoundaries:
    """Ensure guard never makes market decisions — only risk decisions."""

    def test_guard_result_has_no_direction(self, ftmo_guard, healthy_account):
        result = ftmo_guard.check(healthy_account, trade_risk_usd=100.0, lot_size=0.1)
        # GuardResult must NOT contain buy/sell direction
        assert not hasattr(result, "direction")
        assert not hasattr(result, "symbol")
        assert not hasattr(result, "entry_price")
