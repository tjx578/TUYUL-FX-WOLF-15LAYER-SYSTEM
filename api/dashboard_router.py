"""
Dashboard read routes (standalone dashboard app only).

Mount scope: dashboard/backend/api.py  (standalone dashboard app, NOT api_server.py)
These routes have no prefix — they expose /context, /execution, /verdict without
the /api/v1 namespace and are NOT interchangeable with the equivalent routes in
api/l12_routes.py (which serve /api/v1/context etc.).

Do NOT include this router in api_server.py — that would shadow l12_routes.py and
trigger the _assert_no_duplicate_routes() guard or cause silent double-reads.
"""

from fastapi import APIRouter, Depends

from api.auth import verify_token
from api.dashboard_state import DashboardState

router = APIRouter(dependencies=[Depends(verify_token)])
state = DashboardState()


@router.get("/context")
def get_context():
    return state.get_context()


@router.get("/execution")
def get_execution():
    return state.get_execution()


@router.get("/verdict")
def get_verdict():
    return state.get_verdict()
