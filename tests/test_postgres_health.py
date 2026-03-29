"""Tests for PostgreSQL health integration."""

from fastapi.testclient import TestClient

from api.middleware.auth import verify_token
from api_server import app
from storage.postgres_client import pg_client


def test_postgres_health_not_configured() -> None:
    """Detailed status endpoint includes PostgreSQL status even when disabled."""
    app.dependency_overrides[verify_token] = lambda: {"sub": "test", "role": "admin"}
    with TestClient(app) as client:
        response = client.get("/api/v1/status/full")
    app.dependency_overrides.pop(verify_token, None)

    assert response.status_code == 200
    payload = response.json()
    assert "postgres" in payload
    assert payload["postgres"]["connected"] is False


def test_pg_client_health_check_without_pool() -> None:
    """pg_client health check should provide not configured reason without pool."""
    assert pg_client.is_available is False


def test_public_health_is_minimal() -> None:
    """After P5, /health returns liveness-only payload (same as /healthz)."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "alive", "service": "tuyul-fx"}
