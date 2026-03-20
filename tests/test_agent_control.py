"""Tests for enhanced EA Agent Control endpoints.

Covers: GET /status (enriched), GET /agents, GET /logs (with filter),
POST /restart (outcome), POST /safe-mode (sync).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.ea_router import EA_AGENT_PREFIX, EA_SAFE_MODE_KEY, _get_agents, router

# ── helpers ───────────────────────────────────────────────────


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _override_auth(app: FastAPI) -> None:
    """Disable auth and governance middleware for unit tests."""
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


# ── fixtures ──────────────────────────────────────────────────


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
        m._queue = MagicMock()
        m._queue.qsize.return_value = 3
        m._queue.maxsize = 200
        m.queue_snapshot.return_value = {
            "queue_depth": 3,
            "queue_max": 200,
            "overload_mode": "reject_new",
            "overload_rejections": 0,
            "overload_drops": 0,
            "running": True,
        }
        yield m


@pytest.fixture()
def mock_state_machine():
    with patch("api.ea_router._state_machine") as m:
        m.snapshot.return_value = {"state": "IDLE"}
        yield m


# ── Unit: agent health summary mapper ────────────────────────


class TestAgentHealthSummaryMapper:
    """Test _get_agents() builds correct agent summaries."""

    def test_returns_list_from_redis_keys(self, mock_redis: MagicMock) -> None:
        mock_redis.client.keys.return_value = [
            f"{EA_AGENT_PREFIX}ea-1".encode(),
            f"{EA_AGENT_PREFIX}ea-2".encode(),
        ]
        mock_redis.client.hgetall.side_effect = [
            {k.encode(): v.encode() for k, v in _make_agent_hash("ea-1").items()},
            {k.encode(): v.encode() for k, v in _make_agent_hash("ea-2", status="disconnected").items()},
        ]

        agents = _get_agents()
        assert len(agents) == 2
        assert agents[0]["agent_id"] == "ea-1"
        assert agents[0]["healthy"] is True
        assert agents[1]["agent_id"] == "ea-2"
        assert agents[1]["healthy"] is False

    def test_fallback_when_no_redis_agents(
        self, mock_redis: MagicMock, mock_ea_manager: MagicMock, mock_state_machine: MagicMock
    ) -> None:
        mock_redis.client.keys.return_value = []
        agents = _get_agents()
        assert len(agents) == 1
        assert agents[0]["agent_id"] == "ea-primary"
        assert agents[0]["healthy"] is True

    def test_redis_error_returns_fallback(
        self, mock_redis: MagicMock, mock_ea_manager: MagicMock, mock_state_machine: MagicMock
    ) -> None:
        mock_redis.client.keys.side_effect = Exception("Redis down")
        agents = _get_agents()
        assert len(agents) == 1
        assert agents[0]["agent_id"] == "ea-primary"


# ── Unit: safe mode state formatter ──────────────────────────


class TestSafeModeState:
    """Test safe mode value parsing from Redis."""

    @pytest.mark.parametrize(
        "raw_value,expected",
        [
            ("1", True),
            ("true", True),
            ("on", True),
            ("enabled", True),
            ("0", False),
            ("false", False),
            ("off", False),
            (None, False),
        ],
    )
    def test_safe_mode_parsing(
        self,
        client: TestClient,
        mock_redis: MagicMock,
        mock_ea_manager: MagicMock,
        mock_state_machine: MagicMock,
        raw_value: str | None,
        expected: bool,
    ) -> None:
        mock_redis.client.get.return_value = raw_value
        mock_redis.client.keys.return_value = []
        mock_redis.client.ttl.return_value = -2

        resp = client.get("/api/v1/ea/status")
        assert resp.status_code == 200
        assert resp.json()["safe_mode"] is expected


# ── Integration: status endpoint ─────────────────────────────


class TestStatusEndpoint:
    def test_status_returns_enriched_fields(
        self,
        client: TestClient,
        mock_redis: MagicMock,
        mock_ea_manager: MagicMock,
        mock_state_machine: MagicMock,
    ) -> None:
        mock_redis.client.get.return_value = "0"
        mock_redis.client.keys.return_value = []
        mock_redis.client.ttl.return_value = -2

        resp = client.get("/api/v1/ea/status")
        data = resp.json()

        assert resp.status_code == 200
        assert "agents_total" in data
        assert "agents_connected" in data
        assert "recent_failures" in data
        assert "cooldown_active" in data
        assert data["healthy"] is True
        assert data["queue_depth"] == 3

    def test_cooldown_active_when_restart_pending(
        self,
        client: TestClient,
        mock_redis: MagicMock,
        mock_ea_manager: MagicMock,
        mock_state_machine: MagicMock,
    ) -> None:
        mock_redis.client.get.return_value = "0"
        mock_redis.client.keys.return_value = []
        mock_redis.client.ttl.return_value = 300  # 5 min TTL

        resp = client.get("/api/v1/ea/status")
        assert resp.json()["cooldown_active"] is True


# ── Integration: agents endpoint ─────────────────────────────


class TestAgentsEndpoint:
    def test_agents_returns_list(
        self,
        client: TestClient,
        mock_redis: MagicMock,
        mock_ea_manager: MagicMock,
        mock_state_machine: MagicMock,
    ) -> None:
        mock_redis.client.keys.return_value = [f"{EA_AGENT_PREFIX}ea-1".encode()]
        mock_redis.client.hgetall.return_value = {k.encode(): v.encode() for k, v in _make_agent_hash("ea-1").items()}

        resp = client.get("/api/v1/ea/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data[0]["agent_id"] == "ea-1"


# ── Integration: restart mutation updates status ──────────────


class TestRestartMutation:
    def test_restart_returns_queued(
        self,
        client: TestClient,
        mock_redis: MagicMock,
    ) -> None:
        with patch("api.ea_router._audit"):
            resp = client.post(
                "/api/v1/ea/restart",
                json={"reason": "Test restart"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["queued"] is True
        assert "requested_at" in data


# ── Integration: safe-mode mutation syncs with page state ─────


class TestSafeModeMutation:
    def test_enable_safe_mode(
        self,
        client: TestClient,
        mock_redis: MagicMock,
    ) -> None:
        with patch("api.ea_router._audit"):
            resp = client.post(
                "/api/v1/ea/safe-mode",
                json={"enabled": True, "reason": "Testing"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["safe_mode"] is True

        mock_redis.client.set.assert_called_with(EA_SAFE_MODE_KEY, "1")

    def test_disable_safe_mode(
        self,
        client: TestClient,
        mock_redis: MagicMock,
    ) -> None:
        with patch("api.ea_router._audit"):
            resp = client.post(
                "/api/v1/ea/safe-mode",
                json={"enabled": False, "reason": "Testing"},
            )
        assert resp.status_code == 200
        assert resp.json()["safe_mode"] is False
        mock_redis.client.set.assert_called_with(EA_SAFE_MODE_KEY, "0")


# ── Integration: logs with agent filter ──────────────────────


class TestLogsFiltering:
    def test_logs_returns_all(
        self,
        client: TestClient,
        mock_redis: MagicMock,
    ) -> None:
        log_entries = [
            json.dumps({"id": "1", "timestamp": "2026-01-01T00:00:00", "level": "INFO", "message": "ok"}),
            json.dumps({"id": "2", "timestamp": "2026-01-01T00:01:00", "level": "WARNING", "message": "warn"}),
        ]
        mock_redis.client.lrange.return_value = log_entries

        resp = client.get("/api/v1/ea/logs")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_logs_filtered_by_agent(
        self,
        client: TestClient,
        mock_redis: MagicMock,
    ) -> None:
        log_entries = [
            json.dumps({"id": "1", "timestamp": "T1", "level": "INFO", "message": "a", "agent_id": "ea-1"}),
            json.dumps({"id": "2", "timestamp": "T2", "level": "INFO", "message": "b", "agent_id": "ea-2"}),
        ]
        mock_redis.client.lrange.return_value = log_entries

        resp = client.get("/api/v1/ea/logs?agent_id=ea-1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["agent_id"] == "ea-1"
