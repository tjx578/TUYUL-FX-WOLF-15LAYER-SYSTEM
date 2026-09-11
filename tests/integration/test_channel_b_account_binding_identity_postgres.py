"""Real-PostgreSQL gates for the durable Channel-B account-binding identity authority.

Covers the gates that only a live server can settle: the physical column set, the
audit projection, auditor privilege containment, rotation and retirement lifecycle,
and that a Channel-B read performs zero production mutation.

Skips unless a disposable database is offered, so a green local run without one is
reported as NOT_RUN rather than PASS.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from execution.account_binding_identity_repository import (
    AccountBindingIdentityError,
    active_account_binding_identities,
    produce_account_binding_identity,
    retire_account_binding_identity,
)
from ops.mt5_mcp import account_binding
from tests.integration.postgres_test_guard import (
    require_destructive_postgres_opt_in,
    require_disposable_postgres_target,
)
from tests.reconciliation_fixtures import configure_test_keys

_RUN_FLAG = "WOLF15_RUN_POSTGRES_INTEGRATION"
_DATABASE_GUARD = "WOLF15_POSTGRES_TEST_DATABASE"
_DESTRUCTIVE_FLAG = "WOLF15_ALLOW_DESTRUCTIVE_PG_TESTS"

ACCOUNT_ID = "44556677"
BROKER_SERVER = "Broker-Demo-ChannelB"
IDENTITY_TABLE = "executor_account_binding_identifiers"
AUDIT_VIEW = "wolf15_audit.account_binding_identity_v1"
ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def identity_keys(monkeypatch: Any) -> None:
    configure_test_keys(monkeypatch)


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[Any]:
    if os.getenv(_RUN_FLAG) != "1":
        pytest.skip(f"set {_RUN_FLAG}=1 to use a disposable PostgreSQL database")
    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        pytest.fail(f"{_RUN_FLAG}=1 requires DATABASE_URL")
    try:
        asyncpg = import_module("asyncpg")
    except ModuleNotFoundError:
        pytest.fail(f"{_RUN_FLAG}=1 requires the asyncpg dependency")
    created = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4, command_timeout=10)
    try:
        yield created
    finally:
        await created.close()


async def _make_executor(pool: Any, *, execution_mode: str = "SHADOW", account_id: str = ACCOUNT_ID) -> UUID:
    executor_id = uuid4()
    async with pool.acquire() as connection:
        await connection.execute(
            """INSERT INTO ea_agents (id, agent_name, ea_class, ea_subtype, execution_mode,
                                      reporter_mode, status, locked)
               VALUES ($1::uuid,$2,'PRIMARY','EDUMB',$3,'FULL','OFFLINE',false)""",
            str(executor_id),
            f"Channel-B identity {executor_id}",
            execution_mode,
        )
        await connection.execute(
            """INSERT INTO executor_instances (executor_id, account_id, login_hash, broker_server,
                                               terminal_build, ea_version, protocol_version,
                                               execution_mode, status)
               VALUES ($1::uuid,$2,$3,$4,5000,'p4-test','wolf15.mt5.exec.v1',$5,'REGISTERED')""",
            str(executor_id),
            account_id,
            "sha256:" + "a" * 64,
            BROKER_SERVER,
            execution_mode,
        )
    return executor_id


async def _drop_executor(pool: Any, executor_id: UUID) -> None:
    async with pool.acquire() as connection:
        await connection.execute(
            f"DELETE FROM {IDENTITY_TABLE} WHERE executor_id=$1::uuid",  # noqa: S608 - constant table name
            str(executor_id),
        )
        await connection.execute("DELETE FROM executor_instances WHERE executor_id=$1::uuid", str(executor_id))
        await connection.execute("DELETE FROM ea_agents WHERE id=$1::uuid", str(executor_id))


@pytest_asyncio.fixture
async def shadow_executor(pool: Any) -> AsyncIterator[UUID]:
    executor_id = await _make_executor(pool)
    try:
        yield executor_id
    finally:
        await _drop_executor(pool, executor_id)


# --- P4-C03 / P4-C04: physical schema stores nothing sensitive ---------------


async def test_physical_columns_carry_no_raw_account_or_secret(pool: Any) -> None:
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """SELECT column_name FROM information_schema.columns
                WHERE table_name=$1 ORDER BY column_name""",
            IDENTITY_TABLE,
        )
    columns = {row["column_name"] for row in rows}
    assert columns == {
        "executor_id",
        "key_id",
        "scheme",
        "contract_version",
        "algorithm",
        "identifier",
        "binding_source",
        "broker_server",
        "generated_at",
        "retired_at",
        "producer_version",
    }
    for forbidden in ("account_id", "login_hash", "snapshot_payload", "secret", "hmac_key"):
        assert forbidden not in columns


async def test_persisted_row_contains_no_secret_material(pool: Any, shadow_executor: UUID) -> None:
    async with pool.acquire() as connection, connection.transaction():
        projected = await produce_account_binding_identity(connection, shadow_executor)
    secret = os.environ[account_binding.KEY_ENV]
    serialised = repr(projected)
    assert secret not in serialised
    assert ACCOUNT_ID not in serialised
    assert projected["identifier"].startswith("w15ab:v1:")


# --- P4-C19 / P4-C20 / P4-C21 / P4-C22: producer behaviour ------------------


async def test_producer_derives_identity_from_the_authoritative_binding(pool: Any, shadow_executor: UUID) -> None:
    expected = account_binding.identifier(
        secret_key=account_binding.decode_secret_key(os.environ[account_binding.KEY_ENV]),
        key_id=os.environ[account_binding.KEY_ID_ENV],
        login=ACCOUNT_ID,
        server=BROKER_SERVER,
    )
    async with pool.acquire() as connection, connection.transaction():
        projected = await produce_account_binding_identity(connection, shadow_executor)
    assert account_binding.identifiers_match(projected["identifier"], expected)
    assert projected["scheme"] == account_binding.SCHEME
    assert projected["contract_version"] == account_binding.VERSION
    assert projected["algorithm"] == account_binding.ALGORITHM
    assert projected["binding_source"] == account_binding.DATABASE_SOURCE
    assert projected["retired_at"] is None


async def test_producer_is_idempotent_for_an_identical_binding(pool: Any, shadow_executor: UUID) -> None:
    async with pool.acquire() as connection, connection.transaction():
        first = await produce_account_binding_identity(connection, shadow_executor)
        second = await produce_account_binding_identity(connection, shadow_executor)
        rows = await connection.fetch(
            f"SELECT * FROM {IDENTITY_TABLE} WHERE executor_id=$1::uuid",  # noqa: S608 - constant table name
            str(shadow_executor),
        )
    assert first["identifier"] == second["identifier"]
    assert first["generated_at"] == second["generated_at"]
    assert len(rows) == 1


async def test_same_key_id_with_a_changed_binding_fails_closed(pool: Any, shadow_executor: UUID) -> None:
    """P4-C22: an identifier already published under a key version is never rewritten."""

    async with pool.acquire() as connection, connection.transaction():
        original = await produce_account_binding_identity(connection, shadow_executor)
        await connection.execute(
            "UPDATE executor_instances SET account_id=$2 WHERE executor_id=$1::uuid",
            str(shadow_executor),
            "99887766",
        )
        with pytest.raises(AccountBindingIdentityError) as raised:
            await produce_account_binding_identity(connection, shadow_executor)
        assert raised.value.code == "ACCOUNT_BINDING_IDENTITY_CONFLICT"
        stored = await connection.fetchrow(
            f"SELECT identifier FROM {IDENTITY_TABLE} WHERE executor_id=$1::uuid",  # noqa: S608 - constant table
            str(shadow_executor),
        )
        assert stored["identifier"] == original["identifier"]


async def test_revoked_executor_is_refused_and_unprojected(pool: Any, shadow_executor: UUID) -> None:
    async with pool.acquire() as connection, connection.transaction():
        await produce_account_binding_identity(connection, shadow_executor)
        await connection.execute(
            "UPDATE executor_instances SET revoked_at=clock_timestamp() WHERE executor_id=$1::uuid",
            str(shadow_executor),
        )
        with pytest.raises(AccountBindingIdentityError) as raised:
            await produce_account_binding_identity(connection, shadow_executor)
        assert raised.value.code == "ACCOUNT_BINDING_EXECUTOR_REVOKED"
        assert await active_account_binding_identities(connection, shadow_executor) == []


async def test_live_mode_executor_is_out_of_scope_for_this_milestone(pool: Any) -> None:
    executor_id = await _make_executor(pool, execution_mode="LIVE")
    try:
        async with pool.acquire() as connection, connection.transaction():
            with pytest.raises(AccountBindingIdentityError) as raised:
                await produce_account_binding_identity(connection, executor_id)
            assert raised.value.code == "ACCOUNT_BINDING_EXECUTION_MODE_UNSUPPORTED"
    finally:
        await _drop_executor(pool, executor_id)


async def test_opaque_account_id_cannot_be_bound(pool: Any) -> None:
    executor_id = await _make_executor(pool, account_id="acct-opaque-01")
    try:
        async with pool.acquire() as connection, connection.transaction():
            with pytest.raises(AccountBindingIdentityError) as raised:
                await produce_account_binding_identity(connection, executor_id)
            assert raised.value.code == "ACCOUNT_BINDING_LOGIN_INVALID"
    finally:
        await _drop_executor(pool, executor_id)


# --- P4-C11 / P4-C12: rotation and retirement lifecycle ---------------------


async def test_rotation_overlap_keeps_both_key_versions_active(pool: Any, shadow_executor: UUID, monkeypatch) -> None:
    async with pool.acquire() as connection, connection.transaction():
        first = await produce_account_binding_identity(connection, shadow_executor)
        monkeypatch.setenv(account_binding.KEY_ID_ENV, "rotated-next")
        second = await produce_account_binding_identity(connection, shadow_executor)
        active = await active_account_binding_identities(connection, shadow_executor)

    assert first["key_id"] != second["key_id"]
    assert {row["key_id"] for row in active} == {first["key_id"], second["key_id"]}
    # Same account and server under two key versions must not collide.
    assert first["identifier"] != second["identifier"]


async def test_retirement_removes_eligibility_without_rewriting_the_identifier(
    pool: Any, shadow_executor: UUID
) -> None:
    async with pool.acquire() as connection, connection.transaction():
        produced = await produce_account_binding_identity(connection, shadow_executor)
        retired = await retire_account_binding_identity(connection, shadow_executor, produced["key_id"])
        assert retired["identifier"] == produced["identifier"]
        assert retired["retired_at"] is not None

        assert await active_account_binding_identities(connection, shadow_executor) == []
        base = await connection.fetchrow(
            f"SELECT identifier, retired_at FROM {IDENTITY_TABLE} WHERE executor_id=$1::uuid",  # noqa: S608
            str(shadow_executor),
        )
        assert base["identifier"] == produced["identifier"]
        assert base["retired_at"] is not None

        with pytest.raises(AccountBindingIdentityError) as raised:
            await retire_account_binding_identity(connection, shadow_executor, produced["key_id"])
        assert raised.value.code == "ACCOUNT_BINDING_IDENTITY_NOT_ACTIVE"


# --- P4-C05 to P4-C10 enforced by the server, not only by the producer ------


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("scheme", "not-w15"),
        ("contract_version", "v2"),
        ("algorithm", "HMAC-SHA-512"),
        ("binding_source", "MANUAL_INPUT"),
        ("key_id", "UPPERCASE"),
        ("identifier", "w15ab:v1:audit:too-short"),
    ],
)
async def test_server_rejects_non_canonical_rows(pool: Any, shadow_executor: UUID, column: str, value: str) -> None:
    """A compromised or buggy writer must not be able to insert a non-canonical row."""

    asyncpg = import_module("asyncpg")
    good = {
        "scheme": account_binding.SCHEME,
        "contract_version": account_binding.VERSION,
        "algorithm": account_binding.ALGORITHM,
        "binding_source": account_binding.DATABASE_SOURCE,
        "key_id": "audit-key",
        "identifier": "w15ab:v1:audit-key:" + ("A" * 43),
    }
    good[column] = value
    async with pool.acquire() as connection:
        with pytest.raises(asyncpg.exceptions.IntegrityConstraintViolationError):
            await connection.execute(
                f"""INSERT INTO {IDENTITY_TABLE}
                      (executor_id, key_id, scheme, contract_version, algorithm,
                       identifier, binding_source, broker_server, producer_version)
                    VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8,'p4-test')""",  # noqa: S608 - constant table name
                str(shadow_executor),
                good["key_id"],
                good["scheme"],
                good["contract_version"],
                good["algorithm"],
                good["identifier"],
                good["binding_source"],
                BROKER_SERVER,
            )


async def test_embedded_key_id_must_agree_with_the_column(pool: Any, shadow_executor: UUID) -> None:
    asyncpg = import_module("asyncpg")
    async with pool.acquire() as connection:
        with pytest.raises(asyncpg.exceptions.IntegrityConstraintViolationError):
            await connection.execute(
                f"""INSERT INTO {IDENTITY_TABLE}
                      (executor_id, key_id, scheme, contract_version, algorithm,
                       identifier, binding_source, broker_server, producer_version)
                    VALUES ($1::uuid,'key-a',$2,$3,$4,$5,$6,$7,'p4-test')""",  # noqa: S608 - constant table name
                str(shadow_executor),
                account_binding.SCHEME,
                account_binding.VERSION,
                account_binding.ALGORITHM,
                "w15ab:v1:key-b:" + ("A" * 43),
                account_binding.DATABASE_SOURCE,
                BROKER_SERVER,
            )


# --- P4-C13 / P4-C14 / P4-C16: the audit projection -------------------------


@pytest.mark.parametrize("execution_mode", ["SHADOW", "DEMO"])
async def test_identity_is_projected_for_shadow_and_demo(pool: Any, execution_mode: str) -> None:
    executor_id = await _make_executor(pool, execution_mode=execution_mode)
    try:
        async with pool.acquire() as connection, connection.transaction():
            projected = await produce_account_binding_identity(connection, executor_id)
        assert projected["execution_mode"] == execution_mode
    finally:
        await _drop_executor(pool, executor_id)


async def test_audit_view_exposes_only_sanitised_metadata(pool: Any, shadow_executor: UUID) -> None:
    async with pool.acquire() as connection, connection.transaction():
        await produce_account_binding_identity(connection, shadow_executor)
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """SELECT column_name FROM information_schema.columns
                WHERE table_schema='wolf15_audit' AND table_name='account_binding_identity_v1'"""
        )
    columns = {row["column_name"] for row in rows}
    for forbidden in ("account_id", "login_hash", "snapshot_payload"):
        assert forbidden not in columns
    assert {"identifier", "key_id", "scheme", "contract_version", "algorithm", "binding_source"} <= columns


# --- P4-C17 / P4-C18: auditor privilege containment -------------------------


async def test_auditor_may_select_the_view_and_not_the_base_table(pool: Any, shadow_executor: UUID) -> None:
    async with pool.acquire() as connection:
        role = await connection.fetchval("SELECT 1 FROM pg_roles WHERE rolname='wolf15_auditor'")
        if role is None:
            pytest.skip("wolf15_auditor role is not provisioned in this disposable database")
        assert await connection.fetchval("SELECT has_table_privilege('wolf15_auditor', $1, 'SELECT')", AUDIT_VIEW)
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not await connection.fetchval(
                "SELECT has_table_privilege('wolf15_auditor', $1, $2)", IDENTITY_TABLE, privilege
            )


# --- P4-C31 / P4-C32: a Channel-B read mutates nothing ----------------------


async def test_reading_the_projection_performs_zero_production_mutation(pool: Any, shadow_executor: UUID) -> None:
    """Mirror how Channel B actually reads: a separate, never-writing session.

    pg_stat_xact_user_tables reports the calling backend, so a pooled connection
    that just performed the setup INSERTs reports those tuples and the assertion
    would be measuring the wrong thing. The auditor connects as its own session,
    so the test must too.
    """

    async with pool.acquire() as connection, connection.transaction():
        await produce_account_binding_identity(connection, shadow_executor)

    asyncpg = import_module("asyncpg")
    connection = await asyncpg.connect(dsn=os.environ["DATABASE_URL"])
    try:
        transaction = connection.transaction(readonly=True, isolation="repeatable_read")
        await transaction.start()
        try:
            rows = await connection.fetch(
                f"SELECT * FROM {AUDIT_VIEW} WHERE executor_id=$1::uuid",  # noqa: S608 - constant view name
                str(shadow_executor),
            )
            assert len(rows) == 1
            assert await connection.fetchval("SELECT current_setting('transaction_read_only')::boolean") is True
            changed = await connection.fetchval(
                """SELECT coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del), 0)::bigint
                     FROM pg_catalog.pg_stat_xact_user_tables"""
            )
            assert changed == 0
        finally:
            await transaction.rollback()
    finally:
        await connection.close()


# --- migration lifecycle: upgrade -> downgrade -> upgrade -------------------


def _run_alembic(*arguments: str) -> None:
    """Drive alembic in a subprocess, never in-process.

    storage/migrations/env.py calls logging.config.fileConfig(alembic.ini), which
    defaults to disable_existing_loggers=True. Importing and calling alembic
    inside pytest therefore silences every logger already configured, and makes
    unrelated emitter tests later in the session assert against empty output.
    A subprocess keeps that blast radius out of this process entirely.
    """

    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), *arguments],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, "alembic " + " ".join(arguments) + " failed: " + completed.stderr


async def _objects_present(pool: Any) -> tuple[bool, bool]:
    async with pool.acquire() as connection:
        table = await connection.fetchval("SELECT to_regclass($1) IS NOT NULL", IDENTITY_TABLE)
        view = await connection.fetchval("SELECT to_regclass($1) IS NOT NULL", AUDIT_VIEW)
    return bool(table), bool(view)


async def test_migration_survives_downgrade_and_re_upgrade(pool: Any) -> None:
    """Adding an authority object plus a view and ACLs must be reversible.

    Destructive: it rewrites schema on the target, so it needs the explicit
    disposable-database opt-in on top of the integration flag.
    """

    try:
        require_destructive_postgres_opt_in(os.getenv(_DESTRUCTIVE_FLAG, ""))
        require_disposable_postgres_target(os.environ["DATABASE_URL"], expected_database=os.getenv(_DATABASE_GUARD, ""))
    except ValueError as exc:
        pytest.skip(f"destructive migration round-trip not authorised here: {exc}")

    assert await _objects_present(pool) == (True, True)

    await asyncio.to_thread(_run_alembic, "downgrade", "20260910_02")
    assert await _objects_present(pool) == (False, False)

    await asyncio.to_thread(_run_alembic, "upgrade", "20260911_01")
    assert await _objects_present(pool) == (True, True)

    # The re-created object must still enforce the canonical contract and must
    # still deny the auditor on the base table.
    async with pool.acquire() as connection:
        head = await connection.fetchval("SELECT version_num FROM alembic_version")
        assert head == "20260911_01"
        checks = await connection.fetch(
            """SELECT conname FROM pg_constraint
                WHERE conrelid = $1::regclass AND contype = 'c'""",
            IDENTITY_TABLE,
        )
        names = {row["conname"] for row in checks}
        assert {
            "account_binding_identity_scheme",
            "account_binding_identity_version",
            "account_binding_identity_algorithm",
            "account_binding_identity_source",
            "account_binding_identity_key_id_shape",
            "account_binding_identity_shape",
            "account_binding_identity_key_id_agrees",
        } <= names
        if await connection.fetchval("SELECT 1 FROM pg_roles WHERE rolname='wolf15_auditor'"):
            assert await connection.fetchval("SELECT has_table_privilege('wolf15_auditor', $1, 'SELECT')", AUDIT_VIEW)
            assert not await connection.fetchval(
                "SELECT has_table_privilege('wolf15_auditor', $1, 'SELECT')", IDENTITY_TABLE
            )
