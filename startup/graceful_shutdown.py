"""Graceful shutdown coordinator for all Wolf-15 services.

Provides a structured shutdown sequence:
1. Signal receipt → set shutdown event (no new work accepted)
2. Drain in-flight tasks with configurable timeout
3. Flush/close connection pools (Redis, Postgres)
4. Final state persistence
5. Exit

Zone: startup/ — process lifecycle, no execution side-effects.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from loguru import logger

__all__ = ["GracefulShutdown"]

# Default timeout for draining in-flight work before forceful cancellation.
_DEFAULT_DRAIN_TIMEOUT_SEC = 10.0


class GracefulShutdown:
    """Coordinates an ordered shutdown of async tasks and resources.

    Usage::

        gs = GracefulShutdown(drain_timeout=15.0)
        gs.register_cleanup("redis pool", close_pool)
        gs.register_cleanup("persistent storage", shutdown_persistent_storage)

        # When SIGTERM fires and tasks are gathered:
        await gs.shutdown(tasks)
    """

    def __init__(self, drain_timeout: float = _DEFAULT_DRAIN_TIMEOUT_SEC) -> None:
        self._drain_timeout = drain_timeout
        self._cleanups: list[tuple[str, Callable[[], Awaitable[None]]]] = []

    def register_cleanup(self, name: str, coro_fn: Callable[[], Awaitable[None]]) -> None:
        """Register an async cleanup function to run during shutdown."""
        self._cleanups.append((name, coro_fn))

    async def shutdown(self, tasks: list[asyncio.Task[object]]) -> None:
        """Execute the full shutdown sequence.

        1. Cancel all tasks
        2. Wait up to *drain_timeout* for them to finish
        3. Run registered cleanup functions in order
        """
        logger.info(
            "[GracefulShutdown] Initiating shutdown — draining {} task(s) (timeout={}s)",
            len(tasks),
            self._drain_timeout,
        )

        # ── Phase 1: Cancel tasks and drain with timeout ────────────
        for task in tasks:
            if not task.done():
                task.cancel()

        if tasks:
            done, pending = await asyncio.wait(
                tasks, timeout=self._drain_timeout, return_when=asyncio.ALL_COMPLETED
            )
            if pending:
                logger.warning(
                    "[GracefulShutdown] {} task(s) did not finish within {}s drain timeout",
                    len(pending),
                    self._drain_timeout,
                )
                for t in pending:
                    t.cancel()
                # Give forcefully cancelled tasks a short window to clean up
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait(pending, timeout=2.0)

            # Collect and log any unexpected exceptions from drained tasks
            for task in done:
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc is not None:
                    logger.warning(
                        "[GracefulShutdown] Task {} raised during drain: {}",
                        task.get_name(),
                        exc,
                    )

        # ── Phase 2: Run registered cleanups in order ───────────────
        for name, cleanup_fn in self._cleanups:
            try:
                await cleanup_fn()
                logger.info("[GracefulShutdown] Cleanup '{}' completed", name)
            except Exception as exc:
                logger.error("[GracefulShutdown] Cleanup '{}' failed: {}", name, exc)

        logger.info("[GracefulShutdown] Shutdown sequence complete")

    async def drain_worker_tasks(
        self, in_flight: list[asyncio.Task[None]], label: str = "worker"
    ) -> None:
        """Wait for in-flight message-processing tasks to complete.

        Used by stream consumers (execution/allocation workers) to finish
        processing messages that are already being handled before exiting.
        """
        if not in_flight:
            return

        active = [t for t in in_flight if not t.done()]
        if not active:
            return

        logger.info(
            "[GracefulShutdown] Draining {} in-flight {} task(s) (timeout={}s)",
            len(active),
            label,
            self._drain_timeout,
        )

        done, pending = await asyncio.wait(
            active, timeout=self._drain_timeout, return_when=asyncio.ALL_COMPLETED
        )
        if pending:
            logger.warning(
                "[GracefulShutdown] {} {} task(s) did not complete — cancelling",
                len(pending),
                label,
            )
            for t in pending:
                t.cancel()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait(pending, timeout=2.0)
