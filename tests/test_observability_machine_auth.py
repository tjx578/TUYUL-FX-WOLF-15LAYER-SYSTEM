from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from api.app_factory import create_app
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


def test_healthz_readyz_are_machine_auth_protected() -> None:
    app = create_app()
    route_map = {route.path: route for route in app.routes if isinstance(route, APIRoute)}

    for path in ("/healthz", "/readyz"):
        route = route_map[path]
        dependency_names: set[str] = set()
        for dep in route.dependant.dependencies:
            call = getattr(dep, "call", None)
            if callable(call):
                dependency_names.add(call.__name__)
        assert "verify_observability_machine_auth" in dependency_names
