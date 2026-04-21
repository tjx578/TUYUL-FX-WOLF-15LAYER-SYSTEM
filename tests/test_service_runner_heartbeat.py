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
