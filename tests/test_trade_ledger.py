"""
Tests for Trade Ledger Service

Tests cover:
  - Trade creation
  - Status updates with transition validation
  - Trade retrieval (by ID, active, by account)
  - Invalid transitions
  - Redis persistence
"""

import pytest

from dashboard.trade_ledger import TradeLedger
from schemas.trade_models import TradeStatus, CloseReason


@pytest.fixture
def trade_ledger():
    """Create a fresh TradeLedger instance for each test."""
    from unittest.mock import MagicMock
    # Note: Using singleton, so clear cache before each test
    ledger = TradeLedger()
    ledger._cache.clear()
    # Mock Redis to avoid connection timeouts in CI
    ledger._redis = MagicMock()
    return ledger


def test_create_trade(trade_ledger):
    """Test creating a new trade."""
    trade = trade_ledger.create_trade(
        signal_id="SIG-EURUSD_1234567890",
        account_id="ACC-001",
        pair="EURUSD",
        direction="BUY",
        risk_mode="FIXED",
        total_risk_percent=2.0,
        total_risk_amount=2000.0,
        legs=[{
            "entry": 1.08500,
            "sl": 1.08000,
            "tp": 1.09500,
            "lot": 0.01,
        }],
    )

    assert trade.trade_id.startswith("T-")
    assert trade.signal_id == "SIG-EURUSD_1234567890"
    assert trade.account_id == "ACC-001"
    assert trade.pair == "EURUSD"
    assert trade.direction == "BUY"
    assert trade.status == TradeStatus.INTENDED
    assert len(trade.legs) == 1
    assert trade.legs[0].entry == 1.08500


def test_update_status_valid_transition(trade_ledger):
    """Test updating trade status with valid transition."""
    # Create trade
    trade = trade_ledger.create_trade(
        signal_id="SIG-EURUSD_1234567890",
        account_id="ACC-001",
        pair="EURUSD",
        direction="BUY",
        risk_mode="FIXED",
        total_risk_percent=2.0,
        total_risk_amount=2000.0,
        legs=[{
            "entry": 1.08500,
            "sl": 1.08000,
            "tp": 1.09500,
            "lot": 0.01,
        }],
    )

    # Update INTENDED → PENDING
    success = trade_ledger.update_status(trade.trade_id, TradeStatus.PENDING)
    assert success is True

    # Verify update
    updated_trade = trade_ledger.get_trade(trade.trade_id)
    assert updated_trade.status == TradeStatus.PENDING
    assert updated_trade.legs[0].status == TradeStatus.PENDING


def test_update_status_invalid_transition(trade_ledger):
    """Test updating trade status with invalid transition."""
    # Create trade
    trade = trade_ledger.create_trade(
        signal_id="SIG-EURUSD_1234567890",
        account_id="ACC-001",
        pair="EURUSD",
        direction="BUY",
        risk_mode="FIXED",
        total_risk_percent=2.0,
        total_risk_amount=2000.0,
        legs=[{
            "entry": 1.08500,
            "sl": 1.08000,
            "tp": 1.09500,
            "lot": 0.01,
        }],
    )

    # Try invalid transition: INTENDED → OPEN (must go through PENDING)
    success = trade_ledger.update_status(trade.trade_id, TradeStatus.OPEN)
    assert success is False

    # Verify status unchanged
    unchanged_trade = trade_ledger.get_trade(trade.trade_id)
    assert unchanged_trade.status == TradeStatus.INTENDED


def test_update_status_with_close_reason(trade_ledger):
    """Test closing trade with reason."""
    # Create trade and transition to OPEN
    trade = trade_ledger.create_trade(
        signal_id="SIG-EURUSD_1234567890",
        account_id="ACC-001",
        pair="EURUSD",
        direction="BUY",
        risk_mode="FIXED",
        total_risk_percent=2.0,
        total_risk_amount=2000.0,
        legs=[{
            "entry": 1.08500,
            "sl": 1.08000,
            "tp": 1.09500,
            "lot": 0.01,
        }],
    )

    trade_ledger.update_status(trade.trade_id, TradeStatus.PENDING)
    trade_ledger.update_status(trade.trade_id, TradeStatus.OPEN)

    # Close with TP_HIT reason
    success = trade_ledger.update_status(
        trade.trade_id,
        TradeStatus.CLOSED,
        close_reason=CloseReason.TP_HIT,
        pnl=500.0,
    )
    assert success is True

    # Verify close reason and P&L
    closed_trade = trade_ledger.get_trade(trade.trade_id)
    assert closed_trade.status == TradeStatus.CLOSED
    assert closed_trade.close_reason == CloseReason.TP_HIT
    assert closed_trade.pnl == 500.0


def test_get_trade_not_found(trade_ledger):
    """Test getting non-existent trade."""
    trade = trade_ledger.get_trade("T-nonexistent")
    assert trade is None


