"""Atomic, shadow-only persistence for Strategy 5S-CR TradePlanCandidate V2."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import ValidationError

from analysis.strategy_5scr_tradeplan_candidate_v2 import (
    derive_structural_target_map_v1,
    select_nearest_structural_target_v1,
    solve_tradeplan_candidate_v2,
)
from contracts.strategy_5scr_lifecycle_v2 import TERMINAL_LIFECYCLE_STATES, StrategyLifecycleV2
from contracts.strategy_5scr_tradeplan_candidate_v2 import (
    StructuralCandleAuthorityV1,
    StructuralStopAuthorityV1,
    StructuralTargetAuthorityV1,
    StructuralTargetMapAuthorityV1,
    TradePlanCandidateBuildEvidenceV2,
    TradePlanCandidateV2,
    TradePlanEvaluationV2,
    broker_geometry_material_hash_v1,
    canonical_hash_v1,
)
from storage.observer_export_outbox import ObserverExportOutboxRepository
from storage.observer_strategy_events import canonical_tradeplan_decision_observer_draft
from storage.postgres_client import PostgresClient, pg_client
from storage.strategy_5scr_directional_thesis_v1_repository import (
    Strategy5SCRDirectionalThesisV1Repository,
    _context_from_row,
)
from storage.strategy_5scr_directional_thesis_v1_repository import _thesis_from_row as _p4_thesis_from_row
from storage.strategy_5scr_execution_box_v1_repository import (
    Strategy5SCRExecutionBoxV1Repository,
    _box_from_row,
    _validate_predecessor_chain,
)

CANDIDATE_TABLE = "strategy_5scr_tradeplan_candidates_v2"
EVALUATION_TABLE = "strategy_5scr_tradeplan_candidate_evaluations_v2"
BOX_TABLE = "strategy_5scr_execution_boxes_v1"
THESIS_TABLE = "strategy_5scr_directional_theses_v1"
CONTEXT_TABLE = "strategy_5scr_context_epochs_v1"
LIFECYCLE_TABLE = "strategy_5scr_analysis_lifecycles_v2"
CANONICAL_CANDLE_TABLE = "canonical_candles"

TRADEPLAN_CANDIDATE_V2_WRITER_FLAG = "STRATEGY_5SCR_TRADEPLAN_CANDIDATE_V2_WRITER_ENABLED"
TRADEPLAN_CANDIDATE_V2_SHADOW_ONLY_FLAG = "STRATEGY_5SCR_TRADEPLAN_CANDIDATE_V2_SHADOW_ONLY"


class TradePlanCandidateV2IntegrityError(RuntimeError):
    """Durable P6 state disagrees with its immutable authority payload."""


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
    return hashlib.sha256(_normalize_sql(value).encode()).hexdigest()


def _catalog_char(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value or "")


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _terminal_clock(*values: Any, floor: datetime) -> datetime:
    clocks = tuple(value for value in values if isinstance(value, datetime))
    if not clocks:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_PARENT_TERMINAL_CLOCK_MISSING")
    return max((floor, *clocks))


@dataclass(frozen=True)
class TradePlanCandidateV2RuntimeConfig:
    enabled: bool = False
    shadow_only: bool = True

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> TradePlanCandidateV2RuntimeConfig:
        source = os.environ if environ is None else environ
        return cls(
            enabled=_enabled(source.get(TRADEPLAN_CANDIDATE_V2_WRITER_FLAG), default=False),
            shadow_only=_enabled(source.get(TRADEPLAN_CANDIDATE_V2_SHADOW_ONLY_FLAG), default=True),
        )

    def validate(self) -> None:
        if self.enabled and not self.shadow_only:
            raise RuntimeError("STRATEGY_5SCR_TRADEPLAN_CANDIDATE_V2_SHADOW_ONLY_REQUIRED")


@dataclass(frozen=True)
class TradePlanCandidateV2SchemaStatus:
    missing_tables: tuple[str, ...]
    invalid_tables: tuple[str, ...]
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
                self.invalid_tables,
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
    table: str,
    rows: Sequence[tuple[str, str, bool, int | None, str]],
) -> dict[tuple[str, str], _ColumnContract]:
    return {
        (table, name): _ColumnContract(kind, nullable, size, default) for name, kind, nullable, size, default in rows
    }


_REQUIRED_TABLES = frozenset({CANDIDATE_TABLE, EVALUATION_TABLE, BOX_TABLE})
_REQUIRED_COLUMNS: dict[tuple[str, str], _ColumnContract] = {
    **_columns(
        CANDIDATE_TABLE,
        (
            ("tradeplan_id", "text", False, None, ""),
            ("strategy_lifecycle_id", "text", False, None, ""),
            ("context_epoch_id", "text", False, None, ""),
            ("strategy_thesis_id", "text", False, None, ""),
            ("execution_box_id", "text", False, None, ""),
            ("candidate_sequence", "integer", False, None, ""),
            ("candidate_revision", "integer", False, None, ""),
            ("previous_tradeplan_id", "text", True, None, ""),
            ("previous_candidate_sequence", "integer", True, None, ""),
            ("previous_candidate_revision", "integer", True, None, ""),
            ("symbol", "character varying", False, 32, ""),
            ("strategy_direction", "character varying", False, 4, ""),
            ("candidate_status", "character varying", False, 40, ""),
            ("lifecycle_state", "character varying", False, 20, ""),
            ("route_type", "character varying", False, 120, ""),
            ("candidate_price", "numeric", False, None, ""),
            ("stop_loss", "numeric", False, None, ""),
            ("target_price", "numeric", False, None, ""),
            ("risk_distance_price", "numeric", False, None, ""),
            ("target_distance_price", "numeric", False, None, ""),
            ("rr", "numeric", False, None, ""),
            ("pip_size", "numeric", False, None, ""),
            ("target_mode", "character varying", False, 100, ""),
            ("broker_authority_hash", "character varying", False, 71, ""),
            ("broker_geometry_material_hash", "character varying", False, 71, ""),
            ("broker_digits", "integer", False, None, ""),
            ("broker_point", "numeric", False, None, ""),
            ("broker_tick_size", "numeric", False, None, ""),
            ("broker_pip_size", "numeric", False, None, ""),
            ("broker_spread_price", "numeric", False, None, ""),
            ("material_box_hash", "character varying", False, 71, ""),
            ("execution_box_freeze_authority_hash", "character varying", False, 71, ""),
            ("material_context_hash", "character varying", False, 71, ""),
            ("thesis_semantic_identity_hash", "character varying", False, 71, ""),
            ("box_sequence", "integer", False, None, ""),
            ("box_version", "integer", False, None, ""),
            ("structural_target_authority_hash", "character varying", False, 71, ""),
            ("structural_target_material_hash", "character varying", False, 71, ""),
            ("target_map_authority_hash", "character varying", False, 71, ""),
            ("structural_stop_authority_hash", "character varying", False, 71, ""),
            ("material_candidate_hash", "character varying", False, 71, ""),
            ("formation_evidence_hash", "character varying", False, 71, ""),
            ("source_candle_ids", "jsonb", False, None, ""),
            ("opened_at", "timestamp with time zone", False, None, ""),
            ("superseded_at", "timestamp with time zone", True, None, ""),
            ("invalidated_at", "timestamp with time zone", True, None, ""),
            ("expired_at", "timestamp with time zone", True, None, ""),
            ("state_version", "bigint", False, None, ""),
            ("rule_version", "character varying", False, 100, ""),
            ("valid_for_execution", "boolean", False, None, "false"),
            ("execution_authority", "boolean", False, None, "false"),
            (
                "next_required_stage",
                "character varying",
                False,
                40,
                "'RISK_RESERVATION'::character varying",
            ),
            ("payload", "jsonb", False, None, ""),
            ("target_authority_payload", "jsonb", False, None, ""),
            ("stop_authority_payload", "jsonb", False, None, ""),
            ("evidence_payload", "jsonb", False, None, ""),
            ("created_at", "timestamp with time zone", False, None, "now()"),
            ("updated_at", "timestamp with time zone", False, None, "now()"),
        ),
    ),
    **_columns(
        EVALUATION_TABLE,
        (
            ("evaluation_id", "text", False, None, ""),
            ("strategy_lifecycle_id", "text", False, None, ""),
            ("context_epoch_id", "text", False, None, ""),
            ("strategy_thesis_id", "text", False, None, ""),
            ("execution_box_id", "text", False, None, ""),
            ("symbol", "character varying", False, 32, ""),
            ("strategy_direction", "character varying", False, 4, ""),
            ("material_context_hash", "character varying", False, 71, ""),
            ("thesis_semantic_identity_hash", "character varying", False, 71, ""),
            ("material_box_hash", "character varying", False, 71, ""),
            ("execution_box_freeze_authority_hash", "character varying", False, 71, ""),
            ("evaluation_sequence", "integer", False, None, ""),
            ("evaluated_at", "timestamp with time zone", False, None, ""),
            ("source_request_id", "text", False, None, ""),
            ("decision", "character varying", False, 20, ""),
            ("reason_code", "character varying", False, 120, ""),
            ("reason_codes", "jsonb", False, None, ""),
            ("material_evaluation_hash", "character varying", False, 71, ""),
            ("evidence_hash", "character varying", False, 71, ""),
            ("rule_version", "character varying", False, 100, ""),
            ("tradeplan_id", "text", True, None, ""),
            ("candidate_sequence", "integer", True, None, ""),
            ("candidate_revision", "integer", True, None, ""),
            ("material_candidate_hash", "character varying", True, 71, ""),
            ("evidence_payload", "jsonb", False, None, ""),
            ("target_authority_payload", "jsonb", False, None, ""),
            ("stop_authority_payload", "jsonb", False, None, ""),
            ("valid_for_execution", "boolean", False, None, "false"),
            ("execution_authority", "boolean", False, None, "false"),
            ("created_at", "timestamp with time zone", False, None, "now()"),
        ),
    ),
}

_REQUIRED_CONSTRAINTS: dict[str, _ConstraintContract] = {
    f"{CANDIDATE_TABLE}_pkey": _ConstraintContract(CANDIDATE_TABLE, "p"),
    "fk_5scr_tradeplan_candidate_v2_lifecycle": _ConstraintContract(CANDIDATE_TABLE, "f"),
    "fk_5scr_tradeplan_candidate_v2_context_scope": _ConstraintContract(CANDIDATE_TABLE, "f"),
    "fk_5scr_tradeplan_candidate_v2_thesis_scope": _ConstraintContract(CANDIDATE_TABLE, "f"),
    "fk_5scr_tradeplan_candidate_v2_execution_box_scope": _ConstraintContract(CANDIDATE_TABLE, "f"),
    "fk_5scr_tradeplan_candidate_v2_previous_scope": _ConstraintContract(CANDIDATE_TABLE, "f"),
    "uq_5scr_tradeplan_candidate_v2_evaluation_scope": _ConstraintContract(CANDIDATE_TABLE, "u"),
    "uq_5scr_tradeplan_candidate_v2_predecessor_scope": _ConstraintContract(CANDIDATE_TABLE, "u"),
    "uq_5scr_tradeplan_candidate_v2_sequence": _ConstraintContract(CANDIDATE_TABLE, "u"),
    "uq_5scr_tradeplan_candidate_v2_revision": _ConstraintContract(CANDIDATE_TABLE, "u"),
    "ck_5scr_tradeplan_candidate_v2_identity": _ConstraintContract(CANDIDATE_TABLE, "c"),
    "ck_5scr_tradeplan_candidate_v2_numbers": _ConstraintContract(CANDIDATE_TABLE, "c"),
    "ck_5scr_tradeplan_candidate_v2_geometry": _ConstraintContract(CANDIDATE_TABLE, "c"),
    "ck_5scr_tradeplan_candidate_v2_state": _ConstraintContract(CANDIDATE_TABLE, "c"),
    "ck_5scr_tradeplan_candidate_v2_lineage": _ConstraintContract(CANDIDATE_TABLE, "c"),
    "ck_5scr_tradeplan_candidate_v2_temporal": _ConstraintContract(CANDIDATE_TABLE, "c"),
    "ck_5scr_tradeplan_candidate_v2_payloads": _ConstraintContract(CANDIDATE_TABLE, "c"),
    "ck_5scr_tradeplan_candidate_v2_shadow_only": _ConstraintContract(CANDIDATE_TABLE, "c"),
    f"{EVALUATION_TABLE}_pkey": _ConstraintContract(EVALUATION_TABLE, "p"),
    "fk_5scr_tradeplan_candidate_evaluation_v2_box_scope": _ConstraintContract(EVALUATION_TABLE, "f"),
    "fk_5scr_tradeplan_candidate_evaluation_v2_context_scope": _ConstraintContract(EVALUATION_TABLE, "f"),
    "fk_5scr_tradeplan_candidate_evaluation_v2_thesis_scope": _ConstraintContract(EVALUATION_TABLE, "f"),
    "fk_5scr_tradeplan_candidate_evaluation_v2_candidate_scope": _ConstraintContract(EVALUATION_TABLE, "f"),
    "uq_5scr_tradeplan_candidate_evaluation_v2_sequence": _ConstraintContract(EVALUATION_TABLE, "u"),
    "uq_5scr_tradeplan_candidate_evaluation_v2_clock": _ConstraintContract(EVALUATION_TABLE, "u"),
    "uq_5scr_tradeplan_candidate_evaluation_v2_request": _ConstraintContract(EVALUATION_TABLE, "u"),
    "ck_5scr_tradeplan_candidate_evaluation_v2_identity": _ConstraintContract(EVALUATION_TABLE, "c"),
    "ck_5scr_tradeplan_candidate_evaluation_v2_decision": _ConstraintContract(EVALUATION_TABLE, "c"),
    "ck_5scr_tradeplan_candidate_evaluation_v2_candidate_link": _ConstraintContract(EVALUATION_TABLE, "c"),
    "ck_5scr_tradeplan_candidate_evaluation_v2_payloads": _ConstraintContract(EVALUATION_TABLE, "c"),
    "ck_5scr_tradeplan_candidate_evaluation_v2_shadow_only": _ConstraintContract(EVALUATION_TABLE, "c"),
    "uq_5scr_execution_box_tradeplan_evaluation_scope_v1": _ConstraintContract(BOX_TABLE, "u"),
    "uq_5scr_execution_box_tradeplan_scope_v1": _ConstraintContract(BOX_TABLE, "u"),
    "uq_5scr_context_epoch_tradeplan_scope_v1": _ConstraintContract(CONTEXT_TABLE, "u"),
    "uq_5scr_thesis_tradeplan_scope_v1": _ConstraintContract(THESIS_TABLE, "u"),
}

# Filled from pg_get_constraintdef() on disposable PostgreSQL 16.  Empty is
# deliberate fail-closed behavior during development, never fragment matching.
_REQUIRED_CONSTRAINT_DEFINITION_HASHES: dict[str, str] = {
    "ck_5scr_tradeplan_candidate_evaluation_v2_candidate_link": "9f41db0f955d90ec81bd30d5169ef903923dd2274d70f3ff754b67a50ae2a259",
    "ck_5scr_tradeplan_candidate_evaluation_v2_decision": "77ff61d33fe328440f02cee2efadf01913db5bde470c96ceaaad8865cd9c542d",
    "ck_5scr_tradeplan_candidate_evaluation_v2_identity": "064dd5d76843cf4c20219bbadc041b6915a167ae096633f67c4fa921255ca9f5",
    "ck_5scr_tradeplan_candidate_evaluation_v2_payloads": "facf9c80a51023e4f3fc012f12589414fce13b43b942f81db8b1e473b83b7a2e",
    "ck_5scr_tradeplan_candidate_evaluation_v2_shadow_only": "9b996154165a14a6f559155e6d2a0abc80105aeee0ea7383feb1cc9f7f940544",
    "ck_5scr_tradeplan_candidate_v2_geometry": "0f9512e5185c37722ca3cde79271552f2b1058a8625fc6345c559f41e3503ea5",
    "ck_5scr_tradeplan_candidate_v2_identity": "e2c1f6379bb9baee8b00f1511006dbcf69368a962573994819350540ace0a5fc",
    "ck_5scr_tradeplan_candidate_v2_lineage": "5d80ef2f3d93f154f547d5e7c05c135528aeb7947a12f4fb964cf0c29500f044",
    "ck_5scr_tradeplan_candidate_v2_numbers": "40618756125b391aee2639b88810b749a2ffa36c6f8b00dc685cc10441ec5de5",
    "ck_5scr_tradeplan_candidate_v2_payloads": "b46f98595113c3863cbfb551617b46e38e75f86e22f16b84624f72f478f7d4eb",
    "ck_5scr_tradeplan_candidate_v2_shadow_only": "305c9a16938a2618282af19a9a4d2c6fdc8589caf6bf837b0f0e270b1047e756",
    "ck_5scr_tradeplan_candidate_v2_state": "6b13e5cac4c8497d41f9e0fc5dc2ea7b066b079012716bc427934b5922de2b30",
    "ck_5scr_tradeplan_candidate_v2_temporal": "742b882e422f44e1a1a17032350209480d6437fcadb57d5ff4e25d3ef676c99c",
    "fk_5scr_tradeplan_candidate_evaluation_v2_box_scope": "09f8b73a02c11afe2e7cb13d19f467bc8d7b7bfc7f1883040270f7d2e3216fef",
    "fk_5scr_tradeplan_candidate_evaluation_v2_candidate_scope": "d99c23ddf449a3ccb085e78ce9e3442c72c3a6fea870ec503b15507e90372dba",
    "fk_5scr_tradeplan_candidate_evaluation_v2_context_scope": "3630d8b88fc111dbced3c11f162593f259f4b06bde73983c2c6f12627fe4f309",
    "fk_5scr_tradeplan_candidate_evaluation_v2_thesis_scope": "b0a5a5b3940d644501b2c3299ab7a068cb3adf55e3f0a5db34dbf6eae19b8d58",
    "fk_5scr_tradeplan_candidate_v2_context_scope": "3630d8b88fc111dbced3c11f162593f259f4b06bde73983c2c6f12627fe4f309",
    "fk_5scr_tradeplan_candidate_v2_execution_box_scope": "2f303213504e9effd308c11c8f9fa36212d5c4f8fb9b43f295c5839983f598d2",
    "fk_5scr_tradeplan_candidate_v2_lifecycle": "31c316748300dbd4469cf8ccd91828fcdca520c4f93363bbcbb2f8a9411a7d32",
    "fk_5scr_tradeplan_candidate_v2_previous_scope": "e60f1071b4b9a7d63d7b099f87999e4b3b963fe958d0d34668c2b46deb337e60",
    "fk_5scr_tradeplan_candidate_v2_thesis_scope": "b0a5a5b3940d644501b2c3299ab7a068cb3adf55e3f0a5db34dbf6eae19b8d58",
    "strategy_5scr_tradeplan_candidate_evaluations_v2_pkey": "cc5a2fb5a1764a7e8ea36189f516f34698cc47449df36eb8731d9d6017b85b65",
    "strategy_5scr_tradeplan_candidates_v2_pkey": "e4d4e8f0b8679eee2573c889f013a6f3ad75b8ad9f69ab49711288b494eaed7e",
    "uq_5scr_context_epoch_tradeplan_scope_v1": "c9d899c9cff5aa601f408cae55707f1ff4bda669ea0d9641e65156fde67a9446",
    "uq_5scr_execution_box_tradeplan_scope_v1": "2f4b614dc03b602dc6a3cb1412fb4ad6192fb625c5802d1cad7d174daf46e7e7",
    "uq_5scr_execution_box_tradeplan_evaluation_scope_v1": "69fcd6722cef13bf4ee1fd069afbea120896cf6773ba17efaf16149ea7d913c2",
    "uq_5scr_thesis_tradeplan_scope_v1": "839b9daebd1f0fa74fc6c973b51d1c35fae90b508e1bdcf7fa9ad25043123825",
    "uq_5scr_tradeplan_candidate_evaluation_v2_clock": "2ea5a29e7f6dba033d84545b16764155a534e7489e39ddaf821defc393f6cd26",
    "uq_5scr_tradeplan_candidate_evaluation_v2_request": "747f8c55d146e497132c2310ee8d86a65ad1ff3a1bf6c8733171066595cb87e4",
    "uq_5scr_tradeplan_candidate_evaluation_v2_sequence": "a6d1a52390ded5d78d051b7dd7c748f751bff119155586ea432870b26d99b35d",
    "uq_5scr_tradeplan_candidate_v2_evaluation_scope": "6ee676151279427d9c48a04e7c57137f0215879a87b65c0380bfc14a73cb9793",
    "uq_5scr_tradeplan_candidate_v2_predecessor_scope": "2b76c0b70c927b0bb2d37bf8fc234e09c7b052d40b3e7998c4c87960d4fe72c7",
    "uq_5scr_tradeplan_candidate_v2_revision": "d38371d93b6fd500b80674fe7b1906de8277491972b1f5901b33349362c2318b",
    "uq_5scr_tradeplan_candidate_v2_sequence": "c7e28d7a08c4543f052b96a94696f4735e3951984deef04ee548bde36e5a43fe",
}

_REQUIRED_INDEXES: dict[str, _IndexContract] = {
    "uq_5scr_tradeplan_candidate_v2_active_box": _IndexContract(CANDIDATE_TABLE, True, ("execution_box_id",)),
    "uq_5scr_tradeplan_candidate_v2_active_lifecycle": _IndexContract(
        CANDIDATE_TABLE, True, ("strategy_lifecycle_id",)
    ),
    "ix_5scr_tradeplan_candidate_v2_lifecycle_history": _IndexContract(
        CANDIDATE_TABLE, False, ("strategy_lifecycle_id", "candidate_sequence", "tradeplan_id")
    ),
    "ix_5scr_tradeplan_candidate_evaluation_v2_history": _IndexContract(
        EVALUATION_TABLE, False, ("execution_box_id", "evaluation_sequence", "evaluation_id")
    ),
    "ix_5scr_tradeplan_candidate_evaluation_v2_candidate": _IndexContract(
        EVALUATION_TABLE, False, ("tradeplan_id", "evaluation_sequence")
    ),
}
_REQUIRED_INDEX_DEFINITION_HASHES: dict[str, str] = {
    "ix_5scr_tradeplan_candidate_evaluation_v2_candidate": "ab28010f20b62df15c6197b7024c911a3020c9bbb9ccbc6b862d9c50eed6b4b5",
    "ix_5scr_tradeplan_candidate_evaluation_v2_history": "5e73b1e4cdead8801a6de465860f1a44035245b8c16f856425ea102cb0809a01",
    "ix_5scr_tradeplan_candidate_v2_lifecycle_history": "9af3185fdc5fa943025d94f70b1ed7530e2bf63e86b6dac0417a269911afa9d1",
    "uq_5scr_tradeplan_candidate_v2_active_box": "cb363ca48466b04ba8d08a1e51b769bc029cf79766b099165ad4af9c95be0bdb",
    "uq_5scr_tradeplan_candidate_v2_active_lifecycle": "fa35fcb8a71ea8ae1eb96370036de26c97bdf03b73d4f2a8ad24411fc514f767",
}

_REQUIRED_TRIGGERS: dict[str, _TriggerContract] = {
    "trg_strategy_5scr_tradeplan_candidates_v2_guard": _TriggerContract(
        CANDIDATE_TABLE, "strategy_5scr_guard_tradeplan_candidate_v2"
    ),
    "trg_strategy_5scr_tradeplan_candidate_evaluations_v2_immutable": _TriggerContract(
        EVALUATION_TABLE, "strategy_5scr_reject_tradeplan_candidate_evaluation_v2_mutation"
    ),
}
_REQUIRED_TRIGGER_DEFINITION_HASHES: dict[str, tuple[str, str]] = {
    "trg_strategy_5scr_tradeplan_candidate_evaluations_v2_immutable": (
        "4f8f73772476530864cb1970151e4b795486911ec4972ca465b3e3c6d5f5dd36",
        "0a14ed1dae7d32f9435aeb718436c07fdfc165806925a1feb14e7a6d7b50074d",
    ),
    "trg_strategy_5scr_tradeplan_candidates_v2_guard": (
        "ddf140919f6a1679f8c09822ee84b5a958c076e9e0c4921a95c937dab30be353",
        "dd1f98e5314eb044928251923d13d05266b0b6614d4fee6b88a450a8625c99c9",
    ),
}


def _lifecycle_from_row(row: Any) -> StrategyLifecycleV2:
    opened = _row_value(row, "opened_at")
    last_event = _row_value(row, "last_event_at")
    return StrategyLifecycleV2(
        strategy_lifecycle_id=str(_row_value(row, "strategy_lifecycle_id")),
        symbol=str(_row_value(row, "symbol")),
        state=cast(Any, str(_row_value(row, "state"))),
        direction_state=cast(Any, str(_row_value(row, "direction_state"))),
        opened_at_utc=opened,
        last_event_at_utc=last_event,
        last_continuity_event_at_utc=_row_value(row, "last_continuity_event_at"),
        last_material_event_at_utc=_row_value(row, "last_material_event_at"),
        material_state_hash=str(_row_value(row, "material_state_hash")),
        event_count=int(_row_value(row, "event_count")),
        clean_block_count=int(_row_value(row, "clean_block_count")),
        watch_count=int(_row_value(row, "watch_count")),
        execution_authority=cast(Any, bool(_row_value(row, "execution_authority"))),
    )


def _candidate_from_row(row: Any) -> TradePlanCandidateV2:
    payload = _json(_row_value(row, "payload"))
    if not isinstance(payload, Mapping):
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_PAYLOAD_INVALID")
    merged = dict(payload)
    merged["lifecycle_state"] = str(_row_value(row, "lifecycle_state"))
    try:
        candidate = TradePlanCandidateV2.model_validate(merged)
        target = StructuralTargetAuthorityV1.model_validate(_json(_row_value(row, "target_authority_payload")))
        stop = StructuralStopAuthorityV1.model_validate(_json(_row_value(row, "stop_authority_payload")))
    except ValidationError as exc:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_PAYLOAD_INVALID") from exc
    expected: dict[str, Any] = {
        "tradeplan_id": candidate.tradeplan_id,
        "strategy_lifecycle_id": candidate.strategy_lifecycle_id,
        "context_epoch_id": candidate.context_epoch_id,
        "strategy_thesis_id": candidate.strategy_thesis_id,
        "execution_box_id": candidate.execution_box_id,
        "candidate_sequence": candidate.candidate_sequence,
        "candidate_revision": candidate.candidate_revision,
        "previous_tradeplan_id": candidate.previous_tradeplan_id,
        "symbol": candidate.symbol,
        "strategy_direction": candidate.direction,
        "route_type": candidate.route_type,
        "candidate_price": candidate.candidate_price,
        "stop_loss": candidate.stop_authority.structural_stop_price,
        "target_price": candidate.target_authority.target_price,
        # Persisted price distances are exact tick-grid geometry.  Do not
        # recover them through pips division/multiplication, which can create
        # a repeating Decimal even though both price endpoints are exact.
        "risk_distance_price": abs(candidate.candidate_price - candidate.stop_authority.structural_stop_price),
        "target_distance_price": abs(candidate.target_authority.target_price - candidate.candidate_price),
        "rr": candidate.gross_rr,
        "pip_size": candidate.broker_pip_size,
        "target_mode": candidate.target_authority.target_kind,
        "material_box_hash": candidate.execution_box_material_hash,
        "material_context_hash": candidate.material_context_hash,
        "thesis_semantic_identity_hash": candidate.thesis_semantic_identity_hash,
        "box_sequence": candidate.box_sequence,
        "box_version": candidate.box_version,
        "execution_box_freeze_authority_hash": candidate.execution_box_freeze_authority_hash,
        "structural_target_authority_hash": candidate.target_authority.authority_hash,
        "structural_target_material_hash": candidate.target_authority.material_target_hash,
        "target_map_authority_hash": candidate.target_map_authority_hash,
        "structural_stop_authority_hash": candidate.stop_authority.authority_hash,
        "broker_authority_hash": candidate.broker_authority_hash,
        "broker_geometry_material_hash": candidate.broker_geometry_material_hash,
        "broker_digits": candidate.broker_digits,
        "broker_point": candidate.broker_point,
        "broker_tick_size": candidate.broker_tick_size,
        "broker_pip_size": candidate.broker_pip_size,
        "broker_spread_price": candidate.broker_spread_price,
        "material_candidate_hash": candidate.material_candidate_hash,
        "formation_evidence_hash": candidate.evidence_hash,
        "opened_at": candidate.decision_at_utc,
        "rule_version": candidate.rule_version,
        "valid_for_execution": candidate.valid_for_execution,
        "execution_authority": candidate.execution_authority,
        "next_required_stage": candidate.next_required_stage,
        "candidate_status": "TRADEPLAN_CANDIDATE",
        "previous_candidate_sequence": (
            candidate.candidate_sequence - 1 if candidate.previous_tradeplan_id is not None else None
        ),
        "previous_candidate_revision": 1 if candidate.previous_tradeplan_id is not None else None,
    }
    for column, value in expected.items():
        actual = _row_value(row, column)
        if isinstance(value, Decimal):
            if Decimal(str(actual)) != value:
                raise TradePlanCandidateV2IntegrityError(f"TRADEPLAN_CANDIDATE_DURABLE_DRIFT:{column}")
        elif actual != value:
            raise TradePlanCandidateV2IntegrityError(f"TRADEPLAN_CANDIDATE_DURABLE_DRIFT:{column}")
    if candidate.target_authority != target or candidate.stop_authority != stop:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_AUTHORITY_PAYLOAD_DRIFT")
    evidence_payload = _json(_row_value(row, "evidence_payload"))
    try:
        formation_evidence = TradePlanCandidateBuildEvidenceV2.model_validate(evidence_payload)
    except ValidationError as exc:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_EVIDENCE_PAYLOAD_INVALID") from exc
    formation_evidence_hash = canonical_hash_v1(
        formation_evidence.model_dump(mode="json", exclude={"source_deployment_id", "source_replica_id"})
    )
    if formation_evidence_hash != candidate.evidence_hash:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_FORMATION_EVIDENCE_HASH_DRIFT")
    expected_source_ids = tuple(
        item.candle_evidence_id
        for item in (
            *formation_evidence.target_map_evidence.h4_candles,
            *formation_evidence.target_map_evidence.h1_consumption_candles,
            formation_evidence.target_map_evidence.selection_anchor,
        )
    )
    if tuple(_json(_row_value(row, "source_candle_ids"))) != expected_source_ids:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_SOURCE_CANDLE_DRIFT")
    if (
        formation_evidence.target_map_evidence.strategy_lifecycle_id != candidate.strategy_lifecycle_id
        or formation_evidence.target_map_evidence.context_epoch_id != candidate.context_epoch_id
        or formation_evidence.target_map_evidence.strategy_thesis_id != candidate.strategy_thesis_id
        or formation_evidence.target_map_evidence.execution_box_id != candidate.execution_box_id
        or formation_evidence.target_map_evidence.material_context_hash != candidate.material_context_hash
        or formation_evidence.target_map_evidence.thesis_semantic_identity_hash
        != candidate.thesis_semantic_identity_hash
        or formation_evidence.target_map_evidence.execution_box_material_hash != candidate.execution_box_material_hash
        or formation_evidence.target_map_evidence.symbol != candidate.symbol
        or formation_evidence.target_map_evidence.direction != candidate.direction
        or formation_evidence.broker_geometry.authority_hash != candidate.broker_authority_hash
        or broker_geometry_material_hash_v1(formation_evidence.broker_geometry)
        != candidate.broker_geometry_material_hash
    ):
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_EVIDENCE_SCOPE_DRIFT")
    try:
        formation_map = derive_structural_target_map_v1(formation_evidence.target_map_evidence)
    except ValueError as exc:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_TARGET_MAP_INVALID") from exc
    if (
        formation_map.authority_hash != candidate.target_map_authority_hash
        or select_nearest_structural_target_v1(formation_map) != candidate.target_authority
    ):
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_TARGET_MAP_DRIFT")
    raw_lifecycle_state = payload.get("lifecycle_state")
    state = str(_row_value(row, "lifecycle_state"))
    clocks = {
        "SUPERSEDED": _row_value(row, "superseded_at"),
        "INVALIDATED": _row_value(row, "invalidated_at"),
        "EXPIRED": _row_value(row, "expired_at"),
    }
    state_version = int(_row_value(row, "state_version"))
    if raw_lifecycle_state != "ACTIVE" or (
        state == "ACTIVE" and (any(value is not None for value in clocks.values()) or state_version != 1)
    ):
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_LIFECYCLE_DRIFT")
    if state != "ACTIVE":
        matching = clocks.get(state)
        if (
            not isinstance(matching, datetime)
            or matching < candidate.decision_at_utc
            or sum(value is not None for value in clocks.values()) != 1
            or state_version != 2
        ):
            raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_LIFECYCLE_DRIFT")
    if bool(_row_value(row, "valid_for_execution")) or bool(_row_value(row, "execution_authority")):
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_AUTHORITY_DRIFT")
    return candidate


def _evaluation_from_row(row: Any) -> TradePlanEvaluationV2:
    payload = _json(_row_value(row, "evidence_payload"))
    if not isinstance(payload, Mapping) or set(payload) != {"evaluation", "build_evidence"}:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_PAYLOAD_INVALID")
    try:
        evaluation = TradePlanEvaluationV2.model_validate(payload["evaluation"])
        build_evidence = TradePlanCandidateBuildEvidenceV2.model_validate(payload["build_evidence"])
    except ValidationError as exc:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_PAYLOAD_INVALID") from exc
    evidence_hash = canonical_hash_v1(
        build_evidence.model_dump(mode="json", exclude={"source_deployment_id", "source_replica_id"})
    )
    target_evidence = build_evidence.target_map_evidence
    build_scope = (
        build_evidence.source_request_id,
        build_evidence.decision_at_utc,
        target_evidence.strategy_lifecycle_id,
        target_evidence.context_epoch_id,
        target_evidence.strategy_thesis_id,
        target_evidence.execution_box_id,
        target_evidence.material_context_hash,
        target_evidence.thesis_semantic_identity_hash,
        target_evidence.execution_box_material_hash,
        target_evidence.symbol,
        target_evidence.direction,
    )
    evaluation_scope = (
        evaluation.source_request_id,
        evaluation.decision_at_utc,
        evaluation.strategy_lifecycle_id,
        evaluation.context_epoch_id,
        evaluation.strategy_thesis_id,
        evaluation.execution_box_id,
        evaluation.material_context_hash,
        evaluation.thesis_semantic_identity_hash,
        evaluation.execution_box_material_hash,
        evaluation.symbol,
        evaluation.direction,
    )
    if evidence_hash != evaluation.evidence_hash or build_scope != evaluation_scope:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_BUILD_EVIDENCE_DRIFT")
    expected_evaluation_id = (
        "5scr-tradeplan-eval:"
        + hashlib.sha256(
            (
                f"{evaluation.strategy_lifecycle_id}|{evaluation.evaluation_sequence}|"
                f"{evaluation.evidence_hash}|{evaluation.decision}|{'|'.join(evaluation.reason_codes)}"
            ).encode()
        ).hexdigest()[:32]
    )
    if evaluation.evaluation_id != expected_evaluation_id:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_IDENTITY_DRIFT")
    target_payload = _json(_row_value(row, "target_authority_payload"))
    stop_payload = _json(_row_value(row, "stop_authority_payload"))
    if evaluation.decision == "CANDIDATE":
        try:
            durable_target_map = StructuralTargetMapAuthorityV1.model_validate(target_payload)
            durable_stop = StructuralStopAuthorityV1.model_validate(stop_payload)
            rebuilt_target_map = derive_structural_target_map_v1(target_evidence)
        except (ValidationError, ValueError) as exc:
            raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_AUTHORITY_PAYLOAD_INVALID") from exc
        if (
            durable_target_map != rebuilt_target_map
            or durable_stop.execution_box_id != evaluation.execution_box_id
            or durable_stop.direction != evaluation.direction
        ):
            raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_AUTHORITY_PAYLOAD_DRIFT")
    elif target_payload != {} or stop_payload != {}:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_AUTHORITY_PAYLOAD_DRIFT")

    material_sentinel = "sha256:" + "0" * 64
    material_reason = evaluation.reason_codes[0]
    expected_material_hash: str | None = None
    if evaluation.decision == "WAIT" or material_reason == "NO_TRADE_PARENT_AUTHORITY_INVALID":
        expected_material_hash = material_sentinel
    elif evaluation.decision == "NO_TRADE":
        broker = build_evidence.broker_geometry
        broker_is_current = (
            broker.symbol == target_evidence.symbol
            and broker.captured_at_utc <= evaluation.decision_at_utc <= broker.valid_until_utc
        )
        if material_reason == "NO_TRADE_BROKER_CONSTRAINT" and not broker_is_current:
            expected_material_hash = material_sentinel
        else:
            try:
                expected_material_hash = derive_structural_target_map_v1(target_evidence).authority_hash
            except ValueError as exc:
                raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_MATERIAL_AUTHORITY_INVALID") from exc
    if expected_material_hash is not None and evaluation.material_evaluation_hash != expected_material_hash:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_MATERIAL_HASH_DRIFT")
    expected = {
        "evaluation_id": evaluation.evaluation_id,
        "strategy_lifecycle_id": evaluation.strategy_lifecycle_id,
        "context_epoch_id": evaluation.context_epoch_id,
        "strategy_thesis_id": evaluation.strategy_thesis_id,
        "execution_box_id": evaluation.execution_box_id,
        "symbol": evaluation.symbol,
        "strategy_direction": evaluation.direction,
        "material_context_hash": evaluation.material_context_hash,
        "thesis_semantic_identity_hash": evaluation.thesis_semantic_identity_hash,
        "material_box_hash": evaluation.execution_box_material_hash,
        "execution_box_freeze_authority_hash": evaluation.execution_box_freeze_authority_hash,
        "evaluation_sequence": evaluation.evaluation_sequence,
        "evaluated_at": evaluation.decision_at_utc,
        "source_request_id": evaluation.source_request_id,
        "decision": evaluation.decision,
        "material_evaluation_hash": evaluation.material_evaluation_hash,
        "evidence_hash": evaluation.evidence_hash,
        "rule_version": evaluation.rule_version,
        "tradeplan_id": evaluation.result_tradeplan_id,
    }
    for column, value in expected.items():
        if _row_value(row, column) != value:
            raise TradePlanCandidateV2IntegrityError(f"TRADEPLAN_EVALUATION_DURABLE_DRIFT:{column}")
    if str(_row_value(row, "reason_code")) != evaluation.reason_codes[0]:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_DURABLE_DRIFT:reason_code")
    if tuple(_json(_row_value(row, "reason_codes"))) != evaluation.reason_codes:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_DURABLE_DRIFT:reason_codes")
    if bool(_row_value(row, "valid_for_execution")) or bool(_row_value(row, "execution_authority")):
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_AUTHORITY_DRIFT")
    return evaluation


async def _validate_candidate_formation_evaluation(connection: Any, candidate: TradePlanCandidateV2) -> None:
    """Bind a candidate occurrence to its immutable originating evaluation."""

    # Candidate/parent rows define the repository lock order.  Evaluations are
    # append-only under a database mutation-rejection trigger, so reading them
    # must never acquire a row lock that can precede a candidate lock.
    rows = await connection.fetch(
        f"SELECT * FROM {EVALUATION_TABLE} WHERE tradeplan_id=$1 "
        "AND decision='CANDIDATE' AND reason_code='TRADEPLAN_CANDIDATE_CREATED'",
        candidate.tradeplan_id,
    )
    if len(rows) != 1:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_FORMATION_EVALUATION_MISSING")
    row = rows[0]
    evaluation = _evaluation_from_row(row)
    expected = (
        candidate.tradeplan_id,
        candidate.strategy_lifecycle_id,
        candidate.context_epoch_id,
        candidate.strategy_thesis_id,
        candidate.execution_box_id,
        candidate.symbol,
        candidate.direction,
        candidate.material_context_hash,
        candidate.thesis_semantic_identity_hash,
        candidate.execution_box_material_hash,
        candidate.execution_box_freeze_authority_hash,
        candidate.candidate_sequence,
        candidate.candidate_revision,
        candidate.material_candidate_hash,
        candidate.evidence_hash,
        candidate.decision_at_utc,
    )
    actual = (
        evaluation.result_tradeplan_id,
        evaluation.strategy_lifecycle_id,
        evaluation.context_epoch_id,
        evaluation.strategy_thesis_id,
        evaluation.execution_box_id,
        evaluation.symbol,
        evaluation.direction,
        evaluation.material_context_hash,
        evaluation.thesis_semantic_identity_hash,
        evaluation.execution_box_material_hash,
        evaluation.execution_box_freeze_authority_hash,
        _row_value(row, "candidate_sequence"),
        _row_value(row, "candidate_revision"),
        evaluation.material_evaluation_hash,
        evaluation.evidence_hash,
        evaluation.decision_at_utc,
    )
    if actual != expected:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_FORMATION_EVALUATION_DRIFT")
    try:
        target_map = StructuralTargetMapAuthorityV1.model_validate(_json(_row_value(row, "target_authority_payload")))
        stop = StructuralStopAuthorityV1.model_validate(_json(_row_value(row, "stop_authority_payload")))
    except ValidationError as exc:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_FORMATION_AUTHORITY_INVALID") from exc
    selected_target = select_nearest_structural_target_v1(target_map)
    if (
        selected_target is None
        or selected_target.material_target_hash != candidate.target_authority.material_target_hash
        or stop != candidate.stop_authority
    ):
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_FORMATION_AUTHORITY_DRIFT")


async def _validate_candidate_predecessor_chain(connection: Any, candidate: TradePlanCandidateV2) -> None:
    """Validate every immutable occurrence and its formation back to sequence one."""

    current = candidate
    seen: set[str] = set()
    while True:
        await _validate_candidate_formation_evaluation(connection, current)
        if current.candidate_sequence == 1:
            break
        if current.tradeplan_id in seen or current.previous_tradeplan_id is None:
            raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_PREDECESSOR_CYCLE")
        seen.add(current.tradeplan_id)
        row = await connection.fetchrow(
            f"SELECT * FROM {CANDIDATE_TABLE} WHERE tradeplan_id=$1 FOR UPDATE",
            current.previous_tradeplan_id,
        )
        if row is None:
            raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_PREDECESSOR_MISSING")
        previous = _candidate_from_row(row)
        if (
            previous.strategy_lifecycle_id != current.strategy_lifecycle_id
            or previous.context_epoch_id != current.context_epoch_id
            or previous.strategy_thesis_id != current.strategy_thesis_id
            or previous.execution_box_id != current.execution_box_id
            or previous.material_context_hash != current.material_context_hash
            or previous.thesis_semantic_identity_hash != current.thesis_semantic_identity_hash
            or previous.symbol != current.symbol
            or previous.direction != current.direction
            or previous.candidate_sequence != current.candidate_sequence - 1
            or previous.candidate_revision != 1
            or previous.lifecycle_state != "SUPERSEDED"
        ):
            raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_PREDECESSOR_SCOPE_DRIFT")
        current = previous
    if current.previous_tradeplan_id is not None:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_PREDECESSOR_SCOPE_DRIFT")


async def _candidate_for_evaluation(
    connection: Any,
    row: Any,
    evaluation: TradePlanEvaluationV2,
) -> TradePlanCandidateV2 | None:
    """Reconstruct and bind an evaluation's optional durable candidate result."""

    candidate_link_columns = (
        "candidate_sequence",
        "candidate_revision",
        "material_candidate_hash",
    )
    if evaluation.result_tradeplan_id is None:
        if any(_row_value(row, field) is not None for field in candidate_link_columns):
            raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_CANDIDATE_LINK_DRIFT")
        return None

    candidate_row = await connection.fetchrow(
        f"SELECT * FROM {CANDIDATE_TABLE} WHERE tradeplan_id=$1 FOR UPDATE",
        evaluation.result_tradeplan_id,
    )
    if candidate_row is None:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_CANDIDATE_MISSING")
    candidate = _candidate_from_row(candidate_row)
    await _validate_candidate_predecessor_chain(connection, candidate)
    expected_link = (
        candidate.tradeplan_id,
        candidate.strategy_lifecycle_id,
        candidate.context_epoch_id,
        candidate.strategy_thesis_id,
        candidate.execution_box_id,
        candidate.symbol,
        candidate.direction,
        candidate.material_context_hash,
        candidate.thesis_semantic_identity_hash,
        candidate.execution_box_material_hash,
        candidate.execution_box_freeze_authority_hash,
        candidate.candidate_sequence,
        candidate.candidate_revision,
        candidate.material_candidate_hash,
    )
    actual_link = (
        _row_value(row, "tradeplan_id"),
        evaluation.strategy_lifecycle_id,
        evaluation.context_epoch_id,
        evaluation.strategy_thesis_id,
        evaluation.execution_box_id,
        evaluation.symbol,
        evaluation.direction,
        evaluation.material_context_hash,
        evaluation.thesis_semantic_identity_hash,
        evaluation.execution_box_material_hash,
        evaluation.execution_box_freeze_authority_hash,
        _row_value(row, "candidate_sequence"),
        _row_value(row, "candidate_revision"),
        _row_value(row, "material_candidate_hash"),
    )
    if actual_link != expected_link:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_CANDIDATE_LINK_DRIFT")

    try:
        target_map = StructuralTargetMapAuthorityV1.model_validate(_json(_row_value(row, "target_authority_payload")))
        stop = StructuralStopAuthorityV1.model_validate(_json(_row_value(row, "stop_authority_payload")))
    except ValidationError as exc:
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_AUTHORITY_PAYLOAD_INVALID") from exc
    selected_target = select_nearest_structural_target_v1(target_map)
    if (
        selected_target is None
        or selected_target.material_target_hash != candidate.target_authority.material_target_hash
        or stop != candidate.stop_authority
        or evaluation.material_evaluation_hash != candidate.material_candidate_hash
    ):
        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_CANDIDATE_AUTHORITY_LINK_DRIFT")
    return candidate


