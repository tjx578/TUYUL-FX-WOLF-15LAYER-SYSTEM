from context.live_context_bus import LiveContextBus
from execution.state_machine import ExecutionStateMachine


def health_check():
    context = LiveContextBus()
    execution = ExecutionStateMachine()

    snapshot = context.snapshot()
    state = execution.snapshot()

    assert snapshot is not None
    assert state["state"] in ["IDLE", "PENDING_ACTIVE", "CANCELLED", "FILLED"]

    print("✅ SYSTEM HEALTH: OK")


if __name__ == "__main__":
    health_check()
