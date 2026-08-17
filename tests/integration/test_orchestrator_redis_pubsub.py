"""Integration tests for orchestrator Redis pub/sub flow.

These tests require a reachable Redis instance and are skipped automatically
when Redis is unavailable.
"""

from __future__ import annotations

import contextlib
import json
import time
import uuid
from typing import Any

import pytest

from infrastructure.redis_url import get_redis_url
from services.orchestrator.execution_mode import ExecutionMode
from services.orchestrator.state_manager import StateManager

redis = pytest.importorskip("redis")


def _wait_until(predicate: Any, timeout: float = 2.0, interval: float = 0.02) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("Timed out waiting for predicate")


class _RedisAdapter:
    """Small adapter to satisfy StateManager redis protocol in integration tests."""

    def __init__(self, client: Any) -> None:
        super().__init__()
        self._client = client

    def pubsub(self) -> Any:
        return self._client.pubsub()

    def get(self, key: str) -> str | None:
        return self._client.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._client.set(key, value, ex=ex)

    def publish(self, channel: str, message: str) -> int:
        return int(self._client.publish(channel, message))

    def mget(self, keys: list[str]) -> list[str | None]:
        return self._client.mget(keys)

    def pipeline(self) -> Any:
        return self._client.pipeline()


@pytest.fixture
def redis_client() -> Any:
    url = get_redis_url()
    client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2)
    try:
        client.ping()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Redis integration test skipped: {exc}")

    try:
        yield client
    finally:
        with contextlib.suppress(Exception):
            client.close()


