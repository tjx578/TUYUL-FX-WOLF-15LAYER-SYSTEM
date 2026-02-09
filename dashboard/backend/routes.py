"""
Dashboard Routes
"""

from fastapi import APIRouter, Depends

from dashboard.backend.auth import verify_token
from dashboard.dashboard_state import DashboardState

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
