"""
Tests for Price Watcher Service

Tests cover:
  - PENDING → OPEN detection (entry hit)
  - OPEN → CLOSED detection (SL/TP hit)
  - BUY vs SELL logic
  - No false triggers
  - Edge cases
"""

import pytest
from unittest.mock import patch

from dashboard.price_watcher import PriceWatcher
from schemas.trade_models import Trade, TradeLeg, TradeStatus, CloseReason
from utils.timezone_utils import now_utc


@pytest.fixture
def price_watcher():
    """Create a PriceWatcher instance for testing."""
    return PriceWatcher()


@pytest.fixture
def mock_trade_ledger():
    """Mock TradeLedger for isolated testing."""
    with patch('dashboard.price_watcher.TradeLedger') as mock:
        yield mock.return_value


@pytest.fixture
def mock_price_feed():
    """Mock PriceFeed for isolated testing."""
    with patch('dashboard.price_watcher.PriceFeed') as mock:
        yield mock.return_value


@pytest.fixture
def mock_journal():
    """Mock JournalRouter for isolated testing."""
    with patch('dashboard.price_watcher.JournalRouter') as mock:
        yield mock.return_value


def create_test_trade(
    trade_id: str,
    pair: str,
    direction: str,
    status: TradeStatus,
    entry: float,
    sl: float,
    tp: float,
) -> Trade:
    """Helper to create test trade."""
    now = now_utc()

    return Trade(
        trade_id=trade_id,
        signal_id=f"SIG-{pair}_123",
        account_id="ACC-001",
        pair=pair,
        direction=direction,
        status=status,
        risk_mode="FIXED",
        total_risk_percent=2.0,
        total_risk_amount=2000.0,
        legs=[
            TradeLeg(
                leg=1,
                entry=entry,
                sl=sl,
                tp=tp,
                lot=0.01,
                status=status,
            )
        ],
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_pending_to_open_buy_entry_hit(price_watcher, mock_trade_ledger, mock_price_feed):
    """Test BUY pending order opening when entry is hit."""
    # Create BUY pending trade with entry at 1.08500
    trade = create_test_trade(
        trade_id="T-001",
        pair="EURUSD",
        direction="BUY",
        status=TradeStatus.PENDING,
        entry=1.08500,
        sl=1.08000,
        tp=1.09500,
    )

    # Mock active trades
    mock_trade_ledger.get_active_trades.return_value = [trade]

    # Mock price: ask at 1.08500 (entry hit)
    mock_price_feed.get_price.return_value = {
        "bid": 1.08480,
        "ask": 1.08500,
        "ts": 1234567890.0,
        "source": "test",
    }

    # Check trades
    await price_watcher._check_trades()

    # Verify update_status was called to transition to OPEN
    mock_trade_ledger.update_status.assert_called_once_with("T-001", TradeStatus.OPEN)


@pytest.mark.asyncio
async def test_pending_to_open_sell_entry_hit(price_watcher, mock_trade_ledger, mock_price_feed):
    """Test SELL pending order opening when entry is hit."""
    # Create SELL pending trade with entry at 1.25500
    trade = create_test_trade(
        trade_id="T-002",
        pair="GBPUSD",
        direction="SELL",
        status=TradeStatus.PENDING,
        entry=1.25500,
        sl=1.26000,
        tp=1.24500,
    )

    # Mock active trades
    mock_trade_ledger.get_active_trades.return_value = [trade]

    # Mock price: bid at 1.25500 (entry hit)
    mock_price_feed.get_price.return_value = {
        "bid": 1.25500,
        "ask": 1.25520,
        "ts": 1234567890.0,
        "source": "test",
    }

    # Check trades
    await price_watcher._check_trades()

    # Verify update_status was called to transition to OPEN
    mock_trade_ledger.update_status.assert_called_once_with("T-002", TradeStatus.OPEN)


@pytest.mark.asyncio
async def test_pending_to_open_buy_entry_not_hit(price_watcher, mock_trade_ledger, mock_price_feed):
    """Test BUY pending order NOT opening when entry not hit."""
    # Create BUY pending trade with entry at 1.08500
    trade = create_test_trade(
        trade_id="T-003",
        pair="EURUSD",
        direction="BUY",
        status=TradeStatus.PENDING,
        entry=1.08500,
        sl=1.08000,
        tp=1.09500,
    )

    # Mock active trades
    mock_trade_ledger.get_active_trades.return_value = [trade]

    # Mock price: ask above entry (not hit yet)
    mock_price_feed.get_price.return_value = {
        "bid": 1.08520,
        "ask": 1.08540,
        "ts": 1234567890.0,
        "source": "test",
    }

    # Check trades
    await price_watcher._check_trades()

    # Verify update_status was NOT called
    mock_trade_ledger.update_status.assert_not_called()


@pytest.mark.asyncio
async def test_open_to_closed_buy_tp_hit(price_watcher, mock_trade_ledger, mock_price_feed):
    """Test BUY position closing when TP is hit."""
    # Create BUY open trade
    trade = create_test_trade(
        trade_id="T-004",
        pair="EURUSD",
        direction="BUY",
        status=TradeStatus.OPEN,
        entry=1.08500,
        sl=1.08000,
        tp=1.09500,
    )

    # Mock active trades
    mock_trade_ledger.get_active_trades.return_value = [trade]

    # Mock price: bid at TP (TP hit)
    mock_price_feed.get_price.return_value = {
        "bid": 1.09500,
        "ask": 1.09520,
        "ts": 1234567890.0,
        "source": "test",
    }

    # Check trades
    await price_watcher._check_trades()

    # Verify update_status was called to close with TP_HIT
    mock_trade_ledger.update_status.assert_called_once_with(
        "T-004",
        TradeStatus.CLOSED,
        close_reason=CloseReason.TP_HIT,
        pnl=None,
    )


@pytest.mark.asyncio
async def test_open_to_closed_buy_sl_hit(price_watcher, mock_trade_ledger, mock_price_feed):
    """Test BUY position closing when SL is hit."""
    # Create BUY open trade
    trade = create_test_trade(
        trade_id="T-005",
        pair="EURUSD",
        direction="BUY",
        status=TradeStatus.OPEN,
        entry=1.08500,
        sl=1.08000,
        tp=1.09500,
    )

    # Mock active trades
    mock_trade_ledger.get_active_trades.return_value = [trade]

    # Mock price: bid at SL (SL hit)
    mock_price_feed.get_price.return_value = {
        "bid": 1.08000,
        "ask": 1.08020,
        "ts": 1234567890.0,
        "source": "test",
    }

    # Check trades
    await price_watcher._check_trades()

    # Verify update_status was called to close with SL_HIT
    mock_trade_ledger.update_status.assert_called_once_with(
        "T-005",
        TradeStatus.CLOSED,
        close_reason=CloseReason.SL_HIT,
        pnl=None,
    )


@pytest.mark.asyncio
async def test_open_to_closed_sell_tp_hit(price_watcher, mock_trade_ledger, mock_price_feed):
    """Test SELL position closing when TP is hit."""
    # Create SELL open trade
    trade = create_test_trade(
        trade_id="T-006",
        pair="GBPUSD",
        direction="SELL",
        status=TradeStatus.OPEN,
        entry=1.25500,
        sl=1.26000,
        tp=1.24500,
    )

    # Mock active trades
    mock_trade_ledger.get_active_trades.return_value = [trade]

    # Mock price: ask at TP (TP hit for SELL)
    mock_price_feed.get_price.return_value = {
        "bid": 1.24480,
        "ask": 1.24500,
        "ts": 1234567890.0,
        "source": "test",
    }

    # Check trades
    await price_watcher._check_trades()

    # Verify update_status was called to close with TP_HIT
    mock_trade_ledger.update_status.assert_called_once_with(
        "T-006",
        TradeStatus.CLOSED,
        close_reason=CloseReason.TP_HIT,
        pnl=None,
    )


@pytest.mark.asyncio
async def test_open_to_closed_sell_sl_hit(price_watcher, mock_trade_ledger, mock_price_feed):
    """Test SELL position closing when SL is hit."""
    # Create SELL open trade
    trade = create_test_trade(
        trade_id="T-007",
        pair="GBPUSD",
        direction="SELL",
        status=TradeStatus.OPEN,
        entry=1.25500,
        sl=1.26000,
        tp=1.24500,
    )

    # Mock active trades
    mock_trade_ledger.get_active_trades.return_value = [trade]

    # Mock price: ask at SL (SL hit for SELL)
    mock_price_feed.get_price.return_value = {
        "bid": 1.25980,
        "ask": 1.26000,
        "ts": 1234567890.0,
        "source": "test",
    }

    # Check trades
    await price_watcher._check_trades()

    # Verify update_status was called to close with SL_HIT
    mock_trade_ledger.update_status.assert_called_once_with(
        "T-007",
        TradeStatus.CLOSED,
        close_reason=CloseReason.SL_HIT,
        pnl=None,
    )


@pytest.mark.asyncio
async def test_no_price_data(price_watcher, mock_trade_ledger, mock_price_feed):
    """Test handling when no price data is available."""
    # Create trade
    trade = create_test_trade(
        trade_id="T-008",
        pair="EURUSD",
        direction="BUY",
        status=TradeStatus.PENDING,
        entry=1.08500,
        sl=1.08000,
        tp=1.09500,
    )

    # Mock active trades
    mock_trade_ledger.get_active_trades.return_value = [trade]

    # Mock price: no data
    mock_price_feed.get_price.return_value = None

    # Check trades (should not crash)
    await price_watcher._check_trades()

    # Verify update_status was NOT called
    mock_trade_ledger.update_status.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_price_data(price_watcher, mock_trade_ledger, mock_price_feed):
    """Test handling when price data is invalid (zero or negative)."""
    # Create trade
    trade = create_test_trade(
        trade_id="T-009",
        pair="EURUSD",
        direction="BUY",
        status=TradeStatus.PENDING,
        entry=1.08500,
        sl=1.08000,
        tp=1.09500,
    )

    # Mock active trades
    mock_trade_ledger.get_active_trades.return_value = [trade]

    # Mock price: invalid (zero bid/ask)
    mock_price_feed.get_price.return_value = {
        "bid": 0.0,
        "ask": 0.0,
        "ts": 1234567890.0,
        "source": "test",
    }

    # Check trades (should not crash or trigger)
    await price_watcher._check_trades()

    # Verify update_status was NOT called
    mock_trade_ledger.update_status.assert_not_called()
