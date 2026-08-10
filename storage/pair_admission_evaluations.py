"""Independent durable persistence for PairAdmission evaluations.

The ledger is deliberately separate from SignalPressureStateJSON routing and
never creates pressure-outbox, risk, command, or broker authority.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import os
import threading
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from loguru import logger

from storage.postgres_client import PostgresClient, pg_client

_REQUIRED_TABLES = frozenset({"pair_admission_evaluations"})


@dataclass(frozen=True)
class _ColumnContract:
    data_type: str
    nullable: bool
    max_length: int | None = None
    default_kind: str | None = None


_REQUIRED_COLUMNS = {
    "evaluation_id": _ColumnContract("text", False),
    "deployment_id": _ColumnContract("character varying", False, 200),
    "raw_block_id": _ColumnContract("text", False),
    "rule_version": _ColumnContract("character varying", False, 100),
    "symbol": _ColumnContract("character varying", False, 32),
    "direction": _ColumnContract("character varying", True, 4),
    "evaluated_at_utc": _ColumnContract("timestamp with time zone", False),
    "block_started_at_utc": _ColumnContract("timestamp with time zone", False),
    "block_latest_event_at_utc": _ColumnContract("timestamp with time zone", False),
    "duration_seconds": _ColumnContract("double precision", False),
    "raw_event_count": _ColumnContract("integer", False),
    "effective_ticks": _ColumnContract("integer", False),
    "max_gap_seconds": _ColumnContract("double precision", False),
    "cross_symbol_interruption_count": _ColumnContract("integer", False, default_kind="zero"),
    "raw_lineage_hash": _ColumnContract("character varying", True, 71),
    "decision": _ColumnContract("character varying", False, 16),
    "reason_code": _ColumnContract("character varying", True, 100),
    "admission_event_id": _ColumnContract("text", True),
    "payload_hash": _ColumnContract("character varying", False, 64),
    "payload": _ColumnContract("jsonb", False),
    "execution_authority": _ColumnContract("boolean", False, default_kind="false"),
    "created_at": _ColumnContract("timestamp with time zone", False, default_kind="now"),
}
_REQUIRED_CONSTRAINTS = frozenset(
    {
        "ck_pair_admission_decision",
        "ck_pair_admission_direction",
        "ck_pair_admission_duration_non_negative",
        "ck_pair_admission_event_count_non_negative",
        "ck_pair_admission_ticks_non_negative",
        "ck_pair_admission_gap_non_negative",
        "ck_pair_admission_interruptions_non_negative",
        "ck_pair_admission_non_executable",
        "ck_pair_admission_result_shape",
    }
)
_REQUIRED_INDEXES = {
    "ix_pair_admission_evaluated": (False, ("evaluated_at_utc", "decision"), None),
    "ix_pair_admission_symbol_block": (False, ("deployment_id", "symbol", "raw_block_id"), None),
    "uq_pair_admission_one_grant_per_block": (
        True,
        ("deployment_id", "raw_block_id", "rule_version"),
        "GRANTED",
    ),
}


class PairAdmissionEvaluationError(RuntimeError):
    """Base error for durable admission evaluation persistence."""


class PairAdmissionEvaluationContractError(PairAdmissionEvaluationError):
    """Raised when an evaluation cannot be safely persisted."""


class PairAdmissionEvaluationIntegrityError(PairAdmissionEvaluationError):
    """Raised when a stable evaluation or grant identity changes content."""


@dataclass(frozen=True)
class DurablePairAdmissionEvaluation:
    evaluation_id: str
    raw_block_id: str
    decision: Literal["GRANTED", "NOT_GRANTED"]
    duplicate: bool = False


PairAdmissionPersistenceStatus = Literal["PERSISTED", "DUPLICATE", "DISABLED", "REJECTED", "FAILED"]


@dataclass(frozen=True)
class PairAdmissionPersistenceResult:
    status: PairAdmissionPersistenceStatus
    evaluation_id: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class PairAdmissionEvaluationSchemaStatus:
    present_tables: frozenset[str]
    present_columns: frozenset[str]
    present_constraints: frozenset[str]
    present_indexes: frozenset[str]
    missing_tables: tuple[str, ...]
    missing_columns: tuple[str, ...]
    invalid_columns: tuple[str, ...]
    missing_constraints: tuple[str, ...]
    invalid_constraints: tuple[str, ...]
    missing_indexes: tuple[str, ...]
    invalid_indexes: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not any(
            (
                self.missing_tables,
                self.missing_columns,
                self.invalid_columns,
                self.missing_constraints,
                self.invalid_constraints,
                self.missing_indexes,
                self.invalid_indexes,
            )
        )


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _normalized_sql(value: Any) -> str:
    return " ".join(str(value or "").replace('"', "").lower().split())


def _column_contract_error(name: str, row: Any) -> str | None:
    contract = _REQUIRED_COLUMNS[name]
    data_type = str(_row_value(row, "data_type") or "").lower()
    nullable = str(_row_value(row, "is_nullable") or "").upper() == "YES"
    length_raw = _row_value(row, "character_maximum_length")
    length = None if length_raw is None else int(length_raw)
    default = _normalized_sql(_row_value(row, "column_default"))
    if data_type != contract.data_type:
        return f"{name}:type={data_type or 'missing'}"
    if nullable != contract.nullable:
        return f"{name}:nullable={str(nullable).lower()}"
    if length != contract.max_length:
        return f"{name}:max_length={length}"
    if contract.default_kind is None and default:
        return f"{name}:default={default}"
    if contract.default_kind == "false" and "false" not in default:
        return f"{name}:default={default or 'missing'}"
    if contract.default_kind == "zero" and not default.startswith("0"):
        return f"{name}:default={default or 'missing'}"
    if contract.default_kind == "now" and "now()" not in default:
        return f"{name}:default={default or 'missing'}"
    return None


def _text(value: Any) -> str | None:
    resolved = str(value or "").strip()
    return resolved or None


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _number(value: Any, *, default: float = 0.0) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def _integer(value: Any, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def pair_admission_evaluation_hash(evaluation: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(evaluation),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validated(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(evaluation)
    if data.get("event") != "pair_admission_evaluated":
        raise PairAdmissionEvaluationContractError("PAIR_ADMISSION_EVALUATION_EVENT_INVALID")
    evaluation_id = _text(data.get("evaluation_id"))
    raw_block_id = _text(data.get("candidate_block_id"))
    rule_version = _text(data.get("rule_version"))
    symbol = _text(data.get("symbol"))
    deployments = tuple(str(value).strip() for value in (data.get("source_deployment_ids") or ()) if str(value).strip())
    if not evaluation_id or not evaluation_id.startswith("5scr-admission-evaluation:"):
        raise PairAdmissionEvaluationContractError("PAIR_ADMISSION_EVALUATION_ID_INVALID")
    if not raw_block_id or not raw_block_id.startswith("5scr-raw-block:"):
        raise PairAdmissionEvaluationContractError("PAIR_ADMISSION_RAW_BLOCK_ID_INVALID")
    if not rule_version or not symbol:
        raise PairAdmissionEvaluationContractError("PAIR_ADMISSION_EVALUATION_LINEAGE_MISSING")
    if len(set(deployments)) != 1 or deployments[0].lower() == "unknown":
        raise PairAdmissionEvaluationContractError("PAIR_ADMISSION_DEPLOYMENT_SCOPE_INVALID")
    decision = "GRANTED" if str(data.get("decision") or "").upper() == "GRANTED" else "NOT_GRANTED"
    reason = _text(data.get("rejection_reason"))
    admission_event_id = _text(data.get("pair_admission_id"))
    if decision == "GRANTED" and (reason is not None or admission_event_id is None):
        raise PairAdmissionEvaluationContractError("PAIR_ADMISSION_GRANTED_RESULT_INVALID")
    if decision == "NOT_GRANTED" and (reason is None or admission_event_id is not None):
        raise PairAdmissionEvaluationContractError("PAIR_ADMISSION_REJECTED_RESULT_INVALID")
    started_at = _utc(data.get("episode_started_at_utc"))
    latest_at = _utc(data.get("episode_observed_through_utc"))
    evaluated_at = _utc(data.get("decision_at_utc")) or latest_at
    if started_at is None or latest_at is None or evaluated_at is None or latest_at < started_at:
        raise PairAdmissionEvaluationContractError("PAIR_ADMISSION_EVALUATION_TIME_INVALID")
    if data.get("execution_authority") is not False:
        raise PairAdmissionEvaluationContractError("PAIR_ADMISSION_EXECUTION_AUTHORITY_FORBIDDEN")
    direction = _text(data.get("direction"))
    if direction not in {None, "BUY", "SELL"}:
        raise PairAdmissionEvaluationContractError("PAIR_ADMISSION_DIRECTION_INVALID")
    return {
        "payload": data,
        "payload_hash": pair_admission_evaluation_hash(data),
        "evaluation_id": evaluation_id,
        "deployment_id": deployments[0],
        "raw_block_id": raw_block_id,
        "rule_version": rule_version,
        "symbol": symbol.upper(),
        "direction": direction,
        "evaluated_at": evaluated_at,
        "started_at": started_at,
        "latest_at": latest_at,
        "duration": _number(data.get("calculated_duration_seconds")),
        "event_count": _integer(data.get("source_event_count")),
        "effective_ticks": _integer(data.get("calculated_effective_ticks")),
        "max_gap": _number(data.get("calculated_max_gap_seconds")),
        "interruptions": _integer(data.get("cross_symbol_interruption_count")),
        "lineage_hash": _text(data.get("raw_lineage_hash")),
        "decision": decision,
        "reason": reason,
        "admission_event_id": admission_event_id,
    }


class PairAdmissionEvaluationRepository:
    """Append-only admission evaluation ledger with one grant per raw block."""

    def __init__(self, *, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client

    @property
    def is_available(self) -> bool:
        return self._pg.is_available

    async def schema_status(self) -> PairAdmissionEvaluationSchemaStatus:
        if not self._pg.is_available:
            return PairAdmissionEvaluationSchemaStatus(
                present_tables=frozenset(),
                present_columns=frozenset(),
                present_constraints=frozenset(),
                present_indexes=frozenset(),
                missing_tables=tuple(sorted(_REQUIRED_TABLES)),
                missing_columns=tuple(sorted(_REQUIRED_COLUMNS)),
                invalid_columns=(),
                missing_constraints=tuple(sorted(_REQUIRED_CONSTRAINTS)),
                invalid_constraints=(),
                missing_indexes=tuple(sorted(_REQUIRED_INDEXES)),
                invalid_indexes=(),
            )
        table_rows = await self._pg.fetch(
            """
            SELECT tablename
            FROM pg_catalog.pg_tables
            WHERE schemaname = current_schema()
              AND tablename = ANY($1::text[])
            """,
            sorted(_REQUIRED_TABLES),
        )
        column_rows = await self._pg.fetch(
            """
            SELECT column_name, data_type, is_nullable, column_default,
                   character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'pair_admission_evaluations'
            """
        )
        constraint_rows = await self._pg.fetch(
            """
            SELECT con.conname, con.contype, cls.relname AS table_name,
                   pg_get_constraintdef(con.oid) AS definition
            FROM pg_catalog.pg_constraint AS con
            JOIN pg_catalog.pg_class AS cls ON cls.oid = con.conrelid
            JOIN pg_catalog.pg_namespace AS ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()
              AND cls.relname = 'pair_admission_evaluations'
              AND con.conname = ANY($1::text[])
            """,
            sorted(_REQUIRED_CONSTRAINTS),
        )
        index_rows = await self._pg.fetch(
            """
            SELECT index_cls.relname AS indexname,
                   idx.indisunique,
                   ARRAY(
                       SELECT attr.attname
                       FROM unnest(idx.indkey) WITH ORDINALITY AS key(attnum, position)
                       JOIN pg_catalog.pg_attribute AS attr
                         ON attr.attrelid = idx.indrelid AND attr.attnum = key.attnum
                       ORDER BY key.position
                   ) AS columns,
                   pg_get_expr(idx.indpred, idx.indrelid) AS predicate
            FROM pg_catalog.pg_index AS idx
            JOIN pg_catalog.pg_class AS table_cls ON table_cls.oid = idx.indrelid
            JOIN pg_catalog.pg_class AS index_cls ON index_cls.oid = idx.indexrelid
            JOIN pg_catalog.pg_namespace AS ns ON ns.oid = table_cls.relnamespace
            WHERE ns.nspname = current_schema()
              AND table_cls.relname = 'pair_admission_evaluations'
              AND index_cls.relname = ANY($1::text[])
            """,
            sorted(_REQUIRED_INDEXES),
        )
        present_tables = frozenset(str(_row_value(row, "tablename") or "") for row in table_rows)
        columns_by_name = {
            str(_row_value(row, "column_name") or ""): row
            for row in column_rows
            if str(_row_value(row, "column_name") or "")
        }
        present_columns = frozenset(columns_by_name)
        invalid_columns = tuple(
            sorted(
                error
                for name, row in columns_by_name.items()
                if name in _REQUIRED_COLUMNS and (error := _column_contract_error(name, row)) is not None
            )
        )
        constraints_by_name = {
            str(_row_value(row, "conname") or ""): row
            for row in constraint_rows
            if str(_row_value(row, "conname") or "")
        }
        present_constraints = frozenset(constraints_by_name)
        invalid_constraints: list[str] = []
        for name, row in constraints_by_name.items():
            definition = _normalized_sql(_row_value(row, "definition"))
            raw_constraint_type = _row_value(row, "contype")
            constraint_type = (
                raw_constraint_type.decode("ascii")
                if isinstance(raw_constraint_type, bytes)
                else str(raw_constraint_type or "")
            )
            if constraint_type != "c" or str(_row_value(row, "table_name") or "") != ("pair_admission_evaluations"):
                invalid_constraints.append(f"{name}:shape")
                continue
            if name == "ck_pair_admission_non_executable" and not (
                "execution_authority" in definition and "is false" in definition
            ):
                invalid_constraints.append(f"{name}:definition")
            if name == "ck_pair_admission_result_shape" and not all(
                fragment in definition for fragment in ("decision", "granted", "not_granted", "admission_event_id")
            ):
                invalid_constraints.append(f"{name}:definition")
        indexes_by_name = {
            str(_row_value(row, "indexname") or ""): row
            for row in index_rows
            if str(_row_value(row, "indexname") or "")
        }
        present_indexes = frozenset(str(_row_value(row, "indexname") or "") for row in index_rows)
        invalid_indexes: list[str] = []
        for name, row in indexes_by_name.items():
            expected_unique, expected_columns, expected_predicate = _REQUIRED_INDEXES[name]
            actual_unique = bool(_row_value(row, "indisunique"))
            actual_columns = tuple(str(value) for value in (_row_value(row, "columns") or ()))
            predicate = _normalized_sql(_row_value(row, "predicate"))
            if actual_unique != expected_unique or actual_columns != expected_columns:
                invalid_indexes.append(f"{name}:shape")
                continue
            predicate_invalid = (expected_predicate is None and bool(predicate)) or (
                expected_predicate is not None
                and not (
                    "decision" in predicate
                    and expected_predicate.lower() in predicate
                    and "not_granted" not in predicate
                )
            )
            if predicate_invalid:
                invalid_indexes.append(f"{name}:predicate")
        return PairAdmissionEvaluationSchemaStatus(
            present_tables=present_tables,
            present_columns=present_columns,
            present_constraints=present_constraints,
            present_indexes=present_indexes,
            missing_tables=tuple(sorted(_REQUIRED_TABLES - present_tables)),
            missing_columns=tuple(sorted(set(_REQUIRED_COLUMNS) - present_columns)),
            invalid_columns=invalid_columns,
            missing_constraints=tuple(sorted(_REQUIRED_CONSTRAINTS - present_constraints)),
            invalid_constraints=tuple(sorted(invalid_constraints)),
            missing_indexes=tuple(sorted(set(_REQUIRED_INDEXES) - present_indexes)),
            invalid_indexes=tuple(sorted(invalid_indexes)),
        )

    async def ingest(self, evaluation: Mapping[str, Any]) -> DurablePairAdmissionEvaluation:
        if not self._pg.is_available:
            raise PairAdmissionEvaluationError("PAIR_ADMISSION_DATABASE_UNAVAILABLE")
        record = _validated(evaluation)
        async with self._pg.transaction() as conn:
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"pair-admission|{record['deployment_id']}|{record['raw_block_id']}|{record['rule_version']}",
            )
            existing = await conn.fetchrow(
                """
                SELECT payload_hash
                FROM pair_admission_evaluations
                WHERE evaluation_id = $1
                FOR UPDATE
                """,
                record["evaluation_id"],
            )
            if existing is not None:
                if str(_row_value(existing, "payload_hash")) != record["payload_hash"]:
                    raise PairAdmissionEvaluationIntegrityError("PAIR_ADMISSION_EVALUATION_HASH_MISMATCH")
                return DurablePairAdmissionEvaluation(
                    evaluation_id=record["evaluation_id"],
                    raw_block_id=record["raw_block_id"],
                    decision=record["decision"],
                    duplicate=True,
                )
            if record["decision"] == "GRANTED":
                prior_grant = await conn.fetchrow(
                    """
                    SELECT evaluation_id, admission_event_id
                    FROM pair_admission_evaluations
                    WHERE deployment_id = $1 AND raw_block_id = $2 AND rule_version = $3
                      AND decision = 'GRANTED'
                    FOR UPDATE
                    """,
                    record["deployment_id"],
                    record["raw_block_id"],
                    record["rule_version"],
                )
                if prior_grant is not None:
                    if str(_row_value(prior_grant, "admission_event_id")) != record["admission_event_id"]:
                        raise PairAdmissionEvaluationIntegrityError("PAIR_ADMISSION_DUPLICATE_LOGICAL_GRANT")
                    return DurablePairAdmissionEvaluation(
                        evaluation_id=str(_row_value(prior_grant, "evaluation_id")),
                        raw_block_id=record["raw_block_id"],
                        decision="GRANTED",
                        duplicate=True,
                    )
            await conn.execute(
                """
                INSERT INTO pair_admission_evaluations (
                    evaluation_id, deployment_id, raw_block_id, rule_version,
                    symbol, direction, evaluated_at_utc, block_started_at_utc,
                    block_latest_event_at_utc, duration_seconds, raw_event_count,
                    effective_ticks, max_gap_seconds, cross_symbol_interruption_count,
                    raw_lineage_hash, decision, reason_code, admission_event_id,
                    payload_hash, payload, execution_authority, created_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                    $13, $14, $15, $16, $17, $18, $19, $20::jsonb, FALSE, NOW()
                )
                """,
                record["evaluation_id"],
                record["deployment_id"],
                record["raw_block_id"],
                record["rule_version"],
                record["symbol"],
                record["direction"],
                record["evaluated_at"],
                record["started_at"],
                record["latest_at"],
                record["duration"],
                record["event_count"],
                record["effective_ticks"],
                record["max_gap"],
                record["interruptions"],
                record["lineage_hash"],
                record["decision"],
                record["reason"],
                record["admission_event_id"],
                record["payload_hash"],
                json.dumps(record["payload"], separators=(",", ":"), ensure_ascii=False, default=str),
            )
        return DurablePairAdmissionEvaluation(
            evaluation_id=record["evaluation_id"],
            raw_block_id=record["raw_block_id"],
            decision=record["decision"],
        )


class PairAdmissionEvaluationRuntime:
    """Thread-safe synchronous bridge with bounded in-process deduplication."""

    def __init__(self, *, max_seen: int = 20000) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._repository: PairAdmissionEvaluationRepository | None = None
        self._seen: set[tuple[str, str]] = set()
        self._seen_order: deque[tuple[str, str]] = deque()
        self._seen_lock = threading.Lock()
        self._max_seen = max(100, int(max_seen))

    def configure(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        repository: PairAdmissionEvaluationRepository,
    ) -> None:
        self._loop = loop
        self._repository = repository

    def clear(self) -> None:
        self._loop = None
        self._repository = None
        with self._seen_lock:
            self._seen.clear()
            self._seen_order.clear()

    def _remember(self, key: tuple[str, str]) -> None:
        with self._seen_lock:
            if key in self._seen:
                return
            self._seen.add(key)
            self._seen_order.append(key)
            while len(self._seen_order) > self._max_seen:
                self._seen.discard(self._seen_order.popleft())

    def persist_sync(
        self,
        evaluation: Mapping[str, Any],
        *,
        timeout_seconds: float = 5.0,
    ) -> PairAdmissionPersistenceResult:
        flags_enabled = all(
            os.getenv(name, "false").strip().lower() == "true"
            for name in (
                "SIGNAL_PRESSURE_OUTBOX_ENABLED",
                "SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED",
                "SIGNAL_PRESSURE_RADAR_WRITE_ENABLED",
            )
        )
        if not flags_enabled:
            return PairAdmissionPersistenceResult(status="DISABLED")
        try:
            record = _validated(evaluation)
        except PairAdmissionEvaluationContractError as exc:
            return PairAdmissionPersistenceResult(status="REJECTED", error=str(exc))
        key = (record["evaluation_id"], record["payload_hash"])
        with self._seen_lock:
            if key in self._seen:
                return PairAdmissionPersistenceResult(status="DUPLICATE", evaluation_id=record["evaluation_id"])
        loop = self._loop
        repository = self._repository
        if loop is None or repository is None or not loop.is_running() or not repository.is_available:
            return PairAdmissionPersistenceResult(status="FAILED", error="PAIR_ADMISSION_RUNTIME_UNAVAILABLE")
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is loop:
            return PairAdmissionPersistenceResult(status="FAILED", error="PAIR_ADMISSION_SYNC_BRIDGE_ON_OWNER_LOOP")
        future = asyncio.run_coroutine_threadsafe(repository.ingest(evaluation), loop)
        try:
            durable = future.result(timeout=max(0.1, float(timeout_seconds)))
        except concurrent.futures.TimeoutError:
            future.cancel()
            return PairAdmissionPersistenceResult(status="FAILED", error="PAIR_ADMISSION_WRITE_TIMEOUT")
        except PairAdmissionEvaluationContractError as exc:
            return PairAdmissionPersistenceResult(status="REJECTED", error=str(exc))
        except PairAdmissionEvaluationIntegrityError as exc:
            logger.error("Durable PairAdmission integrity failure: {}", exc)
            return PairAdmissionPersistenceResult(status="FAILED", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Durable PairAdmission write failed: {}", exc)
            return PairAdmissionPersistenceResult(status="FAILED", error=str(exc))
        self._remember(key)
        return PairAdmissionPersistenceResult(
            status="DUPLICATE" if durable.duplicate else "PERSISTED",
            evaluation_id=durable.evaluation_id,
        )


pair_admission_evaluation_runtime = PairAdmissionEvaluationRuntime()


def configure_pair_admission_evaluation_runtime(
    *,
    loop: asyncio.AbstractEventLoop | None = None,
    repository: PairAdmissionEvaluationRepository | None = None,
) -> None:
    pair_admission_evaluation_runtime.configure(
        loop=loop or asyncio.get_running_loop(),
        repository=repository or PairAdmissionEvaluationRepository(),
    )


def persist_pair_admission_evaluation_sync(
    evaluation: Mapping[str, Any],
) -> PairAdmissionPersistenceResult:
    timeout = float(os.getenv("PAIR_ADMISSION_WRITE_TIMEOUT_SECONDS", "5"))
    return pair_admission_evaluation_runtime.persist_sync(evaluation, timeout_seconds=timeout)


__all__ = [
    "DurablePairAdmissionEvaluation",
    "PairAdmissionEvaluationContractError",
    "PairAdmissionEvaluationError",
    "PairAdmissionEvaluationIntegrityError",
    "PairAdmissionEvaluationRepository",
    "PairAdmissionEvaluationSchemaStatus",
    "PairAdmissionEvaluationRuntime",
    "PairAdmissionPersistenceResult",
    "configure_pair_admission_evaluation_runtime",
    "pair_admission_evaluation_hash",
    "pair_admission_evaluation_runtime",
    "persist_pair_admission_evaluation_sync",
]
