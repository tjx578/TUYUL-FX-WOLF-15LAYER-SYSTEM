"""End-to-end proof of the MT5 executor bridge against real PostgreSQL.

``tests/test_executor_bridge_api.py`` covers the router in isolation: it
substitutes a ``FakeRepository`` and overrides ``verify_executor_auth``. That
proves the handlers wire up, and nothing about whether the thing works.

This module deliberately removes both substitutes and drives the full path:

    HTTP request
      -> executor auth middleware (real HMAC-derived token)
      -> FastAPI router
      -> MT5CommandRepository
      -> PostgreSQL (disposable, migrated)
      -> HTTP response

So the constraints, transactions, lease semantics and terminal-state rules are
exercised as deployed rather than as imagined. A fake repository cannot fail a
UNIQUE constraint, expire a lease, or refuse a conflicting terminal state.

Scope is transport only. Nothing here creates a risk reservation, a final
SignalJSON, a command producer, or a DEMO promotion, and every command stays
SHADOW: the only terminal outcomes reachable are WOULD_EXECUTE and
WOULD_REJECT.

Opt-in, like the lifecycle V2 suite: set
``WOLF15_RUN_POSTGRES_INTEGRATION=1`` with a disposable ``DATABASE_URL``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.executor_bridge_router import router
from api.middleware.executor_auth import derive_executor_token
from contracts.mt5_execution_protocol import (
    ExecutionCommandV1,
    SignedExecutionEnvelopeV2,
    canonical_json_bytes,
    derive_executor_command_verification_key,
    sha256_tag,
    sign_execution_command,
    verify_signed_execution_envelope,
)
from execution.mt5_command_repository import MT5CommandRepository, get_mt5_command_repository

pytestmark = [pytest.mark.integration]

_RUN_FLAG = "WOLF15_RUN_POSTGRES_INTEGRATION"

#: Distinct from the command signing secret on purpose: a bridge that reuses
#: one secret for authentication and signing collapses two trust boundaries.
AUTH_SECRET = "e2e-executor-bridge-auth-secret-value-0123456789"
SIGNING_SECRET = "e2e-executor-command-signing-secret-value-9876543210"
SIGNING_KEY_ID = "e2e-primary"

ACCOUNT_ID = "acct-e2e-01"
LOGIN_HASH = "sha256:" + "a" * 64
BROKER_SERVER = "Broker-Demo-E2E"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


class _PoolBackedPostgres:
    """Production-like pool semantics over a disposable database."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    @property
    def is_available(self) -> bool:
        return True

    async def execute(self, query: str, *args: Any) -> str:
        async with self._pool.acquire() as connection:
            return str(await connection.execute(query, *args))

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        async with self._pool.acquire() as connection:
            return list(await connection.fetch(query, *args))

    async def fetchrow(self, query: str, *args: Any) -> Any | None:
        async with self._pool.acquire() as connection:
            return await connection.fetchrow(query, *args)

    async def execute_in_transaction(
        self,
        operations: list[tuple[str, tuple[Any, ...]]],
    ) -> list[str]:
        results: list[str] = []
        async with self._pool.acquire() as connection, connection.transaction():
            for query, args in operations:
                result = await connection.execute(query, *args)
                results.append(str(result))
        return results

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        async with self._pool.acquire() as connection, connection.transaction():
            yield connection


def _canonical_governance_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _governance_snapshot(row: Any) -> dict[str, Any]:
    if row is None:
        raise RuntimeError("executor_bridge_governance singleton is missing")
    return {str(key): value for key, value in dict(row).items()}


