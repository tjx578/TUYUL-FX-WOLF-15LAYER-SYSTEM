"""
ARCH-GAP-10: Feature Flags Tests
===================================
Tests for the Redis-backed per-service feature flag system.
"""

from __future__ import annotations

import pytest

from infrastructure.feature_flags import (
    FLAG_MAINTENANCE_MODE,
    KNOWN_SERVICES,
    FeatureFlagService,
    FlagState,
)


class FakeRedis:
    """Minimal in-memory Redis stub for feature flag tests."""

    def __init__(self):
        self._store: dict[str, dict[str, str]] = {}

    def hget(self, key: str, field: str) -> str | None:
        return self._store.get(key, {}).get(field)

    def hset(self, key: str, field: str, value: str) -> int:
        self._store.setdefault(key, {})[field] = value
        return 1

    def hgetall(self, key: str) -> dict[str, str]:
        return self._store.get(key, {})

    def hdel(self, key: str, *fields: str) -> int:
        bucket = self._store.get(key, {})
        count = 0
        for f in fields:
            if f in bucket:
                del bucket[f]
                count += 1
        return count


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def ff(fake_redis):
    return FeatureFlagService(redis_client=fake_redis)


# ── Basic CRUD ────────────────────────────────────────────────────────────────


class TestFeatureFlagCRUD:
    def test_set_and_get_flag(self, ff):
        state = ff.set_flag("engine", "accept_signals", enabled=True, reason="test")
        assert state.enabled is True
        assert state.rollout_pct == 100
        assert state.reason == "test"

        retrieved = ff.get_flag("engine", "accept_signals")
        assert retrieved is not None
        assert retrieved.enabled is True

    def test_get_nonexistent_flag_returns_none(self, ff):
        assert ff.get_flag("engine", "nonexistent") is None

    def test_get_all_flags_empty(self, ff):
        assert ff.get_all_flags("engine") == {}

    def test_get_all_flags_returns_all(self, ff):
        ff.set_flag("engine", "flag_a", enabled=True)
        ff.set_flag("engine", "flag_b", enabled=False)
        all_flags = ff.get_all_flags("engine")
        assert len(all_flags) == 2
        assert "flag_a" in all_flags
        assert "flag_b" in all_flags

    def test_delete_flag(self, ff):
        ff.set_flag("engine", "to_delete", enabled=True)
        assert ff.delete_flag("engine", "to_delete") is True
        assert ff.get_flag("engine", "to_delete") is None

    def test_delete_nonexistent_returns_false(self, ff):
        assert ff.delete_flag("engine", "nope") is False

    def test_rollout_pct_validation(self, ff):
        with pytest.raises(ValueError, match="rollout_pct must be 0-100"):
            ff.set_flag("engine", "bad", enabled=True, rollout_pct=101)
        with pytest.raises(ValueError, match="rollout_pct must be 0-100"):
            ff.set_flag("engine", "bad", enabled=True, rollout_pct=-1)

    def test_get_all_services(self, ff):
        ff.set_flag("api", "flag_x", enabled=True)
        result = ff.get_all_services()
        assert isinstance(result, dict)
        for svc in KNOWN_SERVICES:
            assert svc in result


# ── Feature evaluation ────────────────────────────────────────────────────────


class TestFeatureFlagEvaluation:
    def test_unset_flag_returns_default_true(self, ff):
        assert ff.is_enabled("engine", "unset_flag") is True

    def test_unset_flag_returns_explicit_default(self, ff):
        assert ff.is_enabled("engine", "unset", default=False) is False

    def test_disabled_flag_returns_false(self, ff):
        ff.set_flag("engine", "disabled", enabled=False)
        assert ff.is_enabled("engine", "disabled") is False

    def test_enabled_flag_100pct_returns_true(self, ff):
        ff.set_flag("engine", "on", enabled=True, rollout_pct=100)
        assert ff.is_enabled("engine", "on") is True

    def test_enabled_flag_0pct_returns_false(self, ff):
        ff.set_flag("engine", "off", enabled=True, rollout_pct=0)
        assert ff.is_enabled("engine", "off") is False

    def test_rollout_deterministic_with_context(self, ff):
        """Same context_key always gives same result."""
        ff.set_flag("engine", "gradual", enabled=True, rollout_pct=50)
        results = [ff.is_enabled("engine", "gradual", context_key="ACC-001") for _ in range(100)]
        assert len(set(results)) == 1  # all same

    def test_rollout_varies_by_context(self, ff):
        """Different context_keys produce different buckets (with high rollout, most are enabled)."""
        ff.set_flag("engine", "gradual", enabled=True, rollout_pct=80)
        results = [
            ff.is_enabled("engine", "gradual", context_key=f"ACC-{i:04d}") for i in range(200)
        ]
        enabled = sum(results)
        # Should be roughly 80% — allow generous margin
        assert 100 < enabled < 200


# ── Maintenance mode ──────────────────────────────────────────────────────────


class TestMaintenanceMode:
    def test_not_in_maintenance_by_default(self, ff):
        assert ff.is_maintenance("engine") is False

    def test_enable_maintenance(self, ff):
        ff.set_flag("engine", FLAG_MAINTENANCE_MODE, enabled=True, reason="deploy")
        assert ff.is_maintenance("engine") is True

    def test_disable_maintenance(self, ff):
        ff.set_flag("engine", FLAG_MAINTENANCE_MODE, enabled=True)
        ff.set_flag("engine", FLAG_MAINTENANCE_MODE, enabled=False)
        assert ff.is_maintenance("engine") is False


# ── FlagState dataclass ───────────────────────────────────────────────────────


class TestFlagState:
    def test_to_dict(self):
        fs = FlagState(name="test", enabled=True, rollout_pct=50, reason="r", changed_by="op")
        d = fs.to_dict()
        assert d["name"] == "test"
        assert d["enabled"] is True
        assert d["rollout_pct"] == 50

    def test_decode_round_trip(self, ff):
        """set → get produces identical state."""
        original = ff.set_flag("api", "roundtrip", enabled=True, rollout_pct=75, reason="test")
        retrieved = ff.get_flag("api", "roundtrip")
        assert retrieved is not None
        assert retrieved.enabled == original.enabled
        assert retrieved.rollout_pct == original.rollout_pct
        assert retrieved.reason == original.reason
