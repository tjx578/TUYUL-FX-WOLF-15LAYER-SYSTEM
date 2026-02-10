"""
Wolf L12 API Server

FastAPI server for L12 verdict polling and system health monitoring.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.l12_routes import router as l12_router
from context.runtime_state import RuntimeState
from utils.timezone_utils import now_utc, format_utc, format_local

app = FastAPI(
    title="Wolf L12 API",
    version="7.4r∞",
    description="Wolf 15-Layer Trading System - L12 Verdict API",
)

# CORS middleware for Next.js dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Next.js dev server
        "https://yourdomain.com",  # Production domain (update this)
    ],
    allow_credentials=True,
    allow_methods=["GET"],  # Read-only
    allow_headers=["*"],
)

app.include_router(l12_router)


@app.get("/")
async def root():
    """Root endpoint."""
    current_time = now_utc()
    return {
        "service": "Wolf 15-Layer System",
        "version": "7.4r∞",
        "status": "operational",
        "time_utc": format_utc(current_time),
        "time_local": format_local(current_time),
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "wolf-l12-api",
        "version": "7.4r∞",
        "latency_ms": RuntimeState.latency_ms,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
