"""
Dashboard State
Mirror of Context + Execution + L12
"""

from context.live_context_bus import LiveContextBus
from execution.state_machine import ExecutionStateMachine


class DashboardState:
    def __init__(self):
        self.context = LiveContextBus()
        self.execution = ExecutionStateMachine()
        self._verdict = None

    def update_verdict(self, verdict: dict):
        # called by verdict engine (read-only mirror)
        self._verdict = verdict

    def get_context(self):
        return self.context.snapshot()

    def get_execution(self):
        return self.execution.snapshot()

    def get_verdict(self):
        return self._verdict
