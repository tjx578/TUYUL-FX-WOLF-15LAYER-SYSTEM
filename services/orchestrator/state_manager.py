"""Runtime state manager for governance mode transitions."""

import time
from dataclasses import dataclass

from loguru import logger

from services.orchestrator.execution_mode import ExecutionMode


@dataclass(slots=True)
class OrchestratorState:
    mode: ExecutionMode = ExecutionMode.NORMAL
    reason: str = "startup"


class StateManager:
    def __init__(self) -> None:
        self._state = OrchestratorState()

    def snapshot(self) -> OrchestratorState:
        return self._state

    def set_mode(self, mode: ExecutionMode, reason: str) -> OrchestratorState:
        self._state = OrchestratorState(mode=mode, reason=reason)
        return self._state


def run() -> None:
    manager = StateManager()
    logger.info("wolf15-orchestrator started in {}", manager.snapshot().mode)
    while True:
        time.sleep(5)


if __name__ == "__main__":
    run()
