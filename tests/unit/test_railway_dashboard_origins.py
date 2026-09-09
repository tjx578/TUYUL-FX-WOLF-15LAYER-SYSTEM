"""Existing Railway browser identity; no provider preview-origin expansion."""

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

RAILWAY_ORIGIN = "https://wolf15-dashboard-frontend-production.up.railway.app"


@pytest.mark.parametrize(
    "origin, allowed",
    [
        (RAILWAY_ORIGIN, True),
        (RAILWAY_ORIGIN + ".attacker.invalid", False),
        ("http://wolf15-dashboard-frontend-production.up.railway.app", False),
        ("https://tuyul-fx-dashboard.vercel.app", False),
        ("https://old-preview.vercel.app", False),
        ("https://untrusted.invalid", False),
    ],
)
def test_default_http_cors_is_exact_railway_origin(monkeypatch, origin, allowed):
    from api.app_factory import _add_cors

    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("CORS_ORIGIN_REGEX", raising=False)
    monkeypatch.setenv("VERCEL_FRONTEND_URL", "https://tuyul-fx-dashboard.vercel.app")
    monkeypatch.setenv("VERCEL_URL", "old-preview.vercel.app")
    monkeypatch.setenv("VERCEL_PROJECT_NAME", "old-preview")
    app = FastAPI()
    _add_cors(app)

    @app.get("/read")
    def read():
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/read", headers={"origin": origin})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == (origin if allowed else None)


def test_explicit_local_http_origin_remains_available_for_development(monkeypatch):
    from api.app_factory import _add_cors

    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000\nhttp://localhost:3000")
    monkeypatch.delenv("CORS_ORIGIN_REGEX", raising=False)
    app = FastAPI()
    _add_cors(app)
    middleware = app.user_middleware[0]
    assert middleware.kwargs["allow_origins"] == ["http://localhost:3000"]
    assert middleware.kwargs["allow_origin_regex"] is None


def test_ws_origin_configuration_has_no_implicit_preview_allowance(monkeypatch):
    import api.middleware.ws_auth as ws_auth

    with monkeypatch.context() as config:
        for name in ("WS_ALLOWED_ORIGINS", "CORS_ORIGINS", "CORS_ORIGIN_REGEX"):
            config.delenv(name, raising=False)
        config.setenv("VERCEL_FRONTEND_URL", "https://old-preview.vercel.app")
        config.setenv("VERCEL_PROJECT_NAME", "old-preview")
        importlib.reload(ws_auth)
        assert {RAILWAY_ORIGIN} == ws_auth.WS_ALLOWED_ORIGINS
        assert ws_auth._is_origin_allowed(RAILWAY_ORIGIN)
        assert not ws_auth._is_origin_allowed("https://old-preview.vercel.app")
        assert not ws_auth._is_origin_allowed(RAILWAY_ORIGIN + ".invalid")
        assert ws_auth._ORIGIN_REGEX is None
    importlib.reload(ws_auth)
