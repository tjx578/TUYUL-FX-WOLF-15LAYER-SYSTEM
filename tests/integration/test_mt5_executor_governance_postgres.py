"""Real-PostgreSQL gate for MT5 executor mode and kill-switch governance."""

from __future__ import annotations

import json
from importlib import import_module
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from contracts.mt5_execution_protocol import ExecutionCommandV1, ExecutorMode, sign_execution_command
from execution.mt5_command_repository import CommandConflictError, MT5CommandRepository
from execution.mt5_executor_governance import (
    GovernanceConflictError,
    ModeTransitionError,
    MT5ExecutorGovernanceRepository,
)
from tests.integration import test_mt5_bridge_postgres_e2e as bridge_e2e
from tests.integration.test_mt5_bridge_postgres_e2e import (
    SIGNING_KEY_ID,
    SIGNING_SECRET,
    _auth_headers,
    _claim,
    _cleanup,
    _command_state,
    _registration,
    _report,
    _shadow_command,
)

pytestmark = [pytest.mark.integration]

# Re-export B1's production-like pool, executor, and HTTP client fixtures. Using
# explicit assignments keeps them visible to pytest and to static analysis.
postgres = bridge_e2e.postgres
executor_id = bridge_e2e.executor_id
client = bridge_e2e.client
registered = bridge_e2e.registered


def _governance(postgres: Any) -> MT5ExecutorGovernanceRepository:
    return MT5ExecutorGovernanceRepository(pg=postgres)


def _commands(postgres: Any) -> MT5CommandRepository:
    return MT5CommandRepository(pg=postgres)


def _command_in_mode(executor_id: UUID, mode: ExecutorMode) -> ExecutionCommandV1:
    payload = _shadow_command(executor_id).model_dump(mode="json", exclude={"signature"})
    payload["executor_binding"]["execution_mode"] = mode.value
    return sign_execution_command(payload, secret=SIGNING_SECRET, key_id=SIGNING_KEY_ID)


def _demo_command(executor_id: UUID) -> ExecutionCommandV1:
    return _command_in_mode(executor_id, ExecutorMode.DEMO)


@pytest.mark.asyncio
async def test_migration_defaults_fail_closed_and_registration_cannot_request_privilege(
    client: AsyncClient,
    postgres: Any,
    executor_id: UUID,
) -> None:
    governance = _governance(postgres)
    schema = await governance.schema_status()
    assert schema == {
        "ready": True,
        "governance_table": True,
        "audit_table": True,
        "mode_version_column": True,
        "immutable_audit_trigger": True,
        "singleton_row": True,
    }
    global_state = await governance.global_snapshot()
    assert global_state.kill_switch_active is True

    body = _registration(executor_id)
    body["requested_mode"] = "LIVE"
    try:
        response = await client.post(
            "/api/v1/executors/register",
            json=body,
            headers=_auth_headers(executor_id),
        )
        assert response.status_code == 201, response.text
        assert response.json()["data"]["execution_mode"] == "SHADOW"
        assert response.json()["data"]["kill_switch_active"] is True

        rows = await postgres.fetchrow(
            """
            SELECT e.execution_mode, a.execution_mode::text AS agent_mode
            FROM executor_instances AS e
            JOIN ea_agents AS a ON a.id = e.executor_id
            WHERE e.executor_id = $1::uuid
            """,
            str(executor_id),
        )
        assert dict(rows) == {"execution_mode": "SHADOW", "agent_mode": "SHADOW"}
    finally:
        await _cleanup(postgres, executor_id)


@pytest.mark.asyncio
async def test_shadow_is_usable_while_kill_switch_is_engaged(
    client: AsyncClient,
    postgres: Any,
    registered: UUID,
) -> None:
    command = _shadow_command(registered)
    await _commands(postgres).enqueue_command(command)

    poll = await client.get(
        f"/api/v1/executors/{registered}/commands/next",
        headers=_auth_headers(registered),
    )
    assert poll.status_code == 200, poll.text
    assert poll.headers["X-Execution-Mode"] == "SHADOW"
    assert poll.headers["X-Kill-Switch-Active"] == "true"

    governance = await client.get(
        f"/api/v1/executors/{registered}/governance",
        headers=_auth_headers(registered),
    )
    assert governance.status_code == 200
    assert governance.json()["data"]["kill_switch_active"] is True


