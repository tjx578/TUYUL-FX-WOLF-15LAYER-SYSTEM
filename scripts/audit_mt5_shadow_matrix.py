"""Read-only audit of an operator-issued MT5 SHADOW acceptance matrix.

This module deliberately has no command construction, signing, or enqueue
capability.  An audited operator session may issue SHADOW commands and export a
manifest; this auditor then proves database and executor outcomes without
gaining execution authority itself.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast
from uuid import UUID

from contracts.mt5_execution_protocol import PROTOCOL_VERSION, SIGNED_WIRE_VERSION, ExecutorMode

MANIFEST_VERSION: Final = "wolf15.mt5.shadow-acceptance-manifest.v1"
REQUIRED_UNIVERSE: Final = "WOLF15_XM_30_V1"
EXPECTED_EA_VERSION: Final = "0.22-shadow-acceptance-v1"
REQUIRED_OPERATOR_AUTHORITY: Final = "WOLF15_SHADOW_ACCEPTANCE_OPERATOR_V1"
REQUIRED_PURPOSE: Final = "BROKER_CONNECTED_SHADOW_VALIDATION"
EXPECTED_SYMBOL_COUNT: Final = 30
DEFAULT_HEARTBEAT_MAX_AGE_SECONDS: Final = 30.0
DEFAULT_SNAPSHOT_MAX_AGE_SECONDS: Final = 30.0
ACCEPTANCE_REJECTION_REASONS: Final = frozenset(
    {
        "PROTOCOL_MISMATCH",
        "SHADOW_ONLY_BUILD",
        "SHADOW_ACCEPTANCE_AUTHORITY_REJECTED",
        "SHADOW_ACCEPTANCE_LINEAGE_REJECTED",
        "SHADOW_ACCEPTANCE_GUARD_REJECTED",
        "ACCOUNT_BINDING_MISMATCH",
        "SHADOW_ACCEPTANCE_A1_SYMBOL_REJECTED",
        "SYMBOL_BINDING_MISMATCH",
        "SYMBOL_RUNTIME_NOT_READY",
        "IDEMPOTENCY_KEY_UNSAFE",
        "SHADOW_ACCEPTANCE_EXPIRED",
        "SHADOW_ACCEPTANCE_ACTION_REJECTED",
    }
)
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
_ROOT = Path(__file__).resolve().parents[1]
_BROKER_MAP = _ROOT / "ea_interface" / "wolf15_executor" / "broker_maps" / "xmglobal-mt5-10.csv"


class MatrixAbortError(RuntimeError):
    """Fail-closed matrix audit failure with a stable reason code."""

    def __init__(self, stage: str, detail: str, *, code: str) -> None:
        super().__init__(detail)
        self.stage = stage
        self.detail = detail
        self.reason_code = code


@dataclass(frozen=True)
class ManifestCommand:
    canonical_symbol: str
    broker_symbol: str
    command_id: UUID


@dataclass(frozen=True)
class MatrixManifest:
    schema_version: str
    acceptance_run_id: str
    operator_authority: str
    purpose: str
    phase: str
    symbol_universe: str
    executor_id: UUID
    broker_server: str
    expected_ea_version: str
    expected_protocol_version: str
    started_at_utc: datetime
    expires_at_utc: datetime
    commands: tuple[ManifestCommand, ...]


@dataclass
class SymbolAudit:
    canonical_symbol: str
    broker_symbol: str
    command_id: str
    command_state: str = "UNKNOWN"
    report_state: str | None = None
    report_count: int = 0
    filled_volume: float | None = None
    broker_order_id: object | None = None
    broker_deal_id: object | None = None
    broker_position_id: object | None = None
    outcome: str = "PENDING"


@dataclass
class AuditSummary:
    run_id: str
    phase: str
    universe: str
    status: str = "ABORTED"
    symbols_planned: int = 0
    symbols_verified: int = 0
    execution_mode: str | None = None
    kill_switch_active: bool | None = None
    ea_version: str | None = None
    protocol_version: str | None = None
    baseline_open_positions: int | None = None
    final_open_positions: int | None = None
    active_commands_before: int | None = None
    active_commands_after: int | None = None
    unexpected_reports: int = 0
    broker_entities: int = 0
    aggregate_filled_volume: float = 0.0
    failure_stage: str | None = None
    reason_code: str | None = None
    failure_detail: str | None = None
    started_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at_utc: str | None = None
    records: list[dict[str, Any]] = field(default_factory=list)


def load_symbol_universe(path: Path = _BROKER_MAP) -> tuple[tuple[str, str], ...]:
    """Load and validate the frozen canonical-to-broker map."""

    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = tuple(
                (str(row.get("canonical_symbol", "")).strip(), str(row.get("broker_symbol", "")).strip())
                for row in csv.DictReader(handle)
            )
    except OSError as exc:
        raise MatrixAbortError("CONFIG", f"broker map cannot be read: {exc}", code="BROKER_MAP_UNREADABLE") from exc
    if len(rows) != EXPECTED_SYMBOL_COUNT:
        raise MatrixAbortError(
            "CONFIG",
            f"broker map has {len(rows)} rows, expected {EXPECTED_SYMBOL_COUNT}",
            code="BROKER_MAP_COUNT_MISMATCH",
        )
    if any(not canonical or not broker for canonical, broker in rows):
        raise MatrixAbortError("CONFIG", "broker map contains a blank symbol", code="BROKER_MAP_BLANK_SYMBOL")
    if len({canonical for canonical, _ in rows}) != EXPECTED_SYMBOL_COUNT:
        raise MatrixAbortError("CONFIG", "canonical symbols are not unique", code="BROKER_MAP_CANONICAL_DUPLICATE")
    if len({broker for _, broker in rows}) != EXPECTED_SYMBOL_COUNT:
        raise MatrixAbortError("CONFIG", "broker symbols are not unique", code="BROKER_MAP_BROKER_DUPLICATE")
    return rows


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MatrixAbortError("MANIFEST", f"{field_name} must be an object", code="MANIFEST_TYPE_INVALID")
    return cast(dict[str, Any], value)


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MatrixAbortError("MANIFEST", f"{field_name} must be a non-empty string", code="MANIFEST_FIELD_INVALID")
    return value.strip()


def _utc_datetime(value: object, field_name: str) -> datetime:
    raw = _required_string(value, field_name)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MatrixAbortError("MANIFEST", f"{field_name} is not ISO-8601", code="MANIFEST_TIME_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MatrixAbortError("MANIFEST", f"{field_name} must include a UTC offset", code="MANIFEST_TIME_NOT_UTC")
    return parsed.astimezone(UTC)


def _exact_keys(payload: dict[str, Any], expected: frozenset[str], field_name: str) -> None:
    actual = frozenset(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise MatrixAbortError(
            "MANIFEST",
            f"{field_name} keys mismatch missing={missing} extra={extra}",
            code="MANIFEST_KEYS_INVALID",
        )


def load_manifest(path: Path, pairs: tuple[tuple[str, str], ...] | None = None) -> MatrixManifest:
    """Load a strict manifest that contains identities, never credentials."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatrixAbortError("MANIFEST", f"manifest cannot be read: {exc}", code="MANIFEST_UNREADABLE") from exc
    payload = _mapping(raw, "manifest")
    _exact_keys(
        payload,
        frozenset(
            {
                "schema_version",
                "acceptance_run_id",
                "operator_authority",
                "purpose",
                "phase",
                "symbol_universe",
                "executor_id",
                "broker_server",
                "expected_ea_version",
                "expected_protocol_version",
                "started_at_utc",
                "expires_at_utc",
                "commands",
            }
        ),
        "manifest",
    )
    schema_version = _required_string(payload["schema_version"], "schema_version")
    if schema_version != MANIFEST_VERSION:
        raise MatrixAbortError("MANIFEST", "manifest schema is unsupported", code="MANIFEST_VERSION_MISMATCH")
    run_id = _required_string(payload["acceptance_run_id"], "acceptance_run_id")
    if _RUN_ID.fullmatch(run_id) is None:
        raise MatrixAbortError("MANIFEST", "run_id has an unsafe shape", code="RUN_ID_INVALID")
    operator_authority = _required_string(payload["operator_authority"], "operator_authority")
    if operator_authority != REQUIRED_OPERATOR_AUTHORITY:
        raise MatrixAbortError("MANIFEST", "operator authority is not accepted", code="AUTHORITY_MISMATCH")
    purpose = _required_string(payload["purpose"], "purpose")
    if purpose != REQUIRED_PURPOSE:
        raise MatrixAbortError("MANIFEST", "acceptance purpose is not accepted", code="PURPOSE_MISMATCH")
    phase = _required_string(payload["phase"], "phase").upper()
    if phase not in {"A1", "A2"}:
        raise MatrixAbortError("MANIFEST", "phase must be A1 or A2", code="PHASE_INVALID")
    universe = _required_string(payload["symbol_universe"], "symbol_universe")
    if universe != REQUIRED_UNIVERSE:
        raise MatrixAbortError("MANIFEST", "symbol universe is not the frozen XM30 universe", code="UNIVERSE_MISMATCH")
    try:
        executor_id = UUID(_required_string(payload["executor_id"], "executor_id"))
    except ValueError as exc:
        raise MatrixAbortError("MANIFEST", "executor_id is not a UUID", code="EXECUTOR_ID_INVALID") from exc
    commands_raw = payload["commands"]
    if not isinstance(commands_raw, list):
        raise MatrixAbortError("MANIFEST", "commands must be a list", code="MANIFEST_COMMANDS_INVALID")
    commands: list[ManifestCommand] = []
    for index, item in enumerate(commands_raw):
        command = _mapping(item, f"commands[{index}]")
        _exact_keys(command, frozenset({"canonical_symbol", "broker_symbol", "command_id"}), f"commands[{index}]")
        try:
            command_id = UUID(_required_string(command["command_id"], f"commands[{index}].command_id"))
        except ValueError as exc:
            raise MatrixAbortError("MANIFEST", "command_id is not a UUID", code="COMMAND_ID_INVALID") from exc
        commands.append(
            ManifestCommand(
                canonical_symbol=_required_string(command["canonical_symbol"], "canonical_symbol"),
                broker_symbol=_required_string(command["broker_symbol"], "broker_symbol"),
                command_id=command_id,
            )
        )
    expected_count = 1 if phase == "A1" else EXPECTED_SYMBOL_COUNT
    if len(commands) != expected_count:
        raise MatrixAbortError(
            "MANIFEST", f"phase {phase} requires {expected_count} commands", code="MANIFEST_COMMAND_COUNT_MISMATCH"
        )
    if len({command.command_id for command in commands}) != len(commands):
        raise MatrixAbortError("MANIFEST", "command ids are not unique", code="COMMAND_ID_DUPLICATE")
    if len({command.canonical_symbol for command in commands}) != len(commands):
        raise MatrixAbortError("MANIFEST", "canonical symbols are not unique", code="CANONICAL_SYMBOL_DUPLICATE")
    universe_pairs = pairs or load_symbol_universe()
    allowed = set(universe_pairs)
    actual = {(command.canonical_symbol, command.broker_symbol) for command in commands}
    eurusd = {pair for pair in allowed if pair[0] == "EURUSD"}
    if (phase == "A1" and actual != eurusd) or (phase == "A2" and actual != allowed):
        raise MatrixAbortError("MANIFEST", "manifest pairs do not match the audited map", code="SYMBOL_PAIR_MISMATCH")
    started_at = _utc_datetime(payload["started_at_utc"], "started_at_utc")
    expires_at = _utc_datetime(payload["expires_at_utc"], "expires_at_utc")
    if expires_at <= started_at or (expires_at - started_at).total_seconds() > 900:
        raise MatrixAbortError("MANIFEST", "acceptance validity window is invalid", code="ACCEPTANCE_WINDOW_INVALID")
    return MatrixManifest(
        schema_version=schema_version,
        acceptance_run_id=run_id,
        operator_authority=operator_authority,
        purpose=purpose,
        phase=phase,
        symbol_universe=universe,
        executor_id=executor_id,
        broker_server=_required_string(payload["broker_server"], "broker_server"),
        expected_ea_version=_required_string(payload["expected_ea_version"], "expected_ea_version"),
        expected_protocol_version=_required_string(payload["expected_protocol_version"], "expected_protocol_version"),
        started_at_utc=started_at,
        expires_at_utc=expires_at,
        commands=tuple(commands),
    )


