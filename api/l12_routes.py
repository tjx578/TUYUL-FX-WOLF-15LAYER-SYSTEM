from fastapi import APIRouter, HTTPException
from storage.l12_cache import get_verdict

router = APIRouter()

@router.get("/api/v1/l12/{pair}")
def fetch_l12(pair: str):
    data = get_verdict(pair.upper())
    if not data:
        raise HTTPException(status_code=404, detail="No verdict")
    return data
