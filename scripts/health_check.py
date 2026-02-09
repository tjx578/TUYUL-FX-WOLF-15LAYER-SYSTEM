import sys
from context.live_context_bus import LiveContextBus
from execution.state_machine import ExecutionStateMachine


def health_check():
    context = LiveContextBus()
    execution = ExecutionStateMachine()

    snapshot = context.snapshot()
    state = execution.snapshot()

    if snapshot is None:
        print("❌ SYSTEM HEALTH: FAILED - Context snapshot is None", file=sys.stderr)
        sys.exit(1)
    
    valid_states = ["IDLE", "PENDING_ACTIVE", "CANCELLED", "FILLED"]
    if state["state"] not in valid_states:
        print(f"❌ SYSTEM HEALTH: FAILED - Invalid state: {state['state']}", file=sys.stderr)
        sys.exit(1)

    print("✅ SYSTEM HEALTH: OK")


if __name__ == "__main__":
    health_check()
