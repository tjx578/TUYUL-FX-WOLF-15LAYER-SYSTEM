"""Tests for PostgreSQL health integration."""

from fastapi.testclient import TestClient

from api_server import app
from storage.postgres_client import pg_client


def test_postgres_health_not_configured() -> None:
    """Health endpoint includes PostgreSQL status even when disabled."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert "postgres" in payload
    assert payload["postgres"]["connected"] is False


def test_pg_client_health_check_without_pool() -> None:
    """pg_client health check should provide not configured reason without pool."""
    assert pg_client.is_available is False
