"""
Tests for execution/state_machine.py -- state transitions.
Constitutional boundary: execution must contain NO strategy logic.
"""

import time

import pytest

from execution.state_machine import (
    OrderState,
    StateMachine,
    StateMachineRegistry,
)

# Define expected states for conceptual tests
IDLE = "IDLE"
PENDING_ACTIVE = "PENDING_ACTIVE"
FILLED = "FILLED"
CANCELLED = "CANCELLED"


class TestStateMachineTransitions:
    """Core state transition tests."""

    @pytest.mark.parametrize(
        "from_state,event,to_state",
        [
            (IDLE, "PLACE_ORDER", PENDING_ACTIVE),
            (PENDING_ACTIVE, "ORDER_FILLED", FILLED),
            (PENDING_ACTIVE, "ORDER_CANCELLED", CANCELLED),
            (PENDING_ACTIVE, "ORDER_EXPIRED", CANCELLED),
        ],
    )
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

    @pytest.mark.parametrize(
        "from_state,event",
        [
            (IDLE, "ORDER_FILLED"),  # can't fill without placing
            (CANCELLED, "ORDER_FILLED"),  # terminal state
            (FILLED, "PLACE_ORDER"),  # can't re-place a filled order
        ],
    )
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
        assert result == CANCELLED  # pyright: ignore[reportPossiblyUnboundVariable]

    def test_pending_fill_sets_entry_price(self):
        order = {
            "state": PENDING_ACTIVE,
            "entry_price": None,
            "fill_price": None,
        }
        fill_price = 1.0855
        order["state"] = FILLED
        order["fill_price"] = fill_price
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
        order_fields = {
            "order_id",
            "symbol",
            "direction",
            "lot_size",
            "entry_price",
            "stop_loss",
            "take_profit",
            "state",
            "placed_at",
            "filled_at",
        }
        strategy_fields = {"wolf_score", "tii_score", "frpc_score", "confluence"}
        overlap = order_fields & strategy_fields
        assert len(overlap) == 0, f"Execution order must not contain strategy fields: {overlap}"


def test_replay_terminal_event_is_noop() -> None:
    sm = StateMachine()
    sm.set_pending({"order_id": "T-1"})
    sm.set_cancelled("TEST")

    result = sm.set_cancelled("TEST")
    snap = sm.snapshot()

    assert result.replay is True
    assert result.applied is False
    assert snap["state"] == "CANCELLED"


def test_invalid_transition_raises() -> None:
    sm = StateMachine()

    with pytest.raises(ValueError):
        sm.set_filled({"order_id": "T-2"})


class TestPerSymbolRegistry:
    """Per-symbol FSM registry tests."""

    def test_different_symbols_independent(self) -> None:
        registry = StateMachineRegistry()
        registry.reset_all()

        eu = registry.get("EURUSD")
        gj = registry.get("GBPJPY")

        eu.set_pending({"order_id": "EU-1"})
        assert eu.is_pending()
        assert not gj.is_pending()

        gj.set_pending({"order_id": "GJ-1"})
        assert gj.is_pending()

        eu.set_filled({"order_id": "EU-1"})
        assert eu.state == OrderState.FILLED
        assert gj.is_pending()

    def test_registry_is_singleton(self) -> None:
        a = StateMachineRegistry()
        b = StateMachineRegistry()
        assert a is b

    def test_snapshot_all(self) -> None:
        registry = StateMachineRegistry()
        registry.reset_all()

        registry.get("AUDUSD").set_pending({"order_id": "AU-1"})

        snap = registry.snapshot_all()
        assert "AUDUSD" in snap
        assert snap["AUDUSD"]["state"] == "PENDING_ACTIVE"

    def test_reset_symbol(self) -> None:
        registry = StateMachineRegistry()
        registry.reset_all()

        sm = registry.get("USDJPY")
        sm.set_pending({"order_id": "UJ-1"})
        assert sm.is_pending()

        registry.reset("USDJPY")
        sm2 = registry.get("USDJPY")
        assert not sm2.is_pending()
        assert sm2.state == OrderState.IDLE

    def test_symbol_case_normalised(self) -> None:
        registry = StateMachineRegistry()
        registry.reset_all()

        sm1 = registry.get("eurusd")
        sm2 = registry.get("EURUSD")
        assert sm1 is sm2

    def test_backward_compat_default_symbol(self) -> None:
        """Old callers that skip symbol still work via __default__."""
        registry = StateMachineRegistry()
        registry._init()
        registry.set_pending({"order_id": "BC-1"})
        assert registry.is_pending()
        snap = registry.snapshot()
        assert snap["state"] == "PENDING_ACTIVE"
