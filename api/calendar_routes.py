"""Compatibility wrapper for calendar routes.

Canonical route implementation now lives in ``news.routes.calendar_routes``.
This module re-exports ``router`` to keep existing imports stable.
"""

from news.routes.calendar_routes import router

__all__ = ["router"]