def _governance_fingerprint(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(
        {key: _canonical_governance_value(value) for key, value in snapshot.items()},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _assert_governance_restored_exactly(
    baseline: dict[str, Any],
    restored: dict[str, Any],
) -> None:
    if restored != baseline:
        changed = {
            key: {"baseline": baseline.get(key), "restored": restored.get(key)}
            for key in sorted(set(baseline) | set(restored))
            if baseline.get(key) != restored.get(key)
        }
        raise RuntimeError(f"executor_bridge_governance exact restoration failed: {changed}")
    if _governance_fingerprint(restored) != _governance_fingerprint(baseline):
        raise RuntimeError("executor_bridge_governance fingerprint restoration failed")


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


async def _restore_governance_exactly(connection: Any, baseline: dict[str, Any]) -> dict[str, Any]:
    primary_key = "singleton_id"
    if primary_key not in baseline:
        raise RuntimeError("executor_bridge_governance snapshot is missing singleton_id")
    mutable_columns = tuple(column for column in baseline if column != primary_key)
    if not mutable_columns:
        raise RuntimeError("executor_bridge_governance snapshot has no restorable columns")
    assignments = ", ".join(
        f"{_quoted_identifier(column)} = ${index}" for index, column in enumerate(mutable_columns, start=1)
    )
    primary_key_position = len(mutable_columns) + 1
    values = tuple(baseline[column] for column in mutable_columns) + (baseline[primary_key],)
    async with connection.transaction():
        await connection.execute(
            f"UPDATE executor_bridge_governance SET {assignments} "
            f"WHERE {_quoted_identifier(primary_key)} = ${primary_key_position}",
            *values,
        )
        restored = _governance_snapshot(
            await connection.fetchrow(
                "SELECT * FROM executor_bridge_governance WHERE singleton_id = $1 FOR UPDATE",
                baseline[primary_key],
            )
        )
        _assert_governance_restored_exactly(baseline, restored)
        return restored


@pytest_asyncio.fixture
async def postgres() -> AsyncIterator[_PoolBackedPostgres]:
    if os.getenv(_RUN_FLAG) != "1":
        pytest.skip(f"set {_RUN_FLAG}=1 to use a disposable PostgreSQL database")
    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        pytest.fail(f"{_RUN_FLAG}=1 requires DATABASE_URL")
    try:
        asyncpg = import_module("asyncpg")
    except ModuleNotFoundError:
        pytest.fail(f"{_RUN_FLAG}=1 requires the asyncpg dependency")

    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4, command_timeout=10)
    baseline_connection = await pool.acquire()
    try:
        governance_baseline = _governance_snapshot(
            await baseline_connection.fetchrow("SELECT * FROM executor_bridge_governance WHERE singleton_id = 1")
        )
        await pool.release(baseline_connection)
        baseline_connection = None
        try:
            yield _PoolBackedPostgres(pool)
        finally:
            restoration_connection = await pool.acquire()
            try:
                await _restore_governance_exactly(restoration_connection, governance_baseline)
            finally:
                await pool.release(restoration_connection)
    finally:
        if baseline_connection is not None:
            await pool.release(baseline_connection)
        await pool.close()


@pytest_asyncio.fixture
async def executor_id(postgres: _PoolBackedPostgres) -> AsyncIterator[UUID]:
    value = uuid4()
    await postgres.execute(
        """
        INSERT INTO ea_agents (
            id,
            agent_name,
            ea_class,
            ea_subtype,
            execution_mode,
            reporter_mode,
            status,
            locked
        ) VALUES (
            $1::uuid,
            $2,
            'PRIMARY',
            'EDUMB',
            'SHADOW',
            'FULL',
            'OFFLINE',
            false
        )
        """,
        str(value),
        f"MT5 Bridge E2E {value}",
    )
    try:
        yield value
    finally:
        await _cleanup(postgres, value)
        await postgres.execute("DELETE FROM ea_agents WHERE id = $1::uuid", str(value))


@pytest_asyncio.fixture
async def client(
    postgres: _PoolBackedPostgres,
    executor_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    """A client that authenticates for real and persists for real.

    Only the database handle is injected. Authentication is *not* overridden --
    every request below carries a token the middleware actually verifies.
    """
    monkeypatch.setenv("EXECUTOR_BRIDGE_AUTH_SECRET", AUTH_SECRET)
    monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_SECRET", SIGNING_SECRET)
    monkeypatch.delenv("EXECUTOR_BRIDGE_AUTH_SECRET_PREVIOUS", raising=False)
    monkeypatch.delenv("EXECUTOR_COMMAND_SIGNING_SECRET_PREVIOUS", raising=False)

    repository = MT5CommandRepository(pg=postgres)  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_mt5_command_repository] = lambda: repository
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client


def _auth_headers(executor_id: UUID, *, token: str | None = None) -> dict[str, str]:
    resolved = token if token is not None else derive_executor_token(str(executor_id), secret=AUTH_SECRET)
    return {
        "Authorization": f"Bearer {resolved}",
        "X-Executor-Id": str(executor_id),
    }


# --------------------------------------------------------------------------
# payload builders
# --------------------------------------------------------------------------


def _registration(executor_id: UUID) -> dict[str, Any]:
    return {
        "executor_id": str(executor_id),
        "account_id": ACCOUNT_ID,
        "login_hash": LOGIN_HASH,
        "broker_server": BROKER_SERVER,
        "terminal_build": 4500,
        "ea_version": "1.0.0-e2e",
    }


def _snapshot(executor_id: UUID, *, captured_at: datetime | None = None) -> dict[str, Any]:
    moment = captured_at or datetime.now(UTC)
    return {
        "snapshot_id": f"snap-{uuid4().hex}",
        "captured_at_utc": moment.isoformat(),
        "executor_id": str(executor_id),
        "account_id": ACCOUNT_ID,
        "currency": "USD",
        "balance": 1000,
        "equity": 1000,
        "floating_pnl": 0,
        "used_margin": 0,
        "free_margin": 1000,
        "margin_mode": "HEDGING",
        "trade_allowed": True,
        "autotrading_enabled": True,
    }


def _heartbeat(executor_id: UUID, *, captured_at: datetime | None = None) -> dict[str, Any]:
    return {
        "executor_id": str(executor_id),
        "sent_at_utc": datetime.now(UTC).isoformat(),
        "terminal_connected": True,
        "trade_allowed": True,
        "autotrading_enabled": True,
        "account_snapshot": _snapshot(executor_id, captured_at=captured_at),
    }


def _shadow_command(executor_id: UUID, *, command_id: UUID | None = None) -> ExecutionCommandV1:
    """A signed SHADOW command. Never DEMO, never LIVE."""
    now = datetime.now(UTC)
    payload = {
        "command_id": command_id or uuid4(),
        "idempotency_key": f"{ACCOUNT_ID}:campaign-e2e:block-e2e:1:PLACE_PENDING:{uuid4().hex[:8]}",
        "revision": 1,
        "issued_at_utc": now,
        "not_before_utc": now,
        "expires_at_utc": now + timedelta(minutes=30),
        "executor_binding": {
            "executor_id": executor_id,
            "account_id": ACCOUNT_ID,
            "login_hash": LOGIN_HASH,
            "broker_server": BROKER_SERVER,
            "execution_mode": "SHADOW",
        },
        "source": {
            "source_event": "signal_json",
            "source_schema_version": "2.0",
            "source_signal_id": f"signal-{uuid4().hex[:8]}",
            "source_signal_hash": "sha256:" + "b" * 64,
            "campaign_id": "campaign-e2e",
            "block_id": "block-e2e",
            "block_role": "PARENT",
            "lifecycle_anchor": "lifecycle-e2e",
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
            "comment_tag": "W15:E2E0123456",
            "time_in_force": "SPECIFIED",
            "broker_expiration_utc": now + timedelta(minutes=30),
        },
        "guards": {
            "max_spread_points": 25,
            "max_price_drift_points": 15,
            "expected_margin_mode": "HEDGING",
            "risk_snapshot_id": "snapshot-e2e",
            # Transport-level placeholder. PR C introduces real reservations;
            # this proves nothing about risk authority.
            "risk_reservation_id": "reservation-e2e",
            "balance_snapshot": 1000,
            "equity_snapshot": 1000,
        },
    }
    return sign_execution_command(payload, secret=SIGNING_SECRET, key_id=SIGNING_KEY_ID)


def _report(
    *,
    command: ExecutionCommandV1,
    executor_id: UUID,
    state: str,
    sequence: int = 1,
    report_id: UUID | None = None,
    reason_code: str = "SHADOW_OK",
) -> dict[str, Any]:
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
        "reason_code": reason_code,
    }


