"""CPU-heavy task offloading — process pool executor.

Prevents event-loop starvation caused by CPU-bound analysis (Monte Carlo,
FTA, divergence engine) from blocking async Redis reads and WebSocket feeds.

Rule of thumb: anything > ~10–20 ms CPU in a hot path should be offloaded if
the service also maintains realtime Redis pub/sub or WebSocket connections.

Usage::

    from infrastructure.cpu_offload import run_cpu
    result = await run_cpu(some_cpu_function, arg1, arg2)

``func`` must be a picklable callable (module-level function or static
method).  Lambdas and closures will raise ``PicklingError``.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable

logger = logging.getLogger(__name__)

_EXEC: ProcessPoolExecutor | None = None
_MAX_WORKERS = 4


def _get_executor() -> ProcessPoolExecutor:
    global _EXEC
    if _EXEC is None:
        _EXEC = ProcessPoolExecutor(max_workers=_MAX_WORKERS)
        logger.info("CPU process pool started (max_workers=%d)", _MAX_WORKERS)
    return _EXEC


async def run_cpu(func: Callable[..., Any], *args: Any) -> Any:
    """Run a CPU-bound callable in a subprocess to avoid blocking the event loop.

    Args:
        func: A picklable callable (module-level function or static method).
        *args: Positional arguments forwarded to ``func``.

    Returns:
        The return value of ``func(*args)``.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_executor(), func, *args)


def shutdown_executor(wait: bool = True) -> None:
    """Shutdown the process pool gracefully.  Call on application exit."""
    global _EXEC
    if _EXEC is not None:
        _EXEC.shutdown(wait=wait)
        _EXEC = None
        logger.info("CPU process pool shut down")
