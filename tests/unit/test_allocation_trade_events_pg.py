from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
async def test_record_trade_event_updates_status_and_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    import api.allocation_router as ar

    trade_id = "T-EVENT-1"
    trade_ledger = ar._trade_ledger  # pyright: ignore[reportPrivateUsage]
    trade_ledger[trade_id] = {
        "trade_id": trade_id,
        "signal_id": "SIG-1",
        "account_id": "ACC-1",
        "pair": "EURUSD",
        "direction": "BUY",
        "status": "PENDING",
        "risk_mode": "FIXED",
        "total_risk_percent": 1.0,
        "total_risk_amount": 100.0,
        "legs": [],
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }

    monkeypatch.setattr(ar, "_redis_set", AsyncMock(return_value=True))
    persist_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(ar, "_persist_trade_write_through", persist_mock)
    monkeypatch.setattr(ar, "_journal_service", Mock(on_trade_closed=Mock()))

    req = ar.TradeLifecycleEventRequest(
        trade_id=trade_id,
        event_type="ORDER_FILLED",
        source="EA",
        fill_price=1.1111,
    )

    response = await ar.record_trade_lifecycle_event(req)

    assert response["status"] == "OPEN"
    assert trade_ledger[trade_id]["status"] == "OPEN"
    assert persist_mock.await_count == 1


@pytest.mark.asyncio
async def test_record_trade_event_expired_marks_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    import api.allocation_router as ar

    trade_id = "T-EVENT-2"
    trade_ledger = ar._trade_ledger  # pyright: ignore[reportPrivateUsage]
    trade_ledger[trade_id] = {
        "trade_id": trade_id,
        "signal_id": "SIG-2",
        "account_id": "ACC-2",
        "pair": "GBPUSD",
        "direction": "SELL",
        "status": "PENDING",
        "risk_mode": "FIXED",
        "total_risk_percent": 1.0,
        "total_risk_amount": 100.0,
        "legs": [],
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }

    monkeypatch.setattr(ar, "_redis_set", AsyncMock(return_value=True))
    monkeypatch.setattr(ar, "_persist_trade_write_through", AsyncMock(return_value=None))

    closed_hook = Mock()
    monkeypatch.setattr(ar, "_journal_service", Mock(on_trade_closed=closed_hook))  # noqa: F821

    req = ar.TradeLifecycleEventRequest(
        trade_id=trade_id,
        event_type="ORDER_EXPIRED",
        source="EA",
        reason="TTL_EXPIRED",
    )

    response = await ar.record_trade_lifecycle_event(req)

    assert response["status"] == "CANCELLED"
    assert trade_ledger[trade_id]["status"] == "CANCELLED"
    assert "closed_at" in trade_ledger[trade_id]
    closed_hook.assert_called_once()


@pytest.mark.asyncio
async def test_record_trade_event_replay_safe_by_execution_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    import api.allocation_router as ar

    trade_id = "T-EVENT-3"
    trade_ledger = ar._trade_ledger  # pyright: ignore[reportPrivateUsage]
    trade_ledger[trade_id] = {
        "trade_id": trade_id,
        "signal_id": "SIG-3",
        "account_id": "ACC-3",
        "pair": "EURUSD",
        "direction": "BUY",
        "status": "PENDING",
        "risk_mode": "FIXED",
        "total_risk_percent": 1.0,
        "total_risk_amount": 100.0,
        "legs": [],
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }

    monkeypatch.setattr(ar, "_redis_set", AsyncMock(return_value=True))
    monkeypatch.setattr(ar, "_persist_trade_write_through", AsyncMock(return_value=True))
    monkeypatch.setattr(ar, "_enqueue_outbox_atomic", AsyncMock(return_value="1-1"))
    monkeypatch.setattr(ar, "_journal_service", Mock(on_trade_closed=Mock()))

    req = ar.TradeLifecycleEventRequest(
        trade_id=trade_id,
        event_type="ORDER_FILLED",
        source="EA",
        execution_intent_id="intent-abc-1",
    )

    first = await ar.record_trade_lifecycle_event(req)
    second = await ar.record_trade_lifecycle_event(req)

    assert first["status"] == "OPEN"
    assert second["status"] == "OPEN"
    assert second["execution_intent_id"] == "intent-abc-1"
