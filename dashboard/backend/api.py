"""
Dashboard API (READ-ONLY)
"""

from fastapi import FastAPI, Request

from dashboard.backend.permissions import ReadOnlyPermission
from dashboard.backend.routes import router

app = FastAPI(title="TUYUL FX — Dashboard (Read Only)")


@app.middleware("http")
async def read_only_guard(request: Request, call_next):
    if not ReadOnlyPermission.allow(request.method):
        return {"error": "READ ONLY"}
    return await call_next(request)


app.include_router(router)
# Placeholder
