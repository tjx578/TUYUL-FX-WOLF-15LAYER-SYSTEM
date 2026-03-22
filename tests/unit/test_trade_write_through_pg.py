from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from storage.trade_write_through import persist_trade_snapshot


@pytest.mark.asyncio
async def test_persist_trade_snapshot_skips_when_pg_unavailable() -> None:
    pg = cast(Any, SimpleNamespace(is_available=False, execute=AsyncMock(return_value="OK")))
    ok = await persist_trade_snapshot({"trade_id": "T-1"}, pg=pg)
    assert ok is False
    pg.execute.assert_not_called()


@pytest.mark.asyncio
async def test_persist_trade_snapshot_writes_trade_and_event() -> None:
    pg = cast(Any, SimpleNamespace(is_available=True, execute=AsyncMock(return_value="OK")))
    trade: dict[str, Any] = {
        "trade_id": "T-1",
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

    ok = await persist_trade_snapshot(
        trade,
        event_type="ORDER_PLACED",
        event_payload={"source": "MANUAL"},
        pg=pg,
    )

    assert ok is True
    assert pg.execute.await_count == 3


@pytest.mark.asyncio
async def test_persist_trade_snapshot_uses_transaction_when_available() -> None:
    pg = cast(
        Any,
        SimpleNamespace(
            is_available=True,
            execute=AsyncMock(return_value="OK"),
            execute_in_transaction=AsyncMock(return_value=["OK", "OK", "OK"]),
        ),
    )
    trade: dict[str, Any] = {
        "trade_id": "T-TX-1",
        "signal_id": "SIG-TX-1",
        "account_id": "ACC-TX-1",
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

    ok = await persist_trade_snapshot(
        trade,
        event_type="ORDER_PLACED",
        event_payload={"source": "MANUAL", "execution_intent_id": "intent-1"},
        pg=pg,
    )

    assert ok is True
    assert pg.execute_in_transaction.await_count == 1
    pg.execute.assert_not_called()


@pytest.mark.asyncio
async def test_trade_ledger_get_trade_async_falls_back_to_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.trade_ledger import TradeLedger

    class _TradeObj:
        trade_id = "T-2"
        pair = "GBPUSD"

    fake_redis = AsyncMock()
    fake_redis.get = AsyncMock(return_value=None)

    async def _fake_get_client():
        return fake_redis

    row: dict[str, Any] = {
        "trade_id": "T-2",
        "signal_id": "SIG-2",
        "account_id": "ACC-2",
        "pair": "GBPUSD",
        "direction": "SELL",
        "status": "PENDING",
        "risk_mode": "FIXED",
        "total_risk_percent": 0.5,
        "total_risk_amount": 50.0,
        "pnl": None,
        "close_reason": None,
        "legs": [],
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "closed_at": None,
    }

    monkeypatch.setattr("dashboard.trade_ledger.get_client", _fake_get_client)
    monkeypatch.setattr("dashboard.trade_ledger.pg_client.fetchrow", AsyncMock(return_value=row))

    def _fake_from_dict(self: Any, data: Any) -> Any:
        return _TradeObj()

    monkeypatch.setattr(TradeLedger, "_from_dict", _fake_from_dict)

    ledger = TradeLedger()

    trade = await ledger.get_trade_async("T-2")

    assert trade is not None
    assert trade.trade_id == "T-2"
    assert trade.pair == "GBPUSD"
