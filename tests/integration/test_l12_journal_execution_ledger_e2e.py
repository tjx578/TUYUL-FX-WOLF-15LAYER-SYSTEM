from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from accounts.account_model import RiskCalculationResult, RiskSeverity
from journal.journal_repository import JournalRepository
from journal.journal_router import journal_router
from journal.journal_writer import JournalWriter
from journal.trade_journal_service import TradeJournalAutomationService


class _FakeRiskEngine:
    def calculate_lot(self, *args: object, **kwargs: object) -> RiskCalculationResult:  # noqa: ARG002
        return RiskCalculationResult(
            trade_allowed=True,
            recommended_lot=0.2,
            max_safe_lot=0.5,
            risk_used_percent=1.0,
            daily_dd_after=1.0,
            total_dd_after=1.0,
            severity=RiskSeverity.SAFE,
            reason="OK",
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_minimal_l12_to_journal_execution_ledger_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import api.allocation_router as ar

    # L12 output is treated as sole authority input contract for downstream pipeline.
    l12_signal_id = "SIG-E2E-PIPE-001"
    l12_symbol = "EURUSD"
    l12_verdict = "EXECUTE_BUY"
    l12_direction = "BUY"
    l12_entry = 1.08500
    l12_sl = 1.08000
    l12_tp1 = 1.09500
    assert l12_verdict == "EXECUTE_BUY"

    archive_dir = tmp_path / "decision_archive"
    journal_router._writer = JournalWriter(base_dir=str(archive_dir))  # pyright: ignore[reportPrivateUsage]
    journal_router._event_count = 0  # pyright: ignore[reportPrivateUsage]

    ar._trade_ledger.clear()  # pyright: ignore[reportPrivateUsage]
    ar._account_registry.clear()  # pyright: ignore[reportPrivateUsage]
    ar._account_registry["ACC-E2E-1"] = {  # pyright: ignore[reportPrivateUsage]
        "balance": 10000.0,
        "equity": 10000.0,
        "equity_high": 10000.0,
        "daily_dd_percent": 0.0,
        "total_dd_percent": 0.0,
        "open_risk_percent": 0.0,
        "open_trades": 0,
        "max_concurrent_trades": 5,
        "max_daily_dd_percent": 5.0,
        "max_total_dd_percent": 10.0,
        "compliance_mode": True,
        "system_state": "NORMAL",
        "correlation_bucket": "GREEN",
        "news_lock": False,
    }

    monkeypatch.setattr(ar, "RiskEngine", _FakeRiskEngine)
    monkeypatch.setattr(ar, "_check_stale_data", AsyncMock(return_value=None))
    monkeypatch.setattr(ar, "_runtime_take_precheck", AsyncMock(return_value=(True, None)))
    monkeypatch.setattr(ar, "_persist_trade_write_through", AsyncMock(return_value=True))
    monkeypatch.setattr(ar, "_enqueue_outbox_atomic", AsyncMock(return_value="1-0"))
    monkeypatch.setattr(ar, "_redis_set", AsyncMock(return_value=True))
    monkeypatch.setattr(ar, "_redis_get", AsyncMock(return_value=None))
    monkeypatch.setattr(ar, "_redis_hgetall", AsyncMock(return_value={}))
    monkeypatch.setattr(ar, "_journal_service", TradeJournalAutomationService())
    monkeypatch.setattr(ar, "_signal_service", Mock(publish=Mock()))

    idem_store: dict[str, str] = {}

    def _idem_set(key: str, value: str, nx: bool | None = None, ex: int | None = None):  # noqa: ARG001
        if nx and key in idem_store:
            return False
        idem_store[key] = value
        return True

    def _idem_get(key: str):
        return idem_store.get(key)

    monkeypatch.setattr("execution.idempotency_ledger.redis_client.client.set", _idem_set)
    monkeypatch.setattr("execution.idempotency_ledger.redis_client.client.get", _idem_get)

    async def _fast_atomic_confirm(trade_id: str) -> dict[str, object]:
        trade = ar._trade_ledger[trade_id]  # pyright: ignore[reportPrivateUsage]
        trade["status"] = "PENDING"
        trade["updated_at"] = datetime.now(UTC).isoformat()
        ar._trade_ledger[trade_id] = trade  # pyright: ignore[reportPrivateUsage]
        return trade

    monkeypatch.setattr(ar, "_atomic_transition_intended_to_pending", _fast_atomic_confirm)

    take_resp = await ar.take_signal(
        ar.TakeSignalRequest(
            signal_id=l12_signal_id,
            account_id="ACC-E2E-1",
            pair=l12_symbol,
            direction=l12_direction,
            entry=l12_entry,
            sl=l12_sl,
            tp=l12_tp1,
            risk_percent=1.0,
            risk_mode="FIXED",
        )
    )
    trade_id = str(take_resp["trade_id"])

    assert ar._trade_ledger[trade_id]["status"] == "INTENDED"  # pyright: ignore[reportPrivateUsage]
    assert ar._trade_ledger[trade_id]["direction"] == l12_direction  # pyright: ignore[reportPrivateUsage]

    confirm_resp = await ar.confirm_trade(ar.ConfirmTradeRequest(trade_id=trade_id))
    assert confirm_resp["status"] == "PENDING"
    assert ar._trade_ledger[trade_id]["status"] == "PENDING"  # pyright: ignore[reportPrivateUsage]

    lifecycle_resp = await ar.record_trade_lifecycle_event(
        ar.TradeLifecycleEventRequest(
            trade_id=trade_id,
            event_type="ORDER_FILLED",
            source="EA",
            order_id="ORD-E2E-1",
            fill_price=1.08510,
        )
    )
    assert lifecycle_resp["status"] == "OPEN"
    assert ar._trade_ledger[trade_id]["status"] == "OPEN"  # pyright: ignore[reportPrivateUsage]

    close_resp = await ar.close_trade(
        ar.CloseTradeRequest(
            trade_id=trade_id,
            reason="TP_HIT",
            close_price=1.09500,
            pnl=150.0,
        )
    )
    assert close_resp["status"] == "CLOSED"
    assert ar._trade_ledger[trade_id]["status"] == "CLOSED"  # pyright: ignore[reportPrivateUsage]

    repo = JournalRepository(base_dir=str(archive_dir))
    entries = repo.load_entries(date_range_days=1)

    journal_types = [str(item.get("journal_type")) for item in entries]
    assert "decision" in journal_types  # J2
    assert "reflective" in journal_types  # J4

    decision = next(item for item in entries if item.get("journal_type") == "decision")
    reflection = next(item for item in entries if item.get("journal_type") == "reflective")

    assert decision["data"]["verdict"] == l12_verdict
    assert reflection["data"]["outcome"] == "WIN"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_system_violation_still_records_j4_reflection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import api.allocation_router as ar

    l12_signal_id = "SIG-E2E-PIPE-NEG-001"
    l12_symbol = "GBPUSD"
    l12_direction = "SELL"
    l12_entry = 1.26100
    l12_sl = 1.26600
    l12_tp1 = 1.25100

    archive_dir = tmp_path / "decision_archive_neg"
    journal_router._writer = JournalWriter(base_dir=str(archive_dir))  # pyright: ignore[reportPrivateUsage]
    journal_router._event_count = 0  # pyright: ignore[reportPrivateUsage]

    ar._trade_ledger.clear()  # pyright: ignore[reportPrivateUsage]
    ar._account_registry.clear()  # pyright: ignore[reportPrivateUsage]
    ar._account_registry["ACC-E2E-NEG-1"] = {  # pyright: ignore[reportPrivateUsage]
        "balance": 10000.0,
        "equity": 10000.0,
        "equity_high": 10000.0,
        "daily_dd_percent": 0.0,
        "total_dd_percent": 0.0,
        "open_risk_percent": 0.0,
        "open_trades": 0,
        "max_concurrent_trades": 5,
        "max_daily_dd_percent": 5.0,
        "max_total_dd_percent": 10.0,
        "compliance_mode": True,
        "system_state": "NORMAL",
        "correlation_bucket": "GREEN",
        "news_lock": False,
    }

    monkeypatch.setattr(ar, "RiskEngine", _FakeRiskEngine)
    monkeypatch.setattr(ar, "_check_stale_data", AsyncMock(return_value=None))
    monkeypatch.setattr(ar, "_runtime_take_precheck", AsyncMock(return_value=(True, None)))
    monkeypatch.setattr(ar, "_persist_trade_write_through", AsyncMock(return_value=True))
    monkeypatch.setattr(ar, "_enqueue_outbox_atomic", AsyncMock(return_value="1-0"))
    monkeypatch.setattr(ar, "_redis_set", AsyncMock(return_value=True))
    monkeypatch.setattr(ar, "_redis_get", AsyncMock(return_value=None))
    monkeypatch.setattr(ar, "_redis_hgetall", AsyncMock(return_value={}))
    monkeypatch.setattr(ar, "_journal_service", TradeJournalAutomationService())
    monkeypatch.setattr(ar, "_signal_service", Mock(publish=Mock()))

    idem_store: dict[str, str] = {}

    def _idem_set(key: str, value: str, nx: bool | None = None, ex: int | None = None):  # noqa: ARG001
        if nx and key in idem_store:
            return False
        idem_store[key] = value
        return True

    def _idem_get(key: str):
        return idem_store.get(key)

    monkeypatch.setattr("execution.idempotency_ledger.redis_client.client.set", _idem_set)
    monkeypatch.setattr("execution.idempotency_ledger.redis_client.client.get", _idem_get)

    async def _fast_atomic_confirm(trade_id: str) -> dict[str, object]:
        trade = ar._trade_ledger[trade_id]  # pyright: ignore[reportPrivateUsage]
        trade["status"] = "PENDING"
        trade["updated_at"] = datetime.now(UTC).isoformat()
        ar._trade_ledger[trade_id] = trade  # pyright: ignore[reportPrivateUsage]
        return trade

    monkeypatch.setattr(ar, "_atomic_transition_intended_to_pending", _fast_atomic_confirm)

    take_resp = await ar.take_signal(
        ar.TakeSignalRequest(
            signal_id=l12_signal_id,
            account_id="ACC-E2E-NEG-1",
            pair=l12_symbol,
            direction=l12_direction,
            entry=l12_entry,
            sl=l12_sl,
            tp=l12_tp1,
            risk_percent=1.0,
            risk_mode="FIXED",
        )
    )
    trade_id = str(take_resp["trade_id"])

    confirm_resp = await ar.confirm_trade(ar.ConfirmTradeRequest(trade_id=trade_id))
    assert confirm_resp["status"] == "PENDING"

    violation_resp = await ar.record_trade_lifecycle_event(
        ar.TradeLifecycleEventRequest(
            trade_id=trade_id,
            event_type="SYSTEM_VIOLATION",
            source="EA",
            reason="PROP_GUARD_BREACH",
            pnl=-120.0,
        )
    )
    assert violation_resp["status"] == "ABORTED"
    assert ar._trade_ledger[trade_id]["status"] == "ABORTED"  # pyright: ignore[reportPrivateUsage]

    repo = JournalRepository(base_dir=str(archive_dir))
    entries = repo.load_entries(date_range_days=1)
    journal_types = [str(item.get("journal_type")) for item in entries]

    assert "decision" in journal_types  # J2 still logged
    assert "reflective" in journal_types  # J4 logged on abort/cancel path

    reflection = next(item for item in entries if item.get("journal_type") == "reflective")
    assert reflection["data"]["outcome"] == "LOSS"
    assert reflection["data"]["learning_note"] == "PROP_GUARD_BREACH"
