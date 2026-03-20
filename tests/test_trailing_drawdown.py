"""Tests for risk/trailing_drawdown.py — Phase-aware trailing drawdown."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from risk.trailing_drawdown import (
    DrawdownMode,
    PropPhase,
    TrailingDrawdownMonitor,
    get_drawdown_mode,
)


@pytest.fixture()
def mock_redis():
    """Mock Redis client to avoid real connections."""
    with patch("risk.trailing_drawdown.RedisClient") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.get.return_value = None
        mock_instance.set.return_value = True
        mock_cls.return_value = mock_instance
        yield mock_instance


class TestDrawdownModeResolution:
    """Test phase-aware mode resolution for different firms."""

    def test_ftmo_all_fixed(self):
        assert get_drawdown_mode("FTMO", PropPhase.CHALLENGE) == DrawdownMode.FIXED
        assert get_drawdown_mode("FTMO", PropPhase.VERIFICATION) == DrawdownMode.FIXED
        assert get_drawdown_mode("FTMO", PropPhase.FUNDED) == DrawdownMode.FIXED

    def test_funded_next_trailing_then_fixed(self):
        assert get_drawdown_mode("FundedNext", PropPhase.CHALLENGE) == DrawdownMode.TRAILING
        assert get_drawdown_mode("FundedNext", PropPhase.VERIFICATION) == DrawdownMode.TRAILING
        assert get_drawdown_mode("FundedNext", PropPhase.FUNDED) == DrawdownMode.FIXED

    def test_topstep_semi_trailing(self):
        assert get_drawdown_mode("TopStep", PropPhase.CHALLENGE) == DrawdownMode.SEMI_TRAILING
        assert get_drawdown_mode("TopStep", PropPhase.FUNDED) == DrawdownMode.SEMI_TRAILING

    def test_unknown_firm_defaults_to_fixed(self):
        assert get_drawdown_mode("UnknownFirm", PropPhase.CHALLENGE) == DrawdownMode.FIXED
        assert get_drawdown_mode("UnknownFirm", PropPhase.FUNDED) == DrawdownMode.FIXED


class TestFixedDrawdown:
    """FIXED mode: floor never moves, measured from initial balance."""

    def test_floor_stays_at_initial(self, mock_redis):
        mon = TrailingDrawdownMonitor(
            account_id="test-1",
            firm_name="FTMO",
            phase=PropPhase.CHALLENGE,
            initial_balance=100_000.0,
            max_drawdown_pct=0.10,
        )

        # Equity rises → floor should NOT move
        snap = mon.update(105_000.0)
        assert snap.trailing_floor == 90_000.0  # 100k - 10k
        assert snap.highest_equity == 105_000.0
        assert not snap.is_breached

    def test_breach_when_below_floor(self, mock_redis):
        mon = TrailingDrawdownMonitor(
            account_id="test-2",
            firm_name="FTMO",
            phase=PropPhase.CHALLENGE,
            initial_balance=100_000.0,
            max_drawdown_pct=0.10,
        )

        snap = mon.update(89_000.0)
        assert snap.is_breached
        assert snap.remaining_before_breach == 0.0

    def test_not_breached_just_above_floor(self, mock_redis):
        mon = TrailingDrawdownMonitor(
            account_id="test-3",
            firm_name="FTMO",
            phase=PropPhase.CHALLENGE,
            initial_balance=100_000.0,
            max_drawdown_pct=0.10,
        )

        snap = mon.update(90_001.0)
        assert not snap.is_breached
        assert snap.remaining_before_breach == pytest.approx(1.0, abs=1)


class TestTrailingDrawdown:
    """TRAILING mode: floor moves up with equity, never down."""

    def test_floor_moves_up_with_equity(self, mock_redis):
        mon = TrailingDrawdownMonitor(
            account_id="test-4",
            firm_name="FundedNext",
            phase=PropPhase.CHALLENGE,
            initial_balance=100_000.0,
            max_drawdown_pct=0.10,
        )

        # Initial floor = 100k - 10k = 90k
        snap = mon.update(100_000.0)
        assert snap.trailing_floor == 90_000.0

        # Equity rises to 105k → floor should move to 95k
        snap = mon.update(105_000.0)
        assert snap.trailing_floor == 95_000.0

        # Equity rises to 110k → floor should move to 100k
        snap = mon.update(110_000.0)
        assert snap.trailing_floor == 100_000.0

    def test_floor_never_moves_down(self, mock_redis):
        mon = TrailingDrawdownMonitor(
            account_id="test-5",
            firm_name="FundedNext",
            phase=PropPhase.CHALLENGE,
            initial_balance=100_000.0,
            max_drawdown_pct=0.10,
        )

        # Move equity up to 110k, floor = 100k
        mon.update(110_000.0)

        # Equity drops to 105k → floor stays at 100k
        snap = mon.update(105_000.0)
        assert snap.trailing_floor == 100_000.0
        assert snap.highest_equity == 110_000.0

        # Equity drops to 100.5k → still above floor
        snap = mon.update(100_500.0)
        assert snap.trailing_floor == 100_000.0
        assert not snap.is_breached

    def test_trailing_breach(self, mock_redis):
        mon = TrailingDrawdownMonitor(
            account_id="test-6",
            firm_name="FundedNext",
            phase=PropPhase.CHALLENGE,
            initial_balance=100_000.0,
            max_drawdown_pct=0.10,
        )

        mon.update(110_000.0)  # Floor = 100k
        snap = mon.update(99_000.0)  # Below 100k floor
        assert snap.is_breached


class TestSemiTrailingDrawdown:
    """SEMI_TRAILING mode: trails until floor reaches initial balance, then locks."""

    def test_trails_until_floor_reaches_initial(self, mock_redis):
        mon = TrailingDrawdownMonitor(
            account_id="test-7",
            firm_name="TopStep",
            phase=PropPhase.CHALLENGE,
            initial_balance=100_000.0,
            max_drawdown_pct=0.10,
        )

        # Initial floor = 90k
        snap = mon.update(100_000.0)
        assert snap.trailing_floor == 90_000.0
        assert not snap.locked_floor

        # Equity to 108k → floor = 98k, not locked yet
        snap = mon.update(108_000.0)
        assert snap.trailing_floor == 98_000.0
        assert not snap.locked_floor

        # Equity to 110k → floor would be 100k = initial_balance → LOCK
        snap = mon.update(110_000.0)
        assert snap.trailing_floor == 100_000.0
        assert snap.locked_floor

        # Equity to 120k → floor stays at 100k (locked)
        snap = mon.update(120_000.0)
        assert snap.trailing_floor == 100_000.0
        assert snap.locked_floor


class TestDailyLossTracking:
    """Daily loss tracking within trailing drawdown."""

    def test_daily_loss_accumulates(self, mock_redis):
        mon = TrailingDrawdownMonitor(
            account_id="test-8",
            firm_name="FTMO",
            phase=PropPhase.CHALLENGE,
            initial_balance=100_000.0,
            max_daily_loss_pct=0.05,
        )

        mon.update(99_500.0, pnl=-500.0)
        snap = mon.get_daily_loss_snapshot()
        assert snap["daily_loss_amount"] == 500.0

        mon.update(99_000.0, pnl=-500.0)
        snap = mon.get_daily_loss_snapshot()
        assert snap["daily_loss_amount"] == 1000.0

    def test_daily_breach_detection(self, mock_redis):
        mon = TrailingDrawdownMonitor(
            account_id="test-9",
            firm_name="FTMO",
            phase=PropPhase.CHALLENGE,
            initial_balance=100_000.0,
            max_daily_loss_pct=0.05,
        )

        # 5% of 100k = 5000
        mon.update(95_000.0, pnl=-5000.0)
        assert mon.is_daily_breached()

    def test_positive_pnl_not_accumulated(self, mock_redis):
        mon = TrailingDrawdownMonitor(
            account_id="test-10",
            firm_name="FTMO",
            phase=PropPhase.CHALLENGE,
            initial_balance=100_000.0,
        )

        mon.update(101_000.0, pnl=1000.0)
        snap = mon.get_daily_loss_snapshot()
        assert snap["daily_loss_amount"] == 0.0


class TestPhaseTransition:
    """Phase transitions (Challenge → Verification → Funded)."""

    def test_transition_resets_state(self, mock_redis):
        mon = TrailingDrawdownMonitor(
            account_id="test-11",
            firm_name="FundedNext",
            phase=PropPhase.CHALLENGE,
            initial_balance=100_000.0,
        )

        # Make some trades in challenge
        mon.update(105_000.0)

        # Transition to verification with new balance
        mon.transition_phase(PropPhase.VERIFICATION, new_balance=100_000.0)
        snap = mon.get_snapshot()
        assert snap.phase == "VERIFICATION"
        assert snap.initial_balance == 100_000.0
        assert snap.highest_equity == 100_000.0

    def test_transition_to_funded_changes_mode(self, mock_redis):
        mon = TrailingDrawdownMonitor(
            account_id="test-12",
            firm_name="FundedNext",
            phase=PropPhase.CHALLENGE,
            initial_balance=100_000.0,
        )

        # Challenge uses TRAILING
        assert mon._mode == DrawdownMode.TRAILING

        # Funded uses FIXED
        mon.transition_phase(PropPhase.FUNDED, new_balance=100_000.0)
        assert mon._mode == DrawdownMode.FIXED


class TestSnapshotSerialization:
    """Snapshot to_dict and immutability."""

    def test_snapshot_immutable(self, mock_redis):
        mon = TrailingDrawdownMonitor(
            account_id="test-13",
            firm_name="FTMO",
            phase=PropPhase.CHALLENGE,
            initial_balance=100_000.0,
        )
        snap = mon.get_snapshot()
        with pytest.raises(AttributeError):
            snap.is_breached = True  # type: ignore[misc]

    def test_to_dict_has_all_keys(self, mock_redis):
        mon = TrailingDrawdownMonitor(
            account_id="test-14",
            firm_name="FTMO",
            phase=PropPhase.CHALLENGE,
            initial_balance=100_000.0,
        )
        d = mon.get_snapshot().to_dict()
        expected = {
            "phase",
            "mode",
            "initial_balance",
            "highest_equity",
            "trailing_floor",
            "current_equity",
            "drawdown_from_floor",
            "drawdown_pct",
            "remaining_before_breach",
            "max_drawdown_amount",
            "is_breached",
            "locked_floor",
        }
        assert expected <= set(d.keys())
