import json
from typing import Any

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


def _new_manager(redis_client: _FakeRedis) -> StateManager:
    manager = StateManager(redis_client=redis_client)
    manager.configure_intervals(compliance_interval_sec=1.0, heartbeat_interval_sec=300.0)
    return manager


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
