from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_list_pending_outbox_returns_items(monkeypatch: pytest.MonkeyPatch) -> None:
    import api.outbox_router as orouter

    monkeypatch.setattr(orouter.pg_client, "_pool", object())
    fetch_mock = AsyncMock(
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
    )
    monkeypatch.setattr(
        orouter.pg_client,
        "fetch",
        fetch_mock,
    )

    res = await orouter.list_pending_outbox(
        limit=100,
        status_filter="PENDING",
        trade_id="T-1",
        event_type="ORDER_PLACED",
    )

    assert res["count"] == 1
    assert res["items"][0]["outbox_id"] == "obx-1"
    assert res["trade_id"] == "T-1"
    assert res["event_type"] == "ORDER_PLACED"
    assert fetch_mock.await_count == 1
    fetch_call = fetch_mock.await_args
    assert fetch_call is not None
    assert fetch_call.args[1:] == ("PENDING", "T-1", "ORDER_PLACED", 100)


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


@pytest.mark.asyncio
async def test_get_outbox_detail_returns_single_row(monkeypatch: pytest.MonkeyPatch) -> None:
    import api.outbox_router as orouter

    monkeypatch.setattr(orouter.pg_client, "_pool", object())
    monkeypatch.setattr(
        orouter.pg_client,
        "fetchrow",
        AsyncMock(
            return_value={
                "outbox_id": "obx-9",
                "outbox_key": "k-9",
                "trade_id": "T-9",
                "event_type": "ORDER_FILLED",
                "topic": "trade_confirmed",
                "payload": {"trade": {"trade_id": "T-9"}},
                "status": "PENDING",
                "attempts": 0,
                "last_error": None,
                "next_attempt_at": datetime.now(UTC),
                "published_at": None,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        ),
    )

    out = await orouter.get_outbox_detail("obx-9")

    assert out["outbox_id"] == "obx-9"
    assert out["trade_id"] == "T-9"
    assert cast(dict[str, Any], out["payload"])["trade"]["trade_id"] == "T-9"


@pytest.mark.asyncio
async def test_retry_outbox_batch_applies_safety_cap_and_summarizes(monkeypatch: pytest.MonkeyPatch) -> None:
    import api.outbox_router as orouter

    monkeypatch.setattr(orouter.pg_client, "_pool", object())
    fetch_mock = AsyncMock(
        return_value=[
            {
                "outbox_id": "obx-ok",
                "trade_id": "T-OK",
                "event_type": "ORDER_PLACED",
                "topic": "trade_lifecycle",
                "payload": {"trade": {"trade_id": "T-OK"}},
                "status": "PENDING",
                "attempts": 0,
            },
            {
                "outbox_id": "obx-skip",
                "trade_id": "T-SKIP",
                "event_type": "ORDER_PLACED",
                "topic": "trade_lifecycle",
                "payload": {"trade": {"trade_id": "T-SKIP"}},
                "status": "PUBLISHED",
                "attempts": 1,
            },
            {
                "outbox_id": "obx-fail",
                "trade_id": "T-FAIL",
                "event_type": "ORDER_PLACED",
                "topic": "trade_lifecycle",
                "payload": {"trade": {"trade_id": "T-FAIL"}},
                "status": "PENDING",
                "attempts": 1,
            },
        ]
    )
    monkeypatch.setattr(orouter.pg_client, "fetch", fetch_mock)

    exec_mock = AsyncMock(return_value="OK")
    monkeypatch.setattr(orouter.pg_client, "execute", exec_mock)

    async def _fake_publish(topic: str, payload: dict[str, object]) -> None:
        _ = topic
        if cast(dict[str, Any], payload).get("trade_id") == "T-FAIL":
            raise RuntimeError("boom")

    monkeypatch.setattr("api.ws_routes.publish_live_update", _fake_publish)

    out = await orouter.retry_outbox_batch(orouter.RetryOutboxBatchRequest(limit=999, status_filter="PENDING"))

    assert out["capped"] is True
    assert out["applied_limit"] == orouter.RETRY_BATCH_SAFETY_CAP
    assert out["count"] == 3
    assert out["replayed"] == 1
    assert out["failed"] == 1
    assert out["skipped"] == 1
    assert fetch_mock.await_count == 1
    fetch_call = fetch_mock.await_args
    assert fetch_call is not None
    assert fetch_call.args[1:] == (
        "PENDING",
        None,
        None,
        orouter.RETRY_BATCH_SAFETY_CAP,
    )
