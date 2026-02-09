from fastapi import FastAPI
from api.l12_routes import router as l12_router

app = FastAPI(title="Wolf L12 API", version="7.4r∞")

app.include_router(l12_router)