def _aware_utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MatrixAbortError("PREFLIGHT", f"{field_name} is absent or timezone-naive", code="RUNTIME_TIME_INVALID")
    return value.astimezone(UTC)


def _age_seconds(value: object, field_name: str) -> float:
    return (datetime.now(UTC) - _aware_utc(value, field_name)).total_seconds()


def _json_object(value: object, field_name: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise MatrixAbortError("AUDIT", f"{field_name} is invalid JSON", code="DATABASE_JSON_INVALID") from exc
    return _mapping(value, field_name)


async def _wait_for_terminal(
    repository: Any,
    *,
    executor_id: UUID,
    command_id: UUID,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    from execution.mt5_command_repository import CommandNotFoundError  # noqa: PLC0415

    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            status = cast(
                dict[str, Any],
                await repository.command_status(executor_id=executor_id, command_id=command_id),
            )
        except CommandNotFoundError as exc:
            raise MatrixAbortError(
                "COMMAND_AUDIT", f"manifest command {command_id} is missing", code="COMMAND_MISSING"
            ) from exc
        if bool(status.get("terminal")):
            return status
        if time.monotonic() >= deadline:
            raise MatrixAbortError(
                "BARRIER", f"command {command_id} did not terminalize", code="COMMAND_BARRIER_TIMEOUT"
            )
        await asyncio.sleep(poll_seconds)


async def audit_manifest(
    manifest: MatrixManifest,
    *,
    heartbeat_max_age_seconds: float = DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
    snapshot_max_age_seconds: float = DEFAULT_SNAPSHOT_MAX_AGE_SECONDS,
    barrier_timeout_seconds: float = 180.0,
    barrier_poll_seconds: float = 0.5,
) -> AuditSummary:
    """Audit a matrix using SELECT-only database operations."""

    from execution.mt5_command_repository import MT5CommandRepository  # noqa: PLC0415
    from storage.postgres_client import pg_client  # noqa: PLC0415

    summary = AuditSummary(
        run_id=manifest.acceptance_run_id,
        phase=manifest.phase,
        universe=manifest.symbol_universe,
        symbols_planned=len(manifest.commands),
    )
    command_ids = {str(command.command_id) for command in manifest.commands}
    await pg_client.initialize()
    try:
        if not pg_client.is_available:
            raise MatrixAbortError("PREFLIGHT", "PostgreSQL is unavailable", code="DATABASE_UNAVAILABLE")
        repository = MT5CommandRepository(pg=pg_client)
        signed_wire = await repository.signed_wire_schema_status()
        if not signed_wire.get("ready"):
            raise MatrixAbortError("PREFLIGHT", "signed-wire schema is not ready", code="SIGNED_WIRE_NOT_READY")
        acceptance_schema = await repository.shadow_acceptance_schema_status()
        if not acceptance_schema.get("ready"):
            raise MatrixAbortError("PREFLIGHT", "acceptance schema is not ready", code="ACCEPTANCE_SCHEMA_NOT_READY")

        executor = await repository.get_executor(manifest.executor_id)
        summary.execution_mode = str(executor["execution_mode"])
        summary.ea_version = str(executor["ea_version"])
        summary.protocol_version = str(executor["protocol_version"])
        if summary.execution_mode != ExecutorMode.SHADOW.value:
            raise MatrixAbortError("PREFLIGHT", "executor is not SHADOW", code="EXECUTOR_MODE_NOT_SHADOW")
        if str(executor["broker_server"]) != manifest.broker_server:
            raise MatrixAbortError("PREFLIGHT", "broker server does not match manifest", code="BROKER_SERVER_MISMATCH")
        if summary.ea_version != manifest.expected_ea_version or summary.ea_version != EXPECTED_EA_VERSION:
            raise MatrixAbortError("PREFLIGHT", "EA version does not match frozen runtime", code="EA_VERSION_MISMATCH")
        if (
            summary.protocol_version != manifest.expected_protocol_version
            or summary.protocol_version != PROTOCOL_VERSION
        ):
            raise MatrixAbortError("PREFLIGHT", "protocol version does not match", code="PROTOCOL_VERSION_MISMATCH")
        heartbeat_age = _age_seconds(executor["last_heartbeat_at"], "last_heartbeat_at")
        if not -5 <= heartbeat_age <= heartbeat_max_age_seconds:
            raise MatrixAbortError("PREFLIGHT", "executor heartbeat is stale", code="HEARTBEAT_STALE")

        governance = await repository.governance_snapshot(manifest.executor_id)
        summary.kill_switch_active = bool(governance.kill_switch_active)
        if not summary.kill_switch_active:
            raise MatrixAbortError("PREFLIGHT", "global kill switch is not active", code="KILL_SWITCH_INACTIVE")

        snapshot = await repository.latest_snapshot(manifest.executor_id)
        if snapshot is None:
            raise MatrixAbortError("PREFLIGHT", "account snapshot is missing", code="SNAPSHOT_MISSING")
        snapshot_age = _age_seconds(snapshot.captured_at_utc, "snapshot.captured_at_utc")
        if not -5 <= snapshot_age <= snapshot_max_age_seconds:
            raise MatrixAbortError("PREFLIGHT", "account snapshot is stale", code="SNAPSHOT_STALE")
        summary.baseline_open_positions = len(snapshot.open_positions)
        if snapshot.open_positions:
            raise MatrixAbortError("PREFLIGHT", "open positions exist", code="BASELINE_OPEN_POSITIONS")
        expected_pairs = set(load_symbol_universe())
        snapshot_pairs = {(item.canonical_symbol, item.broker_symbol) for item in snapshot.symbols}
        if len(snapshot.symbols) != EXPECTED_SYMBOL_COUNT or snapshot_pairs != expected_pairs:
            raise MatrixAbortError("PREFLIGHT", "executor capabilities do not match XM30", code="CAPABILITIES_MISMATCH")

        active_before = await pg_client.fetch(
            """
            SELECT command_id
            FROM execution_commands
            WHERE executor_id = $1::uuid
              AND terminal_at IS NULL
              AND expires_at > now()
            """,
            str(manifest.executor_id),
        )
        active_ids = {str(row["command_id"]) for row in active_before}
        unexpected_active = active_ids - command_ids
        summary.active_commands_before = len(active_ids)
        if unexpected_active:
            raise MatrixAbortError("PREFLIGHT", "unrelated active commands exist", code="UNEXPECTED_ACTIVE_COMMANDS")

        for expected in manifest.commands:
            status = await _wait_for_terminal(
                repository,
                executor_id=manifest.executor_id,
                command_id=expected.command_id,
                timeout_seconds=barrier_timeout_seconds,
                poll_seconds=barrier_poll_seconds,
            )
            record = SymbolAudit(
                canonical_symbol=expected.canonical_symbol,
                broker_symbol=expected.broker_symbol,
                command_id=str(expected.command_id),
                command_state=str(status.get("command_state") or "UNKNOWN"),
            )
            if record.command_state not in {"SHADOW_COMPLETED", "SHADOW_REJECTED"}:
                raise MatrixAbortError(
                    "COMMAND_AUDIT",
                    f"{expected.canonical_symbol} terminal state is {record.command_state}",
                    code="COMMAND_NOT_SHADOW_COMPLETED",
                )
            command_row = await pg_client.fetchrow(
                """
                SELECT payload, payload_hash, wire_format, signed_payload_sha256,
                       source_event, source_signal_id, source_signal_hash,
                       acceptance_run_id, operator_authority, acceptance_purpose,
                       issued_at, not_before, expires_at
                FROM execution_commands
                WHERE command_id = $1::uuid AND executor_id = $2::uuid
                """,
                str(expected.command_id),
                str(manifest.executor_id),
            )
            if command_row is None:
                raise MatrixAbortError("COMMAND_AUDIT", "manifest command is missing", code="COMMAND_MISSING")
            command_payload = _json_object(command_row["payload"], "execution_commands.payload")
            binding = _mapping(command_payload.get("executor_binding"), "executor_binding")
            source = _mapping(command_payload.get("source"), "source")
            guards = _mapping(command_payload.get("guards"), "guards")
            if binding.get("execution_mode") != ExecutorMode.SHADOW.value:
                raise MatrixAbortError("COMMAND_AUDIT", "command binding is not SHADOW", code="COMMAND_MODE_MISMATCH")
            if (source.get("canonical_symbol"), source.get("broker_symbol")) != (
                expected.canonical_symbol,
                expected.broker_symbol,
            ):
                raise MatrixAbortError(
                    "COMMAND_AUDIT", "command symbol binding differs", code="COMMAND_SYMBOL_MISMATCH"
                )
            if (
                command_row["source_event"] != "SHADOW_ACCEPTANCE"
                or command_row["source_signal_id"] is not None
                or command_row["source_signal_hash"] is not None
                or command_row["acceptance_run_id"] != manifest.acceptance_run_id
                or command_row["operator_authority"] != manifest.operator_authority
                or command_row["acceptance_purpose"] != manifest.purpose
                or _aware_utc(command_row["issued_at"], "command.issued_at") < manifest.started_at_utc
                or _aware_utc(command_row["not_before"], "command.not_before")
                != _aware_utc(command_row["issued_at"], "command.issued_at")
                or _aware_utc(command_row["expires_at"], "command.expires_at") > manifest.expires_at_utc
                or source.get("source_event") != "SHADOW_ACCEPTANCE"
                or source.get("source_schema_version") != "wolf15.mt5.shadow-acceptance.v1"
                or source.get("acceptance_run_id") != manifest.acceptance_run_id
                or source.get("operator_authority") != manifest.operator_authority
                or source.get("purpose") != manifest.purpose
                or source.get("phase") != manifest.phase
                or source.get("execution_authority") is not False
                or source.get("broker_execution") != "FORBIDDEN"
            ):
                raise MatrixAbortError(
                    "COMMAND_AUDIT", "acceptance lineage differs from manifest", code="ACCEPTANCE_LINEAGE_MISMATCH"
                )
            if (
                command_payload.get("action") != "RECONCILE_ONLY"
                or command_payload.get("order") is not None
                or guards.get("guard_type") != "SHADOW_ACCEPTANCE"
                or guards.get("kill_switch_required") is not True
                or guards.get("broker_execution") != "FORBIDDEN"
                or "risk_reservation_id" in guards
                or "risk_snapshot_id" in guards
            ):
                raise MatrixAbortError(
                    "COMMAND_AUDIT", "acceptance guard boundary differs", code="ACCEPTANCE_GUARD_MISMATCH"
                )
            if (
                command_row["wire_format"] != SIGNED_WIRE_VERSION
                or command_row["signed_payload_sha256"] != command_row["payload_hash"]
            ):
                raise MatrixAbortError("COMMAND_AUDIT", "command is not signed-wire v2", code="SIGNED_WIRE_MISMATCH")

            report_rows = await pg_client.fetch(
                "SELECT state, payload FROM execution_reports WHERE command_id = $1::uuid ORDER BY sequence",
                str(expected.command_id),
            )
            record.report_count = len(report_rows)
            if len(report_rows) != 1:
                raise MatrixAbortError(
                    "REPORT_AUDIT", "command must have exactly one report", code="REPORT_CARDINALITY_MISMATCH"
                )
            report_payload = _json_object(report_rows[0]["payload"], "execution_reports.payload")
            execution = _mapping(report_payload.get("execution"), "report.execution")
            broker = _mapping(report_payload.get("broker"), "report.broker")
            record.report_state = str(report_rows[0]["state"])
            record.filled_volume = (
                float(execution["filled_volume"]) if execution.get("filled_volume") is not None else None
            )
            record.broker_order_id = broker.get("order_ticket")
            record.broker_deal_id = broker.get("deal_ticket")
            record.broker_position_id = broker.get("position_id")
            expected_command_state = "SHADOW_COMPLETED" if record.report_state == "WOULD_EXECUTE" else "SHADOW_REJECTED"
            if record.report_state not in {"WOULD_EXECUTE", "WOULD_REJECT"}:
                raise MatrixAbortError(
                    "REPORT_AUDIT", "terminal report is not a SHADOW result", code="REPORT_STATE_MISMATCH"
                )
            if record.command_state != expected_command_state:
                raise MatrixAbortError(
                    "REPORT_AUDIT", "command and report terminal states differ", code="REPORT_STATE_MISMATCH"
                )
            if (
                report_payload.get("command_id") != str(expected.command_id)
                or report_payload.get("executor_id") != str(manifest.executor_id)
                or report_payload.get("state") != record.report_state
                or report_payload.get("request_hash") != command_row["payload_hash"]
            ):
                raise MatrixAbortError(
                    "REPORT_AUDIT", "report binding or request hash differs", code="REPORT_BINDING_MISMATCH"
                )
            reason_code = str(report_payload.get("reason_code") or "")
            if record.report_state == "WOULD_EXECUTE" and reason_code != "SHADOW_ACCEPTANCE_VALIDATED":
                raise MatrixAbortError(
                    "REPORT_AUDIT", "report does not prove acceptance validation", code="REPORT_REASON_MISMATCH"
                )
            if record.report_state == "WOULD_REJECT" and reason_code not in ACCEPTANCE_REJECTION_REASONS:
                raise MatrixAbortError(
                    "REPORT_AUDIT",
                    "rejection reason is not an acceptance validator code",
                    code="REPORT_REASON_MISMATCH",
                )
            if record.filled_volume != 0.0:
                raise MatrixAbortError("REPORT_AUDIT", "filled volume is not zero", code="NONZERO_FILLED_VOLUME")
            if not {"order_ticket", "deal_ticket", "position_id"} <= set(broker):
                raise MatrixAbortError(
                    "REPORT_AUDIT", "broker-null fields are incomplete", code="BROKER_FIELDS_MISSING"
                )
            if any(
                value is not None
                for value in (record.broker_order_id, record.broker_deal_id, record.broker_position_id)
            ):
                raise MatrixAbortError(
                    "SIDE_EFFECT", "broker identifiers are present", code="BROKER_IDENTIFIERS_PRESENT"
                )
            record.outcome = "PASS"
            summary.aggregate_filled_volume += record.filled_volume
            summary.symbols_verified += 1
            summary.records.append(asdict(record))

        entity_rows = await pg_client.fetch(
            """
            SELECT command_id
            FROM broker_entities
            WHERE command_id = ANY($1::uuid[])
            """,
            list(command_ids),
        )
        summary.broker_entities = len(entity_rows)
        if entity_rows:
            raise MatrixAbortError("SIDE_EFFECT", "broker entities exist", code="BROKER_ENTITIES_RECORDED")

        report_rows = await pg_client.fetch(
            """
            SELECT command_id
            FROM execution_reports
            WHERE executor_id = $1::uuid AND received_at >= $2
            """,
            str(manifest.executor_id),
            manifest.started_at_utc,
        )
        reported_ids = {str(row["command_id"]) for row in report_rows}
        unexpected = reported_ids - command_ids
        summary.unexpected_reports = len(unexpected)
        if unexpected:
            raise MatrixAbortError("CLOSING_AUDIT", "unexpected reports exist", code="UNEXPECTED_REPORTS")

        active_after = await pg_client.fetch(
            """
            SELECT command_id
            FROM execution_commands
            WHERE executor_id = $1::uuid
              AND terminal_at IS NULL
              AND expires_at > now()
            """,
            str(manifest.executor_id),
        )
        summary.active_commands_after = len(active_after)
        if active_after:
            raise MatrixAbortError("CLOSING_AUDIT", "active commands remain", code="ACTIVE_COMMANDS_REMAIN")

        final_snapshot = await repository.latest_snapshot(manifest.executor_id)
        if final_snapshot is None:
            raise MatrixAbortError("CLOSING_AUDIT", "final snapshot is missing", code="FINAL_SNAPSHOT_MISSING")
        summary.final_open_positions = len(final_snapshot.open_positions)
        if final_snapshot.open_positions:
            raise MatrixAbortError("SIDE_EFFECT", "final open positions are nonzero", code="FINAL_OPEN_POSITIONS")
        summary.status = "PASSED"
        return summary
    finally:
        summary.finished_at_utc = datetime.now(UTC).isoformat()
        await pg_client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--heartbeat-max-age-seconds", type=float, default=DEFAULT_HEARTBEAT_MAX_AGE_SECONDS)
    parser.add_argument("--snapshot-max-age-seconds", type=float, default=DEFAULT_SNAPSHOT_MAX_AGE_SECONDS)
    parser.add_argument("--barrier-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--barrier-poll-seconds", type=float, default=0.5)
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    for name in (
        "heartbeat_max_age_seconds",
        "snapshot_max_age_seconds",
        "barrier_timeout_seconds",
        "barrier_poll_seconds",
    ):
        if not 0 < float(getattr(args, name)) <= 3600:
            parser.error(f"--{name.replace('_', '-')} must be in (0, 3600]")
    if args.out.resolve() == args.manifest.resolve():
        parser.error("--out must not overwrite --manifest")


def _write_summary(path: Path, summary: AuditSummary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(summary), indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    fallback = AuditSummary(run_id="MANIFEST_NOT_LOADED", phase="UNKNOWN", universe=REQUIRED_UNIVERSE)
    try:
        manifest = load_manifest(args.manifest)
        fallback = AuditSummary(
            run_id=manifest.acceptance_run_id,
            phase=manifest.phase,
            universe=manifest.symbol_universe,
            symbols_planned=len(manifest.commands),
        )
        summary = asyncio.run(
            audit_manifest(
                manifest,
                heartbeat_max_age_seconds=args.heartbeat_max_age_seconds,
                snapshot_max_age_seconds=args.snapshot_max_age_seconds,
                barrier_timeout_seconds=args.barrier_timeout_seconds,
                barrier_poll_seconds=args.barrier_poll_seconds,
            )
        )
    except MatrixAbortError as exc:
        fallback.failure_stage = exc.stage
        fallback.reason_code = exc.reason_code
        fallback.failure_detail = exc.detail
        fallback.finished_at_utc = datetime.now(UTC).isoformat()
        _write_summary(args.out, fallback)
        print(f"ABORT stage={exc.stage} reason={exc.reason_code}: {exc.detail}", file=sys.stderr)
        return 2
    except Exception as exc:  # fail closed and always leave an artefact
        fallback.failure_stage = "UNEXPECTED"
        fallback.reason_code = "UNEXPECTED_ERROR"
        fallback.failure_detail = type(exc).__name__
        fallback.finished_at_utc = datetime.now(UTC).isoformat()
        _write_summary(args.out, fallback)
        print(f"ABORT stage=UNEXPECTED reason=UNEXPECTED_ERROR: {type(exc).__name__}", file=sys.stderr)
        return 3
    _write_summary(args.out, summary)
    print(
        f"status={summary.status} verified={summary.symbols_verified}/{summary.symbols_planned} "
        f"filled_volume={summary.aggregate_filled_volume} broker_entities={summary.broker_entities}"
    )
    return 0 if summary.status == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
