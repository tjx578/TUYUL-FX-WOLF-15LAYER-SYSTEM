from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import patch

from services.orchestrator.execution_mode import ExecutionMode
from services.orchestrator.state_manager import StateManager


class _FakePubSub:
    def __init__(self) -> None:
        super().__init__()
        self._messages: list[dict[str, Any]] = []
        self.subscribed: list[str] = []
        self.closed = False

    def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    def queue_json(self, payload: dict[str, Any]) -> None:
        self._messages.append({"data": json.dumps(payload)})

    def get_message(
        self,
        ignore_subscribe_messages: bool = True,
        timeout: float = 0.0,
    ) -> dict[str, Any] | None:
        del ignore_subscribe_messages, timeout
        if not self._messages:
            return None
        return self._messages.pop(0)

    def close(self) -> None:
        self.closed = True


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._commands: list[tuple[str, tuple[Any, ...]]] = []

    def set(self, key: str, value: str, ex: int | None = None) -> _FakePipeline:
        self._commands.append(("set", (key, value, ex)))
        return self

    def publish(self, channel: str, message: str) -> _FakePipeline:
        self._commands.append(("publish", (channel, message)))
        return self

    def execute(self) -> list[Any]:
        results: list[Any] = []
        for cmd, args in self._commands:
            if cmd == "set":
                self._redis.set(args[0], args[1], ex=args[2])
                results.append(True)
            elif cmd == "publish":
                results.append(self._redis.publish(args[0], args[1]))
        self._commands.clear()
        return results


class _FakeRedis:
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []
        self._pubsub = _FakePubSub()

    def pubsub(self) -> _FakePubSub:
        return self._pubsub

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        del ex
        self.values[key] = value

    def queue_channel_json(self, payload: dict[str, Any]) -> None:
        self._pubsub.queue_json(payload)

    def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1

    def mget(self, keys: list[str]) -> list[str | None]:
        return [self.values.get(k) for k in keys]

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)


def _new_manager(redis_client: _FakeRedis) -> StateManager:
    manager = StateManager(redis_client=redis_client)
    manager.configure_intervals(compliance_interval_sec=1.0, heartbeat_interval_sec=300.0)
    return manager


def _seed_compliance_signals(redis: _FakeRedis) -> None:
    """Populate Redis keys needed by _refresh_compliance_signals so it doesn't inject blockers."""
    from core.redis_keys import HEARTBEAT_INGEST
    redis.values[HEARTBEAT_INGEST] = json.dumps({"producer": "ingest", "ts": time.time()})


# Patch is_forex_market_open for all tests in this module so session_locked
# doesn't depend on the real clock (which may be a weekend).
_MKT_OPEN = patch("services.orchestrator.state_manager.is_forex_market_open", return_value=True)


def test_compliance_critical_sets_kill_switch() -> None:
    redis = _FakeRedis()
    manager = _new_manager(redis)

    manager.process_once(now=10.0)

    snap = manager.snapshot()
    assert snap.mode == ExecutionMode.KILL_SWITCH
    assert snap.compliance_code == "ACCOUNT_STATE_MISSING"
    assert len(redis.published) == 1
    event = json.loads(redis.published[0][1])
    assert event["event"] == "MODE_CHANGED"


def test_compliance_warning_sets_safe() -> None:
    redis = _FakeRedis()
    manager = _new_manager(redis)
    manager.update_account_state(
        {
            "balance": 10000,
            "equity": 9800,
            "compliance_mode": True,
            "daily_dd_percent": 4.6,
            "max_daily_dd_percent": 5.0,
        }
    )

    manager.process_once(now=10.0)

    snap = manager.snapshot()
    assert snap.mode == ExecutionMode.SAFE
    assert snap.compliance_code == "DAILY_DD_NEAR_LIMIT"


def test_healthy_compliance_back_to_normal() -> None:
    redis = _FakeRedis()
    _seed_compliance_signals(redis)
    manager = _new_manager(redis)
    manager.set_mode(ExecutionMode.SAFE, reason="manual")
    manager.update_account_state(
        {
            "balance": 10000,
            "equity": 9990,
            "compliance_mode": True,
            "daily_dd_percent": 1.0,
            "max_daily_dd_percent": 5.0,
            "total_dd_percent": 2.0,
            "max_total_dd_percent": 10.0,
        }
    )

    with _MKT_OPEN:
        # Auto-recovery requires 3 consecutive normal compliance checks
        manager.process_once(now=10.0)
        assert manager.snapshot().mode == ExecutionMode.SAFE  # check 1/3

        manager.process_once(now=20.0)
        assert manager.snapshot().mode == ExecutionMode.SAFE  # check 2/3

        manager.process_once(now=30.0)  # check 3/3 → recovers
    snap = manager.snapshot()
    assert snap.mode == ExecutionMode.NORMAL
    assert snap.compliance_code == "OK"


