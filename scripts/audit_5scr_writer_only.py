"""Read-only Lifecycle V2 writer snapshot and restart-parity auditor."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from storage.postgres_client import pg_client

SCHEMA_VERSION = "wolf15.5scr.writer-only-audit.v1"
CAPTURE_SCHEMA_VERSION = "wolf15.5scr.writer-restart-capture.v1"
COMPARISON_SCHEMA_VERSION = "wolf15.5scr.writer-restart-comparison.v1"
MANIFEST_SCHEMA_VERSION = "wolf15.5scr.writer-only-operator-manifest.v1"
QUERY_VERSION = "WOLF15_5SCR_WRITER_ONLY_SNAPSHOT_V1"

_ROOT = Path(__file__).resolve().parents[1]
_SQL_DIR = _ROOT / "sql" / "observability"
_ADMISSION_ID = re.compile(r"^5scr-admission:[0-9a-f]{32}$")
_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_WRITE_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|ALTER|DROP|CREATE|TRUNCATE|GRANT|REVOKE|CALL|COPY)\b",
    re.IGNORECASE,
)
_RESTART_FIELDS = (
    "strategy_lifecycle_id",
    "admission_event_id",
    "pressure_event_id",
    "raw_lineage_hash",
    "evidence_job_id",
    "decision_time",
    "material_state_hash",
    "context_hash",
    "evidence_hash",
)
_EXECUTION_FIELDS = (
    "risk_reservation_row_count",
    "final_signal_outbox_row_count",
    "execution_command_row_count",
    "execution_report_row_count",
    "broker_order_row_count",
    "broker_deal_row_count",
    "broker_position_row_count",
)
_ZERO_GATES = (
    "unlinked_eligible_admission_count",
    "orphan_admission_count",
    "duplicate_admission_row_count",
    "duplicate_logical_job_row_count",
    "completed_job_without_snapshot_count",
    "forming_candle_used_count",
    "future_candle_used_count",
    "unexplained_comparison_difference_count",
    "valid_for_execution_true_count",
    "execution_authority_true_count",
)


class WriterOnlyAuditError(RuntimeError):
    """Fail-closed audit error with a stable public reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class AuditMetadata:
    main_commit: str
    alembic_revision: str
    writer_deployment_id: str
    writer_commit_sha: str
    writer_enabled_at_utc: datetime
    minimum_admission_time_utc: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "main_commit": self.main_commit,
            "alembic_revision": self.alembic_revision,
            "writer_deployment_id": self.writer_deployment_id,
            "writer_commit_sha": self.writer_commit_sha,
            "writer_enabled_at_utc": self.writer_enabled_at_utc.isoformat(),
            "minimum_admission_time_utc": self.minimum_admission_time_utc.isoformat(),
            "query_version": QUERY_VERSION,
        }


def _utc_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines()).strip()


def load_read_only_sql(filename: str) -> str:
    path = (_SQL_DIR / filename).resolve()
    if path.parent != _SQL_DIR.resolve():
        raise WriterOnlyAuditError("AUDIT_SQL_PATH_INVALID")
    try:
        sql = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise WriterOnlyAuditError("AUDIT_SQL_MISSING") from exc
    executable = _strip_sql_comments(sql)
    if not executable or not executable.upper().startswith(("SELECT", "WITH")):
        raise WriterOnlyAuditError("AUDIT_SQL_NOT_SELECT")
    if _WRITE_SQL.search(executable):
        raise WriterOnlyAuditError("AUDIT_SQL_WRITE_FORBIDDEN")
    if executable.rstrip(";").find(";") >= 0:
        raise WriterOnlyAuditError("AUDIT_SQL_MULTISTATEMENT_FORBIDDEN")
    return sql


