"""
Dashboard calendar router — shim forwarding to the canonical implementation.

This module simply re-exports the router defined in api/calendar_routes.py,
which provides full Finnhub integration, Redis caching, and news-lock control.

⚠️  DO NOT also mount api/calendar_routes.router in api_server.py when this
    shim is active in the standalone dashboard/backend/api.py — doing so would
    create duplicate /api/v1/calendar routes and trigger
    _assert_no_duplicate_routes() at startup.

    In practice:
      • api_server.py  → imports from api/calendar_routes.py directly.
      • dashboard/backend/api.py → imports this shim (same router object).
      Both point at the same FastAPI router instance, so no duplication occurs
      as long as each application registers it exactly once.
"""
from api.calendar_routes import router  # noqa: F401 — re-export shim
