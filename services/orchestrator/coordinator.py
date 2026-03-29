"""
Orchestrator Coordinator — P1-4
================================
Coordinator-only orchestration for the take-signal → firewall → execution flow.

The orchestrator:
  - Consumes verdict + take-signal + firewall decision + provenance
  - Dispatches downstream actions ONLY when allowed
  - Preserves hold/reject states and reasons
  - Emits orchestration status events WITHOUT mutating strategic meaning

Constitutional constraint: orchestrator may route flow, NEVER synthesize verdicts.

Zone: orchestrator — coordination authority, NOT verdict authority.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger

from core.redis_keys import EXECUTION_INTENTS, ORCHESTRATION_EVENTS
from services.orchestrator.protocols import (
    STATUS_EXECUTION_SENT,
    STATUS_FIREWALL_APPROVED,
    STATUS_FIREWALL_REJECTED,
    STATUS_PENDING,
    STATUS_REJECTED,
    VERDICT_REJECTED,
    RiskFirewallLike,
    TakeSignalServiceLike,
)


class OrchestrationResult:
    """Result of an orchestrated take-signal flow."""

    __slots__ = ("take_id", "verdict", "firewall_id", "execution_intent_id", "status", "reason", "timestamp")

    def __init__(
        self,
        take_id: str,
        verdict: str,
        firewall_id: str | None = None,
        execution_intent_id: str | None = None,
        status: str = "PENDING",
        reason: str = "",
    ) -> None:
        self.take_id = take_id
        self.verdict = verdict
        self.firewall_id = firewall_id
        self.execution_intent_id = execution_intent_id
        self.status = status
        self.reason = reason
        self.timestamp = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "take_id": self.take_id,
            "verdict": self.verdict,
            "firewall_id": self.firewall_id,
            "execution_intent_id": self.execution_intent_id,
            "status": self.status,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class OrchestratorCoordinator:
    """Coordinator for the take-signal → firewall → execution pipeline.

    This module ONLY routes flow — it never invents or mutates verdicts.
    """

    def __init__(
        self,
        take_signal_service: TakeSignalServiceLike | None = None,
        risk_firewall: RiskFirewallLike | None = None,
    ) -> None:
        if take_signal_service is None:
            from execution.take_signal_service import TakeSignalService  # noqa: PLC0415

            take_signal_service = TakeSignalService()
        if risk_firewall is None:
            from risk.firewall import RiskFirewall  # noqa: PLC0415

            risk_firewall = RiskFirewall()
        self._take_svc = take_signal_service
        self._firewall = risk_firewall

    async def process_take_signal(
        self,
        take_id: str,
        signal: dict[str, Any],
        account_state: dict[str, Any],
    ) -> OrchestrationResult:
        """Run the ordered orchestration flow for a take-signal.

        Flow:
          1. Validate take-signal exists and is in PENDING state
          2. Run risk firewall checks
          3. If firewall rejects: transition to FIREWALL_REJECTED, stop
          4. If firewall approves: transition to FIREWALL_APPROVED
          5. Dispatch to execution (creates execution intent)
          6. Transition to EXECUTION_SENT

        The orchestrator does NOT modify the signal, verdict, or direction.
        """
        # 1. Validate take-signal exists
        take_response = await self._take_svc.get(take_id)
        if take_response is None:
            return OrchestrationResult(
                take_id=take_id,
                verdict="REJECTED",
                status="ERROR",
                reason=f"take_id={take_id} not found",
            )

        if take_response.status != STATUS_PENDING:
            return OrchestrationResult(
                take_id=take_id,
                verdict="NOOP",
                status=str(take_response.status),
                reason=f"Take-signal already in {take_response.status} state",
            )

        # Emit orchestration started event
        await self._emit_event(
            "ORCHESTRATION_STARTED",
            {
                "take_id": take_id,
                "signal_id": take_response.signal_id,
                "account_id": take_response.account_id,
            },
        )

        # 2. Run risk firewall
        try:
            fw_result = await self._firewall.evaluate(take_id, signal, account_state)
        except Exception as exc:
            logger.error("[Coordinator] Firewall evaluation failed: {}", exc)
            await self._take_svc.transition(
                take_id,
                STATUS_REJECTED,
                reason=f"Firewall evaluation error: {exc}",
            )
            return OrchestrationResult(
                take_id=take_id,
                verdict="REJECTED",
                status="ERROR",
                reason=f"Firewall error: {exc}",
            )

        # 3. If firewall rejects: stop
        if fw_result.verdict == VERDICT_REJECTED:
            await self._take_svc.transition(
                take_id,
                STATUS_FIREWALL_REJECTED,
                reason=f"Firewall rejected at: {fw_result.short_circuited_at}",
                firewall_result_id=fw_result.firewall_id,
            )
            await self._emit_event(
                "ORCHESTRATION_REJECTED",
                {
                    "take_id": take_id,
                    "firewall_id": fw_result.firewall_id,
                    "reason": fw_result.short_circuited_at,
                },
            )
            return OrchestrationResult(
                take_id=take_id,
                verdict="REJECTED",
                firewall_id=fw_result.firewall_id,
                status=STATUS_FIREWALL_REJECTED,
                reason=f"Firewall blocked at: {fw_result.short_circuited_at}",
            )

        # 4. Firewall approved → transition
        await self._take_svc.transition(
            take_id,
            STATUS_FIREWALL_APPROVED,
            reason="All firewall checks passed",
            firewall_result_id=fw_result.firewall_id,
        )

        # 5. Dispatch to execution
        execution_intent_id = await self._dispatch_to_execution(
            take_id=take_id,
            signal=signal,
            account_state=account_state,
            firewall_id=fw_result.firewall_id,
        )

        # 6. Transition to EXECUTION_SENT
        await self._take_svc.transition(
            take_id,
            STATUS_EXECUTION_SENT,
            reason="Dispatched to execution",
            execution_intent_id=execution_intent_id,
        )

        await self._emit_event(
            "ORCHESTRATION_DISPATCHED",
            {
                "take_id": take_id,
                "firewall_id": fw_result.firewall_id,
                "execution_intent_id": execution_intent_id,
            },
        )

        logger.info(
            "[Coordinator] take_id=%s approved and dispatched, exec_intent=%s",
            take_id,
            execution_intent_id,
        )
        return OrchestrationResult(
            take_id=take_id,
            verdict="APPROVED",
            firewall_id=fw_result.firewall_id,
            execution_intent_id=execution_intent_id,
            status=STATUS_EXECUTION_SENT,
            reason="Dispatched to execution",
        )

    async def _dispatch_to_execution(
        self,
        take_id: str,
        signal: dict[str, Any],
        account_state: dict[str, Any],
        firewall_id: str,
    ) -> str:
        """Push an execution intent to the execution queue.

        Returns the execution_intent_id.
        The orchestrator does NOT execute — it only dispatches.
        """
        import uuid  # noqa: PLC0415

        execution_intent_id = f"ei_{uuid.uuid4().hex}"

        try:
            from contracts.redis_stream_contracts import ExecutionIntentPayload  # noqa: PLC0415
            from infrastructure.stream_publisher import StreamPublisher  # noqa: PLC0415

            payload = ExecutionIntentPayload(
                execution_intent_id=execution_intent_id,
                take_id=take_id,
                signal_id=signal.get("signal_id", ""),
                symbol=signal.get("symbol", ""),
                direction=signal.get("direction", ""),
                entry_price=str(signal.get("entry_price", "")),
                stop_loss=str(signal.get("stop_loss", "")),
                take_profit_1=str(signal.get("take_profit_1", "")),
                account_id=account_state.get("account_id", ""),
                firewall_id=firewall_id,
                timestamp=datetime.now(UTC).isoformat(),
            )

            publisher = StreamPublisher()
            await publisher.publish(
                stream=EXECUTION_INTENTS,
                fields=payload.to_stream_fields(),
            )
        except Exception:
            logger.error("[Coordinator] Execution dispatch failed to stream", exc_info=True)
            raise

        return execution_intent_id

    @staticmethod
    async def _emit_event(event_type: str, details: dict[str, Any]) -> None:
        """Emit orchestration status event (non-blocking, best-effort)."""
        try:
            from infrastructure.stream_publisher import StreamPublisher  # noqa: PLC0415

            publisher = StreamPublisher()
            fields = {"event_type": event_type, **{k: str(v) for k, v in details.items()}}
            fields["timestamp"] = datetime.now(UTC).isoformat()
            await publisher.publish(stream=ORCHESTRATION_EVENTS, fields=fields)
        except Exception:
            logger.debug("[Coordinator] Event emission failed for {}", event_type)
