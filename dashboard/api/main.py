from fastapi import FastAPI

from dashboard.api.routes.stream import router as stream_router

app = FastAPI()

# Mount routers
app.include_router(stream_router)
