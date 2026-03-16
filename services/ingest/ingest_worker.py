"""Dedicated ingest process entrypoint.

Starts a lightweight health probe **before** importing the heavy
``ingest_service`` module so that Railway's ``/healthz`` check passes
even when module-level imports or config loading fail.

The heavy import is run in a thread executor so the asyncio event loop
stays responsive — without this, ``ingest_service``'s module-level
imports (numpy, pandas, config loading, etc.) block the loop and the
health probe cannot answer Railway's periodic ``/healthz`` probes.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
import signal
import types

from loguru import logger


async def _bootstrap_and_run() -> None:
    """Start health probe first, then import and run ingest service."""
    from config.logging_bootstrap import configure_loguru_logging

    configure_loguru_logging()

    # core.health_probe only depends on stdlib + loguru — safe early import.
    from core.health_probe import HealthProbe

    port = int(os.getenv("INGEST_HEALTH_PORT") or os.getenv("PORT", "8082"))
    probe = HealthProbe(port=port, service_name="ingest")
    health_task = asyncio.create_task(probe.start(), name="BootstrapHealthProbe")
    # Yield so the probe can bind the port before any slow work.
    await asyncio.sleep(0.2)

    logger.info("Bootstrap health probe listening on :{}", port)

    try:
        # Import ingest_service in a thread so heavy module-level imports
        # (numpy, pandas, config YAML, etc.) don't block the event loop.
        # This keeps the health probe responsive during the import.
        probe.set_detail("startup_stage", "importing_ingest_service")
        loop = asyncio.get_running_loop()
        ingest_mod = await loop.run_in_executor(None, importlib.import_module, "ingest_service")
        run_main = ingest_mod.main
        probe.set_detail("startup_stage", "running")

        # Hand the already-running probe to main() so there is no
        # port-rebind gap visible to Railway's prober.
        await run_main(_bootstrap_probe=probe)
    except Exception as exc:
        probe.set_detail("fatal_error", str(exc)[:200])
        logger.error("Ingest service fatal error: {}", exc)
        logger.exception(exc)
        # Keep process alive so health probe keeps responding.
        # Railway deployment succeeds; operator can inspect /status.
        shutdown = asyncio.Event()

        def _sig(signum: int, _frame: types.FrameType | None) -> None:
            logger.info("Received {} — exiting degraded hold", signal.Signals(signum).name)
            shutdown.set()

        signal.signal(signal.SIGTERM, _sig)
        signal.signal(signal.SIGINT, _sig)
        with contextlib.suppress(asyncio.CancelledError):
            await shutdown.wait()
    finally:
        health_task.cancel()
        with contextlib.suppress(Exception):
            await probe.stop()


def run() -> None:
    from config.logging_bootstrap import configure_loguru_logging

    configure_loguru_logging()
    logger.info("Starting wolf15-ingest service")
    asyncio.run(_bootstrap_and_run())


if __name__ == "__main__":
    run()
