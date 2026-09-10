from execution.cancel_engine import CancelEngine
from execution.state_machine import ExecutionStateMachine


def test_m15_cancel():
    sm = ExecutionStateMachine()
    sm.set_pending({"symbol": "EURUSD"})
    CancelEngine().cancel("M15_INVALIDATION")
    assert sm.snapshot()["state"] == "CANCELLED"
