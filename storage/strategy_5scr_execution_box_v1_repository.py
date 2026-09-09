"""Atomic shadow-only persistence for Strategy 5S-CR ExecutionBox V1."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
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
from contracts.strategy_5scr_execution_box_v1 import ExecutionBoxEvidenceV1, ExecutionBoxV1, M1CandleAuthorityV1
from contracts.strategy_5scr_lifecycle_v2 import TERMINAL_LIFECYCLE_STATES
from storage.postgres_client import PostgresClient, pg_client
from storage.strategy_5scr_directional_thesis_v1_repository import (
    Strategy5SCRDirectionalThesisV1Repository,
    _context_from_row,
)
from storage.strategy_5scr_directional_thesis_v1_repository import (
    _thesis_from_row as _p4_thesis_from_row,
)

BOX_TABLE = "strategy_5scr_execution_boxes_v1"
THESIS_TABLE = "strategy_5scr_directional_theses_v1"
CONTEXT_TABLE = "strategy_5scr_context_epochs_v1"
LIFECYCLE_TABLE = "strategy_5scr_analysis_lifecycles_v2"
CANONICAL_CANDLE_TABLE = "canonical_candles"
OBSERVATION_TABLE = "strategy_5scr_execution_box_observations_v1"

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


def _normalize_sql(value: Any) -> str:
    """Fingerprint the exact stable PostgreSQL catalog representation."""

    return str(value or "")


def _sql_fingerprint(value: Any) -> str:
    return hashlib.sha256(_normalize_sql(value).encode("utf-8")).hexdigest()


def _catalog_char(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value or "")


def _observation_id(strategy_thesis_id: str, observed_at: datetime, evidence_hash: str) -> str:
    basis = f"{strategy_thesis_id}|{observed_at.isoformat()}|{evidence_hash}"
    return "5scr-execution-box-observation:" + hashlib.sha256(basis.encode()).hexdigest()[:32]


def _terminal_clock(*values: Any, floor: datetime) -> datetime:
    clocks = tuple(value for value in values if isinstance(value, datetime))
    if not clocks:
        raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_PARENT_TERMINAL_CLOCK_MISSING")
    return max((floor, *clocks))


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


@dataclass(frozen=True)
class _ColumnContract:
    data_type: str
    nullable: bool
    max_length: int | None = None
    default: str = ""


@dataclass(frozen=True)
class _ConstraintContract:
    table: str
    contype: str


@dataclass(frozen=True)
class _IndexContract:
    table: str
    unique: bool
    columns: tuple[str, ...]


@dataclass(frozen=True)
class _TriggerContract:
    table: str
    function: str


def _columns(
    table: str, rows: Sequence[tuple[str, str, bool, int | None, str]]
) -> dict[tuple[str, str], _ColumnContract]:
    return {
        (table, name): _ColumnContract(data_type, nullable, size, default)
        for name, data_type, nullable, size, default in rows
    }


_REQUIRED_TABLES = frozenset(
    {BOX_TABLE, OBSERVATION_TABLE, CANONICAL_CANDLE_TABLE, LIFECYCLE_TABLE, CONTEXT_TABLE, THESIS_TABLE}
)
_REQUIRED_COLUMNS: dict[tuple[str, str], _ColumnContract] = {
    **_columns(
        BOX_TABLE,
        (
            ("execution_box_id", "text", False, None, ""),
            ("strategy_lifecycle_id", "text", False, None, ""),
            ("context_epoch_id", "text", False, None, ""),
            ("strategy_thesis_id", "text", False, None, ""),
            ("box_sequence", "integer", False, None, ""),
            ("box_version", "integer", False, None, ""),
            ("previous_execution_box_id", "text", True, None, ""),
            ("previous_box_sequence", "integer", True, None, ""),
            ("previous_box_version", "integer", True, None, ""),
            ("symbol", "character varying", False, 32, ""),
            ("strategy_direction", "character varying", False, 4, ""),
            ("route_type", "character varying", False, 120, ""),
            ("state", "character varying", False, 20, ""),
            ("box_low", "double precision", False, None, ""),
            ("box_high", "double precision", False, None, ""),
            ("opened_at", "timestamp with time zone", False, None, ""),
            ("frozen_at", "timestamp with time zone", True, None, ""),
            ("freeze_authority_hash", "character varying", True, 71, ""),
            ("superseded_at", "timestamp with time zone", True, None, ""),
            ("invalidated_at", "timestamp with time zone", True, None, ""),
            ("consumed_at", "timestamp with time zone", True, None, ""),
            ("expired_at", "timestamp with time zone", True, None, ""),
            ("material_box_hash", "character varying", False, 71, ""),
            ("formation_evidence_hash", "character varying", False, 71, ""),
            ("evidence_hash", "character varying", False, 71, ""),
            ("thesis_semantic_identity_hash", "character varying", False, 71, ""),
            ("source_m1_ids", "jsonb", False, None, ""),
            ("source_m1_evidence_ids", "jsonb", False, None, ""),
            ("last_observed_at", "timestamp with time zone", False, None, ""),
            ("last_source_request_id", "text", True, None, ""),
            ("state_version", "bigint", False, None, ""),
            ("rule_version", "character varying", False, 100, ""),
            ("valid_for_execution", "boolean", False, None, "false"),
            ("execution_authority", "boolean", False, None, "false"),
            ("payload", "jsonb", False, None, ""),
            ("evidence_payload", "jsonb", False, None, ""),
            ("latest_evidence_payload", "jsonb", False, None, ""),
            ("freeze_evidence_payload", "jsonb", True, None, ""),
            ("created_at", "timestamp with time zone", False, None, "now()"),
            ("updated_at", "timestamp with time zone", False, None, "now()"),
        ),
    ),
    **_columns(
        OBSERVATION_TABLE,
        (
            ("observation_id", "text", False, None, ""),
            ("execution_box_id", "text", False, None, ""),
            ("strategy_lifecycle_id", "text", False, None, ""),
            ("context_epoch_id", "text", False, None, ""),
            ("strategy_thesis_id", "text", False, None, ""),
            ("symbol", "character varying", False, 32, ""),
            ("observed_at", "timestamp with time zone", False, None, ""),
            ("source_request_id", "text", True, None, ""),
            ("evidence_hash", "character varying", False, 71, ""),
            ("material_box_hash", "character varying", False, 71, ""),
            ("outcome", "character varying", False, 32, ""),
            ("evidence_payload", "jsonb", False, None, ""),
            ("execution_authority", "boolean", False, None, "false"),
            ("created_at", "timestamp with time zone", False, None, "now()"),
        ),
    ),
    **_columns(
        CANONICAL_CANDLE_TABLE,
        (
            ("id", "bigint", False, None, "nextval('canonical_candles_id_seq'::regclass)"),
            ("symbol", "character varying", False, 32, ""),
            ("timeframe", "character varying", False, 10, ""),
            ("open_time", "timestamp with time zone", False, None, ""),
            ("close_time", "timestamp with time zone", False, None, ""),
            ("open", "double precision", False, None, ""),
            ("high", "double precision", False, None, ""),
            ("low", "double precision", False, None, ""),
            ("close", "double precision", False, None, ""),
            ("volume", "double precision", False, None, "0"),
            ("tick_count", "integer", False, None, "0"),
            ("complete", "boolean", False, None, ""),
            ("selected_provider", "character varying", False, 100, ""),
            ("selected_feed", "character varying", False, 100, ""),
            ("provider_timestamp_semantics", "character varying", False, 32, ""),
            ("selected_raw_candle_id", "bigint", False, None, ""),
            ("selection_policy", "character varying", False, 100, ""),
            ("selection_rank", "integer", False, None, ""),
            ("content_hash", "character varying", False, 64, ""),
        ),
    ),
    **_columns(
        LIFECYCLE_TABLE,
        (
            ("strategy_lifecycle_id", "text", False, None, ""),
            ("symbol", "character varying", False, 32, ""),
            ("state", "character varying", False, 40, ""),
            ("last_event_at", "timestamp with time zone", False, None, ""),
        ),
    ),
    **_columns(
        CONTEXT_TABLE,
        (
            ("context_epoch_id", "text", False, None, ""),
            ("strategy_lifecycle_id", "text", False, None, ""),
            ("symbol", "character varying", False, 32, ""),
            ("state", "character varying", False, 20, ""),
            ("closed_at", "timestamp with time zone", True, None, ""),
            ("evidence_payload", "jsonb", False, None, ""),
        ),
    ),
    **_columns(
        THESIS_TABLE,
        (
            ("strategy_thesis_id", "text", False, None, ""),
            ("strategy_lifecycle_id", "text", False, None, ""),
            ("context_epoch_id", "text", False, None, ""),
            ("symbol", "character varying", False, 32, ""),
            ("strategy_direction", "character varying", False, 4, ""),
            ("state", "character varying", False, 20, ""),
            ("closed_at", "timestamp with time zone", True, None, ""),
            ("payload", "jsonb", False, None, ""),
        ),
    ),
}

_REQUIRED_CONSTRAINTS: dict[str, _ConstraintContract] = {
    f"{BOX_TABLE}_pkey": _ConstraintContract(BOX_TABLE, "p"),
    "fk_5scr_execution_box_lifecycle_v1": _ConstraintContract(BOX_TABLE, "f"),
    "fk_5scr_execution_box_context_scope_v1": _ConstraintContract(BOX_TABLE, "f"),
    "fk_5scr_execution_box_thesis_scope_v1": _ConstraintContract(BOX_TABLE, "f"),
    "fk_5scr_execution_box_previous_v1": _ConstraintContract(BOX_TABLE, "f"),
    "uq_5scr_execution_box_predecessor_scope_v1": _ConstraintContract(BOX_TABLE, "u"),
    "uq_5scr_execution_box_observation_scope_v1": _ConstraintContract(BOX_TABLE, "u"),
    "uq_5scr_execution_box_version_v1": _ConstraintContract(BOX_TABLE, "u"),
    "uq_5scr_execution_box_sequence_v1": _ConstraintContract(BOX_TABLE, "u"),
    "ck_5scr_execution_box_identity_v1": _ConstraintContract(BOX_TABLE, "c"),
    "ck_5scr_execution_box_geometry_v1": _ConstraintContract(BOX_TABLE, "c"),
    "ck_5scr_execution_box_state_v1": _ConstraintContract(BOX_TABLE, "c"),
    "ck_5scr_execution_box_sources_v1": _ConstraintContract(BOX_TABLE, "c"),
    "ck_5scr_execution_box_lineage_v1": _ConstraintContract(BOX_TABLE, "c"),
    "ck_5scr_execution_box_temporal_v1": _ConstraintContract(BOX_TABLE, "c"),
    "ck_5scr_execution_box_shadow_only_v1": _ConstraintContract(BOX_TABLE, "c"),
    f"{OBSERVATION_TABLE}_pkey": _ConstraintContract(OBSERVATION_TABLE, "p"),
    "fk_5scr_execution_box_observation_box_v1": _ConstraintContract(OBSERVATION_TABLE, "f"),
    "uq_5scr_execution_box_observation_clock_v1": _ConstraintContract(OBSERVATION_TABLE, "u"),
    "ck_5scr_execution_box_observation_identity_v1": _ConstraintContract(OBSERVATION_TABLE, "c"),
    "ck_5scr_execution_box_observation_outcome_v1": _ConstraintContract(OBSERVATION_TABLE, "c"),
    "ck_5scr_execution_box_observation_shadow_only_v1": _ConstraintContract(OBSERVATION_TABLE, "c"),
    "uq_5scr_thesis_execution_box_scope_v1": _ConstraintContract(THESIS_TABLE, "u"),
    "uq_5scr_context_epoch_scope_v1": _ConstraintContract(CONTEXT_TABLE, "u"),
}

# Populated from the final migration against disposable PostgreSQL 16 before
# release.  Missing entries deliberately fail closed; the catalog itself must
# be complete rather than silently falling back to substring matching.
_REQUIRED_CONSTRAINT_DEFINITION_HASHES: dict[str, str] = {
    "ck_5scr_execution_box_geometry_v1": "40dbeabc867e87c702c2f86b46090a1281746b2e4068317a57acf9d8400fdb2e",
    "ck_5scr_execution_box_identity_v1": "f8f9a3c0c9ae7f378041b1c5be51cceb58da59ec5add7a2de5a0dce0fd1c04bb",
    "ck_5scr_execution_box_lineage_v1": "0b4d01e09aa01cf277918eba79df859797c299020a1c3f603ec4253ffebf9980",
    "ck_5scr_execution_box_observation_identity_v1": "1522272f19bd506e40e99822ffb42c54121aa8c7d4d58b936805192bed6cd9fd",
    "ck_5scr_execution_box_observation_outcome_v1": "4e990d77d6678c68c8a20b1c57ffba392c37a201860874d6f023897b65386bf6",
    "ck_5scr_execution_box_observation_shadow_only_v1": "241ba579eb592c0fafb96ddb69ae9ef328390d3465b1b535b70e6977d20438a4",
    "ck_5scr_execution_box_shadow_only_v1": "9b996154165a14a6f559155e6d2a0abc80105aeee0ea7383feb1cc9f7f940544",
    "ck_5scr_execution_box_sources_v1": "c5aa78cc0327dea84d6abb69299656d43d4e59c618cc1a7e51a677ba042d2cb7",
    "ck_5scr_execution_box_state_v1": "707e4890c595b500cbfaad488bb20fac016832983c244e5c36a19d9d4232864e",
    "ck_5scr_execution_box_temporal_v1": "ea44942c9b9b27f03356ad277ef907b29bb75973f14e608620dd0d3b5e90afd5",
    "fk_5scr_execution_box_context_scope_v1": "cd752ec8c65105e4c15ec426a83fc643f87966388e23c460667edf60935a6c66",
    "fk_5scr_execution_box_lifecycle_v1": "31c316748300dbd4469cf8ccd91828fcdca520c4f93363bbcbb2f8a9411a7d32",
    "fk_5scr_execution_box_observation_box_v1": "3ad212cb55e694ece1f1664263959ad6c04670e11a59194ca6e9476fc6dc8986",
    "fk_5scr_execution_box_previous_v1": "40122972954e73bfa7a177dc48bf4e4ab82eb2b471388be34c43d29ce1016d06",
    "fk_5scr_execution_box_thesis_scope_v1": "0bc158c4768c2aca278785bf74badb138d0112c2eada9ee94b33b6618c27c243",
    "strategy_5scr_execution_box_observations_v1_pkey": "4dccce8e06e9a8f52111669142aaccc3bf8e8dd8d0bc6af971567bd55e45917c",
    "strategy_5scr_execution_boxes_v1_pkey": "e04fa22677ebc6d3d59e05a04b880e8fbf7ae8eaf10dda53c6f8c035215f087d",
    "uq_5scr_context_epoch_scope_v1": "fbafdfbe9eb8307bf9997f54d2109e55a3af46ff016a774fdbbf2096de482b59",
    "uq_5scr_execution_box_observation_clock_v1": "5f4a169aafeef2d3117c8baab2a5d4d458f2262f97bcd0f377b74574c9361a52",
    "uq_5scr_execution_box_observation_scope_v1": "3f805c903266813852e93d8e12ead26c17d78578e8fbdb0871c4f5426a51f63c",
    "uq_5scr_execution_box_predecessor_scope_v1": "af102b6508fbcff5c4e54d651d0c106e93ea2dfda31d72afc6638c477fc48a3e",
    "uq_5scr_execution_box_sequence_v1": "e3cefa1fc2cf026c43355e0b9a70f3b0b6ef9c8bea4e48010d1faf38bfae7525",
    "uq_5scr_execution_box_version_v1": "52f4d47689bbc991115a4a17e9f31a71c65a6fd4b3decb28ff16b822fbe890e1",
    "uq_5scr_thesis_execution_box_scope_v1": "0d0ae25a08807535a5beba46f3262e9e7d469dcf24580c91283cc2d7f4f55fa6",
}

_REQUIRED_INDEXES: dict[str, _IndexContract] = {
    "uq_5scr_execution_box_active_thesis_v1": _IndexContract(BOX_TABLE, True, ("strategy_thesis_id",)),
    "uq_5scr_execution_box_active_lifecycle_v1": _IndexContract(BOX_TABLE, True, ("strategy_lifecycle_id",)),
    "ix_5scr_execution_box_lifecycle_history_v1": _IndexContract(
        BOX_TABLE, False, ("strategy_lifecycle_id", "box_sequence", "execution_box_id")
    ),
    "uq_5scr_execution_box_observation_request_v1": _IndexContract(
        OBSERVATION_TABLE, True, ("strategy_thesis_id", "source_request_id")
    ),
    "ix_5scr_execution_box_observation_history_v1": _IndexContract(
        OBSERVATION_TABLE, False, ("strategy_thesis_id", "observed_at", "observation_id")
    ),
    "ix_canonical_candles_closed_asof": _IndexContract(
        CANONICAL_CANDLE_TABLE, False, ("symbol", "timeframe", "close_time")
    ),
}
_REQUIRED_INDEX_DEFINITION_HASHES: dict[str, str] = {
    "ix_5scr_execution_box_lifecycle_history_v1": "ce140fbc2db55f1d7d971cc7e9a1196e95c626e4bbe529a53e2451431377e69a",
    "ix_5scr_execution_box_observation_history_v1": "f284a367c9600870389f18304827b2bf9f2a868778d4b635817009d8fbdf5c55",
    "ix_canonical_candles_closed_asof": "7cdfcd915696824a0635c7c41d38dab8ea03ac179c503121e41819c998dd3b84",
    "uq_5scr_execution_box_active_lifecycle_v1": "677e5d24163bf37194acf7375ef296e01d9858f4486dfae36dbd055109ca2e7b",
    "uq_5scr_execution_box_active_thesis_v1": "73fa53bda5ac943db821af95c37eb1f9f8b693925cc25ef8186e336181c44537",
    "uq_5scr_execution_box_observation_request_v1": "224d61852096314f0be63cd559678b2288120348edb3d8e1ee6cc1eaf8ac6c51",
}

_REQUIRED_TRIGGERS: dict[str, _TriggerContract] = {
    "trg_strategy_5scr_execution_boxes_v1_guard": _TriggerContract(BOX_TABLE, "strategy_5scr_guard_execution_box_v1"),
    "trg_strategy_5scr_execution_box_observations_v1_immutable": _TriggerContract(
        OBSERVATION_TABLE, "strategy_5scr_reject_execution_box_observation_mutation_v1"
    ),
}
_REQUIRED_TRIGGER_DEFINITION_HASHES: dict[str, tuple[str, str]] = {
    "trg_strategy_5scr_execution_box_observations_v1_immutable": (
        "dbe9b421c99c0cfa9426253748e84ecb7d074bbf245aa31b39a514b2ef4ff409",
        "884fddcf149ded8ffc8f475e2524d1ba951a6c81b8d1e2baf78aaabe005dac3f",
    ),
    "trg_strategy_5scr_execution_boxes_v1_guard": (
        "35fc57cd6e79aa808968abe6a96b8f50989f235c3da9d6a91ea5e662c30c888c",
        "735ca65d1afd5c8506d13309f7417b892ded6cdda9d0f53c4f423526b67f16e4",
    ),
}


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
        formation_evidence = ExecutionBoxEvidenceV1.model_validate(_json(_row_value(row, "evidence_payload")))
        latest_evidence = ExecutionBoxEvidenceV1.model_validate(_json(_row_value(row, "latest_evidence_payload")))
    except (ValidationError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_EVIDENCE_PAYLOAD_INVALID") from exc
    if (
        formation_evidence.strategy_lifecycle_id != box.strategy_lifecycle_id
        or formation_evidence.context_epoch_id != box.context_epoch_id
        or formation_evidence.strategy_thesis_id != box.strategy_thesis_id
        or formation_evidence.thesis_semantic_identity_hash != box.thesis_semantic_identity_hash
        or formation_evidence.symbol != box.symbol
        or formation_evidence.strategy_direction != box.strategy_direction
        or formation_evidence.route_type != box.route_type
        or material_box_hash(formation_evidence) != box.material_box_hash
        or execution_box_evidence_hash(formation_evidence) != str(_row_value(row, "formation_evidence_hash"))
        or tuple(sorted(item.material_candle_hash for item in formation_evidence.material_m1_candles))
        != box.source_m1_ids
        or latest_evidence.strategy_lifecycle_id != box.strategy_lifecycle_id
        or latest_evidence.context_epoch_id != box.context_epoch_id
        or latest_evidence.strategy_thesis_id != box.strategy_thesis_id
        or latest_evidence.symbol != box.symbol
        or latest_evidence.strategy_direction != box.strategy_direction
        or latest_evidence.route_type != box.route_type
        or material_box_hash(latest_evidence) != box.material_box_hash
        or execution_box_evidence_hash(latest_evidence) != box.evidence_hash
        or (
            latest_evidence.observed_at_utc != box.last_observed_at_utc
            if box.state in {"BUILDING", "FROZEN"}
            else latest_evidence.observed_at_utc > box.last_observed_at_utc
        )
        or latest_evidence.source_request_id != box.last_source_request_id
        or tuple(sorted(item.material_candle_hash for item in latest_evidence.material_m1_candles)) != box.source_m1_ids
        or tuple(sorted(item.candle_evidence_id for item in latest_evidence.material_m1_candles))
        != box.source_m1_evidence_ids
        or execution_box_id(
            box.strategy_thesis_id,
            box.box_sequence,
            box.box_version,
            box.material_box_hash,
        )
        != box.execution_box_id
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
        thesis = _p4_thesis_from_row(row)
    except (ValidationError, TypeError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        raise ExecutionBoxV1IntegrityError("DIRECTIONAL_THESIS_PAYLOAD_INVALID") from exc
    if thesis.execution_authority or thesis.valid_for_execution:
        raise ExecutionBoxV1IntegrityError("DIRECTIONAL_THESIS_DURABLE_SCOPE_DRIFT")
    return thesis


def _m1_from_canonical_row(row: Any) -> M1CandleAuthorityV1:
    """Reconstruct the exact P5 candle authority from its canonical row."""

    material: dict[str, Any] = {
        "symbol": str(_row_value(row, "symbol")).upper(),
        "timeframe": str(_row_value(row, "timeframe")).upper(),
        "open_time_utc": _row_value(row, "open_time"),
        "close_time_utc": _row_value(row, "close_time"),
        "open": float(_row_value(row, "open")),
        "high": float(_row_value(row, "high")),
        "low": float(_row_value(row, "low")),
        "close": float(_row_value(row, "close")),
    }
    material_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
        ).hexdigest()
    )
    source_hash = str(_row_value(row, "content_hash"))
    if not source_hash.startswith("sha256:"):
        source_hash = "sha256:" + source_hash
    payload: dict[str, Any] = {
        **material,
        "candle_evidence_id": "sha256:" + ("0" * 64),
        "material_candle_hash": material_hash,
        "source_content_hash": source_hash,
        "canonical_row_id": int(_row_value(row, "id")),
        "selected_raw_candle_id": int(_row_value(row, "selected_raw_candle_id")),
        "volume": float(_row_value(row, "volume") or 0),
        "tick_count": int(_row_value(row, "tick_count") or 0),
        "provider": str(_row_value(row, "selected_provider")),
        "feed": str(_row_value(row, "selected_feed")),
        "provider_timestamp_semantics": str(_row_value(row, "provider_timestamp_semantics")).upper(),
        "selection_policy": str(_row_value(row, "selection_policy")),
        "selection_rank": int(_row_value(row, "selection_rank")),
        "is_closed": True,
        "price_authority": True,
    }
    provisional = M1CandleAuthorityV1.model_construct(**payload)
    evidence_payload = provisional.model_dump(mode="json", exclude={"candle_evidence_id"})
    candle_id = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                evidence_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
            ).encode()
        ).hexdigest()
    )
    return M1CandleAuthorityV1.model_validate({**payload, "candle_evidence_id": candle_id})


async def _canonicalize_m1_evidence(connection: Any, evidence: ExecutionBoxEvidenceV1) -> ExecutionBoxEvidenceV1:
    row_ids = tuple(item.canonical_row_id for item in evidence.material_m1_candles)
    if any(item is None for item in row_ids):
        raise ExecutionBoxV1IntegrityError("CANONICAL_M1_CANDLE_MISSING")
    rows = await connection.fetch(
        f"""
        SELECT id,symbol,timeframe,open_time,close_time,open,high,low,close,
               volume,tick_count,complete,selected_provider,selected_feed,
               provider_timestamp_semantics,selected_raw_candle_id,selection_policy,
               selection_rank,content_hash
        FROM {CANONICAL_CANDLE_TABLE}
        WHERE id=ANY($1::bigint[])
        ORDER BY open_time,id
        FOR SHARE
        """,
        list(cast(tuple[int, ...], row_ids)),
    )
    if len(rows) != len(row_ids):
        raise ExecutionBoxV1IntegrityError("CANONICAL_M1_CANDLE_MISSING")
    if any(not bool(_row_value(row, "complete")) for row in rows):
        raise ExecutionBoxV1IntegrityError("CANONICAL_M1_CANDLE_INCOMPLETE")
    try:
        canonical = tuple(_m1_from_canonical_row(row) for row in rows)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ExecutionBoxV1IntegrityError("CANONICAL_M1_CANDLE_DRIFT") from exc
    supplied = tuple(evidence.material_m1_candles)
    if canonical != supplied:
        raise ExecutionBoxV1IntegrityError("CANONICAL_M1_CANDLE_DRIFT")
    return evidence.model_copy(update={"material_m1_candles": canonical})


async def _validate_predecessor_chain(connection: Any, box: ExecutionBoxV1) -> None:
    if box.box_version == 1:
        return
    row = await connection.fetchrow(
        f"SELECT * FROM {BOX_TABLE} WHERE execution_box_id=$1 FOR UPDATE",
        box.previous_execution_box_id,
    )
    if row is None:
        raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_PREDECESSOR_MISSING")
    predecessor = _box_from_row(row)
    if (
        predecessor.strategy_lifecycle_id != box.strategy_lifecycle_id
        or predecessor.context_epoch_id != box.context_epoch_id
        or predecessor.strategy_thesis_id != box.strategy_thesis_id
        or predecessor.symbol != box.symbol
        or predecessor.strategy_direction != box.strategy_direction
        or predecessor.box_sequence != box.box_sequence - 1
        or predecessor.box_version != box.box_version - 1
        or predecessor.state != "SUPERSEDED"
    ):
        raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_PREDECESSOR_SCOPE_DRIFT")


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
                tuple(sorted(_REQUIRED_TABLES)),
                tuple(sorted(f"{table}.{column}" for table, column in _REQUIRED_COLUMNS)),
                (),
                tuple(sorted(_REQUIRED_CONSTRAINTS)),
                (),
                tuple(sorted(_REQUIRED_INDEXES)),
                (),
                tuple(sorted(_REQUIRED_TRIGGERS)),
                (),
            )
        table_rows = await self._pg.fetch(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname=current_schema() AND tablename=ANY($1::text[])",
            sorted(_REQUIRED_TABLES),
        )
        column_rows = await self._pg.fetch(
            """
            SELECT table_name,column_name,data_type,is_nullable,character_maximum_length,column_default
            FROM information_schema.columns
            WHERE table_schema=current_schema() AND table_name=ANY($1::text[])
            """,
            sorted(_REQUIRED_TABLES),
        )
        constraint_rows = await self._pg.fetch(
            """
            SELECT con.conname,con.contype::text AS contype,con.convalidated,
                   cls.relname AS table_name,pg_get_constraintdef(con.oid) AS definition
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class cls ON cls.oid=con.conrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid=cls.relnamespace
            WHERE ns.nspname=current_schema() AND con.conname=ANY($1::text[])
            """,
            sorted(_REQUIRED_CONSTRAINTS),
        )
        index_rows = await self._pg.fetch(
            """
            SELECT cls.relname AS table_name,index_cls.relname AS index_name,
                   idx.indisunique,idx.indisvalid,idx.indisready,
                   pg_get_indexdef(idx.indexrelid) AS definition,
                   pg_get_expr(idx.indpred,idx.indrelid) AS predicate,
                   ARRAY(SELECT attr.attname FROM unnest(idx.indkey) WITH ORDINALITY key(attnum,pos)
                         JOIN pg_catalog.pg_attribute attr ON attr.attrelid=idx.indrelid AND attr.attnum=key.attnum
                         ORDER BY key.pos) AS columns
            FROM pg_catalog.pg_index idx
            JOIN pg_catalog.pg_class cls ON cls.oid=idx.indrelid
            JOIN pg_catalog.pg_class index_cls ON index_cls.oid=idx.indexrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid=cls.relnamespace
            WHERE ns.nspname=current_schema() AND index_cls.relname=ANY($1::text[])
            """,
            sorted(_REQUIRED_INDEXES),
        )
        trigger_rows = await self._pg.fetch(
            """
            SELECT trg.tgname,cls.relname AS table_name,trg.tgenabled,
                   pg_get_triggerdef(trg.oid) AS trigger_definition,
                   proc.proname AS function_name,pg_get_functiondef(proc.oid) AS function_definition
            FROM pg_catalog.pg_trigger trg
            JOIN pg_catalog.pg_class cls ON cls.oid=trg.tgrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid=cls.relnamespace
            JOIN pg_catalog.pg_proc proc ON proc.oid=trg.tgfoid
            WHERE ns.nspname=current_schema() AND NOT trg.tgisinternal
              AND trg.tgname=ANY($1::text[])
            """,
            sorted(_REQUIRED_TRIGGERS),
        )
        present_tables = {str(_row_value(row, "tablename")) for row in table_rows}
        column_map = {
            (str(_row_value(row, "table_name")), str(_row_value(row, "column_name"))): row for row in column_rows
        }
        satisfied_columns: set[str] = set()
        invalid_columns: list[str] = []
        for key, expected in _REQUIRED_COLUMNS.items():
            row = column_map.get(key)
            if row is None:
                continue
            label = f"{key[0]}.{key[1]}"
            actual = (
                str(_row_value(row, "data_type")).lower(),
                str(_row_value(row, "is_nullable")).upper() == "YES",
                _row_value(row, "character_maximum_length"),
                _normalize_sql(_row_value(row, "column_default")),
            )
            expected_tuple = (expected.data_type, expected.nullable, expected.max_length, expected.default)
            if actual != expected_tuple:
                invalid_columns.append(label)
            else:
                satisfied_columns.add(label)
        constraint_map = {str(_row_value(row, "conname")): row for row in constraint_rows}
        invalid_constraints: list[str] = []
        for name, expected in _REQUIRED_CONSTRAINTS.items():
            row = constraint_map.get(name)
            if row is None:
                continue
            if (
                str(_row_value(row, "table_name")) != expected.table
                or str(_row_value(row, "contype")) != expected.contype
                or not bool(_row_value(row, "convalidated"))
                or _sql_fingerprint(_row_value(row, "definition")) != _REQUIRED_CONSTRAINT_DEFINITION_HASHES.get(name)
            ):
                invalid_constraints.append(name)
        index_map = {str(_row_value(row, "index_name")): row for row in index_rows}
        invalid_indexes: list[str] = []
        for name, expected in _REQUIRED_INDEXES.items():
            row = index_map.get(name)
            if row is None:
                continue
            if (
                str(_row_value(row, "table_name")) != expected.table
                or bool(_row_value(row, "indisunique")) != expected.unique
                or not bool(_row_value(row, "indisvalid"))
                or not bool(_row_value(row, "indisready"))
                or tuple(str(item) for item in (_row_value(row, "columns") or ())) != expected.columns
                or _sql_fingerprint(_row_value(row, "definition")) != _REQUIRED_INDEX_DEFINITION_HASHES.get(name)
            ):
                invalid_indexes.append(name)
        trigger_map = {str(_row_value(row, "tgname")): row for row in trigger_rows}
        invalid_triggers: list[str] = []
        for name, expected in _REQUIRED_TRIGGERS.items():
            trigger = trigger_map.get(name)
            if trigger is None:
                continue
            hashes = _REQUIRED_TRIGGER_DEFINITION_HASHES.get(name)
            if (
                str(_row_value(trigger, "table_name")) != expected.table
                or _catalog_char(_row_value(trigger, "tgenabled")) != "O"
                or str(_row_value(trigger, "function_name")) != expected.function
                or hashes is None
                or _sql_fingerprint(_row_value(trigger, "trigger_definition")) != hashes[0]
                or _sql_fingerprint(_row_value(trigger, "function_definition")) != hashes[1]
            ):
                invalid_triggers.append(name)
        invalid_labels = set(invalid_columns)
        expected_labels = {f"{table}.{column}" for table, column in _REQUIRED_COLUMNS}
        status = ExecutionBoxV1SchemaStatus(
            tuple(sorted(_REQUIRED_TABLES - present_tables)),
            tuple(sorted(expected_labels - satisfied_columns - invalid_labels)),
            tuple(sorted(invalid_columns)),
            tuple(sorted(set(_REQUIRED_CONSTRAINTS) - set(constraint_map))),
            tuple(sorted(invalid_constraints)),
            tuple(sorted(set(_REQUIRED_INDEXES) - set(index_map))),
            tuple(sorted(invalid_indexes)),
            tuple(sorted(set(_REQUIRED_TRIGGERS) - set(trigger_map))),
            tuple(sorted(invalid_triggers)),
        )
        thesis_status = await Strategy5SCRDirectionalThesisV1Repository(self._pg).schema_status()
        return ExecutionBoxV1SchemaStatus(
            tuple(
                sorted(
                    (
                        *status.missing_tables,
                        *(f"p4:{item}" for item in thesis_status.missing_tables),
                    )
                )
            ),
            tuple(
                sorted(
                    (
                        *status.missing_columns,
                        *(f"p4:{item}" for item in thesis_status.missing_columns),
                    )
                )
            ),
            tuple(
                sorted(
                    (
                        *status.invalid_columns,
                        *(f"p4:{item}" for item in thesis_status.invalid_columns),
                    )
                )
            ),
            tuple(
                sorted(
                    (
                        *status.missing_constraints,
                        *(f"p4:{item}" for item in thesis_status.missing_constraints),
                    )
                )
            ),
            tuple(
                sorted(
                    (
                        *status.invalid_constraints,
                        *(f"p4:{item}" for item in thesis_status.invalid_constraints),
                    )
                )
            ),
            tuple(
                sorted(
                    (
                        *status.missing_indexes,
                        *(f"p4:{item}" for item in thesis_status.missing_indexes),
                    )
                )
            ),
            tuple(
                sorted(
                    (
                        *status.invalid_indexes,
                        *(f"p4:{item}" for item in thesis_status.invalid_indexes),
                    )
                )
            ),
            tuple(sorted((*status.missing_triggers, *(f"p4:{item}" for item in thesis_status.missing_triggers)))),
            tuple(sorted((*status.invalid_triggers, *(f"p4:{item}" for item in thesis_status.invalid_triggers)))),
        )

    async def load_active(self, strategy_thesis_id: str) -> ExecutionBoxV1 | None:
        row = await self._pg.fetchrow(
            f"SELECT * FROM {BOX_TABLE} WHERE strategy_thesis_id=$1 AND state IN ('BUILDING','FROZEN')",
            strategy_thesis_id,
        )
        if row is None:
            return None
        box = _box_from_row(row)
        async with self._pg.transaction() as connection:
            await _validate_predecessor_chain(connection, box)
        return box

    async def load_history(self, strategy_thesis_id: str) -> tuple[ExecutionBoxV1, ...]:
        rows = await self._pg.fetch(
            f"SELECT * FROM {BOX_TABLE} WHERE strategy_thesis_id=$1 ORDER BY box_version,execution_box_id",
            strategy_thesis_id,
        )
        boxes = tuple(_box_from_row(row) for row in rows)
        by_id = {box.execution_box_id: box for box in boxes}
        for box in boxes:
            if box.box_version == 1:
                continue
            predecessor = by_id.get(cast(str, box.previous_execution_box_id))
            if (
                predecessor is None
                or predecessor.strategy_lifecycle_id != box.strategy_lifecycle_id
                or predecessor.context_epoch_id != box.context_epoch_id
                or predecessor.strategy_thesis_id != box.strategy_thesis_id
                or predecessor.symbol != box.symbol
                or predecessor.strategy_direction != box.strategy_direction
                or predecessor.box_sequence != box.box_sequence - 1
                or predecessor.box_version != box.box_version - 1
                or predecessor.state != "SUPERSEDED"
            ):
                raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_PREDECESSOR_SCOPE_DRIFT")
        return boxes

    async def process_evidence(self, evidence: ExecutionBoxEvidenceV1) -> ExecutionBoxPersistenceResult:
        async with self._pg.transaction() as connection:
            lifecycle = await connection.fetchrow(
                f"SELECT strategy_lifecycle_id,symbol,state,last_event_at FROM {LIFECYCLE_TABLE} "
                "WHERE strategy_lifecycle_id=$1 FOR UPDATE",
                evidence.strategy_lifecycle_id,
            )
            if lifecycle is None:
                return ExecutionBoxPersistenceResult("REJECTED", "CANONICAL_LIFECYCLE_MISSING")
            lifecycle_active_row = await connection.fetchrow(
                f"SELECT * FROM {BOX_TABLE} WHERE strategy_lifecycle_id=$1 "
                "AND state IN ('BUILDING','FROZEN') FOR UPDATE",
                evidence.strategy_lifecycle_id,
            )
            lifecycle_active = None if lifecycle_active_row is None else _box_from_row(lifecycle_active_row)

            # A terminal lifecycle is authoritative even when the incoming
            # replay carries a missing/bogus context or thesis.  Reconcile the
            # persisted active chain first, using only durable parent clocks.
            if str(_row_value(lifecycle, "state")) in TERMINAL_LIFECYCLE_STATES:
                if lifecycle_active is None:
                    return ExecutionBoxPersistenceResult("REJECTED", "EXECUTION_BOX_PARENT_NOT_ACTIVE")
                await _validate_predecessor_chain(connection, lifecycle_active)
                parent_row = await connection.fetchrow(
                    f"SELECT * FROM {THESIS_TABLE} WHERE strategy_thesis_id=$1 FOR UPDATE",
                    lifecycle_active.strategy_thesis_id,
                )
                if parent_row is None:
                    raise ExecutionBoxV1IntegrityError("ACTIVE_EXECUTION_BOX_THESIS_MISSING")
                parent = _thesis_from_row(parent_row)
                await Strategy5SCRDirectionalThesisV1Repository._validate_thesis_proof_chain(connection, parent)
                closed = close_execution_box(
                    lifecycle_active,
                    state="INVALIDATED",
                    occurred_at_utc=_terminal_clock(
                        _row_value(lifecycle, "last_event_at"),
                        parent.closed_at_utc,
                        floor=lifecycle_active.opened_at_utc,
                    ),
                )
                await self._transition_box(connection, lifecycle_active, closed, None)
                return ExecutionBoxPersistenceResult("INVALIDATED", "EXECUTION_BOX_PARENT_NOT_ACTIVE", closed)

            if str(_row_value(lifecycle, "symbol")).upper() != evidence.symbol:
                return ExecutionBoxPersistenceResult("REJECTED", "CANONICAL_LIFECYCLE_SCOPE_MISMATCH")

            context = await connection.fetchrow(
                f"SELECT * FROM {CONTEXT_TABLE} WHERE context_epoch_id=$1 AND strategy_lifecycle_id=$2 FOR UPDATE",
                evidence.context_epoch_id,
                evidence.strategy_lifecycle_id,
            )
            if context is None:
                return ExecutionBoxPersistenceResult("REJECTED", "CONTEXT_EPOCH_MISSING")
            try:
                context_epoch = _context_from_row(context)
            except RuntimeError as exc:
                raise ExecutionBoxV1IntegrityError("CONTEXT_EPOCH_DURABLE_INTEGRITY_DRIFT") from exc
            if context_epoch.symbol != evidence.symbol:
                return ExecutionBoxPersistenceResult("REJECTED", "CONTEXT_EPOCH_SCOPE_MISMATCH")
            thesis_row = await connection.fetchrow(
                f"SELECT * FROM {THESIS_TABLE} WHERE strategy_thesis_id=$1 FOR UPDATE",
                evidence.strategy_thesis_id,
            )
            if thesis_row is None:
                return ExecutionBoxPersistenceResult("REJECTED", "DIRECTIONAL_THESIS_MISSING")
            thesis = _thesis_from_row(thesis_row)
            await Strategy5SCRDirectionalThesisV1Repository._validate_thesis_proof_chain(connection, thesis)

            if lifecycle_active is not None and lifecycle_active.strategy_thesis_id != thesis.strategy_thesis_id:
                await _validate_predecessor_chain(connection, lifecycle_active)
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
                    occurred_at_utc=_terminal_clock(
                        prior_thesis.closed_at_utc,
                        floor=lifecycle_active.opened_at_utc,
                    ),
                )
                await self._transition_box(connection, lifecycle_active, closed, None)
                lifecycle_active = None
            active_row = await connection.fetchrow(
                f"SELECT * FROM {BOX_TABLE} WHERE strategy_thesis_id=$1 AND state IN ('BUILDING','FROZEN') FOR UPDATE",
                thesis.strategy_thesis_id,
            )
            current = None if active_row is None else _box_from_row(active_row)
            if current is not None:
                await _validate_predecessor_chain(connection, current)
            if thesis.state != "ACTIVE" or context_epoch.state != "ACTIVE":
                if current is None:
                    return ExecutionBoxPersistenceResult("REJECTED", "EXECUTION_BOX_PARENT_NOT_ACTIVE")
                closed = close_execution_box(
                    current,
                    state="INVALIDATED",
                    occurred_at_utc=_terminal_clock(
                        thesis.closed_at_utc,
                        context_epoch.closed_at_utc,
                        floor=current.opened_at_utc,
                    ),
                )
                await self._transition_box(connection, current, closed, None)
                return ExecutionBoxPersistenceResult("INVALIDATED", "EXECUTION_BOX_PARENT_NOT_ACTIVE", closed)

            try:
                evidence = await _canonicalize_m1_evidence(connection, evidence)
            except ExecutionBoxV1IntegrityError as exc:
                reason = str(exc)
                status: ExecutionBoxPersistenceStatus = (
                    "REJECTED"
                    if reason in {"CANONICAL_M1_CANDLE_MISSING", "CANONICAL_M1_CANDLE_INCOMPLETE"}
                    else "QUARANTINED"
                )
                return ExecutionBoxPersistenceResult(status, reason, current)
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
            if reduced.status in {"REJECTED", "QUARANTINED"}:
                return ExecutionBoxPersistenceResult(
                    cast(ExecutionBoxPersistenceStatus, reduced.status),
                    reduced.reason_code,
                    reduced.box,
                    reduced.previous_box,
                )
            if reduced.status == "DUPLICATE":
                if reduced.box is not None:
                    await self._insert_observation(connection, reduced.box, evidence, "DUPLICATE")
                return ExecutionBoxPersistenceResult(
                    "DUPLICATE",
                    reduced.reason_code,
                    reduced.box,
                    reduced.previous_box,
                )
            if reduced.box is None:
                raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_REDUCTION_MISSING_STATE")
            if reduced.status == "NO_CHANGE":
                if reduced.previous_box is None:
                    raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_CURSOR_PREDECESSOR_MISSING")
                await self._transition_box(connection, reduced.previous_box, reduced.box, evidence)
                await self._insert_observation(connection, reduced.box, evidence, "NO_CHANGE")
            elif reduced.status == "FROZEN" and reduced.previous_box is not None:
                await self._transition_box(connection, reduced.previous_box, reduced.box, evidence)
                await self._insert_observation(connection, reduced.box, evidence, "FROZEN")
            elif reduced.status == "SUPERSEDED":
                if reduced.previous_box is None:
                    raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_PREDECESSOR_MISSING")
                # The incoming evidence forms the successor.  It must not
                # overwrite the predecessor's durable latest-observation
                # cursor while that predecessor is being superseded.
                await self._transition_box(connection, current, reduced.previous_box, None)  # type: ignore[arg-type]
                await self._insert_box(connection, reduced.box, evidence)
                await self._insert_observation(connection, reduced.box, evidence, "SUPERSEDED")
            else:
                await self._insert_box(connection, reduced.box, evidence)
                await self._insert_observation(connection, reduced.box, evidence, "OPENED")
            return ExecutionBoxPersistenceResult(
                "PERSISTED" if reduced.status == "OPENED" else cast(ExecutionBoxPersistenceStatus, reduced.status),
                reduced.reason_code,
                reduced.box,
                reduced.previous_box,
            )

    async def _insert_box(self, connection: Any, box: ExecutionBoxV1, evidence: ExecutionBoxEvidenceV1) -> None:
        previous_sequence = box.box_sequence - 1 if box.previous_execution_box_id is not None else None
        previous_version = box.box_version - 1 if box.previous_execution_box_id is not None else None
        evidence_json = json.dumps(evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        result = await connection.execute(
            f"""
            INSERT INTO {BOX_TABLE} (
                execution_box_id,strategy_lifecycle_id,context_epoch_id,strategy_thesis_id,
                box_sequence,box_version,previous_execution_box_id,previous_box_sequence,previous_box_version,
                symbol,strategy_direction,
                route_type,state,box_low,box_high,opened_at,frozen_at,freeze_authority_hash,superseded_at,
                invalidated_at,consumed_at,expired_at,material_box_hash,formation_evidence_hash,evidence_hash,
                thesis_semantic_identity_hash,source_m1_ids,source_m1_evidence_ids,
                last_observed_at,last_source_request_id,state_version,rule_version,
                valid_for_execution,execution_authority,payload,evidence_payload,latest_evidence_payload,
                freeze_evidence_payload
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                $21,$22,$23,$24,$25,$26,$27::jsonb,$28::jsonb,$29,$30,$31,$32,false,false,
                $33::jsonb,$34::jsonb,$35::jsonb,$36::jsonb
            )
            """,
            box.execution_box_id,
            box.strategy_lifecycle_id,
            box.context_epoch_id,
            box.strategy_thesis_id,
            box.box_sequence,
            box.box_version,
            box.previous_execution_box_id,
            previous_sequence,
            previous_version,
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
            execution_box_evidence_hash(evidence),
            box.evidence_hash,
            box.thesis_semantic_identity_hash,
            json.dumps(list(box.source_m1_ids), separators=(",", ":")),
            json.dumps(list(box.source_m1_evidence_ids), separators=(",", ":")),
            box.last_observed_at_utc,
            box.last_source_request_id,
            box.state_version,
            box.rule_version,
            json.dumps(box.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            evidence_json,
            evidence_json,
            (evidence_json if box.freeze_authority_hash is not None else None),
        )
        if not str(result).endswith(" 1"):
            raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_INSERT_FAILED")

    async def _transition_box(
        self,
        connection: Any,
        previous: ExecutionBoxV1,
        updated: ExecutionBoxV1,
        evidence: ExecutionBoxEvidenceV1 | None,
    ) -> None:
        evidence_json = (
            None
            if evidence is None
            else json.dumps(evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        )
        result = await connection.execute(
            f"""
            UPDATE {BOX_TABLE} SET state=$2,frozen_at=$3,freeze_authority_hash=$4,
                freeze_evidence_payload=CASE WHEN $5::jsonb IS NULL THEN freeze_evidence_payload ELSE $5::jsonb END,
                superseded_at=$6,invalidated_at=$7,consumed_at=$8,expired_at=$9,last_observed_at=$10,
                last_source_request_id=$11,state_version=$12,evidence_hash=$13,
                source_m1_evidence_ids=$14::jsonb,
                latest_evidence_payload=CASE WHEN $15::jsonb IS NULL THEN latest_evidence_payload ELSE $15::jsonb END,
                payload=$16::jsonb,updated_at=now()
            WHERE execution_box_id=$1 AND state_version=$17
            """,
            updated.execution_box_id,
            updated.state,
            updated.frozen_at_utc,
            updated.freeze_authority_hash,
            (
                evidence_json
                if evidence is not None and previous.state == "BUILDING" and updated.state == "FROZEN"
                else None
            ),
            updated.superseded_at_utc,
            updated.invalidated_at_utc,
            updated.consumed_at_utc,
            updated.expired_at_utc,
            updated.last_observed_at_utc,
            updated.last_source_request_id,
            updated.state_version,
            updated.evidence_hash,
            json.dumps(list(updated.source_m1_evidence_ids), separators=(",", ":")),
            evidence_json,
            json.dumps(updated.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            previous.state_version,
        )
        if not str(result).endswith(" 1"):
            raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_STATE_VERSION_NOT_ADVANCED")

    async def _insert_observation(
        self,
        connection: Any,
        box: ExecutionBoxV1,
        evidence: ExecutionBoxEvidenceV1,
        outcome: Literal["OPENED", "DUPLICATE", "NO_CHANGE", "FROZEN", "SUPERSEDED"],
    ) -> None:
        evidence_hash = execution_box_evidence_hash(evidence)
        observation_id = _observation_id(box.strategy_thesis_id, evidence.observed_at_utc, evidence_hash)
        payload = json.dumps(evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        result = await connection.execute(
            f"""
            INSERT INTO {OBSERVATION_TABLE} (
                observation_id,execution_box_id,strategy_lifecycle_id,context_epoch_id,
                strategy_thesis_id,symbol,observed_at,source_request_id,evidence_hash,
                material_box_hash,outcome,evidence_payload,execution_authority
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,false)
            ON CONFLICT DO NOTHING
            """,
            observation_id,
            box.execution_box_id,
            box.strategy_lifecycle_id,
            box.context_epoch_id,
            box.strategy_thesis_id,
            box.symbol,
            evidence.observed_at_utc,
            evidence.source_request_id,
            evidence_hash,
            material_box_hash(evidence),
            outcome,
            payload,
        )
        if str(result).endswith(" 1"):
            return
        row = await connection.fetchrow(
            f"SELECT * FROM {OBSERVATION_TABLE} WHERE strategy_thesis_id=$1 "
            "AND (observation_id=$2 OR observed_at=$3 OR (source_request_id IS NOT NULL AND source_request_id=$4)) "
            "FOR UPDATE",
            box.strategy_thesis_id,
            observation_id,
            evidence.observed_at_utc,
            evidence.source_request_id,
        )
        if row is None:
            raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_OBSERVATION_CONFLICT_UNKNOWN")
        if (
            str(_row_value(row, "observation_id")) != observation_id
            or str(_row_value(row, "execution_box_id")) != box.execution_box_id
            or str(_row_value(row, "strategy_lifecycle_id")) != box.strategy_lifecycle_id
            or str(_row_value(row, "context_epoch_id")) != box.context_epoch_id
            or str(_row_value(row, "strategy_thesis_id")) != box.strategy_thesis_id
            or str(_row_value(row, "symbol")) != box.symbol
            or str(_row_value(row, "evidence_hash")) != evidence_hash
            or str(_row_value(row, "material_box_hash")) != material_box_hash(evidence)
            or bool(_row_value(row, "execution_authority"))
            or _json(_row_value(row, "evidence_payload")) != evidence.model_dump(mode="json")
        ):
            raise ExecutionBoxV1IntegrityError("EXECUTION_BOX_OBSERVATION_IDENTITY_DRIFT")


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
