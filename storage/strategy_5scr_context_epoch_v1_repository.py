"""Atomic shadow-only persistence for Strategy 5S-CR ContextEpoch V1.

The repository accepts material context evidence only when its pressure event
is already linked to a canonical Lifecycle V2 row.  It serializes every fold
under the lifecycle row lock, stores the epoch boundary and transition in one
transaction, and never grants execution authority.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from analysis.strategy_5scr_context_epoch_v1 import (
    ContextEpochReducerV1,
    context_evidence_failure,
    context_evidence_hash,
    material_context_hash,
)
from contracts.strategy_5scr_context_epoch_v1 import (
    ContextEpochState,
    ContextTransitionReason,
    ContextTransitionV1,
    DirectionDomain,
    MaterialContextEvidenceV1,
    StrategyContextEpochV1,
)
from contracts.strategy_5scr_lifecycle_v2 import TERMINAL_LIFECYCLE_STATES
from storage.postgres_client import PostgresClient, pg_client

EPOCH_TABLE = "strategy_5scr_context_epochs_v1"
TRANSITION_TABLE = "strategy_5scr_context_transitions_v1"
LIFECYCLE_TABLE = "strategy_5scr_analysis_lifecycles_v2"
LIFECYCLE_LINK_TABLE = "strategy_5scr_lifecycle_event_links_v2"

CONTEXT_EPOCH_V1_WRITER_FLAG = "STRATEGY_5SCR_CONTEXT_EPOCH_V1_WRITER_ENABLED"
CONTEXT_EPOCH_V1_SHADOW_ONLY_FLAG = "STRATEGY_5SCR_CONTEXT_EPOCH_V1_SHADOW_ONLY"

_REQUIRED_TABLES = frozenset({EPOCH_TABLE, TRANSITION_TABLE})


@dataclass(frozen=True)
class _ColumnContract:
    data_type: str
    nullable: bool
    max_length: int | None = None
    default: str = ""


_REQUIRED_COLUMNS: dict[tuple[str, str], _ColumnContract] = {
    (EPOCH_TABLE, "context_epoch_id"): _ColumnContract("text", False),
    (EPOCH_TABLE, "strategy_lifecycle_id"): _ColumnContract("text", False),
    (EPOCH_TABLE, "symbol"): _ColumnContract("character varying", False, 32),
    (EPOCH_TABLE, "epoch_sequence"): _ColumnContract("integer", False),
    (EPOCH_TABLE, "state"): _ColumnContract("character varying", False, 20),
    (EPOCH_TABLE, "material_context_hash"): _ColumnContract("character varying", False, 71),
    (EPOCH_TABLE, "opened_at"): _ColumnContract("timestamp with time zone", False),
    (EPOCH_TABLE, "last_confirmed_at"): _ColumnContract("timestamp with time zone", False),
    (EPOCH_TABLE, "closed_at"): _ColumnContract("timestamp with time zone", True),
    (EPOCH_TABLE, "daily_source_candle_ids"): _ColumnContract("jsonb", False),
    (EPOCH_TABLE, "h4_source_candle_ids"): _ColumnContract("jsonb", False),
    (EPOCH_TABLE, "daily_bias"): _ColumnContract("character varying", False, 100),
    (EPOCH_TABLE, "h4_structure"): _ColumnContract("character varying", False, 100),
    (EPOCH_TABLE, "price_location"): _ColumnContract("character varying", False, 100),
    (EPOCH_TABLE, "liquidity_state"): _ColumnContract("character varying", False, 100),
    (EPOCH_TABLE, "direction_domain"): _ColumnContract("character varying", False, 24),
    (EPOCH_TABLE, "allowed_routes"): _ColumnContract("jsonb", False),
    (EPOCH_TABLE, "blocked_routes"): _ColumnContract("jsonb", False),
    (EPOCH_TABLE, "target_map_version"): _ColumnContract("character varying", True, 100),
    (EPOCH_TABLE, "structural_invalidation_version"): _ColumnContract("character varying", True, 100),
    (EPOCH_TABLE, "transition_reason"): _ColumnContract("character varying", False, 32),
    (EPOCH_TABLE, "evidence_hash"): _ColumnContract("character varying", False, 71),
    (EPOCH_TABLE, "evidence_payload"): _ColumnContract("jsonb", False),
    (EPOCH_TABLE, "last_observed_at"): _ColumnContract("timestamp with time zone", False),
    (EPOCH_TABLE, "last_source_event_id"): _ColumnContract("text", False),
    (EPOCH_TABLE, "state_version"): _ColumnContract("bigint", False),
    (EPOCH_TABLE, "execution_authority"): _ColumnContract("boolean", False, default="false"),
    (EPOCH_TABLE, "created_at"): _ColumnContract("timestamp with time zone", False, default="now()"),
    (EPOCH_TABLE, "updated_at"): _ColumnContract("timestamp with time zone", False, default="now()"),
    (TRANSITION_TABLE, "transition_id"): _ColumnContract("text", False),
    (TRANSITION_TABLE, "strategy_lifecycle_id"): _ColumnContract("text", False),
    (TRANSITION_TABLE, "from_context_epoch_id"): _ColumnContract("text", True),
    (TRANSITION_TABLE, "to_context_epoch_id"): _ColumnContract("text", True),
    (TRANSITION_TABLE, "reason"): _ColumnContract("character varying", False, 32),
    (TRANSITION_TABLE, "source_pressure_event_id"): _ColumnContract("text", False),
    (TRANSITION_TABLE, "source_event_ids"): _ColumnContract("jsonb", False),
    (TRANSITION_TABLE, "occurred_at"): _ColumnContract("timestamp with time zone", False),
    (TRANSITION_TABLE, "material_context_hash"): _ColumnContract("character varying", False, 71),
    (TRANSITION_TABLE, "evidence_hash"): _ColumnContract("character varying", False, 71),
    (TRANSITION_TABLE, "dedupe_key"): _ColumnContract("text", False),
    (TRANSITION_TABLE, "payload"): _ColumnContract("jsonb", False),
    (TRANSITION_TABLE, "evidence_payload"): _ColumnContract("jsonb", False),
    (TRANSITION_TABLE, "execution_authority"): _ColumnContract("boolean", False, default="false"),
    (TRANSITION_TABLE, "created_at"): _ColumnContract("timestamp with time zone", False, default="now()"),
}

# Readiness checks the owning table, constraint type, validation state, and
# normalized definition fragments.  The PostgreSQL tests deliberately weaken
# each critical definition while preserving its name.
_REQUIRED_CONSTRAINTS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    f"{EPOCH_TABLE}_pkey": (EPOCH_TABLE, "p", ("primary key (context_epoch_id)",)),
    "fk_5scr_context_epoch_lifecycle_v1": (
        EPOCH_TABLE,
        "f",
        ("foreign key (strategy_lifecycle_id)", "strategy_5scr_analysis_lifecycles_v2", "on delete restrict"),
    ),
    "uq_5scr_context_epoch_sequence_v1": (
        EPOCH_TABLE,
        "u",
        ("unique (strategy_lifecycle_id, epoch_sequence)",),
    ),
    "ck_5scr_context_epoch_identity_v1": (
        EPOCH_TABLE,
        "c",
        ("context_epoch_id", "5scr-context:", "material_context_hash", "evidence_hash", "sha256:"),
    ),
    "ck_5scr_context_epoch_versions_v1": (
        EPOCH_TABLE,
        "c",
        ("epoch_sequence >= 1", "state_version >= 1"),
    ),
    "ck_5scr_context_epoch_state_v1": (
        EPOCH_TABLE,
        "c",
        ("active", "superseded", "terminal"),
    ),
    "ck_5scr_context_epoch_direction_v1": (
        EPOCH_TABLE,
        "c",
        ("buy_only", "sell_only", "both_conditional", "unresolved", "empty"),
    ),
    "ck_5scr_context_epoch_reason_v1": (
        EPOCH_TABLE,
        "c",
        ("opened", "material_context_changed", "lifecycle_terminal"),
    ),
    "ck_5scr_context_epoch_evidence_arrays_v1": (
        EPOCH_TABLE,
        "c",
        ("daily_source_candle_ids", "h4_source_candle_ids", "allowed_routes", "blocked_routes", "jsonb_typeof"),
    ),
    "ck_5scr_context_epoch_temporal_v1": (
        EPOCH_TABLE,
        "c",
        ("last_confirmed_at >= opened_at", "last_observed_at >= opened_at", "closed_at", "active", "terminal"),
    ),
    "ck_5scr_context_epoch_shadow_only_v1": (
        EPOCH_TABLE,
        "c",
        ("execution_authority is false",),
    ),
    f"{TRANSITION_TABLE}_pkey": (TRANSITION_TABLE, "p", ("primary key (transition_id)",)),
    "fk_5scr_context_transition_lifecycle_v1": (
        TRANSITION_TABLE,
        "f",
        ("foreign key (strategy_lifecycle_id)", "strategy_5scr_analysis_lifecycles_v2", "on delete restrict"),
    ),
    "fk_5scr_context_transition_from_v1": (
        TRANSITION_TABLE,
        "f",
        ("foreign key (from_context_epoch_id)", EPOCH_TABLE, "on delete restrict"),
    ),
    "fk_5scr_context_transition_to_v1": (
        TRANSITION_TABLE,
        "f",
        ("foreign key (to_context_epoch_id)", EPOCH_TABLE, "on delete restrict"),
    ),
    "fk_5scr_context_transition_source_v1": (
        TRANSITION_TABLE,
        "f",
        ("foreign key (source_pressure_event_id)", LIFECYCLE_LINK_TABLE, "on delete restrict"),
    ),
    "ck_5scr_context_transition_identity_v1": (
        TRANSITION_TABLE,
        "c",
        ("transition_id", "5scr-context-transition:", "material_context_hash", "evidence_hash", "sha256:"),
    ),
    "ck_5scr_context_transition_shape_v1": (
        TRANSITION_TABLE,
        "c",
        ("opened", "material_context_changed", "lifecycle_terminal", "from_context_epoch_id", "to_context_epoch_id"),
    ),
    "ck_5scr_context_transition_sources_v1": (
        TRANSITION_TABLE,
        "c",
        ("jsonb_typeof(source_event_ids)", "jsonb_array_length(source_event_ids) > 0"),
    ),
    "ck_5scr_context_transition_shadow_only_v1": (
        TRANSITION_TABLE,
        "c",
        ("execution_authority is false",),
    ),
}

_CANONICAL_CONSTRAINT_DEFINITIONS: dict[str, str] = {
    f"{EPOCH_TABLE}_pkey": "PRIMARY KEY (context_epoch_id)",
    "fk_5scr_context_epoch_lifecycle_v1": (
        "FOREIGN KEY (strategy_lifecycle_id) REFERENCES "
        "strategy_5scr_analysis_lifecycles_v2(strategy_lifecycle_id) ON DELETE RESTRICT"
    ),
    "uq_5scr_context_epoch_sequence_v1": "UNIQUE (strategy_lifecycle_id, epoch_sequence)",
    "ck_5scr_context_epoch_identity_v1": (
        "CHECK (((context_epoch_id ~ '^5scr-context:[0-9a-f]{32}$'::text) "
        "AND ((material_context_hash)::text ~ '^sha256:[0-9a-f]{64}$'::text) "
        "AND ((evidence_hash)::text ~ '^sha256:[0-9a-f]{64}$'::text)))"
    ),
    "ck_5scr_context_epoch_versions_v1": ("CHECK (((epoch_sequence >= 1) AND (state_version >= 1)))"),
    "ck_5scr_context_epoch_state_v1": (
        "CHECK (((state)::text = ANY ((ARRAY['ACTIVE'::character varying, "
        "'SUPERSEDED'::character varying, 'TERMINAL'::character varying])::text[])))"
    ),
    "ck_5scr_context_epoch_direction_v1": (
        "CHECK (((direction_domain)::text = ANY ((ARRAY['BUY_ONLY'::character varying, "
        "'SELL_ONLY'::character varying, 'BOTH_CONDITIONAL'::character varying, "
        "'UNRESOLVED'::character varying, 'EMPTY'::character varying])::text[])))"
    ),
    "ck_5scr_context_epoch_reason_v1": (
        "CHECK (((transition_reason)::text = ANY ((ARRAY['OPENED'::character varying, "
        "'MATERIAL_CONTEXT_CHANGED'::character varying, "
        "'LIFECYCLE_TERMINAL'::character varying])::text[])))"
    ),
    "ck_5scr_context_epoch_evidence_arrays_v1": (
        "CHECK (((jsonb_typeof(daily_source_candle_ids) = 'array'::text) "
        "AND (jsonb_array_length(daily_source_candle_ids) > 0) "
        "AND (jsonb_typeof(h4_source_candle_ids) = 'array'::text) "
        "AND (jsonb_array_length(h4_source_candle_ids) > 0) "
        "AND (jsonb_typeof(allowed_routes) = 'array'::text) "
        "AND (jsonb_typeof(blocked_routes) = 'array'::text)))"
    ),
    "ck_5scr_context_epoch_temporal_v1": (
        "CHECK (((last_confirmed_at >= opened_at) AND (last_observed_at >= opened_at) "
        "AND ((((state)::text = 'ACTIVE'::text) AND (closed_at IS NULL)) "
        "OR (((state)::text = ANY ((ARRAY['SUPERSEDED'::character varying, "
        "'TERMINAL'::character varying])::text[])) "
        "AND (closed_at >= last_confirmed_at) AND (closed_at >= last_observed_at)))))"
    ),
    "ck_5scr_context_epoch_shadow_only_v1": "CHECK ((execution_authority IS FALSE))",
    f"{TRANSITION_TABLE}_pkey": "PRIMARY KEY (transition_id)",
    "fk_5scr_context_transition_lifecycle_v1": (
        "FOREIGN KEY (strategy_lifecycle_id) REFERENCES "
        "strategy_5scr_analysis_lifecycles_v2(strategy_lifecycle_id) ON DELETE RESTRICT"
    ),
    "fk_5scr_context_transition_from_v1": (
        "FOREIGN KEY (from_context_epoch_id) REFERENCES "
        "strategy_5scr_context_epochs_v1(context_epoch_id) ON DELETE RESTRICT"
    ),
    "fk_5scr_context_transition_to_v1": (
        "FOREIGN KEY (to_context_epoch_id) REFERENCES "
        "strategy_5scr_context_epochs_v1(context_epoch_id) ON DELETE RESTRICT"
    ),
    "fk_5scr_context_transition_source_v1": (
        "FOREIGN KEY (source_pressure_event_id) REFERENCES "
        "strategy_5scr_lifecycle_event_links_v2(pressure_event_id) ON DELETE RESTRICT"
    ),
    "ck_5scr_context_transition_identity_v1": (
        "CHECK (((transition_id ~ '^5scr-context-transition:[0-9a-f]{32}$'::text) "
        "AND ((material_context_hash)::text ~ '^sha256:[0-9a-f]{64}$'::text) "
        "AND ((evidence_hash)::text ~ '^sha256:[0-9a-f]{64}$'::text)))"
    ),
    "ck_5scr_context_transition_shape_v1": (
        "CHECK (((((reason)::text = 'OPENED'::text) AND (from_context_epoch_id IS NULL) "
        "AND (to_context_epoch_id IS NOT NULL)) OR (((reason)::text = "
        "'MATERIAL_CONTEXT_CHANGED'::text) AND (from_context_epoch_id IS NOT NULL) "
        "AND (to_context_epoch_id IS NOT NULL) AND (from_context_epoch_id <> to_context_epoch_id)) "
        "OR (((reason)::text = 'LIFECYCLE_TERMINAL'::text) "
        "AND (from_context_epoch_id IS NOT NULL) AND (to_context_epoch_id IS NULL))))"
    ),
    "ck_5scr_context_transition_sources_v1": (
        "CHECK (((jsonb_typeof(source_event_ids) = 'array'::text) AND (jsonb_array_length(source_event_ids) > 0)))"
    ),
    "ck_5scr_context_transition_shadow_only_v1": "CHECK ((execution_authority IS FALSE))",
}

_REQUIRED_INDEXES: dict[str, tuple[str, bool, tuple[str, ...], str]] = {
    "uq_5scr_context_active_lifecycle_v1": (
        EPOCH_TABLE,
        True,
        ("strategy_lifecycle_id",),
        "((state)::text = 'ACTIVE'::text)",
    ),
    "ix_5scr_context_lifecycle_history_v1": (
        EPOCH_TABLE,
        False,
        ("strategy_lifecycle_id", "epoch_sequence", "context_epoch_id"),
        "",
    ),
    "uq_5scr_context_transition_dedupe_v1": (
        TRANSITION_TABLE,
        True,
        ("dedupe_key",),
        "",
    ),
    "ix_5scr_context_transition_lifecycle_time_v1": (
        TRANSITION_TABLE,
        False,
        ("strategy_lifecycle_id", "occurred_at", "transition_id"),
        "",
    ),
}


def _enabled(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() == "true"


@dataclass(frozen=True)
class ContextEpochV1RuntimeConfig:
    enabled: bool = False
    shadow_only: bool = True

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ContextEpochV1RuntimeConfig:
        source = os.environ if environ is None else environ
        return cls(
            enabled=_enabled(source.get(CONTEXT_EPOCH_V1_WRITER_FLAG), default=False),
            shadow_only=_enabled(source.get(CONTEXT_EPOCH_V1_SHADOW_ONLY_FLAG), default=True),
        )

    def validate(self) -> None:
        if self.enabled and not self.shadow_only:
            raise RuntimeError("STRATEGY_5SCR_CONTEXT_EPOCH_V1_SHADOW_ONLY_REQUIRED")


@dataclass(frozen=True)
class ContextEpochV1SchemaStatus:
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


ContextEpochPersistenceStatus = Literal[
    "PERSISTED",
    "NO_CHANGE",
    "DUPLICATE",
    "REJECTED",
    "WAITING_CONTEXT_EVIDENCE",
    "QUARANTINED_CONTEXT_EVIDENCE",
]


@dataclass(frozen=True)
class ContextEpochPersistenceResult:
    status: ContextEpochPersistenceStatus
    reason_code: str | None = None
    strategy_lifecycle_id: str | None = None
    epoch: StrategyContextEpochV1 | None = None
    transition_id: str | None = None


class ContextEpochV1PersistenceError(RuntimeError):
    """Base error for atomic durable ContextEpoch persistence."""


class ContextEpochV1IntegrityError(ContextEpochV1PersistenceError):
    """Raised when durable epoch and transition identities disagree."""


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _normalize_sql(value: Any) -> str:
    return " ".join(str(value or "").replace('"', "").lower().split())


def _json_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ContextEpochV1IntegrityError("CONTEXT_EPOCH_JSON_ARRAY_INVALID")
    return tuple(str(item) for item in value)


def _epoch_from_row(row: Any) -> StrategyContextEpochV1:
    payload = _row_value(row, "evidence_payload")
    if isinstance(payload, str):
        payload = json.loads(payload)
    evidence = MaterialContextEvidenceV1.model_validate(payload)
    durable_evidence_hash = str(_row_value(row, "evidence_hash"))
    if context_evidence_hash(evidence) != durable_evidence_hash:
        raise ContextEpochV1IntegrityError("CONTEXT_EPOCH_EVIDENCE_HASH_DRIFT")
    epoch = StrategyContextEpochV1(
        context_epoch_id=str(_row_value(row, "context_epoch_id")),
        strategy_lifecycle_id=str(_row_value(row, "strategy_lifecycle_id")),
        symbol=str(_row_value(row, "symbol")),
        epoch_sequence=int(_row_value(row, "epoch_sequence")),
        state=cast(ContextEpochState, str(_row_value(row, "state"))),
        material_context_hash=str(_row_value(row, "material_context_hash")),
        opened_at_utc=_row_value(row, "opened_at"),
        last_confirmed_at_utc=_row_value(row, "last_confirmed_at"),
        closed_at_utc=_row_value(row, "closed_at"),
        daily_source_candle_ids=_json_tuple(_row_value(row, "daily_source_candle_ids")),
        h4_source_candle_ids=_json_tuple(_row_value(row, "h4_source_candle_ids")),
        daily_bias=str(_row_value(row, "daily_bias")),
        h4_structure=str(_row_value(row, "h4_structure")),
        price_location=str(_row_value(row, "price_location")),
        liquidity_state=str(_row_value(row, "liquidity_state")),
        direction_domain=cast(DirectionDomain, str(_row_value(row, "direction_domain"))),
        allowed_routes=_json_tuple(_row_value(row, "allowed_routes")),
        blocked_routes=_json_tuple(_row_value(row, "blocked_routes")),
        target_map_version=_row_value(row, "target_map_version"),
        structural_invalidation_version=_row_value(row, "structural_invalidation_version"),
        transition_reason=cast(ContextTransitionReason, str(_row_value(row, "transition_reason"))),
        evidence_hash=durable_evidence_hash,
        last_observed_at_utc=_row_value(row, "last_observed_at"),
        last_source_event_id=str(_row_value(row, "last_source_event_id")),
        state_version=int(_row_value(row, "state_version")),
        execution_authority=cast(Literal[False], bool(_row_value(row, "execution_authority"))),
    )
    if epoch.state != "TERMINAL" and material_context_hash(evidence) != epoch.material_context_hash:
        raise ContextEpochV1IntegrityError("CONTEXT_EPOCH_MATERIAL_HASH_DRIFT")
    return epoch


class StrategyContextEpochV1Repository:
    """Fold linked material context evidence under a lifecycle row lock."""

    def __init__(self, *, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client

    @property
    def is_available(self) -> bool:
        return self._pg.is_available

    async def schema_status(self) -> ContextEpochV1SchemaStatus:
        expected_columns = tuple(sorted(f"{table}.{column}" for table, column in _REQUIRED_COLUMNS))
        if not self._pg.is_available:
            return ContextEpochV1SchemaStatus(
                missing_tables=tuple(sorted(_REQUIRED_TABLES)),
                missing_columns=expected_columns,
                invalid_columns=(),
                missing_constraints=tuple(sorted(_REQUIRED_CONSTRAINTS)),
                invalid_constraints=(),
                missing_indexes=tuple(sorted(_REQUIRED_INDEXES)),
                invalid_indexes=(),
            )
        table_rows = await self._pg.fetch(
            """
            SELECT tablename FROM pg_catalog.pg_tables
            WHERE schemaname = current_schema() AND tablename = ANY($1::text[])
            """,
            sorted(_REQUIRED_TABLES),
        )
        column_rows = await self._pg.fetch(
            """
            SELECT table_name, column_name, data_type, is_nullable,
                   character_maximum_length, column_default
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = ANY($1::text[])
            """,
            sorted(_REQUIRED_TABLES),
        )
        constraint_rows = await self._pg.fetch(
            """
            SELECT con.conname, con.contype::text AS contype, con.convalidated,
                   cls.relname AS table_name, pg_get_constraintdef(con.oid) AS definition
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class cls ON cls.oid = con.conrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema() AND con.conname = ANY($1::text[])
            """,
            sorted(_REQUIRED_CONSTRAINTS),
        )
        index_rows = await self._pg.fetch(
            """
            SELECT table_cls.relname AS table_name, index_cls.relname AS index_name,
                   idx.indisunique, idx.indisvalid, idx.indisready,
                   pg_get_expr(idx.indpred, idx.indrelid) AS predicate,
                   ARRAY(
                       SELECT attr.attname
                       FROM unnest(idx.indkey) WITH ORDINALITY key(attnum, position)
                       JOIN pg_catalog.pg_attribute attr
                         ON attr.attrelid = idx.indrelid AND attr.attnum = key.attnum
                       ORDER BY key.position
                   ) AS columns
            FROM pg_catalog.pg_index idx
            JOIN pg_catalog.pg_class table_cls ON table_cls.oid = idx.indrelid
            JOIN pg_catalog.pg_class index_cls ON index_cls.oid = idx.indexrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = table_cls.relnamespace
            WHERE ns.nspname = current_schema() AND index_cls.relname = ANY($1::text[])
            """,
            sorted(_REQUIRED_INDEXES),
        )

        present_tables = {str(_row_value(row, "tablename") or "") for row in table_rows}
        columns = {
            (str(_row_value(row, "table_name")), str(_row_value(row, "column_name"))): row for row in column_rows
        }
        satisfied_columns: set[str] = set()
        invalid_columns: list[str] = []
        for key, expected in _REQUIRED_COLUMNS.items():
            row = columns.get(key)
            if row is None:
                continue
            label = f"{key[0]}.{key[1]}"
            data_type = str(_row_value(row, "data_type") or "").lower()
            nullable = str(_row_value(row, "is_nullable") or "").upper() == "YES"
            raw_length = _row_value(row, "character_maximum_length")
            max_length = None if raw_length is None else int(raw_length)
            default = _normalize_sql(_row_value(row, "column_default"))
            if data_type != expected.data_type:
                invalid_columns.append(f"{label}:type={data_type or 'missing'}")
            elif nullable != expected.nullable:
                invalid_columns.append(f"{label}:nullable={str(nullable).lower()}")
            elif max_length != expected.max_length:
                invalid_columns.append(f"{label}:max_length={max_length}")
            elif default != expected.default:
                invalid_columns.append(f"{label}:default={default or 'missing'}")
            else:
                satisfied_columns.add(label)

        constraints = {str(_row_value(row, "conname") or ""): row for row in constraint_rows}
        invalid_constraints: list[str] = []
        for name, (table, contype, _definition_fragments) in _REQUIRED_CONSTRAINTS.items():
            row = constraints.get(name)
            if row is None:
                continue
            definition = _normalize_sql(_row_value(row, "definition"))
            if str(_row_value(row, "table_name")) != table:
                invalid_constraints.append(f"{name}:table")
            elif str(_row_value(row, "contype")) != contype:
                invalid_constraints.append(f"{name}:type")
            elif not bool(_row_value(row, "convalidated")):
                invalid_constraints.append(f"{name}:not_validated")
            elif definition != _normalize_sql(_CANONICAL_CONSTRAINT_DEFINITIONS[name]):
                invalid_constraints.append(f"{name}:definition")

        indexes = {str(_row_value(row, "index_name") or ""): row for row in index_rows}
        invalid_indexes: list[str] = []
        for name, (table, unique, expected_index_columns, expected_predicate) in _REQUIRED_INDEXES.items():
            row = indexes.get(name)
            if row is None:
                continue
            actual_columns = tuple(str(value) for value in (_row_value(row, "columns") or ()))
            predicate = _normalize_sql(_row_value(row, "predicate"))
            if str(_row_value(row, "table_name")) != table:
                invalid_indexes.append(f"{name}:table")
            elif bool(_row_value(row, "indisunique")) != unique:
                invalid_indexes.append(f"{name}:unique")
            elif not bool(_row_value(row, "indisvalid")):
                invalid_indexes.append(f"{name}:not_valid")
            elif not bool(_row_value(row, "indisready")):
                invalid_indexes.append(f"{name}:not_ready")
            elif actual_columns != expected_index_columns:
                invalid_indexes.append(f"{name}:columns")
            elif predicate != _normalize_sql(expected_predicate):
                invalid_indexes.append(f"{name}:predicate")

        invalid_column_labels = {item.split(":", 1)[0] for item in invalid_columns}
        return ContextEpochV1SchemaStatus(
            missing_tables=tuple(sorted(_REQUIRED_TABLES - present_tables)),
            missing_columns=tuple(sorted(set(expected_columns) - satisfied_columns - invalid_column_labels)),
            invalid_columns=tuple(sorted(invalid_columns)),
            missing_constraints=tuple(sorted(set(_REQUIRED_CONSTRAINTS) - set(constraints))),
            invalid_constraints=tuple(sorted(invalid_constraints)),
            missing_indexes=tuple(sorted(set(_REQUIRED_INDEXES) - set(indexes))),
            invalid_indexes=tuple(sorted(invalid_indexes)),
        )

    async def load_latest(self, strategy_lifecycle_id: str) -> StrategyContextEpochV1 | None:
        row = await self._pg.fetchrow(
            f"SELECT * FROM {EPOCH_TABLE} WHERE strategy_lifecycle_id = $1 ORDER BY epoch_sequence DESC LIMIT 1",
            strategy_lifecycle_id,
        )
        return None if row is None else _epoch_from_row(row)

    async def load_history(self, strategy_lifecycle_id: str) -> tuple[StrategyContextEpochV1, ...]:
        rows = await self._pg.fetch(
            f"SELECT * FROM {EPOCH_TABLE} WHERE strategy_lifecycle_id = $1 ORDER BY epoch_sequence, context_epoch_id",
            strategy_lifecycle_id,
        )
        return tuple(_epoch_from_row(row) for row in rows)

    async def process_evidence(self, evidence: MaterialContextEvidenceV1) -> ContextEpochPersistenceResult:
        """Validate, reduce, and persist one ordered material-context observation."""

        async with self._pg.transaction() as connection:
            lifecycle = await connection.fetchrow(
                f"""
                SELECT lifecycle.strategy_lifecycle_id, lifecycle.symbol, lifecycle.state
                FROM {LIFECYCLE_LINK_TABLE} link
                JOIN {LIFECYCLE_TABLE} lifecycle
                  ON lifecycle.strategy_lifecycle_id = link.strategy_lifecycle_id
                WHERE link.pressure_event_id = $1
                FOR UPDATE OF lifecycle
                """,
                evidence.source_pressure_event_id,
            )
            if lifecycle is None:
                return ContextEpochPersistenceResult(status="REJECTED", reason_code="NO_CANONICAL_LIFECYCLE_LINK")

            lifecycle_id = str(_row_value(lifecycle, "strategy_lifecycle_id"))
            lifecycle_symbol = str(_row_value(lifecycle, "symbol")).upper()
            lifecycle_state = str(_row_value(lifecycle, "state"))
            if lifecycle_symbol != evidence.symbol:
                return ContextEpochPersistenceResult(
                    status="REJECTED",
                    reason_code="LIFECYCLE_SYMBOL_MISMATCH",
                    strategy_lifecycle_id=lifecycle_id,
                )

            epoch_row = await connection.fetchrow(
                f"SELECT * FROM {EPOCH_TABLE} WHERE strategy_lifecycle_id = $1 "
                "ORDER BY epoch_sequence DESC LIMIT 1 FOR UPDATE",
                lifecycle_id,
            )
            current = None if epoch_row is None else _epoch_from_row(epoch_row)
            reducer = ContextEpochReducerV1(lifecycle_id, lifecycle_symbol, initial_epoch=current)
            if lifecycle_state in TERMINAL_LIFECYCLE_STATES:
                # Lifecycle terminality is authoritative for closure.  Invalid
                # material evidence must not open or supersede an epoch, but it
                # must not leave an already-open epoch alive after its parent
                # lifecycle has become terminal either.
                reduction = reducer.terminalize(evidence)
            else:
                failure = context_evidence_failure(evidence)
                if failure is not None:
                    return ContextEpochPersistenceResult(
                        status=cast(ContextEpochPersistenceStatus, failure[0]),
                        reason_code=failure[1],
                        strategy_lifecycle_id=lifecycle_id,
                        epoch=current,
                    )
                reduction = reducer.ingest(evidence)
            if reduction.status in {
                "DUPLICATE",
                "REJECTED",
                "WAITING_CONTEXT_EVIDENCE",
                "QUARANTINED_CONTEXT_EVIDENCE",
            }:
                return ContextEpochPersistenceResult(
                    status=cast(ContextEpochPersistenceStatus, reduction.status),
                    reason_code=reduction.reason_code,
                    strategy_lifecycle_id=lifecycle_id,
                    epoch=reduction.epoch,
                )

            if reduction.epoch is None:
                raise ContextEpochV1IntegrityError("CONTEXT_EPOCH_REDUCTION_MISSING_STATE")
            if reduction.status == "OPENED":
                await self._insert_epoch(connection, reduction.epoch, evidence)
            elif reduction.status == "CONFIRMED":
                await self._update_epoch(connection, reduction.epoch, evidence, replace_evidence=True)
            elif reduction.status == "TRANSITIONED":
                if reduction.previous_epoch is None:
                    raise ContextEpochV1IntegrityError("CONTEXT_EPOCH_PREVIOUS_STATE_MISSING")
                await self._update_epoch(connection, reduction.previous_epoch, evidence, replace_evidence=False)
                await self._insert_epoch(connection, reduction.epoch, evidence)
            elif reduction.status == "TERMINATED":
                await self._update_epoch(connection, reduction.epoch, evidence, replace_evidence=True)
            else:
                raise ContextEpochV1IntegrityError(f"CONTEXT_EPOCH_STATUS_UNHANDLED:{reduction.status}")

            if reduction.transition is not None:
                await self._insert_transition(connection, reduction.transition, evidence)
            return ContextEpochPersistenceResult(
                status="NO_CHANGE" if reduction.status == "CONFIRMED" else "PERSISTED",
                strategy_lifecycle_id=lifecycle_id,
                epoch=reduction.epoch,
                transition_id=None if reduction.transition is None else reduction.transition.transition_id,
            )

    async def process_batch(
        self,
        evidence_items: Sequence[MaterialContextEvidenceV1],
    ) -> tuple[ContextEpochPersistenceResult, ...]:
        ordered = sorted(
            evidence_items,
            key=lambda item: (item.observed_at_utc, item.source_pressure_event_id),
        )
        return tuple([await self.process_evidence(item) for item in ordered])

    async def _insert_epoch(
        self,
        connection: Any,
        epoch: StrategyContextEpochV1,
        evidence: MaterialContextEvidenceV1,
    ) -> None:
        result = await connection.execute(
            f"""
            INSERT INTO {EPOCH_TABLE} (
                context_epoch_id, strategy_lifecycle_id, symbol, epoch_sequence,
                state, material_context_hash, opened_at, last_confirmed_at, closed_at,
                daily_source_candle_ids, h4_source_candle_ids, daily_bias, h4_structure,
                price_location, liquidity_state, direction_domain, allowed_routes,
                blocked_routes, target_map_version, structural_invalidation_version,
                transition_reason, evidence_hash, evidence_payload, last_observed_at,
                last_source_event_id, state_version, execution_authority
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb,$12,$13,$14,$15,
                $16,$17::jsonb,$18::jsonb,$19,$20,$21,$22,$23::jsonb,$24,$25,$26,false
            )
            """,
            epoch.context_epoch_id,
            epoch.strategy_lifecycle_id,
            epoch.symbol,
            epoch.epoch_sequence,
            epoch.state,
            epoch.material_context_hash,
            epoch.opened_at_utc,
            epoch.last_confirmed_at_utc,
            epoch.closed_at_utc,
            json.dumps(list(epoch.daily_source_candle_ids), separators=(",", ":")),
            json.dumps(list(epoch.h4_source_candle_ids), separators=(",", ":")),
            epoch.daily_bias,
            epoch.h4_structure,
            epoch.price_location,
            epoch.liquidity_state,
            epoch.direction_domain,
            json.dumps(list(epoch.allowed_routes), separators=(",", ":")),
            json.dumps(list(epoch.blocked_routes), separators=(",", ":")),
            epoch.target_map_version,
            epoch.structural_invalidation_version,
            epoch.transition_reason,
            epoch.evidence_hash,
            json.dumps(evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            epoch.last_observed_at_utc,
            epoch.last_source_event_id,
            epoch.state_version,
        )
        if not str(result).endswith(" 1"):
            raise ContextEpochV1IntegrityError("CONTEXT_EPOCH_INSERT_FAILED")

    async def _update_epoch(
        self,
        connection: Any,
        epoch: StrategyContextEpochV1,
        evidence: MaterialContextEvidenceV1,
        *,
        replace_evidence: bool,
    ) -> None:
        result = await connection.execute(
            f"""
            UPDATE {EPOCH_TABLE} SET
                state = $2, closed_at = $3, last_confirmed_at = $4,
                evidence_hash = CASE WHEN $11 THEN $5 ELSE evidence_hash END,
                evidence_payload = CASE WHEN $11 THEN $6::jsonb ELSE evidence_payload END,
                last_observed_at = $7, last_source_event_id = $8,
                state_version = $9, execution_authority = false, updated_at = now()
            WHERE context_epoch_id = $1 AND state_version = $10
            """,
            epoch.context_epoch_id,
            epoch.state,
            epoch.closed_at_utc,
            epoch.last_confirmed_at_utc,
            epoch.evidence_hash,
            json.dumps(evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            epoch.last_observed_at_utc,
            epoch.last_source_event_id,
            epoch.state_version,
            epoch.state_version - 1,
            replace_evidence,
        )
        if not str(result).endswith(" 1"):
            raise ContextEpochV1IntegrityError("CONTEXT_EPOCH_STATE_VERSION_NOT_ADVANCED")

    async def _insert_transition(
        self,
        connection: Any,
        transition: ContextTransitionV1,
        evidence: MaterialContextEvidenceV1,
    ) -> None:
        result = await connection.execute(
            f"""
            INSERT INTO {TRANSITION_TABLE} (
                transition_id, strategy_lifecycle_id, from_context_epoch_id,
                to_context_epoch_id, reason, source_pressure_event_id,
                source_event_ids, occurred_at, material_context_hash, evidence_hash,
                dedupe_key, payload, evidence_payload, execution_authority
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11,$12::jsonb,$13::jsonb,false
            )
            ON CONFLICT (dedupe_key) DO NOTHING
            """,
            transition.transition_id,
            transition.strategy_lifecycle_id,
            transition.from_context_epoch_id,
            transition.to_context_epoch_id,
            transition.reason,
            transition.source_pressure_event_id,
            json.dumps(list(transition.source_event_ids), separators=(",", ":")),
            transition.occurred_at_utc,
            transition.material_context_hash,
            transition.evidence_hash,
            transition.dedupe_key,
            json.dumps(transition.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            json.dumps(evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
        )
        if str(result).endswith(" 1"):
            return
        stored = await connection.fetchrow(
            f"SELECT transition_id, evidence_hash FROM {TRANSITION_TABLE} WHERE dedupe_key = $1",
            transition.dedupe_key,
        )
        if (
            stored is None
            or str(_row_value(stored, "transition_id")) != transition.transition_id
            or str(_row_value(stored, "evidence_hash")) != transition.evidence_hash
        ):
            raise ContextEpochV1IntegrityError("CONTEXT_TRANSITION_IDENTITY_DRIFT")
        raise ContextEpochV1IntegrityError("CONTEXT_TRANSITION_EPOCH_ATOMICITY_BROKEN")


__all__ = [
    "CONTEXT_EPOCH_V1_SHADOW_ONLY_FLAG",
    "CONTEXT_EPOCH_V1_WRITER_FLAG",
    "EPOCH_TABLE",
    "TRANSITION_TABLE",
    "ContextEpochPersistenceResult",
    "ContextEpochV1IntegrityError",
    "ContextEpochV1PersistenceError",
    "ContextEpochV1RuntimeConfig",
    "ContextEpochV1SchemaStatus",
    "StrategyContextEpochV1Repository",
]
