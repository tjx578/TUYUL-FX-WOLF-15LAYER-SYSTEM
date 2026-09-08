"""Real PostgreSQL gates for the append-only observer export chain."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import pytest

from contracts.observer_telemetry_export_v1 import (
    CanonicalDecisionReasonV1,
    observer_draft,
    observer_source_from_env,
)
from storage.observer_export_outbox import (
    ObserverExportIntegrityError,
    ObserverExportOutboxRepository,
)

if TYPE_CHECKING:
    from tests.integration.lifecycle_v2_postgres_plugin import PoolBackedPostgres

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)

NOW = datetime(2026, 8, 22, 3, 0, tzinfo=UTC)


def _draft(stream_id: str, index: int, *, reason: str | None = None):
    body = CanonicalDecisionReasonV1(
        decision_id=f"decision:{stream_id}:{index}",
        strategy_lifecycle_id="5scr-lifecycle:" + "c" * 32,
        authority_scope_id="5scr-lifecycle:" + "c" * 32,
        stage="TRADEPLAN_CANDIDATE",
        decision="WAIT",
        reason_code=reason or f"WAIT_{index}",
        next_required_stage="CLOSED_CANDLE_EVIDENCE",
        evidence_refs=(f"evidence:{stream_id}:{index}",),
        decided_at_utc=NOW + timedelta(seconds=index),
    )
    return observer_draft(
        logical_event_key=f"{stream_id}|tradeplan-evaluation|{index}",
        stream_id=stream_id,
        occurred_at_utc=body.decided_at_utc,
        source=observer_source_from_env(
            service="strategy-5scr-tradeplan-candidate-v2",
            policy_version="5scr.tradeplan-candidate.v2",
            environ={"GIT_COMMIT_SHA": "c" * 40},
        ),
        body=body,
    )


def _repository(postgres: PoolBackedPostgres) -> ObserverExportOutboxRepository:
    return ObserverExportOutboxRepository(pg=cast(Any, postgres))


async def test_schema_status_attests_live_append_only_triggers(postgres: PoolBackedPostgres) -> None:
    status = await _repository(postgres).schema_status()

    assert status.ready is True
    assert status.missing_tables == ()
    assert status.missing_indexes == ()
    assert status.missing_triggers == ()


@pytest.mark.parametrize("failure_point", ["canonical", "export"])
async def test_canonical_and_export_rows_share_one_rollback_boundary(
    postgres: PoolBackedPostgres,
    failure_point: str,
) -> None:
    repository = _repository(postgres)
    stream_id = f"observer-atomicity:{uuid4().hex}"
    draft = _draft(stream_id, 1)

    with pytest.raises(RuntimeError, match="injected"):
        async with postgres.transaction() as connection:
            await connection.execute(
                "CREATE TEMP TABLE IF NOT EXISTS observer_export_atomic_probe (id text primary key)"
            )
            await connection.execute("INSERT INTO observer_export_atomic_probe (id) VALUES ($1)", stream_id)
            if failure_point == "canonical":
                raise RuntimeError("injected canonical rollback")
            await repository.append_in_transaction(connection, draft)
            raise RuntimeError("injected export rollback")

    row = await postgres.fetchrow(
        "SELECT event_id FROM observer_export.outbox WHERE event_id=$1",
        draft.event_id,
    )
    head = await postgres.fetchrow(
        "SELECT last_sequence FROM observer_export.stream_heads WHERE stream_id=$1",
        stream_id,
    )
    assert row is None
    assert head is None


async def test_retry_collision_restart_and_concurrent_publishers(postgres: PoolBackedPostgres) -> None:
    repository = _repository(postgres)
    stream_id = f"observer-chain:{uuid4().hex}"
    first_draft = _draft(stream_id, 1)
    async with postgres.transaction() as connection:
        first = await repository.append_in_transaction(connection, first_draft)
    async with postgres.transaction() as connection:
        duplicate = await repository.append_in_transaction(connection, first_draft)
    assert duplicate.duplicate is True
    assert duplicate.event_hash == first.event_hash

    changed = _draft(stream_id, 1, reason="MUTATED_CANONICAL_REASON")
    assert changed.event_id == first_draft.event_id
    with pytest.raises(ObserverExportIntegrityError, match="CONTENT_MISMATCH"):
        async with postgres.transaction() as connection:
            await repository.append_in_transaction(connection, changed)

    restarted = _repository(postgres)

    async def publish(index: int) -> None:
        async with postgres.transaction() as connection:
            await restarted.append_in_transaction(connection, _draft(stream_id, index))

    await asyncio.wait_for(asyncio.gather(*(publish(index) for index in range(2, 102))), timeout=20)
    rows = await postgres.fetch(
        """
        SELECT stream_sequence, previous_event_hash, event_hash
        FROM observer_export.outbox
        WHERE stream_id=$1
        ORDER BY stream_sequence
        """,
        stream_id,
    )
    assert [int(row["stream_sequence"]) for row in rows] == list(range(1, 102))
    assert rows[0]["previous_event_hash"] is None
    assert all(
        current["previous_event_hash"] == previous["event_hash"]
        for previous, current in zip(rows, rows[1:], strict=False)
    )


async def test_outbox_rows_are_immutable_in_postgresql(postgres: PoolBackedPostgres) -> None:
    repository = _repository(postgres)
    stream_id = f"observer-immutable:{uuid4().hex}"
    draft = _draft(stream_id, 1)
    async with postgres.transaction() as connection:
        await repository.append_in_transaction(connection, draft)

    with pytest.raises(postgres.check_violation_error):
        await postgres.execute(
            "UPDATE observer_export.outbox SET payload_version='tampered' WHERE event_id=$1",
            draft.event_id,
        )
    with pytest.raises(postgres.check_violation_error):
        await postgres.execute("DELETE FROM observer_export.outbox WHERE event_id=$1", draft.event_id)


async def test_observer_role_is_select_only_and_cannot_lock_or_mutate(postgres: PoolBackedPostgres) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    repository = _repository(postgres)
    stream_id = f"observer-role:{uuid4().hex}"
    async with postgres.transaction() as connection:
        await repository.append_in_transaction(connection, _draft(stream_id, 1))

    role = f"observer_export_test_{uuid4().hex}"
    quoted_role = '"' + role.replace('"', '""') + '"'
    try:
        await postgres.execute(
            f"CREATE ROLE {quoted_role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        )
        await postgres.execute(f"GRANT USAGE ON SCHEMA observer_export TO {quoted_role}")
        await postgres.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA observer_export TO {quoted_role}")
        async with postgres.transaction() as connection:
            await connection.execute(f"SET LOCAL ROLE {quoted_role}")
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM observer_export.outbox WHERE stream_id=$1",
                    stream_id,
                )
                == 1
            )
            forbidden_value = f"forbidden:{uuid4().hex}"
            for statement, arguments in (
                ("SELECT * FROM observer_export.outbox WHERE stream_id=$1 FOR UPDATE", (forbidden_value,)),
                (
                    "INSERT INTO observer_export.stream_heads (stream_id,last_sequence) VALUES ($1,0)",
                    (forbidden_value,),
                ),
                ("UPDATE observer_export.stream_heads SET last_sequence=1 WHERE stream_id=$1", (forbidden_value,)),
                ("DELETE FROM observer_export.outbox WHERE stream_id=$1", (forbidden_value,)),
                ("TRUNCATE observer_export.outbox", ()),
                ("CREATE TABLE observer_export.forbidden_by_observer (id int)", ()),
            ):
                savepoint = connection.transaction()
                await savepoint.start()
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await connection.execute(statement, *arguments)
                await savepoint.rollback()

            for table in (
                "public.pressure_outbox",
                "public.strategy_5scr_risk_reservations_v2",
                "public.execution_commands",
            ):
                assert (
                    await connection.fetchval(
                        "SELECT has_table_privilege(current_user,$1,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')",
                        table,
                    )
                    is False
                )
    finally:
        await postgres.execute(f"REASSIGN OWNED BY {quoted_role} TO CURRENT_USER")
        await postgres.execute(f"DROP OWNED BY {quoted_role}")
        await postgres.execute(f"DROP ROLE IF EXISTS {quoted_role}")
