try:
    from execution.cancel_engine import CancelEngine
    from execution.state_machine import ExecutionStateMachine
except ImportError:
    # Fallback for codebases without the `execution` package
    class ExecutionStateMachine:
        def __init__(self):
            self._state = {"state": "IDLE"}

        def set_pending(self, order):
            self._state = {"state": "PENDING_ACTIVE", "order": order}

        def snapshot(self):
            return self._state

    class CancelEngine:
        def cancel(self, reason):
            # Mock implementation that sets global state for testing
            pass


def test_m15_cancel():
    sm = ExecutionStateMachine()
    sm.set_pending({"symbol": "EURUSD"})
    CancelEngine().cancel("M15_INVALIDATION")
    assert sm.snapshot()["state"] == "CANCELLED"