async def _cleanup(postgres: _PoolBackedPostgres, executor_id: UUID) -> None:
    canary_table = await postgres.fetchrow("SELECT to_regclass('public.engineering_demo_canary_windows') AS name")
    if canary_table and canary_table["name"] is not None:
        await postgres.execute(
            "DELETE FROM engineering_demo_canary_windows WHERE executor_id = $1::uuid",
            str(executor_id),
        )
    await postgres.execute(
        "DELETE FROM broker_entities WHERE command_id IN "
        "(SELECT command_id FROM execution_commands WHERE executor_id = $1::uuid)",
        str(executor_id),
    )
    await postgres.execute(
        "DELETE FROM execution_reports WHERE command_id IN "
        "(SELECT command_id FROM execution_commands WHERE executor_id = $1::uuid)",
        str(executor_id),
    )
    await postgres.execute("DELETE FROM execution_commands WHERE executor_id = $1::uuid", str(executor_id))
    await postgres.execute("DELETE FROM executor_account_snapshots WHERE executor_id = $1::uuid", str(executor_id))
    await postgres.execute("DELETE FROM executor_instances WHERE executor_id = $1::uuid", str(executor_id))


@pytest_asyncio.fixture
async def registered(
    client: AsyncClient,
    postgres: _PoolBackedPostgres,
    executor_id: UUID,
) -> AsyncIterator[UUID]:
    """A SHADOW executor that exists in the database, cleaned up afterwards."""
    response = await client.post(
        "/api/v1/executors/register",
        json=_registration(executor_id),
        headers=_auth_headers(executor_id),
    )
    assert response.status_code == 201, response.text
    try:
        yield executor_id
    finally:
        await _cleanup(postgres, executor_id)