def test_command_set_mode_from_pubsub() -> None:
    redis = _FakeRedis()
    manager = _new_manager(redis)
    manager.start_listener()

    redis.queue_channel_json({"command": "SET_MODE", "mode": "SAFE", "reason": "ops"})
    manager.process_once(now=0.5)

    snap = manager.snapshot()
    assert snap.mode == ExecutionMode.SAFE
    assert snap.compliance_code == "EXTERNAL_COMMAND"
    assert any(json.loads(raw)["event"] == "MODE_CHANGED" for _, raw in redis.published)


# --- account state helper for healthy compliance ---

_HEALTHY_ACCOUNT = {
    "balance": 10000,
    "equity": 9990,
    "compliance_mode": True,
    "daily_dd_percent": 1.0,
    "max_daily_dd_percent": 5.0,
    "total_dd_percent": 2.0,
    "max_total_dd_percent": 10.0,
}

_WARNING_ACCOUNT = {
    "balance": 10000,
    "equity": 9800,
    "compliance_mode": True,
    "daily_dd_percent": 4.6,
    "max_daily_dd_percent": 5.0,
}


def test_recovery_counter_resets_after_successful_transition() -> None:
    """After 3 normals → NORMAL, _recovery_count must be 0 (not lingering at 3)."""
    redis = _FakeRedis()
    _seed_compliance_signals(redis)
    manager = _new_manager(redis)
    manager.set_mode(ExecutionMode.SAFE, reason="test")
    manager.update_account_state(_HEALTHY_ACCOUNT)

    with _MKT_OPEN:
        manager.process_once(now=10.0)  # 1/3
        manager.process_once(now=20.0)  # 2/3
        manager.process_once(now=30.0)  # 3/3 → NORMAL

    assert manager.snapshot().mode == ExecutionMode.NORMAL
    assert manager._recovery_count == 0  # noqa: SLF001


def test_oscillation_does_not_deadlock_recovery() -> None:
    """Rapid NORMAL/non-NORMAL oscillation must not prevent recovery forever.

    With decrement-by-1 instead of hard-reset, interleaved non-normal checks
    only slow recovery, not block it.
    """
    redis = _FakeRedis()
    _seed_compliance_signals(redis)
    manager = _new_manager(redis)
    manager.set_mode(ExecutionMode.SAFE, reason="test")

    t = 10.0

    with _MKT_OPEN:
        # Oscillation pattern: normal, non-normal, normal, normal, non-normal, normal, normal, normal
        # With decrement: count goes 1 → 0 → 1 → 2 → 1 → 2 → 3 → recover
        for healthy in [True, False, True, True, False, True, True, True]:
            if healthy:
                manager.update_account_state(_HEALTHY_ACCOUNT)
            else:
                manager.update_account_state(_WARNING_ACCOUNT)
            manager.process_once(now=t)
            t += 10.0

    assert manager.snapshot().mode == ExecutionMode.NORMAL, "System should have recovered despite oscillation"


def test_sustained_nonnormal_drains_counter_to_zero() -> None:
    """Sustained non-NORMAL ticks must still drain recovery progress to 0."""
    redis = _FakeRedis()
    _seed_compliance_signals(redis)
    manager = _new_manager(redis)
    manager.set_mode(ExecutionMode.SAFE, reason="test")
    manager.update_account_state(_HEALTHY_ACCOUNT)

    t = 10.0
    with _MKT_OPEN:
        # Build up 2 recovery counts
        manager.process_once(now=t)
        t += 10.0  # count = 1
        manager.process_once(now=t)
        t += 10.0  # count = 2

        # Now 5 non-normals: decrements 2→1→0→0→0
        for _ in range(5):
            manager.update_account_state(_WARNING_ACCOUNT)
            manager.process_once(now=t)
            t += 10.0

    assert manager.snapshot().mode != ExecutionMode.NORMAL
    assert manager._recovery_count == 0  # noqa: SLF001
