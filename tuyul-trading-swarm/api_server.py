"""API Server entrypoint — untuk uvicorn dan Railway deployment."""
from api.app_factory import create_app

app = create_app()
