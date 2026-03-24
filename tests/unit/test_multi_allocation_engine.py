"""Institutional multi-allocation flow tests."""
from __future__ import annotations

from accounts.account_repository import AccountRepository, AccountRiskState
from allocation.allocation_models import AllocationRequest, AllocationStatus
from allocation.allocation_service import AllocationService


class _MemoryRegistry:
    def __init__(self, payload: dict):
        self._payload = payload

    def get_by_id(self, signal_id: str):
        if signal_id == self._payload.get("signal_id"):
            return self._payload
        return None


class _NoopAudit:
    def record(self, request, result) -> None:  # noqa: ANN001
        return None


def test_one_signal_three_accounts_two_execute_one_reject() -> None:
    repo = AccountRepository.get_default()

    repo.upsert_state(
        AccountRiskState(
            account_id="FTMO_100K",
            prop_firm_code="ftmo",
            balance=100000.0,
            equity=100000.0,
            base_risk_percent=0.7,
            max_daily_loss_percent=5.0,
            max_total_loss_percent=10.0,
            daily_loss_used_percent=2.0,
            total_loss_used_percent=2.0,
            phase_mode="PHASE1",
        )
    )
    repo.upsert_state(
        AccountRiskState(
            account_id="FundedNext_50K",
            prop_firm_code="fundednext",
            balance=50000.0,
            equity=50000.0,
            base_risk_percent=0.7,
            max_daily_loss_percent=4.0,
            max_total_loss_percent=8.0,
            daily_loss_used_percent=2.0,
            total_loss_used_percent=2.0,
            phase_mode="PHASE2",
        )
    )
    repo.upsert_state(
        AccountRiskState(
            account_id="Personal_20K",
            prop_firm_code="default",
            balance=20000.0,
            equity=20000.0,
            base_risk_percent=0.7,
            max_daily_loss_percent=5.0,
            max_total_loss_percent=10.0,
            daily_loss_used_percent=4.95,
            total_loss_used_percent=1.0,
            phase_mode="FUNDED",
        )
    )

    signal = {
        "signal_id": "abc123",
        "pair": "XAUUSD",
        "symbol": "XAUUSD",
        "verdict": "EXECUTE_BUY",
        "status": "OPEN",
        "entry_price": 2100.0,
        "stop_loss": 2090.0,
        "take_profit_1": 2120.0,
        "execution_plan_json": {
            "entry_price": 2100.0,
            "stop_loss": 2090.0,
            "take_profit_1": 2120.0,
            "order_type": "PENDING_ONLY",
            "execution_mode": "TP1_ONLY",
        },
    }

    pushed: list[tuple[str, float]] = []

    service = AllocationService()
    service._repo = repo
    service._registry = _MemoryRegistry(signal)  # type: ignore[assignment]
    service._audit = _NoopAudit()  # type: ignore[assignment]
    service._push_execution_plan = lambda request, signal_raw, account_id, lot_size: pushed.append(
        (account_id, lot_size)
    )

    req = AllocationRequest(
        request_id="req-001",
        signal_id="abc123",
        account_ids=["FTMO_100K", "FundedNext_50K", "Personal_20K"],
        operator="desk-op",
        action="TAKE",
        risk_percent=0.7,
    )

    result = service.allocate(req)

    assert result.status == AllocationStatus.PARTIALLY_APPROVED
    assert result.approved_count == 2
    assert result.rejected_count == 1
    assert len(pushed) == 2

    per_account = {x.account_id: x for x in result.account_results}
    assert per_account["FTMO_100K"].allowed is True
    assert per_account["FundedNext_50K"].allowed is True
    assert per_account["Personal_20K"].allowed is False
    assert per_account["Personal_20K"].reason in {"BELOW_MIN_SAFE_THRESHOLD", "daily_or_total_buffer_exhausted"}
