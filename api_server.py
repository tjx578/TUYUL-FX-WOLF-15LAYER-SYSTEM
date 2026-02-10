"""
Wolf L12 API Server

FastAPI server for L12 verdict polling and system health monitoring.
"""

from fastapi import FastAPI
from api.l12_routes import router as l12_router

app = FastAPI(
    title="Wolf L12 API",
    version="7.4r∞",
    description="Wolf 15-Layer Trading System - L12 Verdict API",
)

app.include_router(l12_router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Wolf 15-Layer System",
        "version": "7.4r∞",
        "status": "operational",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "wolf-l12-api",
        "version": "7.4r∞",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
