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

from dotenv import load_dotenv

load_dotenv()  # Load .env before any other imports read os.environ

import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from copy import deepcopy  # noqa: E402
from typing import Any  # noqa: E402

from typing_extensions import override  # noqa: E402

from config.logging_bootstrap import configure_loguru_logging  # noqa: E402

# ── Process-level logging (must run before any app import) ────────────────────


def _configure_process_logging() -> None:
    """Configure stdlib + loguru logging for correct stdout/stderr severity routing."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        stream=sys.stdout,
        force=True,
    )

    configure_loguru_logging(level=os.getenv("WOLF15_LOG_LEVEL", "INFO"))


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
    access_level = os.getenv("UVICORN_ACCESS_LOG_LEVEL", "WARNING").upper().strip() or "WARNING"
    loggers["uvicorn.access"] = {
        "handlers": ["access"],
        "level": access_level,
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