TradePlanCandidateV2PersistenceStatus = Literal[
    "PERSISTED",
    "DUPLICATE",
    "WAIT",
    "NO_TRADE",
    "QUARANTINED",
    "INVALIDATED",
    "SUPERSEDED",
    "EXPIRED",
    "REJECTED",
]


@dataclass(frozen=True)
class TradePlanCandidateV2PersistenceResult:
    status: TradePlanCandidateV2PersistenceStatus
    reason_code: str
    evaluation: TradePlanEvaluationV2 | None = None
    candidate: TradePlanCandidateV2 | None = None
    previous_candidate: TradePlanCandidateV2 | None = None


class Strategy5SCRTradePlanCandidateV2Repository:
    """Persist P6 candidate occurrences under the canonical lifecycle lock."""

    def __init__(
        self,
        pg: PostgresClient | None = None,
        *,
        observer_export_repository: ObserverExportOutboxRepository | None = None,
    ) -> None:
        self._pg = pg or pg_client
        self._observer_export = observer_export_repository
        if pg is None and observer_export_repository is None:
            self._observer_export = ObserverExportOutboxRepository(pg=self._pg)

    async def schema_status(self) -> TradePlanCandidateV2SchemaStatus:
        if not self._pg.is_available:
            return TradePlanCandidateV2SchemaStatus(
                missing_tables=tuple(sorted(_REQUIRED_TABLES)),
                invalid_tables=(),
                missing_columns=tuple(sorted(f"{table}.{column}" for table, column in _REQUIRED_COLUMNS)),
                invalid_columns=(),
                missing_constraints=tuple(sorted(_REQUIRED_CONSTRAINTS)),
                invalid_constraints=(),
                missing_indexes=tuple(sorted(_REQUIRED_INDEXES)),
                invalid_indexes=(),
                missing_triggers=tuple(sorted(_REQUIRED_TRIGGERS)),
                invalid_triggers=(),
            )
        table_rows = await self._pg.fetch(
            """SELECT cls.relname AS tablename,cls.relkind::text AS relkind,
                      cls.relpersistence::text AS relpersistence,cls.relispartition
               FROM pg_catalog.pg_class cls
               JOIN pg_catalog.pg_namespace ns ON ns.oid=cls.relnamespace
               WHERE ns.nspname=current_schema() AND cls.relname=ANY($1::text[])""",
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
                   ARRAY(SELECT attr.attname FROM unnest(idx.indkey) WITH ORDINALITY key(attnum,pos)
                         JOIN pg_catalog.pg_attribute attr
                           ON attr.attrelid=idx.indrelid AND attr.attnum=key.attnum
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
        table_map = {str(_row_value(row, "tablename")): row for row in table_rows}
        present_tables = set(table_map)
        invalid_tables = tuple(
            sorted(
                table
                for table in _REQUIRED_TABLES
                if (row := table_map.get(table)) is not None
                and (
                    str(_row_value(row, "relkind")) != "r"
                    or str(_row_value(row, "relpersistence")) != "p"
                    or bool(_row_value(row, "relispartition"))
                )
            )
        )
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
            expected_value = (expected.data_type, expected.nullable, expected.max_length, expected.default)
            if actual == expected_value:
                satisfied_columns.add(label)
            else:
                invalid_columns.append(label)
        constraint_map = {str(_row_value(row, "conname")): row for row in constraint_rows}
        invalid_constraints = [
            name
            for name, expected in _REQUIRED_CONSTRAINTS.items()
            if (row := constraint_map.get(name)) is not None
            and (
                str(_row_value(row, "table_name")) != expected.table
                or str(_row_value(row, "contype")) != expected.contype
                or not bool(_row_value(row, "convalidated"))
                or _sql_fingerprint(_row_value(row, "definition")) != _REQUIRED_CONSTRAINT_DEFINITION_HASHES.get(name)
            )
        ]
        index_map = {str(_row_value(row, "index_name")): row for row in index_rows}
        invalid_indexes = [
            name
            for name, expected in _REQUIRED_INDEXES.items()
            if (row := index_map.get(name)) is not None
            and (
                str(_row_value(row, "table_name")) != expected.table
                or bool(_row_value(row, "indisunique")) != expected.unique
                or not bool(_row_value(row, "indisvalid"))
                or not bool(_row_value(row, "indisready"))
                or tuple(str(item) for item in (_row_value(row, "columns") or ())) != expected.columns
                or _sql_fingerprint(_row_value(row, "definition")) != _REQUIRED_INDEX_DEFINITION_HASHES.get(name)
            )
        ]
        trigger_map = {str(_row_value(row, "tgname")): row for row in trigger_rows}
        invalid_triggers: list[str] = []
        for name, expected in _REQUIRED_TRIGGERS.items():
            row = trigger_map.get(name)
            if row is None:
                continue
            hashes = _REQUIRED_TRIGGER_DEFINITION_HASHES.get(name)
            if (
                str(_row_value(row, "table_name")) != expected.table
                or _catalog_char(_row_value(row, "tgenabled")) != "O"
                or str(_row_value(row, "function_name")) != expected.function
                or hashes is None
                or _sql_fingerprint(_row_value(row, "trigger_definition")) != hashes[0]
                or _sql_fingerprint(_row_value(row, "function_definition")) != hashes[1]
            ):
                invalid_triggers.append(name)
        invalid_labels = set(invalid_columns)
        expected_labels = {f"{table}.{column}" for table, column in _REQUIRED_COLUMNS}
        own = TradePlanCandidateV2SchemaStatus(
            missing_tables=tuple(sorted(_REQUIRED_TABLES - present_tables)),
            invalid_tables=invalid_tables,
            missing_columns=tuple(sorted(expected_labels - satisfied_columns - invalid_labels)),
            invalid_columns=tuple(sorted(invalid_columns)),
            missing_constraints=tuple(sorted(set(_REQUIRED_CONSTRAINTS) - set(constraint_map))),
            invalid_constraints=tuple(sorted(invalid_constraints)),
            missing_indexes=tuple(sorted(set(_REQUIRED_INDEXES) - set(index_map))),
            invalid_indexes=tuple(sorted(invalid_indexes)),
            missing_triggers=tuple(sorted(set(_REQUIRED_TRIGGERS) - set(trigger_map))),
            invalid_triggers=tuple(sorted(invalid_triggers)),
        )
        parent = await Strategy5SCRExecutionBoxV1Repository(self._pg).schema_status()
        return TradePlanCandidateV2SchemaStatus(
            missing_tables=tuple(sorted((*own.missing_tables, *(f"p5:{item}" for item in parent.missing_tables)))),
            invalid_tables=own.invalid_tables,
            missing_columns=tuple(sorted((*own.missing_columns, *(f"p5:{item}" for item in parent.missing_columns)))),
            invalid_columns=tuple(sorted((*own.invalid_columns, *(f"p5:{item}" for item in parent.invalid_columns)))),
            missing_constraints=tuple(
                sorted((*own.missing_constraints, *(f"p5:{item}" for item in parent.missing_constraints)))
            ),
            invalid_constraints=tuple(
                sorted((*own.invalid_constraints, *(f"p5:{item}" for item in parent.invalid_constraints)))
            ),
            missing_indexes=tuple(sorted((*own.missing_indexes, *(f"p5:{item}" for item in parent.missing_indexes)))),
            invalid_indexes=tuple(sorted((*own.invalid_indexes, *(f"p5:{item}" for item in parent.invalid_indexes)))),
            missing_triggers=tuple(
                sorted((*own.missing_triggers, *(f"p5:{item}" for item in parent.missing_triggers)))
            ),
            invalid_triggers=tuple(
                sorted((*own.invalid_triggers, *(f"p5:{item}" for item in parent.invalid_triggers)))
            ),
        )

    async def load_active(self, execution_box_id: str) -> TradePlanCandidateV2 | None:
        async with self._pg.transaction() as connection:
            row = await connection.fetchrow(
                f"SELECT * FROM {CANDIDATE_TABLE} WHERE execution_box_id=$1 AND lifecycle_state='ACTIVE' FOR UPDATE",
                execution_box_id,
            )
            if row is None:
                return None
            candidate = _candidate_from_row(row)
            await _validate_candidate_predecessor_chain(connection, candidate)
            return candidate

    async def load_history(self, strategy_lifecycle_id: str) -> tuple[TradePlanCandidateV2, ...]:
        async with self._pg.transaction() as connection:
            rows = await connection.fetch(
                f"SELECT * FROM {CANDIDATE_TABLE} WHERE strategy_lifecycle_id=$1 "
                # Predecessor traversal always locks newest -> oldest.  Keep
                # bulk history reads in that same per-box order so they cannot
                # deadlock an active-candidate reconstruction.
                "ORDER BY execution_box_id,candidate_sequence DESC,tradeplan_id DESC FOR UPDATE",
                strategy_lifecycle_id,
            )
            candidates = tuple(_candidate_from_row(row) for row in rows)
            for candidate in candidates:
                await _validate_candidate_predecessor_chain(connection, candidate)
            # Lock acquisition is newest -> oldest, while the public history
            # contract remains deterministic chronological order.
            return tuple(
                sorted(
                    candidates,
                    key=lambda item: (item.execution_box_id, item.candidate_sequence, item.tradeplan_id),
                )
            )

    async def load_evaluations(self, execution_box_id: str) -> tuple[TradePlanEvaluationV2, ...]:
        async with self._pg.transaction() as connection:
            # Capture the append-only evaluation snapshot before taking any
            # candidate lock.  A successor committed after this statement is
            # deliberately outside this read and cannot introduce a newer
            # candidate link after the lock set has been chosen.
            rows = await connection.fetch(
                f"SELECT * FROM {EVALUATION_TABLE} WHERE execution_box_id=$1 "
                "ORDER BY evaluation_sequence,evaluation_id",
                execution_box_id,
            )
            evaluations = tuple(_evaluation_from_row(row) for row in rows)
            linked_candidate_ids = tuple(
                dict.fromkeys(
                    evaluation.result_tradeplan_id
                    for evaluation in evaluations
                    if evaluation.result_tradeplan_id is not None
                )
            )
            if linked_candidate_ids:
                # The evaluation read held no row locks.  Acquire every linked
                # candidate newest -> oldest before reconstruction; traversal
                # can now only revisit this set and its older predecessors.
                locked_rows = await connection.fetch(
                    f"SELECT tradeplan_id FROM {CANDIDATE_TABLE} "
                    "WHERE execution_box_id=$1 AND tradeplan_id=ANY($2::text[]) "
                    "ORDER BY candidate_sequence DESC,tradeplan_id DESC FOR UPDATE",
                    execution_box_id,
                    list(linked_candidate_ids),
                )
                expected_ids = set(linked_candidate_ids)
                locked_ids = {str(_row_value(row, "tradeplan_id")) for row in locked_rows}
                if locked_ids != expected_ids:
                    unresolved_ids = expected_ids - locked_ids
                    existing_rows = await connection.fetch(
                        f"SELECT tradeplan_id FROM {CANDIDATE_TABLE} WHERE tradeplan_id=ANY($1::text[])",
                        list(unresolved_ids),
                    )
                    existing_ids = {str(_row_value(row, "tradeplan_id")) for row in existing_rows}
                    if existing_ids != unresolved_ids:
                        raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_CANDIDATE_MISSING")
                    raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_CANDIDATE_SCOPE_DRIFT")
            for row, evaluation in zip(rows, evaluations, strict=True):
                await _candidate_for_evaluation(connection, row, evaluation)
            return evaluations

    @staticmethod
    def _structural_candle_from_row(row: Any) -> StructuralCandleAuthorityV1:
        source_hash = str(_row_value(row, "content_hash"))
        if not source_hash.startswith("sha256:"):
            source_hash = "sha256:" + source_hash
        return StructuralCandleAuthorityV1(
            source_content_hash=source_hash,
            canonical_row_id=int(_row_value(row, "id")),
            selected_raw_candle_id=int(_row_value(row, "selected_raw_candle_id")),
            symbol=str(_row_value(row, "symbol")).upper(),
            timeframe=cast(Any, str(_row_value(row, "timeframe")).upper()),
            open_time_utc=_row_value(row, "open_time"),
            close_time_utc=_row_value(row, "close_time"),
            open=Decimal(str(_row_value(row, "open"))),
            high=Decimal(str(_row_value(row, "high"))),
            low=Decimal(str(_row_value(row, "low"))),
            close=Decimal(str(_row_value(row, "close"))),
            provider=str(_row_value(row, "selected_provider")),
            feed=str(_row_value(row, "selected_feed")),
            provider_timestamp_semantics=cast(Any, str(_row_value(row, "provider_timestamp_semantics")).upper()),
            selection_policy=str(_row_value(row, "selection_policy")),
            selection_rank=int(_row_value(row, "selection_rank")),
        )

    async def _canonicalize_target_evidence(
        self,
        connection: Any,
        evidence: TradePlanCandidateBuildEvidenceV2,
    ) -> TradePlanCandidateBuildEvidenceV2:
        target = evidence.target_map_evidence
        # Re-select the complete canonical authority cohorts inside the same
        # transaction.  Exact row-ID validation alone is insufficient because
        # a caller could omit a nearer structural target.
        canonical_h4_rows = await connection.fetch(
            f"""
            SELECT id,symbol,timeframe,open_time,close_time,open,high,low,close,
                   complete,selected_provider,selected_feed,provider_timestamp_semantics,
                   selected_raw_candle_id,selection_policy,selection_rank,content_hash
            FROM {CANONICAL_CANDLE_TABLE}
            WHERE symbol=$1 AND timeframe='H4' AND complete=true
              AND close_time>$2 AND close_time<=$3
            ORDER BY close_time,id
            """,
            target.symbol,
            target.coverage_start_utc,
            target.coverage_end_utc,
        )
        canonical_h1_rows = await connection.fetch(
            f"""
            SELECT id,symbol,timeframe,open_time,close_time,open,high,low,close,
                   complete,selected_provider,selected_feed,provider_timestamp_semantics,
                   selected_raw_candle_id,selection_policy,selection_rank,content_hash
            FROM {CANONICAL_CANDLE_TABLE}
            WHERE symbol=$1 AND timeframe='H1' AND complete=true
              AND close_time>$2 AND close_time<=$3
            ORDER BY close_time,id
            """,
            target.symbol,
            target.h1_coverage_start_utc,
            target.h1_coverage_end_utc,
        )
        preliminary_h4 = tuple(self._structural_candle_from_row(row) for row in canonical_h4_rows)
        preliminary_h1 = tuple(self._structural_candle_from_row(row) for row in canonical_h1_rows)

        # READ COMMITTED gives every statement a new snapshot and row locks do
        # not protect absent predicate rows.  Fence canonical writes, then
        # re-read both predicates: a writer that committed between the first
        # H4/H1 reads and this fence is visible and rejected; later writers
        # wait until this transaction has persisted or rolled back.
        await connection.execute(f"LOCK TABLE {CANONICAL_CANDLE_TABLE} IN SHARE MODE")
        fenced_h4_rows = await connection.fetch(
            f"""
            SELECT id,symbol,timeframe,open_time,close_time,open,high,low,close,
                   complete,selected_provider,selected_feed,provider_timestamp_semantics,
                   selected_raw_candle_id,selection_policy,selection_rank,content_hash
            FROM {CANONICAL_CANDLE_TABLE}
            WHERE symbol=$1 AND timeframe='H4' AND complete=true
              AND close_time>$2 AND close_time<=$3
            ORDER BY close_time,id FOR SHARE
            """,
            target.symbol,
            target.coverage_start_utc,
            target.coverage_end_utc,
        )
        fenced_h1_rows = await connection.fetch(
            f"""
            SELECT id,symbol,timeframe,open_time,close_time,open,high,low,close,
                   complete,selected_provider,selected_feed,provider_timestamp_semantics,
                   selected_raw_candle_id,selection_policy,selection_rank,content_hash
            FROM {CANONICAL_CANDLE_TABLE}
            WHERE symbol=$1 AND timeframe='H1' AND complete=true
              AND close_time>$2 AND close_time<=$3
            ORDER BY close_time,id FOR SHARE
            """,
            target.symbol,
            target.h1_coverage_start_utc,
            target.h1_coverage_end_utc,
        )
        canonical_h4 = tuple(self._structural_candle_from_row(row) for row in fenced_h4_rows)
        canonical_h1 = tuple(self._structural_candle_from_row(row) for row in fenced_h1_rows)
        if preliminary_h4 != canonical_h4 or preliminary_h1 != canonical_h1:
            raise TradePlanCandidateV2IntegrityError("CANONICAL_TARGET_COHORT_CHANGED_DURING_READ")
        if canonical_h4 != target.h4_candles or canonical_h1 != target.h1_consumption_candles:
            raise TradePlanCandidateV2IntegrityError("CANONICAL_TARGET_COHORT_INCOMPLETE")
        if (
            len(canonical_h4) != target.h4_cohort_count
            or len(canonical_h1) != target.h1_cohort_count
            or not canonical_h1
            or canonical_h1[-1] != target.selection_anchor
        ):
            raise TradePlanCandidateV2IntegrityError("CANONICAL_TARGET_COHORT_COUNT_DRIFT")

        supplied = (*target.h4_candles, *target.h1_consumption_candles)
        ids = tuple(item.canonical_row_id for item in supplied)
        if len(ids) != len(set(ids)):
            raise TradePlanCandidateV2IntegrityError("CANONICAL_TARGET_CANDLE_ID_DUPLICATE")
        rows = await connection.fetch(
            f"""
            SELECT id,symbol,timeframe,open_time,close_time,open,high,low,close,
                   complete,selected_provider,selected_feed,provider_timestamp_semantics,
                   selected_raw_candle_id,selection_policy,selection_rank,content_hash
            FROM {CANONICAL_CANDLE_TABLE}
            WHERE id=ANY($1::bigint[]) ORDER BY close_time,id FOR SHARE
            """,
            list(ids),
        )
        if len(rows) != len(ids):
            raise TradePlanCandidateV2IntegrityError("CANONICAL_TARGET_CANDLE_MISSING")
        if any(not bool(_row_value(row, "complete")) for row in rows):
            raise TradePlanCandidateV2IntegrityError("CANONICAL_TARGET_CANDLE_INCOMPLETE")
        canonical_by_id = {int(_row_value(row, "id")): self._structural_candle_from_row(row) for row in rows}
        if any(canonical_by_id[item.canonical_row_id] != item for item in supplied):
            raise TradePlanCandidateV2IntegrityError("CANONICAL_TARGET_CANDLE_DRIFT")
        return evidence

    async def process_evidence(
        self,
        evidence: TradePlanCandidateBuildEvidenceV2,
    ) -> TradePlanCandidateV2PersistenceResult:
        target = evidence.target_map_evidence
        async with self._pg.transaction() as connection:
            lifecycle_row = await connection.fetchrow(
                f"SELECT * FROM {LIFECYCLE_TABLE} WHERE strategy_lifecycle_id=$1 FOR UPDATE",
                target.strategy_lifecycle_id,
            )
            if lifecycle_row is None:
                return TradePlanCandidateV2PersistenceResult("REJECTED", "CANONICAL_LIFECYCLE_MISSING")
            lifecycle = _lifecycle_from_row(lifecycle_row)
            active_row = await connection.fetchrow(
                f"SELECT * FROM {CANDIDATE_TABLE} WHERE strategy_lifecycle_id=$1 "
                "AND lifecycle_state='ACTIVE' FOR UPDATE",
                lifecycle.strategy_lifecycle_id,
            )
            active = None if active_row is None else _candidate_from_row(active_row)
            if active is not None:
                await _validate_candidate_predecessor_chain(connection, active)

            # Parent terminality wins over a stale/bogus incoming context,
            # thesis, box, candle ID, or broker snapshot.
            if lifecycle.state in TERMINAL_LIFECYCLE_STATES:
                if active is None:
                    return TradePlanCandidateV2PersistenceResult("REJECTED", "TRADEPLAN_PARENT_NOT_ACTIVE")
                closed = await self._close_candidate(
                    connection,
                    active,
                    state="INVALIDATED",
                    occurred_at=_terminal_clock(lifecycle.last_event_at_utc, floor=active.decision_at_utc),
                )
                return TradePlanCandidateV2PersistenceResult(
                    "INVALIDATED", "TRADEPLAN_PARENT_NOT_ACTIVE", candidate=closed
                )
            if lifecycle.symbol != target.symbol:
                return TradePlanCandidateV2PersistenceResult("REJECTED", "CANONICAL_LIFECYCLE_SCOPE_MISMATCH")

            # Reconcile an existing candidate against *its own* durable parent
            # chain before looking at caller-selected context/thesis/box IDs.
            # Otherwise a bogus new request could strand a candidate whose P3,
            # P4, or P5 parent has already closed.
            if active is not None:
                active_context_row = await connection.fetchrow(
                    f"SELECT * FROM {CONTEXT_TABLE} WHERE context_epoch_id=$1 AND strategy_lifecycle_id=$2 FOR UPDATE",
                    active.context_epoch_id,
                    active.strategy_lifecycle_id,
                )
                active_thesis_row = await connection.fetchrow(
                    f"SELECT * FROM {THESIS_TABLE} WHERE strategy_thesis_id=$1 FOR UPDATE",
                    active.strategy_thesis_id,
                )
                active_box_row = await connection.fetchrow(
                    f"SELECT * FROM {BOX_TABLE} WHERE execution_box_id=$1 FOR UPDATE",
                    active.execution_box_id,
                )
                if active_context_row is None or active_thesis_row is None or active_box_row is None:
                    raise TradePlanCandidateV2IntegrityError("TRADEPLAN_ACTIVE_PARENT_MISSING")
                try:
                    active_context = _context_from_row(active_context_row)
                    active_thesis = _p4_thesis_from_row(active_thesis_row)
                    await Strategy5SCRDirectionalThesisV1Repository._validate_thesis_proof_chain(
                        connection, active_thesis
                    )
                    active_box = _box_from_row(active_box_row)
                    await _validate_predecessor_chain(connection, active_box)
                except RuntimeError as exc:
                    raise TradePlanCandidateV2IntegrityError("TRADEPLAN_ACTIVE_PARENT_INTEGRITY_DRIFT") from exc
                active_parent_scope = (
                    active_context.strategy_lifecycle_id,
                    active_thesis.strategy_lifecycle_id,
                    active_box.strategy_lifecycle_id,
                    active_context.context_epoch_id,
                    active_thesis.context_epoch_id,
                    active_box.context_epoch_id,
                    active_thesis.strategy_thesis_id,
                    active_box.strategy_thesis_id,
                    active_context.material_context_hash,
                    active_thesis.semantic_identity_hash,
                    active_box.material_box_hash,
                    active_box.freeze_authority_hash,
                    active_context.symbol,
                    active_thesis.symbol,
                    active_box.symbol,
                    active_thesis.strategy_direction,
                    active_box.strategy_direction,
                )
                expected_active_scope = (
                    active.strategy_lifecycle_id,
                    active.strategy_lifecycle_id,
                    active.strategy_lifecycle_id,
                    active.context_epoch_id,
                    active.context_epoch_id,
                    active.context_epoch_id,
                    active.strategy_thesis_id,
                    active.strategy_thesis_id,
                    active.material_context_hash,
                    active.thesis_semantic_identity_hash,
                    active.execution_box_material_hash,
                    active.execution_box_freeze_authority_hash,
                    active.symbol,
                    active.symbol,
                    active.symbol,
                    active.direction,
                    active.direction,
                )
                if active_parent_scope != expected_active_scope:
                    raise TradePlanCandidateV2IntegrityError("TRADEPLAN_ACTIVE_PARENT_SCOPE_DRIFT")
                if active_context.state != "ACTIVE" or active_thesis.state != "ACTIVE" or active_box.state != "FROZEN":
                    closed = await self._close_candidate(
                        connection,
                        active,
                        state="INVALIDATED",
                        occurred_at=_terminal_clock(
                            active_context.closed_at_utc,
                            active_thesis.closed_at_utc,
                            active_box.superseded_at_utc,
                            active_box.invalidated_at_utc,
                            active_box.consumed_at_utc,
                            active_box.expired_at_utc,
                            floor=active.decision_at_utc,
                        ),
                    )
                    return TradePlanCandidateV2PersistenceResult(
                        "INVALIDATED", "TRADEPLAN_PARENT_NOT_ACTIVE", candidate=closed
                    )

            context_row = await connection.fetchrow(
                f"SELECT * FROM {CONTEXT_TABLE} WHERE context_epoch_id=$1 AND strategy_lifecycle_id=$2 FOR UPDATE",
                target.context_epoch_id,
                lifecycle.strategy_lifecycle_id,
            )
            if context_row is None:
                return TradePlanCandidateV2PersistenceResult("REJECTED", "CONTEXT_EPOCH_MISSING")
            try:
                context = _context_from_row(context_row)
            except RuntimeError as exc:
                raise TradePlanCandidateV2IntegrityError("CONTEXT_EPOCH_DURABLE_INTEGRITY_DRIFT") from exc
            thesis_row = await connection.fetchrow(
                f"SELECT * FROM {THESIS_TABLE} WHERE strategy_thesis_id=$1 FOR UPDATE",
                target.strategy_thesis_id,
            )
            if thesis_row is None:
                return TradePlanCandidateV2PersistenceResult("REJECTED", "DIRECTIONAL_THESIS_MISSING")
            try:
                thesis = _p4_thesis_from_row(thesis_row)
                await Strategy5SCRDirectionalThesisV1Repository._validate_thesis_proof_chain(connection, thesis)
            except RuntimeError as exc:
                raise TradePlanCandidateV2IntegrityError("DIRECTIONAL_THESIS_DURABLE_INTEGRITY_DRIFT") from exc
            box_row = await connection.fetchrow(
                f"SELECT * FROM {BOX_TABLE} WHERE execution_box_id=$1 FOR UPDATE",
                target.execution_box_id,
            )
            if box_row is None:
                return TradePlanCandidateV2PersistenceResult("REJECTED", "EXECUTION_BOX_MISSING")
            try:
                box = _box_from_row(box_row)
                await _validate_predecessor_chain(connection, box)
            except RuntimeError as exc:
                raise TradePlanCandidateV2IntegrityError("EXECUTION_BOX_DURABLE_INTEGRITY_DRIFT") from exc

            parent_scope_open = (
                context.state == "ACTIVE" and thesis.state == "ACTIVE" and box.state in {"BUILDING", "FROZEN"}
            )
            parent_scope = (
                context.strategy_lifecycle_id,
                thesis.strategy_lifecycle_id,
                box.strategy_lifecycle_id,
                context.context_epoch_id,
                thesis.context_epoch_id,
                box.context_epoch_id,
                thesis.strategy_thesis_id,
                box.strategy_thesis_id,
                lifecycle.symbol,
                context.symbol,
                thesis.symbol,
                box.symbol,
                thesis.strategy_direction,
                box.strategy_direction,
            )
            expected_scope = (
                lifecycle.strategy_lifecycle_id,
                lifecycle.strategy_lifecycle_id,
                lifecycle.strategy_lifecycle_id,
                target.context_epoch_id,
                target.context_epoch_id,
                target.context_epoch_id,
                target.strategy_thesis_id,
                target.strategy_thesis_id,
                target.symbol,
                target.symbol,
                target.symbol,
                target.symbol,
                target.direction,
                target.direction,
            )
            if parent_scope != expected_scope:
                return TradePlanCandidateV2PersistenceResult("REJECTED", "TRADEPLAN_PARENT_SCOPE_MISMATCH")
            if not parent_scope_open:
                if active is None:
                    return TradePlanCandidateV2PersistenceResult("REJECTED", "TRADEPLAN_PARENT_NOT_ACTIVE")
                closed_at = _terminal_clock(
                    context.closed_at_utc,
                    thesis.closed_at_utc,
                    box.superseded_at_utc,
                    box.invalidated_at_utc,
                    box.consumed_at_utc,
                    box.expired_at_utc,
                    floor=active.decision_at_utc,
                )
                closed = await self._close_candidate(connection, active, state="INVALIDATED", occurred_at=closed_at)
                return TradePlanCandidateV2PersistenceResult(
                    "INVALIDATED", "TRADEPLAN_PARENT_NOT_ACTIVE", candidate=closed
                )
            if box.state == "FROZEN" and box.freeze_authority_hash is None:
                raise TradePlanCandidateV2IntegrityError("EXECUTION_BOX_FREEZE_AUTHORITY_MISSING")

            prior_eval = await connection.fetchrow(
                f"SELECT * FROM {EVALUATION_TABLE} WHERE execution_box_id=$1 "
                "AND (source_request_id=$2 OR evaluated_at=$3)",
                box.execution_box_id,
                evidence.source_request_id,
                evidence.decision_at_utc,
            )
            incoming_hash = canonical_hash_v1(
                evidence.model_dump(mode="json", exclude={"source_deployment_id", "source_replica_id"})
            )
            if prior_eval is not None:
                prior = _evaluation_from_row(prior_eval)
                if prior.evidence_hash != incoming_hash:
                    return TradePlanCandidateV2PersistenceResult(
                        "QUARANTINED", "TRADEPLAN_REQUEST_EVIDENCE_DRIFT", candidate=active
                    )
                prior_candidate = await _candidate_for_evaluation(connection, prior_eval, prior)
                return TradePlanCandidateV2PersistenceResult(
                    "DUPLICATE",
                    "TRADEPLAN_EVALUATION_ALREADY_PERSISTED",
                    evaluation=prior,
                    candidate=prior_candidate if prior_candidate is not None else active,
                )
            try:
                evidence = await self._canonicalize_target_evidence(connection, evidence)
            except TradePlanCandidateV2IntegrityError as exc:
                return TradePlanCandidateV2PersistenceResult("QUARANTINED", str(exc), candidate=active)
            evaluation_sequence = int(
                await connection.fetchval(
                    f"SELECT COALESCE(MAX(evaluation_sequence),0)+1 FROM {EVALUATION_TABLE} WHERE execution_box_id=$1",
                    box.execution_box_id,
                )
            )
            candidate_sequence = int(
                await connection.fetchval(
                    f"SELECT COALESCE(MAX(candidate_sequence),0)+1 FROM {CANDIDATE_TABLE} WHERE execution_box_id=$1",
                    box.execution_box_id,
                )
            )
            reduced = solve_tradeplan_candidate_v2(
                lifecycle=lifecycle,
                context=context,
                thesis=thesis,
                execution_box=box,
                evidence=evidence,
                evaluation_sequence=evaluation_sequence,
                candidate_sequence=candidate_sequence,
                current_candidate=active,
            )
            if reduced.decision == "QUARANTINED":
                return TradePlanCandidateV2PersistenceResult("QUARANTINED", reduced.reason_code, candidate=active)
            if reduced.decision == "DUPLICATE":
                if reduced.evaluation is None:
                    raise TradePlanCandidateV2IntegrityError("TRADEPLAN_REDUCTION_EVALUATION_MISSING")
                await self._insert_evaluation(connection, reduced.evaluation, evidence, reduced)
                return TradePlanCandidateV2PersistenceResult(
                    "DUPLICATE",
                    reduced.reason_code,
                    evaluation=reduced.evaluation,
                    candidate=active,
                )
            if reduced.decision == "CANDIDATE":
                if reduced.candidate is None:
                    raise TradePlanCandidateV2IntegrityError("TRADEPLAN_REDUCTION_CANDIDATE_MISSING")
                if reduced.evaluation is None:
                    raise TradePlanCandidateV2IntegrityError("TRADEPLAN_REDUCTION_EVALUATION_MISSING")
                if reduced.previous_candidate is not None:
                    await self._close_candidate(
                        connection,
                        reduced.previous_candidate,
                        state="SUPERSEDED",
                        occurred_at=evidence.decision_at_utc,
                    )
                await self._insert_candidate(connection, reduced.candidate, evidence, reduced.target_map)
                await self._insert_evaluation(connection, reduced.evaluation, evidence, reduced)
                return TradePlanCandidateV2PersistenceResult(
                    "PERSISTED",
                    reduced.reason_code,
                    evaluation=reduced.evaluation,
                    candidate=reduced.candidate,
                    previous_candidate=reduced.previous_candidate,
                )
            if reduced.evaluation is None:
                raise TradePlanCandidateV2IntegrityError("TRADEPLAN_REDUCTION_EVALUATION_MISSING")
            closed_candidate = active
            if reduced.transition is not None:
                if (
                    active is None
                    or reduced.previous_candidate != active
                    or reduced.transition.tradeplan_id != active.tradeplan_id
                    or reduced.transition.from_state != "ACTIVE"
                    or reduced.transition.to_state != "INVALIDATED"
                    or reduced.transition.successor_tradeplan_id is not None
                    or reduced.transition.occurred_at_utc != evidence.decision_at_utc
                ):
                    raise TradePlanCandidateV2IntegrityError("TRADEPLAN_INVALIDATION_TRANSITION_DRIFT")
                closed_candidate = await self._close_candidate(
                    connection,
                    active,
                    state="INVALIDATED",
                    occurred_at=reduced.transition.occurred_at_utc,
                )
            await self._insert_evaluation(connection, reduced.evaluation, evidence, reduced)
            return TradePlanCandidateV2PersistenceResult(
                cast(TradePlanCandidateV2PersistenceStatus, reduced.decision),
                reduced.reason_code,
                evaluation=reduced.evaluation,
                candidate=closed_candidate,
                previous_candidate=active if reduced.transition is not None else None,
            )

    async def reconcile_terminal(
        self,
        strategy_lifecycle_id: str,
        occurred_at_utc: datetime,
        *,
        reason_code: str = "TRADEPLAN_PARENT_NOT_ACTIVE",
    ) -> TradePlanCandidateV2PersistenceResult:
        async with self._pg.transaction() as connection:
            lifecycle = await connection.fetchrow(
                f"SELECT * FROM {LIFECYCLE_TABLE} WHERE strategy_lifecycle_id=$1 FOR UPDATE",
                strategy_lifecycle_id,
            )
            if lifecycle is None:
                return TradePlanCandidateV2PersistenceResult("REJECTED", "CANONICAL_LIFECYCLE_MISSING")
            if str(_row_value(lifecycle, "state")) not in TERMINAL_LIFECYCLE_STATES:
                return TradePlanCandidateV2PersistenceResult("REJECTED", "LIFECYCLE_NOT_TERMINAL")
            row = await connection.fetchrow(
                f"SELECT * FROM {CANDIDATE_TABLE} WHERE strategy_lifecycle_id=$1 "
                "AND lifecycle_state='ACTIVE' FOR UPDATE",
                strategy_lifecycle_id,
            )
            if row is None:
                return TradePlanCandidateV2PersistenceResult("DUPLICATE", "NO_ACTIVE_TRADEPLAN_CANDIDATE")
            candidate = _candidate_from_row(row)
            await _validate_candidate_predecessor_chain(connection, candidate)
            lifecycle_clock = _row_value(lifecycle, "last_event_at")
            closed = await self._close_candidate(
                connection,
                candidate,
                state="INVALIDATED",
                occurred_at=_terminal_clock(lifecycle_clock, occurred_at_utc, floor=candidate.decision_at_utc),
            )
            return TradePlanCandidateV2PersistenceResult("INVALIDATED", reason_code, candidate=closed)

    @staticmethod
    async def _close_candidate(
        connection: Any,
        candidate: TradePlanCandidateV2,
        *,
        state: Literal["SUPERSEDED", "INVALIDATED", "EXPIRED"],
        occurred_at: datetime,
    ) -> TradePlanCandidateV2:
        if candidate.lifecycle_state != "ACTIVE":
            return candidate
        result = await connection.execute(
            f"""
            UPDATE {CANDIDATE_TABLE} SET lifecycle_state=$2::varchar,
                superseded_at=CASE WHEN $2::varchar='SUPERSEDED' THEN $3::timestamptz ELSE NULL END,
                invalidated_at=CASE WHEN $2::varchar='INVALIDATED' THEN $3::timestamptz ELSE NULL END,
                expired_at=CASE WHEN $2::varchar='EXPIRED' THEN $3::timestamptz ELSE NULL END,
                state_version=state_version+1,updated_at=now()
            WHERE tradeplan_id=$1 AND lifecycle_state='ACTIVE'
            """,
            candidate.tradeplan_id,
            state,
            max(candidate.decision_at_utc, occurred_at),
        )
        if not str(result).endswith(" 1"):
            raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_STATE_VERSION_NOT_ADVANCED")
        return candidate.model_copy(update={"lifecycle_state": state})

    @staticmethod
    async def _insert_candidate(
        connection: Any,
        candidate: TradePlanCandidateV2,
        evidence: TradePlanCandidateBuildEvidenceV2,
        target_map: StructuralTargetMapAuthorityV1 | None,
    ) -> None:
        if target_map is None:
            raise TradePlanCandidateV2IntegrityError("TRADEPLAN_TARGET_MAP_AUTHORITY_MISSING")
        broker = evidence.broker_geometry
        pip_size = broker.pip_size
        target_payload = json.dumps(candidate.target_authority.model_dump(mode="json"), sort_keys=True)
        stop_payload = json.dumps(candidate.stop_authority.model_dump(mode="json"), sort_keys=True)
        evidence_json = json.dumps(evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        source_ids = tuple(
            item.candle_evidence_id
            for item in (
                *evidence.target_map_evidence.h4_candles,
                *evidence.target_map_evidence.h1_consumption_candles,
                evidence.target_map_evidence.selection_anchor,
            )
        )
        previous_sequence = candidate.candidate_sequence - 1 if candidate.previous_tradeplan_id else None
        previous_revision = 1 if candidate.previous_tradeplan_id else None
        result = await connection.execute(
            f"""
            INSERT INTO {CANDIDATE_TABLE} (
                tradeplan_id,strategy_lifecycle_id,context_epoch_id,strategy_thesis_id,execution_box_id,
                candidate_sequence,candidate_revision,previous_tradeplan_id,previous_candidate_sequence,
                previous_candidate_revision,symbol,strategy_direction,candidate_status,lifecycle_state,
                route_type,candidate_price,stop_loss,target_price,risk_distance_price,target_distance_price,
                rr,pip_size,target_mode,broker_authority_hash,broker_geometry_material_hash,
                broker_digits,broker_point,broker_tick_size,broker_pip_size,broker_spread_price,
                material_box_hash,execution_box_freeze_authority_hash,material_context_hash,
                thesis_semantic_identity_hash,
                box_sequence,box_version,structural_target_authority_hash,structural_target_material_hash,
                target_map_authority_hash,
                structural_stop_authority_hash,material_candidate_hash,formation_evidence_hash,
                source_candle_ids,opened_at,state_version,rule_version,valid_for_execution,
                execution_authority,next_required_stage,payload,target_authority_payload,
                stop_authority_payload,evidence_payload
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'TRADEPLAN_CANDIDATE','ACTIVE',
                $13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,
                $31,$32,$33,$34,$35,$36,$37,$38,$39,$40,$41::jsonb,$42,1,$43,false,false,
                'RISK_RESERVATION',$44::jsonb,$45::jsonb,$46::jsonb,$47::jsonb
            )
            """,
            candidate.tradeplan_id,
            candidate.strategy_lifecycle_id,
            candidate.context_epoch_id,
            candidate.strategy_thesis_id,
            candidate.execution_box_id,
            candidate.candidate_sequence,
            candidate.candidate_revision,
            candidate.previous_tradeplan_id,
            previous_sequence,
            previous_revision,
            candidate.symbol,
            candidate.direction,
            candidate.route_type,
            candidate.candidate_price,
            candidate.stop_authority.structural_stop_price,
            candidate.target_authority.target_price,
            abs(candidate.candidate_price - candidate.stop_authority.structural_stop_price),
            abs(candidate.target_authority.target_price - candidate.candidate_price),
            candidate.gross_rr,
            pip_size,
            candidate.target_authority.target_kind,
            candidate.broker_authority_hash,
            candidate.broker_geometry_material_hash,
            candidate.broker_digits,
            candidate.broker_point,
            candidate.broker_tick_size,
            candidate.broker_pip_size,
            candidate.broker_spread_price,
            candidate.execution_box_material_hash,
            candidate.execution_box_freeze_authority_hash,
            candidate.material_context_hash,
            candidate.thesis_semantic_identity_hash,
            candidate.box_sequence,
            candidate.box_version,
            candidate.target_authority.authority_hash,
            candidate.target_authority.material_target_hash,
            candidate.target_map_authority_hash,
            candidate.stop_authority.authority_hash,
            candidate.material_candidate_hash,
            candidate.evidence_hash,
            json.dumps(source_ids, separators=(",", ":")),
            candidate.decision_at_utc,
            candidate.rule_version,
            json.dumps(candidate.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            target_payload,
            stop_payload,
            evidence_json,
        )
        if not str(result).endswith(" 1"):
            raise TradePlanCandidateV2IntegrityError("TRADEPLAN_CANDIDATE_INSERT_FAILED")

    async def _insert_evaluation(
        self,
        connection: Any,
        evaluation: TradePlanEvaluationV2,
        evidence: TradePlanCandidateBuildEvidenceV2,
        reduction: Any,
    ) -> None:
        candidate = reduction.candidate if evaluation.decision == "CANDIDATE" else None
        target_map_payload = {} if reduction.target_map is None else reduction.target_map.model_dump(mode="json")
        stop_payload = {} if candidate is None else candidate.stop_authority.model_dump(mode="json")
        wrapper = {
            "evaluation": evaluation.model_dump(mode="json"),
            "build_evidence": evidence.model_dump(mode="json"),
        }
        result = await connection.execute(
            f"""
            INSERT INTO {EVALUATION_TABLE} (
                evaluation_id,strategy_lifecycle_id,context_epoch_id,strategy_thesis_id,
                execution_box_id,symbol,strategy_direction,material_context_hash,
                thesis_semantic_identity_hash,material_box_hash,execution_box_freeze_authority_hash,
                evaluation_sequence,evaluated_at,
                source_request_id,decision,reason_code,reason_codes,material_evaluation_hash,
                evidence_hash,rule_version,tradeplan_id,candidate_sequence,candidate_revision,
                material_candidate_hash,evidence_payload,target_authority_payload,
                stop_authority_payload,valid_for_execution,execution_authority
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17::jsonb,$18,
                $19,$20,$21,$22,$23,$24,$25::jsonb,$26::jsonb,$27::jsonb,false,false
            )
            """,
            evaluation.evaluation_id,
            evaluation.strategy_lifecycle_id,
            evaluation.context_epoch_id,
            evaluation.strategy_thesis_id,
            evaluation.execution_box_id,
            evaluation.symbol,
            evaluation.direction,
            evaluation.material_context_hash,
            evaluation.thesis_semantic_identity_hash,
            evaluation.execution_box_material_hash,
            evaluation.execution_box_freeze_authority_hash,
            evaluation.evaluation_sequence,
            evaluation.decision_at_utc,
            evaluation.source_request_id,
            evaluation.decision,
            evaluation.reason_codes[0],
            json.dumps(evaluation.reason_codes, separators=(",", ":")),
            evaluation.material_evaluation_hash,
            evaluation.evidence_hash,
            evaluation.rule_version,
            None if candidate is None else candidate.tradeplan_id,
            None if candidate is None else candidate.candidate_sequence,
            None if candidate is None else candidate.candidate_revision,
            None if candidate is None else candidate.material_candidate_hash,
            json.dumps(wrapper, sort_keys=True, separators=(",", ":")),
            json.dumps(target_map_payload, sort_keys=True, separators=(",", ":")),
            json.dumps(stop_payload, sort_keys=True, separators=(",", ":")),
        )
        if not str(result).endswith(" 1"):
            raise TradePlanCandidateV2IntegrityError("TRADEPLAN_EVALUATION_INSERT_FAILED")
        if self._observer_export is not None:
            await self._observer_export.append_in_transaction(
                connection,
                canonical_tradeplan_decision_observer_draft(evaluation, evidence),
            )


__all__ = [
    "Strategy5SCRTradePlanCandidateV2Repository",
    "TradePlanCandidateV2IntegrityError",
    "TradePlanCandidateV2PersistenceResult",
    "TradePlanCandidateV2PersistenceStatus",
    "TradePlanCandidateV2RuntimeConfig",
    "TradePlanCandidateV2SchemaStatus",
]
