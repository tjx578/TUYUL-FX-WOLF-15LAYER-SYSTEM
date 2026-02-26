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