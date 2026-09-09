"""Tests for PostgreSQL health integration."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from api.middleware.auth import verify_token
from api_server import app
from storage.postgres_client import PostgresClient, pg_client


def _client_without_pool():
    # PostgresClient() is a singleton; construct a private unit-test subject.
    client = object.__new__(PostgresClient)
    client._pool = None
    client._keepalive_task = None
    client._loop = None
    return client


def test_postgres_health_not_configured(monkeypatch) -> None:
    """Detailed status endpoint includes PostgreSQL status even when disabled."""
    # The CI environment deliberately has a database; this case binds its own
    # absent-pool precondition instead of assuming the shared client is disabled.
    isolated = _client_without_pool()
    monkeypatch.setattr(pg_client, "health_check", isolated.health_check)
    monkeypatch.setattr(pg_client, "initialize", AsyncMock())
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[verify_token] = lambda: {"sub": "test", "role": "admin"}
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/status/full")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)

    assert response.status_code == 200
    payload = response.json()
    assert "postgres" in payload
    assert payload["postgres"]["connected"] is False


def test_pg_client_health_check_without_pool() -> None:
    """pg_client health check should provide not configured reason without pool."""
    assert _client_without_pool().is_available is False


def test_public_health_is_minimal() -> None:
    """After P5, /health returns liveness-only payload (same as /healthz)."""
    # Route projection only. Built-image CI separately exercises real lifespan
    # and shutdown; this assertion must not acquire the shared database pool.
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "alive", "service": "tuyul-fx"}
