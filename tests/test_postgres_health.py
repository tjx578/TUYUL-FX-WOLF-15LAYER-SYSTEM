"""Tests for PostgreSQL health integration."""

import pytest
from fastapi.testclient import TestClient

from api.middleware.auth import verify_token
from api_server import app
from storage.postgres_client import pg_client


@pytest.fixture(autouse=True)
def _unconfigured_database(monkeypatch):
    """Unit health checks must not inherit the integration runner's live pool."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(pg_client, "_pool", None)
    previous = dict(app.dependency_overrides)
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


def test_postgres_health_not_configured() -> None:
    """Detailed status endpoint includes PostgreSQL status even when disabled."""
    app.dependency_overrides[verify_token] = lambda: {"sub": "test", "role": "admin"}
    # The test exercises an HTTP health projection, not startup or external I/O.
    # Lifespan coverage belongs to the dedicated startup/readiness tests.
    response = TestClient(app).get("/api/v1/status/full")

    assert response.status_code == 200
    payload = response.json()
    assert "postgres" in payload
    assert payload["postgres"]["connected"] is False


def test_pg_client_health_check_without_pool() -> None:
    """pg_client health check should provide not configured reason without pool."""
    assert pg_client.is_available is False


def test_public_health_is_minimal() -> None:
    """After P5, /health returns liveness-only payload (same as /healthz)."""
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "alive", "service": "tuyul-fx"}
