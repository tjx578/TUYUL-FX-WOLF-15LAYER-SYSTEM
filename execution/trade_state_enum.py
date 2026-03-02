"""
<<<<<<< Updated upstream
Extended Trade State Machine - 10 States

This module defines the extended trade lifecycle states for the
TUYUL FX system, supporting both EA and manual trading flows.

States:
    - SIGNAL_CREATED: L12 signal received, not yet acted upon
    - SIGNAL_EXPIRED: Signal expired before placement
    - PENDING_PLACED: Order placed, awaiting fill
    - PENDING_FILLED: Order filled successfully
    - PENDING_CANCELLED: Pending order cancelled
    - TRADE_OPEN: Active trade position
    - TRADE_PARTIAL_CLOSED: Partial position closure (TP1, scaling)
    - TRADE_CLOSED: Trade fully closed
    - TRADE_ABORTED: Trade aborted (e.g., emergency exit)
    - IDLE: No active signal/trade (legacy compatibility)
"""
=======
Trade State Enum — canonical state machine states for dashboard + execution.

Maps between execution/state_machine.py (engine states) and
the dashboard conceptual model defined in copilot-instructions.md.
"""
from __future__ import annotations
>>>>>>> Stashed changes

from enum import StrEnum


class TradeState(StrEnum):
<<<<<<< Updated upstream
    """Extended trade lifecycle states (10 states)."""

    SIGNAL_CREATED = "SIGNAL_CREATED"
    SIGNAL_EXPIRED = "SIGNAL_EXPIRED"
    PENDING_PLACED = "PENDING_PLACED"
    PENDING_FILLED = "PENDING_FILLED"
    PENDING_CANCELLED = "PENDING_CANCELLED"
    TRADE_OPEN = "TRADE_OPEN"
    TRADE_PARTIAL_CLOSED = "TRADE_PARTIAL_CLOSED"
    TRADE_CLOSED = "TRADE_CLOSED"
    TRADE_ABORTED = "TRADE_ABORTED"
    IDLE = "IDLE"


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, from_state: TradeState, to_state: TradeState):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid transition: {from_state.value} -> {to_state.value}")


# Valid state transitions mapping
VALID_TRANSITIONS: dict[TradeState, set[TradeState]] = {
    TradeState.IDLE: {
        TradeState.SIGNAL_CREATED,
    },
    TradeState.SIGNAL_CREATED: {
        TradeState.SIGNAL_EXPIRED,
        TradeState.PENDING_PLACED,
        TradeState.IDLE,
    },
    TradeState.SIGNAL_EXPIRED: {
        TradeState.IDLE,
    },
    TradeState.PENDING_PLACED: {
        TradeState.PENDING_FILLED,
        TradeState.PENDING_CANCELLED,
        TradeState.SIGNAL_EXPIRED,
    },
    TradeState.PENDING_FILLED: {
        TradeState.TRADE_OPEN,
    },
    TradeState.PENDING_CANCELLED: {
        TradeState.IDLE,
    },
    TradeState.TRADE_OPEN: {
        TradeState.TRADE_PARTIAL_CLOSED,
        TradeState.TRADE_CLOSED,
        TradeState.TRADE_ABORTED,
    },
    TradeState.TRADE_PARTIAL_CLOSED: {
        TradeState.TRADE_CLOSED,
        TradeState.TRADE_ABORTED,
    },
    TradeState.TRADE_CLOSED: {
        TradeState.IDLE,
    },
    TradeState.TRADE_ABORTED: {
        TradeState.IDLE,
    },
}


def validate_transition(from_state: TradeState, to_state: TradeState) -> None:
    """
    Validate if a state transition is allowed.

    Args:
        from_state: Current state
        to_state: Target state

    Raises:
        InvalidTransitionError: If transition is not allowed
    """
    allowed_states = VALID_TRANSITIONS.get(from_state, set())
    if to_state not in allowed_states:
        raise InvalidTransitionError(from_state, to_state)
=======
    """
    Dashboard-level conceptual trade states.

    Mapping to execution/state_machine.py:
      SIGNAL_CREATED → IDLE (with attached signal, no live order)
      PENDING_PLACED  → PENDING_ACTIVE
      PENDING_FILLED / TRADE_OPEN → FILLED (position live)
      PENDING_CANCELLED / SIGNAL_EXPIRED / TRADE_CLOSED / TRADE_ABORTED → terminal
    """

    SIGNAL_CREATED = "SIGNAL_CREATED"
    PENDING_PLACED = "PENDING_PLACED"
    PENDING_FILLED = "PENDING_FILLED"
    TRADE_OPEN = "TRADE_OPEN"
    TRADE_PARTIAL_CLOSED = "TRADE_PARTIAL_CLOSED"
    TRADE_CLOSED = "TRADE_CLOSED"
    PENDING_CANCELLED = "PENDING_CANCELLED"
    SIGNAL_EXPIRED = "SIGNAL_EXPIRED"
    TRADE_ABORTED = "TRADE_ABORTED"


TERMINAL_STATES: frozenset[TradeState] = frozenset({
    TradeState.TRADE_CLOSED,
    TradeState.PENDING_CANCELLED,
    TradeState.SIGNAL_EXPIRED,
    TradeState.TRADE_ABORTED,
})

ACTIVE_STATES: frozenset[TradeState] = frozenset({
    TradeState.SIGNAL_CREATED,
    TradeState.PENDING_PLACED,
    TradeState.PENDING_FILLED,
    TradeState.TRADE_OPEN,
    TradeState.TRADE_PARTIAL_CLOSED,
})

# Valid transitions map
VALID_TRANSITIONS: dict[TradeState, frozenset[TradeState]] = {
    TradeState.SIGNAL_CREATED: frozenset({TradeState.PENDING_PLACED, TradeState.SIGNAL_EXPIRED}),
    TradeState.PENDING_PLACED: frozenset({TradeState.PENDING_FILLED, TradeState.PENDING_CANCELLED}),
    TradeState.PENDING_FILLED: frozenset({TradeState.TRADE_OPEN}),
    TradeState.TRADE_OPEN: frozenset({TradeState.TRADE_PARTIAL_CLOSED, TradeState.TRADE_CLOSED, TradeState.TRADE_ABORTED}),
    TradeState.TRADE_PARTIAL_CLOSED: frozenset({TradeState.TRADE_CLOSED, TradeState.TRADE_ABORTED}),
    TradeState.TRADE_CLOSED: frozenset(),
    TradeState.PENDING_CANCELLED: frozenset(),
    TradeState.SIGNAL_EXPIRED: frozenset(),
    TradeState.TRADE_ABORTED: frozenset(),
}


def is_valid_transition(from_state: TradeState, to_state: TradeState) -> bool:
    """Check whether a state transition is allowed."""
    return to_state in VALID_TRANSITIONS.get(from_state, frozenset())
>>>>>>> Stashed changes
