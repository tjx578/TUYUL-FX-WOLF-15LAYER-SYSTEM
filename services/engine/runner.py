"""Dedicated engine process entrypoint (no public HTTP).

Starts a bootstrap health probe **before** heavy imports and the DB
preflight so Railway's ``/healthz`` check passes even while Postgres
is still being verified.

Architecture:
- Single event loop: preflight and main() run in the SAME loop to avoid
  state corruption from loop closure/recreation
- Health probe runs in daemon thread with isolated loop (no shared state)
- Explicit sys.path for main.py import (not reliant on CWD)
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

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

    The probe runs in an ISOLATED event loop with no shared asyncio
    primitives to avoid cross-loop state corruption.
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


def _import_main() -> Callable[[], Coroutine[Any, Any, None]]:
    """Import main() from root main.py with explicit sys.path setup.

    Ensures the project root is on sys.path so the import succeeds
    regardless of CWD.
    """
    project_root = str(Path(__file__).resolve().parent.parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from main import main as run_main  # noqa: PLC0415

    return run_main


async def _run_engine() -> None:
    """Run preflight checks and main() in a SINGLE event loop.

    This avoids the double-asyncio.run() problem where global state
    created during main.py import could reference the wrong loop.
    """
    try:
        await _preflight_checks()
    except DatabaseSchemaError:
        logger.exception("Engine startup blocked: database schema is not ready")
        raise
    except Exception:
        logger.exception("Engine DB preflight failed")
        raise

    # Import main AFTER preflight succeeds, within the same event loop
    # that will run it. This ensures any loop-bound state created during
    # import (instrumentation, tracers) binds to the correct loop.
    run_main = _import_main()
    await run_main()


def run() -> None:
    os.environ.setdefault("RUN_MODE", "engine-only")
    run_mode = os.environ["RUN_MODE"]
    logger.info("Starting wolf15-engine service (RUN_MODE={}, HTTP disabled)", run_mode)

    # Start health probe FIRST so Railway sees liveness immediately
    # while the DB preflight and heavy imports proceed.
    _start_health_probe_in_thread()

    try:
        asyncio.run(_run_engine())
    except DatabaseSchemaError:
        # Logged inside _run_engine, fall through to diagnostics
        pass
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