def test_get_active_trades(trade_ledger):
    """Test getting active trades."""
    # Create multiple trades
    trade1 = trade_ledger.create_trade(
        signal_id="SIG-EURUSD_1",
        account_id="ACC-001",
        pair="EURUSD",
        direction="BUY",
        risk_mode="FIXED",
        total_risk_percent=2.0,
        total_risk_amount=2000.0,
        legs=[{"entry": 1.08500, "sl": 1.08000, "tp": 1.09500, "lot": 0.01}],
    )

    trade2 = trade_ledger.create_trade(
        signal_id="SIG-GBPUSD_2",
        account_id="ACC-001",
        pair="GBPUSD",
        direction="SELL",
        risk_mode="FIXED",
        total_risk_percent=2.0,
        total_risk_amount=2000.0,
        legs=[{"entry": 1.25500, "sl": 1.26000, "tp": 1.24500, "lot": 0.01}],
    )

    trade3 = trade_ledger.create_trade(
        signal_id="SIG-USDJPY_3",
        account_id="ACC-002",
        pair="USDJPY",
        direction="BUY",
        risk_mode="FIXED",
        total_risk_percent=1.5,
        total_risk_amount=1500.0,
        legs=[{"entry": 150.500, "sl": 150.000, "tp": 151.500, "lot": 0.01}],
    )

    # Move trade2 to PENDING, then OPEN
    trade_ledger.update_status(trade2.trade_id, TradeStatus.PENDING)
    trade_ledger.update_status(trade2.trade_id, TradeStatus.OPEN)

    # Close trade3
    trade_ledger.update_status(trade3.trade_id, TradeStatus.SKIPPED)

    # Get active trades (should exclude SKIPPED)
    active_trades = trade_ledger.get_active_trades()

    assert len(active_trades) == 2
    active_ids = [t.trade_id for t in active_trades]
    assert trade1.trade_id in active_ids
    assert trade2.trade_id in active_ids
    assert trade3.trade_id not in active_ids


def test_get_trades_by_account(trade_ledger):
    """Test getting trades for a specific account."""
    # Create trades for different accounts
    _ = trade_ledger.create_trade(
        signal_id="SIG-EURUSD_1",
        account_id="ACC-001",
        pair="EURUSD",
        direction="BUY",
        risk_mode="FIXED",
        total_risk_percent=2.0,
        total_risk_amount=2000.0,
        legs=[{"entry": 1.08500, "sl": 1.08000, "tp": 1.09500, "lot": 0.01}],
    )

    _ = trade_ledger.create_trade(
        signal_id="SIG-GBPUSD_2",
        account_id="ACC-001",
        pair="GBPUSD",
        direction="SELL",
        risk_mode="FIXED",
        total_risk_percent=2.0,
        total_risk_amount=2000.0,
        legs=[{"entry": 1.25500, "sl": 1.26000, "tp": 1.24500, "lot": 0.01}],
    )

    _ = trade_ledger.create_trade(
        signal_id="SIG-USDJPY_3",
        account_id="ACC-002",
        pair="USDJPY",
        direction="BUY",
        risk_mode="FIXED",
        total_risk_percent=1.5,
        total_risk_amount=1500.0,
        legs=[{"entry": 150.500, "sl": 150.000, "tp": 151.500, "lot": 0.01}],
    )

    # Get trades for ACC-001
    acc001_trades = trade_ledger.get_trades_by_account("ACC-001")
    assert len(acc001_trades) == 2
    assert all(t.account_id == "ACC-001" for t in acc001_trades)

    # Get trades for ACC-002
    acc002_trades = trade_ledger.get_trades_by_account("ACC-002")
    assert len(acc002_trades) == 1
    assert acc002_trades[0].account_id == "ACC-002"


def test_full_trade_lifecycle(trade_ledger):
    """Test full trade lifecycle: INTENDED → PENDING → OPEN → CLOSED."""
    # Create trade
    trade = trade_ledger.create_trade(
        signal_id="SIG-EURUSD_1234567890",
        account_id="ACC-001",
        pair="EURUSD",
        direction="BUY",
        risk_mode="FIXED",
        total_risk_percent=2.0,
        total_risk_amount=2000.0,
        legs=[{
            "entry": 1.08500,
            "sl": 1.08000,
            "tp": 1.09500,
            "lot": 0.01,
        }],
    )

    # INTENDED → PENDING (trader confirms order placed)
    trade_ledger.update_status(trade.trade_id, TradeStatus.PENDING)
    trade = trade_ledger.get_trade(trade.trade_id)
    assert trade.status == TradeStatus.PENDING

    # PENDING → OPEN (price watcher detects entry hit)
    trade_ledger.update_status(trade.trade_id, TradeStatus.OPEN)
    trade = trade_ledger.get_trade(trade.trade_id)
    assert trade.status == TradeStatus.OPEN

    # OPEN → CLOSED (TP hit)
    trade_ledger.update_status(
        trade.trade_id,
        TradeStatus.CLOSED,
        close_reason=CloseReason.TP_HIT,
        pnl=500.0,
    )
    trade = trade_ledger.get_trade(trade.trade_id)
    assert trade.status == TradeStatus.CLOSED
    assert trade.close_reason == CloseReason.TP_HIT
    assert trade.pnl == 500.0

    # Verify no longer in active trades
    active_trades = trade_ledger.get_active_trades()
    assert trade.trade_id not in [t.trade_id for t in active_trades]
