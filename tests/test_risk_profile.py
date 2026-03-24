"""
Tests for Risk Profile

Tests all RiskProfile functionality:
- Creation & validation (default values, FIXED/SPLIT modes, immutability)
- Parametrized invalid field values
- Split ratio validation
- Serialization round-trip
- Redis persistence
"""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest

from risk.exceptions import RiskException
from risk.risk_profile import (
    RiskMode,
    RiskProfile,
    load_risk_profile,
    save_risk_profile,
)

# ========== Fixtures ==========


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    store: dict[str, str] = {}
    redis_mock = MagicMock()
    redis_mock.get.side_effect = store.get
    redis_mock.set.side_effect = lambda key, value, ex=None: store.__setitem__(key, value)
    return redis_mock


# ========== Creation & Validation ==========


def test_risk_profile_default_values():
    """Test default RiskProfile values."""
    profile = RiskProfile()
    assert profile.risk_per_trade == 0.7
    assert profile.max_daily_dd == 5.0
    assert profile.max_total_dd == 10.0
    assert profile.max_open_trades == 1
    assert profile.risk_mode == RiskMode.FIXED
    assert profile.split_ratio == (0.4, 0.6)


def test_risk_profile_fixed_mode():
    """Test RiskProfile in FIXED mode."""
    profile = RiskProfile(
        risk_per_trade=1.0,
        max_daily_dd=4.0,
        max_total_dd=8.0,
        max_open_trades=2,
        risk_mode=RiskMode.FIXED,
    )
    assert profile.risk_mode == RiskMode.FIXED


def test_risk_profile_split_mode():
    """Test RiskProfile in SPLIT mode with valid ratio."""
    profile = RiskProfile(
        risk_per_trade=0.8,
        risk_mode=RiskMode.SPLIT,
        split_ratio=(0.5, 0.5),
    )
    assert profile.risk_mode == RiskMode.SPLIT
    assert profile.split_ratio == (0.5, 0.5)


def test_risk_profile_immutability():
    """Test that RiskProfile is immutable (frozen dataclass)."""
    profile = RiskProfile()
    with pytest.raises(FrozenInstanceError):
        profile.risk_per_trade = 2.0


# ========== Invalid Field Values ==========


@pytest.mark.parametrize("risk_per_trade", [-1.0, 0.0, 5.1, 10.0])
def test_risk_profile_invalid_risk_per_trade(risk_per_trade):
    """Test that invalid risk_per_trade raises RiskException."""
    with pytest.raises(RiskException, match="risk_per_trade"):
        RiskProfile(risk_per_trade=risk_per_trade)


@pytest.mark.parametrize("max_daily_dd", [-1.0, 0.0, 20.1, 30.0])
def test_risk_profile_invalid_max_daily_dd(max_daily_dd):
    """Test that invalid max_daily_dd raises RiskException."""
    with pytest.raises(RiskException, match="max_daily_dd"):
        RiskProfile(max_daily_dd=max_daily_dd)


@pytest.mark.parametrize("max_total_dd", [-1.0, 0.0, 30.1, 50.0])
def test_risk_profile_invalid_max_total_dd(max_total_dd):
    """Test that invalid max_total_dd raises RiskException."""
    with pytest.raises(RiskException, match="max_total_dd"):
        RiskProfile(max_total_dd=max_total_dd)


@pytest.mark.parametrize("max_open_trades", [0, -1, 6, 10])
def test_risk_profile_invalid_max_open_trades(max_open_trades):
    """Test that invalid max_open_trades raises RiskException."""
    with pytest.raises(RiskException, match="max_open_trades"):
        RiskProfile(max_open_trades=max_open_trades)


# ========== Split Ratio Validation ==========


@pytest.mark.parametrize(
    "split_ratio",
    [
        (0.4, 0.6),
        (0.5, 0.5),
        (0.3, 0.7),
        (0.6, 0.4),
        (0.2, 0.8),
    ],
)
def test_risk_profile_valid_split_ratios(split_ratio):
    """Test various valid split ratios that sum to 1.0."""
    profile = RiskProfile(
        risk_mode=RiskMode.SPLIT,
        split_ratio=split_ratio,
    )
    assert sum(profile.split_ratio) == 1.0


@pytest.mark.parametrize(
    "split_ratio",
    [
        (0.4, 0.5),  # sums to 0.9
        (0.5, 0.6),  # sums to 1.1
        (0.3, 0.3),  # sums to 0.6
        (1.0, 1.0),  # sums to 2.0
    ],
)
def test_risk_profile_invalid_split_ratios(split_ratio):
    """Test that invalid split ratios raise RiskException."""
    with pytest.raises(RiskException, match="split_ratio"):
        RiskProfile(
            risk_mode=RiskMode.SPLIT,
            split_ratio=split_ratio,
        )


def test_risk_profile_split_ratio_ignored_in_fixed_mode():
    """Test that split_ratio is not validated in FIXED mode."""
    # Invalid ratio should not raise exception in FIXED mode
    profile = RiskProfile(
        risk_mode=RiskMode.FIXED,
        split_ratio=(0.3, 0.3),  # invalid but ignored
    )
    assert profile.risk_mode == RiskMode.FIXED


# ========== Serialization ==========


def test_risk_profile_to_dict():
    """Test RiskProfile serialization to dict."""
    profile = RiskProfile(
        risk_per_trade=1.2,
        max_daily_dd=6.0,
        max_total_dd=12.0,
        max_open_trades=3,
        risk_mode=RiskMode.SPLIT,
        split_ratio=(0.4, 0.6),
    )
    data = profile.to_dict()

    assert data["risk_per_trade"] == 1.2
    assert data["max_daily_dd"] == 6.0
    assert data["max_total_dd"] == 12.0
    assert data["max_open_trades"] == 3
    assert data["risk_mode"] == "SPLIT"  # Enum serialized to string
    assert data["split_ratio"] == [0.4, 0.6]  # Tuple serialized to list