@pytest.mark.asyncio
async def test_demo_delivery_requires_explicit_disarm_and_live_stays_blocked(
    client: AsyncClient,
    postgres: Any,
    registered: UUID,
) -> None:
    governance = _governance(postgres)
    commands = _commands(postgres)
    promoted = await governance.transition_mode(
        registered,
        target_mode=ExecutorMode.DEMO,
        actor="integration:test",
        reason="prepare guarded demo",
        expected_mode=ExecutorMode.SHADOW,
        expected_version=1,
    )
    assert promoted.execution_mode == "DEMO"
    assert promoted.kill_switch_active is True

    row = await postgres.fetchrow(
        """
        SELECT e.execution_mode, e.mode_version, a.execution_mode::text AS agent_mode
        FROM executor_instances AS e
        JOIN ea_agents AS a ON a.id = e.executor_id
        WHERE e.executor_id = $1::uuid
        """,
        str(registered),
    )
    assert dict(row) == {"execution_mode": "DEMO", "mode_version": 2, "agent_mode": "DEMO"}

    demo = _demo_command(registered)
    with pytest.raises(CommandConflictError, match="kill switch"):
        await commands.enqueue_command(demo)
    with pytest.raises(ModeTransitionError, match="LIVE promotion"):
        await governance.transition_mode(
            registered,
            target_mode=ExecutorMode.LIVE,
            actor="integration:test",
            reason="must remain blocked",
        )

    global_state = await governance.global_snapshot()
    try:
        await governance.set_kill_switch(
            active=False,
            actor="integration:test",
            reason="bounded demo window",
            expected_version=global_state.governance_version,
        )
        await commands.enqueue_command(demo)
        poll = await client.get(
            f"/api/v1/executors/{registered}/commands/next",
            headers=_auth_headers(registered),
        )
        assert poll.status_code == 200, poll.text
        assert poll.headers["X-Execution-Mode"] == "DEMO"
        assert poll.headers["X-Kill-Switch-Active"] == "false"

        claim_token = await _claim(client, registered, demo)
        assert claim_token
        assert await _command_state(postgres, demo) == "CLAIMED"
        broker_terminal = await postgres.fetchrow(
            """
            SELECT count(*) AS count FROM execution_commands
            WHERE executor_id = $1::uuid
              AND state IN ('BROKER_ACCEPTED', 'ACTIVE', 'FILLED', 'COMPLETED')
            """,
            str(registered),
        )
        assert broker_terminal["count"] == 0
    finally:
        await governance.set_kill_switch(
            active=True,
            actor="integration:test",
            reason="close bounded demo window",
        )


