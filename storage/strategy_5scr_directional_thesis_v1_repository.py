"""Atomic shadow-only persistence for ordered 5S-CR structural proofs.

The repository freezes authoritative H1/M15 candles into append-only proof
rows, builds one immutable DirectionalThesis per semantic proof chain, and
serializes all state changes under the parent Lifecycle V2 row lock.  It never
creates entries, risk reservations, commands, or broker authority.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import ValidationError

from analysis.strategy_5scr_context_epoch_v1 import context_evidence_hash, material_context_hash
from analysis.strategy_5scr_directional_thesis_v1 import (
    DirectionalThesisBuildArtifact,
    advance_directional_thesis_liveness,
    build_directional_thesis_proofs,
    candle_evidence_hash,
    candle_material_hash,
    close_directional_thesis,
    evaluate_active_structural_liveness,
)
from analysis.strategy_5scr_structural_proof_provider_v1 import (
    Strategy5SCRStructuralProofProviderV1,
    candle_authority_from_row,
)
from contracts.strategy_5scr_context_epoch_v1 import MaterialContextEvidenceV1, StrategyContextEpochV1
from contracts.strategy_5scr_directional_thesis_v1 import (
    DIRECTIONAL_THESIS_RULE_VERSION,
    ClosedCandleAuthorityRefV1,
    Direction,
    DirectionalThesisEvidenceV1,
    DirectionalThesisV1,
    H1StructureProofV1,
    M15StructuralProofV1,
    PressureDirectionAuthorityV1,
    RouteDirectionAuthorizationV1,
)
from contracts.strategy_5scr_lifecycle_v2 import TERMINAL_LIFECYCLE_STATES
from storage.postgres_client import PostgresClient, pg_client

H1_PROOF_TABLE = "strategy_5scr_h1_structure_proofs_v1"
M15_PROOF_TABLE = "strategy_5scr_m15_structural_proofs_v1"
THESIS_TABLE = "strategy_5scr_directional_theses_v1"
LIFECYCLE_TABLE = "strategy_5scr_analysis_lifecycles_v2"
CONTEXT_TABLE = "strategy_5scr_context_epochs_v1"
CANONICAL_CANDLE_TABLE = "canonical_candles"

DIRECTIONAL_THESIS_V1_WRITER_FLAG = "STRATEGY_5SCR_DIRECTIONAL_THESIS_V1_WRITER_ENABLED"
DIRECTIONAL_THESIS_V1_SHADOW_ONLY_FLAG = "STRATEGY_5SCR_DIRECTIONAL_THESIS_V1_SHADOW_ONLY"

_REQUIRED_TABLES = frozenset(
    {H1_PROOF_TABLE, M15_PROOF_TABLE, THESIS_TABLE, CANONICAL_CANDLE_TABLE, LIFECYCLE_TABLE, CONTEXT_TABLE}
)


def _normalize_sql(value: Any) -> str:
    """Fingerprint the exact stable PostgreSQL catalog representation."""

    return str(value or "")


def _sql_fingerprint(value: Any) -> str:
    """Hash one exact normalized PostgreSQL catalog definition."""

    return hashlib.sha256(_normalize_sql(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _ColumnContract:
    data_type: str
    nullable: bool
    max_length: int | None = None
    default: str = ""


def _columns(
    table: str,
    definitions: Sequence[tuple[str, str, bool, int | None, str]],
) -> dict[tuple[str, str], _ColumnContract]:
    return {
        (table, name): _ColumnContract(data_type, nullable, max_length, default)
        for name, data_type, nullable, max_length, default in definitions
    }


_REQUIRED_COLUMNS = {
    **_columns(
        H1_PROOF_TABLE,
        (
            ("h1_proof_id", "text", False, None, ""),
            ("strategy_lifecycle_id", "text", False, None, ""),
            ("context_epoch_id", "text", False, None, ""),
            ("symbol", "character varying", False, 32, ""),
            ("strategy_direction", "character varying", False, 4, ""),
            ("structure_event", "character varying", False, 20, ""),
            ("anchor_candle_id", "character varying", False, 71, ""),
            ("confirmation_candle_id", "character varying", False, 71, ""),
            ("reference_level", "double precision", False, None, ""),
            ("confirmation_close", "double precision", False, None, ""),
            ("confirmed_at", "timestamp with time zone", False, None, ""),
            ("decision_at", "timestamp with time zone", False, None, ""),
            ("coverage_start_at", "timestamp with time zone", False, None, ""),
            ("coverage_end_at", "timestamp with time zone", False, None, ""),
            ("source_candle_ids", "jsonb", False, None, ""),
            ("source_content_hashes", "jsonb", False, None, ""),
            ("coverage_complete", "boolean", False, None, ""),
            ("structural_authority", "boolean", False, None, ""),
            ("material_proof_hash", "character varying", False, 71, ""),
            ("evidence_hash", "character varying", False, 71, ""),
            ("semantic_dedupe_key", "text", False, None, ""),
            ("rule_version", "character varying", False, 100, ""),
            ("evidence_payload", "jsonb", False, None, ""),
            ("execution_authority", "boolean", False, None, "false"),
            ("created_at", "timestamp with time zone", False, None, "now()"),
        ),
    ),
    **_columns(
        M15_PROOF_TABLE,
        (
            ("m15_proof_id", "text", False, None, ""),
            ("h1_proof_id", "text", False, None, ""),
            ("strategy_lifecycle_id", "text", False, None, ""),
            ("context_epoch_id", "text", False, None, ""),
            ("symbol", "character varying", False, 32, ""),
            ("strategy_direction", "character varying", False, 4, ""),
            ("reference_candle_id", "character varying", False, 71, ""),
            ("break_candle_id", "character varying", False, 71, ""),
            ("completion_candle_id", "character varying", False, 71, ""),
            ("break_level", "double precision", False, None, ""),
            ("h1_confirmed_at", "timestamp with time zone", False, None, ""),
            ("break_close_at", "timestamp with time zone", False, None, ""),
            ("completed_at", "timestamp with time zone", False, None, ""),
            ("completion_kind", "character varying", False, 24, ""),
            ("decision_at", "timestamp with time zone", False, None, ""),
            ("coverage_start_at", "timestamp with time zone", False, None, ""),
            ("coverage_end_at", "timestamp with time zone", False, None, ""),
            ("source_candle_ids", "jsonb", False, None, ""),
            ("source_content_hashes", "jsonb", False, None, ""),
            ("coverage_complete", "boolean", False, None, ""),
            ("structural_authority", "boolean", False, None, ""),
            ("ordering_valid", "boolean", False, None, ""),
            ("material_proof_hash", "character varying", False, 71, ""),
            ("evidence_hash", "character varying", False, 71, ""),
            ("semantic_dedupe_key", "text", False, None, ""),
            ("rule_version", "character varying", False, 100, ""),
            ("evidence_payload", "jsonb", False, None, ""),
            ("execution_authority", "boolean", False, None, "false"),
            ("created_at", "timestamp with time zone", False, None, "now()"),
        ),
    ),
    **_columns(
        THESIS_TABLE,
        (
            ("strategy_thesis_id", "text", False, None, ""),
            ("strategy_lifecycle_id", "text", False, None, ""),
            ("context_epoch_id", "text", False, None, ""),
            ("thesis_sequence", "integer", False, None, ""),
            ("symbol", "character varying", False, 32, ""),
            ("strategy_direction", "character varying", False, 4, ""),
            ("direction_immutable", "boolean", False, None, "true"),
            ("state", "character varying", False, 20, ""),
            ("direction_domain_at_creation", "character varying", False, 24, ""),
            ("selected_route", "character varying", False, 120, ""),
            ("route_authorization_hash", "character varying", True, 71, ""),
            ("pressure_authority_mode", "character varying", False, 40, ""),
            ("pressure_contract_status", "character varying", False, 24, ""),
            ("pressure_reference_direction", "character varying", True, 4, ""),
            ("pressure_formal_transition_event_id", "character varying", True, 240, ""),
            ("pressure_authority_hash", "character varying", False, 71, ""),
            ("counter_pressure_proof_hash", "character varying", True, 71, ""),
            ("h1_proof_id", "text", False, None, ""),
            ("m15_proof_id", "text", False, None, ""),
            ("structural_proof_hash", "character varying", False, 71, ""),
            ("semantic_identity_hash", "character varying", False, 71, ""),
            ("rule_version", "character varying", False, 100, ""),
            ("created_at", "timestamp with time zone", False, None, ""),
            ("liveness_checked_through", "timestamp with time zone", False, None, ""),
            ("closed_at", "timestamp with time zone", True, None, ""),
            ("closure_reason", "character varying", True, 160, ""),
            ("state_version", "bigint", False, None, ""),
            ("valid_for_execution", "boolean", False, None, "false"),
            ("execution_authority", "boolean", False, None, "false"),
            ("payload", "jsonb", False, None, ""),
            ("updated_at", "timestamp with time zone", False, None, "now()"),
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
            ("material_context_hash", "character varying", False, 71, ""),
            ("direction_domain", "character varying", False, 24, ""),
            ("allowed_routes", "jsonb", False, None, ""),
            ("blocked_routes", "jsonb", False, None, ""),
            ("evidence_hash", "character varying", False, 71, ""),
            ("evidence_payload", "jsonb", False, None, ""),
            ("execution_authority", "boolean", False, None, "false"),
        ),
    ),
}


@dataclass(frozen=True)
class _ConstraintContract:
    table: str
    contype: str
    fragments: tuple[str, ...]


def _constraint(table: str, contype: str, *fragments: str) -> _ConstraintContract:
    return _ConstraintContract(table, contype, tuple(_normalize_sql(item) for item in fragments))


_REQUIRED_CONSTRAINTS: dict[str, _ConstraintContract] = {
    "uq_5scr_context_epoch_scope_v1": _constraint(
        CONTEXT_TABLE, "u", "unique (context_epoch_id, strategy_lifecycle_id, symbol)"
    ),
    f"{H1_PROOF_TABLE}_pkey": _constraint(H1_PROOF_TABLE, "p", "primary key (h1_proof_id)"),
    "fk_5scr_h1_proof_lifecycle_v1": _constraint(
        H1_PROOF_TABLE,
        "f",
        "foreign key (strategy_lifecycle_id)",
        LIFECYCLE_TABLE,
        "on delete restrict",
    ),
    "fk_5scr_h1_proof_context_scope_v1": _constraint(
        H1_PROOF_TABLE,
        "f",
        "foreign key (context_epoch_id, strategy_lifecycle_id, symbol)",
        CONTEXT_TABLE,
        "on delete restrict",
    ),
    "uq_5scr_h1_proof_semantic_v1": _constraint(H1_PROOF_TABLE, "u", "unique (semantic_dedupe_key)"),
    "uq_5scr_h1_proof_scope_v1": _constraint(
        H1_PROOF_TABLE,
        "u",
        "unique (h1_proof_id, strategy_lifecycle_id, context_epoch_id, symbol, strategy_direction)",
    ),
    "ck_5scr_h1_proof_identity_v1": _constraint(
        H1_PROOF_TABLE, "c", "h1_proof_id", "5scr-h1-proof:", "material_proof_hash", "evidence_hash", "sha256:"
    ),
    "ck_5scr_h1_proof_direction_v1": _constraint(H1_PROOF_TABLE, "c", "strategy_direction", "buy", "sell"),
    "ck_5scr_h1_proof_event_v1": _constraint(H1_PROOF_TABLE, "c", "structure_event", "bos", "choch", "continuation"),
    "ck_5scr_h1_proof_structure_v1": _constraint(
        H1_PROOF_TABLE,
        "c",
        "anchor_candle_id",
        "confirmation_candle_id",
        "<>",
        "reference_level >",
        "confirmation_close >",
    ),
    "ck_5scr_h1_proof_order_v1": _constraint(
        H1_PROOF_TABLE,
        "c",
        "confirmed_at = coverage_end_at",
        "coverage_end_at <= decision_at",
        "coverage_start_at < confirmed_at",
    ),
    "ck_5scr_h1_proof_authority_v1": _constraint(
        H1_PROOF_TABLE, "c", "coverage_complete is true", "structural_authority is true"
    ),
    "ck_5scr_h1_proof_sources_v1": _constraint(
        H1_PROOF_TABLE,
        "c",
        "jsonb_typeof(source_candle_ids)",
        "jsonb_array_length(source_candle_ids) = 2",
        "jsonb_array_length(source_content_hashes) = 2",
    ),
    "ck_5scr_h1_proof_shadow_only_v1": _constraint(H1_PROOF_TABLE, "c", "execution_authority is false"),
    f"{M15_PROOF_TABLE}_pkey": _constraint(M15_PROOF_TABLE, "p", "primary key (m15_proof_id)"),
    "fk_5scr_m15_proof_lifecycle_v1": _constraint(
        M15_PROOF_TABLE, "f", "foreign key (strategy_lifecycle_id)", LIFECYCLE_TABLE, "on delete restrict"
    ),
    "fk_5scr_m15_proof_context_scope_v1": _constraint(
        M15_PROOF_TABLE,
        "f",
        "foreign key (context_epoch_id, strategy_lifecycle_id, symbol)",
        CONTEXT_TABLE,
        "on delete restrict",
    ),
    "fk_5scr_m15_proof_h1_scope_v1": _constraint(
        M15_PROOF_TABLE,
        "f",
        "foreign key (h1_proof_id, strategy_lifecycle_id, context_epoch_id, symbol, strategy_direction)",
        H1_PROOF_TABLE,
        "on delete restrict",
    ),
    "uq_5scr_m15_proof_semantic_v1": _constraint(M15_PROOF_TABLE, "u", "unique (semantic_dedupe_key)"),
    "uq_5scr_m15_proof_scope_v1": _constraint(
        M15_PROOF_TABLE,
        "u",
        "unique (m15_proof_id, strategy_lifecycle_id, context_epoch_id, symbol, strategy_direction)",
    ),
    "ck_5scr_m15_proof_identity_v1": _constraint(
        M15_PROOF_TABLE, "c", "m15_proof_id", "5scr-m15-proof:", "material_proof_hash", "evidence_hash", "sha256:"
    ),
    "ck_5scr_m15_proof_direction_v1": _constraint(M15_PROOF_TABLE, "c", "strategy_direction", "buy", "sell"),
    "ck_5scr_m15_proof_completion_v1": _constraint(
        M15_PROOF_TABLE, "c", "completion_kind", "acceptance", "failed_reclaim", "retest"
    ),
    "ck_5scr_m15_proof_order_v1": _constraint(
        M15_PROOF_TABLE,
        "c",
        "h1_confirmed_at <= break_close_at",
        "break_close_at < completed_at",
        "completed_at = coverage_end_at",
        "coverage_start_at < break_close_at",
        "coverage_end_at <= decision_at",
    ),
    "ck_5scr_m15_proof_structure_v1": _constraint(
        M15_PROOF_TABLE,
        "c",
        "reference_candle_id",
        "break_candle_id",
        "completion_candle_id",
        "<>",
        "break_level >",
    ),
    "ck_5scr_m15_proof_authority_v1": _constraint(
        M15_PROOF_TABLE, "c", "coverage_complete is true", "structural_authority is true", "ordering_valid is true"
    ),
    "ck_5scr_m15_proof_sources_v1": _constraint(
        M15_PROOF_TABLE,
        "c",
        "jsonb_array_length(source_candle_ids) = 3",
        "jsonb_array_length(source_content_hashes) = 3",
    ),
    "ck_5scr_m15_proof_shadow_only_v1": _constraint(M15_PROOF_TABLE, "c", "execution_authority is false"),
    f"{THESIS_TABLE}_pkey": _constraint(THESIS_TABLE, "p", "primary key (strategy_thesis_id)"),
    "fk_5scr_thesis_lifecycle_v1": _constraint(
        THESIS_TABLE, "f", "foreign key (strategy_lifecycle_id)", LIFECYCLE_TABLE, "on delete restrict"
    ),
    "fk_5scr_thesis_context_scope_v1": _constraint(
        THESIS_TABLE,
        "f",
        "foreign key (context_epoch_id, strategy_lifecycle_id, symbol)",
        CONTEXT_TABLE,
        "on delete restrict",
    ),
    "fk_5scr_thesis_h1_scope_v1": _constraint(
        THESIS_TABLE,
        "f",
        "foreign key (h1_proof_id, strategy_lifecycle_id, context_epoch_id, symbol, strategy_direction)",
        H1_PROOF_TABLE,
        "on delete restrict",
    ),
    "fk_5scr_thesis_m15_scope_v1": _constraint(
        THESIS_TABLE,
        "f",
        "foreign key (m15_proof_id, strategy_lifecycle_id, context_epoch_id, symbol, strategy_direction)",
        M15_PROOF_TABLE,
        "on delete restrict",
    ),
    "uq_5scr_thesis_sequence_v1": _constraint(THESIS_TABLE, "u", "unique (strategy_lifecycle_id, thesis_sequence)"),
    "uq_5scr_thesis_semantic_identity_v1": _constraint(THESIS_TABLE, "u", "unique (semantic_identity_hash)"),
    "ck_5scr_thesis_identity_v1": _constraint(
        THESIS_TABLE,
        "c",
        "strategy_thesis_id",
        "structural_proof_hash",
        "semantic_identity_hash",
        "pressure_authority_hash",
        "sha256:",
    ),
    "ck_5scr_thesis_direction_v1": _constraint(THESIS_TABLE, "c", "strategy_direction", "buy", "sell"),
    "ck_5scr_thesis_domain_v1": _constraint(
        THESIS_TABLE,
        "c",
        "direction_domain_at_creation",
        "buy_only",
        "sell_only",
        "both_conditional",
        "unresolved",
        "empty",
    ),
    "ck_5scr_thesis_domain_direction_v1": _constraint(
        THESIS_TABLE,
        "c",
        "buy_only",
        "strategy_direction",
        "sell_only",
        "both_conditional",
        "route_authorization_hash is not null",
    ),
    "ck_5scr_thesis_pressure_enum_v1": _constraint(
        THESIS_TABLE,
        "c",
        "pressure_authority_mode",
        "radar_only",
        "consolidated_direction_contract",
        "pressure_contract_status",
        "locked",
    ),
    "ck_5scr_thesis_pressure_authority_v1": _constraint(
        THESIS_TABLE,
        "c",
        "radar_only",
        "pressure_formal_transition_event_id",
        "is null",
        "consolidated_direction_contract",
        "locked",
        "pressure_reference_direction",
        "strategy_direction",
        "is not null",
        "counter_pressure_proof_hash is null",
    ),
    "ck_5scr_thesis_pressure_direction_v1": _constraint(
        THESIS_TABLE, "c", "pressure_reference_direction is null", "buy", "sell"
    ),
    "ck_5scr_thesis_route_hash_v1": _constraint(THESIS_TABLE, "c", "route_authorization_hash is null", "sha256:"),
    "ck_5scr_thesis_counter_pressure_hash_v1": _constraint(
        THESIS_TABLE, "c", "counter_pressure_proof_hash is null", "sha256:"
    ),
    "ck_5scr_thesis_state_v1": _constraint(
        THESIS_TABLE, "c", "state", "active", "invalidated", "terminal", "state_version >= 1"
    ),
    "ck_5scr_thesis_temporal_v1": _constraint(
        THESIS_TABLE,
        "c",
        "state",
        "active",
        "closed_at is null",
        "liveness_checked_through >= created_at",
        "invalidated",
        "terminal",
        "closed_at >= liveness_checked_through",
        "closure_reason is not null",
    ),
    "ck_5scr_thesis_shadow_only_v1": _constraint(
        THESIS_TABLE, "c", "direction_immutable is true", "valid_for_execution is false", "execution_authority is false"
    ),
}

# Exact PostgreSQL-16 ``pg_get_constraintdef`` fingerprints captured from the
# migration's own DDL.  Names, types, or selected fragments are not enough:
# a same-named ``CHECK (... OR TRUE)`` must fail readiness.
_REQUIRED_CONSTRAINT_DEFINITION_HASHES = {
    "ck_5scr_h1_proof_authority_v1": "41c172a46ea906e01d2197546a50507cf76418a2bf1ff47814531eb16bc54f9e",
    "ck_5scr_h1_proof_direction_v1": "ef580a440fc80882fc679015428f630644be900cbe52633db97a0b66d61ed5a3",
    "ck_5scr_h1_proof_event_v1": "edb742e1e1f87198f011f4ec8f99f7cca7d6d7b80dc0cbfd137a1c88a5224b92",
    "ck_5scr_h1_proof_identity_v1": "6a9c40f7ff084aca62b09e188577629927d3621bb61831125104c9eb1592a27e",
    "ck_5scr_h1_proof_order_v1": "6a8e59291af84b603cc1569a84bbf563dccf52272cf4401afe1f5e25b7c99ad3",
    "ck_5scr_h1_proof_shadow_only_v1": "241ba579eb592c0fafb96ddb69ae9ef328390d3465b1b535b70e6977d20438a4",
    "ck_5scr_h1_proof_sources_v1": "7fde116f628aae69619e0850d0f3832a41333f86f9982af1fde259a645b4eec2",
    "ck_5scr_h1_proof_structure_v1": "e171d2230ac7ca925730ef40ad531f106a840f0511810cabc7cbc4cdd3fae2d2",
    "ck_5scr_m15_proof_authority_v1": "61285b1658a3c7da4d75c583f5234cfe89683d38f1189681e9bf7aa2417983d4",
    "ck_5scr_m15_proof_completion_v1": "e64e39e2fe79a2f0ca574c95567ea4cad5741d50f51258826286b2754adad83c",
    "ck_5scr_m15_proof_direction_v1": "ef580a440fc80882fc679015428f630644be900cbe52633db97a0b66d61ed5a3",
    "ck_5scr_m15_proof_identity_v1": "1beec69565c967982a9f0a161cf272b0502f3a42663034cf4bac81238de8ce86",
    "ck_5scr_m15_proof_order_v1": "8c11582c5b9c5b254b266f42cec620fdd472bc8e9f28c09937dfb736314c8731",
    "ck_5scr_m15_proof_shadow_only_v1": "241ba579eb592c0fafb96ddb69ae9ef328390d3465b1b535b70e6977d20438a4",
    "ck_5scr_m15_proof_sources_v1": "107e1ce85041eaf56054dab605089e1c7d81d9b840835feb863a789dc275f604",
    "ck_5scr_m15_proof_structure_v1": "49e5e1a24fc27024239155baf4bf0639d5d1785d709ce70c408e64ca09c7dd32",
    "ck_5scr_thesis_direction_v1": "ef580a440fc80882fc679015428f630644be900cbe52633db97a0b66d61ed5a3",
    "ck_5scr_thesis_domain_direction_v1": "74b44eef46970fa9ec64ef06090a1f2d45fe6da9b1323637823e450c7b4c56b1",
    "ck_5scr_thesis_domain_v1": "ad74cf9bfb0fd477225698c9d5c3670000a4e250e98b599df35ed73ee45816c4",
    "ck_5scr_thesis_identity_v1": "146337e17170aaf3aecc261426a28c6d136e75a74cc86136f46ee2875d844aba",
    "ck_5scr_thesis_pressure_authority_v1": "598253d13c6e5033aa01b2c97d08c9e26f56b1b6ccbeab7867f76c98efe89961",
    "ck_5scr_thesis_pressure_direction_v1": "690ccd6db9066a544e9671e1c89cd5e2ec0004cb18e9071f9bd89c901d25ef5b",
    "ck_5scr_thesis_pressure_enum_v1": "5b853cd4e5f144fbc93db0ab3a07cf6316ae619275bcbb5df016640bf71c87df",
    "ck_5scr_thesis_route_hash_v1": "86f6714bdf170310ab1fbba0c75ef94633ebb7f1ce61a654067eb81837a5ca73",
    "ck_5scr_thesis_counter_pressure_hash_v1": "9854ca8b4e41f04e9f7c7871748b1e545d94f949c951554f599c4e3bd2134378",
    "ck_5scr_thesis_shadow_only_v1": "4d8f493cdf507cdfb69b4d11681dcdc93352247840c59c6ca67d07dd61395d44",
    "ck_5scr_thesis_state_v1": "5ba1f16102bc6df2682ebf7828db275fa48e3ed31f75ee9b69269157d1c1e5ac",
    "ck_5scr_thesis_temporal_v1": "77ad31ea9aca2ce83e20cf2ab771c708ff8fa2be3c215202c9b015470560037e",
    "fk_5scr_h1_proof_context_scope_v1": "cd752ec8c65105e4c15ec426a83fc643f87966388e23c460667edf60935a6c66",
    "fk_5scr_h1_proof_lifecycle_v1": "31c316748300dbd4469cf8ccd91828fcdca520c4f93363bbcbb2f8a9411a7d32",
    "fk_5scr_m15_proof_context_scope_v1": "cd752ec8c65105e4c15ec426a83fc643f87966388e23c460667edf60935a6c66",
    "fk_5scr_m15_proof_h1_scope_v1": "3e5540dc573f83ef5473c82ddf43e4406c09b94ae4be3b87641e2a753578e7aa",
    "fk_5scr_m15_proof_lifecycle_v1": "31c316748300dbd4469cf8ccd91828fcdca520c4f93363bbcbb2f8a9411a7d32",
    "fk_5scr_thesis_context_scope_v1": "cd752ec8c65105e4c15ec426a83fc643f87966388e23c460667edf60935a6c66",
    "fk_5scr_thesis_h1_scope_v1": "3e5540dc573f83ef5473c82ddf43e4406c09b94ae4be3b87641e2a753578e7aa",
    "fk_5scr_thesis_lifecycle_v1": "31c316748300dbd4469cf8ccd91828fcdca520c4f93363bbcbb2f8a9411a7d32",
    "fk_5scr_thesis_m15_scope_v1": "4547a12535c0b12bd0e10c7c6d426a4bff0095121feb6611007274fa8c8df8bf",
    "strategy_5scr_directional_theses_v1_pkey": "f09f3a34f1bd0ad12bcd17340852bc458684b8a5845685247d7cd68f45bd5d76",
    "strategy_5scr_h1_structure_proofs_v1_pkey": "66cc0248f1bc625bab4b428d7a118337402b547d4b3c18602c893b22efdc1940",
    "strategy_5scr_m15_structural_proofs_v1_pkey": "d08c6819bb772cc974f3e2ca4ac70e9cfdfc812dfb5bfea85e041ccee0685544",
    "uq_5scr_context_epoch_scope_v1": "fbafdfbe9eb8307bf9997f54d2109e55a3af46ff016a774fdbbf2096de482b59",
    "uq_5scr_h1_proof_scope_v1": "b5f725b1088d870c6041316d3e2a60d16e991ecac7bed9cca1868755524a3d41",
    "uq_5scr_h1_proof_semantic_v1": "f3719d5de776b48d0a70df01debbac5b2ccbf0c8a11adddc7fcc104b6f2bb865",
    "uq_5scr_m15_proof_scope_v1": "087249552887224eaac69e54ccb0755bcefeed1d95eec7ec1676e89b7f62eb58",
    "uq_5scr_m15_proof_semantic_v1": "f3719d5de776b48d0a70df01debbac5b2ccbf0c8a11adddc7fcc104b6f2bb865",
    "uq_5scr_thesis_semantic_identity_v1": "da727f20d1ffb03f698e6f057b2f73af513378b5d7065b88489449fc0af49bbe",
    "uq_5scr_thesis_sequence_v1": "302fd8a492ee3480e9f248696893f078a1b5ee775888e306dd6dbee359fb2f03",
}


@dataclass(frozen=True)
class _IndexContract:
    table: str
    unique: bool
    columns: tuple[str, ...]
    predicate: str = ""


_REQUIRED_INDEXES = {
    "ix_canonical_candles_closed_asof": _IndexContract(
        CANONICAL_CANDLE_TABLE, False, ("symbol", "timeframe", "close_time"), "complete"
    ),
    "ix_5scr_h1_proof_context_time_v1": _IndexContract(
        H1_PROOF_TABLE, False, ("context_epoch_id", "confirmed_at", "h1_proof_id")
    ),
    "ix_5scr_m15_proof_context_time_v1": _IndexContract(
        M15_PROOF_TABLE, False, ("context_epoch_id", "completed_at", "m15_proof_id")
    ),
    "uq_5scr_thesis_active_lifecycle_v1": _IndexContract(
        THESIS_TABLE, True, ("strategy_lifecycle_id",), "((state)::text = 'ACTIVE'::text)"
    ),
    "ix_5scr_thesis_context_history_v1": _IndexContract(
        THESIS_TABLE, False, ("context_epoch_id", "thesis_sequence", "strategy_thesis_id")
    ),
}

_REQUIRED_INDEX_DEFINITION_HASHES = {
    "ix_5scr_h1_proof_context_time_v1": "34bebfeae4bcd024015797960590a7bb3f1f7eca61ce9be158619a806f27cb55",
    "ix_5scr_m15_proof_context_time_v1": "5926ddd0ef1e83da3490a76bbace2cf7faf16527e422ce4e71da69ca889ff025",
    "ix_5scr_thesis_context_history_v1": "5076e8e4a20cabd286e708ede83843a1a0b91470acf1a185e803fc07c5d6dbc7",
    "ix_canonical_candles_closed_asof": "7cdfcd915696824a0635c7c41d38dab8ea03ac179c503121e41819c998dd3b84",
    "uq_5scr_thesis_active_lifecycle_v1": "bdebb9ee9e727eaf17b3b832b92fbac6fb8e6cab32c5fe20222c74345ab5d3bb",
}


@dataclass(frozen=True)
class _TriggerContract:
    table: str
    function: str
    trigger_fragments: tuple[str, ...]
    function_fragments: tuple[str, ...]


_REQUIRED_TRIGGERS = {
    f"trg_{H1_PROOF_TABLE}_immutable": _TriggerContract(
        H1_PROOF_TABLE,
        "strategy_5scr_reject_proof_mutation_v1",
        ("before", "update", "delete", H1_PROOF_TABLE),
        ("raise exception", "strategy_5scr_proof_immutable", "23514", "ck_5scr_proof_immutable_v1"),
    ),
    f"trg_{M15_PROOF_TABLE}_immutable": _TriggerContract(
        M15_PROOF_TABLE,
        "strategy_5scr_reject_proof_mutation_v1",
        ("before", "update", "delete", M15_PROOF_TABLE),
        ("raise exception", "strategy_5scr_proof_immutable", "23514", "ck_5scr_proof_immutable_v1"),
    ),
    f"trg_{THESIS_TABLE}_guard": _TriggerContract(
        THESIS_TABLE,
        "strategy_5scr_guard_thesis_update_v1",
        ("before", "update", "delete", THESIS_TABLE),
        (
            "strategy_5scr_thesis_delete_forbidden",
            "strategy_5scr_thesis_identity_immutable",
            "strategy_5scr_thesis_state_transition_invalid",
            "strategy_5scr_thesis_liveness_transition_invalid",
            "old.state <> 'active'",
            "new.state_version <> old.state_version + 1",
        ),
    ),
}

_REQUIRED_TRIGGER_DEFINITION_HASHES = {
    "trg_strategy_5scr_directional_theses_v1_guard": (
        "ffad54ce02e33c29dc64b7444f0302ef2168aa3b032562294cee70387cdde10a",
        "f56a1d9a0061d937e5a90acf0c2db66307ecb5e4245ec8f8399548a956afa284",
    ),
    "trg_strategy_5scr_h1_structure_proofs_v1_immutable": (
        "bdaf117ffd2b74ea91f7553d16f1e1254f29a1bae589d68f78434ae44a591cf1",
        "4c671ced56042b8c3356bca9e34a18ebdf63811be1a68908b207f9927e700804",
    ),
    "trg_strategy_5scr_m15_structural_proofs_v1_immutable": (
        "e09fc0fe4930b51e5b447c2369b913deb495fe9884bd0df5607a3a7a286639bb",
        "4c671ced56042b8c3356bca9e34a18ebdf63811be1a68908b207f9927e700804",
    ),
}

if set(_REQUIRED_CONSTRAINT_DEFINITION_HASHES) != set(_REQUIRED_CONSTRAINTS):
    raise RuntimeError("P4_CONSTRAINT_FINGERPRINT_CATALOG_INCOMPLETE")
if set(_REQUIRED_INDEX_DEFINITION_HASHES) != set(_REQUIRED_INDEXES):
    raise RuntimeError("P4_INDEX_FINGERPRINT_CATALOG_INCOMPLETE")
if set(_REQUIRED_TRIGGER_DEFINITION_HASHES) != set(_REQUIRED_TRIGGERS):
    raise RuntimeError("P4_TRIGGER_FINGERPRINT_CATALOG_INCOMPLETE")


def _enabled(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() == "true"


@dataclass(frozen=True)
class DirectionalThesisV1RuntimeConfig:
    enabled: bool = False
    shadow_only: bool = True

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> DirectionalThesisV1RuntimeConfig:
        source = os.environ if environ is None else environ
        return cls(
            enabled=_enabled(source.get(DIRECTIONAL_THESIS_V1_WRITER_FLAG), default=False),
            shadow_only=_enabled(source.get(DIRECTIONAL_THESIS_V1_SHADOW_ONLY_FLAG), default=True),
        )

    def validate(self) -> None:
        if self.enabled and not self.shadow_only:
            raise RuntimeError("STRATEGY_5SCR_DIRECTIONAL_THESIS_V1_SHADOW_ONLY_REQUIRED")


@dataclass(frozen=True)
class DirectionalThesisV1SchemaStatus:
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


DirectionalThesisPersistStatus = Literal[
    "PERSISTED",
    "DUPLICATE",
    "WAIT",
    "REJECTED",
    "QUARANTINED",
    "INVALIDATED",
    "TERMINATED",
    "NO_CHANGE",
]


@dataclass(frozen=True)
class DirectionalThesisPersistResult:
    status: DirectionalThesisPersistStatus
    reason_code: str | None = None
    strategy_lifecycle_id: str | None = None
    context_epoch_id: str | None = None
    h1_proof_id: str | None = None
    m15_proof_id: str | None = None
    thesis: DirectionalThesisV1 | None = None


class DirectionalThesisV1PersistenceError(RuntimeError):
    """Base error for atomic durable P4 persistence."""


class DirectionalThesisV1IntegrityError(DirectionalThesisV1PersistenceError):
    """Raised when durable proof/thesis identity disagrees with recomputation."""


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _catalog_char(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value or "")


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _json_tuple(value: Any) -> tuple[str, ...]:
    parsed = _json_value(value)
    if not isinstance(parsed, Sequence) or isinstance(parsed, (str, bytes, bytearray)):
        raise DirectionalThesisV1IntegrityError("P4_JSON_ARRAY_INVALID")
    return tuple(str(item) for item in parsed)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


def _context_from_row(row: Any) -> StrategyContextEpochV1:
    evidence = MaterialContextEvidenceV1.model_validate(_json_value(_row_value(row, "evidence_payload")))
    durable_evidence_hash = str(_row_value(row, "evidence_hash"))
    if context_evidence_hash(evidence) != durable_evidence_hash:
        raise DirectionalThesisV1IntegrityError("CONTEXT_EPOCH_EVIDENCE_HASH_DRIFT")
    epoch = StrategyContextEpochV1(
        context_epoch_id=str(_row_value(row, "context_epoch_id")),
        strategy_lifecycle_id=str(_row_value(row, "strategy_lifecycle_id")),
        symbol=str(_row_value(row, "symbol")),
        epoch_sequence=int(_row_value(row, "epoch_sequence")),
        state=cast(Any, str(_row_value(row, "state"))),
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
        direction_domain=cast(Any, str(_row_value(row, "direction_domain"))),
        allowed_routes=_json_tuple(_row_value(row, "allowed_routes")),
        blocked_routes=_json_tuple(_row_value(row, "blocked_routes")),
        target_map_version=_row_value(row, "target_map_version"),
        structural_invalidation_version=_row_value(row, "structural_invalidation_version"),
        transition_reason=cast(Any, str(_row_value(row, "transition_reason"))),
        evidence_hash=durable_evidence_hash,
        last_observed_at_utc=_row_value(row, "last_observed_at"),
        last_source_event_id=str(_row_value(row, "last_source_event_id")),
        state_version=int(_row_value(row, "state_version")),
        execution_authority=cast(Any, bool(_row_value(row, "execution_authority"))),
    )
    if epoch.state != "TERMINAL" and material_context_hash(evidence) != epoch.material_context_hash:
        raise DirectionalThesisV1IntegrityError("CONTEXT_EPOCH_MATERIAL_HASH_DRIFT")
    return epoch


def _proof_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _verify_candle(candle: ClosedCandleAuthorityRefV1, *, proof_kind: str) -> None:
    if candle.material_candle_hash != candle_material_hash(candle):
        raise DirectionalThesisV1IntegrityError(f"{proof_kind}_PROOF_CANDLE_MATERIAL_HASH_DRIFT")
    if candle.candle_evidence_id != candle_evidence_hash(candle):
        raise DirectionalThesisV1IntegrityError(f"{proof_kind}_PROOF_CANDLE_EVIDENCE_ID_DRIFT")


def _durable_value_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, datetime):
        return isinstance(actual, datetime) and _utc(actual, "durable_timestamp") == expected
    if isinstance(expected, tuple):
        return _json_tuple(actual) == expected
    return actual == expected


def _verify_durable_columns(row: Any, expected: Mapping[str, Any], *, proof_kind: str) -> None:
    for column, value in expected.items():
        if not _durable_value_matches(_row_value(row, column), value):
            raise DirectionalThesisV1IntegrityError(f"{proof_kind}_PROOF_PAYLOAD_DRIFT:{column}")


def _h1_from_row(row: Any) -> H1StructureProofV1:
    payload = _json_value(_row_value(row, "evidence_payload"))
    if not isinstance(payload, Mapping):
        raise DirectionalThesisV1IntegrityError("H1_PROOF_PAYLOAD_INVALID")
    try:
        proof = H1StructureProofV1.model_validate(payload)
    except ValidationError as exc:
        raise DirectionalThesisV1IntegrityError("H1_PROOF_PAYLOAD_INVALID") from exc
    _verify_candle(proof.anchor_candle, proof_kind="H1")
    _verify_candle(proof.confirmation_candle, proof_kind="H1")
    material_hash = _proof_hash(
        {
            "context_epoch_id": proof.context_epoch_id,
            "strategy_direction": proof.strategy_direction,
            "anchor_material_hash": proof.anchor_candle.material_candle_hash,
            "confirmation_material_hash": proof.confirmation_candle.material_candle_hash,
            "reference_level": proof.reference_level,
            "structure_event": proof.structure_event,
            "rule_version": proof.rule_version,
        }
    )
    evidence_hash = _proof_hash(
        {
            "context_epoch_id": proof.context_epoch_id,
            "strategy_direction": proof.strategy_direction,
            "anchor_material_hash": proof.anchor_candle.material_candle_hash,
            "confirmation_material_hash": proof.confirmation_candle.material_candle_hash,
            "reference_level": proof.reference_level,
            "structure_event": proof.structure_event,
            "rule_version": proof.rule_version,
            "anchor": proof.anchor_candle.model_dump(mode="json"),
            "confirmation": proof.confirmation_candle.model_dump(mode="json"),
            "decision_at_utc": proof.decision_at_utc,
        }
    )
    expected_id = "5scr-h1-proof:" + material_hash.removeprefix("sha256:")[:32]
    expected_dedupe = f"{proof.context_epoch_id}|{proof.strategy_direction}|H1|{material_hash}"
    if proof.material_proof_hash != material_hash:
        raise DirectionalThesisV1IntegrityError("H1_PROOF_MATERIAL_HASH_DRIFT")
    if proof.evidence_hash != evidence_hash:
        raise DirectionalThesisV1IntegrityError("H1_PROOF_EVIDENCE_HASH_DRIFT")
    if proof.h1_proof_id != expected_id or proof.semantic_dedupe_key != expected_dedupe:
        raise DirectionalThesisV1IntegrityError("H1_PROOF_IDENTITY_DRIFT")
    if proof.confirmation_close != proof.confirmation_candle.close:
        raise DirectionalThesisV1IntegrityError("H1_PROOF_CONFIRMATION_CLOSE_DRIFT")
    _verify_durable_columns(
        row,
        {
            "h1_proof_id": proof.h1_proof_id,
            "strategy_lifecycle_id": proof.strategy_lifecycle_id,
            "context_epoch_id": proof.context_epoch_id,
            "symbol": proof.symbol,
            "strategy_direction": proof.strategy_direction,
            "structure_event": proof.structure_event,
            "anchor_candle_id": proof.anchor_candle.candle_evidence_id,
            "confirmation_candle_id": proof.confirmation_candle.candle_evidence_id,
            "reference_level": proof.reference_level,
            "confirmation_close": proof.confirmation_close,
            "confirmed_at": proof.confirmed_at_utc,
            "decision_at": proof.decision_at_utc,
            "coverage_start_at": proof.coverage_start_at_utc,
            "coverage_end_at": proof.coverage_end_at_utc,
            "source_candle_ids": proof.source_candle_ids,
            "source_content_hashes": proof.source_content_hashes,
            "coverage_complete": proof.coverage_complete,
            "structural_authority": proof.structural_authority,
            "material_proof_hash": proof.material_proof_hash,
            "evidence_hash": proof.evidence_hash,
            "semantic_dedupe_key": proof.semantic_dedupe_key,
            "rule_version": proof.rule_version,
            "execution_authority": proof.execution_authority,
        },
        proof_kind="H1",
    )
    return proof


def _m15_from_row(row: Any) -> M15StructuralProofV1:
    payload = _json_value(_row_value(row, "evidence_payload"))
    if not isinstance(payload, Mapping):
        raise DirectionalThesisV1IntegrityError("M15_PROOF_PAYLOAD_INVALID")
    try:
        proof = M15StructuralProofV1.model_validate(payload)
    except ValidationError as exc:
        raise DirectionalThesisV1IntegrityError("M15_PROOF_PAYLOAD_INVALID") from exc
    for candle in (proof.reference_candle, proof.break_candle, proof.completion_candle):
        _verify_candle(candle, proof_kind="M15")
    material_hash = _proof_hash(
        {
            "context_epoch_id": proof.context_epoch_id,
            "h1_proof_id": proof.h1_proof_id,
            "strategy_direction": proof.strategy_direction,
            "reference_material_hash": proof.reference_candle.material_candle_hash,
            "break_material_hash": proof.break_candle.material_candle_hash,
            "completion_material_hash": proof.completion_candle.material_candle_hash,
            "break_level": proof.break_level,
            "completion_kind": proof.completion_kind,
            "rule_version": proof.rule_version,
        }
    )
    evidence_hash = _proof_hash(
        {
            "context_epoch_id": proof.context_epoch_id,
            "h1_proof_id": proof.h1_proof_id,
            "strategy_direction": proof.strategy_direction,
            "reference_material_hash": proof.reference_candle.material_candle_hash,
            "break_material_hash": proof.break_candle.material_candle_hash,
            "completion_material_hash": proof.completion_candle.material_candle_hash,
            "break_level": proof.break_level,
            "completion_kind": proof.completion_kind,
            "rule_version": proof.rule_version,
            "reference": proof.reference_candle.model_dump(mode="json"),
            "break": proof.break_candle.model_dump(mode="json"),
            "completion": proof.completion_candle.model_dump(mode="json"),
            "decision_at_utc": proof.decision_at_utc,
        }
    )
    expected_id = "5scr-m15-proof:" + material_hash.removeprefix("sha256:")[:32]
    expected_dedupe = f"{proof.context_epoch_id}|{proof.strategy_direction}|M15|{material_hash}"
    if proof.material_proof_hash != material_hash:
        raise DirectionalThesisV1IntegrityError("M15_PROOF_MATERIAL_HASH_DRIFT")
    if proof.evidence_hash != evidence_hash:
        raise DirectionalThesisV1IntegrityError("M15_PROOF_EVIDENCE_HASH_DRIFT")
    if proof.m15_proof_id != expected_id or proof.semantic_dedupe_key != expected_dedupe:
        raise DirectionalThesisV1IntegrityError("M15_PROOF_IDENTITY_DRIFT")
    _verify_durable_columns(
        row,
        {
            "m15_proof_id": proof.m15_proof_id,
            "h1_proof_id": proof.h1_proof_id,
            "strategy_lifecycle_id": proof.strategy_lifecycle_id,
            "context_epoch_id": proof.context_epoch_id,
            "symbol": proof.symbol,
            "strategy_direction": proof.strategy_direction,
            "reference_candle_id": proof.reference_candle.candle_evidence_id,
            "break_candle_id": proof.break_candle.candle_evidence_id,
            "completion_candle_id": proof.completion_candle.candle_evidence_id,
            "break_level": proof.break_level,
            "h1_confirmed_at": proof.h1_confirmed_at_utc,
            "break_close_at": proof.break_close_at_utc,
            "completed_at": proof.completed_at_utc,
            "completion_kind": proof.completion_kind,
            "decision_at": proof.decision_at_utc,
            "coverage_start_at": proof.coverage_start_at_utc,
            "coverage_end_at": proof.coverage_end_at_utc,
            "source_candle_ids": proof.source_candle_ids,
            "source_content_hashes": proof.source_content_hashes,
            "coverage_complete": proof.coverage_complete,
            "structural_authority": proof.structural_authority,
            "ordering_valid": proof.ordering_valid,
            "material_proof_hash": proof.material_proof_hash,
            "evidence_hash": proof.evidence_hash,
            "semantic_dedupe_key": proof.semantic_dedupe_key,
            "rule_version": proof.rule_version,
            "execution_authority": proof.execution_authority,
        },
        proof_kind="M15",
    )
    return proof


def _thesis_from_row(row: Any) -> DirectionalThesisV1:
    payload = _json_value(_row_value(row, "payload"))
    if not isinstance(payload, Mapping):
        raise DirectionalThesisV1IntegrityError("DIRECTIONAL_THESIS_PAYLOAD_INVALID")
    try:
        thesis = DirectionalThesisV1.model_validate(payload)
    except ValidationError as exc:
        raise DirectionalThesisV1IntegrityError("DIRECTIONAL_THESIS_PAYLOAD_INVALID") from exc
    immutable = {
        "strategy_thesis_id": thesis.strategy_thesis_id,
        "strategy_lifecycle_id": thesis.strategy_lifecycle_id,
        "context_epoch_id": thesis.context_epoch_id,
        "thesis_sequence": thesis.thesis_sequence,
        "symbol": thesis.symbol,
        "strategy_direction": thesis.strategy_direction,
        "direction_immutable": thesis.direction_immutable,
        "direction_domain_at_creation": thesis.direction_domain_at_creation,
        "selected_route": thesis.selected_route,
        "route_authorization_hash": thesis.route_authorization_hash,
        "pressure_authority_mode": thesis.pressure_authority_mode,
        "pressure_contract_status": thesis.pressure_contract_status,
        "pressure_reference_direction": thesis.pressure_reference_direction,
        "pressure_formal_transition_event_id": thesis.pressure_formal_transition_event_id,
        "pressure_authority_hash": thesis.pressure_authority_hash,
        "counter_pressure_proof_hash": thesis.counter_pressure_proof_hash,
        "h1_proof_id": thesis.h1_proof_id,
        "m15_proof_id": thesis.m15_proof_id,
        "structural_proof_hash": thesis.structural_proof_hash,
        "semantic_identity_hash": thesis.semantic_identity_hash,
        "rule_version": thesis.rule_version,
        "created_at": thesis.created_at_utc,
        "valid_for_execution": thesis.valid_for_execution,
        "execution_authority": thesis.execution_authority,
    }
    for column, expected in immutable.items():
        actual = _row_value(row, column)
        if str(actual) != str(expected):
            raise DirectionalThesisV1IntegrityError(f"DIRECTIONAL_THESIS_PAYLOAD_DRIFT:{column}")
    mutable = {
        "state": thesis.state,
        "liveness_checked_through": thesis.liveness_checked_through_utc,
        "closed_at": thesis.closed_at_utc,
        "closure_reason": thesis.closure_reason,
        "state_version": thesis.state_version,
    }
    for column, expected in mutable.items():
        actual = _row_value(row, column)
        if str(actual) != str(expected):
            raise DirectionalThesisV1IntegrityError(f"DIRECTIONAL_THESIS_PAYLOAD_DRIFT:{column}")
    return DirectionalThesisV1.model_validate(
        {
            **dict(payload),
            "state": str(_row_value(row, "state")),
            "liveness_checked_through_utc": _row_value(row, "liveness_checked_through"),
            "closed_at_utc": _row_value(row, "closed_at"),
            "closure_reason": _row_value(row, "closure_reason"),
            "state_version": int(_row_value(row, "state_version")),
        }
    )


def _thesis_id(semantic_identity_hash: str) -> str:
    return "5scr-thesis:" + semantic_identity_hash.removeprefix("sha256:")[:32]


class Strategy5SCRDirectionalThesisV1Repository:
    """Persist immutable proofs and one active shadow-only thesis per lifecycle."""

    def __init__(self, postgres: PostgresClient = pg_client) -> None:
        self._pg = postgres

    async def schema_status(self) -> DirectionalThesisV1SchemaStatus:
        expected_columns = tuple(sorted(f"{table}.{column}" for table, column in _REQUIRED_COLUMNS))
        if not self._pg.is_available:
            return DirectionalThesisV1SchemaStatus(
                missing_tables=tuple(sorted(_REQUIRED_TABLES)),
                missing_columns=expected_columns,
                invalid_columns=(),
                missing_constraints=tuple(sorted(_REQUIRED_CONSTRAINTS)),
                invalid_constraints=(),
                missing_indexes=tuple(sorted(_REQUIRED_INDEXES)),
                invalid_indexes=(),
                missing_triggers=tuple(sorted(_REQUIRED_TRIGGERS)),
                invalid_triggers=(),
            )
        table_rows = await self._pg.fetch(
            "SELECT tablename FROM pg_catalog.pg_tables "
            "WHERE schemaname = current_schema() AND tablename = ANY($1::text[])",
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
                   pg_get_indexdef(idx.indexrelid) AS definition,
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
        trigger_rows = await self._pg.fetch(
            """
            SELECT trg.tgname, table_cls.relname AS table_name, trg.tgenabled,
                   pg_get_triggerdef(trg.oid) AS trigger_definition,
                   proc.proname AS function_name, pg_get_functiondef(proc.oid) AS function_definition
            FROM pg_catalog.pg_trigger trg
            JOIN pg_catalog.pg_class table_cls ON table_cls.oid = trg.tgrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = table_cls.relnamespace
            JOIN pg_catalog.pg_proc proc ON proc.oid = trg.tgfoid
            WHERE ns.nspname = current_schema() AND NOT trg.tgisinternal
              AND trg.tgname = ANY($1::text[])
            """,
            sorted(_REQUIRED_TRIGGERS),
        )

        present_tables = {str(_row_value(row, "tablename")) for row in table_rows}
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

        constraints = {str(_row_value(row, "conname")): row for row in constraint_rows}
        invalid_constraints: list[str] = []
        for name, expected in _REQUIRED_CONSTRAINTS.items():
            row = constraints.get(name)
            if row is None:
                continue
            if str(_row_value(row, "table_name")) != expected.table:
                invalid_constraints.append(f"{name}:table")
            elif str(_row_value(row, "contype")) != expected.contype:
                invalid_constraints.append(f"{name}:type")
            elif not bool(_row_value(row, "convalidated")):
                invalid_constraints.append(f"{name}:not_validated")
            elif _sql_fingerprint(_row_value(row, "definition")) != _REQUIRED_CONSTRAINT_DEFINITION_HASHES[name]:
                invalid_constraints.append(f"{name}:definition")

        indexes = {str(_row_value(row, "index_name")): row for row in index_rows}
        invalid_indexes: list[str] = []
        for name, expected in _REQUIRED_INDEXES.items():
            row = indexes.get(name)
            if row is None:
                continue
            actual_columns = tuple(str(item) for item in (_row_value(row, "columns") or ()))
            if str(_row_value(row, "table_name")) != expected.table:
                invalid_indexes.append(f"{name}:table")
            elif bool(_row_value(row, "indisunique")) != expected.unique:
                invalid_indexes.append(f"{name}:unique")
            elif not bool(_row_value(row, "indisvalid")):
                invalid_indexes.append(f"{name}:not_valid")
            elif not bool(_row_value(row, "indisready")):
                invalid_indexes.append(f"{name}:not_ready")
            elif actual_columns != expected.columns:
                invalid_indexes.append(f"{name}:columns")
            elif _sql_fingerprint(_row_value(row, "definition")) != _REQUIRED_INDEX_DEFINITION_HASHES[name]:
                invalid_indexes.append(f"{name}:definition")

        triggers = {str(_row_value(row, "tgname")): row for row in trigger_rows}
        invalid_triggers: list[str] = []
        for name, expected in _REQUIRED_TRIGGERS.items():
            row = triggers.get(name)
            if row is None:
                continue
            trigger_hash, function_hash = _REQUIRED_TRIGGER_DEFINITION_HASHES[name]
            if str(_row_value(row, "table_name")) != expected.table:
                invalid_triggers.append(f"{name}:table")
            elif _catalog_char(_row_value(row, "tgenabled")) != "O":
                invalid_triggers.append(f"{name}:disabled")
            elif str(_row_value(row, "function_name")) != expected.function:
                invalid_triggers.append(f"{name}:function")
            elif _sql_fingerprint(_row_value(row, "trigger_definition")) != trigger_hash:
                invalid_triggers.append(f"{name}:definition")
            elif _sql_fingerprint(_row_value(row, "function_definition")) != function_hash:
                invalid_triggers.append(f"{name}:function_definition")

        invalid_labels = {item.split(":", 1)[0] for item in invalid_columns}
        return DirectionalThesisV1SchemaStatus(
            missing_tables=tuple(sorted(_REQUIRED_TABLES - present_tables)),
            missing_columns=tuple(sorted(set(expected_columns) - satisfied_columns - invalid_labels)),
            invalid_columns=tuple(sorted(invalid_columns)),
            missing_constraints=tuple(sorted(set(_REQUIRED_CONSTRAINTS) - set(constraints))),
            invalid_constraints=tuple(sorted(invalid_constraints)),
            missing_indexes=tuple(sorted(set(_REQUIRED_INDEXES) - set(indexes))),
            invalid_indexes=tuple(sorted(invalid_indexes)),
            missing_triggers=tuple(sorted(set(_REQUIRED_TRIGGERS) - set(triggers))),
            invalid_triggers=tuple(sorted(invalid_triggers)),
        )

    async def load_authoritative_candle_range(
        self,
        *,
        symbol: str,
        timeframe: str,
        start_exclusive_utc: datetime,
        as_of_utc: datetime,
    ) -> Sequence[ClosedCandleAuthorityRefV1]:
        """Freeze complete range coverage plus one preceding candle for adjacency."""

        normalized_timeframe = timeframe.upper()
        if normalized_timeframe not in {"H1", "M15"}:
            raise ValueError("P4_CANDLE_TIMEFRAME_UNSUPPORTED")
        cutoff = _utc(as_of_utc, "as_of_utc")
        start = _utc(start_exclusive_utc, "start_exclusive_utc")
        if start > cutoff:
            raise ValueError("P4_CANDLE_RANGE_INVALID")
        rows = await self._pg.fetch(
            f"""
            WITH preceding AS (
                SELECT id, symbol, timeframe, open_time, close_time,
                       open, high, low, close, volume, tick_count,
                       selected_provider, selected_feed, provider_timestamp_semantics,
                       selected_raw_candle_id, selection_policy, selection_rank, content_hash
                FROM {CANONICAL_CANDLE_TABLE}
                WHERE symbol = $1 AND timeframe = $2 AND complete IS TRUE
                  AND provider_timestamp_semantics <> 'UNSPECIFIED'
                  AND close_time <= $3
                ORDER BY close_time DESC, id DESC
                LIMIT 1
            ), covered AS (
                SELECT id, symbol, timeframe, open_time, close_time,
                       open, high, low, close, volume, tick_count,
                       selected_provider, selected_feed, provider_timestamp_semantics,
                       selected_raw_candle_id, selection_policy, selection_rank, content_hash
                FROM {CANONICAL_CANDLE_TABLE}
                WHERE symbol = $1 AND timeframe = $2 AND complete IS TRUE
                  AND provider_timestamp_semantics <> 'UNSPECIFIED'
                  AND close_time > $3 AND close_time <= $4
            )
            SELECT * FROM (SELECT * FROM preceding UNION ALL SELECT * FROM covered) selected
            ORDER BY close_time, id
            """,
            symbol.upper(),
            normalized_timeframe,
            start,
            cutoff,
        )
        return tuple(candle_authority_from_row(dict(row)) for row in rows)

    async def process_from_canonical_candles(
        self,
        *,
        strategy_lifecycle_id: str,
        context_epoch_id: str,
        symbol: str,
        decision_at_utc: datetime,
        strategy_direction: Direction,
        selected_route: str,
        pressure_authority: PressureDirectionAuthorityV1,
        route_authorization: RouteDirectionAuthorizationV1 | None = None,
        source_request_id: str | None = None,
    ) -> DirectionalThesisPersistResult:
        context_row = await self._pg.fetchrow(
            f"SELECT opened_at FROM {CONTEXT_TABLE} WHERE context_epoch_id = $1",
            context_epoch_id,
        )
        if context_row is None:
            return DirectionalThesisPersistResult(
                status="REJECTED",
                strategy_lifecycle_id=strategy_lifecycle_id,
                context_epoch_id=context_epoch_id,
                reason_code="CONTEXT_EPOCH_MISSING",
            )
        coverage_start = _row_value(context_row, "opened_at")
        if not isinstance(coverage_start, datetime):
            raise DirectionalThesisV1IntegrityError("CONTEXT_EPOCH_OPEN_CLOCK_MISSING")
        provider = Strategy5SCRStructuralProofProviderV1(self)
        evidence = await provider.provide(
            strategy_lifecycle_id=strategy_lifecycle_id,
            context_epoch_id=context_epoch_id,
            symbol=symbol,
            decision_at_utc=decision_at_utc,
            strategy_direction=strategy_direction,
            selected_route=selected_route,
            pressure_authority=pressure_authority,
            coverage_start_at_utc=coverage_start,
            route_authorization=route_authorization,
            source_request_id=source_request_id,
        )
        return await self.process_evidence(evidence)

    async def load_thesis(self, strategy_thesis_id: str) -> DirectionalThesisV1 | None:
        row = await self._pg.fetchrow(
            f"SELECT * FROM {THESIS_TABLE} WHERE strategy_thesis_id = $1",
            strategy_thesis_id,
        )
        return None if row is None else _thesis_from_row(row)

    async def load_active(self, strategy_lifecycle_id: str) -> DirectionalThesisV1 | None:
        row = await self._pg.fetchrow(
            f"SELECT * FROM {THESIS_TABLE} WHERE strategy_lifecycle_id = $1 AND state = 'ACTIVE'",
            strategy_lifecycle_id,
        )
        return None if row is None else _thesis_from_row(row)

    async def load_history(self, strategy_lifecycle_id: str) -> tuple[DirectionalThesisV1, ...]:
        rows = await self._pg.fetch(
            f"SELECT * FROM {THESIS_TABLE} WHERE strategy_lifecycle_id = $1 "
            "ORDER BY thesis_sequence, strategy_thesis_id",
            strategy_lifecycle_id,
        )
        return tuple(_thesis_from_row(row) for row in rows)

    async def process_evidence(self, evidence: DirectionalThesisEvidenceV1) -> DirectionalThesisPersistResult:
        """Build and atomically persist one ordered proof chain."""

        async with self._pg.transaction() as connection:
            lifecycle = await connection.fetchrow(
                f"SELECT strategy_lifecycle_id, symbol, state, last_event_at FROM {LIFECYCLE_TABLE} "
                "WHERE strategy_lifecycle_id = $1 FOR UPDATE",
                evidence.strategy_lifecycle_id,
            )
            if lifecycle is None:
                return self._result("REJECTED", evidence, "CANONICAL_LIFECYCLE_MISSING")

            active_preview = await connection.fetchrow(
                f"SELECT strategy_thesis_id, context_epoch_id FROM {THESIS_TABLE} "
                "WHERE strategy_lifecycle_id = $1 AND state = 'ACTIVE'",
                evidence.strategy_lifecycle_id,
            )
            lifecycle_state = str(_row_value(lifecycle, "state"))
            if lifecycle_state in TERMINAL_LIFECYCLE_STATES:
                if active_preview is None:
                    return self._result("NO_CHANGE", evidence, "NO_ACTIVE_THESIS")
                active_context_id = str(_row_value(active_preview, "context_epoch_id"))
                await connection.fetchrow(
                    f"SELECT context_epoch_id FROM {CONTEXT_TABLE} WHERE context_epoch_id = $1 FOR UPDATE",
                    active_context_id,
                )
                active_row = await connection.fetchrow(
                    f"SELECT * FROM {THESIS_TABLE} WHERE strategy_thesis_id = $1 AND state = 'ACTIVE' FOR UPDATE",
                    str(_row_value(active_preview, "strategy_thesis_id")),
                )
                if active_row is None:
                    return self._result("NO_CHANGE", evidence, "NO_ACTIVE_THESIS")
                active = _thesis_from_row(active_row)
                terminal_at = _row_value(lifecycle, "last_event_at")
                if not isinstance(terminal_at, datetime):
                    raise DirectionalThesisV1IntegrityError("LIFECYCLE_TERMINAL_CLOCK_MISSING")
                closed = await self._close_locked(
                    connection,
                    active,
                    state="TERMINAL",
                    closed_at_utc=max(active.created_at_utc, terminal_at),
                    reason="LIFECYCLE_TERMINAL",
                )
                return self._result("TERMINATED", evidence, thesis=closed)

            if str(_row_value(lifecycle, "symbol")).upper() != evidence.symbol:
                return self._result("REJECTED", evidence, "LIFECYCLE_SYMBOL_MISMATCH")

            context_ids = {evidence.context_epoch_id}
            if active_preview is not None:
                context_ids.add(str(_row_value(active_preview, "context_epoch_id")))
            context_rows = await connection.fetch(
                f"SELECT * FROM {CONTEXT_TABLE} WHERE context_epoch_id = ANY($1::text[]) "
                "ORDER BY context_epoch_id FOR UPDATE",
                sorted(context_ids),
            )
            contexts = {str(_row_value(row, "context_epoch_id")): row for row in context_rows}
            context_row = contexts.get(evidence.context_epoch_id)
            active_row = await connection.fetchrow(
                f"SELECT * FROM {THESIS_TABLE} WHERE strategy_lifecycle_id = $1 AND state = 'ACTIVE' FOR UPDATE",
                evidence.strategy_lifecycle_id,
            )
            active = None if active_row is None else _thesis_from_row(active_row)

            # Reconcile an active thesis against its persisted parent before
            # evaluating new proof evidence.  A WAIT/invalid successor request
            # must never keep a thesis alive under a superseded/terminal epoch.
            if active is not None:
                parent_row = contexts.get(active.context_epoch_id)
                if parent_row is None:
                    raise DirectionalThesisV1IntegrityError("ACTIVE_THESIS_CONTEXT_EPOCH_MISSING")
                parent = _context_from_row(parent_row)
                if parent.state != "ACTIVE":
                    parent_state: Literal["INVALIDATED", "TERMINAL"] = (
                        "TERMINAL" if parent.state == "TERMINAL" else "INVALIDATED"
                    )
                    parent_closed_at = parent.closed_at_utc or evidence.decision_at_utc
                    await self._close_locked(
                        connection,
                        active,
                        state=parent_state,
                        closed_at_utc=max(active.created_at_utc, parent_closed_at),
                        reason=f"CONTEXT_EPOCH_{parent.state}",
                    )
                    active = None

            # Parent reconciliation above is authoritative even when the
            # incoming replay points at a missing/bogus context epoch.
            if context_row is None:
                return self._result("REJECTED", evidence, "CONTEXT_EPOCH_MISSING")
            context = _context_from_row(context_row)
            if context.strategy_lifecycle_id != evidence.strategy_lifecycle_id or context.symbol != evidence.symbol:
                return self._result("REJECTED", evidence, "CONTEXT_EPOCH_SCOPE_MISMATCH")
            if active is not None and context.state == "ACTIVE" and active.context_epoch_id != context.context_epoch_id:
                await self._close_locked(
                    connection,
                    active,
                    state="INVALIDATED",
                    closed_at_utc=max(active.created_at_utc, context.opened_at_utc),
                    reason="CONTEXT_EPOCH_CHANGED",
                )
                active = None

            if context.state != "ACTIVE":
                if active is not None and active.context_epoch_id == context.context_epoch_id:
                    state: Literal["INVALIDATED", "TERMINAL"] = (
                        "TERMINAL" if context.state == "TERMINAL" else "INVALIDATED"
                    )
                    closed_at = context.closed_at_utc or evidence.decision_at_utc
                    closed = await self._close_locked(
                        connection,
                        active,
                        state=state,
                        closed_at_utc=max(active.created_at_utc, closed_at),
                        reason=f"CONTEXT_EPOCH_{context.state}",
                    )
                    status: DirectionalThesisPersistStatus = "TERMINATED" if state == "TERMINAL" else "INVALIDATED"
                    return self._result(status, evidence, thesis=closed)
                return self._result("REJECTED", evidence, "CONTEXT_EPOCH_NOT_ACTIVE")

            # Reconcile the immutable active proof chain only after the
            # requested parent is proven to be this same active ContextEpoch,
            # but before candidate pressure/route/direction gates.  A bogus
            # context request must not gain authority to close the thesis.
            if active is not None:
                active_h1, active_m15 = await self._validate_thesis_proof_chain(
                    connection,
                    active,
                )
                liveness = evaluate_active_structural_liveness(
                    h1_proof=active_h1,
                    m15_proof=active_m15,
                    h1_candles=evidence.h1_candles,
                    m15_candles=evidence.m15_candles,
                    liveness_checked_through_utc=active.liveness_checked_through_utc,
                    decision_at_utc=evidence.decision_at_utc,
                )
                liveness_reason = liveness.reason_code
                if liveness_reason in {
                    "THESIS_INVALIDATED_BY_COUNTER_H1",
                    "THESIS_INVALIDATED_BY_M15_LEVEL_FAILURE",
                }:
                    closed = await self._close_locked(
                        connection,
                        active,
                        state="INVALIDATED",
                        closed_at_utc=max(
                            active.created_at_utc,
                            liveness.invalidated_at_utc or evidence.decision_at_utc,
                        ),
                        reason=liveness_reason,
                    )
                    return self._result(
                        "INVALIDATED",
                        evidence,
                        liveness_reason,
                        thesis=closed,
                    )
                if liveness_reason is not None:
                    status: DirectionalThesisPersistStatus = (
                        "REJECTED" if liveness_reason == "ACTIVE_LIVENESS_DECISION_PRECEDES_PROOF" else "QUARANTINED"
                    )
                    return self._result(status, evidence, liveness_reason, thesis=active)
                if liveness.checked_through_utc > active.liveness_checked_through_utc:
                    active = await self._advance_liveness_locked(
                        connection,
                        active,
                        checked_through_utc=liveness.checked_through_utc,
                    )

            build = build_directional_thesis_proofs(context=context, evidence=evidence)
            if build.status != "READY" or build.artifact is None:
                return self._result(cast(DirectionalThesisPersistStatus, build.status), evidence, build.reason_code)
            artifact = build.artifact

            if active is not None:
                await self._validate_thesis_proof_chain(
                    connection,
                    active,
                    expected_artifact=(
                        artifact if active.semantic_identity_hash == artifact.semantic_identity_hash else None
                    ),
                )
                if active.semantic_identity_hash == artifact.semantic_identity_hash:
                    return self._result(
                        "DUPLICATE",
                        evidence,
                        "DIRECTIONAL_THESIS_ALREADY_PERSISTED",
                        artifact=artifact,
                        thesis=active,
                    )
                if active.strategy_direction == evidence.strategy_direction:
                    return self._result(
                        "NO_CHANGE",
                        evidence,
                        "ACTIVE_DIRECTIONAL_THESIS_RETAINED_ON_REINFORCEMENT",
                        artifact=artifact,
                        thesis=active,
                    )
                return self._result(
                    "REJECTED",
                    evidence,
                    "ACTIVE_DIRECTIONAL_THESIS_EXISTS",
                    artifact=artifact,
                    thesis=active,
                )

            existing_row = await connection.fetchrow(
                f"SELECT * FROM {THESIS_TABLE} WHERE semantic_identity_hash = $1 FOR UPDATE",
                artifact.semantic_identity_hash,
            )
            if existing_row is not None:
                existing = _thesis_from_row(existing_row)
                await self._validate_thesis_proof_chain(
                    connection,
                    existing,
                    expected_artifact=artifact,
                )
                return self._result(
                    "DUPLICATE",
                    evidence,
                    "DIRECTIONAL_THESIS_ALREADY_PERSISTED",
                    artifact=artifact,
                    thesis=existing,
                )

            await self._insert_or_reuse_h1(connection, artifact.h1_proof)
            await self._insert_or_reuse_m15(connection, artifact.m15_proof)
            sequence = int(
                await connection.fetchval(
                    f"SELECT COALESCE(MAX(thesis_sequence), 0) + 1 FROM {THESIS_TABLE} "
                    "WHERE strategy_lifecycle_id = $1",
                    evidence.strategy_lifecycle_id,
                )
            )
            thesis = self._new_thesis(context, evidence, artifact, sequence)
            await self._insert_thesis(connection, thesis)
            return self._result("PERSISTED", evidence, artifact=artifact, thesis=thesis)

    async def invalidate_active(
        self,
        strategy_lifecycle_id: str,
        closed_at_utc: datetime,
        reason: str,
    ) -> DirectionalThesisPersistResult:
        return await self._close_active(
            strategy_lifecycle_id,
            closed_at_utc,
            reason,
            state="INVALIDATED",
            require_terminal_lifecycle=False,
        )

    async def reconcile_terminal(
        self,
        strategy_lifecycle_id: str,
        closed_at_utc: datetime,
        reason: str = "LIFECYCLE_TERMINAL",
    ) -> DirectionalThesisPersistResult:
        return await self._close_active(
            strategy_lifecycle_id,
            closed_at_utc,
            reason,
            state="TERMINAL",
            require_terminal_lifecycle=True,
        )

    async def _close_active(
        self,
        strategy_lifecycle_id: str,
        closed_at_utc: datetime,
        reason: str,
        *,
        state: Literal["INVALIDATED", "TERMINAL"],
        require_terminal_lifecycle: bool,
    ) -> DirectionalThesisPersistResult:
        requested_at = _utc(closed_at_utc, "closed_at_utc")
        if not reason.strip():
            raise ValueError("closure reason must be non-empty")
        async with self._pg.transaction() as connection:
            lifecycle = await connection.fetchrow(
                f"SELECT strategy_lifecycle_id, state, last_event_at FROM {LIFECYCLE_TABLE} "
                "WHERE strategy_lifecycle_id = $1 FOR UPDATE",
                strategy_lifecycle_id,
            )
            if lifecycle is None:
                return DirectionalThesisPersistResult(
                    status="REJECTED",
                    reason_code="CANONICAL_LIFECYCLE_MISSING",
                    strategy_lifecycle_id=strategy_lifecycle_id,
                )
            lifecycle_state = str(_row_value(lifecycle, "state"))
            if require_terminal_lifecycle and lifecycle_state not in TERMINAL_LIFECYCLE_STATES:
                return DirectionalThesisPersistResult(
                    status="REJECTED", reason_code="LIFECYCLE_NOT_TERMINAL", strategy_lifecycle_id=strategy_lifecycle_id
                )

            preview = await connection.fetchrow(
                f"SELECT strategy_thesis_id, context_epoch_id FROM {THESIS_TABLE} "
                "WHERE strategy_lifecycle_id = $1 AND state = 'ACTIVE'",
                strategy_lifecycle_id,
            )
            if preview is None:
                return DirectionalThesisPersistResult(
                    status="NO_CHANGE", reason_code="NO_ACTIVE_THESIS", strategy_lifecycle_id=strategy_lifecycle_id
                )
            context_id = str(_row_value(preview, "context_epoch_id"))
            await connection.fetchrow(
                f"SELECT context_epoch_id FROM {CONTEXT_TABLE} WHERE context_epoch_id = $1 FOR UPDATE",
                context_id,
            )
            row = await connection.fetchrow(
                f"SELECT * FROM {THESIS_TABLE} WHERE strategy_thesis_id = $1 AND state = 'ACTIVE' FOR UPDATE",
                str(_row_value(preview, "strategy_thesis_id")),
            )
            if row is None:
                return DirectionalThesisPersistResult(
                    status="NO_CHANGE", reason_code="NO_ACTIVE_THESIS", strategy_lifecycle_id=strategy_lifecycle_id
                )
            thesis = _thesis_from_row(row)
            authoritative_at = requested_at
            if require_terminal_lifecycle:
                lifecycle_clock = _row_value(lifecycle, "last_event_at")
                if not isinstance(lifecycle_clock, datetime):
                    raise DirectionalThesisV1IntegrityError("LIFECYCLE_TERMINAL_CLOCK_MISSING")
                authoritative_at = lifecycle_clock
            closed = await self._close_locked(
                connection,
                thesis,
                state=state,
                closed_at_utc=max(thesis.created_at_utc, authoritative_at),
                reason=reason.strip(),
            )
            return DirectionalThesisPersistResult(
                status="TERMINATED" if state == "TERMINAL" else "INVALIDATED",
                strategy_lifecycle_id=strategy_lifecycle_id,
                context_epoch_id=closed.context_epoch_id,
                h1_proof_id=closed.h1_proof_id,
                m15_proof_id=closed.m15_proof_id,
                thesis=closed,
            )

    @staticmethod
    def _new_thesis(
        context: StrategyContextEpochV1,
        evidence: DirectionalThesisEvidenceV1,
        artifact: DirectionalThesisBuildArtifact,
        sequence: int,
    ) -> DirectionalThesisV1:
        pressure = evidence.pressure_authority
        pressure_reference = (
            pressure.contract_direction
            if pressure.mode == "CONSOLIDATED_DIRECTION_CONTRACT"
            else pressure.raw_pressure_direction
        )
        return DirectionalThesisV1(
            strategy_thesis_id=_thesis_id(artifact.semantic_identity_hash),
            strategy_lifecycle_id=evidence.strategy_lifecycle_id,
            context_epoch_id=evidence.context_epoch_id,
            thesis_sequence=sequence,
            symbol=evidence.symbol,
            strategy_direction=evidence.strategy_direction,
            direction_domain_at_creation=context.direction_domain,
            selected_route=evidence.selected_route,
            route_authorization_hash=(
                evidence.route_authorization.authorization_hash
                if context.direction_domain == "BOTH_CONDITIONAL" and evidence.route_authorization is not None
                else None
            ),
            pressure_authority_mode=pressure.mode,
            pressure_contract_status=pressure.contract_status,
            pressure_reference_direction=pressure_reference,
            pressure_formal_transition_event_id=pressure.formal_transition_event_id,
            pressure_authority_hash=pressure.authority_hash,
            counter_pressure_proof_hash=artifact.counter_pressure_proof_hash,
            h1_proof_id=artifact.h1_proof.h1_proof_id,
            m15_proof_id=artifact.m15_proof.m15_proof_id,
            structural_proof_hash=artifact.structural_proof_hash,
            semantic_identity_hash=artifact.semantic_identity_hash,
            rule_version=DIRECTIONAL_THESIS_RULE_VERSION,
            created_at_utc=evidence.decision_at_utc,
            liveness_checked_through_utc=evidence.decision_at_utc,
        )

    @staticmethod
    def _result(
        status: DirectionalThesisPersistStatus,
        evidence: DirectionalThesisEvidenceV1,
        reason_code: str | None = None,
        *,
        artifact: DirectionalThesisBuildArtifact | None = None,
        thesis: DirectionalThesisV1 | None = None,
    ) -> DirectionalThesisPersistResult:
        return DirectionalThesisPersistResult(
            status=status,
            reason_code=reason_code,
            strategy_lifecycle_id=evidence.strategy_lifecycle_id,
            context_epoch_id=evidence.context_epoch_id,
            h1_proof_id=None if artifact is None else artifact.h1_proof.h1_proof_id,
            m15_proof_id=None if artifact is None else artifact.m15_proof.m15_proof_id,
            thesis=thesis,
        )

    @staticmethod
    async def _validate_thesis_proof_chain(
        connection: Any,
        thesis: DirectionalThesisV1,
        *,
        expected_artifact: DirectionalThesisBuildArtifact | None = None,
    ) -> tuple[H1StructureProofV1, M15StructuralProofV1]:
        """Reconstruct every durable proof before treating a thesis as authority."""

        h1_row = await connection.fetchrow(
            f"SELECT * FROM {H1_PROOF_TABLE} WHERE h1_proof_id = $1 FOR UPDATE",
            thesis.h1_proof_id,
        )
        if h1_row is None:
            raise DirectionalThesisV1IntegrityError("H1_PROOF_DURABLE_ROW_MISSING")
        m15_row = await connection.fetchrow(
            f"SELECT * FROM {M15_PROOF_TABLE} WHERE m15_proof_id = $1 FOR UPDATE",
            thesis.m15_proof_id,
        )
        if m15_row is None:
            raise DirectionalThesisV1IntegrityError("M15_PROOF_DURABLE_ROW_MISSING")

        h1 = _h1_from_row(h1_row)
        m15 = _m15_from_row(m15_row)
        expected_scope = (
            thesis.strategy_lifecycle_id,
            thesis.context_epoch_id,
            thesis.symbol,
            thesis.strategy_direction,
            thesis.rule_version,
        )
        if (
            h1.strategy_lifecycle_id,
            h1.context_epoch_id,
            h1.symbol,
            h1.strategy_direction,
            h1.rule_version,
        ) != expected_scope:
            raise DirectionalThesisV1IntegrityError("H1_PROOF_THESIS_SCOPE_DRIFT")
        if (
            m15.strategy_lifecycle_id,
            m15.context_epoch_id,
            m15.symbol,
            m15.strategy_direction,
            m15.rule_version,
        ) != expected_scope:
            raise DirectionalThesisV1IntegrityError("M15_PROOF_THESIS_SCOPE_DRIFT")
        if m15.h1_proof_id != h1.h1_proof_id:
            raise DirectionalThesisV1IntegrityError("M15_PROOF_H1_LINK_DRIFT")
        if m15.h1_confirmed_at_utc != h1.confirmed_at_utc:
            raise DirectionalThesisV1IntegrityError("M15_PROOF_H1_CONFIRMATION_CLOCK_DRIFT")

        structural_hash = _proof_hash(
            {
                "context_epoch_id": thesis.context_epoch_id,
                "direction": thesis.strategy_direction,
                "h1_material_proof_hash": h1.material_proof_hash,
                "m15_material_proof_hash": m15.material_proof_hash,
                "rule_version": thesis.rule_version,
            }
        )
        semantic_hash = _proof_hash(
            {
                "context_epoch_id": thesis.context_epoch_id,
                "direction": thesis.strategy_direction,
                "h1_proof_hash": h1.material_proof_hash,
                "m15_proof_hash": m15.material_proof_hash,
                "selected_route": thesis.selected_route,
                "route_authorization_hash": thesis.route_authorization_hash,
                "pressure_authority_hash": thesis.pressure_authority_hash,
                "counter_pressure_proof_hash": thesis.counter_pressure_proof_hash,
                "rule_version": thesis.rule_version,
            }
        )
        if thesis.structural_proof_hash != structural_hash:
            raise DirectionalThesisV1IntegrityError("DIRECTIONAL_THESIS_STRUCTURAL_PROOF_HASH_DRIFT")
        if thesis.semantic_identity_hash != semantic_hash or thesis.strategy_thesis_id != _thesis_id(semantic_hash):
            raise DirectionalThesisV1IntegrityError("DIRECTIONAL_THESIS_SEMANTIC_IDENTITY_DRIFT")

        if expected_artifact is not None and (
            expected_artifact.h1_proof.h1_proof_id != h1.h1_proof_id
            or expected_artifact.h1_proof.material_proof_hash != h1.material_proof_hash
            or expected_artifact.m15_proof.m15_proof_id != m15.m15_proof_id
            or expected_artifact.m15_proof.h1_proof_id != h1.h1_proof_id
            or expected_artifact.m15_proof.material_proof_hash != m15.material_proof_hash
            or expected_artifact.structural_proof_hash != structural_hash
            or expected_artifact.semantic_identity_hash != semantic_hash
        ):
            raise DirectionalThesisV1IntegrityError("DIRECTIONAL_THESIS_PROOF_CHAIN_DRIFT")
        return h1, m15

    async def _insert_or_reuse_h1(self, connection: Any, proof: H1StructureProofV1) -> None:
        result = await connection.execute(
            f"""
            INSERT INTO {H1_PROOF_TABLE} (
                h1_proof_id, strategy_lifecycle_id, context_epoch_id, symbol,
                strategy_direction, structure_event, anchor_candle_id,
                confirmation_candle_id, reference_level, confirmation_close,
                confirmed_at, decision_at, coverage_start_at, coverage_end_at,
                source_candle_ids, source_content_hashes, coverage_complete,
                structural_authority, material_proof_hash, evidence_hash,
                semantic_dedupe_key, rule_version, evidence_payload, execution_authority
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,
                $16::jsonb,true,true,$17,$18,$19,$20,$21::jsonb,false
            ) ON CONFLICT DO NOTHING
            """,
            proof.h1_proof_id,
            proof.strategy_lifecycle_id,
            proof.context_epoch_id,
            proof.symbol,
            proof.strategy_direction,
            proof.structure_event,
            proof.anchor_candle.candle_evidence_id,
            proof.confirmation_candle.candle_evidence_id,
            proof.reference_level,
            proof.confirmation_close,
            proof.confirmed_at_utc,
            proof.decision_at_utc,
            proof.coverage_start_at_utc,
            proof.coverage_end_at_utc,
            json.dumps(list(proof.source_candle_ids), separators=(",", ":")),
            json.dumps(list(proof.source_content_hashes), separators=(",", ":")),
            proof.material_proof_hash,
            proof.evidence_hash,
            proof.semantic_dedupe_key,
            proof.rule_version,
            json.dumps(proof.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
        )
        if str(result).endswith(" 1"):
            return
        row = await connection.fetchrow(
            f"SELECT * FROM {H1_PROOF_TABLE} WHERE semantic_dedupe_key = $1 OR h1_proof_id = $2 FOR UPDATE",
            proof.semantic_dedupe_key,
            proof.h1_proof_id,
        )
        stored = None if row is None else _h1_from_row(row)
        expected = (
            proof.h1_proof_id,
            proof.strategy_lifecycle_id,
            proof.context_epoch_id,
            proof.symbol,
            proof.strategy_direction,
            proof.material_proof_hash,
            proof.semantic_dedupe_key,
        )
        actual = (
            None
            if stored is None
            else (
                stored.h1_proof_id,
                stored.strategy_lifecycle_id,
                stored.context_epoch_id,
                stored.symbol,
                stored.strategy_direction,
                stored.material_proof_hash,
                stored.semantic_dedupe_key,
            )
        )
        if actual != expected:
            raise DirectionalThesisV1IntegrityError("H1_PROOF_IDENTITY_DRIFT")

    async def _insert_or_reuse_m15(self, connection: Any, proof: M15StructuralProofV1) -> None:
        result = await connection.execute(
            f"""
            INSERT INTO {M15_PROOF_TABLE} (
                m15_proof_id, h1_proof_id, strategy_lifecycle_id, context_epoch_id,
                symbol, strategy_direction, reference_candle_id, break_candle_id,
                completion_candle_id, break_level, h1_confirmed_at, break_close_at,
                completed_at, completion_kind, decision_at, coverage_start_at,
                coverage_end_at, source_candle_ids, source_content_hashes,
                coverage_complete, structural_authority, ordering_valid,
                material_proof_hash, evidence_hash, semantic_dedupe_key,
                rule_version, evidence_payload, execution_authority
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,
                $18::jsonb,$19::jsonb,true,true,true,$20,$21,$22,$23,$24::jsonb,false
            ) ON CONFLICT DO NOTHING
            """,
            proof.m15_proof_id,
            proof.h1_proof_id,
            proof.strategy_lifecycle_id,
            proof.context_epoch_id,
            proof.symbol,
            proof.strategy_direction,
            proof.reference_candle.candle_evidence_id,
            proof.break_candle.candle_evidence_id,
            proof.completion_candle.candle_evidence_id,
            proof.break_level,
            proof.h1_confirmed_at_utc,
            proof.break_close_at_utc,
            proof.completed_at_utc,
            proof.completion_kind,
            proof.decision_at_utc,
            proof.coverage_start_at_utc,
            proof.coverage_end_at_utc,
            json.dumps(list(proof.source_candle_ids), separators=(",", ":")),
            json.dumps(list(proof.source_content_hashes), separators=(",", ":")),
            proof.material_proof_hash,
            proof.evidence_hash,
            proof.semantic_dedupe_key,
            proof.rule_version,
            json.dumps(proof.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
        )
        if str(result).endswith(" 1"):
            return
        row = await connection.fetchrow(
            f"SELECT * FROM {M15_PROOF_TABLE} WHERE semantic_dedupe_key = $1 OR m15_proof_id = $2 FOR UPDATE",
            proof.semantic_dedupe_key,
            proof.m15_proof_id,
        )
        stored = None if row is None else _m15_from_row(row)
        expected = (
            proof.m15_proof_id,
            proof.h1_proof_id,
            proof.strategy_lifecycle_id,
            proof.context_epoch_id,
            proof.symbol,
            proof.strategy_direction,
            proof.material_proof_hash,
            proof.semantic_dedupe_key,
        )
        actual = (
            None
            if stored is None
            else (
                stored.m15_proof_id,
                stored.h1_proof_id,
                stored.strategy_lifecycle_id,
                stored.context_epoch_id,
                stored.symbol,
                stored.strategy_direction,
                stored.material_proof_hash,
                stored.semantic_dedupe_key,
            )
        )
        if actual != expected:
            raise DirectionalThesisV1IntegrityError("M15_PROOF_IDENTITY_DRIFT")

    async def _insert_thesis(self, connection: Any, thesis: DirectionalThesisV1) -> None:
        payload = thesis.model_dump(mode="json")
        result = await connection.execute(
            f"""
            INSERT INTO {THESIS_TABLE} (
                strategy_thesis_id, strategy_lifecycle_id, context_epoch_id,
                thesis_sequence, symbol, strategy_direction, direction_immutable,
                state, direction_domain_at_creation, selected_route,
                route_authorization_hash, pressure_authority_mode,
                pressure_contract_status, pressure_reference_direction,
                pressure_formal_transition_event_id, pressure_authority_hash,
                counter_pressure_proof_hash,
                h1_proof_id, m15_proof_id, structural_proof_hash,
                semantic_identity_hash, rule_version, created_at, liveness_checked_through, closed_at,
                closure_reason, state_version, valid_for_execution,
                execution_authority, payload
            ) VALUES (
                $1,$2,$3,$4,$5,$6,true,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                $17,$18,$19,$20,$21,$22,$23,$24,$25,$26,false,false,$27::jsonb
            ) ON CONFLICT DO NOTHING
            """,
            thesis.strategy_thesis_id,
            thesis.strategy_lifecycle_id,
            thesis.context_epoch_id,
            thesis.thesis_sequence,
            thesis.symbol,
            thesis.strategy_direction,
            thesis.state,
            thesis.direction_domain_at_creation,
            thesis.selected_route,
            thesis.route_authorization_hash,
            thesis.pressure_authority_mode,
            thesis.pressure_contract_status,
            thesis.pressure_reference_direction,
            thesis.pressure_formal_transition_event_id,
            thesis.pressure_authority_hash,
            thesis.counter_pressure_proof_hash,
            thesis.h1_proof_id,
            thesis.m15_proof_id,
            thesis.structural_proof_hash,
            thesis.semantic_identity_hash,
            thesis.rule_version,
            thesis.created_at_utc,
            thesis.liveness_checked_through_utc,
            thesis.closed_at_utc,
            thesis.closure_reason,
            thesis.state_version,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
        if str(result).endswith(" 1"):
            return
        row = await connection.fetchrow(
            f"SELECT * FROM {THESIS_TABLE} WHERE semantic_identity_hash = $1 OR strategy_thesis_id = $2 FOR UPDATE",
            thesis.semantic_identity_hash,
            thesis.strategy_thesis_id,
        )
        if row is None:
            raise DirectionalThesisV1IntegrityError("DIRECTIONAL_THESIS_INSERT_CONFLICT_UNKNOWN")
        stored = _thesis_from_row(row)
        if (
            stored.strategy_thesis_id != thesis.strategy_thesis_id
            or stored.semantic_identity_hash != thesis.semantic_identity_hash
            or stored.structural_proof_hash != thesis.structural_proof_hash
            or stored.h1_proof_id != thesis.h1_proof_id
            or stored.m15_proof_id != thesis.m15_proof_id
        ):
            raise DirectionalThesisV1IntegrityError("DIRECTIONAL_THESIS_IDENTITY_DRIFT")

    @staticmethod
    async def _advance_liveness_locked(
        connection: Any,
        thesis: DirectionalThesisV1,
        *,
        checked_through_utc: datetime,
    ) -> DirectionalThesisV1:
        await Strategy5SCRDirectionalThesisV1Repository._validate_thesis_proof_chain(connection, thesis)
        advanced = advance_directional_thesis_liveness(
            thesis,
            checked_through_utc=checked_through_utc,
        )
        if advanced is thesis:
            return thesis
        payload = json.dumps(advanced.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        result = await connection.execute(
            f"""
            UPDATE {THESIS_TABLE}
            SET liveness_checked_through = $2, state_version = $3,
                payload = $4::jsonb, updated_at = now()
            WHERE strategy_thesis_id = $1 AND state = 'ACTIVE' AND state_version = $5
            """,
            advanced.strategy_thesis_id,
            advanced.liveness_checked_through_utc,
            advanced.state_version,
            payload,
            thesis.state_version,
        )
        if not str(result).endswith(" 1"):
            raise DirectionalThesisV1IntegrityError("DIRECTIONAL_THESIS_LIVENESS_VERSION_NOT_ADVANCED")
        return advanced

    @staticmethod
    async def _close_locked(
        connection: Any,
        thesis: DirectionalThesisV1,
        *,
        state: Literal["INVALIDATED", "TERMINAL"],
        closed_at_utc: datetime,
        reason: str,
    ) -> DirectionalThesisV1:
        await Strategy5SCRDirectionalThesisV1Repository._validate_thesis_proof_chain(
            connection,
            thesis,
        )
        effective_closed_at = max(closed_at_utc, thesis.liveness_checked_through_utc)
        closed = close_directional_thesis(
            thesis,
            state=state,
            closed_at_utc=effective_closed_at,
            reason=reason,
        )
        payload = json.dumps(closed.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        result = await connection.execute(
            f"""
            UPDATE {THESIS_TABLE}
            SET state = $2, closed_at = $3, closure_reason = $4,
                state_version = $5, liveness_checked_through = $6,
                payload = $7::jsonb, updated_at = now()
            WHERE strategy_thesis_id = $1 AND state = 'ACTIVE' AND state_version = $8
            """,
            closed.strategy_thesis_id,
            closed.state,
            closed.closed_at_utc,
            closed.closure_reason,
            closed.state_version,
            closed.liveness_checked_through_utc,
            payload,
            thesis.state_version,
        )
        if not str(result).endswith(" 1"):
            raise DirectionalThesisV1IntegrityError("DIRECTIONAL_THESIS_STATE_VERSION_NOT_ADVANCED")
        return closed


__all__ = [
    "DIRECTIONAL_THESIS_V1_SHADOW_ONLY_FLAG",
    "DIRECTIONAL_THESIS_V1_WRITER_FLAG",
    "H1_PROOF_TABLE",
    "M15_PROOF_TABLE",
    "THESIS_TABLE",
    "DirectionalThesisPersistResult",
    "DirectionalThesisPersistStatus",
    "DirectionalThesisV1IntegrityError",
    "DirectionalThesisV1PersistenceError",
    "DirectionalThesisV1RuntimeConfig",
    "DirectionalThesisV1SchemaStatus",
    "Strategy5SCRDirectionalThesisV1Repository",
]
