import pytest  # pyright: ignore[reportMissingImports]

from execution.cancel_engine import CancelEngine
from execution.state_machine import ExecutionStateMachine


@pytest.fixture(autouse=True)
def reset_state_machine():
    sm = ExecutionStateMachine()
    sm._init()
    return sm


def test_cancel_changes_pending_state(reset_state_machine):
    sm = reset_state_machine
    sm.set_pending({"symbol": "XAUUSD"})

    CancelEngine().cancel("M15_INVALIDATION")

    snapshot = sm.snapshot()
    assert snapshot["state"] == "CANCELLED"
    assert snapshot["reason"] == "M15_INVALIDATION"


def test_cancel_is_noop_when_not_pending(reset_state_machine):
    sm = reset_state_machine

    CancelEngine().cancel("NO_PENDING")

    snapshot = sm.snapshot()
    assert snapshot["state"] == "IDLE"
    assert snapshot["reason"] is None
