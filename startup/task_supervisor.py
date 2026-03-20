"""Auto-restart supervisor for long-running async tasks.

Zone: startup/ — process lifecycle, no execution side-effects.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Coroutine

from loguru import logger

from core.health_probe import HealthProbe

__all__ = ["supervised_task"]

_MAX_TASK_RESTARTS = int(os.getenv("MAX_TASK_RESTARTS", "5"))
_RESTART_COOLDOWN = float(os.getenv("RESTART_COOLDOWN_SEC", "5.0"))


async def supervised_task(
    name: str,
    coro_factory: Callable[[], Coroutine[object, object, object]],
    shutdown_event: asyncio.Event | None = None,
    health_probe: HealthProbe | None = None,
    max_restarts: int = _MAX_TASK_RESTARTS,
    cooldown: float = _RESTART_COOLDOWN,
) -> None:
    """Run *coro_factory()* with automatic restart on crash.

    After *max_restarts* consecutive failures the task is abandoned and
    the health probe is marked dead.
    """
    restarts = 0
    while restarts <= max_restarts:
        if shutdown_event and shutdown_event.is_set():
            return
        try:
            logger.info(f"[SUPERVISOR] Starting task '{name}' (attempt {restarts + 1})")
            await coro_factory()
            return  # clean exit
        except asyncio.CancelledError:
            logger.info(f"[SUPERVISOR] Task '{name}' cancelled")
            return
        except Exception as exc:
            restarts += 1
            logger.error(f"[SUPERVISOR] Task '{name}' crashed: {exc} (restart {restarts}/{max_restarts})")
            if restarts > max_restarts:
                logger.critical(f"[SUPERVISOR] Task '{name}' exceeded max restarts — giving up")
                if health_probe:
                    health_probe.set_alive(False)
                    health_probe.set_detail("dead_reason", f"{name}_crash_limit")
                return
            await asyncio.sleep(cooldown)
