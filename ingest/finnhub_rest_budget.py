"""Process-wide pacing and cooldown for Finnhub REST requests.

All ``FinnhubCandleFetcher`` instances in an ingest process share this
coordinator.  That prevents independently scheduled warmup, repair, and HTF
jobs from creating a burst even when each job is locally rate limited.
"""

from __future__ import annotations

import asyncio
import threading
import time
import weakref
from dataclasses import dataclass


class FinnhubRestCooldownError(RuntimeError):
    """Raised before I/O when Finnhub REST is in a process-wide cooldown."""

    def __init__(self, retry_after_sec: float) -> None:
        self.retry_after_sec = max(0.0, float(retry_after_sec))
        super().__init__(f"Finnhub REST cooldown active; retry in {self.retry_after_sec:.1f}s")


@dataclass
class _LoopPacingState:
    lock: asyncio.Lock
    next_request_at: float = 0.0


class FinnhubRestBudget:
    """Coordinate REST request spacing and cooldown across fetcher instances."""

    def __init__(self) -> None:
        self._state_lock = threading.Lock()
        self._loop_states: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopPacingState] = (
            weakref.WeakKeyDictionary()
        )
        self._cooldown_until = 0.0

    def _loop_state(self) -> _LoopPacingState:
        loop = asyncio.get_running_loop()
        with self._state_lock:
            state = self._loop_states.get(loop)
            if state is None:
                state = _LoopPacingState(lock=asyncio.Lock())
                self._loop_states[loop] = state
            return state

    def cooldown_remaining(self) -> float:
        """Return seconds until process-wide REST traffic may resume."""
        with self._state_lock:
            return max(0.0, self._cooldown_until - time.monotonic())

    def defer_for(self, seconds: float) -> None:
        """Extend the global cooldown without shortening an existing one."""
        delay = max(0.0, float(seconds))
        with self._state_lock:
            self._cooldown_until = max(
                self._cooldown_until,
                time.monotonic() + delay,
            )

    async def wait_for_slot(self, delay_seconds: float) -> None:
        """Reserve one globally paced request slot, or fail during cooldown."""
        remaining = self.cooldown_remaining()
        if remaining > 0:
            raise FinnhubRestCooldownError(remaining)

        state = self._loop_state()
        async with state.lock:
            remaining = self.cooldown_remaining()
            if remaining > 0:
                raise FinnhubRestCooldownError(remaining)

            now = time.monotonic()
            wait_for = state.next_request_at - now
            if wait_for > 0:
                await asyncio.sleep(wait_for)

            state.next_request_at = max(state.next_request_at, time.monotonic()) + max(0.0, float(delay_seconds))

    def reset_for_tests(self) -> None:
        """Clear process state. Intended only for isolated unit tests."""
        with self._state_lock:
            self._loop_states = weakref.WeakKeyDictionary()
            self._cooldown_until = 0.0


finnhub_rest_budget = FinnhubRestBudget()
