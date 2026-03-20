"""
Tests for Trade Domain Models

Tests cover:
  - Trade, TradeLeg, Account model validation
  - Enum validation (TradeStatus, RiskMode, CloseReason)
  - State transition validation
  - Edge cases and invalid inputs
"""

import pytest

from schemas.trade_models import (
    Account,
    CloseReason,
    RiskMode,
    Trade,
    TradeLeg,
    TradeStatus,
    is_valid_transition,
)
from utils.timezone_utils import now_utc

# ========================
# TRADE LEG TESTS
# ========================


def test_trade_leg_valid():
    """Test TradeLeg with valid data."""
    leg = TradeLeg(
        leg=1,
        entry=1.08500,
        sl=1.08000,
        tp=1.09500,
        lot=0.01,
        status=TradeStatus.INTENDED,
    )
    assert leg.leg == 1
    assert leg.entry == 1.08500
    assert leg.lot == 0.01
    assert leg.status == TradeStatus.INTENDED


def test_trade_leg_invalid_entry():
    """Test TradeLeg with invalid entry price."""
    with pytest.raises(ValueError):
        TradeLeg(
            leg=1,
            entry=0.0,  # Invalid: must be > 0
            sl=1.08000,
            tp=1.09500,
            lot=0.01,
            status=TradeStatus.INTENDED,
        )


def test_trade_leg_invalid_lot():
    """Test TradeLeg with invalid lot size."""
    with pytest.raises(ValueError):
        TradeLeg(
            leg=1,
            entry=1.08500,
            sl=1.08000,
            tp=1.09500,
            lot=0.0,  # Invalid: must be > 0
            status=TradeStatus.INTENDED,
        )


# ========================
# TRADE TESTS
# ========================


def test_trade_valid():
    """Test Trade with valid data."""
    now = now_utc()

    trade = Trade(
        trade_id="T-1234567890",
        signal_id="SIG-EURUSD_1234567890",
        account_id="ACC-001",
        pair="EURUSD",
        direction="BUY",
        status=TradeStatus.INTENDED,
        risk_mode=RiskMode.FIXED,
        total_risk_percent=2.0,
        total_risk_amount=2000.0,
        legs=[
            TradeLeg(
                leg=1,
                entry=1.08500,
                sl=1.08000,
                tp=1.09500,
                lot=0.01,
                status=TradeStatus.INTENDED,
            )
        ],
        created_at=now,
        updated_at=now,
    )

    assert trade.trade_id == "T-1234567890"
    assert trade.direction == "BUY"
    assert trade.status == TradeStatus.INTENDED
    assert len(trade.legs) == 1
    assert trade.close_reason is None
    assert trade.pnl is None


def test_trade_direction_normalization():
    """Test that direction is normalized to uppercase."""
    now = now_utc()

    trade = Trade(
        trade_id="T-1234567890",
        signal_id="SIG-EURUSD_1234567890",
        account_id="ACC-001",
        pair="EURUSD",
        direction="buy",  # lowercase
        status=TradeStatus.INTENDED,
        risk_mode=RiskMode.FIXED,
        total_risk_percent=2.0,
        total_risk_amount=2000.0,
        legs=[
            TradeLeg(
                leg=1,
                entry=1.08500,
                sl=1.08000,
                tp=1.09500,
                lot=0.01,
                status=TradeStatus.INTENDED,
            )
        ],
        created_at=now,
        updated_at=now,
    )

    assert trade.direction == "BUY"


def test_trade_invalid_direction():
    """Test Trade with invalid direction."""
    now = now_utc()

    with pytest.raises(ValueError, match="Direction must be BUY or SELL"):
        Trade(
            trade_id="T-1234567890",
            signal_id="SIG-EURUSD_1234567890",
            account_id="ACC-001",
            pair="EURUSD",
            direction="INVALID",  # Invalid direction
            status=TradeStatus.INTENDED,
            risk_mode=RiskMode.FIXED,
            total_risk_percent=2.0,
            total_risk_amount=2000.0,
            legs=[
                TradeLeg(
                    leg=1,
                    entry=1.08500,
                    sl=1.08000,
                    tp=1.09500,
                    lot=0.01,
                    status=TradeStatus.INTENDED,
                )
            ],
            created_at=now,
            updated_at=now,
        )


def test_trade_no_legs():
    """Test Trade with no legs (invalid)."""
    now = now_utc()

    with pytest.raises(ValueError, match="Trade must have at least one leg"):
        Trade(
            trade_id="T-1234567890",
            signal_id="SIG-EURUSD_1234567890",
            account_id="ACC-001",
            pair="EURUSD",
            direction="BUY",
            status=TradeStatus.INTENDED,
            risk_mode=RiskMode.FIXED,
            total_risk_percent=2.0,
            total_risk_amount=2000.0,
            legs=[],  # Empty legs
            created_at=now,
            updated_at=now,
        )


