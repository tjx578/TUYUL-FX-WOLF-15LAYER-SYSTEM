"""ASGI auto-discovery shim — delegates to ``api_server.app``.

Used by gunicorn: ``gunicorn app:app``.
``api_server.py`` bootstraps logging, loads env, and calls
``api/app_factory.create_app()`` to build the FastAPI instance.
"""

from api_server import app  # noqa: F401  — re-exported for ASGI discovery

__all__ = ["app"]
