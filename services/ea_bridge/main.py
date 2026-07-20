"""Minimal FastAPI surface for the external MT5 dumb executor."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException

from api.executor_bridge_router import router as executor_router
from contracts.mt5_execution_protocol import PROTOCOL_VERSION
from storage.postgres_client import pg_client


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await pg_client.initialize()
    try:
        yield
    finally:
        await pg_client.close()


app = FastAPI(
    title="Wolf15 MT5 Executor Bridge",
    version=PROTOCOL_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.include_router(executor_router)


@app.get("/health/live")
@app.get("/healthz")
async def health_live() -> dict[str, Any]:
    return {"status": "live", "service": "ea-bridge", "protocol_version": PROTOCOL_VERSION}


@app.get("/health/ready")
async def health_ready() -> dict[str, Any]:
    auth_secret = os.getenv("EXECUTOR_BRIDGE_AUTH_SECRET", "").strip()
    signing_secret = os.getenv("EXECUTOR_COMMAND_SIGNING_SECRET", "").strip()
    if len(auth_secret.encode("utf-8")) < 32 or len(signing_secret.encode("utf-8")) < 32:
        raise HTTPException(status_code=503, detail="executor secrets are missing or weak")
    health = await pg_client.health_check()
    if not health.get("connected"):
        raise HTTPException(status_code=503, detail="executor database is unavailable")
    table = await pg_client.fetchrow("SELECT to_regclass('public.execution_commands') AS name")
    if not table or table["name"] is None:
        raise HTTPException(status_code=503, detail="executor bridge migration is not applied")
    return {
        "status": "ready",
        "service": "ea-bridge",
        "protocol_version": PROTOCOL_VERSION,
        "database": "connected",
    }


__all__ = ["app"]
