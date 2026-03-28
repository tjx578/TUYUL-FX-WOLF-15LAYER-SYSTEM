"""Pydantic contracts for inter-service Redis messages.

These models enforce structural validation at service boundaries
to prevent silent field-missing / type-coercion bugs when data
flows between services through Redis Streams, Pub/Sub, or key-value.

Zone: contracts — no market logic, no execution authority.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# ── Verdict Payload (L12 cache → signal_service / allocation) ─────────────

class VerdictPayload(BaseModel):
    """Validated shape for a cached L12 verdict read from Redis."""

    model_config = ConfigDict(extra="allow")  # tolerant of extra analysis fields

    signal_id: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    verdict: str = Field(...)
    confidence: float = Field(..., ge=0.0, le=1.0)
    direction: str | None = None
    entry_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit_1: float | None = Field(default=None, gt=0)
    risk_reward_ratio: float | None = Field(default=None, ge=0)
    timestamp: float | None = None
    expires_at: float | None = None


# ── Execution Intent (Orchestrator → Execution stream) ────────────────────

class ExecutionIntentPayload(BaseModel):
    """Validated shape for an execution intent pushed by the coordinator."""

    model_config = ConfigDict(extra="forbid")

    execution_intent_id: str = Field(..., min_length=1)
    take_id: str = Field(..., min_length=1)
    signal_id: str = Field(default="")
    symbol: str = Field(..., min_length=1)
    direction: str = Field(...)
    entry_price: str = Field(...)
    stop_loss: str = Field(...)
    take_profit_1: str = Field(...)
    account_id: str = Field(..., min_length=1)
    firewall_id: str = Field(default="")
    timestamp: str = Field(...)

    def to_stream_fields(self) -> dict[str, str]:
        """Serialize to Redis Stream fields (all strings)."""
        return {k: str(v) for k, v in self.model_dump().items()}


# ── Worker Result (worker jobs → Redis key) ───────────────────────────────

class WorkerResultPayload(BaseModel):
    """Validated shape for a worker job result stored in Redis."""

    model_config = ConfigDict(extra="allow")  # workers may add job-specific fields

    job: str = Field(..., min_length=1)
    timestamp: str = Field(..., min_length=1)


# ── Orchestrator Command (Pub/Sub) ───────────────────────────────────────

class OrchestratorCommand(BaseModel):
    """Validated shape for an orchestrator mode-change command.

    Only the 'command' field is authoritative — the 'event' field
    is explicitly excluded (SVC-BUG-12).
    """

    model_config = ConfigDict(extra="allow")

    command: str = Field(..., min_length=1)
    mode: str = Field(..., min_length=1)
    reason: str = Field(default="command")
