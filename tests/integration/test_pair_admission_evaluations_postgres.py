"""Real-PostgreSQL gate for the independent PairAdmission ledger."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any

import pytest

from analysis.signal_throttle_log_analyzer import SignalThrottleLogEvent
from analysis.strategy_5scr_pair_admission import build_pair_admission_audit
from analysis.strategy_5scr_raw_admission_blocks import build_raw_admission_population
from storage.pair_admission_evaluations import PairAdmissionEvaluationRepository

pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)

START = datetime(2026, 8, 10, 3, 0, tzinfo=UTC)


def _evaluation() -> dict[str, Any]:
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
            deployment_id="integration-deployment",
            scanner_cycle_id=f"cycle-{seconds}",
            eligible_for_pressure_block=True,
            eligible_for_execution=False,
        )
        for seconds in (0, 150, 300)
    )
    population = build_raw_admission_population(events)
    audit = build_pair_admission_audit(population.blocks, raw_events=population.events)
    return dict(audit.evaluations[0])


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
