from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

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

    await worker._mark_db_retry(event, "publish failed")  # pyright: ignore[reportPrivateUsage]

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

    ok, err = await worker._deliver_event(event)  # pyright: ignore[reportPrivateUsage]

    assert ok is True
    assert err is None
    assert called["topic"] == "trade_intended"
    assert called["payload"]["trade_id"] == "T-2"