@pytest.mark.integration
def test_orchestrator_receives_set_mode_command_via_redis(redis_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    suffix = uuid.uuid4().hex
    channel = f"wolf15:test:orchestrator:commands:{suffix}"
    state_key = f"wolf15:test:orchestrator:state:{suffix}"
    account_key = f"wolf15:test:orchestrator:account:{suffix}"
    risk_key = f"wolf15:test:orchestrator:risk:{suffix}"
    news_key = f"wolf15:test:orchestrator:news:{suffix}"
    heartbeat_key = f"wolf15:test:orchestrator:heartbeat:{suffix}"
    orchestrator_heartbeat_key = f"wolf15:test:orchestrator:self-heartbeat:{suffix}"
    kill_switch_key = f"wolf15:test:orchestrator:kill-switch:{suffix}"

    monkeypatch.setenv("ORCHESTRATOR_CHANNEL", channel)
    monkeypatch.setenv("ORCHESTRATOR_STATE_KEY", state_key)
    monkeypatch.setenv("ORCHESTRATOR_ACCOUNT_STATE_KEY", account_key)
    monkeypatch.setenv("ORCHESTRATOR_TRADE_RISK_KEY", risk_key)
    monkeypatch.delenv("ORCHESTRATOR_COMMAND_SECRET", raising=False)
    monkeypatch.setattr("services.orchestrator.state_manager._NEWS_LOCK_STATE_KEY", news_key)
    monkeypatch.setattr("services.orchestrator.state_manager.HEARTBEAT_INGEST", heartbeat_key)
    monkeypatch.setattr(
        "services.orchestrator.state_manager.HEARTBEAT_ORCHESTRATOR",
        orchestrator_heartbeat_key,
    )
    monkeypatch.setattr("services.orchestrator.state_manager.KILL_SWITCH", kill_switch_key)
    monkeypatch.setattr("services.orchestrator.state_manager.is_forex_market_open", lambda: True)

    redis_client.set(
        account_key,
        json.dumps(
            {
                "balance": 10_000,
                "equity": 10_000,
                "compliance_mode": True,
                "account_locked": False,
                "system_state": "NORMAL",
                "circuit_breaker": False,
                "daily_dd_percent": 0.0,
                "max_daily_dd_percent": 5.0,
                "total_dd_percent": 0.0,
                "max_total_dd_percent": 10.0,
                "open_trades": 0,
                "max_concurrent_trades": 5,
                "max_risk_per_trade_percent": 2.0,
            }
        ),
    )
    redis_client.set(risk_key, json.dumps({"risk_percent": 1.0}))
    redis_client.set(heartbeat_key, json.dumps({"producer": "ingest", "ts": time.time()}))

    manager = StateManager(redis_client=_RedisAdapter(redis_client))  # type: ignore[arg-type]

    try:
        manager.process_once(now=10.0)
        assert manager.snapshot().mode == ExecutionMode.NORMAL
        assert manager.snapshot().compliance_code == "OK"

        manager.start_listener()
        redis_client.publish(
            channel,
            json.dumps({"command": "SET_MODE", "mode": "SAFE", "reason": "integration-test"}),
        )

        _wait_until(
            lambda: manager.process_once(now=10.5) or manager.snapshot().mode == ExecutionMode.SAFE,
            timeout=2.0,
            interval=0.02,
        )

        snap = manager.snapshot()
        assert snap.mode == ExecutionMode.SAFE
        assert snap.compliance_code == "EXTERNAL_COMMAND"

        stored = redis_client.get(state_key)
        assert stored is not None
        payload = json.loads(stored)
        assert payload["event"] == "MODE_CHANGED"
        assert payload["mode"] == "SAFE"
    finally:
        manager.close()
        redis_client.delete(
            state_key,
            account_key,
            risk_key,
            news_key,
            heartbeat_key,
            orchestrator_heartbeat_key,
            kill_switch_key,
        )


@pytest.mark.integration
def test_orchestrator_redis_set_mode_cannot_downgrade_missing_account_kill_switch(
    redis_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid.uuid4().hex
    channel = f"wolf15:test:orchestrator:commands:{suffix}"
    state_key = f"wolf15:test:orchestrator:state:{suffix}"
    account_key = f"wolf15:test:orchestrator:account:{suffix}"
    risk_key = f"wolf15:test:orchestrator:risk:{suffix}"
    news_key = f"wolf15:test:orchestrator:news:{suffix}"
    heartbeat_key = f"wolf15:test:orchestrator:heartbeat:{suffix}"
    orchestrator_heartbeat_key = f"wolf15:test:orchestrator:self-heartbeat:{suffix}"
    kill_switch_key = f"wolf15:test:orchestrator:kill-switch:{suffix}"

    monkeypatch.setenv("ORCHESTRATOR_CHANNEL", channel)
    monkeypatch.setenv("ORCHESTRATOR_STATE_KEY", state_key)
    monkeypatch.setenv("ORCHESTRATOR_ACCOUNT_STATE_KEY", account_key)
    monkeypatch.setenv("ORCHESTRATOR_TRADE_RISK_KEY", risk_key)
    monkeypatch.delenv("ORCHESTRATOR_COMMAND_SECRET", raising=False)
    monkeypatch.setattr("services.orchestrator.state_manager._NEWS_LOCK_STATE_KEY", news_key)
    monkeypatch.setattr("services.orchestrator.state_manager.HEARTBEAT_INGEST", heartbeat_key)
    monkeypatch.setattr(
        "services.orchestrator.state_manager.HEARTBEAT_ORCHESTRATOR",
        orchestrator_heartbeat_key,
    )
    monkeypatch.setattr("services.orchestrator.state_manager.KILL_SWITCH", kill_switch_key)
    monkeypatch.setattr("services.orchestrator.state_manager.is_forex_market_open", lambda: True)

    redis_client.set(risk_key, json.dumps({"risk_percent": 1.0}))
    redis_client.set(heartbeat_key, json.dumps({"producer": "ingest", "ts": time.time()}))

    manager = StateManager(redis_client=_RedisAdapter(redis_client))  # type: ignore[arg-type]
    manager.start_listener()
    handled_commands: list[dict[str, Any]] = []
    original_handle = manager._handle_channel_message  # noqa: SLF001

    def track_command(payload: dict[str, Any]) -> None:
        if str(payload.get("command", "")).strip().lower() == "set_mode":
            handled_commands.append(payload)
        original_handle(payload)

    monkeypatch.setattr(manager, "_handle_channel_message", track_command)

    try:
        manager.process_once(now=10.0)
        assert manager.snapshot().mode == ExecutionMode.KILL_SWITCH
        assert manager.snapshot().compliance_code == "ACCOUNT_STATE_MISSING"

        command = {"command": "SET_MODE", "mode": "SAFE", "reason": "integration-test"}
        redis_client.publish(channel, json.dumps(command))

        _wait_until(
            lambda: manager.process_once(now=10.5) or bool(handled_commands),
            timeout=2.0,
            interval=0.02,
        )

        assert handled_commands == [command]
        assert manager.snapshot().mode == ExecutionMode.KILL_SWITCH
        assert manager.snapshot().compliance_code == "ACCOUNT_STATE_MISSING"

        stored = redis_client.get(state_key)
        assert stored is not None
        payload = json.loads(stored)
        assert payload["event"] == "MODE_CHANGED"
        assert payload["mode"] == "KILL_SWITCH"
        assert payload["compliance_code"] == "ACCOUNT_STATE_MISSING"

        kill_switch = redis_client.get(kill_switch_key)
        assert kill_switch is not None
        assert json.loads(kill_switch)["active"] is True
    finally:
        manager.close()
        redis_client.delete(
            state_key,
            account_key,
            risk_key,
            news_key,
            heartbeat_key,
            orchestrator_heartbeat_key,
            kill_switch_key,
        )


@pytest.mark.integration
def test_orchestrator_compliance_tick_reads_redis_snapshots(redis_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    suffix = uuid.uuid4().hex
    channel = f"wolf15:test:orchestrator:commands:{suffix}"
    state_key = f"wolf15:test:orchestrator:state:{suffix}"
    account_key = f"wolf15:test:orchestrator:account:{suffix}"
    risk_key = f"wolf15:test:orchestrator:risk:{suffix}"
    news_key = f"wolf15:test:orchestrator:news:{suffix}"
    heartbeat_key = f"wolf15:test:orchestrator:heartbeat:{suffix}"
    orchestrator_heartbeat_key = f"wolf15:test:orchestrator:self-heartbeat:{suffix}"
    kill_switch_key = f"wolf15:test:orchestrator:kill-switch:{suffix}"

    monkeypatch.setenv("ORCHESTRATOR_CHANNEL", channel)
    monkeypatch.setenv("ORCHESTRATOR_STATE_KEY", state_key)
    monkeypatch.setenv("ORCHESTRATOR_ACCOUNT_STATE_KEY", account_key)
    monkeypatch.setenv("ORCHESTRATOR_TRADE_RISK_KEY", risk_key)
    monkeypatch.setattr("services.orchestrator.state_manager._NEWS_LOCK_STATE_KEY", news_key)
    monkeypatch.setattr("services.orchestrator.state_manager.HEARTBEAT_INGEST", heartbeat_key)
    monkeypatch.setattr(
        "services.orchestrator.state_manager.HEARTBEAT_ORCHESTRATOR",
        orchestrator_heartbeat_key,
    )
    monkeypatch.setattr("services.orchestrator.state_manager.KILL_SWITCH", kill_switch_key)

    redis_client.set(
        account_key,
        json.dumps(
            {
                "balance": 10_000,
                "equity": 9_700,
                "compliance_mode": True,
                "daily_dd_percent": 4.6,
                "max_daily_dd_percent": 5.0,
            }
        ),
    )
    redis_client.set(risk_key, json.dumps({"risk_percent": 1.0}))

    manager = StateManager(redis_client=_RedisAdapter(redis_client))  # type: ignore[arg-type]
    manager.configure_intervals(compliance_interval_sec=1.0, heartbeat_interval_sec=300.0)

    try:
        manager.process_once(now=10.0)

        snap = manager.snapshot()
        assert snap.mode == ExecutionMode.SAFE
        assert snap.compliance_code == "DAILY_DD_NEAR_LIMIT"

        stored = redis_client.get(state_key)
        assert stored is not None
        payload = json.loads(stored)
        assert payload["event"] == "MODE_CHANGED"
        assert payload["mode"] == "SAFE"
    finally:
        manager.close()
        redis_client.delete(
            state_key,
            account_key,
            risk_key,
            news_key,
            heartbeat_key,
            orchestrator_heartbeat_key,
            kill_switch_key,
        )
