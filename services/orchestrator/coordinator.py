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

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from core.redis_keys import EXECUTION_INTENTS, ORCHESTRATION_EVENTS
from services.orchestrator.compliance_auto_mode import (
    ComplianceAutoMode,
    ComplianceAutoModePaused,
)
from services.orchestrator.protocols import (
    STATUS_EXECUTION_SENT,
    STATUS_FIREWALL_APPROVED,
    STATUS_FIREWALL_REJECTED,
    STATUS_PENDING,
    STATUS_REJECTED,
    VERDICT_REJECTED,
    RiskFirewallLike,
    StreamPublisherLike,
    TakeSignalResponseLike,
    TakeSignalServiceLike,
)


@dataclass(slots=True)
class OrchestrationResult:
    """Result of an orchestrated take-signal flow."""

    take_id: str
    verdict: str
    firewall_id: str | None = None
    execution_intent_id: str | None = None
    status: str = "PENDING"
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

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
    """Coordinator for the take-signal → compliance → firewall → execution pipeline.

    This module ONLY routes flow — it never invents or mutates verdicts.
    """

    def __init__(
        self,
        take_signal_service: TakeSignalServiceLike | None = None,
        risk_firewall: RiskFirewallLike | None = None,
        stream_publisher: StreamPublisherLike | None = None,
        compliance_auto_mode: ComplianceAutoMode | None = None,
    ) -> None:
        if take_signal_service is None:
            from execution.take_signal_service import TakeSignalService  # noqa: PLC0415

            take_signal_service = TakeSignalService()
        if risk_firewall is None:
            from risk.firewall import RiskFirewall  # noqa: PLC0415

            risk_firewall = RiskFirewall()
        self._take_svc = take_signal_service
        self._firewall = risk_firewall
        self._publisher = stream_publisher
        self._compliance = compliance_auto_mode

    def _get_publisher(self) -> StreamPublisherLike:
        if self._publisher is None:
            from infrastructure.stream_publisher import StreamPublisher  # noqa: PLC0415

            self._publisher = StreamPublisher()
        return self._publisher

    # ── Public entry point ────────────────────────────────────────────────

    async def process_take_signal(
        self,
        take_id: str,
        signal: dict[str, Any],
        account_state: dict[str, Any],
    ) -> OrchestrationResult:
        """Run the ordered orchestration flow for a take-signal.

        Pipeline:
          1. Validate take-signal exists and is in PENDING state
          2. Enforce compliance auto-mode (block if paused)
          3. Run risk firewall checks
          4. If firewall rejects → handle rejection, stop
          5. If firewall approves → dispatch to execution, complete

        The orchestrator does NOT modify the signal, verdict, or direction.
        """
        take_response = await self._validate_take(take_id)
        if isinstance(take_response, OrchestrationResult):
            return take_response

        # ── Compliance gate: must pass BEFORE firewall ────────────────
        compliance_block = self._enforce_compliance(take_id)
        if compliance_block is not None:
            return compliance_block

        await self._emit_event(
            "ORCHESTRATION_STARTED",
            {
                "take_id": take_id,
                "signal_id": take_response.signal_id,
                "account_id": take_response.account_id,
            },
        )

        fw_result = await self._evaluate_firewall(take_id, signal, account_state)
        if isinstance(fw_result, OrchestrationResult):
            return fw_result

        if fw_result.verdict == VERDICT_REJECTED:
            return await self._handle_rejection(take_id, fw_result)

        return await self._dispatch_and_complete(
            take_id,
            signal,
            account_state,
            fw_result,
        )

    # ── Pipeline steps (private) ───────────────────────────────────────────

    def _enforce_compliance(self, take_id: str) -> OrchestrationResult | None:
        """Check compliance auto-mode. Returns OrchestrationResult if blocked, else None.

        This is a synchronous gate — ComplianceAutoMode.enforce() raises
        ComplianceAutoModePaused when auto-trading is paused.
        Called BEFORE the firewall so that compliance violations are caught
        before any risk evaluation or downstream dispatch.
        """
        if self._compliance is None:
            return None
        try:
            self._compliance.enforce()
        except ComplianceAutoModePaused as exc:
            logger.warning(
                "[Coordinator] Compliance gate blocked take_id=%s: %s",
                take_id,
                exc,
            )
            return OrchestrationResult(
                take_id=take_id,
                verdict="REJECTED",
                status="COMPLIANCE_BLOCKED",
                reason=str(exc),
            )
        return None

    async def _validate_take(
        self,
        take_id: str,
    ) -> TakeSignalResponseLike | OrchestrationResult:
        """Fetch take-signal and verify it is in PENDING state."""
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
        return take_response

    async def _evaluate_firewall(
        self,
        take_id: str,
        signal: dict[str, Any],
        account_state: dict[str, Any],
    ) -> Any | OrchestrationResult:
        """Run firewall evaluation. Returns firewall result or OrchestrationResult on error."""
        try:
            return await self._firewall.evaluate(take_id, signal, account_state)
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

    async def _handle_rejection(
        self,
        take_id: str,
        fw_result: Any,
    ) -> OrchestrationResult:
        """Transition to FIREWALL_REJECTED and emit rejection event."""
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

    async def _dispatch_and_complete(
        self,
        take_id: str,
        signal: dict[str, Any],
        account_state: dict[str, Any],
        fw_result: Any,
    ) -> OrchestrationResult:
        """Approve, dispatch to execution, and finalize the flow."""
        await self._take_svc.transition(
            take_id,
            STATUS_FIREWALL_APPROVED,
            reason="All firewall checks passed",
            firewall_result_id=fw_result.firewall_id,
        )

        execution_intent_id = await self._dispatch_to_execution(
            take_id=take_id,
            signal=signal,
            account_state=account_state,
            firewall_id=fw_result.firewall_id,
        )

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

            publisher = self._get_publisher()
            await publisher.publish(
                stream=EXECUTION_INTENTS,
                fields=payload.to_stream_fields(),
            )
        except Exception:
            logger.error("[Coordinator] Execution dispatch failed to stream", exc_info=True)
            raise

        return execution_intent_id

    async def _emit_event(self, event_type: str, details: dict[str, Any]) -> None:
        """Emit orchestration status event (non-blocking, best-effort)."""
        try:
            publisher = self._get_publisher()
            fields = {"event_type": event_type, **{k: str(v) for k, v in details.items()}}
            fields["timestamp"] = datetime.now(UTC).isoformat()
            await publisher.publish(stream=ORCHESTRATION_EVENTS, fields=fields)
        except Exception:
            logger.debug("[Coordinator] Event emission failed for {}", event_type)
