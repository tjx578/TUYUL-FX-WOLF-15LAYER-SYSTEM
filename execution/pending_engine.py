"""
Pending Engine
Places PENDING orders ONLY based on L12 verdict.
"""

from loguru import logger
from execution.state_machine import ExecutionStateMachine
from execution.execution_guard import ExecutionGuard


class PendingEngine:
    def __init__(self):
        self.guard = ExecutionGuard()
        self.state = ExecutionStateMachine()

    def place(self, verdict: dict):
        if not self.guard.allow_execution(verdict):
            logger.warning("PendingEngine: execution blocked by guard")
            return

        order = {
            "symbol": verdict["symbol"],
            "direction": verdict["verdict"],
            "entry": verdict.get("entry"),
            "sl": verdict.get("sl"),
            "tp": verdict.get("tp"),
            "mode": verdict.get("execution_mode"),
        }

        self.state.set_pending(order)
        logger.info(f"\ud83d\udfe0 PENDING ORDER PLACED \u2192 {order}")
# Placeholder
