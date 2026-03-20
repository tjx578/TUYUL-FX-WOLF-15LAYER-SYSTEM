"""Integration tests for orchestrator Redis pub/sub flow.

These tests require a reachable Redis instance and are skipped automatically
when Redis is unavailable.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from typing import Any

import pytest

from infrastructure.redis_url import get_redis_url
from services.orchestrator.execution_mode import ExecutionMode
from services.orchestrator.state_manager import StateManager

redis = pytest.importorskip("redis")


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

    monkeypatch.setenv("ORCHESTRATOR_CHANNEL", channel)
    monkeypatch.setenv("ORCHESTRATOR_STATE_KEY", state_key)
    monkeypatch.setenv("ORCHESTRATOR_ACCOUNT_STATE_KEY", account_key)
    monkeypatch.setenv("ORCHESTRATOR_TRADE_RISK_KEY", risk_key)

    manager = StateManager(redis_client=_RedisAdapter(redis_client))
    manager.start_listener()

    try:
        redis_client.publish(
            channel,
            json.dumps({"command": "SET_MODE", "mode": "SAFE", "reason": "integration-test"}),
        )

        manager.process_once(now=0.2)

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
        redis_client.delete(state_key, account_key, risk_key)


@pytest.mark.integration
def test_orchestrator_compliance_tick_reads_redis_snapshots(redis_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    suffix = uuid.uuid4().hex
    channel = f"wolf15:test:orchestrator:commands:{suffix}"
    state_key = f"wolf15:test:orchestrator:state:{suffix}"
    account_key = f"wolf15:test:orchestrator:account:{suffix}"
    risk_key = f"wolf15:test:orchestrator:risk:{suffix}"

    monkeypatch.setenv("ORCHESTRATOR_CHANNEL", channel)
    monkeypatch.setenv("ORCHESTRATOR_STATE_KEY", state_key)
    monkeypatch.setenv("ORCHESTRATOR_ACCOUNT_STATE_KEY", account_key)
    monkeypatch.setenv("ORCHESTRATOR_TRADE_RISK_KEY", risk_key)

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

    manager = StateManager(redis_client=_RedisAdapter(redis_client))
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
        redis_client.delete(state_key, account_key, risk_key)
