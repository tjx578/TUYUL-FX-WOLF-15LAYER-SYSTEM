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

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from accounts.account_model import Layer12Signal, RiskMode
from accounts.account_repository import AccountRepository
from accounts.risk_engine import RiskEngine
from allocation.allocation_models import (
    AccountAllocationResult,
    AllocationRequest,
    AllocationResult,
    AllocationStatus,
)
from allocation.allocation_audit import AllocationAudit
from allocation.signal_registry import SignalRegistry

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
        self._repo = AccountRepository()
        self._risk_engine = RiskEngine()
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
                approved_count=0,
                rejected_count=len(request.account_ids),
            )

        # Build Layer12Signal from registry data (no balance fields)
        try:
            signal = Layer12Signal(**{k: signal_raw[k] for k in Layer12Signal.model_fields if k in signal_raw})
        except Exception as exc:
            logger.error(f"AllocationService: invalid signal schema for {request.signal_id}: {exc}")
            return AllocationResult(
                request_id=request.request_id,
                signal_id=request.signal_id,
                status=AllocationStatus.REJECTED,
                approved_count=0,
                rejected_count=len(request.account_ids),
            )

        account_results: list[AccountAllocationResult] = []

        for account_id in request.account_ids:
            account_state = self._repo.get_state(account_id)
            if not account_state:
                account_results.append(AccountAllocationResult(
                    account_id=account_id, allowed=False, reason="account_not_found",
                ))
                continue

            result = self._risk_engine.calculate_lot(
                signal=signal,
                account_state=account_state,
                risk_percent=request.risk_percent,
                prop_firm_code=account_state.model_extra.get("prop_firm_code", "default") if account_state.model_extra else "default",
                risk_mode=RiskMode.FIXED,
            )

            acct_result = AccountAllocationResult(
                account_id=account_id,
                allowed=result.trade_allowed,
                lot_size=result.recommended_lot,
                risk_percent=result.risk_used_percent,
                reason=result.reason,
                severity=result.severity.value,
            )
            account_results.append(acct_result)

            if result.trade_allowed:
                self._push_execution_plan(request, signal_raw, account_id, result.recommended_lot)

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
            plan = {
                "request_id": request.request_id,
                "signal_id": request.signal_id,
                "account_id": account_id,
                "symbol": signal_raw.get("symbol"),
                "verdict": signal_raw.get("verdict"),
                "entry_price": str(signal_raw.get("entry_price", signal_raw.get("entry", ""))),
                "stop_loss": str(signal_raw.get("stop_loss", "")),
                "take_profit_1": str(signal_raw.get("take_profit_1", "")),
                "order_type": signal_raw.get("order_type", "PENDING_ONLY"),
                "execution_mode": signal_raw.get("execution_mode", "TP1_ONLY"),
                "lot_size": str(lot_size),
            }
            rc.xadd(EXECUTION_STREAM, plan)
        except Exception as exc:
            logger.error(f"AllocationService: failed to push execution plan: {exc}")
