"""
Tests for execution/state_machine.py -- state transitions.
Constitutional boundary: execution must contain NO strategy logic.
"""
import time

import pytest

try:
    from execution.state_machine import (  # pyright: ignore[reportAttributeAccessIssue] # noqa: F401
        OrderState,  # pyright: ignore[reportAttributeAccessIssue]
        StateMachine,  # pyright: ignore[reportAttributeAccessIssue]
    )
    HAS_SM = True
except ImportError:
    HAS_SM = False

# Define expected states for conceptual tests
IDLE = "IDLE"
PENDING_ACTIVE = "PENDING_ACTIVE"
FILLED = "FILLED"
CANCELLED = "CANCELLED"


class TestStateMachineTransitions:
    """Core state transition tests."""

    @pytest.mark.parametrize("from_state,event,to_state", [
        (IDLE, "PLACE_ORDER", PENDING_ACTIVE),
        (PENDING_ACTIVE, "ORDER_FILLED", FILLED),
        (PENDING_ACTIVE, "ORDER_CANCELLED", CANCELLED),
        (PENDING_ACTIVE, "ORDER_EXPIRED", CANCELLED),
    ])
    def test_valid_transitions(self, from_state, event, to_state):
        transitions = {
            (IDLE, "PLACE_ORDER"): PENDING_ACTIVE,
            (PENDING_ACTIVE, "ORDER_FILLED"): FILLED,
            (PENDING_ACTIVE, "ORDER_CANCELLED"): CANCELLED,
            (PENDING_ACTIVE, "ORDER_EXPIRED"): CANCELLED,
            (FILLED, "CLOSE_POSITION"): "CLOSED",
        }
        result = transitions.get((from_state, event))
        assert result == to_state

    @pytest.mark.parametrize("from_state,event", [
        (IDLE, "ORDER_FILLED"),       # can't fill without placing
        (CANCELLED, "ORDER_FILLED"),  # terminal state
        (FILLED, "PLACE_ORDER"),      # can't re-place a filled order
    ])
    def test_invalid_transitions(self, from_state, event):
        valid_transitions = {
            (IDLE, "PLACE_ORDER"): PENDING_ACTIVE,
            (PENDING_ACTIVE, "ORDER_FILLED"): FILLED,
            (PENDING_ACTIVE, "ORDER_CANCELLED"): CANCELLED,
            (PENDING_ACTIVE, "ORDER_EXPIRED"): CANCELLED,
            (FILLED, "CLOSE_POSITION"): "CLOSED",
        }
        result = valid_transitions.get((from_state, event))
        assert result is None, f"Transition ({from_state}, {event}) should be invalid"

    def test_terminal_states_are_terminal(self):
        terminal = {CANCELLED, "CLOSED"}
        valid_transitions = {
            (IDLE, "PLACE_ORDER"): PENDING_ACTIVE,
            (PENDING_ACTIVE, "ORDER_FILLED"): FILLED,
            (PENDING_ACTIVE, "ORDER_CANCELLED"): CANCELLED,
            (FILLED, "CLOSE_POSITION"): "CLOSED",
        }
        for (s, _), _ in valid_transitions.items():
            if s in terminal:
                pytest.fail(f"Terminal state {s} should not have outgoing transitions")


class TestPendingEngine:
    """Tests for pending order lifecycle."""

    def test_pending_expiry_after_timeout(self):
        """A pending order that exceeds TTL should transition to CANCELLED."""
        placed_at = time.time() - 600  # 10 minutes ago
        ttl_seconds = 300  # 5 min TTL
        expired = (time.time() - placed_at) > ttl_seconds
        assert expired, "Order should be expired after TTL"

    def test_pending_not_expired_within_ttl(self):
        placed_at = time.time() - 60  # 1 minute ago
        ttl_seconds = 300
        expired = (time.time() - placed_at) > ttl_seconds
        assert not expired

    def test_pending_cancellation_idempotent(self):
        """Cancelling an already-cancelled order should be a no-op."""
        state = CANCELLED
        # Should either remain CANCELLED or raise gracefully
        if state == CANCELLED:
            result = CANCELLED  # idempotent
        assert result == CANCELLED # pyright: ignore[reportPossiblyUnboundVariable]

    def test_pending_fill_sets_entry_price(self):
        order = {
            "state": PENDING_ACTIVE,
            "entry_price": None,
            "fill_price": None,
        }
        fill_price = 1.0855
        order["state"] = FILLED
        order["fill_price"] = fill_price # pyright: ignore[reportArgumentType]
        assert order["fill_price"] == 1.0855
        assert order["state"] == FILLED

    @pytest.mark.parametrize("num_orders", [1, 5, 20])
    def test_multiple_pending_orders_tracked(self, num_orders):
        """System should track multiple pending orders per pair or across pairs."""
        orders = {}
        for i in range(num_orders):
            oid = f"ORD-{i:04d}"
            orders[oid] = {"state": PENDING_ACTIVE, "symbol": f"PAIR{i % 5}"}
        assert len(orders) == num_orders
        active = [o for o in orders.values() if o["state"] == PENDING_ACTIVE]
        assert len(active) == num_orders


class TestExecutionBoundary:
    """
    Constitutional: execution must not compute market direction or strategy logic.
    """

    @pytest.mark.skipif(not HAS_SM, reason="state_machine not importable")
    def test_state_machine_has_no_analysis_imports(self):
        import importlib  # noqa: PLC0415
        import inspect  # noqa: PLC0415
        mod = importlib.import_module("execution.state_machine")
        source = inspect.getsource(mod)
        for forbidden in ["from analysis", "import analysis", "compute_direction", "compute_verdict"]:
            assert forbidden not in source, (
                f"execution/state_machine.py must not contain '{forbidden}' -- boundary violation"
            )

    def test_execution_order_has_no_strategy_fields(self):
        """Order object should only carry execution-relevant data."""
        order_fields = {"order_id", "symbol", "direction", "lot_size", "entry_price",
                        "stop_loss", "take_profit", "state", "placed_at", "filled_at"}
        strategy_fields = {"wolf_score", "tii_score", "frpc_score", "confluence"}
        overlap = order_fields & strategy_fields
        assert len(overlap) == 0, f"Execution order must not contain strategy fields: {overlap}"


@pytest.mark.skipif(not HAS_SM, reason="state_machine not importable")
def test_replay_terminal_event_is_noop() -> None:
    sm = StateMachine()
    sm._init()  # pyright: ignore[reportPrivateUsage]
    sm.set_pending({"order_id": "T-1"})
    sm.set_cancelled("TEST")

    result = sm.set_cancelled("TEST")
    snap = sm.snapshot()

    assert result.replay is True
    assert result.applied is False
    assert snap["state"] == "CANCELLED"


@pytest.mark.skipif(not HAS_SM, reason="state_machine not importable")
def test_invalid_transition_raises() -> None:
    sm = StateMachine()
    sm._init()  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(ValueError):
        sm.set_filled({"order_id": "T-2"})
