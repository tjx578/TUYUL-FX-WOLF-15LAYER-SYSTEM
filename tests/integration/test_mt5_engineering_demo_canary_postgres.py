"""Real-PostgreSQL D0 gate: one scoped DEMO command and one broker order."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from contracts.mt5_execution_protocol import (
    ENGINEERING_DEMO_CANARY_EA_VERSION,
    ExecutionCommandV1,
    ExecutorMode,
    sha256_tag,
)
from execution.mt5_command_repository import MT5CommandRepository
from execution.mt5_engineering_demo_canary import (
    EngineeringDemoCanaryAuthorityV1,
    EngineeringDemoCanaryError,
    EngineeringDemoCanaryRequest,
)
from execution.mt5_executor_governance import MT5ExecutorGovernanceRepository
from tests.integration import test_mt5_bridge_postgres_e2e as bridge_e2e
from tests.integration.test_mt5_bridge_postgres_e2e import (
    ACCOUNT_ID,
    BROKER_SERVER,
    SIGNING_KEY_ID,
    SIGNING_SECRET,
    _auth_headers,
)

pytestmark = [pytest.mark.integration]

postgres = bridge_e2e.postgres
executor_id = bridge_e2e.executor_id
client = bridge_e2e.client
registered = bridge_e2e.registered


def _commands(postgres: Any) -> MT5CommandRepository:
    return MT5CommandRepository(pg=postgres)


def _governance(postgres: Any) -> MT5ExecutorGovernanceRepository:
    return MT5ExecutorGovernanceRepository(pg=postgres)


def _snapshot(
    executor_id: UUID,
    snapshot_id: str,
    *,
    account_id: str = ACCOUNT_ID,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "snapshot_id": snapshot_id,
        "captured_at_utc": now.isoformat(),
        "executor_id": str(executor_id),
        "account_id": account_id,
        "currency": "USD",
        "balance": 1000,
        "equity": 1000,
        "floating_pnl": 0,
        "used_margin": 0,
        "free_margin": 1000,
        "margin_mode": "HEDGING",
        "trade_allowed": True,
        "autotrading_enabled": True,
        "open_positions": [],
        "pending_orders": [],
        "broker_ledger_reconciled": True,
        "symbols": [
            {
                "canonical_symbol": "EURUSD",
                "broker_symbol": "EURUSD.a",
                "digits": 5,
                "point": 0.00001,
                "tick_size": 0.00001,
                "tick_value_profit": 1,
                "tick_value_loss": 1,
                "volume_min": 0.01,
                "volume_max": 100,
                "volume_step": 0.01,
                "stops_level_points": 0,
                "freeze_level_points": 0,
                "expiration_modes": ["GTC"],
            }
        ],
    }


def _request(
    executor_id: UUID,
    snapshot_id: str,
    *,
    canary_id: str | None = None,
    account_id: str = ACCOUNT_ID,
    broker_server: str = BROKER_SERVER,
) -> EngineeringDemoCanaryRequest:
    now = datetime.now(UTC)
    return EngineeringDemoCanaryRequest(
        canary_id=canary_id or f"d0-{uuid4().hex[:16]}",
        executor_id=executor_id,
        approved_account_id=account_id,
        approved_broker_server=broker_server,
        approved_canonical_symbol="EURUSD",
        approved_broker_symbol="EURUSD.a",
        expected_account_snapshot_id=snapshot_id,
        side="BUY",
        volume=0.01,
        entry_price=1.1,
        stop_loss=1.095,
        take_profit=1.11,
        max_spread_points=25,
        max_price_drift_points=10,
        issued_at_utc=now,
        expires_at_utc=now + timedelta(seconds=90),
    )


async def _prepare_demo_executor(
    client: AsyncClient,
    postgres: Any,
    executor_id: UUID,
    *,
    snapshot_id: str,
    account_id: str = ACCOUNT_ID,
) -> None:
    await postgres.execute(
        "UPDATE executor_instances SET ea_version=$2 WHERE executor_id=$1::uuid",
        str(executor_id),
        ENGINEERING_DEMO_CANARY_EA_VERSION,
    )
    await _governance(postgres).transition_mode(
        executor_id,
        target_mode=ExecutorMode.DEMO,
        actor="integration:d0",
        reason="prepare dedicated D0 executor",
        expected_mode=ExecutorMode.SHADOW,
    )
    heartbeat = {
        "executor_id": str(executor_id),
        "sent_at_utc": datetime.now(UTC).isoformat(),
        "terminal_connected": True,
        "trade_allowed": True,
        "autotrading_enabled": True,
        "account_snapshot": _snapshot(executor_id, snapshot_id, account_id=account_id),
    }
    response = await client.post(
        f"/api/v1/executors/{executor_id}/heartbeat",
        json=heartbeat,
        headers=_auth_headers(executor_id),
    )
    assert response.status_code == 200, response.text


async def _issue_and_arm(
    client: AsyncClient,
    postgres: Any,
    executor_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ExecutionCommandV1, str, EngineeringDemoCanaryRequest]:
    snapshot_id = f"snapshot-d0-{uuid4().hex[:12]}"
    await _prepare_demo_executor(client, postgres, executor_id, snapshot_id=snapshot_id)
    monkeypatch.setenv("WOLF15_ENABLE_ENGINEERING_DEMO_CANARY_ISSUANCE", "true")
    monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_SECRET", SIGNING_SECRET)
    monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_KEY_ID", SIGNING_KEY_ID)
    repository = _commands(postgres)
    authority = EngineeringDemoCanaryAuthorityV1(repository)
    request = _request(executor_id, snapshot_id)
    await authority.issue(request)

    blocked = await client.get(
        f"/api/v1/executors/{executor_id}/commands/next",
        headers=_auth_headers(executor_id),
    )
    assert blocked.status_code == 204
    assert blocked.headers["X-Kill-Switch-Active"] == "true"

    global_state = await _governance(postgres).global_snapshot()
    armed = await authority.arm(
        request.canary_id,
        actor="integration:d0",
        reason="one exact D0 command",
        expected_governance_version=global_state.governance_version,
    )
    assert armed["window_state"] == "ARMED"
    assert armed["max_broker_effects"] == 1

    poll = await client.get(
        f"/api/v1/executors/{executor_id}/commands/next",
        headers=_auth_headers(executor_id),
    )
    assert poll.status_code == 200, poll.text
    command = ExecutionCommandV1.model_validate(poll.json()["data"]["command"])
    claim = await client.post(
        f"/api/v1/commands/{command.command_id}/claim",
        json={"lease_seconds": 30},
        headers=_auth_headers(executor_id),
    )
    assert claim.status_code == 200, claim.text
    return command, str(claim.json()["data"]["claim_token"]), request


def _report(
    command: ExecutionCommandV1,
    executor_id: UUID,
    *,
    state: str,
    sequence: int,
    report_id: UUID | None = None,
    order_ticket: int | None = None,
    deal_ticket: int | None = None,
    position_id: int | None = None,
    filled_volume: float = 0,
) -> dict[str, Any]:
    assert command.order is not None
    return {
        "report_id": str(report_id or uuid4()),
        "command_id": str(command.command_id),
        "idempotency_key": command.idempotency_key,
        "sequence": sequence,
        "state": state,
        "event_time_utc": datetime.now(UTC).isoformat(),
        "executor_id": str(executor_id),
        "account_id": ACCOUNT_ID,
        "request_hash": sha256_tag(command.model_dump(mode="json")),
        "broker": {
            "order_ticket": order_ticket,
            "deal_ticket": deal_ticket,
            "position_id": position_id,
            "retcode": 10009,
        },
        "execution": {
            "requested_volume": command.order.volume,
            "filled_volume": filled_volume,
            "requested_price": command.order.entry_price,
            "filled_price": command.order.entry_price if filled_volume else None,
            "stop_loss": command.order.stop_loss,
            "take_profit": command.order.take_profit,
        },
        "reason_code": f"D0_{state}",
    }


@pytest.mark.asyncio
async def test_d0_one_order_lineage_auto_reengages_and_links_broker_entities(
    client: AsyncClient,
    postgres: Any,
    registered: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _commands(postgres)
    schema = await repository.engineering_demo_canary_schema_status()
    assert schema["ready"] is True
    command, claim_token, request = await _issue_and_arm(client, postgres, registered, monkeypatch)

    submitting = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(command, registered, state="SUBMITTING", sequence=1),
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert submitting.status_code == 202, submitting.text

    filled_id = uuid4()
    filled_body = _report(
        command,
        registered,
        state="FILLED",
        sequence=2,
        report_id=filled_id,
        order_ticket=700001,
        deal_ticket=800001,
        position_id=900001,
        filled_volume=0.01,
    )
    filled = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=filled_body,
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert filled.status_code == 202, filled.text
    assert filled.json()["data"]["command_state"] == "FILLED"

    governance = await _governance(postgres).global_snapshot()
    assert governance.kill_switch_active is True
    window = await postgres.fetchrow(
        "SELECT state, terminal_at FROM engineering_demo_canary_windows WHERE canary_id=$1",
        request.canary_id,
    )
    assert dict(window) == {"state": "CLOSED", "terminal_at": window["terminal_at"]}
    assert window["terminal_at"] is not None
    entities = await postgres.fetch(
        """
        SELECT entity_type, broker_ticket
        FROM broker_entities WHERE command_id=$1::uuid
        ORDER BY entity_type
        """,
        str(command.command_id),
    )
    assert {(row["entity_type"], row["broker_ticket"]) for row in entities} == {
        ("ORDER", 700001),
        ("DEAL", 800001),
        ("POSITION", 900001),
    }

    duplicate = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=filled_body,
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert duplicate.status_code == 202, duplicate.text
    assert duplicate.json()["data"]["duplicate"] is True
    count = await postgres.fetchrow(
        "SELECT count(*) AS count FROM broker_entities WHERE command_id=$1::uuid",
        str(command.command_id),
    )
    assert count["count"] == 3


@pytest.mark.asyncio
async def test_d0_rejects_a_second_broker_order_ticket(
    client: AsyncClient,
    postgres: Any,
    registered: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command, claim_token, _request_value = await _issue_and_arm(client, postgres, registered, monkeypatch)
    for body in (
        _report(command, registered, state="SUBMITTING", sequence=1),
        _report(command, registered, state="BROKER_ACCEPTED", sequence=2, order_ticket=700101),
    ):
        response = await client.post(
            f"/api/v1/commands/{command.command_id}/reports",
            json=body,
            headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
        )
        assert response.status_code == 202, response.text

    window_state = await postgres.fetchrow(
        "SELECT state FROM engineering_demo_canary_windows WHERE command_id=$1::uuid",
        str(command.command_id),
    )
    assert window_state is not None
    assert window_state["state"] == "RECONCILIATION_REQUIRED"

    active = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(command, registered, state="PENDING_ACTIVE", sequence=3, order_ticket=700101),
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert active.status_code == 202, active.text
    assert active.json()["data"]["command_state"] == "ACTIVE"
    window_state = await postgres.fetchrow(
        "SELECT state FROM engineering_demo_canary_windows WHERE command_id=$1::uuid",
        str(command.command_id),
    )
    assert window_state is not None
    assert window_state["state"] == "RECONCILIATION_REQUIRED"

    second = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(command, registered, state="PENDING_ACTIVE", sequence=4, order_ticket=700102),
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert second.status_code == 409
    assert "second broker order" in second.text
    entities = await postgres.fetch(
        "SELECT broker_ticket FROM broker_entities WHERE command_id=$1::uuid AND entity_type='ORDER'",
        str(command.command_id),
    )
    assert [row["broker_ticket"] for row in entities] == [700101]


@pytest.mark.asyncio
async def test_d0_unresolved_effect_blocks_a_second_account_canary(
    client: AsyncClient,
    postgres: Any,
    registered: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command, claim_token, _request_value = await _issue_and_arm(client, postgres, registered, monkeypatch)
    for body in (
        _report(command, registered, state="SUBMITTING", sequence=1),
        _report(command, registered, state="BROKER_ACCEPTED", sequence=2, order_ticket=700201),
    ):
        response = await client.post(
            f"/api/v1/commands/{command.command_id}/reports",
            json=body,
            headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
        )
        assert response.status_code == 202, response.text

    second_executor = uuid4()
    second_account = "acct-e2e-02"
    await postgres.execute(
        """
        INSERT INTO ea_agents (
            id, agent_name, ea_class, ea_subtype, execution_mode,
            reporter_mode, status, locked
        ) VALUES (
            $1::uuid, $2, 'PRIMARY', 'EDUMB', 'SHADOW',
            'FULL', 'OFFLINE', false
        )
        """,
        str(second_executor),
        f"MT5 D0 second-account E2E {second_executor}",
    )
    try:
        second_registration = bridge_e2e._registration(second_executor)
        second_registration["account_id"] = second_account
        registered_second = await client.post(
            "/api/v1/executors/register",
            json=second_registration,
            headers=_auth_headers(second_executor),
        )
        assert registered_second.status_code == 201, registered_second.text

        second_snapshot = f"snapshot-d0-{uuid4().hex[:12]}"
        await _prepare_demo_executor(
            client,
            postgres,
            second_executor,
            snapshot_id=second_snapshot,
            account_id=second_account,
        )
        second_request = _request(
            second_executor,
            second_snapshot,
            account_id=second_account,
            canary_id=f"d0-{uuid4().hex[:16]}",
        )
        with pytest.raises(EngineeringDemoCanaryError, match="another engineering canary effect"):
            await EngineeringDemoCanaryAuthorityV1(_commands(postgres)).issue(second_request)
    finally:
        await bridge_e2e._cleanup(postgres, second_executor)
        await postgres.execute("DELETE FROM ea_agents WHERE id=$1::uuid", str(second_executor))


@pytest.mark.asyncio
async def test_d0_expired_inflight_scope_requires_reconciliation_and_keeps_reporting_open(
    client: AsyncClient,
    postgres: Any,
    registered: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _commands(postgres)
    command, claim_token, request = await _issue_and_arm(client, postgres, registered, monkeypatch)
    submitting = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(command, registered, state="SUBMITTING", sequence=1),
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert submitting.status_code == 202, submitting.text

    await postgres.execute(
        """
        UPDATE engineering_demo_canary_windows
        SET expires_at=now() - interval '1 second'
        WHERE canary_id=$1
        """,
        request.canary_id,
    )
    assert await repository.expire_engineering_demo_canary_windows() == 1

    row = await postgres.fetchrow(
        """
        SELECT w.state AS window_state, w.terminal_at, c.state AS command_state
        FROM engineering_demo_canary_windows AS w
        JOIN execution_commands AS c ON c.command_id=w.command_id
        WHERE w.canary_id=$1
        """,
        request.canary_id,
    )
    assert dict(row) == {
        "window_state": "RECONCILIATION_REQUIRED",
        "terminal_at": None,
        "command_state": "SUBMITTING",
    }
    governance = await _governance(postgres).global_snapshot()
    assert governance.kill_switch_active is True

    ambiguous = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(
            command,
            registered,
            state="AMBIGUOUS_REQUIRES_RECONCILIATION",
            sequence=2,
        ),
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert ambiguous.status_code == 202, ambiguous.text
    assert ambiguous.json()["data"]["command_state"] == "AMBIGUOUS"


@pytest.mark.asyncio
async def test_d0_kill_switch_revokes_claimed_command_before_submit(
    client: AsyncClient,
    postgres: Any,
    registered: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command, claim_token, request = await _issue_and_arm(client, postgres, registered, monkeypatch)
    governance = _governance(postgres)
    current = await governance.global_snapshot()
    await governance.set_kill_switch(
        active=True,
        actor="integration:d0",
        reason="emergency stop before submit",
        expected_version=current.governance_version,
    )

    row = await postgres.fetchrow(
        """
        SELECT c.state AS command_state, w.state AS window_state, w.terminal_at
        FROM execution_commands AS c
        JOIN engineering_demo_canary_windows AS w ON w.command_id=c.command_id
        WHERE w.canary_id=$1
        """,
        request.canary_id,
    )
    assert row["command_state"] == "EXPIRED"
    assert row["window_state"] == "EXPIRED"
    assert row["terminal_at"] is not None

    submitting = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(command, registered, state="SUBMITTING", sequence=1),
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert submitting.status_code == 409


@pytest.mark.asyncio
async def test_d0_kill_after_submitting_requires_reconciliation_and_rejects_duplicate_authority(
    client: AsyncClient,
    postgres: Any,
    registered: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command, claim_token, request = await _issue_and_arm(client, postgres, registered, monkeypatch)
    submitting_body = _report(command, registered, state="SUBMITTING", sequence=1)
    submitting = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=submitting_body,
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert submitting.status_code == 202, submitting.text

    governance = _governance(postgres)
    current = await governance.global_snapshot()
    await governance.set_kill_switch(
        active=True,
        actor="integration:d0",
        reason="emergency stop after submit acknowledgement",
        expected_version=current.governance_version,
    )
    row = await postgres.fetchrow(
        """
        SELECT c.state AS command_state, w.state AS window_state, w.terminal_at
        FROM execution_commands AS c
        JOIN engineering_demo_canary_windows AS w ON w.command_id=c.command_id
        WHERE w.canary_id=$1
        """,
        request.canary_id,
    )
    assert dict(row) == {
        "command_state": "SUBMITTING",
        "window_state": "RECONCILIATION_REQUIRED",
        "terminal_at": None,
    }

    duplicate_submit = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=submitting_body,
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert duplicate_submit.status_code == 409
    assert "kill switch" in duplicate_submit.text

    ambiguous = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(
            command,
            registered,
            state="AMBIGUOUS_REQUIRES_RECONCILIATION",
            sequence=2,
        ),
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert ambiguous.status_code == 202, ambiguous.text


@pytest.mark.asyncio
async def test_d0_incomplete_filled_report_is_rejected_atomically(
    client: AsyncClient,
    postgres: Any,
    registered: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command, claim_token, _request_value = await _issue_and_arm(client, postgres, registered, monkeypatch)
    submitting = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(command, registered, state="SUBMITTING", sequence=1),
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert submitting.status_code == 202, submitting.text

    incomplete = _report(command, registered, state="FILLED", sequence=2)
    incomplete["broker"] = {}
    incomplete["execution"] = {}
    rejected = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=incomplete,
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert rejected.status_code == 409

    row = await postgres.fetchrow(
        """
        SELECT c.state, c.last_report_sequence,
               (SELECT count(*) FROM execution_reports r WHERE r.command_id=c.command_id) AS reports,
               (SELECT count(*) FROM broker_entities b WHERE b.command_id=c.command_id) AS entities
        FROM execution_commands AS c
        WHERE c.command_id=$1::uuid
        """,
        str(command.command_id),
    )
    assert dict(row) == {
        "state": "SUBMITTING",
        "last_report_sequence": 1,
        "reports": 1,
        "entities": 0,
    }
    await _governance(postgres).set_kill_switch(
        active=True,
        actor="integration:d0",
        reason="close incomplete evidence drill",
    )
