"""Real-PostgreSQL gate for the independent PairAdmission ledger."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any
from uuid import uuid4

import pytest

from analysis.signal_throttle_log_analyzer import SignalThrottleLogEvent
from analysis.strategy_5scr_pair_admission import build_pair_admission_audit
from analysis.strategy_5scr_raw_admission_blocks import build_raw_admission_population
from storage.observer_export_outbox import ObserverExportOutboxRepository
from storage.pair_admission_evaluations import PairAdmissionEvaluationRepository

pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)

START = datetime(2026, 8, 10, 3, 0, tzinfo=UTC)


def _evaluation_for(
    seconds_values: tuple[int, ...],
    *,
    deployment_id: str = "integration-deployment",
) -> dict[str, Any]:
    events = tuple(
        SignalThrottleLogEvent(
            timestamp=START + timedelta(seconds=seconds),
            severity="warning",
            message="raw",
            symbol="EURUSD",
            event_type="ALLOWED",
            verdict="EXECUTE_BUY",
            direction="BUY",
            pressure_source="SignalThrottle",
            source_stream="ALLOWED",
            deployment_id=deployment_id,
            scanner_cycle_id=f"cycle-{seconds}",
            eligible_for_pressure_block=True,
            eligible_for_execution=False,
        )
        for seconds in seconds_values
    )
    population = build_raw_admission_population(events)
    audit = build_pair_admission_audit(population.blocks, raw_events=population.events)
    return dict(audit.evaluations[0])


def _evaluation() -> dict[str, Any]:
    return _evaluation_for((0, 150, 300))


class _FailAfterObserverAppend(ObserverExportOutboxRepository):
    async def append_in_transaction(self, connection: Any, draft: Any, **kwargs: Any) -> Any:
        await super().append_in_transaction(connection, draft, **kwargs)
        raise RuntimeError("injected failure after observer append")


def _raw_event(seconds: int, symbol: str = "EURUSD") -> SignalThrottleLogEvent:
    return SignalThrottleLogEvent(
        timestamp=START + timedelta(seconds=seconds),
        severity="warning",
        message="raw",
        symbol=symbol,
        event_type="ALLOWED",
        verdict="EXECUTE_BUY",
        direction="BUY",
        pressure_source="SignalThrottle",
        source_stream="ALLOWED",
        deployment_id="integration-deployment",
        scanner_cycle_id=f"cycle-{seconds}",
        eligible_for_pressure_block=True,
        eligible_for_execution=False,
    )


def _first_evaluation(events: tuple[SignalThrottleLogEvent, ...]) -> dict[str, Any]:
    population = build_raw_admission_population(events)
    audit = build_pair_admission_audit(population.blocks, raw_events=population.events)
    return dict(audit.evaluations[0])


@pytest.mark.asyncio
async def test_pair_admission_schema_matches_the_full_migration_contract(postgres: Any) -> None:
    status = await PairAdmissionEvaluationRepository(pg=postgres).schema_status()

    assert status.ready is True


@pytest.mark.asyncio
async def test_pair_admission_and_observer_export_share_one_transaction(postgres: Any) -> None:
    deployment_id = f"observer-atomic-{uuid4().hex}"
    evaluation = _evaluation_for((0, 150, 300), deployment_id=deployment_id)
    evaluation_id = str(evaluation["evaluation_id"])
    failing_export = _FailAfterObserverAppend(pg=postgres)
    failing_repository = PairAdmissionEvaluationRepository(
        pg=postgres,
        observer_export_repository=failing_export,
    )

    with pytest.raises(RuntimeError, match="after observer append"):
        await failing_repository.ingest(evaluation)

    rolled_back = await postgres.fetchrow(
        """
        SELECT
          (SELECT count(*) FROM pair_admission_evaluations WHERE evaluation_id=$1) AS canonical_rows,
          (SELECT count(*) FROM observer_export.outbox
             WHERE envelope->'payload'->'body'->>'evaluation_id'=$1) AS observer_rows
        """,
        evaluation_id,
    )
    assert rolled_back is not None
    assert dict(rolled_back) == {"canonical_rows": 0, "observer_rows": 0}

    export = ObserverExportOutboxRepository(pg=postgres)
    repository = PairAdmissionEvaluationRepository(
        pg=postgres,
        observer_export_repository=export,
    )
    first = await repository.ingest(evaluation)
    replay = await repository.ingest(evaluation)
    rows = await postgres.fetch(
        """
        SELECT authority_class, payload_type, envelope
        FROM observer_export.outbox
        WHERE envelope->'payload'->'body'->>'evaluation_id'=$1
        """,
        evaluation_id,
    )

    assert first.duplicate is False
    assert replay.duplicate is True
    assert len(rows) == 1
    assert rows[0]["authority_class"] == "CANONICAL_PAIR_ADMISSION"
    assert rows[0]["payload_type"] == "PairAdmissionEvaluationV3_1"
    envelope = json.loads(rows[0]["envelope"])
    assert envelope["payload"]["body"]["execution_authority"] is False
    assert envelope["safety"]["observer_can_mutate_source"] is False


@pytest.mark.asyncio
async def test_pair_admission_grant_is_idempotent_and_non_executable(postgres: Any) -> None:
    await postgres.execute("TRUNCATE TABLE pair_admission_evaluations")
    repository = PairAdmissionEvaluationRepository(pg=postgres)
    evaluation = _evaluation()

    first = await repository.ingest(evaluation)
    # A fresh repository instance models a process restart; PostgreSQL, not
    # process memory, must retain the idempotency boundary.
    replay = await PairAdmissionEvaluationRepository(pg=postgres).ingest(evaluation)
    row = await postgres.fetchrow(
        """
        SELECT decision, admission_event_id, execution_authority, count(*) OVER () AS row_count
        FROM pair_admission_evaluations
        WHERE evaluation_id = $1
        """,
        evaluation["evaluation_id"],
    )

    assert first.duplicate is False
    assert replay.duplicate is True
    assert row is not None
    assert row["decision"] == "GRANTED"
    assert row["admission_event_id"] == evaluation["pair_admission_id"]
    assert row["execution_authority"] is False
    assert row["row_count"] == 1


@pytest.mark.asyncio
async def test_database_rejects_execution_authority(postgres: Any) -> None:
    await postgres.execute("TRUNCATE TABLE pair_admission_evaluations")
    repository = PairAdmissionEvaluationRepository(pg=postgres)
    evaluation = _evaluation()
    await repository.ingest(evaluation)
    asyncpg = import_module("asyncpg")

    with pytest.raises(asyncpg.CheckViolationError) as raised:
        await postgres.execute(
            "UPDATE pair_admission_evaluations SET execution_authority = TRUE WHERE evaluation_id = $1",
            evaluation["evaluation_id"],
        )

    assert raised.value.constraint_name == "ck_pair_admission_non_executable"


@pytest.mark.asyncio
async def test_growing_block_remains_one_grant_across_repository_restart(postgres: Any) -> None:
    await postgres.execute("TRUNCATE TABLE pair_admission_evaluations")
    first_evaluation = _evaluation_for((0, 150, 300))
    growing_evaluation = _evaluation_for((0, 150, 300, 350, 500, 650))

    first = await PairAdmissionEvaluationRepository(pg=postgres).ingest(first_evaluation)
    growing = await PairAdmissionEvaluationRepository(pg=postgres).ingest(growing_evaluation)
    row = await postgres.fetchrow(
        """
        SELECT count(*) AS evaluation_count,
               count(*) FILTER (WHERE logical_grant_created IS TRUE) AS logical_grant_count,
               min(admission_event_id) AS admission_event_id
        FROM pair_admission_evaluations
        WHERE deployment_id = $1 AND raw_block_id = $2 AND rule_version = $3
          AND decision = 'GRANTED'
        """,
        "integration-deployment",
        growing_evaluation["candidate_block_id"],
        growing_evaluation["rule_version"],
    )

    assert first.duplicate is False
    assert growing.duplicate is False
    assert first_evaluation["pair_admission_id"] == growing_evaluation["pair_admission_id"]
    assert row is not None
    assert row["evaluation_count"] == 2
    assert row["logical_grant_count"] == 1
    assert row["admission_event_id"] == first_evaluation["pair_admission_id"]


@pytest.mark.asyncio
async def test_active_snapshot_growth_appends_without_identity_collision(postgres: Any) -> None:
    await postgres.execute("TRUNCATE TABLE pair_admission_evaluations")
    first_evaluation = _first_evaluation((_raw_event(0), _raw_event(150)))
    growing_evaluation = _first_evaluation((_raw_event(0), _raw_event(150), _raw_event(250)))
    repository = PairAdmissionEvaluationRepository(pg=postgres)

    first = await repository.ingest(first_evaluation)
    growing = await repository.ingest(growing_evaluation)
    row_count = await postgres.fetchrow("SELECT count(*) AS value FROM pair_admission_evaluations")

    assert first.duplicate is False
    assert growing.duplicate is False
    assert first_evaluation["evaluation_id"] != growing_evaluation["evaluation_id"]
    assert row_count is not None
    assert row_count["value"] == 2


@pytest.mark.asyncio
async def test_active_to_finalized_appends_once_and_replays_after_restart(postgres: Any) -> None:
    await postgres.execute("TRUNCATE TABLE pair_admission_evaluations")
    active_evaluation = _first_evaluation((_raw_event(0),))
    finalized_evaluation = _first_evaluation((_raw_event(0), _raw_event(1, "GBPUSD")))

    active = await PairAdmissionEvaluationRepository(pg=postgres).ingest(active_evaluation)
    finalized = await PairAdmissionEvaluationRepository(pg=postgres).ingest(finalized_evaluation)
    replay = await PairAdmissionEvaluationRepository(pg=postgres).ingest(finalized_evaluation)
    rows = await postgres.fetch(
        """
        SELECT evaluation_id, payload->>'evaluation_state' AS evaluation_state,
               execution_authority
        FROM pair_admission_evaluations
        ORDER BY created_at
        """
    )

    assert active.duplicate is False
    assert finalized.duplicate is False
    assert replay.duplicate is True
    assert active_evaluation["evaluation_id"] != finalized_evaluation["evaluation_id"]
    assert [row["evaluation_state"] for row in rows] == ["ACTIVE", "FINALIZED"]
    assert all(row["execution_authority"] is False for row in rows)


@pytest.mark.asyncio
async def test_grant_identity_survives_finalization_without_second_grant(postgres: Any) -> None:
    await postgres.execute("TRUNCATE TABLE pair_admission_evaluations")
    active_evaluation = _first_evaluation((_raw_event(0), _raw_event(150), _raw_event(300)))
    finalized_evaluation = _first_evaluation(
        (_raw_event(0), _raw_event(150), _raw_event(300), _raw_event(301, "GBPUSD"))
    )

    active = await PairAdmissionEvaluationRepository(pg=postgres).ingest(active_evaluation)
    finalized = await PairAdmissionEvaluationRepository(pg=postgres).ingest(finalized_evaluation)
    row = await postgres.fetchrow(
        """
        SELECT count(*) AS evaluation_count,
               count(*) FILTER (WHERE logical_grant_created IS TRUE) AS logical_grant_count,
               min(admission_event_id) AS admission_event_id
        FROM pair_admission_evaluations
        WHERE raw_block_id = $1 AND rule_version = $2 AND decision = 'GRANTED'
        """,
        active_evaluation["candidate_block_id"],
        active_evaluation["rule_version"],
    )

    assert active.duplicate is False
    assert finalized.duplicate is False
    assert active_evaluation["pair_admission_id"] == finalized_evaluation["pair_admission_id"]
    assert row is not None
    assert row["evaluation_count"] == 2
    assert row["logical_grant_count"] == 1
    assert row["admission_event_id"] == active_evaluation["pair_admission_id"]


@pytest.mark.asyncio
async def test_schema_readiness_rejects_missing_and_weakened_non_execution_check(postgres: Any) -> None:
    repository = PairAdmissionEvaluationRepository(pg=postgres)
    await postgres.execute("ALTER TABLE pair_admission_evaluations DROP CONSTRAINT ck_pair_admission_non_executable")
    try:
        missing = await repository.schema_status()
        assert missing.ready is False
        assert "ck_pair_admission_non_executable" in missing.missing_constraints

        await postgres.execute(
            """
            ALTER TABLE pair_admission_evaluations
            ADD CONSTRAINT ck_pair_admission_non_executable CHECK (execution_authority IS NOT NULL)
            """
        )
        weakened = await repository.schema_status()
        assert weakened.ready is False
        assert "ck_pair_admission_non_executable:definition" in weakened.invalid_constraints
    finally:
        await postgres.execute(
            "ALTER TABLE pair_admission_evaluations DROP CONSTRAINT IF EXISTS ck_pair_admission_non_executable"
        )
        await postgres.execute(
            """
            ALTER TABLE pair_admission_evaluations
            ADD CONSTRAINT ck_pair_admission_non_executable CHECK (execution_authority IS FALSE)
            """
        )
    assert (await repository.schema_status()).ready is True


@pytest.mark.asyncio
async def test_schema_readiness_rejects_broadened_non_execution_check(postgres: Any) -> None:
    repository = PairAdmissionEvaluationRepository(pg=postgres)
    await postgres.execute("ALTER TABLE pair_admission_evaluations DROP CONSTRAINT ck_pair_admission_non_executable")
    try:
        await postgres.execute(
            """
            ALTER TABLE pair_admission_evaluations
            ADD CONSTRAINT ck_pair_admission_non_executable
            CHECK (execution_authority IS FALSE OR TRUE)
            """
        )
        status = await repository.schema_status()
        assert status.ready is False
        assert "ck_pair_admission_non_executable:definition" in status.invalid_constraints
    finally:
        await postgres.execute(
            "ALTER TABLE pair_admission_evaluations DROP CONSTRAINT IF EXISTS ck_pair_admission_non_executable"
        )
        await postgres.execute(
            """
            ALTER TABLE pair_admission_evaluations
            ADD CONSTRAINT ck_pair_admission_non_executable CHECK (execution_authority IS FALSE)
            """
        )
    assert (await repository.schema_status()).ready is True


@pytest.mark.asyncio
async def test_schema_readiness_rejects_wrong_unique_predicate(postgres: Any) -> None:
    repository = PairAdmissionEvaluationRepository(pg=postgres)
    await postgres.execute("TRUNCATE TABLE pair_admission_evaluations")
    await postgres.execute("DROP INDEX uq_pair_admission_one_grant_per_block")
    try:
        await postgres.execute(
            """
            CREATE UNIQUE INDEX uq_pair_admission_one_grant_per_block
            ON pair_admission_evaluations (deployment_id, raw_block_id, rule_version)
            WHERE logical_grant_created IS FALSE
            """
        )
        status = await repository.schema_status()
        assert status.ready is False
        assert "uq_pair_admission_one_grant_per_block:predicate" in status.invalid_indexes
    finally:
        await postgres.execute("DROP INDEX IF EXISTS uq_pair_admission_one_grant_per_block")
        await postgres.execute(
            """
            CREATE UNIQUE INDEX uq_pair_admission_one_grant_per_block
            ON pair_admission_evaluations (deployment_id, raw_block_id, rule_version)
            WHERE logical_grant_created IS TRUE
            """
        )
    assert (await repository.schema_status()).ready is True


@pytest.mark.asyncio
async def test_schema_readiness_rejects_broadened_unique_predicate(postgres: Any) -> None:
    repository = PairAdmissionEvaluationRepository(pg=postgres)
    await postgres.execute("TRUNCATE TABLE pair_admission_evaluations")
    await postgres.execute("DROP INDEX uq_pair_admission_one_grant_per_block")
    try:
        await postgres.execute(
            """
            CREATE UNIQUE INDEX uq_pair_admission_one_grant_per_block
            ON pair_admission_evaluations (deployment_id, raw_block_id, rule_version)
            WHERE logical_grant_created IS TRUE OR TRUE
            """
        )
        status = await repository.schema_status()
        assert status.ready is False
        assert "uq_pair_admission_one_grant_per_block:predicate" in status.invalid_indexes
    finally:
        await postgres.execute("DROP INDEX IF EXISTS uq_pair_admission_one_grant_per_block")
        await postgres.execute(
            """
            CREATE UNIQUE INDEX uq_pair_admission_one_grant_per_block
            ON pair_admission_evaluations (deployment_id, raw_block_id, rule_version)
            WHERE logical_grant_created IS TRUE
            """
        )
    assert (await repository.schema_status()).ready is True


@pytest.mark.asyncio
async def test_schema_readiness_rejects_wrong_execution_authority_default(postgres: Any) -> None:
    repository = PairAdmissionEvaluationRepository(pg=postgres)
    await postgres.execute("ALTER TABLE pair_admission_evaluations ALTER COLUMN execution_authority SET DEFAULT TRUE")
    try:
        status = await repository.schema_status()
        assert status.ready is False
        assert any(item.startswith("execution_authority:default=") for item in status.invalid_columns)
    finally:
        await postgres.execute(
            "ALTER TABLE pair_admission_evaluations ALTER COLUMN execution_authority SET DEFAULT FALSE"
        )
    assert (await repository.schema_status()).ready is True


@pytest.mark.asyncio
async def test_schema_readiness_rejects_inverted_execution_authority_default(postgres: Any) -> None:
    repository = PairAdmissionEvaluationRepository(pg=postgres)
    await postgres.execute(
        "ALTER TABLE pair_admission_evaluations ALTER COLUMN execution_authority SET DEFAULT (NOT FALSE)"
    )
    try:
        status = await repository.schema_status()
        assert status.ready is False
        assert any(item.startswith("execution_authority:default=") for item in status.invalid_columns)
    finally:
        await postgres.execute(
            "ALTER TABLE pair_admission_evaluations ALTER COLUMN execution_authority SET DEFAULT FALSE"
        )
    assert (await repository.schema_status()).ready is True
