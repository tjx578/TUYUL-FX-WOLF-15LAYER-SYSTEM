"""Small data contracts for SignalJSON execution-gate decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ExecutionGateOutcome = Literal["ALLOW", "DEFER", "BLOCK"]


@dataclass(frozen=True)
class ExecutionGateDecision:
    """Output-only decision produced before a final SignalJSON is emitted."""

    applies: bool
    decision: ExecutionGateOutcome
    execution_status: str
    blocked_by: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    live_rr: dict[str, Any] | None = None
    gate_version: str = "exec_gate.v1"

    @property
    def allows_execution(self) -> bool:
        return self.decision == "ALLOW"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "gate_version": self.gate_version,
            "applies": self.applies,
            "decision": self.decision,
            "execution_status": self.execution_status,
            "blocked_by": list(self.blocked_by),
            "reasons": list(self.reasons),
        }
        if self.live_rr is not None:
            payload["live_rr"] = dict(self.live_rr)
        return payload