def _normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, (UUID, Path)):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def _record(value: Any | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    try:
        keys = value.keys()
        return {str(key): _normalize(value[key]) for key in keys}
    except (AttributeError, KeyError, TypeError) as exc:
        raise WriterOnlyAuditError("AUDIT_DATABASE_ROW_INVALID") from exc


def build_snapshot_report(metrics: Mapping[str, Any], metadata: AuditMetadata) -> dict[str, Any]:
    normalized = {str(key): _normalize(value) for key, value in metrics.items()}
    gates: dict[str, dict[str, object]] = {}
    for field in _ZERO_GATES:
        observed = int(normalized.get(field, 0) or 0)
        gates[field] = {"observed": observed, "threshold": 0, "passed": observed == 0}

    eligible = int(normalized.get("eligible_delivered_admission_count", 0) or 0)
    links = int(normalized.get("admission_link_count", 0) or 0)
    gates["admission_funnel_equality"] = {
        "observed": {"eligible": eligible, "linked": links},
        "threshold": "eligible == linked",
        "passed": eligible == links,
    }
    failed = sorted(name for name, gate in gates.items() if not bool(gate["passed"]))
    status = "FAIL" if failed else ("NO_OPPORTUNITY" if eligible == 0 else "PASS")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "metadata": metadata.as_dict(),
        "audited_at_utc": datetime.now(UTC).isoformat(),
        "metrics": normalized,
        "gates": gates,
        "failed_gates": failed,
        "not_measurable_yet": [
            "price_coverage_from_block_start_pct",
            "session_aware_waiting_evidence_age_seconds",
        ],
        "authority_granted": False,
    }


def compare_restart_captures(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    if before.get("schema_version") != CAPTURE_SCHEMA_VERSION or after.get("schema_version") != CAPTURE_SCHEMA_VERSION:
        raise WriterOnlyAuditError("RESTART_CAPTURE_SCHEMA_INVALID")
    if before.get("phase") != "before" or after.get("phase") != "after":
        raise WriterOnlyAuditError("RESTART_CAPTURE_PHASE_INVALID")

    before_meta = before.get("metadata")
    after_meta = after.get("metadata")
    if not isinstance(before_meta, Mapping) or not isinstance(after_meta, Mapping):
        raise WriterOnlyAuditError("RESTART_CAPTURE_METADATA_INVALID")
    stable_metadata = (
        "main_commit",
        "alembic_revision",
        "writer_deployment_id",
        "writer_commit_sha",
        "minimum_admission_time_utc",
        "query_version",
    )
    metadata_drift = [field for field in stable_metadata if before_meta.get(field) != after_meta.get(field)]

    before_capture = before.get("capture")
    after_capture = after.get("capture")
    if not isinstance(before_capture, Mapping) or not isinstance(after_capture, Mapping):
        raise WriterOnlyAuditError("RESTART_CAPTURE_PAYLOAD_INVALID")
    identity_drift = [field for field in _RESTART_FIELDS if before_capture.get(field) != after_capture.get(field)]

    before_execution = before.get("execution_plane")
    after_execution = after.get("execution_plane")
    if not isinstance(before_execution, Mapping) or not isinstance(after_execution, Mapping):
        raise WriterOnlyAuditError("RESTART_EXECUTION_SNAPSHOT_INVALID")
    execution_deltas = {
        field: int(after_execution.get(field, 0) or 0) - int(before_execution.get(field, 0) or 0)
        for field in _EXECUTION_FIELDS
    }
    execution_drift = [field for field, delta in execution_deltas.items() if delta != 0]
    status = "PASS" if not (metadata_drift or identity_drift or execution_drift) else "FAIL"
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "status": status,
        "admission_event_id": before_capture.get("admission_event_id"),
        "metadata_drift_fields": metadata_drift,
        "identity_drift_fields": identity_drift,
        "execution_plane_deltas": execution_deltas,
        "execution_plane_drift_fields": execution_drift,
        "compared_at_utc": datetime.now(UTC).isoformat(),
        "authority_granted": False,
    }