def _repo(postgres: _PoolBackedPostgres) -> MT5CommandRepository:
    return MT5CommandRepository(pg=postgres)  # type: ignore[arg-type]


async def _claim(client: AsyncClient, executor_id: UUID, command: ExecutionCommandV1) -> str:
    response = await client.post(
        f"/api/v1/commands/{command.command_id}/claim",
        json={"lease_seconds": 60},
        headers=_auth_headers(executor_id),
    )
    assert response.status_code == 200, response.text
    return str(response.json()["data"]["claim_token"])


async def _command_state(postgres: _PoolBackedPostgres, command: ExecutionCommandV1) -> str:
    row = await postgres.fetchrow(
        "SELECT state FROM execution_commands WHERE command_id = $1::uuid",
        str(command.command_id),
    )
    assert row is not None
    return str(row["state"])


# --------------------------------------------------------------------------
# registration, heartbeat, durable snapshot
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registration_persists_a_shadow_executor(
    client: AsyncClient, postgres: _PoolBackedPostgres, executor_id: UUID
) -> None:
    """Registration must create a SHADOW executor and never a privileged one."""
    try:
        response = await client.post(
            "/api/v1/executors/register",
            json=_registration(executor_id),
            headers=_auth_headers(executor_id),
        )
        assert response.status_code == 201, response.text
        assert response.json()["data"]["execution_mode"] == "SHADOW"

        row = await postgres.fetchrow(
            "SELECT account_id, execution_mode, revoked_at FROM executor_instances WHERE executor_id = $1::uuid",
            str(executor_id),
        )
        assert row is not None
        assert row["account_id"] == ACCOUNT_ID
        # Registration is not a privilege-escalation path.
        assert row["execution_mode"] == "SHADOW"
        assert row["revoked_at"] is None
    finally:
        await _cleanup(postgres, executor_id)


@pytest.mark.asyncio
async def test_registration_is_idempotent(client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID) -> None:
    second = await client.post(
        "/api/v1/executors/register",
        json=_registration(registered),
        headers=_auth_headers(registered),
    )

    assert second.status_code == 201, second.text
    count = await postgres.fetchrow(
        "SELECT count(*) AS n FROM executor_instances WHERE executor_id = $1::uuid", str(registered)
    )
    assert count["n"] == 1


