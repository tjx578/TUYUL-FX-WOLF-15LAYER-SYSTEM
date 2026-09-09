"""Factory-level bridge binding; no lifespan, database or broker is started."""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from api import app_factory
from api.middleware.executor_auth import derive_executor_token
from execution.mt5_command_repository import CommandConflictError, get_mt5_command_repository

EXECUTOR = UUID("11111111-1111-4111-8111-111111111111")
OTHER = UUID("22222222-2222-4222-8222-222222222222")
COMMAND = UUID("33333333-3333-4333-8333-333333333333")
SECRET = "factory-fixture-only-key-000000000000"


@pytest.fixture
def factory(monkeypatch):
    # Retain the actual inner factory and middleware; unrelated router imports
    # and telemetry exporters are isolated, and TestClient does not run lifespan.
    monkeypatch.setattr(app_factory, "load_routers", lambda: ([], []))
    for name in (
        "setup_tracer",
        "instrument_asyncio",
        "instrument_redis",
        "instrument_requests",
        "instrument_httpx",
        "instrument_fastapi",
    ):
        monkeypatch.setattr(app_factory, name, lambda *a, **kw: None)
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("ENABLE_DEV_ROUTES", "false")
    monkeypatch.setenv("FORCE_HTTPS", "false")
    monkeypatch.setenv("EXECUTOR_BRIDGE_AUTH_SECRET", SECRET)
    monkeypatch.delenv("EXECUTOR_BRIDGE_AUTH_SECRET_PREVIOUS", raising=False)
    return app_factory.create_app


def path(executor=EXECUTOR):
    return f"/api/v1/executors/{executor}/commands/{COMMAND}/status"


def headers(executor=EXECUTOR):
    return {
        "X-Executor-Id": str(executor),
        "Authorization": "Bearer " + derive_executor_token(str(executor), secret=SECRET),
    }


def test_factory_default_has_no_bridge(factory, monkeypatch):
    monkeypatch.setenv("EXECUTOR_BRIDGE_ENABLED", "true")
    app = factory()
    assert TestClient(app).get(path(), headers=headers()).status_code == 404
    assert path() not in app.openapi()["paths"]


@pytest.mark.parametrize("value", ["true", "false", 1, None])
def test_factory_rejects_ambiguous_opt_in(factory, value):
    with pytest.raises(ValueError, match="EXPLICIT_BOOLEAN"):
        factory(executor_bridge_enabled=value)


@pytest.mark.parametrize("auth,resource,expected", [({}, EXECUTOR, 401), (headers(), OTHER, 403)])
def test_factory_auth_prevents_repository_calls(factory, auth, resource, expected):
    app = factory(executor_bridge_enabled=True)
    repository = AsyncMock()
    app.dependency_overrides[get_mt5_command_repository] = lambda: repository
    assert TestClient(app).get(path(resource), headers=auth).status_code == expected
    repository.command_status.assert_not_awaited()


def test_factory_preserves_repository_veto(factory):
    app = factory(executor_bridge_enabled=True)
    repository = AsyncMock()
    repository.command_status.side_effect = CommandConflictError("fixture governance veto")
    app.dependency_overrides[get_mt5_command_repository] = lambda: repository
    response = TestClient(app).get(path(), headers=headers())
    assert response.status_code == 409
    repository.command_status.assert_awaited_once_with(executor_id=EXECUTOR, command_id=COMMAND)


def test_factory_missing_auth_configuration_fails_closed(factory, monkeypatch):
    monkeypatch.delenv("EXECUTOR_BRIDGE_AUTH_SECRET")
    app = factory(executor_bridge_enabled=True)
    repository = AsyncMock()
    app.dependency_overrides[get_mt5_command_repository] = lambda: repository
    assert TestClient(app).get(path(), headers=headers()).status_code == 503
    repository.command_status.assert_not_awaited()


def test_requested_bridge_rejects_degraded_router_boot(factory, monkeypatch):
    monkeypatch.setattr(app_factory, "load_routers", lambda: ([], ["fixture import failure"]))
    monkeypatch.setenv("API_BOOT_FAIL_OPEN", "true")
    monkeypatch.setenv("ROUTER_BOOT_FAIL_OPEN", "true")
    with pytest.raises(ValueError, match="ROUTER_BOOT_FAILED"):
        factory(executor_bridge_enabled=True)


def test_requested_bridge_rejects_duplicate_routes(factory, monkeypatch):
    from api.executor_bridge_router import router

    monkeypatch.setattr(app_factory, "load_routers", lambda: ([(router, "duplicate fixture")], []))
    with pytest.raises(ValueError, match="ALREADY_REGISTERED"):
        factory(executor_bridge_enabled=True)


def test_factory_authenticated_status_success(factory):
    app = factory(executor_bridge_enabled=True)
    repository = AsyncMock()
    repository.command_status.return_value = {"command_id": str(COMMAND), "terminal": False}
    app.dependency_overrides[get_mt5_command_repository] = lambda: repository
    response = TestClient(app).get(path(), headers=headers())
    assert response.status_code == 200
    assert response.json()["data"] == repository.command_status.return_value
    assert response.headers["cache-control"] == "no-store"


def test_all_mounted_bridge_routes_require_machine_auth(factory):
    from api.executor_bridge_router import router

    app = factory(executor_bridge_enabled=True)
    repository = AsyncMock()
    app.dependency_overrides[get_mt5_command_repository] = lambda: repository
    client = TestClient(app)
    for route in router.routes:
        resource = route.path.replace("{executor_id}", str(EXECUTOR)).replace("{command_id}", str(COMMAND))
        for method in route.methods:
            response = client.request(method, resource, json={})
            assert response.status_code == 401, (method, resource, response.text)
    assert not repository.mock_calls
