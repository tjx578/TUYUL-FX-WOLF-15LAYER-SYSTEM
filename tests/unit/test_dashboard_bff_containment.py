from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from services.dashboard_bff.app_factory import create_app


class _FakeCoreClient:
    def __init__(self, response: httpx.Response | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    async def get(self, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
        self.calls.append((path, headers))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _valid_auth(monkeypatch, fake: _FakeCoreClient | None = None) -> dict[str, str]:
    auth_client = fake or _FakeCoreClient(
        httpx.Response(200, json={"user_id": "owner", "email": "owner", "role": "owner"})
    )
    monkeypatch.setattr("services.dashboard_bff.auth.get_client", lambda: auth_client)
    return {"Authorization": "Bearer test-token"}


def test_business_routes_reject_missing_authorization_before_upstream(monkeypatch) -> None:
    fake = _FakeCoreClient(error=AssertionError("upstream must not be called"))
    monkeypatch.setattr("services.dashboard_bff.routes.read_model.get_client", lambda: fake)
    monkeypatch.setattr("services.dashboard_bff.routes.status.get_client", lambda: fake)

    with TestClient(create_app()) as client:
        for path in (
            "/api/bff/aggregated-status",
            "/api/dashboard/overview",
            "/api/dashboard/feed-status",
        ):
            response = client.get(path)
            assert response.status_code == 401
            assert "token" not in response.text.lower()

    assert fake.calls == []


def test_business_route_rejects_invalid_bearer_without_leaking_it(monkeypatch) -> None:
    raw_secret = "invalid-secret-bearing-token"
    fake = _FakeCoreClient(error=AssertionError("upstream must not be called"))
    monkeypatch.setattr("services.dashboard_bff.routes.status.get_client", lambda: fake)
    auth_client = _FakeCoreClient(httpx.Response(401, json={"detail": "invalid"}))
    monkeypatch.setattr("services.dashboard_bff.auth.get_client", lambda: auth_client)

    with TestClient(create_app()) as client:
        response = client.get(
            "/api/bff/aggregated-status",
            headers={"Authorization": f"Bearer {raw_secret}"},
        )

    assert response.status_code == 401
    assert raw_secret not in response.text
    assert fake.calls == []
    assert auth_client.calls[0][0] == "/api/auth/session"
    assert auth_client.calls[0][1] == {
        "authorization": f"Bearer {raw_secret}",
        "accept": "application/json",
        "cookie": "",
    }


def test_business_route_requires_canonical_core_session_shape(monkeypatch) -> None:
    auth_client = _FakeCoreClient(httpx.Response(200, json={"id": "legacy-shape", "role": "viewer"}))
    business_client = _FakeCoreClient(error=AssertionError("business upstream must not be called"))
    monkeypatch.setattr("services.dashboard_bff.auth.get_client", lambda: auth_client)
    monkeypatch.setattr("services.dashboard_bff.routes.status.get_client", lambda: business_client)

    with TestClient(create_app()) as client:
        response = client.get(
            "/api/bff/aggregated-status",
            headers={"Authorization": "Bearer structurally-valid-probe"},
        )

    assert response.status_code == 401
    assert business_client.calls == []


def test_valid_session_cookie_cannot_authorize_a_later_invalid_bearer(monkeypatch) -> None:
    class _CookieAwareAuthClient:
        def __init__(self) -> None:
            self.has_session_cookie = False

        async def get(self, _path: str, headers: dict[str, str] | None = None) -> httpx.Response:
            assert headers is not None
            if headers["authorization"] == "Bearer valid-viewer":
                self.has_session_cookie = True
                return httpx.Response(
                    200,
                    json={"user_id": "viewer", "email": "viewer", "role": "viewer"},
                )
            if self.has_session_cookie and headers.get("cookie") != "":
                return httpx.Response(
                    200,
                    json={"user_id": "viewer", "email": "viewer", "role": "viewer"},
                )
            return httpx.Response(401, json={"detail": "invalid"})

    auth_client = _CookieAwareAuthClient()
    business_client = _FakeCoreClient(httpx.Response(200, json={"status": "ok"}))
    monkeypatch.setattr("services.dashboard_bff.auth.get_client", lambda: auth_client)
    monkeypatch.setattr("services.dashboard_bff.routes.status.get_client", lambda: business_client)

    with TestClient(create_app()) as client:
        valid = client.get(
            "/api/bff/aggregated-status",
            headers={"Authorization": "Bearer valid-viewer"},
        )
        invalid = client.get(
            "/api/bff/aggregated-status",
            headers={"Authorization": "Bearer invalid-after-valid"},
        )

    assert valid.status_code == 200
    assert invalid.status_code == 401
    assert len(business_client.calls) == 1


def test_feed_status_uses_canonical_core_path(monkeypatch) -> None:
    fake = _FakeCoreClient(httpx.Response(200, json={"status": "ok"}))
    monkeypatch.setattr("services.dashboard_bff.routes.read_model.get_client", lambda: fake)
    headers = _valid_auth(monkeypatch)

    with TestClient(create_app()) as client:
        response = client.get("/api/dashboard/feed-status", headers=headers)

    assert response.status_code == 200
    assert fake.calls[0][0] == "/api/v1/candles/feed-status"


def test_healthz_is_static_and_does_not_touch_core(monkeypatch) -> None:
    def _unexpected_client():
        raise AssertionError("liveness must not inspect dependencies")

    monkeypatch.setattr("services.dashboard_bff.routes.health.get_client", _unexpected_client)
    with TestClient(create_app()) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "dashboard-bff"}


def test_readyz_probes_core_and_fails_closed_on_non_success(monkeypatch) -> None:
    fake = _FakeCoreClient(httpx.Response(503, json={"detail": "private upstream detail"}))
    monkeypatch.setattr("services.dashboard_bff.routes.health.get_client", lambda: fake)

    with TestClient(create_app()) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "reason": "core_api_unhealthy"}
    assert fake.calls == [("/healthz", None)]
    assert "private upstream detail" not in response.text


def test_readyz_sanitizes_connection_exception(monkeypatch) -> None:
    secret = "secret-token-that-must-not-leak"
    fake = _FakeCoreClient(error=httpx.ConnectError(f"connection failed: {secret}"))
    monkeypatch.setattr("services.dashboard_bff.routes.health.get_client", lambda: fake)

    with TestClient(create_app()) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert secret not in response.text
    assert "connection failed" not in response.text


def test_business_proxy_sanitizes_upstream_exception(monkeypatch) -> None:
    secret = "Bearer raw-secret-value"
    fake = _FakeCoreClient(error=httpx.ConnectError(f"failed with {secret}"))
    monkeypatch.setattr("services.dashboard_bff.routes.status.get_client", lambda: fake)
    headers = _valid_auth(monkeypatch)

    with TestClient(create_app()) as client:
        response = client.get("/api/bff/aggregated-status", headers=headers)

    assert response.status_code == 502
    assert response.json() == {"error": "core-api request failed", "surface": "bff"}
    assert secret not in response.text


def test_production_docs_respect_generic_env(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("ENV", "production")
    paths = {route.path for route in create_app().routes}
    assert "/docs" not in paths


def test_bff_registers_only_get_routes() -> None:
    app = create_app()
    business_paths = ("/api/bff", "/api/dashboard")
    for route in app.routes:
        if route.path.startswith(business_paths):
            assert route.methods == {"GET"}
