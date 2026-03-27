"""Deprecated compatibility alias for dashboard routes.

Canonical dashboard read routes live in ``api.dashboard_routes``.
This module remains import-compatible for legacy callers.
"""

from .dashboard_routes import router

__all__ = ["router"]
