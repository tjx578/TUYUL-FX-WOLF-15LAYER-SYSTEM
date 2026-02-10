"""
Dashboard API (Account & Risk Governor)
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from dashboard.backend.permissions import ReadOnlyPermission
from dashboard.backend.routes import router as read_router
from dashboard.backend.trade_input_api import write_router

app = FastAPI(title="TUYUL FX — Dashboard (Account & Risk Governor)")

# Add CORS support
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def permission_guard(request: Request, call_next):
    """Guard to enforce permission rules."""
    if not ReadOnlyPermission.allow(request.method, request.url.path):
        return {"error": "Method not allowed"}
    return await call_next(request)


# Include routers
app.include_router(read_router)
app.include_router(write_router)
# Placeholder
