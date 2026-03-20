"""
Take-Signal Models — P1-1/P1-2
================================
Pydantic models and state machine for the take-signal operational binding.

A take-signal record binds one global L12 signal to one account + EA instance.
The lifecycle is governed by an explicit state machine with terminal states.

Zone: API / control plane — no market logic, no verdict mutation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Take-Signal Lifecycle States ──────────────────────────────────────────────


class TakeSignalStatus(StrEnum):
    """Explicit lifecycle states for a take-signal binding."""

    PENDING = "PENDING"  # Created, awaiting firewall
    FIREWALL_APPROVED = "FIREWALL_APPROVED"  # Passed risk firewall
    FIREWALL_REJECTED = "FIREWALL_REJECTED"  # Blocked by risk firewall (terminal)
    EXECUTION_SENT = "EXECUTION_SENT"  # Dispatched to execution
    EXECUTED = "EXECUTED"  # Confirmed by broker/EA (terminal)
    REJECTED = "REJECTED"  # Rejected (signal expired, invalid, etc.) (terminal)
    CANCELLED = "CANCELLED"  # Operator cancelled (terminal)
    EXPIRED = "EXPIRED"  # TTL expired without execution (terminal)


TERMINAL_STATES: frozenset[TakeSignalStatus] = frozenset(
    {
        TakeSignalStatus.FIREWALL_REJECTED,
        TakeSignalStatus.EXECUTED,
        TakeSignalStatus.REJECTED,
        TakeSignalStatus.CANCELLED,
        TakeSignalStatus.EXPIRED,
    }
)

# ── State Transition Table ────────────────────────────────────────────────────
# Maps each state to the set of states it may transition to.
# Terminal states have no outgoing transitions (empty set).

VALID_TRANSITIONS: dict[TakeSignalStatus, frozenset[TakeSignalStatus]] = {
    TakeSignalStatus.PENDING: frozenset(
        {
            TakeSignalStatus.FIREWALL_APPROVED,
            TakeSignalStatus.FIREWALL_REJECTED,
            TakeSignalStatus.REJECTED,
            TakeSignalStatus.CANCELLED,
            TakeSignalStatus.EXPIRED,
        }
    ),
    TakeSignalStatus.FIREWALL_APPROVED: frozenset(
        {
            TakeSignalStatus.EXECUTION_SENT,
            TakeSignalStatus.CANCELLED,
            TakeSignalStatus.EXPIRED,
        }
    ),
    TakeSignalStatus.FIREWALL_REJECTED: frozenset(),
    TakeSignalStatus.EXECUTION_SENT: frozenset(
        {
            TakeSignalStatus.EXECUTED,
            TakeSignalStatus.REJECTED,
            TakeSignalStatus.CANCELLED,
            TakeSignalStatus.EXPIRED,
        }
    ),
    TakeSignalStatus.EXECUTED: frozenset(),
    TakeSignalStatus.REJECTED: frozenset(),
    TakeSignalStatus.CANCELLED: frozenset(),
    TakeSignalStatus.EXPIRED: frozenset(),
}


class InvalidTakeSignalTransition(Exception):  # noqa: N818
    """Raised when a forbidden state transition is attempted."""

    def __init__(self, from_state: TakeSignalStatus, to_state: TakeSignalStatus) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Forbidden take-signal transition: {from_state.value} -> {to_state.value}")


def validate_transition(
    from_state: TakeSignalStatus,
    to_state: TakeSignalStatus,
) -> None:
    """Validate and enforce state transition rules.

    Raises InvalidTakeSignalTransition if the transition is forbidden.
    """
    allowed = VALID_TRANSITIONS.get(from_state, frozenset())
    if to_state not in allowed:
        raise InvalidTakeSignalTransition(from_state, to_state)


def is_terminal(state: TakeSignalStatus) -> bool:
    """Return True if the state is terminal (no further transitions allowed)."""
    return state in TERMINAL_STATES


# ── Request / Response Models ─────────────────────────────────────────────────


class TakeSignalCreateRequest(BaseModel):
    """Operator request to bind a global signal to an account + EA instance."""

    model_config = ConfigDict(extra="forbid")

    signal_id: str = Field(..., min_length=3, description="Global L12 signal ID")
    account_id: str = Field(..., min_length=3, description="Target account ID")
    ea_instance_id: str = Field(..., min_length=3, description="Target EA instance")
    operator: str = Field(..., min_length=2, max_length=64, description="Operator identity")
    reason: str = Field(..., min_length=3, max_length=512, description="Reason for taking signal")
    request_id: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Client-generated idempotency key",
    )
    strategy_profile_id: str | None = Field(
        default=None,
        min_length=2,
        max_length=128,
        description="Optional strategy profile override",
    )
    metadata: dict[str, Any] | None = Field(default=None, description="Arbitrary operator metadata")


class TakeSignalRecord(BaseModel):
    """Persisted take-signal binding record."""

    model_config = ConfigDict(extra="forbid")

    take_id: str = Field(..., description="Server-generated unique take ID")
    request_id: str = Field(..., description="Client idempotency key")
    signal_id: str
    account_id: str
    ea_instance_id: str
    operator: str
    reason: str
    status: TakeSignalStatus = TakeSignalStatus.PENDING
    strategy_profile_id: str | None = None
    metadata: dict[str, Any] | None = None

    # Provenance
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    status_reason: str | None = Field(default=None, description="Reason for last status change")

    # Links to downstream records (populated as lifecycle progresses)
    firewall_result_id: str | None = None
    execution_intent_id: str | None = None


class TakeSignalResponse(BaseModel):
    """API response for a take-signal operation."""

    model_config = ConfigDict(extra="forbid")

    take_id: str
    request_id: str
    signal_id: str
    account_id: str
    ea_instance_id: str
    status: TakeSignalStatus
    created_at: str
    updated_at: str
    status_reason: str | None = None
    firewall_result_id: str | None = None
    execution_intent_id: str | None = None
