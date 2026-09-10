from __future__ import annotations

import builtins
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import app_factory
from api.middleware.machine_auth import verify_observability_machine_auth
from state.data_freshness import FreshnessClass


def health_app() -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[verify_observability_machine_auth] = lambda: None
    app_factory._register_health_routes(app)
    return app


@pytest.mark.parametrize("errors", [None, ["router import error containing private details"]])
def test_router_boot_failure_is_503_even_when_router_import_is_broken(monkeypatch, errors) -> None:
    app = health_app()
    if errors is not None:
        app.state.router_boot_errors = errors
    original_import = builtins.__import__

    def fail_router(name, *args, **kwargs):
        if name == "api.allocation_router":
            raise ImportError("private-connection-detail")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_router)
    with TestClient(app) as client:
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["ready"] is False
        assert response.json()["router_boot_ok"] is False
        assert "private" not in response.text
        assert client.get("/healthz").status_code == 200


@pytest.mark.parametrize("alive", [True, False])
def test_completed_router_boot_preserves_heartbeat_gate(monkeypatch, alive: bool) -> None:
    import api.allocation_router

    app = health_app()
    app.state.router_boot_errors = []
    app.state.redis = SimpleNamespace(get=AsyncMock(return_value=json.dumps({"ts": time.time()}) if alive else None))
    monkeypatch.setattr(
        api.allocation_router,
        "_feed_freshness_snapshot",
        AsyncMock(return_value=SimpleNamespace(freshness_class=FreshnessClass.LIVE, staleness_seconds=0.1)),
    )
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == (200 if alive else 503)
    assert response.json()["ready"] is alive
    assert response.json()["router_boot_ok"] is True


def test_fallback_is_not_ready_and_does_not_disclose_bootstrap_exception() -> None:
    app = app_factory._build_bootstrap_fallback_app("private-connection-detail")
    app.dependency_overrides[verify_observability_machine_auth] = lambda: None
    with TestClient(app) as client:
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["reasons"] == ["api_bootstrap_failed"]
        assert "private" not in response.text
        assert client.get("/healthz").status_code == 200


@pytest.mark.parametrize("strict", [True, False])
def test_router_import_failure_obeys_explicit_bootstrap_policy(monkeypatch, strict: bool) -> None:
    monkeypatch.setenv("ROUTER_BOOT_FAIL_OPEN", "false" if strict else "true")
    monkeypatch.setenv("API_BOOT_FAIL_OPEN", "false")
    monkeypatch.setenv("ENABLE_DEV_ROUTES", "false")
    monkeypatch.setenv("FORCE_HTTPS", "false")
    monkeypatch.setattr(app_factory, "load_routers", lambda: ([], ["failed required router"]))
    if strict:
        with pytest.raises(RuntimeError, match="Mandatory API router import failed"):
            app_factory.create_app()
    else:
        app = app_factory.create_app()
        # No lifespan: this test proves served ASGI readiness, not dependency startup.
        app.dependency_overrides[verify_observability_machine_auth] = lambda: None
        client = TestClient(app)
        try:
            assert client.get("/readyz").status_code == 503
        finally:
            client.close()
