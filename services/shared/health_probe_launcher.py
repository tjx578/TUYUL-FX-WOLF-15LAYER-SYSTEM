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
import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self

from loguru import logger

from core.health_probe import HealthProbe


@dataclass(slots=True)
class _ThreadRuntimeState:
    event_loop: asyncio.AbstractEventLoop | None = None
    async_stop: asyncio.Event | None = None
    loop_ready: threading.Event = field(default_factory=threading.Event)
    stop_requested: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    failure: BaseException | None = None


@dataclass(slots=True)
class HealthProbeRuntime:
    """Own a thread-launched health probe and its isolated event loop."""

    probe: HealthProbe
    thread: threading.Thread
    _state: _ThreadRuntimeState = field(repr=False)

    @property
    def event_loop(self) -> asyncio.AbstractEventLoop:
        """Return the isolated loop after launcher readiness is established."""
        loop = self._state.event_loop
        if loop is None:
            raise RuntimeError("health-probe event loop is not ready")
        return loop

    def stop(self) -> None:
        """Request shutdown; safe to call repeatedly and from any thread."""
        self._state.stop_requested.set()
        if self._state.finished.is_set():
            return

        loop = self._state.event_loop
        async_stop = self._state.async_stop
        if loop is None or async_stop is None:
            return
        try:
            loop.call_soon_threadsafe(async_stop.set)
        except RuntimeError:
            if not self._state.finished.is_set():
                raise

    def join(self, timeout: float = 5.0) -> None:
        """Join within *timeout* seconds or fail with the thread still alive."""
        if timeout < 0:
            raise ValueError("health-probe join timeout must be non-negative")
        self.thread.join(timeout)
        if self.thread.is_alive():
            raise TimeoutError(f"health-probe thread {self.thread.name!r} did not stop within {timeout}s")
        if self._state.failure is not None:
            raise RuntimeError(f"health-probe thread {self.thread.name!r} failed") from self._state.failure

    def close(self, timeout: float = 5.0) -> None:
        """Request shutdown and wait for complete resource release."""
        self.stop()
        self.join(timeout)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def start_probe_in_thread(
    *,
    port: int,
    service_name: str,
    readiness_check: Callable[[], bool] | None = None,
    extra_details: dict[str, str] | None = None,
) -> HealthProbeRuntime:
    """Launch a :class:`HealthProbe` on a daemon thread (isolated loop).

    Returns an explicit runtime owner. Callers that retain the handle must
    call ``stop()`` and bounded ``join()`` (or use it as a context manager).
    The probe remains available through ``runtime.probe``.
    """
    probe = HealthProbe(
        port=port,
        service_name=service_name,
        readiness_check=readiness_check,
    )
    if extra_details:
        for key, value in extra_details.items():
            probe.set_detail(key, value)

    state = _ThreadRuntimeState()

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        async_stop = asyncio.Event()
        state.event_loop = loop
        state.async_stop = async_stop
        state.loop_ready.set()
        if state.stop_requested.is_set():
            async_stop.set()

        async def _serve_until_stopped() -> None:
            probe_task = asyncio.create_task(probe.start())
            stop_task = asyncio.create_task(async_stop.wait())
            try:
                done, _ = await asyncio.wait(
                    {probe_task, stop_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if probe_task in done:
                    await probe_task
                    return

                if probe._server is not None:
                    await probe.stop()
                if not probe_task.done():
                    probe_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await probe_task
            finally:
                for task in (probe_task, stop_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(probe_task, stop_task, return_exceptions=True)

        try:
            loop.run_until_complete(_serve_until_stopped())
        except Exception as exc:
            state.failure = exc
            logger.warning("{} health-probe thread stopped: {}", service_name, exc)
        finally:
            loop.close()
            state.finished.set()

    t = threading.Thread(
        target=_run,
        daemon=True,
        name=f"{service_name}-health-probe",
    )
    t.start()
    if not state.loop_ready.wait(timeout=5.0):
        state.stop_requested.set()
        t.join(timeout=5.0)
        raise TimeoutError(f"{service_name} health-probe event loop did not become ready")

    runtime = HealthProbeRuntime(probe=probe, thread=t, _state=state)
    logger.info("{} health probe listening on :{}", service_name.capitalize(), port)
    return runtime


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
