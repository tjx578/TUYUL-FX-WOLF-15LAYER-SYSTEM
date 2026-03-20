"""
Execution Reconciliation — P1-6
=================================
Reconciliation logic for ambiguous/pending execution states on timeout/restart.

On restart or timeout:
  - Reload all pending/ambiguous intents
  - Mark ambiguous states explicitly (UNRESOLVED)
  - Reconcile against broker/EA truth where available
  - Prevent blind resend until reconciliation resolves

Zone: execution — safety authority, prevents duplicate semantics.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from execution.execution_intent import (
    ExecutionIntentRecord,
    ExecutionIntentRepository,
    ExecutionLifecycleState,
)

# Configurable timeout threshold for marking pending intents as unresolved
_PENDING_TIMEOUT_SEC = int(os.getenv("EXECUTION_PENDING_TIMEOUT_SEC", "300"))


class ReconciliationResult:
    """Result of a single intent reconciliation."""

    __slots__ = ("execution_intent_id", "previous_state", "resolved_state", "resolution_source", "reason")

    def __init__(
        self,
        execution_intent_id: str,
        previous_state: str,
        resolved_state: str,
        resolution_source: str,
        reason: str,
    ) -> None:
        self.execution_intent_id = execution_intent_id
        self.previous_state = previous_state
        self.resolved_state = resolved_state
        self.resolution_source = resolution_source
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_intent_id": self.execution_intent_id,
            "previous_state": self.previous_state,
            "resolved_state": self.resolved_state,
            "resolution_source": self.resolution_source,
            "reason": self.reason,
        }


class ExecutionReconciler:
    """Reconciles ambiguous execution states on timeout/restart.

    Safety rules:
      - Never blind-resend without reconciliation
      - UNRESOLVED stays visible until explicitly resolved
      - Broker/EA truth takes precedence over intent truth
    """

    def __init__(
        self,
        repo: ExecutionIntentRepository | None = None,
        pending_timeout_sec: int = _PENDING_TIMEOUT_SEC,
    ) -> None:
        self._repo = repo or ExecutionIntentRepository()
        self._pending_timeout_sec = max(60, pending_timeout_sec)

    async def reconcile_on_restart(self) -> list[ReconciliationResult]:
        """Run reconciliation for all pending/ambiguous intents.

        Called on service restart. Marks timed-out intents as UNRESOLVED.
        """
        results: list[ReconciliationResult] = []

        # Find all ORDER_PLACED and ACKNOWLEDGED intents
        for state in (
            ExecutionLifecycleState.ORDER_PLACED,
            ExecutionLifecycleState.ACKNOWLEDGED,
            ExecutionLifecycleState.PARTIALLY_FILLED,
        ):
            intents = await self._repo.list_by_state(state)
            for intent in intents:
                result = await self._reconcile_single(intent)
                if result is not None:
                    results.append(result)

        if results:
            logger.warning(
                "[Reconciler] Reconciled %d intents on restart",
                len(results),
            )
            await self._emit_reconciliation_event(results)

        return results

    async def reconcile_single(
        self,
        execution_intent_id: str,
        broker_truth: dict[str, Any] | None = None,
    ) -> ReconciliationResult | None:
        """Reconcile a single execution intent against broker truth."""
        intent = await self._repo.get(execution_intent_id)
        if intent is None:
            return None
        return await self._reconcile_single(intent, broker_truth)

    async def _reconcile_single(
        self,
        intent: ExecutionIntentRecord,
        broker_truth: dict[str, Any] | None = None,
    ) -> ReconciliationResult | None:
        """Core reconciliation logic for a single intent."""
        now = datetime.now(UTC)
        created = datetime.fromisoformat(intent.created_at)
        age_sec = (now - created).total_seconds()

        # If broker truth is available, use it
        if broker_truth is not None:
            return await self._resolve_from_broker(intent, broker_truth)

        # If intent has timed out, mark as UNRESOLVED
        if age_sec > self._pending_timeout_sec:
            return await self._mark_unresolved(
                intent,
                reason=f"Pending for {int(age_sec)}s (timeout: {self._pending_timeout_sec}s)",
            )

        return None  # Still within timeout, no action

    async def _resolve_from_broker(
        self,
        intent: ExecutionIntentRecord,
        broker_truth: dict[str, Any],
    ) -> ReconciliationResult:
        """Resolve an intent using broker/EA truth."""
        broker_status = str(broker_truth.get("status", "")).upper()
        previous = intent.state.value

        if broker_status in ("FILLED", "EXECUTED"):
            await self._repo.transition(
                intent.execution_intent_id,
                ExecutionLifecycleState.FILLED,
                reason="Reconciled from broker: FILLED",
                fill_price=broker_truth.get("fill_price"),
                fill_time=broker_truth.get("fill_time"),
                slippage=broker_truth.get("slippage"),
                actual_lot_size=broker_truth.get("lot_size"),
                broker_order_id=broker_truth.get("order_id"),
            )
            return ReconciliationResult(
                intent.execution_intent_id,
                previous,
                "FILLED",
                "broker",
                "Broker confirmed fill",
            )

        if broker_status in ("CANCELLED", "REJECTED"):
            target = (
                ExecutionLifecycleState.CANCELLED if broker_status == "CANCELLED" else ExecutionLifecycleState.REJECTED
            )
            await self._repo.transition(
                intent.execution_intent_id,
                target,
                reason=f"Reconciled from broker: {broker_status}",
                rejection_code=broker_truth.get("rejection_code"),
            )
            return ReconciliationResult(
                intent.execution_intent_id,
                previous,
                target.value,
                "broker",
                f"Broker reported {broker_status}",
            )

        if broker_status == "EXPIRED":
            await self._repo.transition(
                intent.execution_intent_id,
                ExecutionLifecycleState.EXPIRED,
                reason="Reconciled from broker: EXPIRED",
            )
            return ReconciliationResult(
                intent.execution_intent_id,
                previous,
                "EXPIRED",
                "broker",
                "Broker reported expired",
            )

        # Unknown broker status → mark unresolved
        return await self._mark_unresolved(
            intent,
            reason=f"Broker status '{broker_status}' not recognized",
        )

    async def _mark_unresolved(
        self,
        intent: ExecutionIntentRecord,
        reason: str,
    ) -> ReconciliationResult:
        """Mark an intent as UNRESOLVED."""
        previous = intent.state.value
        if intent.state == ExecutionLifecycleState.UNRESOLVED:
            # Already unresolved — no-op
            return ReconciliationResult(
                intent.execution_intent_id,
                previous,
                "UNRESOLVED",
                "reconciler",
                "Already unresolved",
            )

        await self._repo.transition(
            intent.execution_intent_id,
            ExecutionLifecycleState.UNRESOLVED,
            reason=reason,
        )
        logger.warning(
            "[Reconciler] Marked %s as UNRESOLVED: %s",
            intent.execution_intent_id,
            reason,
        )
        return ReconciliationResult(
            intent.execution_intent_id,
            previous,
            "UNRESOLVED",
            "reconciler",
            reason,
        )

    @staticmethod
    async def _emit_reconciliation_event(
        results: list[ReconciliationResult],
    ) -> None:
        """Emit reconciliation summary event."""
        try:
            from infrastructure.stream_publisher import StreamPublisher  # noqa: PLC0415

            publisher = StreamPublisher()
            await publisher.publish(
                stream="wolf15:reconciliation:events",
                fields={
                    "event_type": "RECONCILIATION_COMPLETED",
                    "count": str(len(results)),
                    "timestamp": datetime.now(UTC).isoformat(),
                    "unresolved": str(sum(1 for r in results if r.resolved_state == "UNRESOLVED")),
                },
            )
        except Exception:
            logger.debug("[Reconciler] Event emission failed")
