from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi import HTTPException as FastAPIHTTPException
from fastapi.testclient import TestClient

from agents.exceptions import AgentValidationError
from agents.models import ExecutionModeEnum, UpdateAgentRequest
from agents.service import AgentManagerService
from api.executor_governance_router import router
from api.middleware import governance
from api.middleware.auth import verify_token
from api.middleware.governance import GovernanceContext
from execution.mt5_executor_governance import (
    GovernanceSnapshot,
    ModeTransitionError,
    get_mt5_executor_governance_repository,
)
from services.ea_bridge import main as bridge_main


class FakeGovernanceRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def global_snapshot(self) -> GovernanceSnapshot:
        return GovernanceSnapshot(True, "DEFAULT_ENGAGED", 1)

    async def executor_snapshot(self, executor_id: object) -> GovernanceSnapshot:
        return GovernanceSnapshot(True, "DEFAULT_ENGAGED", 1, str(executor_id), "SHADOW", 1)

    async def set_kill_switch(self, **kwargs: object) -> GovernanceSnapshot:
        self.calls.append(("kill_switch", kwargs))
        return GovernanceSnapshot(bool(kwargs["active"]), str(kwargs["reason"]), 2)

    async def transition_mode(self, executor_id: object, **kwargs: object) -> GovernanceSnapshot:
        self.calls.append(("mode", {"executor_id": executor_id, **kwargs}))
        target = kwargs["target_mode"]
        if str(target) == "LIVE":
            raise ModeTransitionError("LIVE promotion is blocked by the B2 rollout contract")
        return GovernanceSnapshot(True, "DEFAULT_ENGAGED", 1, str(executor_id), str(target), 2)


def _context(*, role: str = "admin", scopes: frozenset[str] | None = None) -> GovernanceContext:
    return GovernanceContext(
        role=role,
        actor="operator:test",
        auth_method="jwt",
        scopes=scopes or frozenset({"ea:write"}),
        reason="",
    )


def _client(
    monkeypatch: pytest.MonkeyPatch, repository: FakeGovernanceRepository, context: GovernanceContext
) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_token] = lambda: {"sub": context.actor}
    app.dependency_overrides[get_mt5_executor_governance_repository] = lambda: repository
    monkeypatch.setattr(governance, "_resolve_context", lambda _token: context)
    monkeypatch.setattr(governance, "_safe_mode_enabled", lambda: False)
    monkeypatch.setenv("DASHBOARD_ACTION_PIN", "2468")
    return TestClient(app)


def _headers(*, pin: str | None = "2468") -> dict[str, str]:
    headers = {
        "Authorization": "Bearer test-token",
        "X-Edit-Mode": "ON",
        "X-Action-Reason": "operator drill",
    }
    if pin is not None:
        headers["X-Action-Pin"] = pin
    return headers


def test_kill_switch_is_admin_only_and_requires_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = FakeGovernanceRepository()
    missing_pin = _client(monkeypatch, repository, _context()).post(
        "/api/v1/ea/executor-governance/kill-switch",
        headers=_headers(pin=None),
        json={"active": False},
    )
    assert missing_pin.status_code == 403
    assert repository.calls == []

    trader = _client(monkeypatch, repository, _context(role="trader")).post(
        "/api/v1/ea/executor-governance/kill-switch",
        headers=_headers(),
        json={"active": False},
    )
    assert trader.status_code == 403
    assert repository.calls == []


