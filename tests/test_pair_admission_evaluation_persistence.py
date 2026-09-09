from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

import storage.pair_admission_evaluations as admission_storage
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


def _evaluation_for(seconds: tuple[int, ...]) -> dict[str, Any]:
    population = build_raw_admission_population([_event(second) for second in seconds])
    audit = build_pair_admission_audit(population.blocks, raw_events=population.events)
    return dict(audit.evaluations[0])


def _evaluation() -> dict[str, Any]:
    return _evaluation_for((0, 150, 300))


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
        if "logical_grant_created IS TRUE" in query:
            deployment_id, raw_block_id, rule_version = map(str, args[:3])
            return next(
                (
                    row
                    for row in self.rows.values()
                    if row["deployment_id"] == deployment_id
                    and row["raw_block_id"] == raw_block_id
                    and row["rule_version"] == rule_version
                    and row["logical_grant_created"] is True
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
            "logical_grant_created": bool(args[18]),
            "payload_hash": str(args[19]),
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

    def __init__(
        self,
        *,
        complete: bool,
        missing_constraint: str | None = None,
        wrong_constraint: bool = False,
        wrong_index: bool = False,
        wrong_column: bool = False,
        broadened_constraint: bool = False,
        broadened_index: bool = False,
        inverted_default: bool = False,
    ) -> None:
        self.complete = complete
        self.missing_constraint = missing_constraint
        self.wrong_constraint = wrong_constraint
        self.wrong_index = wrong_index
        self.wrong_column = wrong_column
        self.broadened_constraint = broadened_constraint
        self.broadened_index = broadened_index
        self.inverted_default = inverted_default

    async def fetch(self, query: str, *_: Any) -> list[dict[str, Any]]:
        if "pg_catalog.pg_tables" in query:
            return [{"tablename": "pair_admission_evaluations"}] if self.complete else []
        if not self.complete:
            return []
        if "information_schema.columns" in query:
            defaults = {
                "cross_symbol_interruption_count": "0",
                "logical_grant_created": "false",
                "execution_authority": "false",
                "created_at": "now()",
            }
            rows = [
                {
                    "column_name": name,
                    "data_type": contract.data_type,
                    "is_nullable": "YES" if contract.nullable else "NO",
                    "column_default": defaults.get(name),
                    "character_maximum_length": contract.max_length,
                }
                for name, contract in admission_storage._REQUIRED_COLUMNS.items()
            ]
            if self.wrong_column:
                next(row for row in rows if row["column_name"] == "execution_authority")["column_default"] = "true"
            if self.inverted_default:
                next(row for row in rows if row["column_name"] == "execution_authority")["column_default"] = (
                    "(NOT FALSE)"
                )
            return rows
        if "pg_catalog.pg_constraint" in query:
            rows = [
                {
                    "conname": name,
                    "contype": "c",
                    "table_name": "pair_admission_evaluations",
                    "definition": admission_storage._REQUIRED_CONSTRAINT_DEFINITIONS[name],
                }
                for name in admission_storage._REQUIRED_CONSTRAINTS
                if name != self.missing_constraint
            ]
            if self.wrong_constraint:
                next(row for row in rows if row["conname"] == "ck_pair_admission_non_executable")["definition"] = (
                    "CHECK (execution_authority IS NOT NULL)"
                )
            if self.broadened_constraint:
                next(row for row in rows if row["conname"] == "ck_pair_admission_non_executable")["definition"] = (
                    "CHECK ((execution_authority IS FALSE) OR TRUE)"
                )
            return rows
        if "pg_catalog.pg_index" in query:
            rows = [
                {
                    "indexname": name,
                    "indisunique": unique,
                    "columns": list(columns),
                    "predicate": predicate,
                }
                for name, (unique, columns, predicate) in admission_storage._REQUIRED_INDEXES.items()
            ]
            if self.wrong_index:
                next(row for row in rows if row["indexname"] == "uq_pair_admission_one_grant_per_block")[
                    "predicate"
                ] = "logical_grant_created IS FALSE"
            if self.broadened_index:
                next(row for row in rows if row["indexname"] == "uq_pair_admission_one_grant_per_block")[
                    "predicate"
                ] = "logical_grant_created IS TRUE OR TRUE"
            return rows
        raise AssertionError(query)


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
async def test_growing_granted_block_appends_snapshot_without_a_second_logical_grant() -> None:
    postgres = _Postgres()
    repository = PairAdmissionEvaluationRepository(pg=postgres)  # type: ignore[arg-type]
    first_evaluation = _evaluation_for((0, 150, 300))
    growing_evaluation = _evaluation_for((0, 150, 300, 350, 500, 650))

    first = await repository.ingest(first_evaluation)
    growing = await repository.ingest(growing_evaluation)

    assert first.duplicate is False
    assert growing.duplicate is False
    assert first_evaluation["pair_admission_id"] == growing_evaluation["pair_admission_id"]
    assert (
        first_evaluation["pair_admission_source_ledger_hash"] == growing_evaluation["pair_admission_source_ledger_hash"]
    )
    assert len(postgres.connection.rows) == 2
    assert sum(bool(row["logical_grant_created"]) for row in postgres.connection.rows.values()) == 1


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("postgres", "dimension"),
    [
        (
            _SchemaPostgres(complete=True, missing_constraint="ck_pair_admission_non_executable"),
            "missing_constraints",
        ),
        (_SchemaPostgres(complete=True, wrong_constraint=True), "invalid_constraints"),
        (_SchemaPostgres(complete=True, wrong_index=True), "invalid_indexes"),
        (_SchemaPostgres(complete=True, wrong_column=True), "invalid_columns"),
        (_SchemaPostgres(complete=True, broadened_constraint=True), "invalid_constraints"),
        (_SchemaPostgres(complete=True, broadened_index=True), "invalid_indexes"),
        (_SchemaPostgres(complete=True, inverted_default=True), "invalid_columns"),
    ],
)
async def test_schema_readiness_fails_closed_on_contract_drift(
    postgres: _SchemaPostgres,
    dimension: str,
) -> None:
    status = await PairAdmissionEvaluationRepository(pg=postgres).schema_status()  # type: ignore[arg-type]

    assert status.ready is False
    assert getattr(status, dimension)


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


def test_migrations_enforce_non_execution_and_separate_snapshot_from_grant() -> None:
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

    hotfix_migration = (
        Path(__file__).resolve().parents[1]
        / "storage"
        / "migrations"
        / "versions"
        / "20260810_02_pair_admission_snapshot_grants.py"
    ).read_text(encoding="utf-8")

    assert "logical_grant_created" in hotfix_migration
    assert "logical_grant_created IS TRUE" in hotfix_migration
    assert "pressure_outbox" not in hotfix_migration
    assert "execution_commands" not in hotfix_migration
