"""Machine-only ingest authorization through the real app registration and service.

Only the affected registry entry is loaded. Persistence is faked and app lifespan
is not entered; accidental external I/O fails rather than reaching real services.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

_TEST_SECRET = "agent-ingest-test-signing-secret-at-least-32-characters"
_MACHINE_KEY = "agent-ingest-synthetic-machine-key"
_AGENT_ID = "e4238759-c714-4fce-996c-9b47a640ce28"
_PAYLOADS: dict[str, dict[str, Any]] = {
    "heartbeat": {
        "agent_id": _AGENT_ID,
        "timestamp": "2026-09-14T00:00:00Z",
        "trades_executed": 4,
        "uptime_seconds": 600,
    },
    "status-change": {"agent_id": _AGENT_ID, "new_status": "WARNING", "reason": "EA reporting"},
    "portfolio-snapshot": {
        "agent_id": _AGENT_ID,
        "account_id": "synthetic-account",
        "balance": 1000.0,
        "equity": 1010.0,
        "open_positions": 1,
    },
}
_SERVICE_METHODS = ("record_heartbeat", "change_status", "record_portfolio_snapshot")


@dataclass
class _Harness:
    client: TestClient
    repo: Mock
    service_calls: dict[str, AsyncMock]

    def assert_no_ingest(self) -> None:
        for call in self.service_calls.values():
            call.assert_not_awaited()
        assert self.repo.mock_calls == []


@pytest.fixture
def ingest(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Harness]:
    # Set safe values before importing application modules; never load .env files.
    for key, value in {
        "PYTHON_DOTENV_DISABLED": "1",
        "DATABASE_URL": "",
        "REDIS_URL": "",
        "DASHBOARD_JWT_SECRET": "",
        "JWT_SECRET": "",
        "DASHBOARD_API_KEY": "",
        "ENV": "test",
        "APP_ENV": "test",
        "FORCE_HTTPS": "false",
        "ENABLE_DEV_ROUTES": "false",
        "OTEL_ENABLED": "false",
        "RATE_LIMIT_BACKEND": "memory",
        "API_BOOT_FAIL_OPEN": "false",
        "ROUTER_BOOT_FAIL_OPEN": "false",
    }.items():
        monkeypatch.setenv(key, value)

    def no_external_io(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("External I/O is forbidden in agent-ingest auth tests")

    # Windows' asyncio wakeup socketpair uses a loopback connection internally.
    # Permit only that standard-library operation on its current thread.
    original_socketpair = socket.socketpair
    original_connect = socket.socket.connect
    pair_context = threading.local()

    def local_socketpair(*args: Any, **kwargs: Any) -> Any:
        pair_context.active = True
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            pair_context.active = False

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        if getattr(pair_context, "active", False) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        return no_external_io()

    monkeypatch.setattr(socket, "socketpair", local_socketpair)
    monkeypatch.setattr(socket, "create_connection", no_external_io)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", no_external_io)

    from agents.repository import AgentRepository
    from agents.service import AgentManagerService
    from api import agent_ingest_router, app_factory, router_registry
    from api.middleware import auth, rate_limit
    from infrastructure import redis_client
    from storage.postgres_client import PostgresClient

    monkeypatch.setattr(auth, "JWT_SECRET", _TEST_SECRET)
    monkeypatch.setattr(auth, "JWT_VERIFY_SECRETS", (_TEST_SECRET,))
    monkeypatch.setattr(auth, "API_KEY", _MACHINE_KEY)
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(redis_client, "get_client", AsyncMock(side_effect=no_external_io))
    for method in ("initialize", "execute", "fetch", "fetchrow"):
        monkeypatch.setattr(PostgresClient, method, AsyncMock(side_effect=no_external_io))
    # TestClient is intentionally used without its lifespan context manager.
    monkeypatch.setattr(app_factory, "lifespan", no_external_io)

    # Exercise the real registry entry, loader and create_app mount behavior while
    # avoiding unrelated routers' import-time clients and background components.
    entries = [entry for entry in router_registry.ROUTER_ENTRIES if entry.module == "api.agent_ingest_router"]
    assert len(entries) == 1
    monkeypatch.setattr(router_registry, "ROUTER_ENTRIES", entries)

    repo = Mock(spec_set=AgentRepository)
    repo.get_agent = AsyncMock(return_value={"id": _AGENT_ID, "status": "ONLINE", "locked": False})
    repo.upsert_runtime = AsyncMock(return_value={"agent_id": _AGENT_ID, "trades_executed": 4})
    repo.update_agent_status = AsyncMock(return_value={"id": _AGENT_ID, "status": "WARNING", "locked": False})
    repo.insert_portfolio_snapshot = AsyncMock(return_value={"agent_id": _AGENT_ID, "balance": 1000.0})
    repo.insert_event = AsyncMock()
    repo.insert_audit_log = AsyncMock()
    service = AgentManagerService(repo=cast(AgentRepository, repo))
    calls = {name: AsyncMock(wraps=getattr(service, name)) for name in _SERVICE_METHODS}
    for name, call in calls.items():
        monkeypatch.setattr(service, name, call)
    monkeypatch.setattr(agent_ingest_router, "_service", service)

    app = app_factory.create_app()
    assert app.state.router_boot_errors == []
    assert not app.dependency_overrides
    mounted_posts = {path for path, methods in app.openapi()["paths"].items() if "post" in methods}
    assert mounted_posts == {f"/api/v1/agent-ingest/{endpoint}" for endpoint in _PAYLOADS}
    client = TestClient(app)
    try:
        yield _Harness(client, repo, calls)
    finally:
        client.close()


@pytest.mark.parametrize("endpoint", _PAYLOADS)
@pytest.mark.parametrize("authorization", [None, "Bearer wrong-machine-key", "Bearer ", "Basic invalid"])
def test_invalid_credentials_never_reach_ingest(ingest: _Harness, endpoint: str, authorization: str | None) -> None:
    headers = {"Authorization": authorization} if authorization is not None else {}
    response = ingest.client.post(f"/api/v1/agent-ingest/{endpoint}", json=_PAYLOADS[endpoint], headers=headers)
    assert response.status_code == 401
    ingest.assert_no_ingest()


@pytest.mark.parametrize("endpoint", _PAYLOADS)
@pytest.mark.parametrize("transport", ["bearer", "cookie", "invalid-bearer-with-cookie"])
@pytest.mark.parametrize(
    "claims",
    [
        pytest.param({"role": "viewer", "scopes": ["read:dashboard"]}, id="owner-viewer"),
        pytest.param({"role": "operator"}, id="legacy-operator"),
        pytest.param({"role": "admin", "scopes": ["*"]}, id="admin-wildcard"),
        pytest.param({"role": "producer", "scopes": ["write:agent-ingest"]}, id="unrecognized-producer-claims"),
        pytest.param(
            {"role": "admin", "scopes": ["*"], "auth_method": "api_key", "sub": "api_key_user"},
            id="spoofed-machine-principal",
        ),
    ],
)
def test_signed_jwt_claims_and_cookies_cannot_authorize_ingest(
    ingest: _Harness, endpoint: str, transport: str, claims: dict[str, Any]
) -> None:
    from api.middleware import auth

    token = auth.create_token(sub="synthetic-owner", extra=claims)
    headers = {"X-Agent-Id": _AGENT_ID, "X-Auth-Method": "api_key"}
    if transport == "bearer":
        headers["Authorization"] = f"Bearer {token}"
    else:
        ingest.client.cookies.set(auth.COOKIE_NAME, token)
        if transport == "invalid-bearer-with-cookie":
            headers["Authorization"] = "Bearer wrong-machine-key"
    response = ingest.client.post(f"/api/v1/agent-ingest/{endpoint}", json=_PAYLOADS[endpoint], headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "Agent ingest requires machine API key authentication"}
    ingest.assert_no_ingest()


@pytest.mark.parametrize("endpoint", _PAYLOADS)
def test_missing_configured_machine_key_fails_closed(
    ingest: _Harness, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    from api.middleware import auth

    monkeypatch.setattr(auth, "API_KEY", "")
    response = ingest.client.post(
        f"/api/v1/agent-ingest/{endpoint}",
        json=_PAYLOADS[endpoint],
        headers={"Authorization": f"Bearer {_MACHINE_KEY}"},
    )
    assert response.status_code == 401
    ingest.assert_no_ingest()


@pytest.mark.parametrize("endpoint", _PAYLOADS)
def test_ea_machine_bearer_reaches_real_service_and_persistence(ingest: _Harness, endpoint: str) -> None:
    response = ingest.client.post(
        f"/api/v1/agent-ingest/{endpoint}",
        json=_PAYLOADS[endpoint],
        headers={"Authorization": f"Bearer {_MACHINE_KEY}", "X-Agent-Id": _AGENT_ID, "X-EA-Version": "3.00"},
    )
    assert response.status_code == 200
    ingest.repo.get_agent.assert_awaited_once_with(_AGENT_ID)
    if endpoint == "heartbeat":
        assert response.json() == {"agent_id": _AGENT_ID, "trades_executed": 4}
        ingest.service_calls["record_heartbeat"].assert_awaited_once()
        ingest.repo.upsert_runtime.assert_awaited_once()
        agent_id, metrics = ingest.repo.upsert_runtime.call_args.args
        assert agent_id == _AGENT_ID
        assert metrics["trades_executed"] == 4
        assert metrics["uptime_seconds"] == 600
    elif endpoint == "portfolio-snapshot":
        assert response.json() == {"agent_id": _AGENT_ID, "balance": 1000.0}
        ingest.service_calls["record_portfolio_snapshot"].assert_awaited_once()
        ingest.repo.insert_portfolio_snapshot.assert_awaited_once()
        snapshot = ingest.repo.insert_portfolio_snapshot.call_args.args[0]
        assert snapshot["account_id"] == "synthetic-account"
        assert snapshot["balance"] == 1000.0
        assert snapshot["equity"] == 1010.0
    else:
        assert response.json() == {"id": _AGENT_ID, "status": "WARNING", "locked": False}
        ingest.service_calls["change_status"].assert_awaited_once()
        ingest.repo.update_agent_status.assert_awaited_once_with(_AGENT_ID, "WARNING")
        ingest.repo.insert_event.assert_awaited_once()
        ingest.repo.insert_audit_log.assert_awaited_once()
        audit = ingest.repo.insert_audit_log.call_args.kwargs
        assert audit["performed_by"] == "api_key_user"
        assert audit["action"] == "STATUS_CHANGE"
        assert audit["details"] == {"old_status": "ONLINE", "new_status": "WARNING", "reason": "EA reporting"}


@pytest.mark.parametrize("endpoint", _PAYLOADS)
def test_machine_key_preserves_missing_agent_control(ingest: _Harness, endpoint: str) -> None:
    ingest.repo.get_agent.return_value = None
    response = ingest.client.post(
        f"/api/v1/agent-ingest/{endpoint}",
        json=_PAYLOADS[endpoint],
        headers={"Authorization": f"Bearer {_MACHINE_KEY}"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
    ingest.repo.upsert_runtime.assert_not_awaited()
    ingest.repo.update_agent_status.assert_not_awaited()
    ingest.repo.insert_portfolio_snapshot.assert_not_awaited()
    ingest.repo.insert_event.assert_not_awaited()
    ingest.repo.insert_audit_log.assert_not_awaited()


@pytest.mark.parametrize(
    ("locked", "status", "expected_code"),
    [(True, "ONLINE", 423), (False, "WARNING", 422)],
)
def test_machine_key_preserves_status_lock_and_transition_controls(
    ingest: _Harness, locked: bool, status: str, expected_code: int
) -> None:
    ingest.repo.get_agent.return_value = {"id": _AGENT_ID, "status": status, "locked": locked}
    response = ingest.client.post(
        "/api/v1/agent-ingest/status-change",
        json=_PAYLOADS["status-change"],
        headers={"Authorization": f"Bearer {_MACHINE_KEY}"},
    )
    assert response.status_code == expected_code
    ingest.repo.update_agent_status.assert_not_awaited()
    ingest.repo.insert_event.assert_not_awaited()
    ingest.repo.insert_audit_log.assert_not_awaited()
