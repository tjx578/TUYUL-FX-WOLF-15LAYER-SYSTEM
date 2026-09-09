"""One owner for required async task state, readiness and fatal exit signals."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any


class RequiredTaskSupervisor:
    def __init__(self, requirements: dict[str, bool]):
        self.states = {name: "STARTING" if enabled else "DISABLED" for name, enabled in requirements.items()}
        self.tasks: dict[str, asyncio.Task] = {}
        self.failure_reasons: dict[str, str] = {}
        self.fatal = asyncio.Event()
        self.stopping = False

    def fail(self, name: str, cause: str) -> None:
        self.states[name] = "FAILED"
        self.failure_reasons[name] = cause
        self.fatal.set()

    def start(self, name: str, coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task:
        if self.states.get(name) != "STARTING" or self.stopping:
            coroutine.close()
            raise RuntimeError("TASK_START_NOT_ALLOWED")
        task = asyncio.create_task(coroutine, name=name)
        self.tasks[name] = task
        self.states[name] = "RUNNING"
        task.add_done_callback(lambda completed: self._observe(name, completed))
        return task

    def _observe(self, name: str, task: asyncio.Task) -> None:
        if not task.done():
            return
        # Retrieve exceptions even during shutdown, without exposing their text.
        cause = "cancelled" if task.cancelled() else "exception" if task.exception() is not None else "returned"
        if self.stopping:
            if self.states[name] != "FAILED":
                self.states[name] = "STOPPED"
        else:
            self.fail(name, cause)

    def snapshot(self) -> dict:
        for name, task in self.tasks.items():
            self._observe(name, task)
        reasons = [f"required_task_{name}_{cause}" for name, cause in sorted(self.failure_reasons.items())]
        reasons.extend(
            f"required_task_{name}_not_started" for name, state in self.states.items() if state == "STARTING"
        )
        if self.stopping:
            reasons.append("runtime_stopping")
        return {"ready": not reasons, "states": dict(self.states), "reasons": reasons}

    async def stop(self, timeout: float = 10.0) -> None:
        self.stopping = True
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        if self.tasks:
            _, pending = await asyncio.wait(self.tasks.values(), timeout=timeout)
            if pending:
                # Caller must not close pools used by a still-running task.
                self.fail("shutdown", "drain_timeout")
                raise TimeoutError("REQUIRED_TASK_DRAIN_TIMEOUT")
        for name, task in self.tasks.items():
            self._observe(name, task)
