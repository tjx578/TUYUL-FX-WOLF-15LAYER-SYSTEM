"""
Dashboard API (Account & Risk Governor)
"""


import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from dashboard.backend.permissions import DashboardPermission
from dashboard.backend.routes import router as read_router
from dashboard.backend.trade_input_api import write_router

app = FastAPI(title="TUYUL FX - Dashboard (Account & Risk Governor)")

# Add CORS support (configurable via environment)
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)



@app.middleware("http")
async def permission_guard(request: Request, call_next):
    """Guard to enforce permission rules."""
    if not DashboardPermission.allow(request.method, request.url.path):
        return JSONResponse(status_code=405, content={"error": "Method not allowed"})
    return await call_next(request)


# Include routers
app.include_router(read_router)
app.include_router(write_router)
# Placeholder
