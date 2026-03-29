from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.config_profile_router import router as config_profile_router
from api.ea_router import router as ea_router
from api.middleware import auth as auth_mod
from api.middleware import governance
from risk.risk_router import router as risk_router


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(risk_router)
    app.include_router(ea_router)
    app.include_router(config_profile_router)
    return app


def _headers(pin: str | None = None) -> dict[str, str]:
    base = {
        "Authorization": "Bearer test-token",
        "X-Edit-Mode": "ON",
        "X-Action-Reason": "TEST_REASON",
    }
    if pin is not None:
        base["X-Action-Pin"] = pin
    return base


def test_rbac_rejects_missing_role_claim(monkeypatch) -> None:
    app = _app()
    client = TestClient(app)

    _payload = {"sub": "user-1", "iss": "issuer-A"}
    monkeypatch.setattr(auth_mod, "decode_token", lambda _t: _payload)
    monkeypatch.setattr(auth_mod, "validate_api_key", lambda _t: False)
    monkeypatch.setattr(governance, "decode_token", lambda _t: _payload)
    monkeypatch.setattr(governance, "validate_api_key", lambda _t: False)
    monkeypatch.setenv("DASHBOARD_ACTION_PIN", "1234")

    response = client.post(
        "/api/v1/config/profiles/lock",
        headers=_headers(pin="1234"),
        json={"locked": True},
    )
    assert response.status_code == 403
    assert "role claim" in response.text


def test_rbac_rejects_invalid_role_claim(monkeypatch) -> None:
    app = _app()
    client = TestClient(app)

    _payload = {"sub": "user-2", "role": "superuser", "iss": "issuer-A"}
    monkeypatch.setattr(auth_mod, "decode_token", lambda _t: _payload)
    monkeypatch.setattr(auth_mod, "validate_api_key", lambda _t: False)
    monkeypatch.setattr(governance, "decode_token", lambda _t: _payload)
    monkeypatch.setattr(governance, "validate_api_key", lambda _t: False)
    monkeypatch.setenv("DASHBOARD_ACTION_PIN", "1234")

    response = client.post(
        "/api/v1/config/profiles/lock",
        headers=_headers(pin="1234"),
        json={"locked": True},
    )
    assert response.status_code == 403
    assert "invalid" in response.text.lower()


def test_rbac_rejects_untrusted_issuer(monkeypatch) -> None:
    app = _app()
    client = TestClient(app)

    _payload = {"sub": "user-3", "role": "admin", "iss": "rogue-issuer"}
    monkeypatch.setattr(auth_mod, "decode_token", lambda _t: _payload)
    monkeypatch.setattr(auth_mod, "validate_api_key", lambda _t: False)
    monkeypatch.setattr(governance, "decode_token", lambda _t: _payload)
    monkeypatch.setattr(governance, "validate_api_key", lambda _t: False)
    monkeypatch.setenv("DASHBOARD_ACTION_PIN", "1234")
    monkeypatch.setenv("DASHBOARD_JWT_REQUIRED_ISSUER", "issuer-A,issuer-B")

    response = client.post(
        "/api/v1/config/profiles/lock",
        headers=_headers(pin="1234"),
        json={"locked": True},
    )
    assert response.status_code == 403
    assert "issuer" in response.text.lower()


def test_critical_kill_switch_requires_pin(monkeypatch) -> None:
    app = _app()
    client = TestClient(app)

    _payload = {"sub": "trader-1", "role": "admin", "iss": "issuer-A", "scopes": ["*"]}
    monkeypatch.setattr(auth_mod, "decode_token", lambda _t: _payload)
    monkeypatch.setattr(auth_mod, "validate_api_key", lambda _t: False)
    monkeypatch.setattr(governance, "decode_token", lambda _t: _payload)
    monkeypatch.setattr(governance, "validate_api_key", lambda _t: False)
    monkeypatch.setenv("DASHBOARD_ACTION_PIN", "4321")

    response = client.post("/api/v1/risk/kill-switch", headers=_headers(), json={"reason": "TEST"})
    assert response.status_code == 403
    assert "x-action-pin" in response.text.lower()


def test_critical_routes_accept_with_valid_pin(monkeypatch) -> None:
    app = _app()
    client = TestClient(app)

    _payload = {"sub": "admin-1", "role": "admin", "iss": "issuer-A", "scopes": ["*"]}
    monkeypatch.setattr(auth_mod, "decode_token", lambda _t: _payload)
    monkeypatch.setattr(auth_mod, "validate_api_key", lambda _t: False)
    monkeypatch.setattr(governance, "decode_token", lambda _t: _payload)
    monkeypatch.setattr(governance, "validate_api_key", lambda _t: False)
    monkeypatch.setenv("DASHBOARD_ACTION_PIN", "9999")

    # kill-switch
    resp_kill = client.post(
        "/api/v1/risk/kill-switch",
        headers=_headers(pin="9999"),
        json={"reason": "TEST"},
    )
    assert resp_kill.status_code == 200

    # ea restart
    resp_restart = client.post(
        "/api/v1/ea/restart",
        headers=_headers(pin="9999"),
        json={"reason": "TEST"},
    )
    assert resp_restart.status_code == 200

    # config lock
    resp_lock = client.post(
        "/api/v1/config/profiles/lock",
        headers=_headers(pin="9999"),
        json={"locked": True},
    )
    assert resp_lock.status_code == 200
