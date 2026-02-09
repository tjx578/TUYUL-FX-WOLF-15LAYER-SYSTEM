"""
Cancel Engine
Cancels pending orders based on M15 invalidation.
"""

from loguru import logger
from execution.state_machine import ExecutionStateMachine


class CancelEngine:
    def __init__(self):
        self.state = ExecutionStateMachine()

    def cancel(self, reason: str = "M15_INVALIDATION"):
        if not self.state.is_pending():
            return

        self.state.set_cancelled(reason)
        logger.warning(f"\u274c ORDER CANCELLED \u2192 {reason}")
