"""
TUYUL FX Wolf-15 — Main API Server
=====================================
Entry point for Railway deployment.

Architecture:
  - Router registration: api/router_registry.py
  - App construction:    api/app_factory.py
  - This file:           logging bootstrap + uvicorn entry point

Run (Railway):
    python api_server.py
"""

import logging
import os
import sys
from copy import deepcopy
from typing import Any

from loguru import logger as loguru_logger
from typing_extensions import override

# ── Process-level logging (must run before any app import) ────────────────────

def _configure_process_logging() -> None:
    """Configure stdlib + loguru logging for correct stdout/stderr severity routing."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        stream=sys.stdout,
        force=True,
    )

    loguru_logger.remove()
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    loguru_logger.add(
        sys.stdout,
        format=log_format,
        level="INFO",
        filter=lambda record: record["level"].no < 40,
    )
    loguru_logger.add(
        sys.stderr,
        format=log_format,
        level="ERROR",
    )


_configure_process_logging()

# ── Build application via factory ─────────────────────────────────────────────
from api.app_factory import create_app  # noqa: E402

app = create_app()

logger = logging.getLogger(__name__)


# ── Uvicorn log config ────────────────────────────────────────────────────────

class _MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def _build_uvicorn_log_config() -> dict[str, Any]:
    from uvicorn.config import LOGGING_CONFIG

    config = deepcopy(LOGGING_CONFIG)
    config["disable_existing_loggers"] = False

    filters = config.setdefault("filters", {})
    filters["max_warning"] = {
        "()": _MaxLevelFilter,
        "max_level": logging.WARNING,
    }

    handlers = config.setdefault("handlers", {})
    handlers["default_stdout"] = {
        "class": "logging.StreamHandler",
        "formatter": "default",
        "stream": "ext://sys.stdout",
        "filters": ["max_warning"],
    }
    handlers["default_stderr"] = {
        "class": "logging.StreamHandler",
        "formatter": "default",
        "stream": "ext://sys.stderr",
        "level": "ERROR",
    }
    handlers["access"] = {
        "class": "logging.StreamHandler",
        "formatter": "access",
        "stream": "ext://sys.stdout",
    }

    loggers = config.setdefault("loggers", {})
    loggers["uvicorn"] = {
        "handlers": ["default_stdout", "default_stderr"],
        "level": "INFO",
        "propagate": False,
    }
    loggers["uvicorn.error"] = {
        "handlers": ["default_stdout", "default_stderr"],
        "level": "INFO",
        "propagate": False,
    }
    loggers["uvicorn.access"] = {
        "handlers": ["access"],
        "level": "INFO",
        "propagate": False,
    }

    return config


def _resolve_port(default: int = 8000) -> int:
    raw_port = os.getenv("PORT", str(default)).strip()
    try:
        return int(raw_port)
    except (TypeError, ValueError):
        logger.warning("Invalid PORT value '%s'; falling back to %d", raw_port, default)
        return default


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=_resolve_port(),
        log_level="info",
        log_config=_build_uvicorn_log_config(),
    )
