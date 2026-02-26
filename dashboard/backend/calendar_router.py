from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/v1/calendar", tags=["calendar"])

@router.get("")
def get_calendar(date: str = Query("today"), impact: str = Query("HIGH")):
    return []

@router.post("/news-lock")
def set_news_lock(enabled: bool):
    return {"enabled": enabled}