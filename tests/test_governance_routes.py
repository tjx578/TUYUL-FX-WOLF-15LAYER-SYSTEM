"""
ARCH-GAP-10: Governance Routes Tests
========================================
Tests for the feature flags + circuit breaker API endpoints.
"""

from __future__ import annotations

import pytest

from infrastructure.feature_flags import FeatureFlagService
from infrastructure.service_circuit_breaker import ServiceCircuitBreaker


class FakeRedisHash:
    """Stub for feature flag tests (HASH operations)."""

    def __init__(self):
        self._hashes: dict[str, dict[str, str]] = {}
        self._store: dict[str, str] = {}

    def hget(self, key, field):
        return self._hashes.get(key, {}).get(field)

    def hset(self, key, field, value):
        self._hashes.setdefault(key, {})[field] = value
        return 1

    def hgetall(self, key):
        return self._hashes.get(key, {})

    def hdel(self, key, *fields):
        bucket = self._hashes.get(key, {})
        count = 0
        for f in fields:
            if f in bucket:
                del bucket[f]
                count += 1
        return count

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value):
        self._store[key] = value
        return True


@pytest.fixture
def fake_redis():
    return FakeRedisHash()


@pytest.fixture
def ff_service(fake_redis):
    return FeatureFlagService(redis_client=fake_redis)


@pytest.fixture
def cb_engine(fake_redis):
    return ServiceCircuitBreaker(
        service="engine",
        redis_client=fake_redis,
        failure_threshold=3,
    )


# ── Integration test: FF + CB used together ───────────────────────────────────


class TestGovernanceIntegration:
    def test_maintenance_mode_blocks_evaluation(self, ff_service):
        """When maintenance_mode flag is set, is_maintenance returns True."""
        ff_service.set_flag("engine", "maintenance_mode", enabled=True, reason="deploy")
        assert ff_service.is_maintenance("engine") is True

        ff_service.set_flag("engine", "maintenance_mode", enabled=False, reason="done")
        assert ff_service.is_maintenance("engine") is False

    def test_feature_flag_and_cb_independent(self, ff_service, cb_engine):
        """Feature flags and circuit breakers operate independently."""
        ff_service.set_flag("engine", "accept_signals", enabled=False)
        assert ff_service.is_enabled("engine", "accept_signals") is False
        assert cb_engine.is_closed() is True

        # CB trips, but flags are separate
        for _ in range(3):
            cb_engine.record_failure()
        assert cb_engine.is_open() is True
        assert ff_service.is_enabled("engine", "accept_signals") is False

    def test_gradual_rollout_with_cb(self, ff_service, cb_engine):
        """50% rollout with CB closed should work for deterministic context."""
        ff_service.set_flag("engine", "new_feature", enabled=True, rollout_pct=50)
        assert cb_engine.is_closed() is True
        # Result is deterministic for same key
        result = ff_service.is_enabled("engine", "new_feature", context_key="ACC-001")
        assert isinstance(result, bool)


# ── Redis key registry ────────────────────────────────────────────────────────


class TestRedisKeyRegistry:
    def test_feature_flags_key_registered(self):
        from core.redis_keys import FEATURE_FLAGS_PREFIX, feature_flags_key

        assert FEATURE_FLAGS_PREFIX == "wolf15:feature_flags"
        assert feature_flags_key("engine") == "wolf15:feature_flags:engine"

    def test_service_cb_key_registered(self):
        from core.redis_keys import SERVICE_CB_PREFIX, service_cb_key

        assert SERVICE_CB_PREFIX == "wolf15:service_cb"
        assert service_cb_key("ingest") == "wolf15:service_cb:ingest"


# ── Router registration ──────────────────────────────────────────────────────


class TestRouterRegistered:
    def test_governance_router_in_registry(self):
        from api.router_registry import ROUTER_ENTRIES

        modules = [e.module for e in ROUTER_ENTRIES]
        assert "api.governance_routes" in modules

    def test_governance_router_imports(self):
        """Validate the governance routes module imports cleanly."""
        from api.governance_routes import router

        assert router is not None
        # Check that all expected paths exist (routes include the router prefix)
        paths = [getattr(r, "path", "") for r in router.routes]
        assert any("/flags/{service}" in p for p in paths)
        assert any("/circuit-breaker/{service}" in p for p in paths)
        assert any("/maintenance/{service}" in p for p in paths)
