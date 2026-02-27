"""
FastAPI entrypoint shim for ASGI auto-discovery.

Deployment tools (Railway, Gunicorn, uvicorn) that look for ``app:app``
will find the fully-configured application here without any duplication.

The single source of truth is ``api_server.py``.
"""

from api_server import app  # noqa: F401  — re-exported for ASGI discovery

__all__ = ["app"]
