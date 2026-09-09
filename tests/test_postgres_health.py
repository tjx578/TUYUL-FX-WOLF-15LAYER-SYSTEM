"""Isolated PostgreSQL health projections; lifespan has dedicated acceptance."""

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import api.app_factory as app_factory_module
from api.middleware.auth import verify_token
from api_server import app
from storage.postgres_client import PostgresClient, pg_client


def _client_without_pool():
    # PostgresClient is a singleton; never mutate the integration runner's pool.
    client = object.__new__(PostgresClient)
    client._pool = None
    client._keepalive_task = None
    client._loop = None
    return client


def test_postgres_health_not_configured(monkeypatch) -> None:
    isolated = _client_without_pool()
    monkeypatch.setattr(pg_client, "health_check", isolated.health_check)
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[verify_token] = lambda: {"sub": "test", "role": "admin"}
    try:
        # Deliberately no context manager: route projection must not start workers
        # or acquire a real database connection. Built-image CI covers lifespan.
        client = TestClient(app)
        try:
            response = client.get("/api/v1/status/full")
        finally:
            client.close()
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
    assert response.status_code == 200
    assert response.json()["postgres"]["connected"] is False


def test_pg_client_health_check_without_pool() -> None:
    assert _client_without_pool().is_available is False


def test_public_health_is_minimal() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "alive", "service": "tuyul-fx"}
