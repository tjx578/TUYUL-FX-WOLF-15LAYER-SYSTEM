"""Deprecation tests for the legacy EA bridge router.

Verifies that all /api/v1/ea/* endpoints:
- Return Deprecation: true header
- Return Sunset: 2026-06-01 header
- Return X-Deprecated-Use header pointing to Agent Manager
- Maintain backward-compatible response shapes
- Gracefully degrade to Redis when Agent Manager is unavailable

Sunset: 2026-06-01
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.ea_router import EA_AGENT_PREFIX, EA_SAFE_MODE_KEY, router

# ── Helpers ────────────────────────────────────────────────────


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _override_auth(app: FastAPI) -> None:
    from api.middleware.auth import verify_token
    from api.middleware.governance import enforce_write_policy

    app.dependency_overrides[verify_token] = lambda: None
    app.dependency_overrides[enforce_write_policy] = lambda: None


def _make_agent_hash(agent_id: str, **overrides: str) -> dict[str, str]:
    defaults = {
        "account_id": f"ACC_{agent_id}",
        "profile": "default",
        "status": "connected",
        "last_heartbeat": datetime.now(UTC).isoformat(),
        "last_success": "",
        "last_failure": "",
        "failure_reason": "",
        "trades_executed": "5",
        "trades_failed": "1",
        "uptime_seconds": "3600",
        "version": "1.2.0",
        "scope": "single",
    }
    defaults.update(overrides)
    return defaults


# ── Fixtures ───────────────────────────────────────────────────


@pytest.fixture()
def client():
    app = _make_app()
    _override_auth(app)
    return TestClient(app)


@pytest.fixture()
def mock_redis():
    with patch("api.ea_router.redis_client") as m:
        m.client = MagicMock()
        yield m


@pytest.fixture()
def mock_ea_manager():
    with patch("api.ea_router._ea_manager") as m:
        m._running = True
        m.queue_snapshot.return_value = {
            "queue_depth": 0,
            "queue_max": 200,
        }
        yield m


@pytest.fixture()
def mock_state_machine():
    with patch("api.ea_router._state_machine") as m:
        m.snapshot.return_value = {"state": "IDLE"}
        yield m


# ── 1. Deprecation headers on ALL endpoints ────────────────────


LEGACY_GET_ENDPOINTS = ["/api/v1/ea/status", "/api/v1/ea/agents", "/api/v1/ea/logs"]
LEGACY_POST_ENDPOINTS = [
    ("/api/v1/ea/restart", {"reason": "test"}),
    ("/api/v1/ea/safe-mode", {"enabled": True, "reason": "test"}),
]


class TestDeprecationHeaders:
    """All legacy endpoints must return Deprecation + Sunset + X-Deprecated-Use headers."""

    @pytest.mark.parametrize("endpoint", LEGACY_GET_ENDPOINTS)
    def test_get_endpoints_have_deprecation_header(
        self,
        client: TestClient,
        mock_redis: MagicMock,
        mock_ea_manager: MagicMock,
        mock_state_machine: MagicMock,
        endpoint: str,
    ) -> None:
        mock_redis.client.get.return_value = "0"
        mock_redis.client.keys.return_value = []
        mock_redis.client.ttl.return_value = -2
        mock_redis.client.lrange.return_value = []

        with patch("agents.service.AgentManagerService") as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc.list_agents.return_value = ([], 0)
            mock_svc.get_agent_events.return_value = []
            mock_svc_cls.return_value = mock_svc

            resp = client.get(endpoint)

        assert resp.status_code == 200
        assert resp.headers.get("Deprecation") == "true"

    @pytest.mark.parametrize("endpoint", LEGACY_GET_ENDPOINTS)
    def test_get_endpoints_have_sunset_header(
        self,
        client: TestClient,
        mock_redis: MagicMock,
        mock_ea_manager: MagicMock,
        mock_state_machine: MagicMock,
        endpoint: str,
    ) -> None:
        mock_redis.client.get.return_value = "0"
        mock_redis.client.keys.return_value = []
        mock_redis.client.ttl.return_value = -2
        mock_redis.client.lrange.return_value = []

        with patch("agents.service.AgentManagerService") as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc.list_agents.return_value = ([], 0)
            mock_svc.get_agent_events.return_value = []
            mock_svc_cls.return_value = mock_svc

            resp = client.get(endpoint)

        assert resp.headers.get("Sunset") == "2026-06-01"

    @pytest.mark.parametrize("endpoint", LEGACY_GET_ENDPOINTS)
    def test_get_endpoints_have_x_deprecated_use_header(
        self,
        client: TestClient,
        mock_redis: MagicMock,
        mock_ea_manager: MagicMock,
        mock_state_machine: MagicMock,
        endpoint: str,
    ) -> None:
        mock_redis.client.get.return_value = "0"
        mock_redis.client.keys.return_value = []
        mock_redis.client.ttl.return_value = -2
        mock_redis.client.lrange.return_value = []

        with patch("agents.service.AgentManagerService") as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc.list_agents.return_value = ([], 0)
            mock_svc.get_agent_events.return_value = []
            mock_svc_cls.return_value = mock_svc

            resp = client.get(endpoint)

        assert "/api/v1/agent-manager" in (resp.headers.get("X-Deprecated-Use") or "")

    @pytest.mark.parametrize("endpoint,body", LEGACY_POST_ENDPOINTS)
    def test_post_endpoints_have_deprecation_headers(
        self,
        client: TestClient,
        mock_redis: MagicMock,
        endpoint: str,
        body: dict,
    ) -> None:
        with (
            patch("api.ea_router._audit"),
            patch("agents.service.AgentManagerService") as mock_svc_cls,
        ):
            mock_svc = AsyncMock()
            mock_svc.list_agents.return_value = ([], 0)
            mock_svc_cls.return_value = mock_svc

            resp = client.post(endpoint, json=body)

        assert resp.status_code == 200
        assert resp.headers.get("Deprecation") == "true"
        assert resp.headers.get("Sunset") == "2026-06-01"
        assert "/api/v1/agent-manager" in (resp.headers.get("X-Deprecated-Use") or "")


# ── 2. Response shape backward compatibility ────────────────────


class TestStatusEndpointShape:
    """GET /api/v1/ea/status must return the legacy EAStatus shape."""

    def test_status_returns_all_legacy_fields(
        self,
        client: TestClient,
        mock_redis: MagicMock,
        mock_ea_manager: MagicMock,
        mock_state_machine: MagicMock,
    ) -> None:
        mock_redis.client.get.return_value = "0"
        mock_redis.client.keys.return_value = []
        mock_redis.client.ttl.return_value = -2

        with patch("agents.service.AgentManagerService") as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc.list_agents.return_value = ([], 0)
            mock_svc_cls.return_value = mock_svc

            resp = client.get("/api/v1/ea/status")

        assert resp.status_code == 200
        data = resp.json()
        expected_keys = {
            "healthy",
            "running",
            "engine_state",
            "queue_depth",
            "queue_max",
            "safe_mode",
            "agents_total",
            "agents_connected",
            "total_failures",
            "recent_failures",
            "cooldown_active",
            "updated_at",
        }
        assert expected_keys.issubset(set(data.keys()))


class TestAgentsEndpointShape:
    """GET /api/v1/ea/agents must return agents with legacy status strings."""

    @pytest.mark.parametrize(
        "am_status,expected_legacy",
        [
            ("ONLINE", "connected"),
            ("WARNING", "degraded"),
            ("OFFLINE", "disconnected"),
            ("QUARANTINED", "cooldown"),
            ("DISABLED", "disconnected"),
        ],
    )
    def test_agents_maps_am_status_to_legacy(
        self,
        client: TestClient,
        am_status: str,
        expected_legacy: str,
    ) -> None:
        am_agent = {
            "id": "agent-uuid-1",
            "status": am_status,
            "linked_account_id": "ACC-1",
            "strategy_profile": "default",
            "version": "3.0.0",
            "ea_class": "PRIMARY",
            "runtime": {
                "last_heartbeat": None,
                "last_success": None,
                "last_failure": None,
                "failure_reason": None,
                "trades_executed": 0,
                "trades_failed": 0,
                "uptime_seconds": 0,
            },
        }

        with patch("agents.service.AgentManagerService") as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc.list_agents.return_value = ([am_agent], 1)
            mock_svc_cls.return_value = mock_svc

            resp = client.get("/api/v1/ea/agents")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["status"] == expected_legacy

    def test_agents_returns_legacy_fields(
        self,
        client: TestClient,
    ) -> None:
        am_agent = {
            "id": "agent-uuid-1",
            "status": "ONLINE",
            "linked_account_id": "ACC-1",
            "strategy_profile": "default",
            "version": "3.0.0",
            "ea_class": "PRIMARY",
            "runtime": {
                "last_heartbeat": None,
                "last_success": None,
                "last_failure": None,
                "failure_reason": None,
                "trades_executed": 10,
                "trades_failed": 2,
                "uptime_seconds": 7200,
            },
        }

        with patch("agents.service.AgentManagerService") as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc.list_agents.return_value = ([am_agent], 1)
            mock_svc_cls.return_value = mock_svc

            resp = client.get("/api/v1/ea/agents")

        assert resp.status_code == 200
        data = resp.json()
        agent = data[0]
        assert "agent_id" in agent
        assert "account_id" in agent
        assert "profile" in agent
        assert "status" in agent
        assert "healthy" in agent
        assert "trades_executed" in agent
        assert "trades_failed" in agent
        assert "uptime_seconds" in agent


# ── 3. Graceful degradation when Agent Manager unavailable ──────


class TestGracefulDegradation:
    """Endpoints fall back to Redis when Agent Manager service is unavailable."""

    def test_status_falls_back_to_redis(
        self,
        client: TestClient,
        mock_redis: MagicMock,
        mock_ea_manager: MagicMock,
        mock_state_machine: MagicMock,
    ) -> None:
        mock_redis.client.get.return_value = "1"  # safe_mode enabled
        mock_redis.client.keys.return_value = [f"{EA_AGENT_PREFIX}ea-1".encode()]
        mock_redis.client.hgetall.return_value = {k.encode(): v.encode() for k, v in _make_agent_hash("ea-1").items()}
        mock_redis.client.ttl.return_value = -2

        # Simulate Agent Manager unavailable
        with patch("agents.service.AgentManagerService", side_effect=ImportError("unavailable")):
            resp = client.get("/api/v1/ea/status")

        assert resp.status_code == 200
        data = resp.json()
        # Falls back to Redis: safe_mode should be True from Redis
        assert "safe_mode" in data
        assert data["safe_mode"] is True

    def test_agents_falls_back_to_redis(
        self,
        client: TestClient,
        mock_redis: MagicMock,
        mock_ea_manager: MagicMock,
        mock_state_machine: MagicMock,
    ) -> None:
        mock_redis.client.keys.return_value = [f"{EA_AGENT_PREFIX}ea-redis-1".encode()]
        mock_redis.client.hgetall.return_value = {
            k.encode(): v.encode() for k, v in _make_agent_hash("ea-redis-1").items()
        }

        with patch("agents.service.AgentManagerService", side_effect=ImportError("unavailable")):
            resp = client.get("/api/v1/ea/agents")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["agent_id"] == "ea-redis-1"

    def test_logs_falls_back_to_redis(
        self,
        client: TestClient,
        mock_redis: MagicMock,
    ) -> None:
        log_entries = [
            json.dumps({"id": "1", "timestamp": "2026-01-01T00:00:00", "level": "INFO", "message": "redis-ok"}),
        ]
        mock_redis.client.lrange.return_value = log_entries

        with patch("agents.service.AgentManagerService", side_effect=ImportError("unavailable")):
            resp = client.get("/api/v1/ea/logs")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["message"] == "redis-ok"

    def test_restart_falls_back_to_redis(
        self,
        client: TestClient,
        mock_redis: MagicMock,
    ) -> None:
        with (
            patch("api.ea_router._audit"),
            patch("agents.service.AgentManagerService", side_effect=ImportError("unavailable")),
        ):
            resp = client.post("/api/v1/ea/restart", json={"reason": "test-fallback"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["queued"] is True
        # Redis restart marker is always written for backward compat
        mock_redis.client.set.assert_called()

    def test_safe_mode_falls_back_to_redis(
        self,
        client: TestClient,
        mock_redis: MagicMock,
    ) -> None:
        with (
            patch("api.ea_router._audit"),
            patch("agents.service.AgentManagerService", side_effect=ImportError("unavailable")),
        ):
            resp = client.post("/api/v1/ea/safe-mode", json={"enabled": True, "reason": "test-fallback"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["safe_mode"] is True
        mock_redis.client.set.assert_called_with(EA_SAFE_MODE_KEY, "1")


# ── 4. Delegation tests ──────────────────────────────────────────


class TestAgentManagerDelegation:
    """POST endpoints properly delegate to Agent Manager service."""

    def test_restart_delegates_to_agent_manager(
        self,
        client: TestClient,
        mock_redis: MagicMock,
    ) -> None:
        online_agent = {"id": "am-agent-1", "status": "ONLINE", "locked": False}

        with (
            patch("api.ea_router._audit"),
            patch("agents.service.AgentManagerService") as mock_svc_cls,
            patch("agents.models.LockAgentRequest") as mock_lock_req,
        ):
            mock_svc = AsyncMock()
            mock_svc.list_agents.return_value = ([online_agent], 1)
            mock_svc.lock_agent.return_value = {"id": "am-agent-1", "locked": True}
            mock_svc.unlock_agent.return_value = {"id": "am-agent-1", "locked": False}
            mock_svc_cls.return_value = mock_svc

            mock_lock_req.return_value = MagicMock(reason="test", locked_by="user:dashboard")

            resp = client.post("/api/v1/ea/restart", json={"reason": "test-delegation"})

        assert resp.status_code == 200
        assert resp.json()["queued"] is True

    def test_safe_mode_delegates_to_agent_manager(
        self,
        client: TestClient,
        mock_redis: MagicMock,
    ) -> None:
        am_agent = {"id": "am-agent-1", "status": "ONLINE"}

        with (
            patch("api.ea_router._audit"),
            patch("agents.service.AgentManagerService") as mock_svc_cls,
            patch("agents.models.UpdateAgentRequest") as mock_upd_req,
        ):
            mock_svc = AsyncMock()
            mock_svc.list_agents.return_value = ([am_agent], 1)
            mock_svc.update_agent.return_value = {"id": "am-agent-1", "safe_mode": True}
            mock_svc_cls.return_value = mock_svc

            mock_upd_req.return_value = MagicMock(safe_mode=True)

            resp = client.post("/api/v1/ea/safe-mode", json={"enabled": True, "reason": "test"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["safe_mode"] is True


# ── 5. Logs endpoint maps AgentEvent to legacy EALog format ─────


class TestLogsEndpointMapping:
    """GET /api/v1/ea/logs maps Agent Manager events to legacy EALog format."""

    def test_logs_from_agent_manager_have_legacy_shape(
        self,
        client: TestClient,
    ) -> None:
        am_event = {
            "id": "evt-1",
            "agent_id": "am-agent-1",
            "event_type": "STATUS_CHANGE",
            "severity": "WARNING",
            "message": "Agent went degraded",
            "metadata": {},
            "created_at": "2026-01-01T12:00:00",
        }

        with patch("agents.service.AgentManagerService") as mock_svc_cls:
            mock_svc = AsyncMock()
            mock_svc.list_agents.return_value = ([{"id": "am-agent-1"}], 1)
            mock_svc.get_agent_events.return_value = [am_event]
            mock_svc_cls.return_value = mock_svc

            resp = client.get("/api/v1/ea/logs")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        if data:
            log = data[0]
            assert "id" in log
            assert "timestamp" in log
            assert "level" in log
            assert "message" in log
