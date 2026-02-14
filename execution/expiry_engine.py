"""
Expiry Engine
Time-based pending order expiration (H1 count).
"""

from loguru import logger

from execution.state_machine import ExecutionStateMachine


class ExpiryEngine:
    def __init__(self, max_h1_bars: int = 3):
        self.state = ExecutionStateMachine()
        self.max_h1_bars = max_h1_bars

    def check_expiry(self, elapsed_h1: int):
        if not self.state.is_pending():
            return

        if elapsed_h1 >= self.max_h1_bars:
            self.state.set_cancelled("H1_EXPIRY")
            logger.warning("⏱️ ORDER EXPIRED (H1 COUNT)")


# Placeholder
