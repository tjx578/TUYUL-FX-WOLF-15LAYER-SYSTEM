"""
Allocation Service — multi-account simultaneous allocation.

Reads signal from SignalRegistry, applies per-account risk engine,
enforces prop firm rules, and publishes execution plans to Redis.

Authority boundaries:
  - Does NOT compute market direction (that is L12's domain).
  - Does NOT execute trades (that is execution worker's domain).
  - DOES clamp lot size per account risk profile.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger

from accounts.account_repository import AccountRepository, AccountRiskState
from accounts.account_risk_engine import AccountRiskEngine
from accounts.risk_calculator import AccountScopedRiskEngine
from allocation.allocation_models import (
    AccountAllocationResult,
    AllocationRequest,
    AllocationResult,
    AllocationStatus,
)
from allocation.allocation_audit import AllocationAudit
from allocation.signal_registry import SignalRegistry
from config.pip_values import DEFAULT_PIP_VALUE, PipLookupError, get_pip_info
from infrastructure.tracing import inject_trace_context

EXECUTION_STREAM = "execution:queue"
TRADE_UPDATES_CHANNEL = "trade:updates"


class AllocationService:
    """
    Simultaneous multi-account allocation service.

    Flow:
      operator/API → AllocationService.allocate() → per-account RiskEngine
      → approved plans pushed to execution:queue
    """

    def __init__(self) -> None:
        self._repo = AccountRepository.get_default()
        self._account_risk_engine = AccountRiskEngine()
        self._scoped_engine = AccountScopedRiskEngine()
        self._registry = SignalRegistry()
        self._audit = AllocationAudit()

    def allocate(self, request: AllocationRequest) -> AllocationResult:
        """
        Allocate a signal across requested accounts simultaneously.

        Returns AllocationResult with per-account outcomes.
        Does NOT block on execution — pushes to Redis stream asynchronously.
        """
        signal_raw = self._registry.get_by_id(request.signal_id)
        if not signal_raw:
            return AllocationResult(
                request_id=request.request_id,
                signal_id=request.signal_id,
                status=AllocationStatus.REJECTED,
                account_results=[
                    AccountAllocationResult(
                        account_id=account_id,
                        approved=False,
                        allowed=False,
                        status="REJECT",
                        reason="signal_not_found",
                        severity="CRITICAL",
                    )
                    for account_id in request.account_ids
                ],
                approved_count=0,
                rejected_count=len(request.account_ids),
            )

        if str(signal_raw.get("status", "OPEN")).upper() != "OPEN":
            return AllocationResult(
                request_id=request.request_id,
                signal_id=request.signal_id,
                status=AllocationStatus.REJECTED,
                account_results=[
                    AccountAllocationResult(
                        account_id=account_id,
                        approved=False,
                        allowed=False,
                        status="REJECT",
                        reason="signal_not_open",
                        severity="WARNING",
                    )
                    for account_id in request.account_ids
                ],
                approved_count=0,
                rejected_count=len(request.account_ids),
            )

        account_results: list[AccountAllocationResult] = []
        symbol = str(signal_raw.get("pair") or signal_raw.get("symbol") or "").upper()

        for account_id in request.account_ids:
            account_state = self._repo.get_state(account_id)
            if not account_state:
                account_results.append(AccountAllocationResult(
                    account_id=account_id,
                    approved=False,
                    allowed=False,
                    status="REJECT",
                    reason="account_not_found",
                    severity="CRITICAL",
                ))
                continue

            if account_state.in_pair_cooldown(symbol):
                account_results.append(AccountAllocationResult(
                    account_id=account_id,
                    approved=False,
                    allowed=False,
                    status="REJECT",
                    reason="pair_cooldown_active",
                    severity="WARNING",
                ))
                continue

            result = self._calculate_account_plan(
                account_state=account_state,
                signal=signal_raw,
                requested_risk=request.risk_percent,
            )
            account_results.append(result)

            if result.allowed and request.action.upper() == "TAKE":
                self._push_execution_plan(request, signal_raw, account_id, result.lot_size)

        approved = sum(1 for r in account_results if r.allowed)
        rejected = len(account_results) - approved
        status = (
            AllocationStatus.APPROVED if approved == len(account_results) and approved > 0 else
            AllocationStatus.PARTIALLY_APPROVED if approved > 0 else
            AllocationStatus.REJECTED
        )

        final_result = AllocationResult(
            request_id=request.request_id,
            signal_id=request.signal_id,
            status=status,
            account_results=account_results,
            approved_count=approved,
            rejected_count=rejected,
        )
        self._audit.record(request, final_result)
        logger.info(f"AllocationService: {request.request_id} → approved={approved} rejected={rejected}")
        return final_result

    def _calculate_account_plan(
        self,
        *,
        account_state: AccountRiskState,
        signal: dict[str, Any],
        requested_risk: float,
    ) -> AccountAllocationResult:
        symbol = str(signal.get("pair") or signal.get("symbol") or "UNKNOWN").upper()

        try:
            _pip_value, pip_mult = get_pip_info(symbol)
        except PipLookupError:
            pip_mult = 10_000.0

        entry = float(signal.get("entry_price") or signal.get("entry") or 0.0)
        sl = float(signal.get("stop_loss") or 0.0)
        stop_loss_pips = abs(entry - sl) * pip_mult
        if stop_loss_pips <= 0:
            return AccountAllocationResult(
                account_id=account_state.account_id,
                approved=False,
                allowed=False,
                status="REJECT",
                reason="invalid_stop_loss_distance",
                severity="CRITICAL",
            )

        allowed = self._account_risk_engine.calculate_allowed_risk(account_state)
        requested_clamped = min(max(requested_risk, 0.0), allowed.allowed_risk_percent)
        if requested_clamped <= 0:
            return AccountAllocationResult(
                account_id=account_state.account_id,
                approved=False,
                allowed=False,
                status="REJECT",
                reason="daily_or_total_buffer_exhausted",
                daily_buffer_percent=allowed.daily_remaining_percent,
                total_buffer_percent=allowed.total_remaining_percent,
                severity="CRITICAL",
            )

        scoped = self._scoped_engine.evaluate_trade(
            account_state=account_state,
            requested_risk_percent=requested_clamped,
            stop_loss_pips=stop_loss_pips,
            pip_value_per_lot=DEFAULT_PIP_VALUE,
        )

        approved = bool(scoped.trade_allowed)
        return AccountAllocationResult(
            account_id=account_state.account_id,
            approved=approved,
            allowed=approved,
            lot_size=float(scoped.recommended_lot if approved else 0.0),
            risk_percent=float(scoped.recommended_risk_percent if approved else 0.0),
            daily_buffer_percent=float(scoped.daily_buffer_percent),
            total_buffer_percent=float(scoped.total_buffer_percent),
            status="APPROVED" if approved else "REJECT",
            reason=scoped.reason,
            severity="SAFE" if approved else "WARNING",
        )

    def _push_execution_plan(
        self,
        request: AllocationRequest,
        signal_raw: dict[str, Any],
        account_id: str,
        lot_size: float,
    ) -> None:
        try:
            from storage.redis_client import RedisClient  # noqa: PLC0415
            rc = RedisClient()
            execution_plan = dict(signal_raw.get("execution_plan_json") or {})
            plan = {
                "request_id": request.request_id,
                "signal_id": request.signal_id,
                "account_id": account_id,
                "symbol": signal_raw.get("pair") or signal_raw.get("symbol"),
                "verdict": signal_raw.get("verdict"),
                "entry_price": str(execution_plan.get("entry_price", signal_raw.get("entry_price", signal_raw.get("entry", "")))),
                "stop_loss": str(execution_plan.get("stop_loss", signal_raw.get("stop_loss", ""))),
                "take_profit_1": str(execution_plan.get("take_profit_1", signal_raw.get("take_profit_1", ""))),
                "order_type": execution_plan.get("order_type", signal_raw.get("order_type", "PENDING_ONLY")),
                "execution_mode": execution_plan.get("execution_mode", signal_raw.get("execution_mode", "TP1_ONLY")),
                "lot_size": str(lot_size),
                "operator": request.operator,
            }
            inject_trace_context(plan)
            rc.xadd(EXECUTION_STREAM, plan)
        except Exception as exc:
            logger.error(f"AllocationService: failed to push execution plan: {exc}")
