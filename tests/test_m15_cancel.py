import pytest

from execution.cancel_engine import CancelEngine
from execution.state_machine import ExecutionStateMachine


@pytest.fixture(autouse=True)
def reset_state_machine():
    registry = ExecutionStateMachine()
    registry.reset_all()
    return registry


def test_cancel_changes_pending_state(reset_state_machine):
    registry = reset_state_machine
    sm = registry.get("XAUUSD")
    sm.set_pending({"symbol": "XAUUSD"})

    CancelEngine().cancel("XAUUSD", "M15_INVALIDATION")

    snapshot = sm.snapshot()
    assert snapshot["state"] == "CANCELLED"
    assert snapshot["reason"] == "M15_INVALIDATION"


def test_cancel_is_noop_when_not_pending(reset_state_machine):
    registry = reset_state_machine
    sm = registry.get("EURUSD")

    CancelEngine().cancel("EURUSD", "NO_PENDING")

    snapshot = sm.snapshot()
    assert snapshot["state"] == "IDLE"
    assert snapshot["reason"] is None
