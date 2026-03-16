"""
Cancel Engine
Cancels pending orders based on M15 invalidation.
"""

from loguru import logger

from execution.state_machine import ExecutionStateMachine


class CancelEngine:
    def __init__(self):
        self._registry = ExecutionStateMachine()

    def cancel(self, symbol: str, reason: str = "M15_INVALIDATION"):
        sm = self._registry.get(symbol)
        if not sm.is_pending():
            return

        sm.set_cancelled(reason)
        logger.warning("\u274c ORDER CANCELLED for {} \u2192 {}", symbol, reason)


# Placeholder
