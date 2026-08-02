from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.executor_bridge_router import router
from api.middleware.executor_auth import verify_executor_auth
from contracts.mt5_execution_protocol import ExecutionCommandV1, sha256_tag, sign_execution_command
from execution.mt5_command_repository import CommandClaim, get_mt5_command_repository
from execution.mt5_executor_governance import GovernanceSnapshot

SECRET = "z" * 64


def _command(executor_id: UUID) -> ExecutionCommandV1:
    now = datetime.now(UTC)
    payload = {
        "command_id": uuid4(),
        "idempotency_key": "acct:campaign:block:1:PLACE_PENDING",
        "revision": 1,
        "issued_at_utc": now,
        "not_before_utc": now,
        "expires_at_utc": now + timedelta(minutes=30),
        "executor_binding": {
            "executor_id": executor_id,
            "account_id": "acct-01",
            "login_hash": "sha256:" + "a" * 64,
            "broker_server": "Broker-Demo",
            "execution_mode": "SHADOW",
        },
        "source": {
            "source_event": "signal_json",
            "source_schema_version": "2.0",
            "source_signal_id": "signal-001",
            "source_signal_hash": "sha256:" + "b" * 64,
            "campaign_id": "campaign-001",
            "block_id": "block-001",
            "block_role": "PARENT",
            "lifecycle_anchor": "lifecycle-001",
            "valid_for_execution": True,
            "execution_gate_passed": True,
            "tradeplan_valid": True,
            "strategy_model": "STRATEGY_5S_CR_FINAL",
            "strategy_rule_version": "5scr.final.2026-07-19",
            "strategy_rule_status": "FROZEN",
            "strategy_proof_hash": "sha256:" + "c" * 64,
            "context_resolution_status": "RESOLVED",
            "confirmation_policy": "H1_CLOSED_PLUS_M15_BREAK_ACCEPTANCE_OR_FAILED_RECLAIM_RETEST",
        },
        "action": "PLACE_PENDING",
        "order": {
            "canonical_symbol": "EURUSD",
            "broker_symbol": "EURUSD.a",
            "side": "BUY",
            "order_type": "BUY_LIMIT",
            "volume": 0.1,
            "entry_price": 1.1,
            "stop_loss": 1.095,
            "take_profit": 1.11,
            "magic": 150015,
            "comment_tag": "W15:ABCDEF123456",
            "time_in_force": "SPECIFIED",
            "broker_expiration_utc": now + timedelta(minutes=30),
        },
        "guards": {
            "max_spread_points": 25,
            "max_price_drift_points": 15,
            "expected_margin_mode": "HEDGING",
            "risk_snapshot_id": "snapshot-001",
            "risk_reservation_id": "reservation-001",
            "balance_snapshot": 1000,
            "equity_snapshot": 1000,
        },
    }
    return sign_execution_command(payload, secret=SECRET, key_id="test")


class FakeRepository:
    def __init__(self, command: ExecutionCommandV1 | None = None) -> None:
        self.command = command

    async def register_executor(self, request: Any) -> dict[str, Any]:
        return {
            "executor_id": request.executor_id,
            "account_id": request.account_id,
            "execution_mode": "SHADOW",
            "status": "REGISTERED",
        }

    async def next_command(self, executor_id: UUID) -> ExecutionCommandV1 | None:
        return self.command

    async def governance_snapshot(self, executor_id: UUID) -> GovernanceSnapshot:
        return GovernanceSnapshot(
            executor_id=str(executor_id),
            execution_mode="SHADOW",
            mode_version=1,
            kill_switch_active=True,
            kill_switch_reason="TEST_ENGAGED",
            governance_version=1,
        )

    async def claim_command(self, *, executor_id: UUID, command_id: UUID, lease_seconds: int) -> CommandClaim:
        assert self.command is not None
        assert command_id == self.command.command_id
        return CommandClaim(
            command=self.command,
            claim_token="claim-token",
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease_seconds),
        )


def _client(executor_id: UUID, repository: FakeRepository) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_mt5_command_repository] = lambda: repository
    app.dependency_overrides[verify_executor_auth] = lambda: {
        "executor_id": str(executor_id),
        "sub": f"executor:{executor_id}",
    }
    return TestClient(app)


def test_empty_command_poll_returns_204() -> None:
    executor_id = uuid4()
    response = _client(executor_id, FakeRepository()).get(f"/api/v1/executors/{executor_id}/commands/next")
    assert response.status_code == 204
    assert response.headers["cache-control"] == "no-store"


def test_claim_returns_hash_bound_to_signed_command() -> None:
    executor_id = uuid4()
    command = _command(executor_id)
    response = _client(executor_id, FakeRepository(command)).post(
        f"/api/v1/commands/{command.command_id}/claim",
        json={"lease_seconds": 30},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["claim_token"] == "claim-token"
    assert data["request_hash"] == sha256_tag(command.model_dump(mode="json"))


def test_registration_path_is_bound_to_authenticated_executor() -> None:
    executor_id = uuid4()
    response = _client(executor_id, FakeRepository()).post(
        "/api/v1/executors/register",
        json={
            "protocol_version": "wolf15.mt5.exec.v1",
            "executor_id": str(uuid4()),
            "account_id": "acct-01",
            "login_hash": "sha256:" + "a" * 64,
            "broker_server": "Broker-Demo",
            "terminal_build": 5000,
            "ea_version": "0.10-shadow",
            "requested_mode": "SHADOW",
        },
    )
    assert response.status_code == 403
