"""Dedicated API service entrypoint.

Bootstraps process-level logging and builds the FastAPI app via the shared
factory.  This is the ASGI target for the per-service Dockerfile::

    gunicorn services.api.main:app -k uvicorn.workers.UvicornWorker

The module uses ``api.app_factory.create_app()`` directly — no dependency on
the root-level ``api_server.py`` convenience shim.
"""

from __future__ import annotations

import logging
import os
import sys

from config.logging_bootstrap import configure_loguru_logging, resolve_stdlib_log_level

# ── Process-level logging (must run before any app import) ────────────────────


def _configure_process_logging() -> None:
    logging.basicConfig(
        level=resolve_stdlib_log_level(os.getenv("WOLF15_LOG_LEVEL")),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        stream=sys.stdout,
        force=True,
    )
    configure_loguru_logging(level=os.getenv("WOLF15_LOG_LEVEL"))


_configure_process_logging()

# ── Build application via factory ─────────────────────────────────────────────

from api.app_factory import create_app  # noqa: E402

app = create_app()

__all__ = ["app"]
