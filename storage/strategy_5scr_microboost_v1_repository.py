"""Atomic shadow-only persistence for durable Microboost pulse/state V1.

The repository accepts only pressure emissions already linked to a canonical
Strategy Lifecycle V2 row.  Source block, cluster, watch, and transport IDs are
lineage only; none may create a Microboost state by itself.

Pulse rows are insert-only by this repository contract.  Database-role
immutability is deliberately not claimed here; that privilege boundary is a
separate deployment hardening concern.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from analysis.strategy_5scr_microboost_pulse_engine import MicroboostPulseEngine
from contracts.strategy_5scr_lifecycle_v2 import TERMINAL_LIFECYCLE_STATES
from contracts.strategy_5scr_microboost_pulse import (
    MicroboostPulseEvent,
    MicroboostState,
    MicroboostStateName,
    PulseDirection,
)
from contracts.strategy_5scr_pressure_emission_v3 import CanonicalPressureEmissionV3
from storage.postgres_client import PostgresClient, pg_client

PULSE_EVENT_TABLE = "strategy_5scr_microboost_pulse_events_v1"
STATE_TABLE = "strategy_5scr_microboost_states_v1"
LIFECYCLE_TABLE = "strategy_5scr_analysis_lifecycles_v2"
LIFECYCLE_LINK_TABLE = "strategy_5scr_lifecycle_event_links_v2"

MICROBOOST_V1_WRITER_FLAG = "STRATEGY_5SCR_MICROBOOST_V1_WRITER_ENABLED"
MICROBOOST_V1_SHADOW_ONLY_FLAG = "STRATEGY_5SCR_MICROBOOST_V1_SHADOW_ONLY"

_REQUIRED_TABLES = frozenset({PULSE_EVENT_TABLE, STATE_TABLE})
_REQUIRED_CONSTRAINT_DEFINITIONS: dict[str, tuple[str, str, str]] = {
    "fk_5scr_microboost_pulse_lifecycle_v1": (
        PULSE_EVENT_TABLE,
        "f",
        "foreign key (strategy_lifecycle_id) references "
        "strategy_5scr_analysis_lifecycles_v2(strategy_lifecycle_id) on delete restrict",
    ),
    "ck_5scr_microboost_pulse_identity_v1": (
        PULSE_EVENT_TABLE,
        "c",
        "check (((pulse_event_id ~ '^5scr-pulse:[0-9a-f]{32}$'::text) and "
        "((evidence_hash)::text ~ '^sha256:[0-9a-f]{64}$'::text)))",
    ),
    "ck_5scr_microboost_pulse_transition_v1": (
        PULSE_EVENT_TABLE,
        "c",
        "check (((transition)::text = any ((array['formed'::character varying, "
        "'reinforced'::character varying, 'weakened'::character varying, "
        "'invalidated'::character varying, 'expired'::character varying])::text[])))",
    ),
    "ck_5scr_microboost_pulse_direction_v1": (
        PULSE_EVENT_TABLE,
        "c",
        "check (((direction is null) or ((direction)::text = any "
        "((array['buy'::character varying, 'sell'::character varying])::text[]))))",
    ),
    "ck_5scr_microboost_pulse_sources_v1": (
        PULSE_EVENT_TABLE,
        "c",
        "check (((jsonb_typeof(source_event_ids) = 'array'::text) and (jsonb_array_length(source_event_ids) > 0)))",
    ),
    "ck_5scr_microboost_pulse_shadow_only_v1": (
        PULSE_EVENT_TABLE,
        "c",
        "check ((execution_authority is false))",
    ),
    "fk_5scr_microboost_state_lifecycle_v1": (
        STATE_TABLE,
        "f",
        "foreign key (strategy_lifecycle_id) references "
        "strategy_5scr_analysis_lifecycles_v2(strategy_lifecycle_id) on delete restrict",
    ),
    "ck_5scr_microboost_state_name_v1": (
        STATE_TABLE,
        "c",
        "check (((state)::text = any ((array['none'::character varying, "
        "'active'::character varying, 'weakening'::character varying, "
        "'invalidated'::character varying, 'expired'::character varying])::text[])))",
    ),
    "ck_5scr_microboost_state_direction_v1": (
        STATE_TABLE,
        "c",
        "check (((direction is null) or ((direction)::text = any "
        "((array['buy'::character varying, 'sell'::character varying])::text[]))))",
    ),
    "ck_5scr_microboost_state_counters_v1": (
        STATE_TABLE,
        "c",
        "check (((independent_pulse_count >= 0) and (reinforcement_count >= 0) and "
        "(carried_snapshot_count >= 0) and (observed_snapshot_count >= 0) and "
        "(current_effective_ticks >= 0) and (peak_effective_ticks >= current_effective_ticks) and "
        "(state_version >= 0)))",
    ),
    "ck_5scr_microboost_state_evidence_v1": (
        STATE_TABLE,
        "c",
        "check (((evidence_hash)::text ~ '^sha256:[0-9a-f]{64}$'::text))",
    ),
    "ck_5scr_microboost_state_shadow_only_v1": (
        STATE_TABLE,
        "c",
        "check ((execution_authority is false))",
    ),
}
_REQUIRED_CONSTRAINTS = frozenset(_REQUIRED_CONSTRAINT_DEFINITIONS)
_REQUIRED_INDEXES: dict[str, tuple[str, bool, tuple[str, ...]]] = {
    "uq_5scr_microboost_pulse_dedupe_v1": (PULSE_EVENT_TABLE, True, ("dedupe_key",)),
    "ix_5scr_microboost_pulse_lifecycle_time_v1": (
        PULSE_EVENT_TABLE,
        False,
        ("strategy_lifecycle_id", "occurred_at", "pulse_event_id"),
    ),
    "ix_5scr_microboost_state_status_v1": (
        STATE_TABLE,
        False,
        ("state", "last_observed_at", "strategy_lifecycle_id"),
    ),
}


@dataclass(frozen=True)
class _ColumnContract:
    data_type: str
    nullable: bool
    max_length: int | None = None
    default: str = ""


_REQUIRED_COLUMNS: dict[tuple[str, str], _ColumnContract] = {
    (PULSE_EVENT_TABLE, "pulse_event_id"): _ColumnContract("text", False),
    (PULSE_EVENT_TABLE, "strategy_lifecycle_id"): _ColumnContract("text", False),
    (PULSE_EVENT_TABLE, "transition"): _ColumnContract("character varying", False, 20),
    (PULSE_EVENT_TABLE, "direction"): _ColumnContract("character varying", True, 4),
    (PULSE_EVENT_TABLE, "occurred_at"): _ColumnContract("timestamp with time zone", False),
    (PULSE_EVENT_TABLE, "source_event_ids"): _ColumnContract("jsonb", False),
    (PULSE_EVENT_TABLE, "evidence_hash"): _ColumnContract("character varying", False, 71),
    (PULSE_EVENT_TABLE, "dedupe_key"): _ColumnContract("text", False),
    (PULSE_EVENT_TABLE, "payload"): _ColumnContract("jsonb", False),
    (PULSE_EVENT_TABLE, "execution_authority"): _ColumnContract("boolean", False, default="false"),
    (PULSE_EVENT_TABLE, "created_at"): _ColumnContract(
        "timestamp with time zone",
        False,
        default="now()",
    ),
    (STATE_TABLE, "strategy_lifecycle_id"): _ColumnContract("text", False),
    (STATE_TABLE, "symbol"): _ColumnContract("character varying", False, 32),
    (STATE_TABLE, "state"): _ColumnContract("character varying", False, 20),
    (STATE_TABLE, "direction"): _ColumnContract("character varying", True, 4),
    (STATE_TABLE, "first_formed_at"): _ColumnContract("timestamp with time zone", True),
    (STATE_TABLE, "last_pulse_at"): _ColumnContract("timestamp with time zone", True),
    (STATE_TABLE, "last_confirmed_at"): _ColumnContract("timestamp with time zone", True),
    (STATE_TABLE, "expires_at"): _ColumnContract("timestamp with time zone", True),
    (STATE_TABLE, "independent_pulse_count"): _ColumnContract("integer", False, default="0"),
    (STATE_TABLE, "reinforcement_count"): _ColumnContract("integer", False, default="0"),
    (STATE_TABLE, "carried_snapshot_count"): _ColumnContract("integer", False, default="0"),
    (STATE_TABLE, "observed_snapshot_count"): _ColumnContract("integer", False, default="0"),
    (STATE_TABLE, "current_effective_ticks"): _ColumnContract("integer", False, default="0"),
    (STATE_TABLE, "peak_effective_ticks"): _ColumnContract("integer", False, default="0"),
    (STATE_TABLE, "current_strength"): _ColumnContract("character varying", True, 100),
    (STATE_TABLE, "peak_strength"): _ColumnContract("character varying", True, 100),
    (STATE_TABLE, "active_block_id"): _ColumnContract("text", True),
    (STATE_TABLE, "last_source_stage"): _ColumnContract("character varying", True, 100),
    (STATE_TABLE, "last_observed_at"): _ColumnContract("timestamp with time zone", False),
    (STATE_TABLE, "last_source_event_id"): _ColumnContract("text", False),
    (STATE_TABLE, "state_version"): _ColumnContract("bigint", False),
    (STATE_TABLE, "evidence_hash"): _ColumnContract("character varying", False, 71),
    (STATE_TABLE, "execution_authority"): _ColumnContract("boolean", False, default="false"),
    (STATE_TABLE, "updated_at"): _ColumnContract(
        "timestamp with time zone",
        False,
        default="now()",
    ),
}


def _enabled(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() == "true"


@dataclass(frozen=True)
class MicroboostV1RuntimeConfig:
    enabled: bool = False
    shadow_only: bool = True

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> MicroboostV1RuntimeConfig:
        source = os.environ if environ is None else environ
        return cls(
            enabled=_enabled(source.get(MICROBOOST_V1_WRITER_FLAG), default=False),
            shadow_only=_enabled(source.get(MICROBOOST_V1_SHADOW_ONLY_FLAG), default=True),
        )

    def validate(self) -> None:
        if self.enabled and not self.shadow_only:
            raise RuntimeError("STRATEGY_5SCR_MICROBOOST_V1_SHADOW_ONLY_REQUIRED")


@dataclass(frozen=True)
class MicroboostV1SchemaStatus:
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


MicroboostPersistenceStatus = Literal["PERSISTED", "NO_CHANGE", "DUPLICATE", "REJECTED"]


@dataclass(frozen=True)
class MicroboostPersistenceResult:
    status: MicroboostPersistenceStatus
    reason_code: str | None = None
    strategy_lifecycle_id: str | None = None
    pulse_event_ids: tuple[str, ...] = ()
    state: MicroboostState | None = None


class MicroboostV1PersistenceError(RuntimeError):
    """Base error for atomic durable Microboost persistence."""


class MicroboostV1IntegrityError(MicroboostV1PersistenceError):
    """Raised when durable pulse and state identities disagree."""


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _normalize_sql(value: Any) -> str:
    return " ".join(str(value or "").replace('"', "").lower().split())


def _state_from_row(row: Any) -> MicroboostState:
    return MicroboostState(
        strategy_lifecycle_id=str(_row_value(row, "strategy_lifecycle_id")),
        symbol=str(_row_value(row, "symbol")),
        state=cast(MicroboostStateName, str(_row_value(row, "state"))),
        direction=cast(PulseDirection | None, _row_value(row, "direction")),
        first_formed_at_utc=_row_value(row, "first_formed_at"),
        last_pulse_at_utc=_row_value(row, "last_pulse_at"),
        last_confirmed_at_utc=_row_value(row, "last_confirmed_at"),
        expires_at_utc=_row_value(row, "expires_at"),
        independent_pulse_count=int(_row_value(row, "independent_pulse_count", 0) or 0),
        reinforcement_count=int(_row_value(row, "reinforcement_count", 0) or 0),
        carried_snapshot_count=int(_row_value(row, "carried_snapshot_count", 0) or 0),
        observed_snapshot_count=int(_row_value(row, "observed_snapshot_count", 0) or 0),
        current_effective_ticks=int(_row_value(row, "current_effective_ticks", 0) or 0),
        peak_effective_ticks=int(_row_value(row, "peak_effective_ticks", 0) or 0),
        current_strength=_row_value(row, "current_strength"),
        peak_strength=_row_value(row, "peak_strength"),
        active_block_id=_row_value(row, "active_block_id"),
        last_source_stage=_row_value(row, "last_source_stage"),
        last_observed_at_utc=_row_value(row, "last_observed_at"),
        last_source_event_id=str(_row_value(row, "last_source_event_id")),
        state_version=int(_row_value(row, "state_version", 0) or 0),
        evidence_hash=str(_row_value(row, "evidence_hash")),
    )


class StrategyMicroboostV1Repository:
    """Fold canonical linked emissions and commit pulse/state atomically."""

    def __init__(self, *, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client

    @property
    def is_available(self) -> bool:
        return self._pg.is_available

    async def schema_status(self) -> MicroboostV1SchemaStatus:
        expected_columns = tuple(sorted(f"{table}.{column}" for table, column in _REQUIRED_COLUMNS))
        if not self._pg.is_available:
            return MicroboostV1SchemaStatus(
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
                   cls.relname AS table_name,
                   pg_get_constraintdef(con.oid) AS definition
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class cls ON cls.oid = con.conrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()
              AND con.conname = ANY($1::text[])
            """,
            sorted(_REQUIRED_CONSTRAINTS),
        )
        index_rows = await self._pg.fetch(
            """
            SELECT table_cls.relname AS table_name,
                   index_cls.relname AS index_name,
                   idx.indisunique,
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
            WHERE ns.nspname = current_schema()
              AND index_cls.relname = ANY($1::text[])
            """,
            sorted(_REQUIRED_INDEXES),
        )

        present_tables = {str(_row_value(row, "tablename") or "") for row in table_rows}
        columns = {
            (str(_row_value(row, "table_name")), str(_row_value(row, "column_name"))): row for row in column_rows
        }
        invalid_columns: list[str] = []
        satisfied_columns: set[str] = set()
        for key, expected in _REQUIRED_COLUMNS.items():
            row = columns.get(key)
            if row is None:
                continue
            label = f"{key[0]}.{key[1]}"
            data_type = str(_row_value(row, "data_type") or "").lower()
            nullable = str(_row_value(row, "is_nullable") or "").upper() == "YES"
            length_value = _row_value(row, "character_maximum_length")
            length = None if length_value is None else int(length_value)
            default = _normalize_sql(_row_value(row, "column_default"))
            if data_type != expected.data_type:
                invalid_columns.append(f"{label}:type={data_type or 'missing'}")
            elif nullable != expected.nullable:
                invalid_columns.append(f"{label}:nullable={str(nullable).lower()}")
            elif length != expected.max_length:
                invalid_columns.append(f"{label}:max_length={length}")
            elif default != expected.default:
                invalid_columns.append(f"{label}:default={default or 'missing'}")
            else:
                satisfied_columns.add(label)

        constraints = {str(_row_value(row, "conname") or ""): row for row in constraint_rows}
        invalid_constraints: list[str] = []
        for name, expected in _REQUIRED_CONSTRAINT_DEFINITIONS.items():
            row = constraints.get(name)
            if row is None:
                continue
            table, contype, definition = expected
            if str(_row_value(row, "table_name")) != table:
                invalid_constraints.append(f"{name}:table")
            elif str(_row_value(row, "contype")) != contype:
                invalid_constraints.append(f"{name}:type")
            elif not bool(_row_value(row, "convalidated")):
                invalid_constraints.append(f"{name}:not_validated")
            elif _normalize_sql(_row_value(row, "definition")) != definition:
                invalid_constraints.append(f"{name}:definition")

        indexes = {str(_row_value(row, "index_name") or ""): row for row in index_rows}
        invalid_indexes: list[str] = []
        for name, expected in _REQUIRED_INDEXES.items():
            row = indexes.get(name)
            if row is None:
                continue
            table, unique, columns_expected = expected
            columns_actual = tuple(str(value) for value in (_row_value(row, "columns") or ()))
            if str(_row_value(row, "table_name")) != table:
                invalid_indexes.append(f"{name}:table")
            elif bool(_row_value(row, "indisunique")) != unique:
                invalid_indexes.append(f"{name}:unique")
            elif columns_actual != columns_expected:
                invalid_indexes.append(f"{name}:columns")

        return MicroboostV1SchemaStatus(
            missing_tables=tuple(sorted(_REQUIRED_TABLES - present_tables)),
            missing_columns=tuple(
                sorted(set(expected_columns) - satisfied_columns - {item.split(":", 1)[0] for item in invalid_columns})
            ),
            invalid_columns=tuple(sorted(invalid_columns)),
            missing_constraints=tuple(sorted(_REQUIRED_CONSTRAINTS - set(constraints))),
            invalid_constraints=tuple(sorted(invalid_constraints)),
            missing_indexes=tuple(sorted(set(_REQUIRED_INDEXES) - set(indexes))),
            invalid_indexes=tuple(sorted(invalid_indexes)),
        )

    async def load_state(self, strategy_lifecycle_id: str) -> MicroboostState | None:
        row = await self._pg.fetchrow(
            f"SELECT * FROM {STATE_TABLE} WHERE strategy_lifecycle_id = $1",
            strategy_lifecycle_id,
        )
        return None if row is None else _state_from_row(row)

    async def process_emission(
        self,
        emission: CanonicalPressureEmissionV3,
    ) -> MicroboostPersistenceResult:
        """Persist one canonically ordered emission under its lifecycle lock."""

        if emission.normalization.status == "QUARANTINED":
            return MicroboostPersistenceResult(status="REJECTED", reason_code="EMISSION_QUARANTINED")
        if emission.microboost_snapshot.detected is None:
            return MicroboostPersistenceResult(
                status="REJECTED",
                reason_code="MICROBOOST_SNAPSHOT_MISSING",
            )

        event_id = emission.identity.transport_event_id
        event_time = emission.time.event_time_utc
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
                event_id,
            )
            if lifecycle is None:
                return MicroboostPersistenceResult(
                    status="REJECTED",
                    reason_code="NO_CANONICAL_LIFECYCLE_LINK",
                )
            lifecycle_id = str(_row_value(lifecycle, "strategy_lifecycle_id"))
            lifecycle_symbol = str(_row_value(lifecycle, "symbol")).upper()
            lifecycle_state = str(_row_value(lifecycle, "state"))
            if lifecycle_symbol != emission.symbol:
                return MicroboostPersistenceResult(
                    status="REJECTED",
                    reason_code="LIFECYCLE_SYMBOL_MISMATCH",
                    strategy_lifecycle_id=lifecycle_id,
                )
            if lifecycle_state in TERMINAL_LIFECYCLE_STATES:
                return MicroboostPersistenceResult(
                    status="REJECTED",
                    reason_code="TERMINAL_LIFECYCLE",
                    strategy_lifecycle_id=lifecycle_id,
                )

            state_row = await connection.fetchrow(
                f"SELECT * FROM {STATE_TABLE} WHERE strategy_lifecycle_id = $1 FOR UPDATE",
                lifecycle_id,
            )
            state = (
                _state_from_row(state_row)
                if state_row is not None
                else MicroboostState(strategy_lifecycle_id=lifecycle_id, symbol=lifecycle_symbol)
            )
            if state.last_observed_at_utc is not None and state.last_source_event_id is not None:
                incoming_cursor = (event_time, event_id)
                durable_cursor = (state.last_observed_at_utc, state.last_source_event_id)
                if incoming_cursor <= durable_cursor:
                    reason = (
                        "SOURCE_EVENT_ALREADY_OBSERVED"
                        if event_id == state.last_source_event_id
                        else "NON_MONOTONIC_CANONICAL_ORDER"
                    )
                    return MicroboostPersistenceResult(
                        status="DUPLICATE" if reason == "SOURCE_EVENT_ALREADY_OBSERVED" else "REJECTED",
                        reason_code=reason,
                        strategy_lifecycle_id=lifecycle_id,
                        state=state,
                    )

            engine = MicroboostPulseEngine(
                lifecycle_id,
                lifecycle_symbol,
                initial_state=state,
            )
            pulses = engine.ingest_canonical(emission)
            next_state = engine.state
            for pulse in pulses:
                await self._insert_pulse(connection, pulse)
            await self._write_state(connection, next_state)
            return MicroboostPersistenceResult(
                status="PERSISTED" if pulses else "NO_CHANGE",
                strategy_lifecycle_id=lifecycle_id,
                pulse_event_ids=tuple(pulse.pulse_event_id for pulse in pulses),
                state=next_state,
            )

    async def process_batch(
        self,
        emissions: Sequence[CanonicalPressureEmissionV3],
    ) -> tuple[MicroboostPersistenceResult, ...]:
        """Canonicalize input order before folding a replay batch."""

        ordered = sorted(
            emissions,
            key=lambda item: (item.time.event_time_utc, item.identity.transport_event_id),
        )
        return tuple([await self.process_emission(item) for item in ordered])

    async def _insert_pulse(self, connection: Any, pulse: MicroboostPulseEvent) -> None:
        payload = pulse.model_dump(mode="json")
        result = await connection.execute(
            f"""
            INSERT INTO {PULSE_EVENT_TABLE} (
                pulse_event_id, strategy_lifecycle_id, transition, direction,
                occurred_at, source_event_ids, evidence_hash, dedupe_key,
                payload, execution_authority
            ) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9::jsonb,false)
            ON CONFLICT (dedupe_key) DO NOTHING
            """,
            pulse.pulse_event_id,
            pulse.strategy_lifecycle_id,
            pulse.transition,
            pulse.direction,
            pulse.occurred_at_utc,
            json.dumps(list(pulse.source_event_ids), separators=(",", ":")),
            pulse.evidence_hash,
            pulse.dedupe_key,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
        if str(result).endswith(" 1"):
            return
        stored = await connection.fetchrow(
            f"SELECT pulse_event_id, evidence_hash FROM {PULSE_EVENT_TABLE} WHERE dedupe_key = $1",
            pulse.dedupe_key,
        )
        if (
            stored is None
            or str(_row_value(stored, "pulse_event_id")) != pulse.pulse_event_id
            or str(_row_value(stored, "evidence_hash")) != pulse.evidence_hash
        ):
            raise MicroboostV1IntegrityError("MICROBOOST_PULSE_IDENTITY_DRIFT")
        raise MicroboostV1IntegrityError("MICROBOOST_PULSE_STATE_ATOMICITY_BROKEN")

    async def _write_state(self, connection: Any, state: MicroboostState) -> None:
        if state.last_observed_at_utc is None or state.last_source_event_id is None or state.evidence_hash is None:
            raise MicroboostV1IntegrityError("MICROBOOST_DURABLE_CURSOR_MISSING")
        result = await connection.execute(
            f"""
            INSERT INTO {STATE_TABLE} (
                strategy_lifecycle_id, symbol, state, direction,
                first_formed_at, last_pulse_at, last_confirmed_at, expires_at,
                independent_pulse_count, reinforcement_count,
                carried_snapshot_count, observed_snapshot_count,
                current_effective_ticks, peak_effective_ticks,
                current_strength, peak_strength, active_block_id,
                last_source_stage, last_observed_at, last_source_event_id,
                state_version, evidence_hash, execution_authority, updated_at
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                $17,$18,$19,$20,$21,$22,false,now()
            )
            ON CONFLICT (strategy_lifecycle_id) DO UPDATE SET
                symbol = EXCLUDED.symbol,
                state = EXCLUDED.state,
                direction = EXCLUDED.direction,
                first_formed_at = EXCLUDED.first_formed_at,
                last_pulse_at = EXCLUDED.last_pulse_at,
                last_confirmed_at = EXCLUDED.last_confirmed_at,
                expires_at = EXCLUDED.expires_at,
                independent_pulse_count = EXCLUDED.independent_pulse_count,
                reinforcement_count = EXCLUDED.reinforcement_count,
                carried_snapshot_count = EXCLUDED.carried_snapshot_count,
                observed_snapshot_count = EXCLUDED.observed_snapshot_count,
                current_effective_ticks = EXCLUDED.current_effective_ticks,
                peak_effective_ticks = EXCLUDED.peak_effective_ticks,
                current_strength = EXCLUDED.current_strength,
                peak_strength = EXCLUDED.peak_strength,
                active_block_id = EXCLUDED.active_block_id,
                last_source_stage = EXCLUDED.last_source_stage,
                last_observed_at = EXCLUDED.last_observed_at,
                last_source_event_id = EXCLUDED.last_source_event_id,
                state_version = EXCLUDED.state_version,
                evidence_hash = EXCLUDED.evidence_hash,
                execution_authority = false,
                updated_at = now()
            WHERE {STATE_TABLE}.state_version < EXCLUDED.state_version
            """,
            state.strategy_lifecycle_id,
            state.symbol,
            state.state,
            state.direction,
            state.first_formed_at_utc,
            state.last_pulse_at_utc,
            state.last_confirmed_at_utc,
            state.expires_at_utc,
            state.independent_pulse_count,
            state.reinforcement_count,
            state.carried_snapshot_count,
            state.observed_snapshot_count,
            state.current_effective_ticks,
            state.peak_effective_ticks,
            state.current_strength,
            state.peak_strength,
            state.active_block_id,
            state.last_source_stage,
            state.last_observed_at_utc,
            state.last_source_event_id,
            state.state_version,
            state.evidence_hash,
        )
        if not str(result).endswith(" 1"):
            raise MicroboostV1IntegrityError("MICROBOOST_STATE_VERSION_NOT_ADVANCED")


__all__ = [
    "MICROBOOST_V1_SHADOW_ONLY_FLAG",
    "MICROBOOST_V1_WRITER_FLAG",
    "PULSE_EVENT_TABLE",
    "STATE_TABLE",
    "MicroboostPersistenceResult",
    "MicroboostV1IntegrityError",
    "MicroboostV1PersistenceError",
    "MicroboostV1RuntimeConfig",
    "MicroboostV1SchemaStatus",
    "StrategyMicroboostV1Repository",
]