async def _read_snapshot_and_capture(
    *,
    minimum_admission_time: datetime,
    capture_phase: str | None = None,
    admission_event_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    snapshot_sql = load_read_only_sql("5scr_writer_only_snapshot.sql")
    capture_sql = None if capture_phase is None else load_read_only_sql(f"5scr_restart_{capture_phase}.sql")
    async with pg_client.transaction() as connection:
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        metrics = _record(await connection.fetchrow(snapshot_sql, minimum_admission_time))
        if metrics is None:
            raise WriterOnlyAuditError("AUDIT_SNAPSHOT_EMPTY")
        capture = None
        if capture_sql is not None:
            capture = _record(
                await connection.fetchrow(
                    capture_sql,
                    admission_event_id,
                    minimum_admission_time,
                )
            )
        return metrics, capture


def _metadata_from_args(args: argparse.Namespace) -> AuditMetadata:
    payload = _load_json(args.manifest)
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise WriterOnlyAuditError("AUDIT_MANIFEST_SCHEMA_INVALID")
    required = (
        "main_commit",
        "alembic_revision",
        "writer_deployment_id",
        "writer_commit_sha",
        "writer_enabled_at_utc",
        "minimum_admission_time_utc",
    )
    if any(not isinstance(payload.get(field), str) or not str(payload[field]).strip() for field in required):
        raise WriterOnlyAuditError("AUDIT_MANIFEST_FIELD_MISSING")
    main_commit = str(payload["main_commit"])
    writer_commit_sha = str(payload["writer_commit_sha"])
    if not _COMMIT.fullmatch(main_commit) or not _COMMIT.fullmatch(writer_commit_sha):
        raise WriterOnlyAuditError("AUDIT_COMMIT_SHA_INVALID")
    try:
        writer_enabled_at = _utc_timestamp(str(payload["writer_enabled_at_utc"]))
        minimum_admission_time = _utc_timestamp(str(payload["minimum_admission_time_utc"]))
    except argparse.ArgumentTypeError as exc:
        raise WriterOnlyAuditError("AUDIT_MANIFEST_TIMESTAMP_INVALID") from exc
    if minimum_admission_time < writer_enabled_at:
        raise WriterOnlyAuditError("AUDIT_WATERMARK_PRECEDES_WRITER")
    return AuditMetadata(
        main_commit=main_commit,
        alembic_revision=str(payload["alembic_revision"]),
        writer_deployment_id=str(payload["writer_deployment_id"]),
        writer_commit_sha=writer_commit_sha,
        writer_enabled_at_utc=writer_enabled_at,
        minimum_admission_time_utc=minimum_admission_time,
    )


async def audit_database(args: argparse.Namespace) -> dict[str, Any]:
    metadata = _metadata_from_args(args)
    await pg_client.initialize()
    try:
        if not pg_client.is_available:
            raise WriterOnlyAuditError("AUDIT_DATABASE_UNAVAILABLE")
        phase = getattr(args, "phase", None)
        admission_event_id = getattr(args, "admission_event_id", None)
        metrics, capture = await _read_snapshot_and_capture(
            minimum_admission_time=metadata.minimum_admission_time_utc,
            capture_phase=phase,
            admission_event_id=admission_event_id,
        )
        snapshot = build_snapshot_report(metrics, metadata)
        if phase is None:
            return snapshot
        if snapshot["status"] == "FAIL":
            raise WriterOnlyAuditError("AUDIT_SNAPSHOT_GATE_FAILED")
        if capture is None:
            raise WriterOnlyAuditError("RESTART_ADMISSION_NOT_FOUND")
        return {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "phase": phase,
            "metadata": metadata.as_dict(),
            "captured_at_utc": datetime.now(UTC).isoformat(),
            "snapshot_status": snapshot["status"],
            "capture": capture,
            "execution_plane": {field: metrics.get(field, 0) for field in _EXECUTION_FIELDS},
            "authority_granted": False,
        }
    finally:
        await pg_client.close()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WriterOnlyAuditError("AUDIT_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise WriterOnlyAuditError("AUDIT_JSON_INVALID")
    return value


def _write_result(result: Mapping[str, object], output: Path | None) -> None:
    body = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if output is None:
        print(body, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(body, encoding="utf-8")
    temporary.replace(output)


def _add_database_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot", help="capture writer-only KPI state")
    _add_database_args(snapshot)
    capture = commands.add_parser("capture", help="capture one admission before or after restart")
    _add_database_args(capture)
    capture.add_argument("--phase", choices=("before", "after"), required=True)
    capture.add_argument("--admission-event-id", required=True)
    compare = commands.add_parser("compare", help="compare two local restart captures")
    compare.add_argument("--before", type=Path, required=True)
    compare.add_argument("--after", type=Path, required=True)
    compare.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "compare":
            result = compare_restart_captures(_load_json(args.before), _load_json(args.after))
        else:
            if args.command == "capture" and not _ADMISSION_ID.fullmatch(args.admission_event_id):
                raise WriterOnlyAuditError("RESTART_ADMISSION_ID_INVALID")
            result = asyncio.run(audit_database(args))
        _write_result(result, args.output)
        return 0 if result.get("status", result.get("snapshot_status")) != "FAIL" else 1
    except Exception as exc:
        reason_code = str(getattr(exc, "reason_code", type(exc).__name__))
        print(json.dumps({"status": "FAIL", "reason_code": reason_code}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
