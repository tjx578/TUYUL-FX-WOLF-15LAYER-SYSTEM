"""
TUYUL FX Wolf-15 — Main API Server
=====================================
Entry point for Railway deployment.
Mounts all routers including the 7 new endpoints.

CHANGES FROM ORIGINAL:
  - Added constitutional_router    (GET /api/v1/health/constitutional, /equity/history)
  - Added risk_events_router       (GET /api/v1/risk/events, /risk/{id}/snapshot)
  - Added journal_router           (GET /api/v1/journal/* with search + extended metrics)
  - Added instrument_router        (GET /api/v1/instruments/*)
  - Added calendar_router          (GET /api/v1/calendar/*)
  - trade_input_api write_router   (BUG FIX: APIRouter shadow removed, Redis env fixed)
  - CORS uses CORS_ORIGINS env var

Run (Railway):
    python api_server.py
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger as loguru_logger


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

from api.calendar_routes import router as calendar_router  # noqa: E402

# ── New routers (7 new endpoints) ─────────────────────────────────────────────
from api.constitutional_routes import router as constitutional_router  # noqa: E402
from api.instrument_routes import router as instrument_router  # noqa: E402
from api.journal_routes import router as journal_router  # noqa: E402

# ── Existing routers ───────────────────────────────────────────────────────────
from api.l12_routes import router as l12_router  # noqa: E402
from api.risk_events_routes import router as risk_events_router  # noqa: E402
from api.ws_routes import router as ws_router  # noqa: E402

# ── Fixed routers ─────────────────────────────────────────────────────────────
from dashboard.backend.trade_input_api import write_router  # BUG-1/2/3 FIXED  # noqa: E402

logger = logging.getLogger(__name__)


class _MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def _build_uvicorn_log_config() -> dict:
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


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    logger.info("🐺 TUYUL FX Wolf-15 starting up…")
    yield
    logger.info("🐺 TUYUL FX Wolf-15 shutting down…")


app = FastAPI(
    title="TUYUL FX — Wolf-15 API",
    version="10.0.0",
    description="Institutional-grade trading system API",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
_cors_raw = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:8000",
)
cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount routers ─────────────────────────────────────────────────────────────
app.include_router(l12_router)
app.include_router(ws_router)
app.include_router(write_router)
app.include_router(constitutional_router)
app.include_router(risk_events_router)
app.include_router(journal_router)
app.include_router(instrument_router)
app.include_router(calendar_router)


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health() -> dict:
    from datetime import datetime

    import redis as redis_lib

    redis_ok = False
    try:
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis_lib.from_url(url, decode_responses=True)
        r.ping()
        redis_ok = True
    except Exception:
        pass

    return {
        "status": "ok",
        "service": "tuyul-fx",
        "version": "10.0.0",
        "redis_connected": redis_ok,
        "mt5_connected": False,   # updated by EA bridge
        "active_pairs": 0,        # updated by L12 pipeline
        "active_trades": 0,       # updated by TradeLedger
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ── Endpoint summary (dev helper) ────────────────────────────────────────────
@app.get("/api/v1/endpoints")
async def endpoint_summary() -> dict:
    """List all registered routes — for development debugging."""
    routes = []
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            routes.append({
                "path": getattr(route, "path", "unknown"),
                "methods": list(route.methods),  # type: ignore[arg-type]
                "name": getattr(route, "name", "unknown"),
            })
    return {"total": len(routes), "routes": sorted(routes, key=lambda r: r["path"])}


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