@pytest.mark.asyncio
async def test_engaging_switch_expires_queued_demo_but_preserves_claimed_reporting(
    client: AsyncClient,
    postgres: Any,
    registered: UUID,
) -> None:
    governance = _governance(postgres)
    commands = _commands(postgres)
    await governance.transition_mode(
        registered,
        target_mode="DEMO",
        actor="integration:test",
        reason="prepare kill-switch drill",
    )
    await governance.set_kill_switch(
        active=False,
        actor="integration:test",
        reason="start kill-switch drill",
    )
    claimed = _demo_command(registered)
    queued = _demo_command(registered)
    await commands.enqueue_command(claimed)
    await commands.enqueue_command(queued)
    claim_token = await _claim(client, registered, claimed)

    engaged = await governance.set_kill_switch(
        active=True,
        actor="integration:test",
        reason="emergency stop drill",
    )
    assert engaged.kill_switch_active is True
    assert await _command_state(postgres, queued) == "EXPIRED"
    assert await _command_state(postgres, claimed) == "CLAIMED"

    blocked_poll = await client.get(
        f"/api/v1/executors/{registered}/commands/next",
        headers=_auth_headers(registered),
    )
    assert blocked_poll.status_code == 204
    assert blocked_poll.headers["X-Kill-Switch-Active"] == "true"

    report = await client.post(
        f"/api/v1/commands/{claimed.command_id}/reports",
        json=_report(
            command=claimed,
            executor_id=registered,
            state="PREFLIGHT_REJECTED",
            reason_code="KILL_SWITCH_ACTIVE",
        ),
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert report.status_code == 202, report.text
    assert await _command_state(postgres, claimed) == "REJECTED"

    audit = await postgres.fetchrow(
        """
        SELECT actor, reason, new_state
        FROM executor_governance_audit
        WHERE action = 'KILL_SWITCH_ENGAGED'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    assert audit["actor"] == "integration:test"
    assert audit["reason"] == "emergency stop drill"
    new_state = audit["new_state"]
    if isinstance(new_state, str):
        new_state = json.loads(new_state)
    assert new_state["queued_commands_expired"] == 1
    assert new_state["claimed_commands_outstanding"] == 1


@pytest.mark.asyncio
async def test_mode_transition_rejects_stale_writers_and_database_drift(
    postgres: Any,
    registered: UUID,
) -> None:
    governance = _governance(postgres)
    with pytest.raises(GovernanceConflictError, match="stale mode version"):
        await governance.transition_mode(
            registered,
            target_mode="SHADOW",
            actor="integration:test",
            reason="stale writer",
            expected_version=99,
        )

    await postgres.execute(
        "UPDATE ea_agents SET execution_mode = 'DEMO' WHERE id = $1::uuid",
        str(registered),
    )
    try:
        with pytest.raises(ModeTransitionError, match="mode drift"):
            await governance.transition_mode(
                registered,
                target_mode="SHADOW",
                actor="integration:test",
                reason="must detect drift",
            )
    finally:
        await postgres.execute(
            "UPDATE ea_agents SET execution_mode = 'SHADOW' WHERE id = $1::uuid",
            str(registered),
        )


@pytest.mark.asyncio
async def test_preexisting_live_mode_cannot_deliver_even_when_switch_is_disarmed(
    client: AsyncClient,
    postgres: Any,
    registered: UUID,
) -> None:
    governance = _governance(postgres)
    commands = _commands(postgres)
    await governance.transition_mode(
        registered,
        target_mode="DEMO",
        actor="integration:test",
        reason="prepare legacy live defense proof",
    )
    await governance.set_kill_switch(
        active=False,
        actor="integration:test",
        reason="prove live remains blocked after disarm",
    )
    demo = _demo_command(registered)
    await commands.enqueue_command(demo)
    await postgres.execute(
        """
        UPDATE execution_commands
        SET payload = jsonb_set(payload, '{executor_binding,execution_mode}', '"LIVE"'::jsonb)
        WHERE command_id = $1::uuid
        """,
        str(demo.command_id),
    )
    await postgres.execute(
        "UPDATE executor_instances SET execution_mode = 'LIVE' WHERE executor_id = $1::uuid",
        str(registered),
    )
    await postgres.execute(
        "UPDATE ea_agents SET execution_mode = 'LIVE' WHERE id = $1::uuid",
        str(registered),
    )
    try:
        with pytest.raises(CommandConflictError, match="LIVE command delivery"):
            await commands.enqueue_command(_command_in_mode(registered, ExecutorMode.LIVE))

        poll = await client.get(
            f"/api/v1/executors/{registered}/commands/next",
            headers=_auth_headers(registered),
        )
        assert poll.status_code == 204
        claim = await client.post(
            f"/api/v1/commands/{demo.command_id}/claim",
            json={"lease_seconds": 30},
            headers=_auth_headers(registered),
        )
        assert claim.status_code == 409
        assert await _command_state(postgres, demo) == "QUEUED"
    finally:
        await governance.set_kill_switch(
            active=True,
            actor="integration:test",
            reason="restore fail-closed default",
        )


@pytest.mark.asyncio
async def test_governance_audit_is_database_immutable(postgres: Any, registered: UUID) -> None:
    governance = _governance(postgres)
    await governance.transition_mode(
        registered,
        target_mode="SHADOW",
        actor="integration:test",
        reason="create immutable audit proof",
    )
    audit = await postgres.fetchrow(
        """
        SELECT audit_id FROM executor_governance_audit
        WHERE executor_id = $1::uuid
        ORDER BY created_at DESC LIMIT 1
        """,
        str(registered),
    )
    asyncpg = import_module("asyncpg")
    with pytest.raises(asyncpg.PostgresError) as raised:
        await postgres.execute(
            "UPDATE executor_governance_audit SET reason = 'tampered' WHERE audit_id = $1::uuid",
            str(audit["audit_id"]),
        )
    assert raised.value.sqlstate == "55000"
    assert "append-only" in str(raised.value)


@pytest.mark.asyncio
async def test_readiness_detects_a_disabled_immutability_trigger(postgres: Any) -> None:
    governance = _governance(postgres)
    await postgres.execute(
        "ALTER TABLE executor_governance_audit DISABLE TRIGGER trg_executor_governance_audit_immutable"
    )
    try:
        status = await governance.schema_status()
        assert status["ready"] is False
        assert status["immutable_audit_trigger"] is False
    finally:
        await postgres.execute(
            "ALTER TABLE executor_governance_audit ENABLE TRIGGER trg_executor_governance_audit_immutable"
        )
