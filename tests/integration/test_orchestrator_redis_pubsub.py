"""Integration tests for orchestrator Redis pub/sub flow.

These tests require a reachable Redis instance and are skipped automatically
when Redis is unavailable.
"""

from __future__ import annotations

import contextlib
import json
import time
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from infrastructure.redis_url import get_redis_url
from services.orchestrator import state_manager
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

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        return self._client.eval(script, numkeys, *keys_and_args)


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
def test_orchestrator_receives_set_mode_command_via_redis(
    redis_client: Any, monkeypatch: pytest.MonkeyPatch, isolated_governance_keys: float
) -> None:
    suffix = uuid.uuid4().hex
    channel = f"wolf15:test:orchestrator:commands:{suffix}"
    state_key = f"wolf15:test:orchestrator:state:{suffix}"
    account_key = f"wolf15:test:orchestrator:account:{suffix}"
    risk_key = f"wolf15:test:orchestrator:risk:{suffix}"
    lease_key = f"wolf15:test:orchestrator:lease:{suffix}"
    fence_key = f"wolf15:test:orchestrator:fence:{suffix}"
    ingest_heartbeat_key = f"wolf15:test:ingest:heartbeat:{suffix}"
    orchestrator_heartbeat_key = f"wolf15:test:orchestrator:heartbeat:{suffix}"
    news_lock_key = f"wolf15:test:news-lock:{suffix}"
    kill_switch_key = f"wolf15:test:kill-switch:{suffix}"

    monkeypatch.setenv("ORCHESTRATOR_CHANNEL", channel)
    monkeypatch.setenv("ORCHESTRATOR_STATE_KEY", state_key)
    monkeypatch.setenv("ORCHESTRATOR_ACCOUNT_STATE_KEY", account_key)
    monkeypatch.setenv("ORCHESTRATOR_TRADE_RISK_KEY", risk_key)
    monkeypatch.setenv("ORCHESTRATOR_LEASE_KEY", lease_key)
    monkeypatch.setenv("ORCHESTRATOR_FENCE_COUNTER_KEY", fence_key)
    monkeypatch.setattr("services.orchestrator.state_manager.HEARTBEAT_INGEST", ingest_heartbeat_key)
    monkeypatch.setattr("services.orchestrator.state_manager.HEARTBEAT_ORCHESTRATOR", orchestrator_heartbeat_key)
    monkeypatch.setattr("services.orchestrator.state_manager._NEWS_LOCK_STATE_KEY", news_lock_key)
    monkeypatch.setattr("services.orchestrator.state_manager.KILL_SWITCH", kill_switch_key)
    monkeypatch.setattr("services.orchestrator.state_manager.is_forex_market_open", lambda: True)

    # Keep the compliance tick valid and non-blocking so this test isolates
    # signed command transport. Without authoritative account state, the
    # fail-closed evaluator correctly enters KILL_SWITCH before consuming SAFE.
    redis_client.set(
        account_key,
        json.dumps(
            {
                "balance": 10_000,
                "equity": 9_990,
                "compliance_mode": True,
                "daily_dd_percent": 1.0,
                "max_daily_dd_percent": 5.0,
                "total_dd_percent": 2.0,
                "max_total_dd_percent": 10.0,
            }
        ),
    )
    redis_client.set(risk_key, json.dumps({"risk_percent": 1.0}))
    redis_client.set(ingest_heartbeat_key, json.dumps({"producer": "test", "ts": time.time()}))

    redis_client.set(
        account_key,
        json.dumps(
            {
                "balance": 10_000,
                "equity": 10_000,
                "compliance_mode": True,
                "daily_dd_percent": 0.0,
                "max_daily_dd_percent": 5.0,
                "max_risk_per_trade_percent": 1.0,
            }
        ),
    )
    redis_client.set(risk_key, json.dumps({"risk_percent": 0.5}))
    manager = StateManager(redis_client=_RedisAdapter(redis_client))  # type: ignore[arg-type]
    assert manager._ownership.acquire()  # noqa: SLF001
    manager.configure_intervals(compliance_interval_sec=1.0, heartbeat_interval_sec=300.0)
    manager.start_listener()

    try:
        # Exercise a real compliance tick with valid authoritative snapshots first.
        manager.process_once(now=isolated_governance_keys)
        assert manager.snapshot().compliance_code == "OK"
        redis_client.publish(
            channel,
            json.dumps({"command": "SET_MODE", "mode": "SAFE", "reason": "integration-test"}),
        )

        _wait_until(
            lambda: (
                manager.process_once(now=isolated_governance_keys + 0.1)
                or manager.snapshot().mode == ExecutionMode.SAFE
            ),
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
        # A subsequent compliance tick must not replace SAFE with a missing-data veto.
        manager.process_once(now=isolated_governance_keys + 1.0)
        assert manager.snapshot().mode == ExecutionMode.SAFE
        assert manager.snapshot().compliance_code == "EXTERNAL_COMMAND"
    finally:
        manager.close()
        manager._ownership.release()  # noqa: SLF001
        redis_client.delete(
            state_key,
            account_key,
            risk_key,
            lease_key,
            fence_key,
            ingest_heartbeat_key,
            orchestrator_heartbeat_key,
            news_lock_key,
            kill_switch_key,
        )


@pytest.fixture(autouse=True)
def isolated_governance_keys(redis_client: Any, monkeypatch: pytest.MonkeyPatch):
    fixed_now = 1_800_000_000.0
    monkeypatch.setattr(state_manager, "time", SimpleNamespace(time=lambda: fixed_now, sleep=time.sleep))
    monkeypatch.setattr(state_manager, "is_forex_market_open", lambda: True)
    monkeypatch.delenv("ORCHESTRATOR_COMMAND_SECRET", raising=False)
    keys = []
    for name in ("KILL_SWITCH", "HEARTBEAT_ORCHESTRATOR", "HEARTBEAT_INGEST", "_NEWS_LOCK_STATE_KEY"):
        key = f"wolf15:test:orchestrator:{uuid.uuid4().hex}:{name}"
        keys.append(key)
        monkeypatch.setattr(state_manager, name, key)
    redis_client.set(state_manager.HEARTBEAT_INGEST, json.dumps({"ts": fixed_now}))
    yield fixed_now
    redis_client.delete(*keys)


@pytest.mark.integration
def test_missing_account_kill_switch_cannot_be_cleared_by_redis_command(
    redis_client: Any, monkeypatch: pytest.MonkeyPatch
):
    suffix = uuid.uuid4().hex
    keys = {
        name: f"wolf15:test:orchestrator:{suffix}:{name}"
        for name in (
            "ORCHESTRATOR_CHANNEL",
            "ORCHESTRATOR_STATE_KEY",
            "ORCHESTRATOR_ACCOUNT_STATE_KEY",
            "ORCHESTRATOR_TRADE_RISK_KEY",
        )
    }
    for name, key in keys.items():
        monkeypatch.setenv(name, key)
    manager = StateManager(redis_client=_RedisAdapter(redis_client))
    manager.start_listener()
    try:
        manager.process_once(now=10.0)
        assert manager.snapshot().mode == ExecutionMode.KILL_SWITCH
        assert manager.snapshot().compliance_code == "ACCOUNT_STATE_MISSING"
        # Confirm delivery through the real subscriber before checking the veto.
        observed = []
        original = manager._handle_channel_message

        def handle(payload):
            if payload.get("command") == "SET_MODE":
                observed.append(payload)
            original(payload)

        monkeypatch.setattr(manager, "_handle_channel_message", handle)
        redis_client.publish(keys["ORCHESTRATOR_CHANNEL"], json.dumps({"command": "SET_MODE", "mode": "SAFE"}))
        _wait_until(lambda: manager.process_once(now=10.0) or bool(observed))
        assert manager.snapshot().mode == ExecutionMode.KILL_SWITCH
        assert manager.snapshot().compliance_code == "ACCOUNT_STATE_MISSING"
    finally:
        manager.close()
        redis_client.delete(*keys.values())


@pytest.mark.integration
def test_orchestrator_compliance_tick_reads_redis_snapshots(redis_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    suffix = uuid.uuid4().hex
    channel = f"wolf15:test:orchestrator:commands:{suffix}"
    state_key = f"wolf15:test:orchestrator:state:{suffix}"
    account_key = f"wolf15:test:orchestrator:account:{suffix}"
    risk_key = f"wolf15:test:orchestrator:risk:{suffix}"
    lease_key = f"wolf15:test:orchestrator:lease:{suffix}"
    fence_key = f"wolf15:test:orchestrator:fence:{suffix}"
    ingest_heartbeat_key = f"wolf15:test:ingest:heartbeat:{suffix}"
    orchestrator_heartbeat_key = f"wolf15:test:orchestrator:heartbeat:{suffix}"
    news_lock_key = f"wolf15:test:news-lock:{suffix}"
    kill_switch_key = f"wolf15:test:kill-switch:{suffix}"

    monkeypatch.setenv("ORCHESTRATOR_CHANNEL", channel)
    monkeypatch.setenv("ORCHESTRATOR_STATE_KEY", state_key)
    monkeypatch.setenv("ORCHESTRATOR_ACCOUNT_STATE_KEY", account_key)
    monkeypatch.setenv("ORCHESTRATOR_TRADE_RISK_KEY", risk_key)
    monkeypatch.setenv("ORCHESTRATOR_LEASE_KEY", lease_key)
    monkeypatch.setenv("ORCHESTRATOR_FENCE_COUNTER_KEY", fence_key)
    monkeypatch.setattr("services.orchestrator.state_manager.HEARTBEAT_INGEST", ingest_heartbeat_key)
    monkeypatch.setattr("services.orchestrator.state_manager.HEARTBEAT_ORCHESTRATOR", orchestrator_heartbeat_key)
    monkeypatch.setattr("services.orchestrator.state_manager._NEWS_LOCK_STATE_KEY", news_lock_key)
    monkeypatch.setattr("services.orchestrator.state_manager.KILL_SWITCH", kill_switch_key)
    monkeypatch.setattr("services.orchestrator.state_manager.is_forex_market_open", lambda: True)

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
    redis_client.set(ingest_heartbeat_key, json.dumps({"producer": "test", "ts": time.time()}))

    manager = StateManager(redis_client=_RedisAdapter(redis_client))  # type: ignore[arg-type]
    assert manager._ownership.acquire()  # noqa: SLF001
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
        manager._ownership.release()  # noqa: SLF001
        redis_client.delete(
            state_key,
            account_key,
            risk_key,
            lease_key,
            fence_key,
            ingest_heartbeat_key,
            orchestrator_heartbeat_key,
            news_lock_key,
            kill_switch_key,
        )
