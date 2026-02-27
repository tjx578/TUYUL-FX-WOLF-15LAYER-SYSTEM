"""
Dashboard calendar stub — development placeholder ONLY.

⚠️  DO NOT mount this router in api_server.py.
    The canonical /api/v1/calendar router with full Finnhub integration lives in:
        api/calendar_routes.py  (already registered in api_server.py)

    Mounting both would create duplicate routes for:
        GET  /api/v1/calendar
        POST /api/v1/calendar/news-lock
    and trigger the _assert_no_duplicate_routes() guard at startup.

    This file is only kept as a dev reference stub inside the standalone
    dashboard/backend/api.py app, which does NOT mount it either.
    Remove or replace with a shim that imports from api/calendar_routes.py if needed.
"""
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/v1/calendar", tags=["calendar"])


@router.get("")
def get_calendar(date: str = Query("today"), impact: str = Query("HIGH")):
    return []


@router.post("/news-lock")
def set_news_lock(enabled: bool):
    return {"enabled": enabled}
