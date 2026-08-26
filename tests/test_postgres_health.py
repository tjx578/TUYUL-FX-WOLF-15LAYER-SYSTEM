"""Tests for PostgreSQL health integration."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import app_factory as app_factory_module
from api.middleware.auth import verify_token
from api_server import app
from storage.postgres_client import PostgresClient, pg_client


class _HealthyConnection:
    async def fetchrow(self, _query: str, *_args: Any) -> dict[str, int]:
        return {"ok": 1}


class _PoolAcquire:
    async def __aenter__(self) -> _HealthyConnection:
        return _HealthyConnection()

    async def __aexit__(self, *_args: Any) -> None:
        return None


class _HealthyPool:
    def __init__(self) -> None:
        self.closed = False

    def acquire(self) -> _PoolAcquire:
        return _PoolAcquire()

    def get_size(self) -> int:
        return 1

    def get_idle_size(self) -> int:
        return 1

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def isolated_pg_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[PostgresClient]:
    """Give the app a pool-free client without mutating the process singleton."""
    client = object.__new__(PostgresClient)
    client._pool = None
    client._keepalive_task = None
    client._loop = None
    monkeypatch.setattr(app_factory_module, "pg_client", client)
    yield client
    assert client.is_available is False


@pytest.fixture
def admin_auth_override() -> Iterator[None]:
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[verify_token] = lambda: {"sub": "test", "role": "admin"}
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.fixture
def offline_app_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent status tests from opening Redis sockets or starting an outbox loop."""
    from api import allocation_router, ws_routes
    from infrastructure import redis_client as redis_client_module
    from storage import trade_outbox_worker as outbox_module

    async def _redis_unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("redis intentionally unavailable in postgres health tests")

    async def _close_pool() -> None:
        return None

    async def _outbox_run(_self: Any) -> None:
        return None

    async def _outbox_stop(_self: Any) -> None:
        return None

    async def _candle_agg_start(_symbols: list[str]) -> None:
        return None

    async def _candle_agg_stop() -> None:
        return None

    monkeypatch.setattr(redis_client_module, "get_client", _redis_unavailable)
    monkeypatch.setattr(allocation_router, "get_client", _redis_unavailable)
    monkeypatch.setattr(redis_client_module, "close_pool", _close_pool)
    monkeypatch.setattr(outbox_module.TradeOutboxWorker, "run", _outbox_run)
    monkeypatch.setattr(outbox_module.TradeOutboxWorker, "stop", _outbox_stop)
    monkeypatch.setattr(ws_routes._candle_agg, "start", _candle_agg_start)
    monkeypatch.setattr(ws_routes._candle_agg, "stop", _candle_agg_stop)
    monkeypatch.setenv("ENABLE_PEER_HEALTH", "false")
    monkeypatch.setenv("ENABLE_WS_RELAY", "false")
    monkeypatch.setenv("WOLF15_EMBED_ORCHESTRATOR", "false")


def test_postgres_health_not_configured(
    monkeypatch: pytest.MonkeyPatch,
    isolated_pg_client: PostgresClient,
    admin_auth_override: None,
    offline_app_services: None,
) -> None:
    """Detailed status endpoint includes PostgreSQL status even when disabled."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as client:
        response = client.get("/api/v1/status/full")

    assert response.status_code == 200
    payload = response.json()
    assert "postgres" in payload
    assert payload["postgres"]["connected"] is False
    assert payload["postgres"]["reason"] == "DATABASE_URL not configured"
    assert isolated_pg_client.is_available is False


def test_pg_client_health_check_without_pool(isolated_pg_client: PostgresClient) -> None:
    """pg_client health check should provide not configured reason without pool."""
    assert isolated_pg_client.is_available is False


def test_postgres_health_reports_configured_pool(
    monkeypatch: pytest.MonkeyPatch,
    isolated_pg_client: PostgresClient,
    admin_auth_override: None,
    offline_app_services: None,
) -> None:
    """A configured healthy pool remains visible through the status endpoint."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.invalid/wolf15_test")
    pool = _HealthyPool()
    isolated_pg_client._pool = pool

    with TestClient(app) as client:
        response = client.get("/api/v1/status/full")

    assert response.status_code == 200
    assert response.json()["postgres"]["connected"] is True
    assert pool.closed is True
    assert isolated_pg_client.is_available is False


def test_postgres_health_not_configured_ignores_stale_process_singleton(
    monkeypatch: pytest.MonkeyPatch,
    isolated_pg_client: PostgresClient,
    admin_auth_override: None,
    offline_app_services: None,
) -> None:
    """A stale process singleton cannot leak into the isolated endpoint test."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    stale_pool = _HealthyPool()
    monkeypatch.setattr(pg_client, "_pool", stale_pool)
    assert pg_client.is_available is True

    with TestClient(app) as client:
        response = client.get("/api/v1/status/full")

    assert response.status_code == 200
    assert response.json()["postgres"]["connected"] is False
    assert stale_pool.closed is False
    assert isolated_pg_client.is_available is False


def test_public_health_is_minimal(
    isolated_pg_client: PostgresClient,
    offline_app_services: None,
) -> None:
    """After P5, /health returns liveness-only payload (same as /healthz)."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "alive", "service": "tuyul-fx"}
