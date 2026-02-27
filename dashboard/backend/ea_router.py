"""
EA (Expert Advisor) executor-status routes.

Mount scope: dashboard/backend/api.py  (standalone dashboard app)
Do NOT add to api_server.py without also updating _assert_no_duplicate_routes() coverage.
EA is an executor only — no market decisions or verdicts live here.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/ea", tags=["ea"])


@router.get("/status")
def get_status():
    return {"healthy": True, "workers": 1}


@router.get("/logs")
def get_logs():
    return []


@router.post("/restart")
def restart():
    # executor infra only; no market decision here
    return {"ok": True}
