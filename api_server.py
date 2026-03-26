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

from __future__ import annotations

import logging  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from copy import deepcopy  # noqa: E402
from typing import Any  # noqa: E402

from dotenv import load_dotenv
from fastapi import FastAPI
from typing_extensions import override  # noqa: E402

from config.logging_bootstrap import configure_loguru_logging  # noqa: E402


def _is_railway_runtime() -> bool:
    return bool(
        os.environ.get("RAILWAY_ENVIRONMENT")
        or os.environ.get("RAILWAY_ENVIRONMENT_ID")
        or os.environ.get("RAILWAY_PROJECT_ID")
        or os.environ.get("RAILWAY_SERVICE_ID")
        or os.environ.get("RAILWAY_DEPLOYMENT_ID")
        or os.environ.get("RAILWAY_REPLICA_ID")
    )


def _env_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


# Load .env only for local/dev workflows. On Railway, rely on platform env vars
# unless explicitly forced via WOLF15_LOAD_DOTENV=true.
if _env_true(os.getenv("WOLF15_LOAD_DOTENV")) or not _is_railway_runtime():
    load_dotenv(override=False)

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
from fastapi import WebSocket  # noqa: E402

from api.app_factory import create_app  # noqa: E402
from core.auth_ws_killswitch_fix import ws_auth_fixed  # noqa: E402


def _env_fail_open_enabled() -> bool:
    return _env_true(os.getenv("API_BOOT_FAIL_OPEN", "true"))


def _build_bootstrap_fallback_app(error_text: str) -> FastAPI:
    """Create a minimal fail-open app that keeps Railway liveness healthy.

    This endpoint set is intentionally tiny and dependency-free so operators
    can inspect startup failures via ``/health`` while ``/healthz`` remains
    alive for platform probes.
    """

    fallback = FastAPI(
        title="TUYUL FX — Bootstrap Fallback",
        version="10.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @fallback.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "alive", "service": "tuyul-fx", "degraded": True}

    @fallback.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "degraded",
            "service": "tuyul-fx",
            "router_boot_ok": False,
            "router_boot_errors": [error_text],
        }

    return fallback


try:
    app = create_app()
except Exception as exc:  # pragma: no cover - exercised only on bootstrap faults
    if not _env_fail_open_enabled():
        raise
    logging.getLogger(__name__).exception("API bootstrap failed - enabling fallback liveness app")
    app = _build_bootstrap_fallback_app(f"api_bootstrap_failed: {exc!s}")

logger = logging.getLogger(__name__)

# ── JWT config ────────────────────────────────────────────────────────────────
JWT_SECRET: str = os.environ.get("DASHBOARD_JWT_SECRET", "").strip() or os.environ.get("JWT_SECRET", "").strip()


# ── WebSocket endpoint (fixed auth) ──────────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """General-purpose authenticated WebSocket relay.

    Validates JWT via ws_auth_fixed, then forwards Redis PubSub messages
    to the connected client until disconnect.
    """
    await ws.accept()
    payload = await ws_auth_fixed(ws, JWT_SECRET)
    if not payload:
        return

    import asyncio
    import contextlib
    import json as _json

    from storage.redis_client import redis_client

    pubsub = None
    try:
        pubsub = redis_client.pubsub()
        # Subscribe to general signal channels
        from state.pubsub_channels import SIGNAL_EVENTS

        pubsub.subscribe(SIGNAL_EVENTS)
        logger.info("WS /ws connected: user=%s", payload.get("sub"))

        while True:
            # Read from Redis PubSub (non-blocking via thread)
            raw_msg: object = await asyncio.to_thread(pubsub.get_message, ignore_subscribe_messages=True, timeout=1.0)
            if raw_msg and isinstance(raw_msg, dict) and raw_msg.get("type") == "message":
                data = raw_msg.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                if isinstance(data, str):
                    await ws.send_text(data)
            else:
                # Heartbeat ping to detect dead connections
                with contextlib.suppress(Exception):
                    await ws.send_text(_json.dumps({"type": "ping", "ts": __import__("time").time()}))
                await asyncio.sleep(1.0)
    except Exception:
        logger.debug("WS /ws disconnected: user=%s", payload.get("sub"))
    finally:
        if pubsub is not None:
            with contextlib.suppress(Exception):
                pubsub.unsubscribe()
                pubsub.close()


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
        ws_per_message_deflate=True,
    )
