"""Minimal FastAPI entrypoint for platform auto-discovery."""

from fastapi import FastAPI

app = FastAPI(title="TUYUL FX WOLF 15-Layer")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Basic health check used by deployment probes."""
    return {"status": "ok"}
"""
FastAPI entrypoint for auto-discovery.
Exposes 'app' from api_server.py for ASGI servers and deployment tools.
"""

