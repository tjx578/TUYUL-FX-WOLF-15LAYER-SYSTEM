"""Dedicated ingest process entrypoint.

Starts a lightweight health probe **before** importing the heavy
``ingest_service`` module so that Railway's ``/healthz`` check passes
even when module-level imports or config loading fail.

The heavy import is done synchronously in the main thread after the
health probe has bound its port.  An earlier version used
``run_in_executor`` to offload the import to a thread, but
``ingest_service`` performs module-level imports of Redis clients and
async infrastructure that must live on the event-loop thread.
"""

from __future__ import annotations

import asyncio
import contextlib
import os

from loguru import logger

from config.logging_bootstrap import configure_loguru_logging

configure_loguru_logging()


async def _bootstrap_and_run() -> None:
    """Start health probe first, then import and run ingest service."""
    from services.shared.health_probe_launcher import start_probe_as_task

    port = int(os.getenv("INGEST_HEALTH_PORT") or os.getenv("PORT", "8082"))
    probe, health_task = await start_probe_as_task(
        port=port,
        service_name="ingest",
        readiness_check=lambda: False,
        task_name="BootstrapHealthProbe",
    )
    # Yield so the probe can bind the port before any slow work.
    await asyncio.sleep(0.2)

    service_task = None
    try:
        # Import ingest_service in the main thread.  Using run_in_executor
        # was the original approach but ingest_service's module-level imports
        # pull in Redis clients, asyncpg helpers and context managers that
        # assume they run on the event-loop thread.  Importing in a worker
        # thread risks import-lock contention and creates async resources
        # on the wrong thread.  The synchronous import may briefly block
        # the loop, but the health probe has already bound its port and
        # answered the first Railway /healthz probe above.
        probe.set_detail("startup_stage", "importing_ingest_service")
        import ingest_service  # noqa: PLC0415

        run_main = ingest_service.main
        probe.set_detail("startup_stage", "running")

        # Hand the already-running probe to main() so there is no
        # port-rebind gap visible to Railway's prober.
        service_task = asyncio.create_task(run_main(_bootstrap_probe=probe), name="RequiredIngestService")
        done, _ = await asyncio.wait({service_task, health_task}, return_when=asyncio.FIRST_COMPLETED)
        if health_task in done:
            raise RuntimeError("ingest_health_probe_stopped")
        await service_task
        shutdown = getattr(ingest_service, "_shutdown_event", None)
        if shutdown is None or not shutdown.is_set():
            raise RuntimeError("ingest_required_service_returned")
    except Exception as exc:
        probe.set_alive(False)
        probe.set_detail("fatal_error", str(exc)[:200])
        logger.error("Ingest service fatal error: {}", exc)
        logger.exception(exc)
        raise
    finally:
        probe.set_alive(False)
        if service_task is not None and not service_task.done():
            service_task.cancel()
            _, pending = await asyncio.wait({service_task}, timeout=20)
            if pending:
                raise RuntimeError("ingest_service_not_drained")
        if service_task is not None:
            await asyncio.gather(service_task, return_exceptions=True)
        health_task.cancel()
        await asyncio.gather(health_task, return_exceptions=True)
        with contextlib.suppress(Exception):
            await probe.stop()


def run() -> None:
    logger.info("Starting wolf15-ingest service")
    asyncio.run(_bootstrap_and_run())


if __name__ == "__main__":
    run()
