from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_list_pending_outbox_returns_items(monkeypatch: pytest.MonkeyPatch) -> None:
    import api.outbox_router as orouter

    monkeypatch.setattr(orouter.pg_client, "_pool", object())
    monkeypatch.setattr(
        orouter.pg_client,
        "fetch",
        AsyncMock(
            return_value=[
                {
                    "outbox_id": "obx-1",
                    "outbox_key": "k-1",
                    "trade_id": "T-1",
                    "event_type": "ORDER_PLACED",
                    "topic": "trade_confirmed",
                    "status": "PENDING",
                    "attempts": 1,
                    "last_error": "x",
                    "next_attempt_at": datetime.now(UTC),
                    "published_at": None,
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                }
            ]
        ),
    )

    res = await orouter.list_pending_outbox(limit=100, status_filter="PENDING")

    assert res["count"] == 1
    assert res["items"][0]["outbox_id"] == "obx-1"


@pytest.mark.asyncio
async def test_retry_outbox_event_marks_published(monkeypatch: pytest.MonkeyPatch) -> None:
    import api.outbox_router as orouter

    monkeypatch.setattr(orouter.pg_client, "_pool", object())
    monkeypatch.setattr(
        orouter.pg_client,
        "fetchrow",
        AsyncMock(
            return_value={
                "outbox_id": "obx-2",
                "trade_id": "T-2",
                "event_type": "TRADE_INTENDED",
                "topic": "trade_intended",
                "payload": {"trade": {"trade_id": "T-2", "status": "INTENDED"}},
                "status": "PENDING",
                "attempts": 0,
            }
        ),
    )
    exec_mock = AsyncMock(return_value="OK")
    monkeypatch.setattr(orouter.pg_client, "execute", exec_mock)

    called: dict[str, Any] = {}

    async def _fake_publish(topic: str, payload: dict[str, object]) -> None:
        called["topic"] = topic
        called["payload"] = payload

    monkeypatch.setattr("api.ws_routes.publish_live_update", _fake_publish)

    out = await orouter.retry_outbox_event("obx-2")

    assert out["replayed"] is True
    assert out["status"] == "PUBLISHED"
    assert called["topic"] == "trade_intended"
    assert cast(dict[str, Any], called["payload"])["trade_id"] == "T-2"
    assert exec_mock.await_count == 1
