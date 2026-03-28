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
    # Resolve ports BEFORE importing workers so env vars are visible at
    # import time (workers may read them during module-level init).
    health_port = int(os.getenv("PORT", os.getenv("TRADE_HEALTH_PORT", "8090")))
    alloc_health_port = str(health_port + 1)
    exec_health_port = str(health_port + 2)
    os.environ["ALLOC_HEALTH_PORT"] = alloc_health_port
    os.environ["EXEC_HEALTH_PORT"] = exec_health_port

    # Track whether workers are alive so probe reports unhealthy on crash.
    _workers_alive = True

    def _readiness_check() -> bool:
        return _workers_alive

    probe = HealthProbe(
        port=health_port,
        service_name="trade",
        readiness_check=_readiness_check,
    )
    # Store reference to prevent GC collection (Python docs warning).
    probe_task = asyncio.create_task(probe.start(), name="TradeHealthProbe")
    logger.info("Trade service health probe started on :{}", health_port)

    # Import workers lazily to avoid import-time side effects until we're ready.
    from allocation.async_worker import _main as alloc_main  # noqa: PLC0415
    from execution.async_worker import _main as exec_main  # noqa: PLC0415

    alloc_task = asyncio.create_task(alloc_main(), name="AllocationWorker")
    exec_task = asyncio.create_task(exec_main(), name="ExecutionWorker")
    logger.info("Trade service running allocation + execution workers")

    from startup.graceful_shutdown import GracefulShutdown  # noqa: PLC0415

    gs = GracefulShutdown(drain_timeout=float(os.getenv("SHUTDOWN_DRAIN_SEC", "15")))
    gs.register_cleanup("trade health probe", probe.stop)

    worker_tasks: list[asyncio.Task[object]] = [alloc_task, exec_task]
    try:
        await asyncio.gather(*worker_tasks)
    except Exception:
        _workers_alive = False
        logger.exception("Trade service worker crashed — marking unhealthy")
        raise
    finally:
        _workers_alive = False
        await gs.shutdown([alloc_task, exec_task, probe_task])


if __name__ == "__main__":
    asyncio.run(_main())
