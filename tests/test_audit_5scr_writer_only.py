from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from scripts import audit_5scr_writer_only as audit


def _metadata() -> audit.AuditMetadata:
    watermark = datetime(2026, 8, 4, tzinfo=UTC)
    return audit.AuditMetadata(
        main_commit="f422a3b7e2c7482c135c6b744ac5ed4408cc831c",
        alembic_revision="20260804_01",
        writer_deployment_id="deployment-1",
        writer_commit_sha="f422a3b7e2c7482c135c6b744ac5ed4408cc831c",
        writer_enabled_at_utc=watermark,
        minimum_admission_time_utc=watermark,
    )


def _metrics(*, eligible: int = 0) -> dict[str, int | float | None]:
    values: dict[str, int | float | None] = {
        "eligible_delivered_admission_count": eligible,
        "admission_link_count": eligible,
        "evidence_job_count": eligible,
        "active_lifecycle_count": eligible,
        "legacy_to_v2_lifecycle_ratio": None if eligible == 0 else 1.0,
        "events_per_v2_lifecycle": None if eligible == 0 else 1.0,
        "clean_blocks_per_v2_lifecycle": None if eligible == 0 else 1.0,
        "comparison_difference_with_reason_count": 0,
        "risk_reservation_row_count": 0,
        "final_signal_outbox_row_count": 0,
        "execution_command_row_count": 0,
        "execution_report_row_count": 0,
        "broker_order_row_count": 0,
        "broker_deal_row_count": 0,
        "broker_position_row_count": 0,
    }
    values.update({field: 0 for field in audit._ZERO_GATES})
    return values


def _capture(phase: str) -> dict[str, Any]:
    return {
        "schema_version": audit.CAPTURE_SCHEMA_VERSION,
        "phase": phase,
        "metadata": _metadata().as_dict(),
        "capture": {
            "strategy_lifecycle_id": "5scr-lifecycle:" + "a" * 32,
            "admission_event_id": "5scr-admission:" + "b" * 32,
            "pressure_event_id": "event-1",
            "raw_lineage_hash": "sha256:" + "c" * 64,
            "evidence_job_id": "5scr-evidence-job-v2:" + "d" * 32,
            "decision_time": None,
            "material_state_hash": "e" * 64,
            "context_hash": None,
            "evidence_hash": None,
        },
        "execution_plane": {field: 0 for field in audit._EXECUTION_FIELDS},
    }


def test_versioned_sql_files_are_read_only() -> None:
    for filename in (
        "5scr_writer_only_snapshot.sql",
        "5scr_restart_before.sql",
        "5scr_restart_after.sql",
        "5scr_restart_compare.sql",
    ):
        sql = audit.load_read_only_sql(filename)
        assert sql
        assert not audit._WRITE_SQL.search(audit._strip_sql_comments(sql))


def test_operator_manifest_round_trips_cutover_metadata(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        audit.json.dumps(
            {
                "schema_version": audit.MANIFEST_SCHEMA_VERSION,
                **_metadata().as_dict(),
            }
        ),
        encoding="utf-8",
    )
    metadata = audit._metadata_from_args(argparse.Namespace(manifest=manifest))
    assert metadata == _metadata()


def test_asyncpg_style_record_uses_column_keys_not_iteration_values() -> None:
    class Record:
        def __init__(self) -> None:
            self._data = {"eligible_delivered_admission_count": 0}

        def keys(self) -> list[str]:
            return list(self._data)

        def __getitem__(self, key: str) -> object:
            return self._data[key]

        def __iter__(self) -> Any:
            return iter(self._data.values())

    assert audit._record(Record()) == {"eligible_delivered_admission_count": 0}


def test_empty_clean_snapshot_is_no_opportunity() -> None:
    report = audit.build_snapshot_report(_metrics(), _metadata())
    assert report["status"] == "NO_OPPORTUNITY"
    assert report["failed_gates"] == []
    assert report["authority_granted"] is False


def test_observed_clean_snapshot_passes() -> None:
    report = audit.build_snapshot_report(_metrics(eligible=1), _metadata())
    assert report["status"] == "PASS"
    assert report["gates"]["admission_funnel_equality"]["passed"] is True


def test_authority_violation_fails_closed() -> None:
    metrics = _metrics(eligible=1)
    metrics["execution_authority_true_count"] = 1
    report = audit.build_snapshot_report(metrics, _metadata())
    assert report["status"] == "FAIL"
    assert report["failed_gates"] == ["execution_authority_true_count"]


def test_restart_comparison_passes_when_identity_and_plane_are_stable() -> None:
    result = audit.compare_restart_captures(_capture("before"), _capture("after"))
    assert result["status"] == "PASS"
    assert result["identity_drift_fields"] == []
    assert all(delta == 0 for delta in result["execution_plane_deltas"].values())


def test_restart_comparison_reports_identity_and_independent_plane_drift() -> None:
    before = _capture("before")
    after = _capture("after")
    after["capture"]["material_state_hash"] = "f" * 64
    after["execution_plane"]["execution_command_row_count"] = 1
    result = audit.compare_restart_captures(before, after)
    assert result["status"] == "FAIL"
    assert result["identity_drift_fields"] == ["material_state_hash"]
    assert result["execution_plane_deltas"]["execution_command_row_count"] == 1
    assert result["execution_plane_drift_fields"] == ["execution_command_row_count"]


@pytest.mark.asyncio
async def test_database_capture_sets_repeatable_read_only_before_select(monkeypatch: pytest.MonkeyPatch) -> None:
    class Connection:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def execute(self, sql: str) -> None:
            self.calls.append(("execute", sql))

        async def fetchrow(self, sql: str, *_arguments: object) -> Any:
            self.calls.append(("fetchrow", sql))
            return _metrics()

    connection = Connection()

    class Database:
        @asynccontextmanager
        async def transaction(self) -> AsyncIterator[Any]:
            yield connection

    monkeypatch.setattr(audit, "pg_client", Database())
    metrics, capture = await audit._read_snapshot_and_capture(
        minimum_admission_time=datetime(2026, 8, 4, tzinfo=UTC),
    )
    assert capture is None
    assert metrics["eligible_delivered_admission_count"] == 0
    assert connection.calls[0] == (
        "execute",
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
    )
    assert connection.calls[1][0] == "fetchrow"


def test_compare_cli_writes_deterministic_json(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    output = tmp_path / "comparison.json"
    before.write_text(audit.json.dumps(_capture("before")), encoding="utf-8")
    after.write_text(audit.json.dumps(_capture("after")), encoding="utf-8")
    assert (
        audit.main(
            [
                "compare",
                "--before",
                str(before),
                "--after",
                str(after),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert audit.json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
