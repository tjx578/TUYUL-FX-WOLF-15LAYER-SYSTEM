from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from api.app_factory import _register_health_routes
from api.metrics_routes import router as metrics_router


def test_metrics_requires_machine_key_when_required(monkeypatch) -> None:
    monkeypatch.setenv("OBSERVABILITY_AUTH_MODE", "required")
    monkeypatch.setenv("OBSERVABILITY_MACHINE_KEY", "obs-test-key")

    app = FastAPI()
    app.include_router(metrics_router)
    client = TestClient(app)

    class _FakeRedis:
        async def get(self, _key: str):
            return None

    async def _fake_get_async_redis():
        return _FakeRedis()

    monkeypatch.setattr("api.metrics_routes.get_async_redis", _fake_get_async_redis)

    try:
        unauthorized = client.get("/metrics")
        assert unauthorized.status_code == 401

        authorized = client.get("/metrics", headers={"X-Machine-Key": "obs-test-key"})
        assert authorized.status_code == 200
    finally:
        client.close()


def test_metrics_rejects_invalid_bearer_machine_key(monkeypatch) -> None:
    monkeypatch.setenv("OBSERVABILITY_AUTH_MODE", "required")
    monkeypatch.setenv("OBSERVABILITY_MACHINE_KEY", "obs-test-key")

    app = FastAPI()
    app.include_router(metrics_router)
    client = TestClient(app)

    class _FakeRedis:
        async def get(self, _key: str):
            return None

    async def _fake_get_async_redis():
        return _FakeRedis()

    monkeypatch.setattr("api.metrics_routes.get_async_redis", _fake_get_async_redis)

    try:
        unauthorized = client.get("/metrics", headers={"Authorization": "Bearer wrong-key"})
        assert unauthorized.status_code == 401

        authorized = client.get("/metrics", headers={"Authorization": "Bearer obs-test-key"})
        assert authorized.status_code == 200
    finally:
        client.close()


def test_metrics_rejects_malformed_bearer_machine_key(monkeypatch) -> None:
    monkeypatch.setenv("OBSERVABILITY_AUTH_MODE", "required")
    monkeypatch.setenv("OBSERVABILITY_MACHINE_KEY", "obs-test-key")

    app = FastAPI()
    app.include_router(metrics_router)
    client = TestClient(app)

    class _FakeRedis:
        async def get(self, _key: str):
            return None

    async def _fake_get_async_redis():
        return _FakeRedis()

    monkeypatch.setattr("api.metrics_routes.get_async_redis", _fake_get_async_redis)

    try:
        unauthorized = client.get("/metrics", headers={"Authorization": "Bearer "})
        assert unauthorized.status_code == 401
    finally:
        client.close()


def test_production_profile_forces_required_mode(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("OBSERVABILITY_AUTH_MODE", "optional")
    monkeypatch.delenv("OBSERVABILITY_MACHINE_KEY", raising=False)
    monkeypatch.delenv("MACHINE_OBSERVABILITY_KEY", raising=False)

    app = FastAPI()
    app.include_router(metrics_router)
    client = TestClient(app)

    class _FakeRedis:
        async def get(self, _key: str):
            return None

    async def _fake_get_async_redis():
        return _FakeRedis()

    monkeypatch.setattr("api.metrics_routes.get_async_redis", _fake_get_async_redis)

    try:
        # In production runtime, optional mode is upgraded to required and fails closed without a machine key.
        response = client.get("/metrics")
        assert response.status_code == 503
    finally:
        client.close()


def test_active_production_profile_forces_required_mode(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("OBSERVABILITY_AUTH_MODE", "optional")
    monkeypatch.delenv("OBSERVABILITY_MACHINE_KEY", raising=False)
    monkeypatch.delenv("MACHINE_OBSERVABILITY_KEY", raising=False)
    monkeypatch.setattr("api.middleware.machine_auth._resolve_active_profile_name", lambda: "production")

    app = FastAPI()
    app.include_router(metrics_router)
    client = TestClient(app)

    class _FakeRedis:
        async def get(self, _key: str):
            return None

    async def _fake_get_async_redis():
        return _FakeRedis()

    monkeypatch.setattr("api.metrics_routes.get_async_redis", _fake_get_async_redis)

    try:
        # Even in non-production APP_ENV, production config profile enforces required mode.
        response = client.get("/metrics")
        assert response.status_code == 503
    finally:
        client.close()


def test_healthz_is_unauthenticated_liveness_probe() -> None:
    """Liveness probe /healthz must have NO machine auth so infrastructure
    healthchecks (Railway, k8s) always reach the handler."""
    app = FastAPI()
    _register_health_routes(app)
    route_map = {route.path: route for route in app.routes if isinstance(route, APIRoute)}

    route = route_map["/healthz"]
    dependency_names: set[str] = set()
    for dep in route.dependant.dependencies:
        call = getattr(dep, "call", None)
        if callable(call):
            dependency_names.add(call.__name__)
    assert "verify_observability_machine_auth" not in dependency_names


def test_readyz_is_machine_auth_protected() -> None:
    """Readiness probe /readyz keeps machine auth."""
    app = FastAPI()
    _register_health_routes(app)
    route_map = {route.path: route for route in app.routes if isinstance(route, APIRoute)}

    route = route_map["/readyz"]
    dependency_names: set[str] = set()
    for dep in route.dependant.dependencies:
        call = getattr(dep, "call", None)
        if callable(call):
            dependency_names.add(call.__name__)
    assert "verify_observability_machine_auth" in dependency_names
