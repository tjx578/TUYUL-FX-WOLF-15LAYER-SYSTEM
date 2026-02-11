"""
Tests for Trade State Enum

Validates:
- All 10 states defined
- Valid transitions work
- Invalid transitions raise error
"""

import pytest

from execution.trade_state_enum import (
    VALID_TRANSITIONS,
    InvalidTransitionError,
    TradeState,
    validate_transition,
)


class TestTradeStates:
    """Test trade state definitions."""

    def test_all_states_exist(self):
        """Verify all 10 states are defined."""
        expected_states = {
            "SIGNAL_CREATED",
            "SIGNAL_EXPIRED",
            "PENDING_PLACED",
            "PENDING_FILLED",
            "PENDING_CANCELLED",
            "TRADE_OPEN",
            "TRADE_PARTIAL_CLOSED",
            "TRADE_CLOSED",
            "TRADE_ABORTED",
            "IDLE",
        }

        actual_states = {state.value for state in TradeState}
        assert actual_states == expected_states

    def test_state_values_match_names(self):
        """Ensure state values match their names."""
        assert TradeState.IDLE.value == "IDLE"
        assert TradeState.SIGNAL_CREATED.value == "SIGNAL_CREATED"
        assert TradeState.TRADE_OPEN.value == "TRADE_OPEN"


class TestValidTransitions:
    """Test valid state transitions."""

    def test_idle_to_signal_created(self):
        """IDLE -> SIGNAL_CREATED is valid."""
        validate_transition(TradeState.IDLE, TradeState.SIGNAL_CREATED)

    def test_signal_created_to_pending_placed(self):
        """SIGNAL_CREATED -> PENDING_PLACED is valid."""
        validate_transition(TradeState.SIGNAL_CREATED, TradeState.PENDING_PLACED)

    def test_pending_placed_to_filled(self):
        """PENDING_PLACED -> PENDING_FILLED is valid."""
        validate_transition(TradeState.PENDING_PLACED, TradeState.PENDING_FILLED)

    def test_pending_filled_to_trade_open(self):
        """PENDING_FILLED -> TRADE_OPEN is valid."""
        validate_transition(TradeState.PENDING_FILLED, TradeState.TRADE_OPEN)

    def test_trade_open_to_closed(self):
        """TRADE_OPEN -> TRADE_CLOSED is valid."""
        validate_transition(TradeState.TRADE_OPEN, TradeState.TRADE_CLOSED)

    def test_trade_open_to_partial_closed(self):
        """TRADE_OPEN -> TRADE_PARTIAL_CLOSED is valid."""
        validate_transition(TradeState.TRADE_OPEN, TradeState.TRADE_PARTIAL_CLOSED)

    def test_partial_closed_to_closed(self):
        """TRADE_PARTIAL_CLOSED -> TRADE_CLOSED is valid."""
        validate_transition(TradeState.TRADE_PARTIAL_CLOSED, TradeState.TRADE_CLOSED)

    def test_signal_expired_to_idle(self):
        """SIGNAL_EXPIRED -> IDLE is valid."""
        validate_transition(TradeState.SIGNAL_EXPIRED, TradeState.IDLE)


class TestInvalidTransitions:
    """Test invalid state transitions."""

    def test_idle_to_trade_open_invalid(self):
        """IDLE -> TRADE_OPEN should fail (must go through signals)."""
        with pytest.raises(InvalidTransitionError) as exc_info:
            validate_transition(TradeState.IDLE, TradeState.TRADE_OPEN)

        assert "IDLE" in str(exc_info.value)
        assert "TRADE_OPEN" in str(exc_info.value)

    def test_trade_closed_to_trade_open_invalid(self):
        """TRADE_CLOSED -> TRADE_OPEN should fail (no reopening)."""
        with pytest.raises(InvalidTransitionError):
            validate_transition(TradeState.TRADE_CLOSED, TradeState.TRADE_OPEN)

    def test_signal_created_to_trade_closed_invalid(self):
        """SIGNAL_CREATED -> TRADE_CLOSED should fail (skip steps)."""
        with pytest.raises(InvalidTransitionError):
            validate_transition(TradeState.SIGNAL_CREATED, TradeState.TRADE_CLOSED)


class TestTransitionMap:
    """Test transition mapping completeness."""

    def test_all_states_have_transitions(self):
        """Every state should have defined transitions."""
        for state in TradeState:
            assert state in VALID_TRANSITIONS

    def test_transitions_are_sets(self):
        """All transition values should be sets."""
        for state, allowed in VALID_TRANSITIONS.items():
            assert isinstance(allowed, set)

    def test_no_self_transitions(self):
        """States should not transition to themselves."""
        for state, allowed in VALID_TRANSITIONS.items():
            assert state not in allowed
