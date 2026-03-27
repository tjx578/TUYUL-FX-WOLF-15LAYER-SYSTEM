"""Consolidated Trade Service — runs Allocation + Execution workers.

Combines both Redis Stream consumer workers in a single event loop.
Railway probes a single health port; both Prometheus metrics endpoints
are started on their respective ports.

Environment variables:
  PORT               — Railway-assigned health probe port (default 8090)
  ALLOC_METRICS_PORT — Prometheus metrics for allocation (default 9102)
  EXEC_METRICS_PORT  — Prometheus metrics for execution  (default 9103)
"""

from __future__ import annotations

import asyncio
import os

from loguru import logger

from config.logging_bootstrap import configure_loguru_logging
from core.health_probe import HealthProbe

configure_loguru_logging()


async def _main() -> None:
    # Single health probe for Railway — covers both workers.
    health_port = int(os.getenv("PORT", os.getenv("TRADE_HEALTH_PORT", "8090")))
    probe = HealthProbe(port=health_port, service_name="trade")
    asyncio.create_task(probe.start())
    logger.info("Trade service health probe started on :{}", health_port)

    # Prevent child workers from binding their own health probes on PORT
    # (would conflict with our consolidated probe).  Give each a distinct
    # secondary port that is NOT the Railway-probed PORT.
    os.environ["ALLOC_HEALTH_PORT"] = str(health_port + 1)
    os.environ["EXEC_HEALTH_PORT"] = str(health_port + 2)

    # Import workers lazily to avoid import-time side effects until we're ready.
    from allocation.async_worker import _main as alloc_main  # noqa: PLC0415
    from execution.async_worker import _main as exec_main  # noqa: PLC0415

    # Run both workers as concurrent tasks in the same event loop.
    alloc_task = asyncio.create_task(alloc_main(), name="AllocationWorker")
    exec_task = asyncio.create_task(exec_main(), name="ExecutionWorker")

    logger.info("Trade service running allocation + execution workers")
    await asyncio.gather(alloc_task, exec_task)


if __name__ == "__main__":
    asyncio.run(_main())
