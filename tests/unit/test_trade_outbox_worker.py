from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from storage.trade_outbox_worker import OutboxEvent, TradeOutboxWorker


@pytest.mark.asyncio
async def test_mark_db_retry_increments_attempts() -> None:
    pg = cast(
        Any,
        SimpleNamespace(
            is_available=True,
            fetchrow=AsyncMock(return_value={"attempts": 2}),
            execute=AsyncMock(return_value="OK"),
        ),
    )

    worker = TradeOutboxWorker(pg=pg)
    event = OutboxEvent(
        outbox_id="obx-1",
        trade_id="T-1",
        event_type="ORDER_PLACED",
        topic="trade_confirmed",
        payload={"trade_id": "T-1"},
    )

    await worker._mark_db_retry(event, "publish failed")

    assert pg.fetchrow.await_count == 1
    assert pg.execute.await_count == 1


@pytest.mark.asyncio
async def test_deliver_event_calls_ws_publisher(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = TradeOutboxWorker()
    called: dict[str, Any] = {}

    async def _fake_publish(topic: str, payload: dict[str, Any]) -> None:
        called["topic"] = topic
        called["payload"] = payload

    monkeypatch.setattr("api.ws_routes.publish_live_update", _fake_publish)

    event = OutboxEvent(
        outbox_id="obx-2",
        trade_id="T-2",
        event_type="TRADE_INTENDED",
        topic="trade_intended",
        payload={"trade": {"trade_id": "T-2", "status": "INTENDED"}},
    )

    ok, err = await worker._deliver_event(event)

    assert ok is True
    assert err is None
    assert called["topic"] == "trade_intended"
    assert called["payload"]["trade_id"] == "T-2"


@pytest.mark.asyncio
async def test_run_retries_ensure_group_on_redis_failure() -> None:
    """Worker retries _ensure_group each loop iteration until Redis is reachable."""
    fake_redis = AsyncMock()
    # First call: connection refused; second call: succeeds (BUSYGROUP = already exists)
    fake_redis.xgroup_create = AsyncMock(
        side_effect=[
            ConnectionError("Error 111 connecting to localhost:6379. Connection refused."),
            Exception("BUSYGROUP Consumer Group name already exists"),
        ]
    )
    fake_redis.xreadgroup = AsyncMock(return_value=[])

    worker = TradeOutboxWorker(poll_interval_sec=0.01)

    iteration_count = 0

    async def _run_limited(self: Any) -> None:
        """Run the worker but stop after group becomes ready."""
        nonlocal iteration_count
        redis_client: Any = None

        while not self._stopped.is_set():
            iteration_count += 1
            if iteration_count > 5:
                # Safety: stop the loop to avoid infinite iteration
                self._stopped.set()
                break

            if redis_client is None:
                redis_client = fake_redis

            if not self._group_ready:
                try:
                    await self._ensure_group(redis_client)
                    self._group_ready = True
                except Exception:
                    await asyncio.sleep(0.001)
                    continue

            # Group is ready — stop
            self._stopped.set()

    with patch.object(TradeOutboxWorker, "run", _run_limited):
        await worker.run()

    # xgroup_create should have been called twice (failed once, succeeded once)
    assert fake_redis.xgroup_create.await_count == 2
    assert worker._group_ready is True


@pytest.mark.asyncio
async def test_ensure_group_raises_on_non_busygroup_error() -> None:
    """_ensure_group re-raises non-BUSYGROUP exceptions so the caller can retry."""
    fake_redis = AsyncMock()
    fake_redis.xgroup_create = AsyncMock(side_effect=ConnectionError("Connection refused"))

    worker = TradeOutboxWorker()

    with pytest.raises(ConnectionError, match="Connection refused"):
        await worker._ensure_group(fake_redis)


@pytest.mark.asyncio
async def test_ensure_group_ignores_busygroup_error() -> None:
    """_ensure_group silently succeeds when the group already exists."""
    fake_redis = AsyncMock()
    fake_redis.xgroup_create = AsyncMock(side_effect=Exception("BUSYGROUP Consumer Group name already exists"))

    worker = TradeOutboxWorker()

    # Should not raise
    await worker._ensure_group(fake_redis)


@pytest.mark.asyncio
async def test_run_stops_on_nonrecoverable_redis_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = TradeOutboxWorker(poll_interval_sec=0.01)

    async def _boom() -> Any:
        raise RuntimeError("Redis configuration missing on Railway")

    monkeypatch.setattr("storage.trade_outbox_worker.get_client", _boom)

    await asyncio.wait_for(worker.run(), timeout=0.5)

    # Worker exits immediately instead of looping retries.
    assert worker._stopped.is_set() is False
