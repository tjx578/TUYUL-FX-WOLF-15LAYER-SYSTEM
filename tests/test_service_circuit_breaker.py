"""
ARCH-GAP-10: Service Circuit Breaker Tests
=============================================
Tests for the Redis-persisted per-service circuit breaker.
"""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

from infrastructure.service_circuit_breaker import (
    ServiceCBSnapshot,
    ServiceCBState,
    ServiceCircuitBreaker,
)


class FakeRedis:
    """Minimal in-memory Redis stub for circuit breaker tests."""

    def __init__(self):
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str) -> bool:
        self._store[key] = value
        return True


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def cb(fake_redis):
    return ServiceCircuitBreaker(
        service="engine",
        redis_client=fake_redis,
        failure_threshold=3,
        recovery_timeout_sec=60.0,
        half_open_successes=2,
    )


# ── Basic state tests ─────────────────────────────────────────────────────────


class TestServiceCBBasic:
    def test_starts_closed(self, cb):
        assert cb.state == ServiceCBState.CLOSED
        assert cb.is_closed() is True
        assert cb.is_open() is False

    def test_snapshot_returns_dataclass(self, cb):
        snap = cb.snapshot()
        assert isinstance(snap, ServiceCBSnapshot)
        assert snap.service == "engine"
        assert snap.state == "CLOSED"
        assert snap.failure_count == 0

    def test_snapshot_to_dict(self, cb):
        d = cb.snapshot().to_dict()
        assert d["service"] == "engine"
        assert d["state"] == "CLOSED"


# ── Failure → OPEN ────────────────────────────────────────────────────────────


class TestServiceCBFailures:
    def test_trips_open_after_threshold(self, cb):
        for i in range(3):
            cb.record_failure(reason=f"fail-{i}")
        assert cb.state == ServiceCBState.OPEN
        assert cb.is_open() is True

    def test_under_threshold_stays_closed(self, cb):
        cb.record_failure()
        cb.record_failure()
        assert cb.state == ServiceCBState.CLOSED

    def test_success_resets_failure_count(self, cb):
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        # Counter reset, shouldn't trip on next failure
        cb.record_failure()
        assert cb.state == ServiceCBState.CLOSED


# ── Recovery ──────────────────────────────────────────────────────────────────


class TestServiceCBRecovery:
    def test_open_to_half_open_after_timeout(self, cb):
        for _ in range(3):
            cb.record_failure()
        assert cb.state == ServiceCBState.OPEN

        # Simulate time passing
        with patch("infrastructure.service_circuit_breaker.time.monotonic", return_value=time.monotonic() + 61):
            assert cb.state == ServiceCBState.HALF_OPEN

    def test_half_open_to_closed_after_successes(self, cb):
        # Trip open
        for _ in range(3):
            cb.record_failure()

        # Fast-forward past recovery timeout
        future = time.monotonic() + 61
        with patch("infrastructure.service_circuit_breaker.time.monotonic", return_value=future):
            assert cb.state == ServiceCBState.HALF_OPEN
            cb.record_success()
            assert cb.state == ServiceCBState.HALF_OPEN  # needs 2
            cb.record_success()
            assert cb.state == ServiceCBState.CLOSED

    def test_half_open_failure_trips_open_again(self, cb):
        # Trip open
        for _ in range(3):
            cb.record_failure()

        future = time.monotonic() + 61
        with patch("infrastructure.service_circuit_breaker.time.monotonic", return_value=future):
            assert cb.state == ServiceCBState.HALF_OPEN
            # Fail enough to re-trip
            for _ in range(3):
                cb.record_failure()
            assert cb.state == ServiceCBState.OPEN


# ── Force controls ────────────────────────────────────────────────────────────


class TestServiceCBForceControls:
    def test_force_open(self, cb):
        cb.force_open(reason="deploy")
        assert cb.state == ServiceCBState.OPEN
        assert cb.snapshot().reason == "deploy"

    def test_force_close(self, cb):
        cb.force_open()
        cb.force_close(reason="recovery")
        assert cb.state == ServiceCBState.CLOSED
        assert cb.snapshot().failure_count == 0

    def test_reset(self, cb):
        for _ in range(3):
            cb.record_failure()
        cb.reset()
        assert cb.state == ServiceCBState.CLOSED
        assert cb.snapshot().failure_count == 0


# ── Redis persistence ─────────────────────────────────────────────────────────


class TestServiceCBPersistence:
    def test_persists_to_redis_on_failure(self, cb, fake_redis):
        cb.record_failure()
        raw = fake_redis.get("wolf15:service_cb:engine")
        assert raw is not None
        data = json.loads(raw)
        assert data["state"] == "CLOSED"
        assert data["failure_count"] == 1

    def test_persists_open_state(self, cb, fake_redis):
        for _ in range(3):
            cb.record_failure()
        raw = fake_redis.get("wolf15:service_cb:engine")
        data = json.loads(raw)
        assert data["state"] == "OPEN"

    def test_hydrates_from_redis(self, fake_redis):
        # Pre-seed Redis
        fake_redis.set(
            "wolf15:service_cb:ingest",
            json.dumps({"state": "OPEN", "failure_count": 5, "success_count": 0, "reason": "seed"}),
        )
        cb2 = ServiceCircuitBreaker(
            service="ingest",
            redis_client=fake_redis,
            failure_threshold=3,
            recovery_timeout_sec=60.0,
        )
        # State is hydrated but OPEN → auto-checks timeout which depends on _opened_at
        # Since _opened_at is None after hydration (no monotonic persistence),
        # it stays in the hydrated state
        assert cb2._failure_count == 5
        assert cb2._reason == "seed"

    def test_force_close_persists(self, cb, fake_redis):
        cb.force_open()
        cb.force_close(reason="manual")
        raw = fake_redis.get("wolf15:service_cb:engine")
        data = json.loads(raw)
        assert data["state"] == "CLOSED"
        assert data["failure_count"] == 0


# ── ServiceCBState enum ───────────────────────────────────────────────────────


class TestServiceCBStateEnum:
    def test_values(self):
        assert ServiceCBState.CLOSED == "CLOSED"
        assert ServiceCBState.OPEN == "OPEN"
        assert ServiceCBState.HALF_OPEN == "HALF_OPEN"

    def test_from_string(self):
        assert ServiceCBState("CLOSED") == ServiceCBState.CLOSED
        assert ServiceCBState("OPEN") == ServiceCBState.OPEN