def test_trade_closed_with_pnl():
    """Test closed Trade with P&L."""
    now = now_utc()

    trade = Trade(
        trade_id="T-1234567890",
        signal_id="SIG-EURUSD_1234567890",
        account_id="ACC-001",
        pair="EURUSD",
        direction="BUY",
        status=TradeStatus.CLOSED,
        risk_mode=RiskMode.FIXED,
        total_risk_percent=2.0,
        total_risk_amount=2000.0,
        legs=[
            TradeLeg(
                leg=1,
                entry=1.08500,
                sl=1.08000,
                tp=1.09500,
                lot=0.01,
                status=TradeStatus.CLOSED,
            )
        ],
        created_at=now,
        updated_at=now,
        close_reason=CloseReason.TP_HIT,
        pnl=500.0,
    )

    assert trade.status == TradeStatus.CLOSED
    assert trade.close_reason == CloseReason.TP_HIT
    assert trade.pnl == 500.0


# ========================
# ACCOUNT TESTS
# ========================


def test_account_valid():
    """Test Account with valid data."""
    account = Account(
        account_id="ACC-001",
        name="Demo Account",
        balance=100000.0,
        equity=102000.0,
        prop_firm=False,
        max_daily_dd_percent=4.0,
        max_total_dd_percent=8.0,
        max_concurrent_trades=3,
    )

    assert account.account_id == "ACC-001"
    assert account.balance == 100000.0
    assert account.equity == 102000.0
    assert account.prop_firm is False


def test_account_invalid_equity():
    """Test Account with invalid equity."""
    with pytest.raises(ValueError):
        Account(
            account_id="ACC-001",
            name="Demo Account",
            balance=100000.0,
            equity=0.0,  # Invalid: must be > 0
            prop_firm=False,
            max_daily_dd_percent=4.0,
            max_total_dd_percent=8.0,
            max_concurrent_trades=3,
        )


# ========================
# STATE TRANSITION TESTS
# ========================


def test_valid_transitions():
    """Test valid state transitions."""
    # INTENDED -> PENDING
    assert is_valid_transition(TradeStatus.INTENDED, TradeStatus.PENDING) is True

    # INTENDED -> CANCELLED
    assert is_valid_transition(TradeStatus.INTENDED, TradeStatus.CANCELLED) is True

    # INTENDED -> SKIPPED
    assert is_valid_transition(TradeStatus.INTENDED, TradeStatus.SKIPPED) is True

    # PENDING -> OPEN
    assert is_valid_transition(TradeStatus.PENDING, TradeStatus.OPEN) is True

    # PENDING -> CANCELLED
    assert is_valid_transition(TradeStatus.PENDING, TradeStatus.CANCELLED) is True

    # OPEN -> CLOSED
    assert is_valid_transition(TradeStatus.OPEN, TradeStatus.CLOSED) is True


def test_invalid_transitions():
    """Test invalid state transitions."""
    # INTENDED -> OPEN (must go through PENDING)
    assert is_valid_transition(TradeStatus.INTENDED, TradeStatus.OPEN) is False

    # CLOSED -> OPEN (terminal state)
    assert is_valid_transition(TradeStatus.CLOSED, TradeStatus.OPEN) is False

    # CANCELLED -> PENDING (terminal state)
    assert is_valid_transition(TradeStatus.CANCELLED, TradeStatus.PENDING) is False

    # SKIPPED -> PENDING (terminal state)
    assert is_valid_transition(TradeStatus.SKIPPED, TradeStatus.PENDING) is False

    # OPEN -> PENDING (can't go back)
    assert is_valid_transition(TradeStatus.OPEN, TradeStatus.PENDING) is False


# ========================
# ENUM TESTS
# ========================


def test_trade_status_enum():
    """Test TradeStatus enum values."""
    assert TradeStatus.INTENDED.value == "INTENDED"
    assert TradeStatus.PENDING.value == "PENDING"
    assert TradeStatus.OPEN.value == "OPEN"
    assert TradeStatus.CLOSED.value == "CLOSED"
    assert TradeStatus.CANCELLED.value == "CANCELLED"
    assert TradeStatus.SKIPPED.value == "SKIPPED"


def test_risk_mode_enum():
    """Test RiskMode enum values."""
    assert RiskMode.FIXED.value == "FIXED"
    assert RiskMode.SPLIT.value == "SPLIT"


def test_close_reason_enum():
    """Test CloseReason enum values."""
    assert CloseReason.TP_HIT.value == "TP_HIT"
    assert CloseReason.SL_HIT.value == "SL_HIT"
    assert CloseReason.MANUAL_CLOSE.value == "MANUAL_CLOSE"
    assert CloseReason.SYSTEM_PROTECTION.value == "SYSTEM_PROTECTION"
    assert CloseReason.EXPIRY.value == "EXPIRY"
    assert CloseReason.NEWS_LOCK.value == "NEWS_LOCK"
    assert CloseReason.M15_INVALIDATION.value == "M15_INVALIDATION"
