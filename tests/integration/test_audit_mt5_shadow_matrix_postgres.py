"""Prove the read-only SHADOW matrix auditor against disposable PostgreSQL."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from contracts.mt5_execution_protocol import (
    PROTOCOL_VERSION,
    SIGNED_WIRE_VERSION,
    AccountSnapshotV1,
    ExecutorHeartbeatV1,
    ExecutorMode,
    ExecutorRegistrationV1,
    MarginMode,
    SymbolCapability,
    canonical_json_bytes,
    sha256_tag,
)
from execution.mt5_command_repository import MT5CommandRepository
from scripts.audit_mt5_shadow_matrix import (
    EXPECTED_EA_VERSION,
    MANIFEST_VERSION,
    REQUIRED_UNIVERSE,
    ManifestCommand,
    MatrixAbortError,
    MatrixManifest,
    audit_manifest,
    load_symbol_universe,
)
from tests.integration.postgres_test_guard import (
    require_destructive_postgres_opt_in,
    require_disposable_postgres_target,
    verify_connected_database,
    verify_operational_tables_empty,
)

pytestmark = [pytest.mark.integration]

_RUN_FLAG = "WOLF15_RUN_POSTGRES_INTEGRATION"
_DATABASE_GUARD = "WOLF15_POSTGRES_TEST_DATABASE"
_DESTRUCTIVE_FLAG = "WOLF15_ALLOW_DESTRUCTIVE_PG_TESTS"
_LOCK_KEY = 0x5701_1504
_LOCK_TIMEOUT_SECONDS = 120
ACCOUNT_ID = "acct-matrix-audit"
LOGIN_HASH = "sha256:" + "b" * 64
BROKER_SERVER = "XMGlobal-MT5 10"


class _PoolBackedPostgres:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    @property
    def is_available(self) -> bool:
        return True

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def execute(self, query: str, *args: Any) -> str:
        async with self._pool.acquire() as connection:
            return str(await connection.execute(query, *args))

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        async with self._pool.acquire() as connection:
            return list(await connection.fetch(query, *args))

    async def fetchrow(self, query: str, *args: Any) -> Any | None:
        async with self._pool.acquire() as connection:
            return await connection.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        async with self._pool.acquire() as connection:
            return await connection.fetchval(query, *args)

    async def execute_in_transaction(self, operations: list[tuple[str, tuple[Any, ...]]]) -> list[str]:
        results: list[str] = []
        async with self._pool.acquire() as connection, connection.transaction():
            for query, args in operations:
                results.append(str(await connection.execute(query, *args)))
        return results

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        async with self._pool.acquire() as connection, connection.transaction():
            yield connection


@pytest_asyncio.fixture
async def postgres() -> AsyncIterator[_PoolBackedPostgres]:
    if os.getenv(_RUN_FLAG) != "1":
        pytest.skip(f"set {_RUN_FLAG}=1 for disposable PostgreSQL integration tests")
    try:
        require_destructive_postgres_opt_in(os.getenv(_DESTRUCTIVE_FLAG, ""))
    except ValueError as exc:
        pytest.fail(str(exc))
    dsn = os.getenv("DATABASE_URL", "")
    expected_database = os.getenv(_DATABASE_GUARD, "")
    if not dsn or not expected_database:
        pytest.fail(f"{_RUN_FLAG}=1 requires DATABASE_URL and {_DATABASE_GUARD}")
    try:
        require_disposable_postgres_target(dsn, expected_database=expected_database)
    except ValueError as exc:
        pytest.fail(str(exc))
    try:
        asyncpg = import_module("asyncpg")
    except ModuleNotFoundError:
        pytest.fail(f"{_RUN_FLAG}=1 requires asyncpg")

    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4, command_timeout=10)
    lock_connection = await pool.acquire()
    lock_acquired = False
    try:
        await verify_connected_database(lock_connection, expected_database=expected_database)
        deadline = asyncio.get_running_loop().time() + _LOCK_TIMEOUT_SECONDS
        while not await lock_connection.fetchval("SELECT pg_try_advisory_lock($1)", _LOCK_KEY):
            if asyncio.get_running_loop().time() >= deadline:
                pytest.fail("timed out waiting for the matrix-audit PostgreSQL lock")
            await asyncio.sleep(0.25)
        lock_acquired = True
        await verify_operational_tables_empty(lock_connection)
        original = await lock_connection.fetchrow(
            """
            SELECT kill_switch_active, kill_switch_reason, governance_version, updated_by, updated_at
            FROM executor_bridge_governance
            WHERE singleton_id = 1
            """
        )
        if original is None:
            pytest.fail("executor_bridge_governance singleton is missing")
        try:
            yield _PoolBackedPostgres(pool)
        finally:
            await lock_connection.execute(
                """
                UPDATE executor_bridge_governance
                SET kill_switch_active = $1,
                    kill_switch_reason = $2,
                    governance_version = $3,
                    updated_by = $4,
                    updated_at = $5
                WHERE singleton_id = 1
                """,
                original["kill_switch_active"],
                original["kill_switch_reason"],
                original["governance_version"],
                original["updated_by"],
                original["updated_at"],
            )
            restored = await lock_connection.fetchrow(
                """
                SELECT kill_switch_active, kill_switch_reason, governance_version, updated_by, updated_at
                FROM executor_bridge_governance
                WHERE singleton_id = 1
                """
            )
            if restored is None or dict(restored) != dict(original):
                pytest.fail("executor_bridge_governance was not restored exactly")
            await verify_operational_tables_empty(lock_connection)
    finally:
        if lock_acquired:
            await lock_connection.execute("SELECT pg_advisory_unlock($1)", _LOCK_KEY)
        await pool.release(lock_connection)
        await pool.close()


def _symbols() -> list[SymbolCapability]:
    return [
        SymbolCapability(
            canonical_symbol=canonical,
            broker_symbol=broker,
            digits=5,
            point=0.00001,
            tick_size=0.00001,
            tick_value_profit=1.0,
            tick_value_loss=1.0,
            volume_min=0.01,
            volume_max=50.0,
            volume_step=0.01,
            stops_level_points=0,
            freeze_level_points=0,
            expiration_modes=["SPECIFIED"],
        )
        for canonical, broker in load_symbol_universe()
    ]


async def _publish_snapshot(
    postgres: _PoolBackedPostgres,
    executor_id: UUID,
    *,
    open_positions: list[dict[str, object]] | None = None,
) -> None:
    repository = MT5CommandRepository(pg=cast(Any, postgres))
    now = datetime.now(UTC)
    snapshot = AccountSnapshotV1.model_validate(
        {
            "snapshot_id": f"snap-{uuid4()}",
            "captured_at_utc": now,
            "executor_id": executor_id,
            "account_id": ACCOUNT_ID,
            "currency": "USD",
            "balance": 1000.0,
            "equity": 1000.0,
            "floating_pnl": 0.0,
            "used_margin": 0.0,
            "free_margin": 1000.0,
            "margin_level_pct": None,
            "margin_mode": MarginMode.HEDGING,
            "trade_allowed": True,
            "autotrading_enabled": True,
            "open_positions": open_positions or [],
            "symbols": [item.model_dump(mode="json") for item in _symbols()],
        }
    )
    await repository.record_heartbeat(
        ExecutorHeartbeatV1(
            executor_id=executor_id,
            sent_at_utc=now,
            terminal_connected=True,
            trade_allowed=True,
            autotrading_enabled=True,
            account_snapshot=snapshot,
        )
    )


async def _cleanup(postgres: _PoolBackedPostgres, executor_id: UUID) -> None:
    await postgres.execute(
        "DELETE FROM broker_entities WHERE command_id IN "
        "(SELECT command_id FROM execution_commands WHERE executor_id = $1::uuid)",
        str(executor_id),
    )
    await postgres.execute("DELETE FROM execution_reports WHERE executor_id = $1::uuid", str(executor_id))
    await postgres.execute("DELETE FROM execution_commands WHERE executor_id = $1::uuid", str(executor_id))
    await postgres.execute("DELETE FROM executor_account_snapshots WHERE executor_id = $1::uuid", str(executor_id))
    await postgres.execute("DELETE FROM executor_governance_audit WHERE executor_id = $1::uuid", str(executor_id))
    await postgres.execute("DELETE FROM executor_instances WHERE executor_id = $1::uuid", str(executor_id))
    await postgres.execute("DELETE FROM ea_agents WHERE id = $1::uuid", str(executor_id))


@pytest_asyncio.fixture
async def executor_id(postgres: _PoolBackedPostgres) -> AsyncIterator[UUID]:
    value = uuid4()
    await postgres.execute(
        """
        INSERT INTO ea_agents (
            id, agent_name, ea_class, ea_subtype, execution_mode, reporter_mode, status, locked
        ) VALUES ($1::uuid, $2, 'PRIMARY', 'EDUMB', 'SHADOW', 'FULL', 'OFFLINE', false)
        """,
        str(value),
        f"MT5 Matrix Auditor {value}",
    )
    try:
        repository = MT5CommandRepository(pg=cast(Any, postgres))
        await repository.register_executor(
            ExecutorRegistrationV1(
                executor_id=value,
                account_id=ACCOUNT_ID,
                login_hash=LOGIN_HASH,
                broker_server=BROKER_SERVER,
                terminal_build=5000,
                ea_version=EXPECTED_EA_VERSION,
                requested_mode=ExecutorMode.SHADOW,
            )
        )
        await _publish_snapshot(postgres, value)
        yield value
    finally:
        await _cleanup(postgres, value)


def _manifest(executor_id: UUID, commands: list[ManifestCommand], *, started_at: datetime) -> MatrixManifest:
    return MatrixManifest(
        schema_version=MANIFEST_VERSION,
        run_id=f"audit-{executor_id.hex[:12]}",
        phase="A1" if len(commands) == 1 else "A2",
        symbol_universe=REQUIRED_UNIVERSE,
        executor_id=executor_id,
        broker_server=BROKER_SERVER,
        expected_ea_version=EXPECTED_EA_VERSION,
        expected_protocol_version=PROTOCOL_VERSION,
        started_at_utc=started_at,
        commands=tuple(commands),
    )


async def _insert_command(
    postgres: _PoolBackedPostgres,
    executor_id: UUID,
    *,
    canonical: str,
    broker: str,
    terminal: bool = True,
) -> ManifestCommand:
    command_id = uuid4()
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "event": "execution_command",
        "protocol_version": PROTOCOL_VERSION,
        "command_id": str(command_id),
        "idempotency_key": f"test:{command_id}",
        "executor_binding": {
            "executor_id": str(executor_id),
            "account_id": ACCOUNT_ID,
            "login_hash": LOGIN_HASH,
            "broker_server": BROKER_SERVER,
            "execution_mode": ExecutorMode.SHADOW.value,
        },
        "order": {"canonical_symbol": canonical, "broker_symbol": broker},
    }
    payload_hash = sha256_tag(payload)
    payload_b64 = base64.urlsafe_b64encode(canonical_json_bytes(payload)).decode("ascii").rstrip("=")
    await postgres.execute(
        """
        INSERT INTO execution_commands (
            command_id, executor_id, account_id, source_signal_id, source_signal_hash,
            idempotency_key, revision, action, payload, payload_hash, state,
            issued_at, not_before, expires_at, last_report_sequence, terminal_at,
            wire_format, payload_encoding, signed_payload_b64, signed_payload_sha256,
            signature_algorithm, signature_key_id, signature_value
        ) VALUES (
            $1::uuid, $2::uuid, $3, $4, $5, $6, 1, 'PLACE_PENDING', $7::jsonb, $8, $9,
            $10, $10, $11, $12, $13, $14, 'base64url', $15, $8,
            'HMAC-SHA256', 'matrix-test.v2', $16
        )
        """,
        str(command_id),
        str(executor_id),
        ACCOUNT_ID,
        f"matrix-test-{command_id}",
        "sha256:" + "1" * 64,
        f"matrix:test:{command_id}",
        json.dumps(payload),
        payload_hash,
        "SHADOW_COMPLETED" if terminal else "QUEUED",
        now - timedelta(seconds=1),
        now + timedelta(minutes=5),
        1 if terminal else 0,
        now if terminal else None,
        SIGNED_WIRE_VERSION,
        payload_b64,
        "base64url:" + "A" * 43,
    )
    if terminal:
        report_id = uuid4()
        report_payload: dict[str, object] = {
            "report_id": str(report_id),
            "command_id": str(command_id),
            "executor_id": str(executor_id),
            "state": "WOULD_EXECUTE",
            "request_hash": payload_hash,
            "reason_code": "SHADOW_PREFLIGHT_PASSED",
            "broker": {"order_ticket": None, "deal_ticket": None, "position_id": None},
            "execution": {"filled_volume": 0.0},
        }
        await postgres.execute(
            """
            INSERT INTO execution_reports (
                report_id, command_id, executor_id, sequence, state, payload, payload_hash,
                event_time, received_at
            ) VALUES ($1::uuid, $2::uuid, $3::uuid, 1, 'WOULD_EXECUTE', $4::jsonb, $5, $6, $6)
            """,
            str(report_id),
            str(command_id),
            str(executor_id),
            json.dumps(report_payload),
            sha256_tag(report_payload),
            now,
        )
    return ManifestCommand(canonical_symbol=canonical, broker_symbol=broker, command_id=command_id)


@pytest.fixture(autouse=True)
def _inject_postgres(monkeypatch: pytest.MonkeyPatch, postgres: _PoolBackedPostgres) -> None:
    import storage.postgres_client as postgres_module

    monkeypatch.setattr(postgres_module, "pg_client", postgres)


@pytest.mark.asyncio
async def test_auditor_proves_one_terminal_command_without_writing(
    postgres: _PoolBackedPostgres,
    executor_id: UUID,
) -> None:
    started = datetime.now(UTC) - timedelta(seconds=1)
    expected = await _insert_command(postgres, executor_id, canonical="EURUSD", broker="EURUSD")
    before_commands = await postgres.fetchval(
        "SELECT count(*) FROM execution_commands WHERE executor_id = $1::uuid", str(executor_id)
    )
    before_reports = await postgres.fetchval(
        "SELECT count(*) FROM execution_reports WHERE executor_id = $1::uuid", str(executor_id)
    )

    summary = await audit_manifest(_manifest(executor_id, [expected], started_at=started))

    assert summary.status == "PASSED"
    assert summary.symbols_verified == 1
    assert summary.aggregate_filled_volume == 0.0
    assert summary.broker_entities == 0
    assert (
        await postgres.fetchval(
            "SELECT count(*) FROM execution_commands WHERE executor_id = $1::uuid", str(executor_id)
        )
        == before_commands
    )
    assert (
        await postgres.fetchval("SELECT count(*) FROM execution_reports WHERE executor_id = $1::uuid", str(executor_id))
        == before_reports
    )


@pytest.mark.asyncio
async def test_auditor_rejects_an_unrelated_active_command(
    postgres: _PoolBackedPostgres,
    executor_id: UUID,
) -> None:
    started = datetime.now(UTC) - timedelta(seconds=1)
    expected = await _insert_command(postgres, executor_id, canonical="EURUSD", broker="EURUSD")
    await _insert_command(postgres, executor_id, canonical="GBPUSD", broker="GBPUSD", terminal=False)

    with pytest.raises(MatrixAbortError) as raised:
        await audit_manifest(_manifest(executor_id, [expected], started_at=started))

    assert raised.value.reason_code == "UNEXPECTED_ACTIVE_COMMANDS"


@pytest.mark.asyncio
async def test_auditor_rejects_an_unexpected_report(
    postgres: _PoolBackedPostgres,
    executor_id: UUID,
) -> None:
    started = datetime.now(UTC) - timedelta(seconds=1)
    expected = await _insert_command(postgres, executor_id, canonical="EURUSD", broker="EURUSD")
    await _insert_command(postgres, executor_id, canonical="GBPUSD", broker="GBPUSD")

    with pytest.raises(MatrixAbortError) as raised:
        await audit_manifest(_manifest(executor_id, [expected], started_at=started))

    assert raised.value.reason_code == "UNEXPECTED_REPORTS"


@pytest.mark.asyncio
async def test_auditor_rejects_report_request_hash_tampering(
    postgres: _PoolBackedPostgres,
    executor_id: UUID,
) -> None:
    started = datetime.now(UTC) - timedelta(seconds=1)
    expected = await _insert_command(postgres, executor_id, canonical="EURUSD", broker="EURUSD")
    await postgres.execute(
        """
        UPDATE execution_reports
        SET payload = jsonb_set(payload, '{request_hash}', to_jsonb($2::text))
        WHERE command_id = $1::uuid
        """,
        str(expected.command_id),
        "sha256:" + "0" * 64,
    )

    with pytest.raises(MatrixAbortError) as raised:
        await audit_manifest(_manifest(executor_id, [expected], started_at=started))

    assert raised.value.reason_code == "REPORT_BINDING_MISMATCH"


@pytest.mark.asyncio
async def test_auditor_rejects_wrong_ea_version(
    postgres: _PoolBackedPostgres,
    executor_id: UUID,
) -> None:
    expected = await _insert_command(postgres, executor_id, canonical="EURUSD", broker="EURUSD")
    await postgres.execute(
        "UPDATE executor_instances SET ea_version = 'wrong-version' WHERE executor_id = $1::uuid",
        str(executor_id),
    )

    with pytest.raises(MatrixAbortError) as raised:
        await audit_manifest(_manifest(executor_id, [expected], started_at=datetime.now(UTC) - timedelta(seconds=1)))

    assert raised.value.reason_code == "EA_VERSION_MISMATCH"


@pytest.mark.asyncio
async def test_auditor_rejects_disengaged_kill_switch_and_fixture_restores_original(
    postgres: _PoolBackedPostgres,
    executor_id: UUID,
) -> None:
    expected = await _insert_command(postgres, executor_id, canonical="EURUSD", broker="EURUSD")
    original = await postgres.fetchval(
        "SELECT kill_switch_active FROM executor_bridge_governance WHERE singleton_id = 1"
    )
    await postgres.execute("UPDATE executor_bridge_governance SET kill_switch_active = false WHERE singleton_id = 1")
    try:
        with pytest.raises(MatrixAbortError) as raised:
            await audit_manifest(
                _manifest(executor_id, [expected], started_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        assert raised.value.reason_code == "KILL_SWITCH_INACTIVE"
    finally:
        await postgres.execute(
            "UPDATE executor_bridge_governance SET kill_switch_active = $1 WHERE singleton_id = 1",
            original,
        )


@pytest.mark.asyncio
async def test_auditor_rejects_nonzero_open_positions(
    postgres: _PoolBackedPostgres,
    executor_id: UUID,
) -> None:
    expected = await _insert_command(postgres, executor_id, canonical="EURUSD", broker="EURUSD")
    await _publish_snapshot(
        postgres,
        executor_id,
        open_positions=[
            {
                "position_id": 123,
                "symbol": "EURUSD",
                "side": "BUY",
                "volume": 0.01,
                "entry_price": 1.1,
                "current_price": 1.1,
                "stop_loss": 1.09,
                "take_profit": 1.12,
                "magic": 915030,
                "comment": "test",
                "floating_pnl": 0.0,
            }
        ],
    )

    with pytest.raises(MatrixAbortError) as raised:
        await audit_manifest(_manifest(executor_id, [expected], started_at=datetime.now(UTC) - timedelta(seconds=1)))

    assert raised.value.reason_code == "BASELINE_OPEN_POSITIONS"
