"""Tests for PostgreSQL health integration."""

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import api.app_factory as app_factory_module
from api.middleware.auth import verify_token
from api_server import app
from storage.postgres_client import PostgresClient


def _isolated_postgres_client(monkeypatch: MonkeyPatch) -> PostgresClient:
    monkeypatch.setattr(PostgresClient, "_instance", None)
    return PostgresClient()


def test_postgres_health_not_configured(monkeypatch: MonkeyPatch) -> None:
    """Detailed status endpoint includes PostgreSQL status even when disabled."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    isolated_pg_client = _isolated_postgres_client(monkeypatch)
    monkeypatch.setattr(app_factory_module, "pg_client", isolated_pg_client)
    app.dependency_overrides[verify_token] = lambda: {"sub": "test", "role": "admin"}
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/status/full")
    finally:
        app.dependency_overrides.pop(verify_token, None)

    assert response.status_code == 200
    payload = response.json()
    assert "postgres" in payload
    assert payload["postgres"]["connected"] is False


def test_pg_client_health_check_without_pool(monkeypatch: MonkeyPatch) -> None:
    """pg_client health check should provide not configured reason without pool."""
    assert _isolated_postgres_client(monkeypatch).is_available is False


def test_public_health_is_minimal() -> None:
    """After P5, /health returns liveness-only payload (same as /healthz)."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "alive", "service": "tuyul-fx"}
