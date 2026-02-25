"""
Dashboard app entry point.

For backward compatibility, re-exports the main API server app
so that ``gunicorn dashboard.app:app`` still works correctly.

The actual application with all routes, WebSocket endpoints,
and background tasks lives in api_server.py.
"""

from api_server import app  # noqa: F401

__all__ = ["app"]
