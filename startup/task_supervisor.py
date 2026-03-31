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
import os
import time
from collections.abc import Callable, Coroutine

from loguru import logger

from core.health_probe import HealthProbe

__all__ = ["supervised_task"]

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
) -> None:
    """Run *coro_factory()* with automatic restart on crash.

    After *max_restarts* **consecutive** failures the task is abandoned
    and the health probe is marked dead.  If a task runs for longer than
    ``_SUCCESS_WINDOW`` seconds before crashing, the restart counter is
    reset — the assumption being that the task was healthy for a while
    and the crash is a new transient failure, not a persistent bug.

    Cooldown between restarts grows exponentially from *cooldown* up to
    ``_RESTART_COOLDOWN_MAX`` to avoid hammering a broken dependency.
    """
    restarts = 0
    while restarts <= max_restarts:
        if shutdown_event and shutdown_event.is_set():
            return
        try:
            logger.info(
                "[SUPERVISOR] Starting task '{}' (consecutive restarts: {}/{})",
                name,
                restarts,
                max_restarts,
            )
            started_at = time.monotonic()
            await coro_factory()
            return  # clean exit
        except asyncio.CancelledError:
            logger.info("[SUPERVISOR] Task '{}' cancelled", name)
            return
        except Exception as exc:
            elapsed = time.monotonic() - started_at if "started_at" in dir() else 0.0

            # If task survived long enough, treat crash as transient → reset counter
            if elapsed >= _SUCCESS_WINDOW:
                logger.info(
                    "[SUPERVISOR] Task '{}' ran for {:.0f}s before crash — "
                    "resetting restart counter (was {})",
                    name,
                    elapsed,
                    restarts,
                )
                restarts = 0

            restarts += 1
            delay = _exp_cooldown(restarts, cooldown, _RESTART_COOLDOWN_MAX)

            logger.error(
                "[SUPERVISOR] Task '{}' crashed: {} (restart {}/{}, "
                "next cooldown {:.1f}s, ran {:.1f}s)",
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
