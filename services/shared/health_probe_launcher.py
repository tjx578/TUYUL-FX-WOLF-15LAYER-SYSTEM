"""Shared health-probe launcher utilities.

Provides two consistent patterns for starting a :class:`HealthProbe`:

* **Thread pattern** – daemon thread with an isolated event loop.
  Use for services that perform blocking startup (DB preflight, heavy
  sync imports) *before* the main ``asyncio`` loop is running.

* **Task pattern** – ``asyncio.create_task`` in the current loop.
  Use for services already executing inside an async context.

Both helpers handle probe construction, optional readiness-check,
extra detail injection, and logging so that call-sites stay minimal.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any

from loguru import logger

from core.health_probe import HealthProbe


def start_probe_in_thread(
    *,
    port: int,
    service_name: str,
    readiness_check: Callable[[], bool] | None = None,
    extra_details: dict[str, str] | None = None,
) -> HealthProbe:
    """Launch a :class:`HealthProbe` on a daemon thread (isolated loop).

    Returns the *probe* instance so the caller can call
    :meth:`~HealthProbe.set_detail` later if needed.
    """
    probe = HealthProbe(
        port=port,
        service_name=service_name,
        readiness_check=readiness_check,
    )
    if extra_details:
        for key, value in extra_details.items():
            probe.set_detail(key, value)

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(probe.start())
        except Exception:
            logger.warning("{} health-probe thread stopped", service_name)
        finally:
            loop.close()

    t = threading.Thread(
        target=_run,
        daemon=True,
        name=f"{service_name}-health-probe",
    )
    t.start()
    logger.info("{} health probe listening on :{}", service_name.capitalize(), port)
    return probe


async def start_probe_as_task(
    *,
    port: int,
    service_name: str,
    readiness_check: Callable[[], bool] | None = None,
    extra_details: dict[str, str] | None = None,
    task_name: str | None = None,
) -> tuple[HealthProbe, asyncio.Task[Any]]:
    """Launch a :class:`HealthProbe` as an ``asyncio`` task.

    Returns ``(probe, task)`` so callers can cancel/await the task on
    shutdown and access the probe for later detail updates.
    """
    probe = HealthProbe(
        port=port,
        service_name=service_name,
        readiness_check=readiness_check,
    )
    if extra_details:
        for key, value in extra_details.items():
            probe.set_detail(key, value)

    name = task_name or f"{service_name.capitalize()}HealthProbe"
    task: asyncio.Task[Any] = asyncio.create_task(probe.start(), name=name)
    logger.info("{} health probe listening on :{}", service_name.capitalize(), port)
    return probe, task
