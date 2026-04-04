"""Dashboard BFF ASGI entrypoint.

Bootstraps process-level logging and builds the FastAPI app via the
BFF factory.  ASGI target for gunicorn::

    gunicorn services.dashboard_bff.main:app -k uvicorn.workers.UvicornWorker
"""

from __future__ import annotations

import logging
import os
import sys

from config.logging_bootstrap import configure_loguru_logging


def _configure_process_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        stream=sys.stdout,
        force=True,
    )
    configure_loguru_logging(level=os.getenv("WOLF15_LOG_LEVEL", "INFO"))


_configure_process_logging()

from services.dashboard_bff.app_factory import create_app  # noqa: E402

app = create_app()

__all__ = ["app"]