def test_kill_switch_forwards_governed_actor_reason_and_version(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = FakeGovernanceRepository()
    response = _client(monkeypatch, repository, _context()).post(
        "/api/v1/ea/executor-governance/kill-switch",
        headers=_headers(),
        json={"active": False, "expected_version": 1},
    )

    assert response.status_code == 200, response.text
    assert response.json()["kill_switch_active"] is False
    assert repository.calls == [
        (
            "kill_switch",
            {
                "active": False,
                "actor": "operator:test",
                "reason": "operator drill",
                "expected_version": 1,
            },
        )
    ]


def test_execution_mode_is_critical_and_live_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = FakeGovernanceRepository()
    executor_id = uuid4()
    without_pin = _client(monkeypatch, repository, _context()).post(
        f"/api/v1/ea/executor-governance/executors/{executor_id}/execution-mode",
        headers=_headers(pin=None),
        json={"target_mode": "DEMO"},
    )
    assert without_pin.status_code == 403

    live = _client(monkeypatch, repository, _context()).post(
        f"/api/v1/ea/executor-governance/executors/{executor_id}/execution-mode",
        headers=_headers(),
        json={"target_mode": "LIVE"},
    )
    assert live.status_code == 422
    assert "blocked" in live.text.lower()


def test_write_requires_ea_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = FakeGovernanceRepository()
    response = _client(monkeypatch, repository, _context(scopes=frozenset({"trade:take"}))).post(
        "/api/v1/ea/executor-governance/kill-switch",
        headers=_headers(),
        json={"active": True},
    )
    assert response.status_code == 403
    assert "ea:write" in response.text


@pytest.mark.asyncio
async def test_generic_agent_update_cannot_bypass_edumb_mode_governance() -> None:
    repository = AsyncMock()
    repository.get_agent.return_value = {
        "id": str(uuid4()),
        "ea_subtype": "EDUMB",
        "execution_mode": "SHADOW",
    }
    service = AgentManagerService(repo=repository)

    with pytest.raises(AgentValidationError, match="executor-governance"):
        await service.update_agent(
            repository.get_agent.return_value["id"],
            UpdateAgentRequest(execution_mode=ExecutionModeEnum.DEMO),
            performed_by="operator:test",
        )

    repository.update_agent.assert_not_awaited()


class _HealthyPostgres:
    async def health_check(self) -> dict[str, bool]:
        return {"connected": True}

    async def fetchrow(self, _query: str) -> dict[str, str]:
        return {"name": "execution_commands"}


class _ReadinessGovernance:
    ready = True

    def __init__(self, *, pg: object) -> None:
        self.pg = pg

    async def schema_status(self) -> dict[str, bool]:
        return {"ready": self.ready, "immutable_audit_trigger": self.ready}

    async def global_snapshot(self) -> GovernanceSnapshot:
        return GovernanceSnapshot(True, "DEFAULT_ENGAGED", 1)


class _ReadinessCommands:
    ready = True

    def __init__(self, *, pg: object) -> None:
        self.pg = pg

    async def signed_wire_schema_status(self) -> dict[str, bool]:
        return {"ready": self.ready, "signed_wire_constraint": self.ready}


@pytest.mark.asyncio
async def test_ea_bridge_readiness_exposes_fail_closed_governance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTOR_BRIDGE_AUTH_SECRET", "a" * 32)
    monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_SECRET", "b" * 32)
    monkeypatch.setattr(bridge_main, "pg_client", _HealthyPostgres())
    monkeypatch.setattr(bridge_main, "MT5ExecutorGovernanceRepository", _ReadinessGovernance)
    monkeypatch.setattr(bridge_main, "MT5CommandRepository", _ReadinessCommands)

    result = await bridge_main.health_ready()

    assert result["executor_governance"]["ready"] is True
    assert result["executor_governance"]["kill_switch_active"] is True
    assert result["executor_signed_wire"]["ready"] is True


@pytest.mark.asyncio
async def test_ea_bridge_readiness_rejects_missing_governance_guarantee(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NotReadyGovernance(_ReadinessGovernance):
        ready = False

    monkeypatch.setenv("EXECUTOR_BRIDGE_AUTH_SECRET", "a" * 32)
    monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_SECRET", "b" * 32)
    monkeypatch.setattr(bridge_main, "pg_client", _HealthyPostgres())
    monkeypatch.setattr(bridge_main, "MT5ExecutorGovernanceRepository", _NotReadyGovernance)
    monkeypatch.setattr(bridge_main, "MT5CommandRepository", _ReadinessCommands)

    with pytest.raises(FastAPIHTTPException) as raised:
        await bridge_main.health_ready()

    assert raised.value.status_code == 503


@pytest.mark.asyncio
async def test_ea_bridge_readiness_rejects_missing_signed_wire_guarantee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NotReadyCommands(_ReadinessCommands):
        ready = False

    monkeypatch.setenv("EXECUTOR_BRIDGE_AUTH_SECRET", "a" * 32)
    monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_SECRET", "b" * 32)
    monkeypatch.setattr(bridge_main, "pg_client", _HealthyPostgres())
    monkeypatch.setattr(bridge_main, "MT5ExecutorGovernanceRepository", _ReadinessGovernance)
    monkeypatch.setattr(bridge_main, "MT5CommandRepository", _NotReadyCommands)

    with pytest.raises(FastAPIHTTPException) as raised:
        await bridge_main.health_ready()

    assert raised.value.status_code == 503
