"""FastAPI app factory — buat dan konfigurasi aplikasi."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from loguru import logger

from api.routes.agent_routes import router as agent_router
from api.routes.decision_routes import router as decision_router
from api.routes.memory_routes import router as memory_router
from api.routes.governance_routes import router as governance_router
from infrastructure.redis_client import ping_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup dan shutdown hooks."""
    logger.info("🐺 TUYUL Trading Swarm — Starting up...")

    # Redis health check
    redis_ok = await ping_redis()
    if redis_ok:
        logger.success("✅ Redis connection OK")
    else:
        logger.warning("⚠️  Redis not available — memory fabric akan gunakan fallback")

    logger.success("🎯 All agents initialized")
    logger.info("📊 Dashboard: http://localhost:8000/dashboard")
    yield

    logger.info("TUYUL Trading Swarm — Shutting down...")


def create_app() -> FastAPI:
    """Buat dan konfigurasi FastAPI application."""
    app = FastAPI(
        title="TUYUL Trading Swarm",
        description="Production-grade multi-agent AI trading decision system — Tuyul Exception v.3",
        version="3.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────
    cors_origins_raw = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:8000,http://localhost:3000,http://127.0.0.1:8000",
    )
    cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routes ────────────────────────────────────────────────────────────
    app.include_router(agent_router)
    app.include_router(decision_router)
    app.include_router(memory_router)
    app.include_router(governance_router)

    # ── Auth route ────────────────────────────────────────────────────────
    from fastapi import APIRouter
    auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

    @auth_router.post("/token")
    async def get_token(payload: dict) -> dict:
        """Get JWT token (dev/simple mode)."""
        from api.middleware.auth import create_access_token
        user = payload.get("user", "trader")
        role = payload.get("role", "viewer")
        token = create_access_token(user, role)
        return {"access_token": token, "token_type": "bearer"}

    app.include_router(auth_router)

    # ── Health endpoints ───────────────────────────────────────────────────
    @app.get("/health")
    async def health() -> dict:
        redis_ok = await ping_redis()
        return {
            "status": "healthy" if redis_ok else "degraded",
            "redis": redis_ok,
            "service": "tuyul-trading-swarm",
            "version": "3.0.0",
        }

    @app.get("/")
    async def root() -> dict:
        return {
            "service": "TUYUL Trading Swarm",
            "version": "3.0.0",
            "docs": "/api/docs",
            "dashboard": "/dashboard",
        }

    # ── Static files (dashboard) ──────────────────────────────────────────
    dashboard_path = os.path.join(os.path.dirname(__file__), "..", "dashboard")
    dashboard_path = os.path.abspath(dashboard_path)

    if os.path.exists(dashboard_path):
        app.mount("/dashboard/static", StaticFiles(directory=os.path.join(dashboard_path, "static")), name="static")

        @app.get("/dashboard")
        @app.get("/dashboard/")
        async def serve_dashboard():
            return FileResponse(os.path.join(dashboard_path, "index.html"))

    return app