def test_risk_profile_from_dict():
    """Test RiskProfile deserialization from dict."""
    data = {
        "risk_per_trade": 1.5,
        "max_daily_dd": 7.0,
        "max_total_dd": 14.0,
        "max_open_trades": 4,
        "risk_mode": "FIXED",
        "split_ratio": [0.5, 0.5],
    }
    profile = RiskProfile.from_dict(data)

    assert profile.risk_per_trade == 1.5
    assert profile.max_daily_dd == 7.0
    assert profile.max_total_dd == 14.0
    assert profile.max_open_trades == 4
    assert profile.risk_mode == RiskMode.FIXED
    assert profile.split_ratio == (0.5, 0.5)  # List converted to tuple


def test_risk_profile_round_trip():
    """Test serialization round-trip preserves data."""
    original = RiskProfile(
        risk_per_trade=2.0,
        max_daily_dd=8.0,
        max_total_dd=15.0,
        max_open_trades=5,
        risk_mode=RiskMode.SPLIT,
        split_ratio=(0.3, 0.7),
    )
    data = original.to_dict()
    restored = RiskProfile.from_dict(data)

    assert restored.risk_per_trade == original.risk_per_trade
    assert restored.max_daily_dd == original.max_daily_dd
    assert restored.max_total_dd == original.max_total_dd
    assert restored.max_open_trades == original.max_open_trades
    assert restored.risk_mode == original.risk_mode
    assert restored.split_ratio == original.split_ratio


def test_risk_profile_json_round_trip():
    """Test JSON serialization round-trip."""
    original = RiskProfile(
        risk_per_trade=1.8,
        risk_mode=RiskMode.SPLIT,
        split_ratio=(0.6, 0.4),
    )

    # Serialize to JSON
    json_str = json.dumps(original.to_dict())

    # Deserialize from JSON
    data = json.loads(json_str)
    restored = RiskProfile.from_dict(data)

    assert restored.risk_per_trade == original.risk_per_trade
    assert restored.risk_mode == original.risk_mode
    assert restored.split_ratio == original.split_ratio


# ========== Redis Persistence ==========


def test_save_risk_profile(mock_redis):
    """Test saving risk profile to Redis."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        profile = RiskProfile(
            risk_per_trade=1.5,
            risk_mode=RiskMode.FIXED,
        )

        save_risk_profile("test_account", profile)

        # Verify Redis set was called
        assert mock_redis.set.called
        call_args = mock_redis.set.call_args
        key = call_args[0][0]
        value = call_args[0][1]

        assert "wolf15:risk:profile:test_account" in key
        assert "1.5" in value  # JSON contains risk_per_trade


def test_load_risk_profile_existing(mock_redis):
    """Test loading existing risk profile from Redis."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        # Prepare stored profile
        stored_profile = RiskProfile(
            risk_per_trade=2.5,
            risk_mode=RiskMode.SPLIT,
            split_ratio=(0.5, 0.5),
        )

        # Manually set in mock store
        store: dict[str, str] = {}
        mock_redis.get.side_effect = store.get
        store["wolf15:risk:profile:test_account"] = json.dumps(stored_profile.to_dict())

        # Load profile
        loaded = load_risk_profile("test_account")

        assert loaded.risk_per_trade == 2.5
        assert loaded.risk_mode == RiskMode.SPLIT
        assert loaded.split_ratio == (0.5, 0.5)


def test_load_risk_profile_default_fallback(mock_redis):
    """Test loading profile returns default when not found."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        # Mock get returns None (not found)
        mock_redis.get.return_value = None

        # Load profile
        loaded = load_risk_profile("nonexistent_account")

        # Should return default profile
        assert loaded.risk_per_trade == 0.7
        assert loaded.risk_mode == RiskMode.FIXED


def test_save_and_load_round_trip(mock_redis):
    """Test save/load round-trip with Redis."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        store: dict[str, str] = {}
        mock_redis.get.side_effect = store.get
        mock_redis.set.side_effect = lambda key, value, ex=None: store.__setitem__(key, value)
        MockRedis.return_value = mock_redis

        # Create and save profile
        original = RiskProfile(
            risk_per_trade=3.0,
            max_daily_dd=10.0,
            max_total_dd=20.0,
            max_open_trades=4,
            risk_mode=RiskMode.SPLIT,
            split_ratio=(0.4, 0.6),
        )
        save_risk_profile("test_account", original)

        # Load profile
        loaded = load_risk_profile("test_account")

        # Verify all fields match
        assert loaded.risk_per_trade == original.risk_per_trade
        assert loaded.max_daily_dd == original.max_daily_dd
        assert loaded.max_total_dd == original.max_total_dd
        assert loaded.max_open_trades == original.max_open_trades
        assert loaded.risk_mode == original.risk_mode
        assert loaded.split_ratio == original.split_ratio


# ========== RiskMode Enum ==========


def test_risk_mode_enum_values():
    """Test RiskMode enum has expected values."""
    assert RiskMode.FIXED == "FIXED"
    assert RiskMode.SPLIT == "SPLIT"


def test_risk_mode_enum_from_string():
    """Test creating RiskMode from string."""
    assert RiskMode("FIXED") == RiskMode.FIXED
    assert RiskMode("SPLIT") == RiskMode.SPLIT


def test_risk_mode_enum_invalid():
    """Test invalid RiskMode raises ValueError."""
    with pytest.raises(ValueError):
        RiskMode("INVALID")
