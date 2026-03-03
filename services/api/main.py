"""Dedicated API service entrypoint.

This module intentionally re-exports the existing FastAPI app object to avoid
duplicating route/business logic while enabling clean service-based deployment.
"""

from api_server import app

__all__ = ["app"]
