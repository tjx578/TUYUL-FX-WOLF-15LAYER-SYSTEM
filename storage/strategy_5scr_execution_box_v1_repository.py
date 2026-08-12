"""Atomic shadow-only persistence for Strategy 5S-CR ExecutionBox V1."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import ValidationError

from analysis.strategy_5scr_execution_box_v1 import (
    close_execution_box,
    execution_box_evidence_hash,
    execution_box_id,
    material_box_hash,
    reduce_execution_box,
)
from contracts.strategy_5scr_directional_thesis_v1 import DirectionalThesisV1
from contracts.strategy_5scr_execution_box_v1 import ExecutionBoxEvidenceV1, ExecutionBoxV1
from storage.postgres_client import PostgresClient, pg_client
from storage.strategy_5scr_directional_thesis_v1_repository import (
    Strategy5SCRDirectionalThesisV1Repository,
)

BOX_TABLE = "strategy_5scr_execution_boxes_v1"
THESIS_TABLE = "strategy_5scr_directional_theses_v1"
CONTEXT_TABLE = "strategy_5scr_context_epochs_v1"
LIFECYCLE_TABLE = "strategy_5scr_analysis_lifecycles_v2"

EXECUTION_BOX_V1_WRITER_FLAG = "STRATEGY_5SCR_EXECUTION_BOX_V1_WRITER_ENABLED"
EXECUTION_BOX_V1_SHADOW_ONLY_FLAG = "STRATEGY_5SCR_EXECUTION_BOX_V1_SHADOW_ONLY"


class ExecutionBoxV1IntegrityError(RuntimeError):
    """Raised when durable P5 state disagrees with its frozen payload."""


def _row_value(row: Any, key: str) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError):
        return getattr(row, key, None)


def _enabled(value: str | None, *, default: bool) -> bool:
    return default if value is None else value.strip().lower() == "true"


@dataclass(frozen=True)
class ExecutionBoxV1RuntimeConfig:
    enabled: bool = False
    shadow_only: bool = True

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ExecutionBoxV1RuntimeConfig:
        source = os.environ if environ is None else environ
        return cls(
            enabled=_enabled(source.get(EXECUTION_BOX_V1_WRITER_FLAG), default=False),
            shadow_only=_enabled(source.get(EXECUTION_BOX_V1_SHADOW_ONLY_FLAG), default=True),
        )

    def validate(self) -> None:
        if self.enabled and not self.shadow_only:
            raise RuntimeError("STRATEGY_5SCR_EXECUTION_BOX_V1_SHADOW_ONLY_REQUIRED")


@dataclass(frozen=True)
class ExecutionBoxV1SchemaStatus:
    missing_tables: tuple[str, ...]
    missing_columns: tuple[str, ...]
    invalid_columns: tuple[str, ...]
    missing_constraints: tuple[str, ...]
    invalid_constraints: tuple[str, ...]
    missing_indexes: tuple[str, ...]
    invalid_indexes: tuple[str, ...]
    missing_triggers: tuple[str, ...]
    invalid_triggers: tuple[str, ...]

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
                self.missing_triggers,
                self.invalid_triggers,
            )
        )


_REQUIRED_COLUMNS: dict[str, tuple[str, bool, int | None, str]] = {
    "execution_box_id": ("text", False, None, ""),
    "strategy_lifecycle_id": ("text", False, None, ""),
    "context_epoch_id": ("text", False, None, ""),
    "strategy_thesis_id": ("text", False, None, ""),
    "box_sequence": ("integer", False, None, ""),
    "box_version": ("integer", False, None, ""),
    "previous_execution_box_id": ("text", True, None, ""),
    "symbol": ("character varying", False, 32, ""),
    "strategy_direction": ("character varying", False, 4, ""),
    "route_type": ("character varying", False, 120, ""),
    "state": ("character varying", False, 20, ""),
    "box_low": ("double precision", False, None, ""),
    "box_high": ("double precision", False, None, ""),
    "opened_at": ("timestamp with time zone", False, None, ""),
    "frozen_at": ("timestamp with time zone", True, None, ""),
    "freeze_authority_hash": ("character varying", True, 71, ""),
    "superseded_at": ("timestamp with time zone", True, None, ""),
    "invalidated_at": ("timestamp with time zone", True, None, ""),
    "consumed_at": ("timestamp with time zone", True, None, ""),
    "expired_at": ("timestamp with time zone", True, None, ""),
    "material_box_hash": ("character varying", False, 71, ""),
    "evidence_hash": ("character varying", False, 71, ""),
    "thesis_semantic_identity_hash": ("character varying", False, 71, ""),
    "source_m1_ids": ("jsonb", False, None, ""),
    "source_m1_evidence_ids": ("jsonb", False, None, ""),
    "last_observed_at": ("timestamp with time zone", False, None, ""),
    "last_source_request_id": ("text", True, None, ""),
    "state_version": ("bigint", False, None, ""),
    "rule_version": ("character varying", False, 100, ""),
    "valid_for_execution": ("boolean", False, None, "false"),
    "execution_authority": ("boolean", False, None, "false"),
    "payload": ("jsonb", False, None, ""),
    "evidence_payload": ("jsonb", False, None, ""),
    "freeze_evidence_payload": ("jsonb", True, None, ""),
    "created_at": ("timestamp with time zone", False, None, "now()"),
    "updated_at": ("timestamp with time zone", False, None, "now()"),
}

_REQUIRED_CONSTRAINTS: dict[str, tuple[str, tuple[str, ...]]] = {
    f"{BOX_TABLE}_pkey": ("p", ("primary key (execution_box_id)",)),
    "fk_5scr_execution_box_lifecycle_v1": ("f", ("strategy_lifecycle_id", LIFECYCLE_TABLE)),
    "fk_5scr_execution_box_context_scope_v1": (
        "f",
        ("context_epoch_id, strategy_lifecycle_id, symbol", CONTEXT_TABLE),
    ),
    "fk_5scr_execution_box_thesis_scope_v1": (
        "f",
        ("strategy_thesis_id, strategy_lifecycle_id, context_epoch_id, symbol, strategy_direction", THESIS_TABLE),
    ),
    "fk_5scr_execution_box_previous_v1": ("f", ("previous_execution_box_id", BOX_TABLE)),
    "uq_5scr_execution_box_version_v1": ("u", ("strategy_thesis_id, box_version",)),
    "uq_5scr_execution_box_sequence_v1": ("u", ("strategy_lifecycle_id, box_sequence",)),
    "ck_5scr_execution_box_identity_v1": ("c", ("5scr-execution-box:", "material_box_hash", "evidence_hash")),
    "ck_5scr_execution_box_geometry_v1": ("c", ("box_sequence >= 1", "box_high > box_low")),
    "ck_5scr_execution_box_state_v1": ("c", ("building", "frozen", "superseded", "invalidated")),
    "ck_5scr_execution_box_sources_v1": ("c", ("jsonb_typeof(source_m1_ids)", "jsonb_array_length")),
    "ck_5scr_execution_box_lineage_v1": ("c", ("box_version = 1", "previous_execution_box_id")),
    "ck_5scr_execution_box_temporal_v1": ("c", ("frozen_at >= opened_at", "expired_at >= opened_at")),
    "ck_5scr_execution_box_shadow_only_v1": ("c", ("valid_for_execution is false", "execution_authority is false")),
}

_REQUIRED_INDEXES: dict[str, tuple[bool, tuple[str, ...], tuple[str, ...]]] = {
    "uq_5scr_execution_box_active_thesis_v1": (True, ("strategy_thesis_id",), ("building", "frozen")),
    "uq_5scr_execution_box_active_lifecycle_v1": (
        True,
        ("strategy_lifecycle_id",),
        ("building", "frozen"),
    ),
    "ix_5scr_execution_box_lifecycle_history_v1": (
        False,
        ("strategy_lifecycle_id", "box_sequence", "execution_box_id"),
        (),
    ),
}


def _normalize_sql(value: Any) -> str:
    return " ".join(str(value or "").lower().replace('"', "").split())


def _json(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _box_from_row(row: Any) -> ExecutionBoxV1:
    try:
        box = ExecutionBoxV1.model_validate(_json(_row_value(row, "payload")))
    except (ValidationError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_PAYLOAD_INVALID") from exc
    durable = {
        "execution_box_id": _row_value(row, "execution_box_id"),
        "strategy_lifecycle_id": _row_value(row, "strategy_lifecycle_id"),
        "context_epoch_id": _row_value(row, "context_epoch_id"),
        "strategy_thesis_id": _row_value(row, "strategy_thesis_id"),
        "box_sequence": _row_value(row, "box_sequence"),
        "box_version": _row_value(row, "box_version"),
        "previous_execution_box_id": _row_value(row, "previous_execution_box_id"),
        "symbol": _row_value(row, "symbol"),
        "strategy_direction": _row_value(row, "strategy_direction"),
        "route_type": _row_value(row, "route_type"),
        "state": _row_value(row, "state"),
        "box_low": _row_value(row, "box_low"),
        "box_high": _row_value(row, "box_high"),
        "opened_at_utc": _row_value(row, "opened_at"),
        "frozen_at_utc": _row_value(row, "frozen_at"),
        "freeze_authority_hash": _row_value(row, "freeze_authority_hash"),
        "superseded_at_utc": _row_value(row, "superseded_at"),
        "invalidated_at_utc": _row_value(row, "invalidated_at"),
        "consumed_at_utc": _row_value(row, "consumed_at"),
        "expired_at_utc": _row_value(row, "expired_at"),
        "material_box_hash": _row_value(row, "material_box_hash"),
        "evidence_hash": _row_value(row, "evidence_hash"),
        "thesis_semantic_identity_hash": _row_value(row, "thesis_semantic_identity_hash"),
        "source_m1_ids": tuple(_json(_row_value(row, "source_m1_ids"))),
        "source_m1_evidence_ids": tuple(_json(_row_value(row, "source_m1_evidence_ids"))),
        "last_observed_at_utc": _row_value(row, "last_observed_at"),
        "last_source_request_id": _row_value(row, "last_source_request_id"),
        "state_version": _row_value(row, "state_version"),
        "rule_version": _row_value(row, "rule_version"),
        "valid_for_execution": bool(_row_value(row, "valid_for_execution")),
        "execution_authority": bool(_row_value(row, "execution_authority")),
    }
    projection = box.model_dump(mode="python")
    if any(projection[key] != value for key, value in durable.items()):
        raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_DURABLE_COLUMN_DRIFT")
    try:
        evidence = ExecutionBoxEvidenceV1.model_validate(_json(_row_value(row, "evidence_payload")))
    except (ValidationError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_EVIDENCE_PAYLOAD_INVALID") from exc
    if (
        evidence.strategy_lifecycle_id != box.strategy_lifecycle_id
        or evidence.context_epoch_id != box.context_epoch_id
        or evidence.strategy_thesis_id != box.strategy_thesis_id
        or evidence.thesis_semantic_identity_hash != box.thesis_semantic_identity_hash
        or evidence.symbol != box.symbol
        or evidence.strategy_direction != box.strategy_direction
        or evidence.route_type != box.route_type
        or material_box_hash(evidence) != box.material_box_hash
        or execution_box_evidence_hash(evidence) != box.evidence_hash
        or tuple(sorted(item.material_candle_hash for item in evidence.material_m1_candles)) != box.source_m1_ids
        or tuple(sorted(item.candle_evidence_id for item in evidence.material_m1_candles)) != box.source_m1_evidence_ids
        or execution_box_id(box.strategy_thesis_id, box.box_version, box.material_box_hash) != box.execution_box_id
    ):
        raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_DURABLE_EVIDENCE_DRIFT")
    freeze_payload = _row_value(row, "freeze_evidence_payload")
    if box.freeze_authority_hash is None:
        if freeze_payload is not None:
            raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_UNAUTHORISED_FREEZE_EVIDENCE")
    else:
        try:
            freeze_evidence = ExecutionBoxEvidenceV1.model_validate(_json(freeze_payload))
        except (ValidationError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_FREEZE_EVIDENCE_INVALID") from exc
        if (
            not freeze_evidence.freeze_requested
            or freeze_evidence.freeze_authority_hash != box.freeze_authority_hash
            or freeze_evidence.strategy_lifecycle_id != box.strategy_lifecycle_id
            or freeze_evidence.context_epoch_id != box.context_epoch_id
            or freeze_evidence.strategy_thesis_id != box.strategy_thesis_id
            or freeze_evidence.symbol != box.symbol
            or freeze_evidence.strategy_direction != box.strategy_direction
            or freeze_evidence.route_type != box.route_type
            or material_box_hash(freeze_evidence) != box.material_box_hash
        ):
            raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_FREEZE_EVIDENCE_DRIFT")
    return box


def _thesis_from_row(row: Any) -> DirectionalThesisV1:
    try:
        thesis = DirectionalThesisV1.model_validate(_json(_row_value(row, "payload")))
    except (ValidationError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ExecutionBoxV1IntegrityError("DIRECTIONAL_THESIS_PAYLOAD_INVALID") from exc
    if (
        thesis.strategy_thesis_id != _row_value(row, "strategy_thesis_id")
        or thesis.strategy_lifecycle_id != _row_value(row, "strategy_lifecycle_id")
        or thesis.context_epoch_id != _row_value(row, "context_epoch_id")
        or thesis.symbol != _row_value(row, "symbol")
        or thesis.state != _row_value(row, "state")
        or thesis.semantic_identity_hash != _row_value(row, "semantic_identity_hash")
        or thesis.execution_authority
        or thesis.valid_for_execution
    ):
        raise ExecutionBoxV1IntegrityError("DIRECTIONAL_THESIS_DURABLE_SCOPE_DRIFT")
    return thesis


ExecutionBoxPersistenceStatus = Literal[
    "PERSISTED",
    "DUPLICATE",
    "NO_CHANGE",
    "SUPERSEDED",
    "FROZEN",
    "INVALIDATED",
    "EXPIRED",
    "REJECTED",
    "QUARANTINED",
]


@dataclass(frozen=True)
class ExecutionBoxPersistenceResult:
    status: ExecutionBoxPersistenceStatus
    reason_code: str | None = None
    box: ExecutionBoxV1 | None = None
    previous_box: ExecutionBoxV1 | None = None


class Strategy5SCRExecutionBoxV1Repository:
    def __init__(self, pg: PostgresClient = pg_client) -> None:
        self._pg = pg

    async def schema_status(self) -> ExecutionBoxV1SchemaStatus:
        if not self._pg.is_available:
            return ExecutionBoxV1SchemaStatus(
                (BOX_TABLE,),
                tuple(sorted(_REQUIRED_COLUMNS)),
                (),
                tuple(sorted(_REQUIRED_CONSTRAINTS)),
                (),
                tuple(sorted(_REQUIRED_INDEXES)),
                (),
                ("trg_strategy_5scr_execution_boxes_v1_guard",),
                (),
            )
        table_row = await self._pg.fetchrow(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname=current_schema() AND tablename=$1",
            BOX_TABLE,
        )
        columns = await self._pg.fetch(
            """
            SELECT column_name,data_type,is_nullable,character_maximum_length,column_default
            FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=$1
            """,
            BOX_TABLE,
        )
        constraints = await self._pg.fetch(
            """
            SELECT con.conname,con.contype::text AS contype,con.convalidated,
                   pg_get_constraintdef(con.oid) AS definition
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class cls ON cls.oid=con.conrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid=cls.relnamespace
            WHERE ns.nspname=current_schema() AND cls.relname=$1
            """,
            BOX_TABLE,
        )
        indexes = await self._pg.fetch(
            """
            SELECT index_cls.relname AS index_name,idx.indisunique,idx.indisvalid,idx.indisready,
                   pg_get_expr(idx.indpred,idx.indrelid) AS predicate,
                   ARRAY(SELECT attr.attname FROM unnest(idx.indkey) WITH ORDINALITY key(attnum,pos)
                         JOIN pg_catalog.pg_attribute attr ON attr.attrelid=idx.indrelid AND attr.attnum=key.attnum
                         ORDER BY key.pos) AS columns
            FROM pg_catalog.pg_index idx
            JOIN pg_catalog.pg_class cls ON cls.oid=idx.indrelid
            JOIN pg_catalog.pg_class index_cls ON index_cls.oid=idx.indexrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid=cls.relnamespace
            WHERE ns.nspname=current_schema() AND cls.relname=$1
            """,
            BOX_TABLE,
        )
        triggers = await self._pg.fetch(
            """
            SELECT trg.tgname,trg.tgenabled::text AS enabled,pg_get_triggerdef(trg.oid) AS definition,
                   pg_get_functiondef(proc.oid) AS function_definition
            FROM pg_catalog.pg_trigger trg
            JOIN pg_catalog.pg_class cls ON cls.oid=trg.tgrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid=cls.relnamespace
            JOIN pg_catalog.pg_proc proc ON proc.oid=trg.tgfoid
            WHERE ns.nspname=current_schema() AND cls.relname=$1 AND NOT trg.tgisinternal
            """,
            BOX_TABLE,
        )
        column_map = {str(_row_value(row, "column_name")): row for row in columns}
        invalid_columns: list[str] = []
        for name, expected in _REQUIRED_COLUMNS.items():
            row = column_map.get(name)
            if row is None:
                continue
            actual = (
                str(_row_value(row, "data_type")).lower(),
                str(_row_value(row, "is_nullable")).upper() == "YES",
                _row_value(row, "character_maximum_length"),
                _normalize_sql(_row_value(row, "column_default")),
            )
            if actual != expected:
                invalid_columns.append(name)
        constraint_map = {str(_row_value(row, "conname")): row for row in constraints}
        invalid_constraints: list[str] = []
        for name, (kind, fragments) in _REQUIRED_CONSTRAINTS.items():
            row = constraint_map.get(name)
            if row is None:
                continue
            definition = _normalize_sql(_row_value(row, "definition"))
            if (
                str(_row_value(row, "contype")) != kind
                or not bool(_row_value(row, "convalidated"))
                or not all(fragment in definition for fragment in fragments)
            ):
                invalid_constraints.append(name)
        index_map = {str(_row_value(row, "index_name")): row for row in indexes}
        invalid_indexes: list[str] = []
        for name, (unique, expected_columns, fragments) in _REQUIRED_INDEXES.items():
            row = index_map.get(name)
            if row is None:
                continue
            if (
                bool(_row_value(row, "indisunique")) != unique
                or not bool(_row_value(row, "indisvalid"))
                or not bool(_row_value(row, "indisready"))
                or tuple(_row_value(row, "columns") or ()) != expected_columns
                or not all(fragment in _normalize_sql(_row_value(row, "predicate")) for fragment in fragments)
            ):
                invalid_indexes.append(name)
        trigger_map = {str(_row_value(row, "tgname")): row for row in triggers}
        trigger_name = "trg_strategy_5scr_execution_boxes_v1_guard"
        invalid_triggers: list[str] = []
        trigger = trigger_map.get(trigger_name)
        if trigger is not None:
            definition = _normalize_sql(_row_value(trigger, "definition"))
            function = _normalize_sql(_row_value(trigger, "function_definition"))
            if (
                str(_row_value(trigger, "enabled")) not in {"O", "A"}
                or "before" not in definition
                or "delete" not in definition
                or "update" not in definition
                or "execution_box_geometry_immutable" not in function
                or "execution_box_transition_invalid" not in function
            ):
                invalid_triggers.append(trigger_name)
        return ExecutionBoxV1SchemaStatus(
            () if table_row is not None else (BOX_TABLE,),
            tuple(sorted(set(_REQUIRED_COLUMNS) - set(column_map))),
            tuple(sorted(invalid_columns)),
            tuple(sorted(set(_REQUIRED_CONSTRAINTS) - set(constraint_map))),
            tuple(sorted(invalid_constraints)),
            tuple(sorted(set(_REQUIRED_INDEXES) - set(index_map))),
            tuple(sorted(invalid_indexes)),
            () if trigger is not None else (trigger_name,),
            tuple(sorted(invalid_triggers)),
        )

    async def load_active(self, strategy_thesis_id: str) -> ExecutionBoxV1 | None:
        row = await self._pg.fetchrow(
            f"SELECT * FROM {BOX_TABLE} WHERE strategy_thesis_id=$1 AND state IN ('BUILDING','FROZEN')",
            strategy_thesis_id,
        )
        return None if row is None else _box_from_row(row)

    async def load_history(self, strategy_thesis_id: str) -> tuple[ExecutionBoxV1, ...]:
        rows = await self._pg.fetch(
            f"SELECT * FROM {BOX_TABLE} WHERE strategy_thesis_id=$1 ORDER BY box_version,execution_box_id",
            strategy_thesis_id,
        )
        return tuple(_box_from_row(row) for row in rows)

    async def process_evidence(self, evidence: ExecutionBoxEvidenceV1) -> ExecutionBoxPersistenceResult:
        async with self._pg.transaction() as connection:
            lifecycle = await connection.fetchrow(
                f"SELECT strategy_lifecycle_id,state FROM {LIFECYCLE_TABLE} WHERE strategy_lifecycle_id=$1 FOR UPDATE",
                evidence.strategy_lifecycle_id,
            )
            if lifecycle is None:
                return ExecutionBoxPersistenceResult("REJECTED", "CANONICAL_LIFECYCLE_MISSING")
            context = await connection.fetchrow(
                f"SELECT context_epoch_id,state FROM {CONTEXT_TABLE} "
                "WHERE context_epoch_id=$1 AND strategy_lifecycle_id=$2 FOR UPDATE",
                evidence.context_epoch_id,
                evidence.strategy_lifecycle_id,
            )
            if context is None:
                return ExecutionBoxPersistenceResult("REJECTED", "CONTEXT_EPOCH_MISSING")
            thesis_row = await connection.fetchrow(
                f"SELECT * FROM {THESIS_TABLE} WHERE strategy_thesis_id=$1 FOR UPDATE",
                evidence.strategy_thesis_id,
            )
            if thesis_row is None:
                return ExecutionBoxPersistenceResult("REJECTED", "DIRECTIONAL_THESIS_MISSING")
            thesis = _thesis_from_row(thesis_row)
            await Strategy5SCRDirectionalThesisV1Repository._validate_thesis_proof_chain(connection, thesis)
            lifecycle_active_row = await connection.fetchrow(
                f"SELECT * FROM {BOX_TABLE} WHERE strategy_lifecycle_id=$1 "
                "AND state IN ('BUILDING','FROZEN') FOR UPDATE",
                evidence.strategy_lifecycle_id,
            )
            lifecycle_active = None if lifecycle_active_row is None else _box_from_row(lifecycle_active_row)
            if lifecycle_active is not None and lifecycle_active.strategy_thesis_id != thesis.strategy_thesis_id:
                parent_row = await connection.fetchrow(
                    f"SELECT * FROM {THESIS_TABLE} WHERE strategy_thesis_id=$1 FOR UPDATE",
                    lifecycle_active.strategy_thesis_id,
                )
                if parent_row is None:
                    raise ExecutionBoxV1IntegrityError("ACTIVE_EXECUTION_BOX_THESIS_MISSING")
                prior_thesis = _thesis_from_row(parent_row)
                await Strategy5SCRDirectionalThesisV1Repository._validate_thesis_proof_chain(
                    connection,
                    prior_thesis,
                )
                if prior_thesis.state == "ACTIVE":
                    return ExecutionBoxPersistenceResult(
                        "REJECTED",
                        "ANOTHER_ACTIVE_THESIS_EXECUTION_BOX_EXISTS",
                        lifecycle_active,
                    )
                closed = close_execution_box(
                    lifecycle_active,
                    state="INVALIDATED",
                    occurred_at_utc=max(lifecycle_active.opened_at_utc, evidence.observed_at_utc),
                )
                await self._transition_box(connection, lifecycle_active, closed, evidence)
                lifecycle_active = None
            active_row = await connection.fetchrow(
                f"SELECT * FROM {BOX_TABLE} WHERE strategy_thesis_id=$1 AND state IN ('BUILDING','FROZEN') FOR UPDATE",
                thesis.strategy_thesis_id,
            )
            current = None if active_row is None else _box_from_row(active_row)
            if (
                thesis.state != "ACTIVE"
                or str(_row_value(context, "state")) != "ACTIVE"
                or str(_row_value(lifecycle, "state")) in {"TERMINAL_NO_TRADE", "INVALIDATED", "SUPERSEDED"}
            ):
                if current is None:
                    return ExecutionBoxPersistenceResult("REJECTED", "EXECUTION_BOX_PARENT_NOT_ACTIVE")
                closed = close_execution_box(
                    current,
                    state="INVALIDATED",
                    occurred_at_utc=max(current.opened_at_utc, evidence.observed_at_utc),
                )
                await self._transition_box(connection, current, closed, evidence)
                return ExecutionBoxPersistenceResult("INVALIDATED", "EXECUTION_BOX_PARENT_NOT_ACTIVE", closed)
            next_sequence = int(
                await connection.fetchval(
                    f"SELECT COALESCE(MAX(box_sequence),0)+1 FROM {BOX_TABLE} WHERE strategy_lifecycle_id=$1",
                    thesis.strategy_lifecycle_id,
                )
            )
            reduced = reduce_execution_box(
                thesis=thesis,
                evidence=evidence,
                current=current,
                next_sequence=next_sequence,
            )
            if reduced.status in {"DUPLICATE", "NO_CHANGE", "REJECTED", "QUARANTINED"}:
                return ExecutionBoxPersistenceResult(
                    cast(ExecutionBoxPersistenceStatus, reduced.status),
                    reduced.reason_code,
                    reduced.box,
                    reduced.previous_box,
                )
            if reduced.box is None:
                raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_REDUCTION_MISSING_STATE")
            if reduced.status == "FROZEN" and reduced.previous_box is not None:
                await self._transition_box(connection, reduced.previous_box, reduced.box, evidence)
            elif reduced.status == "SUPERSEDED":
                if reduced.previous_box is None:
                    raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_PREDECESSOR_MISSING")
                await self._transition_box(connection, current, reduced.previous_box, evidence)  # type: ignore[arg-type]
                await self._insert_box(connection, reduced.box, evidence)
            else:
                await self._insert_box(connection, reduced.box, evidence)
            return ExecutionBoxPersistenceResult(
                "PERSISTED" if reduced.status == "OPENED" else cast(ExecutionBoxPersistenceStatus, reduced.status),
                reduced.reason_code,
                reduced.box,
                reduced.previous_box,
            )

    async def _insert_box(self, connection: Any, box: ExecutionBoxV1, evidence: ExecutionBoxEvidenceV1) -> None:
        result = await connection.execute(
            f"""
            INSERT INTO {BOX_TABLE} (
                execution_box_id,strategy_lifecycle_id,context_epoch_id,strategy_thesis_id,
                box_sequence,box_version,previous_execution_box_id,symbol,strategy_direction,
                route_type,state,box_low,box_high,opened_at,frozen_at,freeze_authority_hash,superseded_at,
                invalidated_at,consumed_at,expired_at,material_box_hash,evidence_hash,
                thesis_semantic_identity_hash,source_m1_ids,source_m1_evidence_ids,
                last_observed_at,last_source_request_id,state_version,rule_version,
                valid_for_execution,execution_authority,payload,evidence_payload,freeze_evidence_payload
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                $21,$22,$23,$24::jsonb,$25::jsonb,$26,$27,$28,$29,false,false,$30::jsonb,$31::jsonb,$32::jsonb
            )
            """,
            box.execution_box_id,
            box.strategy_lifecycle_id,
            box.context_epoch_id,
            box.strategy_thesis_id,
            box.box_sequence,
            box.box_version,
            box.previous_execution_box_id,
            box.symbol,
            box.strategy_direction,
            box.route_type,
            box.state,
            box.box_low,
            box.box_high,
            box.opened_at_utc,
            box.frozen_at_utc,
            box.freeze_authority_hash,
            box.superseded_at_utc,
            box.invalidated_at_utc,
            box.consumed_at_utc,
            box.expired_at_utc,
            box.material_box_hash,
            box.evidence_hash,
            box.thesis_semantic_identity_hash,
            json.dumps(list(box.source_m1_ids), separators=(",", ":")),
            json.dumps(list(box.source_m1_evidence_ids), separators=(",", ":")),
            box.last_observed_at_utc,
            box.last_source_request_id,
            box.state_version,
            box.rule_version,
            json.dumps(box.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            json.dumps(evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            (
                json.dumps(evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
                if box.freeze_authority_hash is not None
                else None
            ),
        )
        if not str(result).endswith(" 1"):
            raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_INSERT_FAILED")

    async def _transition_box(
        self,
        connection: Any,
        previous: ExecutionBoxV1,
        updated: ExecutionBoxV1,
        evidence: ExecutionBoxEvidenceV1,
    ) -> None:
        result = await connection.execute(
            f"""
            UPDATE {BOX_TABLE} SET state=$2,frozen_at=$3,freeze_authority_hash=$4,
                freeze_evidence_payload=CASE WHEN $5::jsonb IS NULL THEN freeze_evidence_payload ELSE $5::jsonb END,
                superseded_at=$6,invalidated_at=$7,consumed_at=$8,expired_at=$9,last_observed_at=$10,
                last_source_request_id=$11,state_version=$12,payload=$13::jsonb,updated_at=now()
            WHERE execution_box_id=$1 AND state_version=$14
            """,
            updated.execution_box_id,
            updated.state,
            updated.frozen_at_utc,
            updated.freeze_authority_hash,
            (
                json.dumps(evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
                if previous.state == "BUILDING" and updated.state == "FROZEN"
                else None
            ),
            updated.superseded_at_utc,
            updated.invalidated_at_utc,
            updated.consumed_at_utc,
            updated.expired_at_utc,
            updated.last_observed_at_utc,
            updated.last_source_request_id,
            updated.state_version,
            json.dumps(updated.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            previous.state_version,
        )
        if not str(result).endswith(" 1"):
            raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_STATE_VERSION_NOT_ADVANCED")


__all__ = [
    "BOX_TABLE",
    "EXECUTION_BOX_V1_SHADOW_ONLY_FLAG",
    "EXECUTION_BOX_V1_WRITER_FLAG",
    "ExecutionBoxPersistenceResult",
    "ExecutionBoxV1IntegrityError",
    "ExecutionBoxV1RuntimeConfig",
    "ExecutionBoxV1SchemaStatus",
    "Strategy5SCRExecutionBoxV1Repository",
]
