"""Contract tests for the EA ↔ backend interface.

Verifies that:
- The heartbeat payload schema sent by the EA matches what ``agent_ingest_router``
  accepts (``IngestHeartbeatRequest``).
- The execution command JSON written by ``mt5_bridge.py`` matches
  ``ea_interface/command_schema.json``.
- The ``POST /api/v1/ea/ping`` endpoint accepts valid requests and rejects
  invalid ones.
- The ping endpoint enforces a per-agent rate limit of 10 requests/minute.
"""

from __future__ import annotations

import json
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.models import (
    AgentStatusEnum,
    IngestHeartbeatRequest,
    IngestPortfolioSnapshotRequest,
    IngestStatusChangeRequest,
)
from api.ea_router import (
    _PING_MAX_PER_MINUTE,
    _PING_RATE_LIMIT,
    _check_ping_rate_limit,
    router,
)
from ea_interface.mt5_bridge import ExecutionCommand, ExecutionReport

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _override_auth(app: FastAPI) -> None:
    from api.middleware.auth import verify_token
    from api.middleware.governance import enforce_write_policy

    app.dependency_overrides[verify_token] = lambda: None
    app.dependency_overrides[enforce_write_policy] = lambda: None


@pytest.fixture()
def client():
    app = _make_app()
    _override_auth(app)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Clear the global rate-limit store before every test."""
    _PING_RATE_LIMIT.clear()
    yield
    _PING_RATE_LIMIT.clear()


# ---------------------------------------------------------------------------
# Section 1 — Heartbeat payload contract
# ---------------------------------------------------------------------------


class TestHeartbeatPayloadContract:
    """The heartbeat JSON an MT5 EA would send must match IngestHeartbeatRequest."""

    def test_minimal_heartbeat_is_valid(self) -> None:
        """Only required fields: agent_id + timestamp."""
        payload: dict[str, Any] = {
            "agent_id": str(uuid.uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        req = IngestHeartbeatRequest(**payload)
        assert req.agent_id is not None
        assert req.timestamp is not None

    def test_full_heartbeat_is_valid(self) -> None:
        """All optional metric fields are accepted."""
        payload: dict[str, Any] = {
            "agent_id": str(uuid.uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "trades_executed": 10,
            "trades_failed": 1,
            "uptime_seconds": 3600,
            "cpu_usage_pct": 12.5,
            "memory_mb": 256.0,
            "connection_latency_ms": 45.3,
        }
        req = IngestHeartbeatRequest(**payload)
        assert req.trades_executed == 10
        assert req.uptime_seconds == 3600

    def test_heartbeat_missing_agent_id_is_invalid(self) -> None:
        """Missing agent_id must raise a validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            IngestHeartbeatRequest(timestamp=datetime.now(UTC).isoformat())  # type: ignore[call-arg]

    def test_heartbeat_missing_timestamp_is_invalid(self) -> None:
        """Missing timestamp must raise a validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            IngestHeartbeatRequest(agent_id=str(uuid.uuid4()))  # type: ignore[call-arg]

    def test_status_change_payload_is_valid(self) -> None:
        """Status-change notification contract."""
        payload: dict[str, Any] = {
            "agent_id": str(uuid.uuid4()),
            "new_status": AgentStatusEnum.ONLINE,
            "reason": "EA initialized",
        }
        req = IngestStatusChangeRequest(**payload)
        assert req.new_status == AgentStatusEnum.ONLINE

    def test_portfolio_snapshot_payload_is_valid(self) -> None:
        """Portfolio snapshot contract."""
        payload: dict[str, Any] = {
            "agent_id": str(uuid.uuid4()),
            "account_id": "12345678",
            "balance": 10000.0,
            "equity": 10250.0,
            "margin_used": 500.0,
            "margin_free": 9500.0,
            "open_positions": 2,
            "daily_pnl": 250.0,
            "floating_pnl": 125.0,
        }
        req = IngestPortfolioSnapshotRequest(**payload)
        assert req.balance == 10000.0
        assert req.open_positions == 2


# ---------------------------------------------------------------------------
# Section 2 — Execution command schema contract (mt5_bridge.py)
# ---------------------------------------------------------------------------


class TestExecutionCommandContract:
    """Verify ExecutionCommand from mt5_bridge.py serialises to a valid command JSON."""

    def _command_dict(self, **overrides: Any) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "signal_id": "sig-abc-001",
            "symbol": "XAUUSD",
            "direction": "BUY",
            "order_type": "LIMIT",
            "entry_price": 2350.00,
            "stop_loss": 2320.00,
            "take_profit": 2400.00,
            "lot_size": 0.10,
        }
        defaults.update(overrides)
        return defaults

    def test_execution_command_has_required_fields(self) -> None:
        cmd = ExecutionCommand(**self._command_dict())
        assert cmd.signal_id == "sig-abc-001"
        assert cmd.direction == "BUY"
        assert cmd.lot_size == 0.10
        assert cmd.magic_number == 151515
        assert cmd.timestamp > 0.0

    def test_execution_command_serialises_to_json(self) -> None:
        from dataclasses import asdict

        cmd = ExecutionCommand(**self._command_dict())
        d = asdict(cmd)
        payload = json.dumps(d)
        parsed = json.loads(payload)
        assert parsed["symbol"] == "XAUUSD"
        assert parsed["entry_price"] == 2350.00
        assert isinstance(parsed["timestamp"], float)

    def test_execution_report_has_required_fields(self) -> None:
        report = ExecutionReport(
            signal_id="sig-abc-001",
            event="ORDER_FILLED",
            broker_ticket=12345,
            fill_price=2351.50,
            slippage_pips=0.15,
        )
        assert report.event == "ORDER_FILLED"
        assert report.broker_ticket == 12345
        assert report.timestamp > 0.0

    def test_execution_report_event_is_recognised(self) -> None:
        """All events the EA reports must be known to the bridge."""
        valid_events = {
            "ORDER_PLACED",
            "ORDER_FILLED",
            "ORDER_CANCELLED",
            "ORDER_EXPIRED",
            "ORDER_FAILED",
            "SYSTEM_VIOLATION",
        }
        for event in valid_events:
            r = ExecutionReport(signal_id="x", event=event)
            assert r.event == event

    def test_command_schema_json_is_valid_json(self) -> None:
        """command_schema.json must be valid JSON and contain required keys."""
        from pathlib import Path

        schema_path = Path(__file__).parent.parent / "ea_interface" / "command_schema.json"
        assert schema_path.is_file(), "command_schema.json must exist"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema.get("type") == "object"
        assert "oneOf" in schema


# ---------------------------------------------------------------------------
# Section 3 — Ping endpoint contract
# ---------------------------------------------------------------------------


class TestPingEndpointContract:
    """POST /api/v1/ea/ping must accept valid requests and reject invalid ones."""

    def test_ping_valid_request_returns_ok(self, client: TestClient) -> None:
        agent_id = str(uuid.uuid4())

        with patch("agents.service.AgentManagerService") as mock_cls:
            mock_svc = AsyncMock()
            mock_svc.get_agent.return_value = {"id": agent_id, "status": "ONLINE"}
            mock_cls.return_value = mock_svc

            resp = client.post(
                "/api/v1/ea/ping",
                json={"agent_id": agent_id, "ea_version": "3.0.0", "ea_class": "PRIMARY"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "server_time" in data
        assert "agent_status" in data

    def test_ping_returns_deprecation_headers(self, client: TestClient) -> None:
        agent_id = str(uuid.uuid4())

        with patch("agents.service.AgentManagerService") as mock_cls:
            mock_svc = AsyncMock()
            mock_svc.get_agent.return_value = {"id": agent_id, "status": "ONLINE"}
            mock_cls.return_value = mock_svc

            resp = client.post(
                "/api/v1/ea/ping",
                json={"agent_id": agent_id},
            )

        assert resp.status_code == 200
        assert resp.headers.get("Deprecation") == "true"
        assert resp.headers.get("Sunset") == "2026-06-01"
        assert "/api/v1/agent-manager" in (resp.headers.get("X-Deprecated-Use") or "")

    def test_ping_missing_agent_id_is_rejected(self, client: TestClient) -> None:
        resp = client.post("/api/v1/ea/ping", json={"ea_version": "3.0.0"})
        assert resp.status_code == 422

    def test_ping_empty_agent_id_is_rejected(self, client: TestClient) -> None:
        resp = client.post("/api/v1/ea/ping", json={"agent_id": ""})
        assert resp.status_code == 422

    def test_ping_unregistered_agent_returns_404(self, client: TestClient) -> None:
        agent_id = str(uuid.uuid4())

        with patch("agents.service.AgentManagerService") as mock_cls:
            mock_svc = AsyncMock()
            from agents.exceptions import AgentNotFoundError

            mock_svc.get_agent.side_effect = AgentNotFoundError(f"Agent {agent_id} not found")
            mock_cls.return_value = mock_svc

            resp = client.post("/api/v1/ea/ping", json={"agent_id": agent_id})

        assert resp.status_code == 404
        assert "not registered" in resp.json().get("detail", "").lower()

    def test_ping_with_defaults_is_valid(self, client: TestClient) -> None:
        """ea_version and ea_class have defaults and are optional."""
        agent_id = str(uuid.uuid4())

        with patch("agents.service.AgentManagerService") as mock_cls:
            mock_svc = AsyncMock()
            mock_svc.get_agent.return_value = {"id": agent_id, "status": "OFFLINE"}
            mock_cls.return_value = mock_svc

            resp = client.post("/api/v1/ea/ping", json={"agent_id": agent_id})

        assert resp.status_code == 200

    def test_ping_agent_status_reflects_backend(self, client: TestClient) -> None:
        """agent_status in response reflects what the Agent Manager returns."""
        agent_id = str(uuid.uuid4())

        for am_status in ("ONLINE", "WARNING", "OFFLINE", "QUARANTINED"):
            _PING_RATE_LIMIT.clear()
            with patch("agents.service.AgentManagerService") as mock_cls:
                mock_svc = AsyncMock()
                mock_svc.get_agent.return_value = {"id": agent_id, "status": am_status}
                mock_cls.return_value = mock_svc

                resp = client.post("/api/v1/ea/ping", json={"agent_id": agent_id})

            assert resp.status_code == 200
            assert resp.json()["agent_status"] == am_status

    def test_ping_agent_manager_unavailable_returns_ok_degraded(
        self, client: TestClient
    ) -> None:
        """If Agent Manager is unavailable (non-NotFound error), endpoint degrades gracefully."""
        agent_id = str(uuid.uuid4())

        with patch("agents.service.AgentManagerService") as mock_cls:
            mock_svc = AsyncMock()
            mock_svc.get_agent.side_effect = RuntimeError("DB connection failed")
            mock_cls.return_value = mock_svc

            resp = client.post("/api/v1/ea/ping", json={"agent_id": agent_id})

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        # agent_status is unknown when backend is down
        assert data["agent_status"] == "unknown"


# ---------------------------------------------------------------------------
# Section 4 — Ping rate limiting
# ---------------------------------------------------------------------------


class TestPingRateLimit:
    """Ping endpoint enforces max 10 requests per minute per agent."""

    def test_within_rate_limit_returns_true(self) -> None:
        agent_id = str(uuid.uuid4())
        for _ in range(_PING_MAX_PER_MINUTE):
            assert _check_ping_rate_limit(agent_id) is True

    def test_exceeding_rate_limit_returns_false(self) -> None:
        agent_id = str(uuid.uuid4())
        for _ in range(_PING_MAX_PER_MINUTE):
            _check_ping_rate_limit(agent_id)
        # The (N+1)-th call should be rejected
        assert _check_ping_rate_limit(agent_id) is False

    def test_rate_limit_is_per_agent(self) -> None:
        """Different agent IDs have independent rate-limit buckets."""
        agent_a = str(uuid.uuid4())
        agent_b = str(uuid.uuid4())

        for _ in range(_PING_MAX_PER_MINUTE):
            _check_ping_rate_limit(agent_a)

        # agent_a is exhausted but agent_b is not
        assert _check_ping_rate_limit(agent_a) is False
        assert _check_ping_rate_limit(agent_b) is True

    def test_sliding_window_allows_requests_after_expiry(self) -> None:
        """After 60 s the window resets and new requests are accepted."""
        agent_id = str(uuid.uuid4())
        now = datetime.now(UTC).timestamp()
        # Manually inject _PING_MAX_PER_MINUTE timestamps that are 61 s old
        _PING_RATE_LIMIT[agent_id] = deque(
            [now - 61.0] * _PING_MAX_PER_MINUTE
        )
        # Now a new request should be permitted (old ones expired)
        assert _check_ping_rate_limit(agent_id) is True

    def test_endpoint_returns_429_when_rate_limited(self, client: TestClient) -> None:
        """The HTTP endpoint returns 429 when the bucket is exhausted."""
        agent_id = str(uuid.uuid4())

        with patch("agents.service.AgentManagerService") as mock_cls:
            mock_svc = AsyncMock()
            mock_svc.get_agent.return_value = {"id": agent_id, "status": "ONLINE"}
            mock_cls.return_value = mock_svc

            # Exhaust the bucket
            for _ in range(_PING_MAX_PER_MINUTE):
                r = client.post("/api/v1/ea/ping", json={"agent_id": agent_id})
                assert r.status_code == 200

            # Next call must be 429
            r = client.post("/api/v1/ea/ping", json={"agent_id": agent_id})
        assert r.status_code == 429
        assert "rate limit" in r.json().get("detail", "").lower()
