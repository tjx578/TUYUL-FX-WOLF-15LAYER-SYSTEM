from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import orjson
import pytest

from core.redis_keys import HEARTBEAT_INGEST_PROCESS, HEARTBEAT_INGEST_PROVIDER


@pytest.mark.asyncio
async def test_process_heartbeat_publishes_ws_reason_while_disconnected(monkeypatch: pytest.MonkeyPatch) -> None:
    import ingest.service_metrics as service_metrics_module
    import ingest.service_runner as service_runner_module

    shutdown_event = asyncio.Event()
    fake_redis = SimpleNamespace(set=AsyncMock())
    fake_ws_feed = SimpleNamespace(
        is_connected=False,
        last_disconnect_reason="not_leader:held_by=replica-2",
    )

    monkeypatch.setattr(
        service_runner_module,
        "build_runtime_snapshot",
        lambda ws_connected: {
            "ingest_state": "DEGRADED_REST_FALLBACK",
            "market_data_mode": "REST_DEGRADED",
            "startup_mode": "warmup",
            "ready": False,
            "degraded": True,
            "ws_connected": ws_connected,
            "rest_fallback_active": True,
            "producer_present": False,
            "producer_fresh": False,
            "symbols_ready": 0,
            "symbols_total": 30,
        },
    )
    monkeypatch.setattr(service_runner_module, "emit_ingest_runtime_metrics", lambda connected: None)
    monkeypatch.setattr(service_runner_module, "update_producer_health", lambda connected: None)
    monkeypatch.setattr(service_runner_module, "producer_fresh", lambda: False)
    monkeypatch.setattr(service_metrics_module, "fresh_pair_count", lambda: 0)
    monkeypatch.setattr(service_metrics_module, "producer_last_heartbeat_ts", time.time())

    async def stop_after_one_iteration(_: float) -> None:
        shutdown_event.set()

    monkeypatch.setattr(service_runner_module.asyncio, "sleep", stop_after_one_iteration)

    await service_runner_module._producer_heartbeat_loop(fake_ws_feed, cast(Any, fake_redis), shutdown_event)

    assert fake_redis.set.await_count == 1
    key, payload_raw = fake_redis.set.await_args.args[:2]
    assert key == HEARTBEAT_INGEST_PROCESS
    payload = orjson.loads(payload_raw)
    assert payload["last_ws_disconnect_reason"] == "not_leader:held_by=replica-2"

    written_keys = [call.args[0] for call in fake_redis.set.await_args_list]
    assert HEARTBEAT_INGEST_PROVIDER not in written_keys


@pytest.mark.asyncio
async def test_process_heartbeat_transitions_from_degraded_to_live_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ingest.service_metrics as service_metrics_module
    import ingest.service_runner as service_runner_module
    from state.heartbeat_classifier import IngestHealthState, read_ingest_health

    class FakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}
            self.writes: list[tuple[str, dict[str, Any]]] = []

        async def set(self, key: str, value: str) -> None:
            self.values[key] = value
            self.writes.append((key, orjson.loads(value)))

        async def get(self, key: str) -> str | None:
            return self.values.get(key)

    shutdown_event = asyncio.Event()
    fake_redis = FakeRedis()
    fake_ws_feed = SimpleNamespace(
        is_connected=False,
        last_disconnect_reason="startup_rest_fallback",
    )

    monkeypatch.setattr(service_metrics_module, "startup_mode", "stale_cache")
    monkeypatch.setattr(service_metrics_module, "ingest_ready", False)
    monkeypatch.setattr(service_metrics_module, "ingest_degraded", True)
    monkeypatch.setattr(service_metrics_module, "enabled_symbol_count", 30)
    monkeypatch.setattr(service_metrics_module, "producer_present", False)
    monkeypatch.setattr(service_metrics_module, "producer_last_heartbeat_ts", 0.0)
    monkeypatch.setattr(service_metrics_module, "pair_last_tick_ts", {})
    monkeypatch.setattr(service_metrics_module, "_last_logged_ingest_state", "")
    monkeypatch.setattr(service_metrics_module, "_last_logged_reason", "")
    monkeypatch.setattr(service_metrics_module, "_last_logged_blocked_by", "")

    sleep_count = {"value": 0}

    async def advance_loop(_: float) -> None:
        sleep_count["value"] += 1
        if sleep_count["value"] == 1:
            fake_ws_feed.is_connected = True
            fake_ws_feed.last_disconnect_reason = None
            now = service_metrics_module.time()
            service_metrics_module.pair_last_tick_ts = {f"PAIR{i}": now for i in range(26)}
            return
        shutdown_event.set()

    monkeypatch.setattr(service_runner_module.asyncio, "sleep", advance_loop)

    await service_runner_module._producer_heartbeat_loop(fake_ws_feed, cast(Any, fake_redis), shutdown_event)

    process_writes = [payload for key, payload in fake_redis.writes if key == HEARTBEAT_INGEST_PROCESS]
    assert len(process_writes) == 2
    assert process_writes[0]["ingest_state"] == "DEGRADED_REST_FALLBACK"
    assert process_writes[0]["ready"] is False
    assert process_writes[0]["market_data_mode"] == "REST_DEGRADED"
    assert process_writes[1]["ingest_state"] == "LIVE"
    assert process_writes[1]["ready"] is True
    assert process_writes[1]["degraded"] is False
    assert process_writes[1]["symbols_ready"] == 26
    assert process_writes[1]["fresh_pair_target"] == 26
    assert process_writes[1]["market_data_mode"] == "WS_PRIMARY"

    provider_writes = [payload for key, payload in fake_redis.writes if key == HEARTBEAT_INGEST_PROVIDER]
    assert len(provider_writes) == 1
    assert provider_writes[0]["ws_connected"] is True

    ingest_health = await read_ingest_health(fake_redis)
    assert ingest_health.state == IngestHealthState.HEALTHY
    assert ingest_health.process.state.value == "ALIVE"
    assert ingest_health.provider.state.value == "ALIVE"