@pytest.mark.asyncio
async def test_heartbeat_persists_a_durable_account_snapshot(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    response = await client.post(
        f"/api/v1/executors/{registered}/heartbeat",
        json=_heartbeat(registered),
        headers=_auth_headers(registered),
    )

    assert response.status_code == 200, response.text
    row = await postgres.fetchrow(
        "SELECT account_id, balance, trade_allowed FROM executor_account_snapshots "
        "WHERE executor_id = $1::uuid ORDER BY received_at DESC LIMIT 1",
        str(registered),
    )
    assert row is not None
    assert row["account_id"] == ACCOUNT_ID
    assert float(row["balance"]) == 1000.0
    assert row["trade_allowed"] is True

    executor = await postgres.fetchrow(
        "SELECT last_heartbeat_at FROM executor_instances WHERE executor_id = $1::uuid", str(registered)
    )
    assert executor["last_heartbeat_at"] is not None


@pytest.mark.asyncio
async def test_heartbeat_body_must_match_the_path(client: AsyncClient, registered: UUID) -> None:
    body = _heartbeat(registered)
    body["executor_id"] = str(uuid4())

    response = await client.post(
        f"/api/v1/executors/{registered}/heartbeat",
        json=body,
        headers=_auth_headers(registered),
    )

    assert response.status_code in {403, 422}


# --------------------------------------------------------------------------
# polling
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_poll_returns_204(client: AsyncClient, registered: UUID) -> None:
    response = await client.get(
        f"/api/v1/executors/{registered}/commands/next",
        headers=_auth_headers(registered),
    )

    assert response.status_code == 204
    assert response.headers.get("Cache-Control") == "no-store"


@pytest.mark.asyncio
async def test_queued_command_is_returned_by_poll(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)

    response = await client.get(
        f"/api/v1/executors/{registered}/commands/next",
        headers=_auth_headers(registered),
    )

    assert response.status_code == 200, response.text
    returned = response.json()["data"]["command"]
    assert returned["command_id"] == str(command.command_id)
    # The EA receives a signed ExecutionCommand, never pressure telemetry.
    assert returned["executor_binding"]["execution_mode"] == "SHADOW"
    assert returned["signature"]["key_id"] == SIGNING_KEY_ID


@pytest.mark.asyncio
async def test_signed_wire_bytes_are_frozen_in_postgres_and_delivered_unchanged(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)

    response = await client.get(
        f"/api/v1/executors/{registered}/commands/next",
        headers=_auth_headers(registered),
    )
    assert response.status_code == 200, response.text
    envelope = SignedExecutionEnvelopeV2.model_validate(response.json()["data"]["signed_envelope"])
    verification_key = derive_executor_command_verification_key(
        registered,
        root_secret=SIGNING_SECRET,
    )
    assert verify_signed_execution_envelope(envelope, verification_key=verification_key) == command

    row = await postgres.fetchrow(
        """
        SELECT wire_format, payload_encoding, signed_payload_b64,
               signed_payload_sha256, signature_algorithm,
               signature_key_id, signature_value
        FROM execution_commands
        WHERE command_id = $1::uuid
        """,
        str(command.command_id),
    )
    assert row is not None
    assert dict(row) == {
        "wire_format": envelope.wire_version,
        "payload_encoding": envelope.payload_encoding,
        "signed_payload_b64": envelope.payload_b64,
        "signed_payload_sha256": envelope.payload_sha256,
        "signature_algorithm": envelope.algorithm,
        "signature_key_id": envelope.key_id,
        "signature_value": envelope.signature,
    }
    decoded = base64.urlsafe_b64decode(envelope.payload_b64 + "=" * (-len(envelope.payload_b64) % 4))
    assert decoded == canonical_json_bytes(command.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_postgres_rejects_an_incomplete_signed_wire_row(postgres: _PoolBackedPostgres, registered: UUID) -> None:
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    asyncpg = import_module("asyncpg")

    with pytest.raises(asyncpg.CheckViolationError) as raised:
        await postgres.execute(
            "UPDATE execution_commands SET signature_value = NULL WHERE command_id = $1::uuid",
            str(command.command_id),
        )

    assert raised.value.constraint_name == "ck_execution_command_signed_wire_complete"


@pytest.mark.asyncio
async def test_postgres_rejects_a_new_command_explicitly_downgraded_to_legacy_wire(
    postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    asyncpg = import_module("asyncpg")

    with pytest.raises(asyncpg.CheckViolationError) as raised:
        await postgres.execute(
            """
            INSERT INTO execution_commands (
                command_id, executor_id, account_id, source_signal_id,
                source_signal_hash, idempotency_key, revision, action,
                payload, payload_hash, state, issued_at, not_before,
                expires_at, wire_format
            )
            SELECT $2::uuid, executor_id, account_id, source_signal_id,
                   source_signal_hash, idempotency_key || ':legacy', revision,
                   action, payload, payload_hash, state, issued_at, not_before,
                   expires_at, 'legacy-json-v1'
            FROM execution_commands
            WHERE command_id = $1::uuid
            """,
            str(command.command_id),
            str(uuid4()),
        )

    assert raised.value.constraint_name == "ck_execution_command_signed_wire_new_rows"


@pytest.mark.asyncio
async def test_signed_wire_readiness_fails_when_the_constraint_is_missing(
    postgres: _PoolBackedPostgres,
) -> None:
    repository = _repo(postgres)
    assert (await repository.signed_wire_schema_status())["ready"] is True
    original = await postgres.fetchrow(
        """
        SELECT pg_get_constraintdef(oid) AS definition
        FROM pg_constraint
        WHERE conname = 'ck_execution_command_signed_wire_complete'
          AND conrelid = 'execution_commands'::regclass
        """
    )
    assert original is not None
    await postgres.execute("ALTER TABLE execution_commands DROP CONSTRAINT ck_execution_command_signed_wire_complete")
    try:
        status = await repository.signed_wire_schema_status()
        assert status["ready"] is False
        assert status["signed_wire_constraint"] is False
    finally:
        await postgres.execute(
            "ALTER TABLE execution_commands "
            "ADD CONSTRAINT ck_execution_command_signed_wire_complete " + str(original["definition"])
        )


@pytest.mark.asyncio
async def test_signed_wire_readiness_rejects_a_weak_constraint_with_the_right_name(
    postgres: _PoolBackedPostgres,
) -> None:
    repository = _repo(postgres)
    original = await postgres.fetchrow(
        """
        SELECT pg_get_constraintdef(oid) AS definition
        FROM pg_constraint
        WHERE conname = 'ck_execution_command_signed_wire_complete'
          AND conrelid = 'execution_commands'::regclass
        """
    )
    assert original is not None
    await postgres.execute("ALTER TABLE execution_commands DROP CONSTRAINT ck_execution_command_signed_wire_complete")
    await postgres.execute(
        "ALTER TABLE execution_commands "
        "ADD CONSTRAINT ck_execution_command_signed_wire_complete CHECK (wire_format IS NOT NULL)"
    )
    try:
        status = await repository.signed_wire_schema_status()
        assert status["ready"] is False
        assert status["signed_wire_constraint"] is False
    finally:
        await postgres.execute(
            "ALTER TABLE execution_commands DROP CONSTRAINT ck_execution_command_signed_wire_complete"
        )
        await postgres.execute(
            "ALTER TABLE execution_commands "
            "ADD CONSTRAINT ck_execution_command_signed_wire_complete " + str(original["definition"])
        )


@pytest.mark.asyncio
async def test_signed_wire_readiness_fails_when_the_legacy_insert_guard_is_missing(
    postgres: _PoolBackedPostgres,
) -> None:
    repository = _repo(postgres)
    original = await postgres.fetchrow(
        """
        SELECT pg_get_triggerdef(oid) AS definition
        FROM pg_trigger
        WHERE tgname = 'trg_execution_command_require_signed_wire'
          AND tgrelid = 'execution_commands'::regclass
        """
    )
    assert original is not None
    await postgres.execute("DROP TRIGGER trg_execution_command_require_signed_wire ON execution_commands")
    try:
        status = await repository.signed_wire_schema_status()
        assert status["ready"] is False
        assert status["legacy_insert_guard"] is False
    finally:
        await postgres.execute(str(original["definition"]))


# --------------------------------------------------------------------------
# claim and lease
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_binds_a_lease_and_request_hash(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)

    response = await client.post(
        f"/api/v1/commands/{command.command_id}/claim",
        json={"lease_seconds": 30},
        headers=_auth_headers(registered),
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["claim_token"]
    assert data["request_hash"] == sha256_tag(command.model_dump(mode="json"))

    row = await postgres.fetchrow(
        "SELECT state, claim_token_hash, lease_expires_at FROM execution_commands WHERE command_id = $1::uuid",
        str(command.command_id),
    )
    assert row["state"] == "CLAIMED"
    assert row["claim_token_hash"]
    assert row["lease_expires_at"] is not None


@pytest.mark.asyncio
async def test_claimed_command_is_not_offered_to_the_next_poll(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    """A live lease must not hand the same work to a second poller."""
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    await _claim(client, registered, command)

    response = await client.get(
        f"/api/v1/executors/{registered}/commands/next",
        headers=_auth_headers(registered),
    )

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_expired_lease_makes_the_command_reclaimable(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    """Reclaim after expiry, so a crashed executor cannot strand work."""
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    await _claim(client, registered, command)
    # Expire the lease in the database rather than sleeping through it.
    await postgres.execute(
        "UPDATE execution_commands SET lease_expires_at = now() - interval '1 minute' WHERE command_id = $1::uuid",
        str(command.command_id),
    )

    response = await client.get(
        f"/api/v1/executors/{registered}/commands/next",
        headers=_auth_headers(registered),
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["command"]["command_id"] == str(command.command_id)


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_terminal_report_is_persisted(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    claim_token = await _claim(client, registered, command)

    response = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(command=command, executor_id=registered, state="WOULD_EXECUTE"),
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )

    assert response.status_code == 202, response.text
    # SHADOW terminals only. No FILLED, no broker side effect.
    assert await _command_state(postgres, command) == "SHADOW_COMPLETED"


@pytest.mark.asyncio
async def test_terminal_command_can_be_reconciled_without_a_claim_token(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    claim_token = await _claim(client, registered, command)
    report = _report(command=command, executor_id=registered, state="WOULD_EXECUTE")
    accepted = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=report,
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )
    assert accepted.status_code == 202, accepted.text

    response = await client.get(
        f"/api/v1/executors/{registered}/commands/{command.command_id}/status",
        headers=_auth_headers(registered),
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["command_state"] == "SHADOW_COMPLETED"
    assert data["terminal"] is True
    assert data["request_hash"] == report["request_hash"]
    assert data["latest_report"]["report_id"] == report["report_id"]
    assert data["latest_report"]["request_hash"] == report["request_hash"]
    assert "claim_token" not in response.text


@pytest.mark.asyncio
async def test_command_status_does_not_disclose_an_unknown_command(client: AsyncClient, registered: UUID) -> None:
    response = await client.get(
        f"/api/v1/executors/{registered}/commands/{uuid4()}/status",
        headers=_auth_headers(registered),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_would_reject_is_also_terminal(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    claim_token = await _claim(client, registered, command)

    response = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(
            command=command,
            executor_id=registered,
            state="WOULD_REJECT",
            reason_code="SHADOW_GUARD_FAILED",
        ),
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )

    assert response.status_code == 202, response.text
    assert await _command_state(postgres, command) == "SHADOW_REJECTED"


@pytest.mark.asyncio
async def test_identical_duplicate_report_is_idempotent(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    """At-least-once delivery must not produce a second logical effect."""
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    claim_token = await _claim(client, registered, command)
    body = _report(command=command, executor_id=registered, state="WOULD_EXECUTE")
    headers = {**_auth_headers(registered), "X-Claim-Token": claim_token}

    first = await client.post(f"/api/v1/commands/{command.command_id}/reports", json=body, headers=headers)
    second = await client.post(f"/api/v1/commands/{command.command_id}/reports", json=body, headers=headers)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    count = await postgres.fetchrow(
        "SELECT count(*) AS n FROM execution_reports WHERE command_id = $1::uuid", str(command.command_id)
    )
    assert count["n"] == 1


@pytest.mark.asyncio
async def test_conflicting_report_on_the_same_sequence_is_rejected(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    """A contradicting report must not overwrite recorded history."""
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    claim_token = await _claim(client, registered, command)
    headers = {**_auth_headers(registered), "X-Claim-Token": claim_token}

    accepted = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(command=command, executor_id=registered, state="WOULD_EXECUTE"),
        headers=headers,
    )
    assert accepted.status_code == 202, accepted.text

    conflicting = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(
            command=command,
            executor_id=registered,
            state="WOULD_REJECT",
            reason_code="SHADOW_GUARD_FAILED",
        ),
        headers=headers,
    )

    assert conflicting.status_code == 409, conflicting.text
    assert await _command_state(postgres, command) == "SHADOW_COMPLETED"


@pytest.mark.asyncio
async def test_terminal_state_is_immutable(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    claim_token = await _claim(client, registered, command)
    headers = {**_auth_headers(registered), "X-Claim-Token": claim_token}
    await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(command=command, executor_id=registered, state="WOULD_EXECUTE"),
        headers=headers,
    )

    later = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(command=command, executor_id=registered, state="WOULD_REJECT", sequence=2),
        headers=headers,
    )

    assert later.status_code == 409, later.text
    assert await _command_state(postgres, command) == "SHADOW_COMPLETED"


@pytest.mark.asyncio
async def test_report_without_a_valid_claim_token_is_refused(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    await _claim(client, registered, command)

    response = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(command=command, executor_id=registered, state="WOULD_EXECUTE"),
        headers={**_auth_headers(registered), "X-Claim-Token": "not-the-real-token"},
    )

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_report_with_a_mismatched_request_hash_is_refused(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    """The report must be about the command the bridge actually issued."""
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    claim_token = await _claim(client, registered, command)
    body = _report(command=command, executor_id=registered, state="WOULD_EXECUTE")
    body["request_hash"] = "sha256:" + "f" * 64

    response = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=body,
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )

    assert response.status_code == 409, response.text


# --------------------------------------------------------------------------
# authentication and binding
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_credentials_are_refused(client: AsyncClient, registered: UUID) -> None:
    response = await client.get(f"/api/v1/executors/{registered}/commands/next")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wrong_token_is_refused(client: AsyncClient, registered: UUID) -> None:
    response = await client.get(
        f"/api/v1/executors/{registered}/commands/next",
        headers=_auth_headers(registered, token="not-a-valid-token"),
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_token_derived_for_another_executor_is_refused(client: AsyncClient, registered: UUID) -> None:
    """A valid token still only speaks for the executor it was derived for."""
    other = uuid4()
    response = await client.get(
        f"/api/v1/executors/{registered}/commands/next",
        headers={
            "Authorization": f"Bearer {derive_executor_token(str(other), secret=AUTH_SECRET)}",
            "X-Executor-Id": str(registered),
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_credential_cannot_reach_another_executors_resource(client: AsyncClient, registered: UUID) -> None:
    other = uuid4()
    response = await client.get(
        f"/api/v1/executors/{other}/commands/next",
        headers=_auth_headers(registered),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_another_executor_cannot_claim_this_command(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    intruder = uuid4()

    response = await client.post(
        f"/api/v1/commands/{command.command_id}/claim",
        json={"lease_seconds": 30},
        headers=_auth_headers(intruder),
    )

    assert response.status_code in {403, 404}
    assert await _command_state(postgres, command) == "QUEUED"


@pytest.mark.asyncio
async def test_report_for_a_mismatched_account_is_refused(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    claim_token = await _claim(client, registered, command)
    body = _report(command=command, executor_id=registered, state="WOULD_EXECUTE")
    body["account_id"] = "acct-someone-else"

    response = await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=body,
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_revoked_executor_cannot_receive_commands(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    """Revocation is enforced by the query, not by a caller remembering to check."""
    await _repo(postgres).enqueue_command(_shadow_command(registered))
    await postgres.execute(
        "UPDATE executor_instances SET revoked_at = now() WHERE executor_id = $1::uuid",
        str(registered),
    )

    response = await client.get(
        f"/api/v1/executors/{registered}/commands/next",
        headers=_auth_headers(registered),
    )

    assert response.status_code != 200, "a revoked executor received a command"


# --------------------------------------------------------------------------
# scope guard
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nothing_here_leaves_shadow_mode(
    client: AsyncClient, postgres: _PoolBackedPostgres, registered: UUID
) -> None:
    """PR B1 proves transport only: no DEMO, no LIVE, no broker terminal."""
    command = _shadow_command(registered)
    await _repo(postgres).enqueue_command(command)
    claim_token = await _claim(client, registered, command)
    await client.post(
        f"/api/v1/commands/{command.command_id}/reports",
        json=_report(command=command, executor_id=registered, state="WOULD_EXECUTE"),
        headers={**_auth_headers(registered), "X-Claim-Token": claim_token},
    )

    modes = await postgres.fetch(
        "SELECT DISTINCT execution_mode FROM executor_instances WHERE executor_id = $1::uuid",
        str(registered),
    )
    assert {row["execution_mode"] for row in modes} == {"SHADOW"}

    states = await postgres.fetch(
        "SELECT DISTINCT state FROM execution_commands WHERE executor_id = $1::uuid", str(registered)
    )
    broker_terminals = {"FILLED", "BROKER_ACCEPTED", "ACTIVE", "COMPLETED"}
    assert not ({row["state"] for row in states} & broker_terminals)
