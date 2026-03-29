"""Shared diagnostics utilities for degraded-mode hold-alive.

Provides both sync (threading.Event) and async (asyncio.Event) variants
of the hold-alive pattern used when a service crashes but the health
probe must stay responsive for operator inspection.

Used by: services/engine/runner.py, services/orchestrator/state_manager.py,
         services/ingest/ingest_worker.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal as _signal
import threading
import types

from loguru import logger

_DEFAULT_HOLD_TIMEOUT_SEC = 3600


def hold_alive_sync(*, service_name: str = "service") -> None:
    """Block the current thread so a daemon-thread health probe stays responsive.

    Exits on SIGTERM/SIGINT or after ``DEGRADED_HOLD_TIMEOUT_SEC`` (default 3600s).
    """
    hold_timeout = int(os.environ.get("DEGRADED_HOLD_TIMEOUT_SEC", str(_DEFAULT_HOLD_TIMEOUT_SEC)))
    logger.warning(
        "{} holding alive for health probe diagnostics (max {}s). Send SIGTERM to exit.",
        service_name,
        hold_timeout,
    )
    shutdown = threading.Event()

    def _on_signal(signum: int, _frame: types.FrameType | None) -> None:
        logger.info("Received {} — exiting degraded hold", _signal.Signals(signum).name)
        shutdown.set()

    _signal.signal(_signal.SIGTERM, _on_signal)
    _signal.signal(_signal.SIGINT, _on_signal)
    if not shutdown.wait(timeout=hold_timeout):
        logger.warning("Degraded hold timeout ({}s) — exiting for auto-restart", hold_timeout)


async def hold_alive_async(*, service_name: str = "service") -> None:
    """Async variant — awaits until SIGTERM/SIGINT or timeout.

    Suitable for callers already inside an ``asyncio.run()`` context.
    """
    hold_timeout = int(os.environ.get("DEGRADED_HOLD_TIMEOUT_SEC", str(_DEFAULT_HOLD_TIMEOUT_SEC)))
    logger.warning(
        "{} degraded hold active (max {}s). Send SIGTERM to exit.",
        service_name,
        hold_timeout,
    )
    shutdown = asyncio.Event()

    def _on_signal(signum: int, _frame: types.FrameType | None) -> None:
        logger.info("Received {} — exiting degraded hold", _signal.Signals(signum).name)
        shutdown.set()

    _signal.signal(_signal.SIGTERM, _on_signal)
    _signal.signal(_signal.SIGINT, _on_signal)
    with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
        await asyncio.wait_for(shutdown.wait(), timeout=hold_timeout)
    if not shutdown.is_set():
        logger.warning("Degraded hold timeout ({}s) — exiting for auto-restart", hold_timeout)
