from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from analysis.signal_throttle_log_analyzer import SignalThrottleLogEvent
from analysis.strategy_5scr_pair_admission import build_pair_admission_audit
from analysis.strategy_5scr_raw_admission_blocks import build_raw_admission_population
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline
from storage.pair_admission_evaluations import PairAdmissionEvaluationRepository

START = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)


def _event(seconds: int) -> SignalThrottleLogEvent:
    return SignalThrottleLogEvent(
        timestamp=START + timedelta(seconds=seconds),
        severity="warning",
        message="raw",
        symbol="EURUSD",
        event_type="ALLOWED",
        verdict="EXECUTE_BUY",
        direction="BUY",
        pressure_source="SignalThrottle",
        source_stream="ALLOWED",
        deployment_id="deployment-A",
        scanner_cycle_id=f"cycle-{seconds}",
        eligible_for_pressure_block=True,
        eligible_for_execution=False,
    )


def _evaluation() -> dict[str, Any]:
    population = build_raw_admission_population([_event(0), _event(150), _event(300)])
    audit = build_pair_admission_audit(population.blocks, raw_events=population.events)
    return dict(audit.evaluations[0])


class _Transaction:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, *_: object) -> None:
        return None


class _Connection:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "WHERE evaluation_id = $1" in query:
            return self.rows.get(str(args[0]))
        if "decision = 'GRANTED'" in query:
            deployment_id, raw_block_id, rule_version = map(str, args[:3])
            return next(
                (
                    row
                    for row in self.rows.values()
                    if row["deployment_id"] == deployment_id
                    and row["raw_block_id"] == raw_block_id
                    and row["rule_version"] == rule_version
                    and row["decision"] == "GRANTED"
                ),
                None,
            )
        raise AssertionError(query)

    async def execute(self, query: str, *args: Any) -> str:
        if "pg_advisory_xact_lock" in query:
            return "SELECT 1"
        if "INSERT INTO pair_admission_evaluations" not in query:
            raise AssertionError(query)
        self.rows[str(args[0])] = {
            "evaluation_id": str(args[0]),
            "deployment_id": str(args[1]),
            "raw_block_id": str(args[2]),
            "rule_version": str(args[3]),
            "decision": str(args[15]),
            "admission_event_id": args[17],
            "payload_hash": str(args[18]),
        }
        return "INSERT 0 1"


class _Postgres:
    is_available = True

    def __init__(self) -> None:
        self.connection = _Connection()

    def transaction(self) -> _Transaction:
        return _Transaction(self.connection)


class _SchemaPostgres:
    is_available = True

    def __init__(self, *, complete: bool) -> None:
        self.complete = complete

    async def fetch(self, query: str, *_: Any) -> list[dict[str, str]]:
        if "pg_catalog.pg_tables" in query:
            return [{"tablename": "pair_admission_evaluations"}] if self.complete else []
        if not self.complete:
            return []
        return [
            {"indexname": "ix_pair_admission_evaluated"},
            {"indexname": "ix_pair_admission_symbol_block"},
            {"indexname": "uq_pair_admission_one_grant_per_block"},
        ]


@pytest.mark.asyncio
async def test_repository_persists_grant_once_without_outbox_or_broker_fields() -> None:
    postgres = _Postgres()
    repository = PairAdmissionEvaluationRepository(pg=postgres)  # type: ignore[arg-type]
    evaluation = _evaluation()

    first = await repository.ingest(evaluation)
    replay = await repository.ingest(evaluation)

    assert first.duplicate is False
    assert replay.duplicate is True
    assert len(postgres.connection.rows) == 1
    stored = next(iter(postgres.connection.rows.values()))
    assert stored["decision"] == "GRANTED"
    assert "outbox" not in stored
    assert "broker" not in stored


@pytest.mark.asyncio
async def test_schema_readiness_fails_closed_on_missing_table_or_index() -> None:
    missing = await PairAdmissionEvaluationRepository(
        pg=_SchemaPostgres(complete=False)  # type: ignore[arg-type]
    ).schema_status()
    ready = await PairAdmissionEvaluationRepository(
        pg=_SchemaPostgres(complete=True)  # type: ignore[arg-type]
    ).schema_status()

    assert missing.ready is False
    assert missing.missing_tables == ("pair_admission_evaluations",)
    assert "uq_pair_admission_one_grant_per_block" in missing.missing_indexes
    assert ready.ready is True


def test_pipeline_persists_evaluation_before_any_observability_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    class _Result:
        status = "PERSISTED"
        error = None

    monkeypatch.setattr(
        "storage.pair_admission_evaluations.persist_pair_admission_evaluation_sync",
        lambda evaluation: captured.append(dict(evaluation)) or _Result(),
    )
    report = {
        "pair_admission_summary": {"evaluations": [_evaluation()]},
        "existing_candidate": {"status": "ACTIVE"},
    }

    WolfConstitutionalPipeline._persist_pair_admission_evaluations(report)

    assert captured == [report["pair_admission_summary"]["evaluations"][0]]
    assert report["pair_admission_persistence"] == {
        "evaluations_seen": 1,
        "status_counts": {"PERSISTED": 1},
        "errors": [],
        "persistence_boundary": "INDEPENDENT_PAIR_ADMISSION_LEDGER",
        "observability_route_independent": True,
        "execution_authority": False,
    }


def test_snapshot_persistence_does_not_call_pressure_state_emitter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluation = _evaluation()
    source_report = {"pair_admission_summary": {"evaluations": [evaluation]}}
    captured: list[str] = []

    class _Analyzer:
        def snapshot(self, *, market_contexts: dict[str, Any]) -> dict[str, Any]:
            assert market_contexts == {"EURUSD": {"fresh": True}}
            return source_report

    class _Result:
        status = "PERSISTED"
        error = None

    monkeypatch.setattr(
        "storage.pair_admission_evaluations.persist_pair_admission_evaluation_sync",
        lambda item: captured.append(str(item["evaluation_id"])) or _Result(),
    )
    pipeline = cast(Any, object.__new__(WolfConstitutionalPipeline))
    pipeline._signal_throttle_live_analyzer = _Analyzer()
    pipeline._emit_signal_pressure_state_payload = lambda _payload: pytest.fail(
        "admission persistence must not call the pressure-state emitter"
    )

    report = pipeline._signal_throttle_snapshot(market_contexts={"EURUSD": {"fresh": True}})

    assert report is source_report
    assert captured == [evaluation["evaluation_id"]]


def test_migration_enforces_non_execution_and_one_grant_per_block() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "storage"
        / "migrations"
        / "versions"
        / "20260810_01_pair_admission_evaluations.py"
    ).read_text(encoding="utf-8")

    assert "ck_pair_admission_non_executable" in migration
    assert "uq_pair_admission_one_grant_per_block" in migration
    assert "decision = 'GRANTED'" in migration
    assert "pressure_outbox" not in migration
    assert "execution_commands" not in migration
