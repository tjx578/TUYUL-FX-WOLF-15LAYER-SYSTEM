"""Dedicated engine process entrypoint (no public HTTP).

Starts a bootstrap health probe **before** heavy imports and the DB
preflight so Railway's ``/healthz`` check passes even while Postgres
is still being verified.
"""

from __future__ import annotations

import asyncio
import os
import threading

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from config.logging_bootstrap import configure_loguru_logging
from services.shared.db_revision_guard import DatabaseSchemaError, assert_required_tables

configure_loguru_logging()

REQUIRED_TABLES: tuple[str, ...] = ("trade_outbox",)


def _build_engine_from_env() -> AsyncEngine:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")

    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    return create_async_engine(database_url, pool_pre_ping=True, future=True)


async def _preflight_checks() -> None:
    engine = _build_engine_from_env()
    try:
        await assert_required_tables(engine, REQUIRED_TABLES)
        logger.info("DB schema preflight passed", required_tables=REQUIRED_TABLES)
    finally:
        await engine.dispose()


def _start_health_probe_in_thread() -> None:
    """Run a liveness-only health probe on a daemon thread.

    This keeps ``/healthz`` responsive while the main thread runs the
    blocking DB preflight and heavy module imports.
    """
    from core.health_probe import HealthProbe

    port = int(os.getenv("ENGINE_HEALTH_PORT", os.getenv("PORT", "8081")))
    probe = HealthProbe(port=port, service_name="engine")

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(probe.start())
        except Exception:
            logger.warning("Bootstrap health probe stopped")
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True, name="engine-health-probe")
    t.start()
    logger.info("Bootstrap health probe listening on :{}", port)


def run() -> None:
    os.environ["RUN_MODE"] = "engine-only"
    logger.info("Starting wolf15-engine service (HTTP disabled)")

    # Start health probe FIRST so Railway sees liveness immediately
    # while the DB preflight and heavy imports proceed.
    _start_health_probe_in_thread()

    try:
        asyncio.run(_preflight_checks())
    except DatabaseSchemaError:
        logger.exception("Engine startup blocked: database schema is not ready")
        _hold_alive_for_diagnostics()
        return
    except Exception:
        logger.exception("Engine DB preflight failed")
        _hold_alive_for_diagnostics()
        return

    try:
        from main import main as run_main

        asyncio.run(run_main())
    except Exception:
        logger.exception("Engine main loop exited with error")

    # If main() returns or crashes, keep process alive so the health
    # probe stays responsive and operators can inspect /status.
    _hold_alive_for_diagnostics()


def _hold_alive_for_diagnostics() -> None:
    """Block forever so the daemon-thread health probe stays responsive.

    Same pattern as ingest_worker — Railway deployment succeeds and
    operators can inspect /healthz and /status for diagnostics.
    """
    import signal as _signal
    import types

    logger.warning("Engine holding alive for health probe diagnostics. Send SIGTERM to exit.")
    shutdown = threading.Event()

    def _on_signal(signum: int, _frame: types.FrameType | None) -> None:
        logger.info("Received {} — exiting degraded hold", _signal.Signals(signum).name)
        shutdown.set()

    _signal.signal(_signal.SIGTERM, _on_signal)
    _signal.signal(_signal.SIGINT, _on_signal)
    shutdown.wait()


if __name__ == "__main__":
    run()
