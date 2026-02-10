"""
Tests for Open Risk Tracker

Tests all OpenRiskTracker functionality:
- Basic operations (add/remove trades, snapshots)
- SPLIT mode (2 entries per trade)
- Duplicate prevention
- Edge cases (corrupt data, zero lot size)
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from risk.open_risk_tracker import OpenRiskTracker, OpenTrade


# ========== Fixtures ==========

@pytest.fixture
def mock_redis():
    """Mock Redis client with in-memory store."""
    store: dict[str, str] = {}
    redis_mock = MagicMock()
    redis_mock.get.side_effect = lambda key: store.get(key)
    redis_mock.set.side_effect = lambda key, value, ex=None: store.__setitem__(key, value)
    redis_mock.delete.side_effect = lambda key: store.pop(key, None)
    return redis_mock


@pytest.fixture
def tracker(mock_redis):
    """Create OpenRiskTracker with mocked Redis."""
    with patch("risk.open_risk_tracker.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis
        return OpenRiskTracker("test_account")


# ========== Basic Operations ==========

def test_tracker_empty_initial(tracker):
    """Test tracker starts empty."""
    snapshot = tracker.get_snapshot()
    assert snapshot["open_risk_amount"] == 0.0
    assert snapshot["open_trade_count"] == 0
    assert snapshot["open_entry_count"] == 0
    assert snapshot["trades"] == []


def test_add_single_trade(tracker):
    """Test adding a single trade."""
    trade = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.1,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=50.0,
    )
    tracker.add_trade(trade)
    
    snapshot = tracker.get_snapshot()
    assert snapshot["open_risk_amount"] == 50.0
    assert snapshot["open_trade_count"] == 1
    assert snapshot["open_entry_count"] == 1
    assert len(snapshot["trades"]) == 1


def test_add_multiple_trades(tracker):
    """Test adding multiple trades."""
    trade1 = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.1,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=50.0,
    )
    trade2 = OpenTrade(
        trade_id="trade_2",
        symbol="GBPUSD",
        lot_size=0.15,
        sl_distance_pips=40.0,
        pip_value=10.0,
        risk_amount=60.0,
    )
    
    tracker.add_trade(trade1)
    tracker.add_trade(trade2)
    
    snapshot = tracker.get_snapshot()
    assert snapshot["open_risk_amount"] == 110.0
    assert snapshot["open_trade_count"] == 2
    assert snapshot["open_entry_count"] == 2


def test_remove_trade(tracker):
    """Test removing a trade."""
    trade = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.1,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=50.0,
    )
    tracker.add_trade(trade)
    tracker.remove_trade("trade_1")
    
    snapshot = tracker.get_snapshot()
    assert snapshot["open_risk_amount"] == 0.0
    assert snapshot["open_trade_count"] == 0
    assert snapshot["open_entry_count"] == 0


def test_get_open_risk(tracker):
    """Test get_open_risk calculation."""
    trade1 = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.1,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=50.0,
    )
    trade2 = OpenTrade(
        trade_id="trade_2",
        symbol="GBPUSD",
        lot_size=0.2,
        sl_distance_pips=30.0,
        pip_value=10.0,
        risk_amount=60.0,
    )
    
    tracker.add_trade(trade1)
    tracker.add_trade(trade2)
    
    assert tracker.get_open_risk() == 110.0


def test_get_open_count(tracker):
    """Test get_open_count."""
    trade1 = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.1,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=50.0,
    )
    trade2 = OpenTrade(
        trade_id="trade_2",
        symbol="GBPUSD",
        lot_size=0.2,
        sl_distance_pips=30.0,
        pip_value=10.0,
        risk_amount=60.0,
    )
    
    tracker.add_trade(trade1)
    tracker.add_trade(trade2)
    
    assert tracker.get_open_count() == 2


def test_clear_trades(tracker):
    """Test clearing all trades."""
    trade = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.1,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=50.0,
    )
    tracker.add_trade(trade)
    tracker.clear()
    
    snapshot = tracker.get_snapshot()
    assert snapshot["open_risk_amount"] == 0.0
    assert snapshot["open_trade_count"] == 0


# ========== SPLIT Mode ==========

def test_split_mode_two_entries(tracker):
    """Test SPLIT mode with 2 entries for same trade."""
    entry1 = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.04,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=20.0,
        entry_number=1,
    )
    entry2 = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.06,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=30.0,
        entry_number=2,
    )
    
    tracker.add_trade(entry1)
    tracker.add_trade(entry2)
    
    snapshot = tracker.get_snapshot()
    assert snapshot["open_risk_amount"] == 50.0  # 20 + 30
    assert snapshot["open_trade_count"] == 1  # Same trade_id
    assert snapshot["open_entry_count"] == 2  # Two entries


def test_split_mode_remove_one_entry(tracker):
    """Test removing one entry in SPLIT mode."""
    entry1 = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.04,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=20.0,
        entry_number=1,
    )
    entry2 = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.06,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=30.0,
        entry_number=2,
    )
    
    tracker.add_trade(entry1)
    tracker.add_trade(entry2)
    tracker.remove_trade("trade_1", entry_number=1)
    
    snapshot = tracker.get_snapshot()
    assert snapshot["open_risk_amount"] == 30.0  # Only entry 2 remains
    assert snapshot["open_trade_count"] == 1
    assert snapshot["open_entry_count"] == 1


def test_split_mode_remove_both_entries(tracker):
    """Test removing both entries in SPLIT mode."""
    entry1 = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.04,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=20.0,
        entry_number=1,
    )
    entry2 = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.06,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=30.0,
        entry_number=2,
    )
    
    tracker.add_trade(entry1)
    tracker.add_trade(entry2)
    tracker.remove_trade("trade_1", entry_number=1)
    tracker.remove_trade("trade_1", entry_number=2)
    
    snapshot = tracker.get_snapshot()
    assert snapshot["open_risk_amount"] == 0.0
    assert snapshot["open_trade_count"] == 0
    assert snapshot["open_entry_count"] == 0


# ========== Duplicate Prevention ==========

def test_duplicate_trade_ignored(tracker):
    """Test that duplicate trade (same trade_id + entry_number) is ignored."""
    trade = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.1,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=50.0,
    )
    
    tracker.add_trade(trade)
    tracker.add_trade(trade)  # Duplicate
    
    snapshot = tracker.get_snapshot()
    assert snapshot["open_trade_count"] == 1
    assert snapshot["open_entry_count"] == 1  # Only 1 entry added


def test_different_entry_number_allowed(tracker):
    """Test that same trade_id with different entry_number is allowed."""
    entry1 = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.1,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=50.0,
        entry_number=1,
    )
    entry2 = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.1,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=50.0,
        entry_number=2,
    )
    
    tracker.add_trade(entry1)
    tracker.add_trade(entry2)
    
    snapshot = tracker.get_snapshot()
    assert snapshot["open_trade_count"] == 1  # Same trade_id
    assert snapshot["open_entry_count"] == 2  # Different entry_number


# ========== Snapshot Structure ==========

def test_snapshot_structure(tracker):
    """Test snapshot contains all required fields."""
    trade = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.1,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=50.0,
    )
    tracker.add_trade(trade)
    
    snapshot = tracker.get_snapshot()
    assert "open_risk_amount" in snapshot
    assert "open_trade_count" in snapshot
    assert "open_entry_count" in snapshot
    assert "trades" in snapshot
    assert isinstance(snapshot["trades"], list)


def test_snapshot_trade_details(tracker):
    """Test snapshot contains trade details."""
    trade = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.1,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=50.0,
        entry_number=1,
    )
    tracker.add_trade(trade)
    
    snapshot = tracker.get_snapshot()
    assert len(snapshot["trades"]) == 1
    
    trade_data = snapshot["trades"][0]
    assert trade_data["trade_id"] == "trade_1"
    assert trade_data["symbol"] == "EURUSD"
    assert trade_data["lot_size"] == 0.1
    assert trade_data["sl_distance_pips"] == 50.0
    assert trade_data["pip_value"] == 10.0
    assert trade_data["risk_amount"] == 50.0
    assert trade_data["entry_number"] == 1


# ========== Edge Cases ==========

def test_corrupt_redis_data_graceful_recovery(mock_redis):
    """Test graceful recovery from corrupt Redis data."""
    with patch("risk.open_risk_tracker.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis
        
        # Set corrupt data
        store: dict[str, str] = {}
        mock_redis.get.side_effect = lambda key: store.get(key)
        store["wolf15:risk:open_trades:test_account"] = "invalid json {{"
        
        tracker = OpenRiskTracker("test_account")
        snapshot = tracker.get_snapshot()
        
        # Should recover gracefully with empty data
        assert snapshot["open_risk_amount"] == 0.0
        assert snapshot["open_trade_count"] == 0


def test_zero_lot_size(tracker):
    """Test trade with zero lot size."""
    trade = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.0,
        sl_distance_pips=50.0,
        pip_value=10.0,
        risk_amount=0.0,
    )
    tracker.add_trade(trade)
    
    snapshot = tracker.get_snapshot()
    assert snapshot["open_risk_amount"] == 0.0
    assert snapshot["open_trade_count"] == 1  # Trade is tracked even with 0 lot


def test_zero_risk_amount(tracker):
    """Test trade with zero risk amount."""
    trade = OpenTrade(
        trade_id="trade_1",
        symbol="EURUSD",
        lot_size=0.1,
        sl_distance_pips=0.0,
        pip_value=10.0,
        risk_amount=0.0,
    )
    tracker.add_trade(trade)
    
    snapshot = tracker.get_snapshot()
    assert snapshot["open_risk_amount"] == 0.0
    assert snapshot["open_trade_count"] == 1


def test_remove_nonexistent_trade(tracker):
    """Test removing a trade that doesn't exist (should not error)."""
    tracker.remove_trade("nonexistent_trade")
    
    snapshot = tracker.get_snapshot()
    assert snapshot["open_trade_count"] == 0


def test_multiple_accounts_isolated(mock_redis):
    """Test that multiple accounts are isolated in Redis."""
    with patch("risk.open_risk_tracker.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis
        
        tracker1 = OpenRiskTracker("account_1")
        tracker2 = OpenRiskTracker("account_2")
        
        trade1 = OpenTrade(
            trade_id="trade_1",
            symbol="EURUSD",
            lot_size=0.1,
            sl_distance_pips=50.0,
            pip_value=10.0,
            risk_amount=50.0,
        )
        
        tracker1.add_trade(trade1)
        
        # Account 2 should have no trades
        assert tracker2.get_open_count() == 0
        # Account 1 should have 1 trade
        assert tracker1.get_open_count() == 1
