"""Auto-restart supervisor for long-running async tasks.

Zone: startup/ — process lifecycle, no execution side-effects.

Resilience strategy:
  - Exponential cooldown between restarts (base 5s → max 120s)
  - Consecutive restart counter resets after a task runs successfully
    for longer than ``RESTART_SUCCESS_WINDOW_SEC`` (default 120s)
  - Higher default max restarts (20) suitable for VPS / flaky networks
  - Prometheus-friendly structured logging for observability
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import Callable, Coroutine

from loguru import logger

from core.health_probe import HealthProbe

__all__ = ["RequiredTaskFailedError", "supervised_task"]

_MAX_TASK_RESTARTS = int(os.getenv("MAX_TASK_RESTARTS", "20"))  # Was 5
_RESTART_COOLDOWN = float(os.getenv("RESTART_COOLDOWN_SEC", "5.0"))
_RESTART_COOLDOWN_MAX = float(os.getenv("RESTART_COOLDOWN_MAX_SEC", "120.0"))
_SUCCESS_WINDOW = float(os.getenv("RESTART_SUCCESS_WINDOW_SEC", "120.0"))


def _exp_cooldown(attempt: int, base: float, maximum: float) -> float:
    """Exponential cooldown: base * 2^(attempt-1), capped at maximum."""
    return min(base * (2 ** max(0, attempt - 1)), maximum)


async def supervised_task(
    name: str,
    coro_factory: Callable[[], Coroutine[object, object, object]],
    shutdown_event: asyncio.Event | None = None,
    health_probe: HealthProbe | None = None,
    max_restarts: int = _MAX_TASK_RESTARTS,
    cooldown: float = _RESTART_COOLDOWN,
    *,
    required: bool = False,
    state_callback: Callable[[str, str], None] | None = None,
) -> None:
    """Run *coro_factory()* with automatic restart on crash.

    After *max_restarts* **consecutive** failures the task is abandoned
    and the health probe is marked dead.  If a task runs for longer than
    ``_SUCCESS_WINDOW`` seconds before crashing, the restart counter is
    reset — the assumption being that the task was healthy for a while
    and the crash is a new transient failure, not a persistent bug.

    Required long-running tasks treat unexpected completion as failure and raise
    after the restart budget, so the process owner can exit nonzero. A failure
    latches health/readiness closed unless an explicit state callback owns
    readiness recovery after role bootstrap is proven again. Optional
    intentionally completed tasks retain their existing behavior.

    Cooldown between restarts grows exponentially from *cooldown* up to
    ``_RESTART_COOLDOWN_MAX`` to avoid hammering a broken dependency.
    """
    if required:
        await _supervise_required(
            name, coro_factory, shutdown_event, health_probe, max_restarts, cooldown, state_callback
        )
        return
    restarts = 0
    while restarts <= max_restarts:
        if shutdown_event and shutdown_event.is_set():
            return
        started_at = time.monotonic()
        try:
            logger.info(
                "[SUPERVISOR] Starting task '{}' (consecutive restarts: {}/{})",
                name,
                restarts,
                max_restarts,
            )
            await coro_factory()
            return  # intentional optional exit or requested shutdown
        except asyncio.CancelledError:
            logger.info("[SUPERVISOR] Task '{}' cancelled", name)
            return
        except Exception as exc:
            elapsed = time.monotonic() - started_at

            # If task survived long enough, treat crash as transient → reset counter
            if elapsed >= _SUCCESS_WINDOW:
                logger.info(
                    "[SUPERVISOR] Task '{}' ran for {:.0f}s before crash — resetting restart counter (was {})",
                    name,
                    elapsed,
                    restarts,
                )
                restarts = 0

            restarts += 1
            delay = _exp_cooldown(restarts, cooldown, _RESTART_COOLDOWN_MAX)

            logger.error(
                "[SUPERVISOR] Task '{}' crashed: {} (restart {}/{}, next cooldown {:.1f}s, ran {:.1f}s)",
                name,
                exc,
                restarts,
                max_restarts,
                delay,
                elapsed,
            )

            if restarts > max_restarts:
                logger.critical(
                    "[SUPERVISOR] Task '{}' exceeded max restarts ({}) — giving up",
                    name,
                    max_restarts,
                )
                if health_probe:
                    health_probe.set_alive(False)
                    health_probe.set_detail("dead_reason", f"{name}_crash_limit")
                return
            await asyncio.sleep(delay)


class RequiredTaskFailedError(RuntimeError):
    """Fixed-category required-worker failure; never carry exception contents."""

    def __init__(self, name: str, cause: str):
        self.task_name = name
        self.cause = cause
        super().__init__(f"REQUIRED_TASK_FAILED:{name}:{cause}")


async def _supervise_required(name, coro_factory, shutdown_event, health_probe, max_restarts, cooldown, state_callback):
    """Required callers opt in; readiness is granted by their actual bootstrap.

    The process owner sets shutdown_event before cancelling this supervisor.
    An unsolicited cancellation, including a self-cancelling worker, consumes
    the same finite retry policy as an exception or unexpected return.
    """
    if type(max_restarts) is not int or max_restarts < 0:
        raise ValueError("REQUIRED_TASK_RESTART_LIMIT_INVALID")

    def stopping():
        return shutdown_event is not None and shutdown_event.is_set()

    def publish(state):
        if state_callback is not None:
            state_callback(name, state)

    def failed(cause):
        publish("FAILED")
        if health_probe is not None:
            health_probe.set_readiness_check(lambda: False)
            health_probe.set_alive(False)
            health_probe.set_detail("dead_reason", f"{name}_crash_limit")
        raise RequiredTaskFailedError(name, cause) from None

    restarts = 0
    while True:
        if stopping():
            publish("STOPPED")
            return
        publish("STARTING")
        started_at = time.monotonic()
        try:
            await coro_factory()
            cause = "returned"
        except asyncio.CancelledError:
            cause = "cancelled"
        except Exception:
            cause = "exception"
        if stopping() and cause != "exception":
            publish("STOPPED")
            return
        if stopping():
            # A real worker failure racing an orderly stop is still a failure.
            # Preserve it for the process owner after siblings have drained.
            failed(cause)
        if health_probe is not None and state_callback is None:
            health_probe.set_readiness_check(lambda: False)
            health_probe.set_alive(False)
            health_probe.set_detail("dead_reason", f"{name}_required_task_failed")
        elapsed = time.monotonic() - started_at
        if elapsed >= _SUCCESS_WINDOW:
            restarts = 0
        restarts += 1
        publish("RESTARTING")
        logger.error("[SUPERVISOR] Required task '{}' {} (restart {}/{})", name, cause, restarts, max_restarts)
        if restarts > max_restarts:
            failed(cause)
        delay = _exp_cooldown(restarts, cooldown, _RESTART_COOLDOWN_MAX)
        try:
            if shutdown_event is None:
                await asyncio.sleep(delay)
            else:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(shutdown_event.wait(), timeout=delay)
        except asyncio.CancelledError:
            if stopping():
                publish("STOPPED")
                return
            # Cancellation during restart delay is also required-worker loss.
            restarts += 1
            if restarts > max_restarts:
                failed("cancelled")
