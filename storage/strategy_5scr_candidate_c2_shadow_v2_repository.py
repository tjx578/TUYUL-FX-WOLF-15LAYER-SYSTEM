"""Atomic PostgreSQL authority for CandidateV2 -> C2 SHADOW risk V2.

This repository owns and writes only the new V2 namespace.  It reads legacy
Strategy 5S-CR risk state solely as an account-wide double-risk fence; it never
mutates that state and never creates an execution command.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import ValidationError

from analysis.strategy_5scr_candidate_c2_shadow_v2 import evaluate_candidate_c2_shadow_v2
from contracts.mt5_execution_protocol import AccountSnapshotV1
from contracts.strategy_5scr_candidate_c2_shadow_v2 import (
    C2_SHADOW_CANDIDATE_MAX_AGE_SECONDS,
    C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS,
    C2ShadowAuthorityBundleV2,
    C2ShadowCampaignRiskLockV2,
    C2ShadowEvaluationV2,
    C2ShadowExecutionCampaignV2,
    C2ShadowExistingRiskEvidenceV2,
    C2ShadowFinalSignalV2,
    C2ShadowRiskReservationV2,
    CandidateC2ShadowBuildEvidenceV2,
    CandidateC2ShadowHandoffV2,
    account_snapshot_authority_hash_v2,
    c2_shadow_governance_evidence_v2,
    snapshot_candidate_c2_build_evidence_v2,
    symbol_capability_authority_hash_v2,
)
from contracts.strategy_5scr_execution_box_v1 import ExecutionBoxV1
from contracts.strategy_5scr_lifecycle_v2 import TERMINAL_LIFECYCLE_STATES
from contracts.strategy_5scr_tradeplan_candidate_v2 import TradePlanCandidateV2, canonical_hash_v1
from risk.s5_campaign_risk import CampaignRiskPolicy, find_symbol_capability, validate_account_snapshot
from storage.postgres_client import PostgresClient, pg_client
from storage.strategy_5scr_directional_thesis_v1_repository import (
    Strategy5SCRDirectionalThesisV1Repository,
    _context_from_row,
)
from storage.strategy_5scr_directional_thesis_v1_repository import _thesis_from_row as _p4_thesis_from_row
from storage.strategy_5scr_execution_box_v1_repository import _box_from_row
from storage.strategy_5scr_tradeplan_candidate_v2_repository import (
    BOX_TABLE,
    CANDIDATE_TABLE,
    CONTEXT_TABLE,
    LIFECYCLE_TABLE,
    THESIS_TABLE,
    Strategy5SCRTradePlanCandidateV2Repository,
    _candidate_from_row,
    _lifecycle_from_row,
    _terminal_clock,
    _validate_candidate_predecessor_chain,
)

HANDOFF_TABLE = "strategy_5scr_candidate_c2_handoffs_v2"
EVALUATION_TABLE = "strategy_5scr_candidate_c2_evaluations_v2"
RISK_LOCK_TABLE = "strategy_5scr_campaign_risk_locks_v2"
RESERVATION_TABLE = "strategy_5scr_risk_reservations_v2"
CAMPAIGN_TABLE = "strategy_5scr_execution_campaigns_v2"
OUTBOX_TABLE = "strategy_5scr_final_signal_outbox_v2"

C2_SHADOW_WRITER_FLAG = "STRATEGY_5SCR_C2_SHADOW_V2_WRITER_ENABLED"
C2_SHADOW_ONLY_FLAG = "STRATEGY_5SCR_C2_SHADOW_V2_SHADOW_ONLY"


class CandidateC2ShadowV2IntegrityError(RuntimeError):
    """A durable V2 row disagrees with its frozen authority payload."""


def _enabled(value: str | None, *, default: bool) -> bool:
    return default if value is None else value.strip().lower() == "true"


def _row(row: Any, key: str) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError):
        return getattr(row, key, None)


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _dump(value: Any) -> str:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _normalize_sql(value: Any) -> str:
    """Fingerprint the exact stable PostgreSQL catalog representation."""

    return str(value or "")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_normalize_sql(value).encode()).hexdigest()


def _durable_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (int, float, Decimal)) and not isinstance(expected, bool):
        try:
            return Decimal(str(actual)) == Decimal(str(expected))
        except (InvalidOperation, ValueError):
            return False
    return str(actual) == str(expected)


@dataclass(frozen=True, slots=True)
class CandidateC2ShadowV2RuntimeConfig:
    enabled: bool = False
    shadow_only: bool = True

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> CandidateC2ShadowV2RuntimeConfig:
        source = os.environ if environ is None else environ
        return cls(
            enabled=_enabled(source.get(C2_SHADOW_WRITER_FLAG), default=False),
            shadow_only=_enabled(source.get(C2_SHADOW_ONLY_FLAG), default=True),
        )

    def validate(self) -> None:
        if self.enabled and not self.shadow_only:
            raise RuntimeError("C2_SHADOW_V2_SHADOW_ONLY_REQUIRED")


@dataclass(frozen=True, slots=True)
class CandidateC2ShadowV2SchemaStatus:
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


CandidateC2ShadowPersistenceStatus = Literal["APPROVED", "WAIT", "REJECTED", "DUPLICATE", "QUARANTINED", "INVALIDATED"]


@dataclass(frozen=True, slots=True)
class CandidateC2ShadowPersistenceResult:
    status: CandidateC2ShadowPersistenceStatus
    reason_code: str
    evaluation: C2ShadowEvaluationV2 | None = None
    authority_bundle: C2ShadowAuthorityBundleV2 | None = None


_TABLES = frozenset({HANDOFF_TABLE, EVALUATION_TABLE, RISK_LOCK_TABLE, RESERVATION_TABLE, CAMPAIGN_TABLE, OUTBOX_TABLE})
_DEPENDENCY_TABLE = "executor_account_snapshots"
_DEPENDENCY_TABLES = frozenset(
    {
        _DEPENDENCY_TABLE,
        "executor_instances",
        "executor_bridge_governance",
        "execution_commands",
        "strategy_5scr_campaign_risk_locks",
        "strategy_5scr_risk_reservations",
    }
)
_REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    HANDOFF_TABLE: frozenset(
        {
            "handoff_id",
            "tradeplan_id",
            "strategy_lifecycle_id",
            "context_epoch_id",
            "strategy_thesis_id",
            "execution_box_id",
            "symbol",
            "strategy_direction",
            "material_context_hash",
            "thesis_semantic_identity_hash",
            "candidate_sequence",
            "candidate_revision",
            "material_candidate_hash",
            "formation_evidence_hash",
            "account_id",
            "executor_id",
            "broker_server",
            "account_snapshot_id",
            "account_snapshot_hash",
            "candidate_price",
            "stop_loss",
            "take_profit",
            "target_authority_hash",
            "stop_authority_hash",
            "broker_geometry_material_hash",
            "accepted_at",
            "authority_hash",
            "execution_mode",
            "execution_authority",
            "payload",
            "build_evidence_payload",
            "created_at",
        }
    ),
    RISK_LOCK_TABLE: frozenset(
        {
            "risk_lock_id",
            "execution_campaign_id",
            "handoff_id",
            "tradeplan_id",
            "account_id",
            "account_snapshot_id",
            "policy_id",
            "balance_base",
            "risk_percent_per_entry",
            "risk_unit_usd",
            "max_campaign_risk_usd",
            "locked_at",
            "authority_hash",
            "risk_authority",
            "broker_execution_authority",
            "state",
            "closed_at",
            "terminal_reason",
            "state_version",
            "payload",
            "created_at",
        }
    ),
    RESERVATION_TABLE: frozenset(
        {
            "reservation_id",
            "execution_campaign_id",
            "risk_lock_id",
            "handoff_id",
            "tradeplan_id",
            "executor_id",
            "account_id",
            "account_snapshot_id",
            "account_snapshot_hash",
            "symbol_capability_hash",
            "governance_evidence_hash",
            "existing_risk_evidence_hash",
            "broker_server",
            "canonical_symbol",
            "broker_symbol",
            "direction",
            "entry_role",
            "state",
            "volume",
            "entry_price",
            "stop_loss",
            "take_profit",
            "risk_unit_usd",
            "reserved_risk_usd",
            "reserved_at",
            "expires_at",
            "authority_hash",
            "risk_authority",
            "valid_for_execution",
            "execution_mode",
            "broker_execution_authority",
            "command_authority",
            "terminal_at",
            "terminal_reason",
            "state_version",
            "payload",
            "created_at",
        }
    ),
    CAMPAIGN_TABLE: frozenset(
        {
            "execution_campaign_id",
            "tradeplan_id",
            "reservation_id",
            "account_id",
            "canonical_symbol",
            "direction",
            "state",
            "execution_mode",
            "opened_at",
            "authority_hash",
            "risk_authority",
            "broker_execution_authority",
            "command_authority",
            "terminal_at",
            "terminal_reason",
            "state_version",
            "payload",
            "created_at",
        }
    ),
    OUTBOX_TABLE: frozenset(
        {
            "outbox_id",
            "signal_id",
            "execution_campaign_id",
            "reservation_id",
            "tradeplan_id",
            "account_snapshot_id",
            "account_id",
            "executor_id",
            "broker_server",
            "handoff_id",
            "risk_lock_id",
            "account_snapshot_hash",
            "symbol_capability_hash",
            "governance_evidence_hash",
            "existing_risk_evidence_hash",
            "material_candidate_hash",
            "candidate_evidence_hash",
            "canonical_symbol",
            "broker_symbol",
            "direction",
            "entry_role",
            "payload",
            "payload_hash",
            "authority_hash",
            "status",
            "delivery_authority",
            "broker_execution_authority",
            "command_authority",
            "created_at",
            "terminal_at",
            "terminal_reason",
            "state_version",
        }
    ),
    EVALUATION_TABLE: frozenset(
        {
            "evaluation_id",
            "tradeplan_id",
            "strategy_lifecycle_id",
            "context_epoch_id",
            "strategy_thesis_id",
            "execution_box_id",
            "symbol",
            "strategy_direction",
            "material_context_hash",
            "thesis_semantic_identity_hash",
            "candidate_sequence",
            "candidate_revision",
            "material_candidate_hash",
            "formation_evidence_hash",
            "evaluation_sequence",
            "source_request_id",
            "account_id",
            "executor_id",
            "account_snapshot_id",
            "decision_at",
            "decision",
            "reason_code",
            "evidence_hash",
            "material_evaluation_hash",
            "result_execution_campaign_id",
            "result_reservation_id",
            "rule_version",
            "execution_authority",
            "payload",
            "build_evidence_payload",
            "created_at",
        }
    ),
    _DEPENDENCY_TABLE: frozenset(
        {
            "snapshot_id",
            "executor_id",
            "account_id",
            "captured_at",
            "balance",
            "equity",
            "floating_pnl",
            "used_margin",
            "free_margin",
            "margin_level_pct",
            "margin_mode",
            "trade_allowed",
            "autotrading_enabled",
            "payload",
            "received_at",
            "broker_ledger_reconciled",
            "pending_order_count",
        }
    ),
    "executor_instances": frozenset(
        {
            "executor_id",
            "account_id",
            "login_hash",
            "broker_server",
            "terminal_build",
            "ea_version",
            "protocol_version",
            "execution_mode",
            "status",
            "last_heartbeat_at",
            "revoked_at",
            "created_at",
            "updated_at",
            "mode_version",
            "mode_changed_at",
            "mode_changed_by",
            "mode_change_reason",
        }
    ),
    "executor_bridge_governance": frozenset(
        {
            "singleton_id",
            "kill_switch_active",
            "kill_switch_reason",
            "governance_version",
            "updated_by",
            "updated_at",
        }
    ),
    "execution_commands": frozenset({"command_id", "executor_id", "account_id", "state", "terminal_at"}),
    "strategy_5scr_campaign_risk_locks": frozenset({"account_id", "state"}),
    "strategy_5scr_risk_reservations": frozenset({"account_id", "state", "reserved_risk_usd"}),
}
_CONSTRAINT_TABLES: dict[str, str] = {
    "executor_account_snapshots_pkey": _DEPENDENCY_TABLE,
    "executor_instances_pkey": "executor_instances",
    "executor_bridge_governance_pkey": "executor_bridge_governance",
    "ck_executor_governance_singleton": "executor_bridge_governance",
    "uq_5scr_tradeplan_candidate_v2_c2_scope": CANDIDATE_TABLE,
    "ck_executor_account_snapshot_c2_reconciliation_v2": _DEPENDENCY_TABLE,
    "uq_executor_account_snapshot_c2_scope_v2": _DEPENDENCY_TABLE,
    "pk_5scr_candidate_c2_handoff_v2": HANDOFF_TABLE,
    "fk_5scr_candidate_c2_handoff_v2_candidate_scope": HANDOFF_TABLE,
    "fk_5scr_candidate_c2_handoff_v2_snapshot_scope": HANDOFF_TABLE,
    "ck_5scr_candidate_c2_handoff_v2_shadow": HANDOFF_TABLE,
    "ck_5scr_candidate_c2_handoff_v2_identity": HANDOFF_TABLE,
    "ck_5scr_candidate_c2_handoff_v2_geometry": HANDOFF_TABLE,
    "ck_5scr_candidate_c2_handoff_v2_payload": HANDOFF_TABLE,
    "uq_5scr_candidate_c2_handoff_v2_candidate": HANDOFF_TABLE,
    "uq_5scr_candidate_c2_handoff_v2_risk_scope": HANDOFF_TABLE,
    "uq_5scr_candidate_c2_handoff_v2_outbox_scope": HANDOFF_TABLE,
    "pk_5scr_campaign_risk_lock_v2": RISK_LOCK_TABLE,
    "uq_5scr_campaign_risk_lock_v2_campaign": RISK_LOCK_TABLE,
    "uq_5scr_campaign_risk_lock_v2_handoff": RISK_LOCK_TABLE,
    "fk_5scr_campaign_risk_lock_v2_handoff_scope": RISK_LOCK_TABLE,
    "ck_5scr_campaign_risk_lock_v2_authority": RISK_LOCK_TABLE,
    "ck_5scr_campaign_risk_lock_v2_identity": RISK_LOCK_TABLE,
    "ck_5scr_campaign_risk_lock_v2_amounts": RISK_LOCK_TABLE,
    "ck_5scr_campaign_risk_lock_v2_state": RISK_LOCK_TABLE,
    "ck_5scr_campaign_risk_lock_v2_state_version": RISK_LOCK_TABLE,
    "uq_5scr_campaign_risk_lock_v2_reservation_scope": RISK_LOCK_TABLE,
    "uq_5scr_campaign_risk_lock_v2_reservation_risk_scope": RISK_LOCK_TABLE,
    "fk_5scr_campaign_risk_lock_v2_campaign": RISK_LOCK_TABLE,
    "pk_5scr_risk_reservation_v2": RESERVATION_TABLE,
    "uq_5scr_risk_reservation_v2_campaign": RESERVATION_TABLE,
    "uq_5scr_risk_reservation_v2_risk_lock": RESERVATION_TABLE,
    "uq_5scr_risk_reservation_v2_handoff": RESERVATION_TABLE,
    "uq_5scr_risk_reservation_v2_tradeplan": RESERVATION_TABLE,
    "fk_5scr_risk_reservation_v2_lock_scope": RESERVATION_TABLE,
    "fk_5scr_risk_reservation_v2_handoff_scope": RESERVATION_TABLE,
    "fk_5scr_risk_reservation_v2_snapshot_scope": RESERVATION_TABLE,
    "fk_5scr_risk_reservation_v2_campaign": RESERVATION_TABLE,
    "ck_5scr_risk_reservation_v2_authority": RESERVATION_TABLE,
    "ck_5scr_risk_reservation_v2_identity": RESERVATION_TABLE,
    "ck_5scr_risk_reservation_v2_state": RESERVATION_TABLE,
    "ck_5scr_risk_reservation_v2_lifecycle": RESERVATION_TABLE,
    "ck_5scr_risk_reservation_v2_state_version": RESERVATION_TABLE,
    "ck_5scr_risk_reservation_v2_geometry": RESERVATION_TABLE,
    "uq_5scr_risk_reservation_v2_campaign_scope": RESERVATION_TABLE,
    "uq_5scr_risk_reservation_v2_execution_campaign_scope": RESERVATION_TABLE,
    "uq_5scr_risk_reservation_v2_evaluation_scope": RESERVATION_TABLE,
    "pk_5scr_execution_campaign_v2": CAMPAIGN_TABLE,
    "uq_5scr_execution_campaign_v2_tradeplan": CAMPAIGN_TABLE,
    "uq_5scr_execution_campaign_v2_reservation": CAMPAIGN_TABLE,
    "fk_5scr_execution_campaign_v2_reservation_scope": CAMPAIGN_TABLE,
    "ck_5scr_execution_campaign_v2_authority": CAMPAIGN_TABLE,
    "ck_5scr_execution_campaign_v2_identity": CAMPAIGN_TABLE,
    "ck_5scr_execution_campaign_v2_state": CAMPAIGN_TABLE,
    "ck_5scr_execution_campaign_v2_lifecycle": CAMPAIGN_TABLE,
    "ck_5scr_execution_campaign_v2_state_version": CAMPAIGN_TABLE,
    "uq_5scr_execution_campaign_v2_outbox_scope": CAMPAIGN_TABLE,
    "pk_5scr_final_signal_outbox_v2": OUTBOX_TABLE,
    "uq_5scr_final_signal_outbox_v2_signal": OUTBOX_TABLE,
    "uq_5scr_final_signal_outbox_v2_campaign": OUTBOX_TABLE,
    "uq_5scr_final_signal_outbox_v2_reservation": OUTBOX_TABLE,
    "uq_5scr_final_signal_outbox_v2_tradeplan": OUTBOX_TABLE,
    "fk_5scr_final_signal_outbox_v2_campaign_scope": OUTBOX_TABLE,
    "fk_5scr_final_signal_outbox_v2_reservation_scope": OUTBOX_TABLE,
    "fk_5scr_final_signal_outbox_v2_handoff_scope": OUTBOX_TABLE,
    "fk_5scr_final_signal_outbox_v2_risk_lock_scope": OUTBOX_TABLE,
    "fk_5scr_final_signal_outbox_v2_snapshot_scope": OUTBOX_TABLE,
    "ck_5scr_final_signal_outbox_v2_dark": OUTBOX_TABLE,
    "ck_5scr_final_signal_outbox_v2_identity": OUTBOX_TABLE,
    "ck_5scr_final_signal_outbox_v2_lifecycle": OUTBOX_TABLE,
    "ck_5scr_final_signal_outbox_v2_state_version": OUTBOX_TABLE,
    "ck_5scr_final_signal_outbox_v2_payload": OUTBOX_TABLE,
    "pk_5scr_candidate_c2_evaluation_v2": EVALUATION_TABLE,
    "fk_5scr_candidate_c2_evaluation_v2_candidate_scope": EVALUATION_TABLE,
    "fk_5scr_candidate_c2_evaluation_v2_snapshot_scope": EVALUATION_TABLE,
    "fk_5scr_candidate_c2_evaluation_v2_result_scope": EVALUATION_TABLE,
    "ck_5scr_candidate_c2_evaluation_v2_shadow": EVALUATION_TABLE,
    "ck_5scr_candidate_c2_evaluation_v2_identity": EVALUATION_TABLE,
    "ck_5scr_candidate_c2_evaluation_v2_decision": EVALUATION_TABLE,
    "ck_5scr_candidate_c2_evaluation_v2_result": EVALUATION_TABLE,
    "uq_5scr_candidate_c2_evaluation_v2_sequence": EVALUATION_TABLE,
    "uq_5scr_candidate_c2_evaluation_v2_request": EVALUATION_TABLE,
    "uq_5scr_candidate_c2_evaluation_v2_clock": EVALUATION_TABLE,
    "ck_5scr_campaign_risk_lock_state_v1": "strategy_5scr_campaign_risk_locks",
    "ck_5scr_campaign_risk_lock_amounts_v1": "strategy_5scr_campaign_risk_locks",
    "ck_5scr_campaign_risk_lock_lifecycle_v1": "strategy_5scr_campaign_risk_locks",
    "ck_5scr_risk_reservation_state_v1": "strategy_5scr_risk_reservations",
    "ck_5scr_risk_reservation_amounts_v1": "strategy_5scr_risk_reservations",
    "ck_5scr_risk_reservation_lifecycle_v1": "strategy_5scr_risk_reservations",
}
_INDEX_TABLES = {
    "ix_executor_snapshots_executor_captured": _DEPENDENCY_TABLE,
    "ix_5scr_candidate_c2_handoff_v2_lifecycle": HANDOFF_TABLE,
    "ix_5scr_c2_handoff_v2_executor": HANDOFF_TABLE,
    "ix_5scr_c2_handoff_v2_snapshot_scope": HANDOFF_TABLE,
    "ix_5scr_campaign_risk_lock_v2_account": RISK_LOCK_TABLE,
    "ix_5scr_c2_risk_lock_v2_snapshot": RISK_LOCK_TABLE,
    "ix_5scr_risk_reservation_v2_account_expiry": RESERVATION_TABLE,
    "ix_5scr_c2_reservation_v2_executor_state": RESERVATION_TABLE,
    "ix_5scr_c2_reservation_v2_snapshot_scope": RESERVATION_TABLE,
    "ix_5scr_execution_campaign_v2_account_state": CAMPAIGN_TABLE,
    "ix_5scr_final_signal_outbox_v2_status": OUTBOX_TABLE,
    "ix_5scr_c2_outbox_v2_handoff_scope": OUTBOX_TABLE,
    "ix_5scr_c2_outbox_v2_risk_lock_scope": OUTBOX_TABLE,
    "ix_5scr_c2_outbox_v2_snapshot_scope": OUTBOX_TABLE,
    "ix_5scr_candidate_c2_evaluation_v2_history": EVALUATION_TABLE,
    "ix_5scr_c2_evaluation_v2_candidate_scope": EVALUATION_TABLE,
    "ix_5scr_c2_evaluation_v2_result_scope": EVALUATION_TABLE,
    "ix_5scr_c2_evaluation_v2_snapshot_scope": EVALUATION_TABLE,
    "ix_5scr_campaign_risk_locks_account_state": "strategy_5scr_campaign_risk_locks",
    "ix_5scr_risk_reservations_account_state": "strategy_5scr_risk_reservations",
}
_TRIGGER_TABLES = {
    "trg_5scr_guard_account_snapshot_c2_update_v2": _DEPENDENCY_TABLE,
    "trg_5scr_reject_c2_handoff_v2_mutation": HANDOFF_TABLE,
    "trg_5scr_reject_c2_evaluation_v2_mutation": EVALUATION_TABLE,
    "trg_5scr_guard_execution_command_against_c2_v2": "execution_commands",
    "trg_5scr_guard_executor_identity_against_c2_v2": "executor_instances",
    "trg_5scr_guard_legacy_campaign_risk_against_c2_v2": "strategy_5scr_campaign_risk_locks",
    "trg_5scr_guard_legacy_reservation_against_c2_v2": "strategy_5scr_risk_reservations",
    # P7's legacy-risk fence is only trustworthy while the original lifecycle
    # guards still prevent economic mutation and authority resurrection.
    "trg_5scr_campaign_risk_lock_update_v1": "strategy_5scr_campaign_risk_locks",
    "trg_5scr_risk_reservation_update_v1": "strategy_5scr_risk_reservations",
    **{
        f"trg_5scr_guard_{table}_transition": table
        for table in (RISK_LOCK_TABLE, RESERVATION_TABLE, CAMPAIGN_TABLE, OUTBOX_TABLE)
    },
}

# Captured from a clean PostgreSQL 16 migration at revision 20260813_02.
_COLUMN_HASHES: dict[str, str] = {
    "execution_commands.account_id": "0e9ef2205c7356c5a1935641392a10597d6f2c4d7b1feba2e2ea83ad2998e1ac",
    "execution_commands.command_id": "e43e1f39b14f0ecbcb541dcc44d79475324e71a5aabce4f2313b4f6662aaa042",
    "execution_commands.executor_id": "e43e1f39b14f0ecbcb541dcc44d79475324e71a5aabce4f2313b4f6662aaa042",
    "execution_commands.state": "183eee6fd8ae87fde8ef3e00f1154a72338ac65f31a6e12579f82c5f0d7f0f9d",
    "execution_commands.terminal_at": "7916a7a9a05464c0a93d9cb27adf89734fc2b9394725b6be3030a68d21ef245b",
    "strategy_5scr_campaign_risk_locks.account_id": "0e9ef2205c7356c5a1935641392a10597d6f2c4d7b1feba2e2ea83ad2998e1ac",
    "strategy_5scr_campaign_risk_locks.state": "a97eb0e8ac0ddb35ac02062afe07741b090ab5288246ddad406b543fb3c1ed79",
    "strategy_5scr_risk_reservations.account_id": "0e9ef2205c7356c5a1935641392a10597d6f2c4d7b1feba2e2ea83ad2998e1ac",
    "strategy_5scr_risk_reservations.reserved_risk_usd": "734892c764e4d4059eef667ea7e973cad70482951538fc626f315d9674659463",
    "strategy_5scr_risk_reservations.state": "f19a6a2168c25a502be7ddd89669db75567ab43ac580dfbe1bddd2ae0532f64a",
    "executor_account_snapshots.account_id": "0e9ef2205c7356c5a1935641392a10597d6f2c4d7b1feba2e2ea83ad2998e1ac",
    "executor_account_snapshots.autotrading_enabled": "8d8509b414f32f45691143bdf25fb00c29daf9de84e0567d713566b5b7ae3716",
    "executor_account_snapshots.balance": "734892c764e4d4059eef667ea7e973cad70482951538fc626f315d9674659463",
    "executor_account_snapshots.broker_ledger_reconciled": "f3e6eebebcea0fbd59e4ace54b393bfcda7cf83693f0821d9b978abd7b5480d3",
    "executor_account_snapshots.captured_at": "4c35acdce3298b00dc23b17f8cc26c78dbd68c53b5aab2ff58d7f53097cd5fb2",
    "executor_account_snapshots.equity": "734892c764e4d4059eef667ea7e973cad70482951538fc626f315d9674659463",
    "executor_account_snapshots.executor_id": "e43e1f39b14f0ecbcb541dcc44d79475324e71a5aabce4f2313b4f6662aaa042",
    "executor_account_snapshots.floating_pnl": "734892c764e4d4059eef667ea7e973cad70482951538fc626f315d9674659463",
    "executor_account_snapshots.free_margin": "734892c764e4d4059eef667ea7e973cad70482951538fc626f315d9674659463",
    "executor_account_snapshots.margin_level_pct": "42bcb0e38cc375e599b3f6e9822e460f41e22a41c390d9ad944dd17bc88c70bf",
    "executor_account_snapshots.margin_mode": "e904a7fc63a418b9592ebafe11e9ca823ba45af13c30cd15dab493c49be68789",
    "executor_account_snapshots.payload": "f18f885cbe479d1669e0ca7709fced59ec83d6b0914451002bb71fb807947fcf",
    "executor_account_snapshots.pending_order_count": "e600a3b106e70bdf838c64989b50e861c6bb8048ac5abd0d53103f8734b0d40a",
    "executor_account_snapshots.received_at": "4d69c98ecfac125851d87a272513495e650c525f7608fd520fb4a886fc521446",
    "executor_account_snapshots.snapshot_id": "97fbd0bf37f70208a1cb0de3ef99069b0ddd232b057e4ad2f7ba1d1de8b3d2e3",
    "executor_account_snapshots.trade_allowed": "8d8509b414f32f45691143bdf25fb00c29daf9de84e0567d713566b5b7ae3716",
    "executor_account_snapshots.used_margin": "734892c764e4d4059eef667ea7e973cad70482951538fc626f315d9674659463",
    "executor_bridge_governance.governance_version": "c52d5af39d5c8c12966ab6c4c2291bf06645a57aae2b60dd59df73598fdeb28a",
    "executor_bridge_governance.kill_switch_active": "99d6dd1442d77d0f6634c16703460f481870c13c29ae5ade5ef213ce31424017",
    "executor_bridge_governance.kill_switch_reason": "83dbe90e9a80d7c18298dd7dbe6eee2bf486726a759ea5a29b1a4349c9b2d501",
    "executor_bridge_governance.singleton_id": "5a8fc06a9dff8266ee2ff69df34b7456f5eb0e1bb77f2b2f4df2da9ae8b23791",
    "executor_bridge_governance.updated_at": "4d69c98ecfac125851d87a272513495e650c525f7608fd520fb4a886fc521446",
    "executor_bridge_governance.updated_by": "9b0609b92308f6a4ca38e1863249173834c3ae9e3c5b1652d1d169c75d5d09c1",
    "executor_instances.account_id": "0e9ef2205c7356c5a1935641392a10597d6f2c4d7b1feba2e2ea83ad2998e1ac",
    "executor_instances.broker_server": "97fbd0bf37f70208a1cb0de3ef99069b0ddd232b057e4ad2f7ba1d1de8b3d2e3",
    "executor_instances.created_at": "4d69c98ecfac125851d87a272513495e650c525f7608fd520fb4a886fc521446",
    "executor_instances.ea_version": "a098da01088580434cd1ea463747b8a3cdf9304b39d1604ee47758761ece0d48",
    "executor_instances.execution_mode": "b9a5cb67030da81ceecdbc07e9f52b0550e339b61a07720c93f1f5b0d5842273",
    "executor_instances.executor_id": "e43e1f39b14f0ecbcb541dcc44d79475324e71a5aabce4f2313b4f6662aaa042",
    "executor_instances.last_heartbeat_at": "7916a7a9a05464c0a93d9cb27adf89734fc2b9394725b6be3030a68d21ef245b",
    "executor_instances.login_hash": "300af0e3661b090ccb6fefecbf09540f1fe0f16d2d81d3bb2f2b1df7bf25680c",
    "executor_instances.mode_change_reason": "a118564b7f04e37e02e738821e8988c63f39de70b45621b5a69c405de6f52bf2",
    "executor_instances.mode_changed_at": "7916a7a9a05464c0a93d9cb27adf89734fc2b9394725b6be3030a68d21ef245b",
    "executor_instances.mode_changed_by": "21db8dc3aec230da78f625bffd8fdbb1eae2d8532f81f1db3742eabb3e150236",
    "executor_instances.mode_version": "c52d5af39d5c8c12966ab6c4c2291bf06645a57aae2b60dd59df73598fdeb28a",
    "executor_instances.protocol_version": "a098da01088580434cd1ea463747b8a3cdf9304b39d1604ee47758761ece0d48",
    "executor_instances.revoked_at": "7916a7a9a05464c0a93d9cb27adf89734fc2b9394725b6be3030a68d21ef245b",
    "executor_instances.status": "ed8cdbbb10f5d7b0035dbefbfda3c4ae7ad99bade2a4b1808f46bdabe168cfcf",
    "executor_instances.terminal_build": "04dce7f9b7b141142cab40bff83e4e70bceec3df185cdda2d781a5f075bc46af",
    "executor_instances.updated_at": "4d69c98ecfac125851d87a272513495e650c525f7608fd520fb4a886fc521446",
    "strategy_5scr_campaign_risk_locks_v2.account_id": "0e9ef2205c7356c5a1935641392a10597d6f2c4d7b1feba2e2ea83ad2998e1ac",
    "strategy_5scr_campaign_risk_locks_v2.account_snapshot_id": "97fbd0bf37f70208a1cb0de3ef99069b0ddd232b057e4ad2f7ba1d1de8b3d2e3",
    "strategy_5scr_campaign_risk_locks_v2.authority_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_campaign_risk_locks_v2.balance_base": "810a604821dfed4ff8f6dc3c1fec31b9c8e423ecaa6a9f440ff106260f444adb",
    "strategy_5scr_campaign_risk_locks_v2.broker_execution_authority": "10f9801083cfeae235e2f5deacf84a46d1e31036b745285d85c737bffc333611",
    "strategy_5scr_campaign_risk_locks_v2.closed_at": "7916a7a9a05464c0a93d9cb27adf89734fc2b9394725b6be3030a68d21ef245b",
    "strategy_5scr_campaign_risk_locks_v2.created_at": "4d69c98ecfac125851d87a272513495e650c525f7608fd520fb4a886fc521446",
    "strategy_5scr_campaign_risk_locks_v2.execution_campaign_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_campaign_risk_locks_v2.handoff_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_campaign_risk_locks_v2.locked_at": "4c35acdce3298b00dc23b17f8cc26c78dbd68c53b5aab2ff58d7f53097cd5fb2",
    "strategy_5scr_campaign_risk_locks_v2.max_campaign_risk_usd": "810a604821dfed4ff8f6dc3c1fec31b9c8e423ecaa6a9f440ff106260f444adb",
    "strategy_5scr_campaign_risk_locks_v2.payload": "f18f885cbe479d1669e0ca7709fced59ec83d6b0914451002bb71fb807947fcf",
    "strategy_5scr_campaign_risk_locks_v2.policy_id": "0e9ef2205c7356c5a1935641392a10597d6f2c4d7b1feba2e2ea83ad2998e1ac",
    "strategy_5scr_campaign_risk_locks_v2.risk_authority": "8d8509b414f32f45691143bdf25fb00c29daf9de84e0567d713566b5b7ae3716",
    "strategy_5scr_campaign_risk_locks_v2.risk_lock_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_campaign_risk_locks_v2.risk_percent_per_entry": "810a604821dfed4ff8f6dc3c1fec31b9c8e423ecaa6a9f440ff106260f444adb",
    "strategy_5scr_campaign_risk_locks_v2.risk_unit_usd": "810a604821dfed4ff8f6dc3c1fec31b9c8e423ecaa6a9f440ff106260f444adb",
    "strategy_5scr_campaign_risk_locks_v2.state": "a97eb0e8ac0ddb35ac02062afe07741b090ab5288246ddad406b543fb3c1ed79",
    "strategy_5scr_campaign_risk_locks_v2.state_version": "c52d5af39d5c8c12966ab6c4c2291bf06645a57aae2b60dd59df73598fdeb28a",
    "strategy_5scr_campaign_risk_locks_v2.terminal_reason": "6ab1073675556762e6c73af36a41dcbf9b3562ed9044f6577f183438acd2adb1",
    "strategy_5scr_campaign_risk_locks_v2.tradeplan_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_candidate_c2_evaluations_v2.account_id": "0e9ef2205c7356c5a1935641392a10597d6f2c4d7b1feba2e2ea83ad2998e1ac",
    "strategy_5scr_candidate_c2_evaluations_v2.account_snapshot_id": "9d11d94eeb8d66d49da5a69f558da5405d94e4371d60cc5bf2e1d870f8766b97",
    "strategy_5scr_candidate_c2_evaluations_v2.build_evidence_payload": "f18f885cbe479d1669e0ca7709fced59ec83d6b0914451002bb71fb807947fcf",
    "strategy_5scr_candidate_c2_evaluations_v2.candidate_revision": "04dce7f9b7b141142cab40bff83e4e70bceec3df185cdda2d781a5f075bc46af",
    "strategy_5scr_candidate_c2_evaluations_v2.candidate_sequence": "04dce7f9b7b141142cab40bff83e4e70bceec3df185cdda2d781a5f075bc46af",
    "strategy_5scr_candidate_c2_evaluations_v2.context_epoch_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_candidate_c2_evaluations_v2.created_at": "4d69c98ecfac125851d87a272513495e650c525f7608fd520fb4a886fc521446",
    "strategy_5scr_candidate_c2_evaluations_v2.decision": "e904a7fc63a418b9592ebafe11e9ca823ba45af13c30cd15dab493c49be68789",
    "strategy_5scr_candidate_c2_evaluations_v2.decision_at": "4c35acdce3298b00dc23b17f8cc26c78dbd68c53b5aab2ff58d7f53097cd5fb2",
    "strategy_5scr_candidate_c2_evaluations_v2.evaluation_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_candidate_c2_evaluations_v2.evaluation_sequence": "04dce7f9b7b141142cab40bff83e4e70bceec3df185cdda2d781a5f075bc46af",
    "strategy_5scr_candidate_c2_evaluations_v2.evidence_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_evaluations_v2.execution_authority": "10f9801083cfeae235e2f5deacf84a46d1e31036b745285d85c737bffc333611",
    "strategy_5scr_candidate_c2_evaluations_v2.execution_box_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_candidate_c2_evaluations_v2.executor_id": "e43e1f39b14f0ecbcb541dcc44d79475324e71a5aabce4f2313b4f6662aaa042",
    "strategy_5scr_candidate_c2_evaluations_v2.formation_evidence_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_evaluations_v2.material_candidate_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_evaluations_v2.material_context_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_evaluations_v2.material_evaluation_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_evaluations_v2.payload": "f18f885cbe479d1669e0ca7709fced59ec83d6b0914451002bb71fb807947fcf",
    "strategy_5scr_candidate_c2_evaluations_v2.reason_code": "a24b0c50dac14530dbe1065eeb5016bb4b02a89b446569e9dfc8f43880a17a22",
    "strategy_5scr_candidate_c2_evaluations_v2.result_execution_campaign_id": "a118564b7f04e37e02e738821e8988c63f39de70b45621b5a69c405de6f52bf2",
    "strategy_5scr_candidate_c2_evaluations_v2.result_reservation_id": "a118564b7f04e37e02e738821e8988c63f39de70b45621b5a69c405de6f52bf2",
    "strategy_5scr_candidate_c2_evaluations_v2.rule_version": "0e9ef2205c7356c5a1935641392a10597d6f2c4d7b1feba2e2ea83ad2998e1ac",
    "strategy_5scr_candidate_c2_evaluations_v2.source_request_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_candidate_c2_evaluations_v2.strategy_direction": "eff2b29d489969268f7508474216e414d753f6b613e22147c4d4951f70bd49f5",
    "strategy_5scr_candidate_c2_evaluations_v2.strategy_lifecycle_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_candidate_c2_evaluations_v2.strategy_thesis_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_candidate_c2_evaluations_v2.symbol": "183eee6fd8ae87fde8ef3e00f1154a72338ac65f31a6e12579f82c5f0d7f0f9d",
    "strategy_5scr_candidate_c2_evaluations_v2.thesis_semantic_identity_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_evaluations_v2.tradeplan_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_candidate_c2_handoffs_v2.accepted_at": "4c35acdce3298b00dc23b17f8cc26c78dbd68c53b5aab2ff58d7f53097cd5fb2",
    "strategy_5scr_candidate_c2_handoffs_v2.account_id": "0e9ef2205c7356c5a1935641392a10597d6f2c4d7b1feba2e2ea83ad2998e1ac",
    "strategy_5scr_candidate_c2_handoffs_v2.account_snapshot_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_handoffs_v2.account_snapshot_id": "9d11d94eeb8d66d49da5a69f558da5405d94e4371d60cc5bf2e1d870f8766b97",
    "strategy_5scr_candidate_c2_handoffs_v2.authority_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_handoffs_v2.broker_geometry_material_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_handoffs_v2.broker_server": "97fbd0bf37f70208a1cb0de3ef99069b0ddd232b057e4ad2f7ba1d1de8b3d2e3",
    "strategy_5scr_candidate_c2_handoffs_v2.build_evidence_payload": "f18f885cbe479d1669e0ca7709fced59ec83d6b0914451002bb71fb807947fcf",
    "strategy_5scr_candidate_c2_handoffs_v2.candidate_price": "810a604821dfed4ff8f6dc3c1fec31b9c8e423ecaa6a9f440ff106260f444adb",
    "strategy_5scr_candidate_c2_handoffs_v2.candidate_revision": "04dce7f9b7b141142cab40bff83e4e70bceec3df185cdda2d781a5f075bc46af",
    "strategy_5scr_candidate_c2_handoffs_v2.candidate_sequence": "04dce7f9b7b141142cab40bff83e4e70bceec3df185cdda2d781a5f075bc46af",
    "strategy_5scr_candidate_c2_handoffs_v2.context_epoch_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_candidate_c2_handoffs_v2.created_at": "4d69c98ecfac125851d87a272513495e650c525f7608fd520fb4a886fc521446",
    "strategy_5scr_candidate_c2_handoffs_v2.execution_authority": "10f9801083cfeae235e2f5deacf84a46d1e31036b745285d85c737bffc333611",
    "strategy_5scr_candidate_c2_handoffs_v2.execution_box_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_candidate_c2_handoffs_v2.execution_mode": "e904a7fc63a418b9592ebafe11e9ca823ba45af13c30cd15dab493c49be68789",
    "strategy_5scr_candidate_c2_handoffs_v2.executor_id": "e43e1f39b14f0ecbcb541dcc44d79475324e71a5aabce4f2313b4f6662aaa042",
    "strategy_5scr_candidate_c2_handoffs_v2.formation_evidence_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_handoffs_v2.handoff_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_candidate_c2_handoffs_v2.material_candidate_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_handoffs_v2.material_context_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_handoffs_v2.payload": "f18f885cbe479d1669e0ca7709fced59ec83d6b0914451002bb71fb807947fcf",
    "strategy_5scr_candidate_c2_handoffs_v2.stop_authority_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_handoffs_v2.stop_loss": "810a604821dfed4ff8f6dc3c1fec31b9c8e423ecaa6a9f440ff106260f444adb",
    "strategy_5scr_candidate_c2_handoffs_v2.strategy_direction": "eff2b29d489969268f7508474216e414d753f6b613e22147c4d4951f70bd49f5",
    "strategy_5scr_candidate_c2_handoffs_v2.strategy_lifecycle_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_candidate_c2_handoffs_v2.strategy_thesis_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_candidate_c2_handoffs_v2.symbol": "183eee6fd8ae87fde8ef3e00f1154a72338ac65f31a6e12579f82c5f0d7f0f9d",
    "strategy_5scr_candidate_c2_handoffs_v2.take_profit": "810a604821dfed4ff8f6dc3c1fec31b9c8e423ecaa6a9f440ff106260f444adb",
    "strategy_5scr_candidate_c2_handoffs_v2.target_authority_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_handoffs_v2.thesis_semantic_identity_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_candidate_c2_handoffs_v2.tradeplan_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_execution_campaigns_v2.account_id": "0e9ef2205c7356c5a1935641392a10597d6f2c4d7b1feba2e2ea83ad2998e1ac",
    "strategy_5scr_execution_campaigns_v2.authority_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_execution_campaigns_v2.broker_execution_authority": "10f9801083cfeae235e2f5deacf84a46d1e31036b745285d85c737bffc333611",
    "strategy_5scr_execution_campaigns_v2.canonical_symbol": "183eee6fd8ae87fde8ef3e00f1154a72338ac65f31a6e12579f82c5f0d7f0f9d",
    "strategy_5scr_execution_campaigns_v2.command_authority": "10f9801083cfeae235e2f5deacf84a46d1e31036b745285d85c737bffc333611",
    "strategy_5scr_execution_campaigns_v2.created_at": "4d69c98ecfac125851d87a272513495e650c525f7608fd520fb4a886fc521446",
    "strategy_5scr_execution_campaigns_v2.direction": "eff2b29d489969268f7508474216e414d753f6b613e22147c4d4951f70bd49f5",
    "strategy_5scr_execution_campaigns_v2.execution_campaign_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_execution_campaigns_v2.execution_mode": "e904a7fc63a418b9592ebafe11e9ca823ba45af13c30cd15dab493c49be68789",
    "strategy_5scr_execution_campaigns_v2.opened_at": "4c35acdce3298b00dc23b17f8cc26c78dbd68c53b5aab2ff58d7f53097cd5fb2",
    "strategy_5scr_execution_campaigns_v2.payload": "f18f885cbe479d1669e0ca7709fced59ec83d6b0914451002bb71fb807947fcf",
    "strategy_5scr_execution_campaigns_v2.reservation_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_execution_campaigns_v2.risk_authority": "8d8509b414f32f45691143bdf25fb00c29daf9de84e0567d713566b5b7ae3716",
    "strategy_5scr_execution_campaigns_v2.state": "183eee6fd8ae87fde8ef3e00f1154a72338ac65f31a6e12579f82c5f0d7f0f9d",
    "strategy_5scr_execution_campaigns_v2.state_version": "c52d5af39d5c8c12966ab6c4c2291bf06645a57aae2b60dd59df73598fdeb28a",
    "strategy_5scr_execution_campaigns_v2.terminal_at": "7916a7a9a05464c0a93d9cb27adf89734fc2b9394725b6be3030a68d21ef245b",
    "strategy_5scr_execution_campaigns_v2.terminal_reason": "6ab1073675556762e6c73af36a41dcbf9b3562ed9044f6577f183438acd2adb1",
    "strategy_5scr_execution_campaigns_v2.tradeplan_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_final_signal_outbox_v2.account_id": "0e9ef2205c7356c5a1935641392a10597d6f2c4d7b1feba2e2ea83ad2998e1ac",
    "strategy_5scr_final_signal_outbox_v2.account_snapshot_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_final_signal_outbox_v2.account_snapshot_id": "97fbd0bf37f70208a1cb0de3ef99069b0ddd232b057e4ad2f7ba1d1de8b3d2e3",
    "strategy_5scr_final_signal_outbox_v2.authority_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_final_signal_outbox_v2.broker_execution_authority": "10f9801083cfeae235e2f5deacf84a46d1e31036b745285d85c737bffc333611",
    "strategy_5scr_final_signal_outbox_v2.broker_server": "97fbd0bf37f70208a1cb0de3ef99069b0ddd232b057e4ad2f7ba1d1de8b3d2e3",
    "strategy_5scr_final_signal_outbox_v2.broker_symbol": "73d097939b3256196285ff3d76f698353d18406365f77e6fea0b3dc3b8265001",
    "strategy_5scr_final_signal_outbox_v2.candidate_evidence_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_final_signal_outbox_v2.canonical_symbol": "183eee6fd8ae87fde8ef3e00f1154a72338ac65f31a6e12579f82c5f0d7f0f9d",
    "strategy_5scr_final_signal_outbox_v2.command_authority": "10f9801083cfeae235e2f5deacf84a46d1e31036b745285d85c737bffc333611",
    "strategy_5scr_final_signal_outbox_v2.created_at": "4c35acdce3298b00dc23b17f8cc26c78dbd68c53b5aab2ff58d7f53097cd5fb2",
    "strategy_5scr_final_signal_outbox_v2.delivery_authority": "10f9801083cfeae235e2f5deacf84a46d1e31036b745285d85c737bffc333611",
    "strategy_5scr_final_signal_outbox_v2.direction": "eff2b29d489969268f7508474216e414d753f6b613e22147c4d4951f70bd49f5",
    "strategy_5scr_final_signal_outbox_v2.entry_role": "e904a7fc63a418b9592ebafe11e9ca823ba45af13c30cd15dab493c49be68789",
    "strategy_5scr_final_signal_outbox_v2.execution_campaign_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_final_signal_outbox_v2.executor_id": "e43e1f39b14f0ecbcb541dcc44d79475324e71a5aabce4f2313b4f6662aaa042",
    "strategy_5scr_final_signal_outbox_v2.existing_risk_evidence_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_final_signal_outbox_v2.governance_evidence_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_final_signal_outbox_v2.handoff_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_final_signal_outbox_v2.material_candidate_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_final_signal_outbox_v2.outbox_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_final_signal_outbox_v2.payload": "f18f885cbe479d1669e0ca7709fced59ec83d6b0914451002bb71fb807947fcf",
    "strategy_5scr_final_signal_outbox_v2.payload_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_final_signal_outbox_v2.reservation_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_final_signal_outbox_v2.risk_lock_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_final_signal_outbox_v2.signal_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_final_signal_outbox_v2.state_version": "c52d5af39d5c8c12966ab6c4c2291bf06645a57aae2b60dd59df73598fdeb28a",
    "strategy_5scr_final_signal_outbox_v2.status": "e904a7fc63a418b9592ebafe11e9ca823ba45af13c30cd15dab493c49be68789",
    "strategy_5scr_final_signal_outbox_v2.symbol_capability_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_final_signal_outbox_v2.terminal_at": "7916a7a9a05464c0a93d9cb27adf89734fc2b9394725b6be3030a68d21ef245b",
    "strategy_5scr_final_signal_outbox_v2.terminal_reason": "6ab1073675556762e6c73af36a41dcbf9b3562ed9044f6577f183438acd2adb1",
    "strategy_5scr_final_signal_outbox_v2.tradeplan_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_risk_reservations_v2.account_id": "0e9ef2205c7356c5a1935641392a10597d6f2c4d7b1feba2e2ea83ad2998e1ac",
    "strategy_5scr_risk_reservations_v2.account_snapshot_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_risk_reservations_v2.account_snapshot_id": "97fbd0bf37f70208a1cb0de3ef99069b0ddd232b057e4ad2f7ba1d1de8b3d2e3",
    "strategy_5scr_risk_reservations_v2.authority_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_risk_reservations_v2.broker_execution_authority": "10f9801083cfeae235e2f5deacf84a46d1e31036b745285d85c737bffc333611",
    "strategy_5scr_risk_reservations_v2.broker_server": "97fbd0bf37f70208a1cb0de3ef99069b0ddd232b057e4ad2f7ba1d1de8b3d2e3",
    "strategy_5scr_risk_reservations_v2.broker_symbol": "73d097939b3256196285ff3d76f698353d18406365f77e6fea0b3dc3b8265001",
    "strategy_5scr_risk_reservations_v2.canonical_symbol": "183eee6fd8ae87fde8ef3e00f1154a72338ac65f31a6e12579f82c5f0d7f0f9d",
    "strategy_5scr_risk_reservations_v2.command_authority": "10f9801083cfeae235e2f5deacf84a46d1e31036b745285d85c737bffc333611",
    "strategy_5scr_risk_reservations_v2.created_at": "4d69c98ecfac125851d87a272513495e650c525f7608fd520fb4a886fc521446",
    "strategy_5scr_risk_reservations_v2.direction": "eff2b29d489969268f7508474216e414d753f6b613e22147c4d4951f70bd49f5",
    "strategy_5scr_risk_reservations_v2.entry_price": "810a604821dfed4ff8f6dc3c1fec31b9c8e423ecaa6a9f440ff106260f444adb",
    "strategy_5scr_risk_reservations_v2.entry_role": "e904a7fc63a418b9592ebafe11e9ca823ba45af13c30cd15dab493c49be68789",
    "strategy_5scr_risk_reservations_v2.execution_campaign_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_risk_reservations_v2.execution_mode": "e904a7fc63a418b9592ebafe11e9ca823ba45af13c30cd15dab493c49be68789",
    "strategy_5scr_risk_reservations_v2.executor_id": "e43e1f39b14f0ecbcb541dcc44d79475324e71a5aabce4f2313b4f6662aaa042",
    "strategy_5scr_risk_reservations_v2.existing_risk_evidence_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_risk_reservations_v2.expires_at": "4c35acdce3298b00dc23b17f8cc26c78dbd68c53b5aab2ff58d7f53097cd5fb2",
    "strategy_5scr_risk_reservations_v2.governance_evidence_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_risk_reservations_v2.handoff_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_risk_reservations_v2.payload": "f18f885cbe479d1669e0ca7709fced59ec83d6b0914451002bb71fb807947fcf",
    "strategy_5scr_risk_reservations_v2.reservation_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_risk_reservations_v2.reserved_at": "4c35acdce3298b00dc23b17f8cc26c78dbd68c53b5aab2ff58d7f53097cd5fb2",
    "strategy_5scr_risk_reservations_v2.reserved_risk_usd": "810a604821dfed4ff8f6dc3c1fec31b9c8e423ecaa6a9f440ff106260f444adb",
    "strategy_5scr_risk_reservations_v2.risk_authority": "8d8509b414f32f45691143bdf25fb00c29daf9de84e0567d713566b5b7ae3716",
    "strategy_5scr_risk_reservations_v2.risk_lock_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_risk_reservations_v2.risk_unit_usd": "810a604821dfed4ff8f6dc3c1fec31b9c8e423ecaa6a9f440ff106260f444adb",
    "strategy_5scr_risk_reservations_v2.state": "183eee6fd8ae87fde8ef3e00f1154a72338ac65f31a6e12579f82c5f0d7f0f9d",
    "strategy_5scr_risk_reservations_v2.state_version": "c52d5af39d5c8c12966ab6c4c2291bf06645a57aae2b60dd59df73598fdeb28a",
    "strategy_5scr_risk_reservations_v2.stop_loss": "810a604821dfed4ff8f6dc3c1fec31b9c8e423ecaa6a9f440ff106260f444adb",
    "strategy_5scr_risk_reservations_v2.symbol_capability_hash": "78f49185f109bdf9c3451bf0194fd4a611a56af628014cfe540e00038404f92e",
    "strategy_5scr_risk_reservations_v2.take_profit": "810a604821dfed4ff8f6dc3c1fec31b9c8e423ecaa6a9f440ff106260f444adb",
    "strategy_5scr_risk_reservations_v2.terminal_at": "7916a7a9a05464c0a93d9cb27adf89734fc2b9394725b6be3030a68d21ef245b",
    "strategy_5scr_risk_reservations_v2.terminal_reason": "6ab1073675556762e6c73af36a41dcbf9b3562ed9044f6577f183438acd2adb1",
    "strategy_5scr_risk_reservations_v2.tradeplan_id": "4110ddcad8c2c613b37141a9b5b60828699b932a45a141d0b95c7b5eeb6bac33",
    "strategy_5scr_risk_reservations_v2.valid_for_execution": "8d8509b414f32f45691143bdf25fb00c29daf9de84e0567d713566b5b7ae3716",
    "strategy_5scr_risk_reservations_v2.volume": "810a604821dfed4ff8f6dc3c1fec31b9c8e423ecaa6a9f440ff106260f444adb",
}
_CONSTRAINT_HASHES: dict[str, str] = {
    "executor_account_snapshots_pkey": "c1e38e2dcbbda1b1f7a10cfd31fe90aaf2b6446118f29677ccca603d95576589",
    "executor_instances_pkey": "5dd920030232032fb92cd0046fda57cfe57eca32868d9381cdc87d07270d0b43",
    "executor_bridge_governance_pkey": "2030e338d598447fafb654db829851f8b807125cd1dd6dbd2d163ec2292abe2a",
    "ck_executor_governance_singleton": "0447b72e04cdd4923600cbd4cff2f72a1e1c8217b97378c419eebd05f85c19c6",
    "ck_5scr_campaign_risk_lock_amounts_v1": "46137d354f01cb96e0656acd7ee57eff34286fb4cb6bf71990cdce2af6aa4283",
    "ck_5scr_campaign_risk_lock_lifecycle_v1": "88e545ecbf9c658cf6082e17bfa51475dd17967affef7b3761bd903736278593",
    "ck_5scr_campaign_risk_lock_state_v1": "69acc2ebc3782805f9fcc8a149fa841ff3d259b9e8538950532bb8e6ab4cd3d1",
    "ck_5scr_campaign_risk_lock_v2_amounts": "2f702739d66113173a0bbb50374480e1623af64ad28af287d305159aa410119e",
    "ck_5scr_campaign_risk_lock_v2_authority": "41affb053cf67b2ce682a0975c5e44a2374b4c2b1862ef722be34949338204cd",
    "ck_5scr_campaign_risk_lock_v2_identity": "9315bbcf35476ae30698221797658ab3cde60d964a26beec45fc6d408d563a0a",
    "ck_5scr_campaign_risk_lock_v2_state": "8905575ecf33076b6ca57d6c4bb0ca844492d555493b7fbb57aab9da23ad8a7d",
    "ck_5scr_campaign_risk_lock_v2_state_version": "88c8b2e06edd1182e186c64ed2be5186570aeaf0e047412cccdde9b05daf13bd",
    "ck_5scr_candidate_c2_evaluation_v2_decision": "0b8d38640a5cf6048dbbce12305c48667db8aca869ab28eb95e14b9f8baa18d5",
    "ck_5scr_candidate_c2_evaluation_v2_identity": "f1716ea619cf0884dd544e29f63cf88be8ae781e070bf4391b4038971966c12f",
    "ck_5scr_candidate_c2_evaluation_v2_result": "fb3007740d71f530e5b3c89601e809608e0a82662a1ac85a551af04237bc4599",
    "ck_5scr_candidate_c2_evaluation_v2_shadow": "fd6139c242d5f03402a3d4de24a6a2053f15d2c08621e7dbb0e91db7e546b75e",
    "ck_5scr_candidate_c2_handoff_v2_geometry": "5e53df726c89c65df5d73b00639295cfc04c8432e146a4a89c4cb71970b93f1f",
    "ck_5scr_candidate_c2_handoff_v2_identity": "be9eed94652e83459b5fb52d67172b9ca78c3f140ae58a800b231fba7132bfde",
    "ck_5scr_candidate_c2_handoff_v2_payload": "183b1b976bc256c0a0ff23ae054228381fb81e164e8ed181982f1b8728446430",
    "ck_5scr_candidate_c2_handoff_v2_shadow": "80e742d35531246349b7dd5c193184178ef6d9a270e74839aacfde1889dabf33",
    "ck_5scr_execution_campaign_v2_authority": "7801cf92caf440b4832dfd1ab03622e24a7316e65b062e1eb75fa71107acf6d7",
    "ck_5scr_execution_campaign_v2_identity": "9ec5ad60e7d2ebe89268818a5a233354ddaa07f8de81a07be64d230c0aa7e322",
    "ck_5scr_execution_campaign_v2_lifecycle": "7adccc23656b7158be03b6ae60333d0d0a71a669e3083f5a602f387bb030f057",
    "ck_5scr_execution_campaign_v2_state": "b6f82f436947b7ccacf69ae84be33e37968463dd16fc7845e809d2aed7b7fcfd",
    "ck_5scr_execution_campaign_v2_state_version": "88c8b2e06edd1182e186c64ed2be5186570aeaf0e047412cccdde9b05daf13bd",
    "ck_5scr_final_signal_outbox_v2_dark": "ee520f7910acd8c590a83200a31f2f59ac4356df5e34acfa75f9f375de450479",
    "ck_5scr_final_signal_outbox_v2_identity": "47f96b5adfa4ecacf611e6acdd341ecdd0e18aa390709ee2f00b7bc38896b4e9",
    "ck_5scr_final_signal_outbox_v2_lifecycle": "4ed1ce910dd7185195482a67cc30ab440ee21bf18062490ca5adc2099c9a7e05",
    "ck_5scr_final_signal_outbox_v2_payload": "c41a7b47293ec139ff9be9e1c236c1c1136cbabf2f378977c4d5f670952ca2b5",
    "ck_5scr_final_signal_outbox_v2_state_version": "88c8b2e06edd1182e186c64ed2be5186570aeaf0e047412cccdde9b05daf13bd",
    "ck_5scr_risk_reservation_v2_authority": "4a23833f19db6fe3b870f0c9066295d842b9993abad203ccaaa4e6e7be55d8d9",
    "ck_5scr_risk_reservation_v2_geometry": "9739a8f8ac7e3c890fbdf3183c6f1619072955e425ed7aa26f554f5973755ec7",
    "ck_5scr_risk_reservation_v2_identity": "94c2ee68273d8175fb6f5c56c73d8ce5f91a1fc6cc38db61ea50be70d87ba6b3",
    "ck_5scr_risk_reservation_v2_lifecycle": "909bb778ea9985009363f09d78271e469ffe2eb03256c507447bae9b5011a51d",
    "ck_5scr_risk_reservation_v2_state": "31b9b216a877be509df51b58a45cb153838c5a0c8315fe815933ab5c42431b70",
    "ck_5scr_risk_reservation_v2_state_version": "88c8b2e06edd1182e186c64ed2be5186570aeaf0e047412cccdde9b05daf13bd",
    "ck_5scr_risk_reservation_amounts_v1": "acd81faed5928eff180c423ab0fed04574d0e4594f6152a868f4b8be65f3c723",
    "ck_5scr_risk_reservation_lifecycle_v1": "15bc797b135f1a87eceadb8b27e763ce2c0e553c3e285fedfdee94a4a134dea9",
    "ck_5scr_risk_reservation_state_v1": "e1b110dbb765f078e9c99b70b5bdc376dfe1d28bbd49bb598d5385c3b3db95fb",
    "ck_executor_account_snapshot_c2_reconciliation_v2": "8171fdb49ec3bcf940fcc75ab0beb267997e8e9870640137dfcdf095a487d132",
    "fk_5scr_campaign_risk_lock_v2_campaign": "10e57fc8a5c8c2c61a830e8164132079c89c6206ff72e9ace390e80ef7b37118",
    "fk_5scr_campaign_risk_lock_v2_handoff_scope": "f097aaa722871576fc4449f30d4180b73f078ec7b3f64b17804ee11534aaefc6",
    "fk_5scr_candidate_c2_evaluation_v2_candidate_scope": "6f9224f91517979d11d932ab5144b093b1ce10f511c1d6c11cacf0b04fde7e8e",
    "fk_5scr_candidate_c2_evaluation_v2_result_scope": "d532b0599810bffbd022983da7bdc40c7fbe570a702efa374ecfd4adc34451ed",
    "fk_5scr_candidate_c2_evaluation_v2_snapshot_scope": "07f5236c85198c84ee2056c0f1f6402b261014a50ccf03baeeec88e25ab6f164",
    "fk_5scr_candidate_c2_handoff_v2_candidate_scope": "6f9224f91517979d11d932ab5144b093b1ce10f511c1d6c11cacf0b04fde7e8e",
    "fk_5scr_candidate_c2_handoff_v2_snapshot_scope": "07f5236c85198c84ee2056c0f1f6402b261014a50ccf03baeeec88e25ab6f164",
    "fk_5scr_execution_campaign_v2_reservation_scope": "191521a1dcf4b4eb1d8aaad29eb2b17e900d296a77476f0170fe7eea0423311a",
    "fk_5scr_final_signal_outbox_v2_campaign_scope": "4a2df90221a8fd5332ec84d72705a6f32dc443533a12fa8e3fd0c0fbf2bd92bf",
    "fk_5scr_final_signal_outbox_v2_handoff_scope": "5812ecb499c49185c1f38f1c5a8a976864f4647f9a2f21394f93f6e6b13cd8b5",
    "fk_5scr_final_signal_outbox_v2_reservation_scope": "d85be255c0a5b44cef8216d0ac1d8d55e764af7c3d54a044f5b726db2b6d8f7f",
    "fk_5scr_final_signal_outbox_v2_risk_lock_scope": "ede8fe8f4a19570cc4c3c6aaf5863cb20c7dc66fe3dd243cc67a6d375c632940",
    "fk_5scr_final_signal_outbox_v2_snapshot_scope": "07f5236c85198c84ee2056c0f1f6402b261014a50ccf03baeeec88e25ab6f164",
    "fk_5scr_risk_reservation_v2_campaign": "10e57fc8a5c8c2c61a830e8164132079c89c6206ff72e9ace390e80ef7b37118",
    "fk_5scr_risk_reservation_v2_handoff_scope": "5812ecb499c49185c1f38f1c5a8a976864f4647f9a2f21394f93f6e6b13cd8b5",
    "fk_5scr_risk_reservation_v2_lock_scope": "7ec09bfb8d7d65df551cca548f43733f30e13a73e023b0759b92ea9d9d0af826",
    "fk_5scr_risk_reservation_v2_snapshot_scope": "07f5236c85198c84ee2056c0f1f6402b261014a50ccf03baeeec88e25ab6f164",
    "pk_5scr_campaign_risk_lock_v2": "3567d2246610cae429c3b31d51b8d11e03676cac69d0907cbecfba2fd74ba8c6",
    "pk_5scr_candidate_c2_evaluation_v2": "cc5a2fb5a1764a7e8ea36189f516f34698cc47449df36eb8731d9d6017b85b65",
    "pk_5scr_candidate_c2_handoff_v2": "7d2f7a885b120b593e66a0b73ad09b40d245d69f76b98851ae56f65c94e10103",
    "pk_5scr_execution_campaign_v2": "16cc6a61624682d2c02c7c43877070be2bf233a05c8d41b5ae28d9ddb57b6ee0",
    "pk_5scr_final_signal_outbox_v2": "66060e6653fde114e853a55e2ffe9b592976948dc2505d2d3190652c3d76b18f",
    "pk_5scr_risk_reservation_v2": "c1c1076fe4d1aa7d6352076b60195f7a896513bc529d6856dda85e6283da4e22",
    "uq_5scr_campaign_risk_lock_v2_campaign": "596e9a8af9e00209870ede3c02ab62b730fea86a215cb54f4abe7b68edff6440",
    "uq_5scr_campaign_risk_lock_v2_handoff": "778d89a20bdf26ec3873f9922c87f7c7056a4cb76b47851fe83abbb1ec4baad2",
    "uq_5scr_campaign_risk_lock_v2_reservation_risk_scope": "9ef2c00473fb3e98eeeba8fcdaee79858c44cb076caa50ac3762446cabbb48d8",
    "uq_5scr_campaign_risk_lock_v2_reservation_scope": "819df5a368867d72a9f57d35cc4e56c2925185430c477f8dc4974c3ec6f9b48c",
    "uq_5scr_candidate_c2_evaluation_v2_clock": "ac6ca55267710b8a5c6c429e41654d27ea4569ee8211040ebdee5c8a02620805",
    "uq_5scr_candidate_c2_evaluation_v2_request": "1ca8bb8668a70cf679f05bfa8978fbd2d88c3544d50327f4f55704199c2fcda9",
    "uq_5scr_candidate_c2_evaluation_v2_sequence": "9995b8cade14da657a1d3d402741344194f38ad70088207926ffcdb91ed92480",
    "uq_5scr_candidate_c2_handoff_v2_candidate": "d6c83ab547507378339edd1da121d65d411060730d5182e7ab2965bf4d9a0dc6",
    "uq_5scr_candidate_c2_handoff_v2_outbox_scope": "e0e25d37b8e673b95031c9bc11c9f1ddc96172967dd861b2aa6e8da5dd81f67a",
    "uq_5scr_candidate_c2_handoff_v2_risk_scope": "238324685d8fb2f25546b18e9eab19484754183bfab3051876b82a2b24be5a59",
    "uq_5scr_execution_campaign_v2_outbox_scope": "cd309a23c081bf746173ca93ae121cf1299f811fc72ef9abf498e753e2485f9d",
    "uq_5scr_execution_campaign_v2_reservation": "bf974e1a29076468ca984bb0eefc239b28b27948177d1363b782641821962140",
    "uq_5scr_execution_campaign_v2_tradeplan": "d6c83ab547507378339edd1da121d65d411060730d5182e7ab2965bf4d9a0dc6",
    "uq_5scr_final_signal_outbox_v2_campaign": "596e9a8af9e00209870ede3c02ab62b730fea86a215cb54f4abe7b68edff6440",
    "uq_5scr_final_signal_outbox_v2_reservation": "bf974e1a29076468ca984bb0eefc239b28b27948177d1363b782641821962140",
    "uq_5scr_final_signal_outbox_v2_signal": "e39ed74acf620290f9cda675653677c97b71eba3c9691b18026f5916a3c38fd6",
    "uq_5scr_final_signal_outbox_v2_tradeplan": "d6c83ab547507378339edd1da121d65d411060730d5182e7ab2965bf4d9a0dc6",
    "uq_5scr_risk_reservation_v2_campaign": "596e9a8af9e00209870ede3c02ab62b730fea86a215cb54f4abe7b68edff6440",
    "uq_5scr_risk_reservation_v2_campaign_scope": "fc58d211b7f8957fcf200e77803b06ff5fb111bfde7bc293eaff1bea806549d9",
    "uq_5scr_risk_reservation_v2_evaluation_scope": "cf9ec53a0d8ceb3f114f33b3c805bc860e6f70100785ad0f29825352fc871af2",
    "uq_5scr_risk_reservation_v2_execution_campaign_scope": "e95470ad090bd1f5694c9bb7124ccfaa6f61168a3814024add42c26a5fd94801",
    "uq_5scr_risk_reservation_v2_handoff": "778d89a20bdf26ec3873f9922c87f7c7056a4cb76b47851fe83abbb1ec4baad2",
    "uq_5scr_risk_reservation_v2_risk_lock": "e1333992c9124c3e5ed747de353d52673352eafafe84b795ad96acd149c49ce7",
    "uq_5scr_risk_reservation_v2_tradeplan": "d6c83ab547507378339edd1da121d65d411060730d5182e7ab2965bf4d9a0dc6",
    "uq_5scr_tradeplan_candidate_v2_c2_scope": "41f45c5329d52e5ac149053bf94b37bc7c3e56dcd5ff815ad986945c4b10c881",
    "uq_executor_account_snapshot_c2_scope_v2": "cc606a3eca56a0edbbd245fa9eb873d410f50d4170b1c346053dbad430fd94c3",
}
_INDEX_HASHES: dict[str, str] = {
    "ix_5scr_c2_evaluation_v2_candidate_scope": "79784dda443533a5a3b71f9435204ec72923a41d5c213be2d0d1949e8698996d",
    "ix_5scr_c2_evaluation_v2_result_scope": "0d199fff08ae12bb64d0559b1be23d5d7c1e5bbc431604522322586a9ff494c8",
    "ix_5scr_c2_evaluation_v2_snapshot_scope": "d42128bb6a14cc23f4452afed900739c46aa81b441184e47ffce4b17805b5755",
    "ix_5scr_c2_handoff_v2_executor": "a0edb2b7f92a0ae1b1e37a67ef5c4727a521c00449bc7cf4c31a8f28e7cd0c77",
    "ix_5scr_c2_handoff_v2_snapshot_scope": "b4ebc9a99c324f17e551569a43af4e8a4309ce18327b79a897be2ad733bd1713",
    "ix_5scr_c2_outbox_v2_handoff_scope": "c7b90a34b999dcc01cf73278dbd1ec0a1e7fc1f0017fe9d0ad42aee87cfb5095",
    "ix_5scr_c2_outbox_v2_risk_lock_scope": "572b6d299e366bafa8b3afb36bc3c6a5b8cef835280603821033249e1dbbad39",
    "ix_5scr_c2_outbox_v2_snapshot_scope": "30b56f82c14b113e4880dda92133ba7138ced887fc08a324e128ce6eccb27c27",
    "ix_5scr_c2_reservation_v2_executor_state": "cc14573f1e4644a6babc40568f9dd658c846f424d0b21c2cc599cbc480361a74",
    "ix_5scr_c2_reservation_v2_snapshot_scope": "53ef5d25963a58d2076f31c62b9ce0be8c6877d4441447377c90ab6d64d1586e",
    "ix_5scr_c2_risk_lock_v2_snapshot": "80e912548d28db55191d85ac66fb3b52e0b06caeba49688196218783bdff9006",
    "ix_5scr_campaign_risk_lock_v2_account": "900cf7aa43a2238418ca35336117e08a54bb5665d502027296acad9cc01e0b97",
    "ix_5scr_campaign_risk_locks_account_state": "5b10cce49388c0242cbdc2839540dac1583bec844f3428e2b6181cb4fb3dd172",
    "ix_5scr_candidate_c2_evaluation_v2_history": "f967a5bbcf66b4a9845589ef2eeaa4d844b3f741883b261a1e8f7e8e12fa8e62",
    "ix_5scr_candidate_c2_handoff_v2_lifecycle": "f20118698f411b31d24577acf0e6a78b9e844a51240b162dec6f10bd961b3735",
    "ix_5scr_execution_campaign_v2_account_state": "a773551c8adff33a541a72433b98d791979c5c5bb79d82885e30c70421e9450d",
    "ix_5scr_final_signal_outbox_v2_status": "c3bf54f8ed46a48311478ef88bde0c8cc3464c61cfb4383ee2299a6201462c1e",
    "ix_5scr_risk_reservation_v2_account_expiry": "f99e190591330ace31d71261a2467a0577a75052964ee9cf969d8091c2b7fd24",
    "ix_5scr_risk_reservations_account_state": "972f13ee30a776707adb6ec0e198da65a0a094cf63600e6e5508e65476b8adcb",
    "ix_executor_snapshots_executor_captured": "ec517ec60d862acd264ddd54356521f09d26f6c033da944a1433882d5aaa032d",
}
_TRIGGER_HASHES: dict[str, tuple[str, str]] = {
    "trg_5scr_campaign_risk_lock_update_v1": (
        "fc25d8392f872a194fdcb98363e889ea21b9d7e0abcb18a6e0f611bed389d13e",
        "954709ce4239ca0b77da26cd21430b3d7998a18c90a35b02c75c7cb0444592e6",
    ),
    "trg_5scr_guard_account_snapshot_c2_update_v2": (
        "9309803652e7cd767738578e034696dcca6eb0777ecc9432e629d6871dccd7c8",
        "da208cfba9ca31b20b9020f21c05a9ca560076bb358216b33406d6b8e64e55f2",
    ),
    "trg_5scr_guard_execution_command_against_c2_v2": (
        "c04af2eeb0106180e78296b11a4d9198dc23ad50fe2716663feff04807850055",
        "fe2430a73df1e56963112d6ca4a1c1d3fafd7f308ecc92517c504f25aba41ff0",
    ),
    "trg_5scr_guard_executor_identity_against_c2_v2": (
        "7b1dcf5cd6a6cd60e5bdfbe029c0835a6a556c0c4404ee87599ef13eb1a38ba4",
        "f770b025a672db0b576eb368ac229390694d751155c87b92351bb8c7f54418e1",
    ),
    "trg_5scr_guard_legacy_campaign_risk_against_c2_v2": (
        "3ca3e023490629fb9ad116d454afbdbb1fad2d5fc06e4b3b26dacfed4d903274",
        "c6bb9978d4a2a342e8b2727ee42249073541134d5a7f569f0861621bbe2d6a73",
    ),
    "trg_5scr_guard_legacy_reservation_against_c2_v2": (
        "64443c8ce79168bac8540b8d93a933a7e336b135d6a13639874072cd10895d54",
        "2d36c07dcc52652bb350cf78ae3fd166bb6e694d28fbe74348bc75f0437c8b11",
    ),
    "trg_5scr_guard_strategy_5scr_campaign_risk_locks_v2_transition": (
        "288586da38dfcab38d7bb5182ca5015fed4ec9fa7d3f413204ee0f55e0a0e0bb",
        "d861f1eae0e8d299ed398433d528130d30b7f22a8613e3b83e4a5a68d57863e8",
    ),
    "trg_5scr_guard_strategy_5scr_execution_campaigns_v2_transition": (
        "aa2b28e54957159d4f43a6753db3db92f19921e1a2153c2ac157df828ebd1e1f",
        "15135d267995f7533448dc350f828d5d9838f33874c771ab6f529716ccd9bcb3",
    ),
    "trg_5scr_guard_strategy_5scr_final_signal_outbox_v2_transition": (
        "97543f8bd5c88e7635527d01f08774fb3b813a34b6e728912bca74fe61c3e220",
        "fce6b4de0941eab3e357463dfd2f6049244c3c34b0c1f436aebe1ea5e277f539",
    ),
    "trg_5scr_guard_strategy_5scr_risk_reservations_v2_transition": (
        "58f60524549308fbaf65d001480b59033c03d4cf3c5d31247f0c0a61fbc95f7e",
        "7b40d510f07226542bb9f4024fd9ad4d1ad8ac18b4835a979e33eba2d7eece68",
    ),
    "trg_5scr_reject_c2_evaluation_v2_mutation": (
        "c23c4d4b3ec25de8221cb1cf780a0b9e22bb27f1ddaed983c45620ef27429282",
        "a908d5a718784882de7423bf5adb4059808ca3cebe2d23ca84708565711ae077",
    ),
    "trg_5scr_reject_c2_handoff_v2_mutation": (
        "73a3cc5e05b8f04417c3ff9703d2f68827a53555a2fd7df06889718dc04e84ff",
        "37ed5c7483af1db7f847a8a39b632fb547ecad642dd2f2abbaa8925c422038a7",
    ),
    "trg_5scr_risk_reservation_update_v1": (
        "af3056e46b713b84bb085695033a10218c198f7366733a3375dcf7698d8e7e81",
        "d5d9248923e5d048bd9d9ad246b0b23e539bef5af7d54311d9fec62900dd70d4",
    ),
}


def _candidate_scope(candidate: TradePlanCandidateV2) -> tuple[Any, ...]:
    return (
        candidate.tradeplan_id,
        candidate.strategy_lifecycle_id,
        candidate.context_epoch_id,
        candidate.strategy_thesis_id,
        candidate.execution_box_id,
        candidate.symbol,
        candidate.direction,
        candidate.material_context_hash,
        candidate.thesis_semantic_identity_hash,
        candidate.candidate_sequence,
        candidate.candidate_revision,
        candidate.material_candidate_hash,
        candidate.evidence_hash,
    )


def _rejected_evaluation(
    evidence: CandidateC2ShadowBuildEvidenceV2,
    *,
    sequence: int,
    reason: str,
) -> C2ShadowEvaluationV2:
    material = canonical_hash_v1(
        {
            "tradeplan_id": evidence.candidate.tradeplan_id,
            "candidate_material_hash": evidence.candidate.material_candidate_hash,
            "account_id": evidence.account_snapshot.account_id,
            "executor_id": str(evidence.account_snapshot.executor_id),
            "decision": "REJECTED",
            "reason": reason,
            "campaign_id": None,
            "reservation_id": None,
            "rule_version": "5scr.candidate-c2-shadow.v2",
        }
    )
    identity = {
        "source_request_id": evidence.source_request_id,
        "sequence": sequence,
        "decision_at_utc": evidence.decision_at_utc,
        "evidence_hash": evidence.authority_hash(),
        "material_hash": material,
    }
    evaluation_id = "5scr-c2-eval-v2:" + hashlib.sha256(canonical_hash_v1(identity).encode()).hexdigest()[:32]
    return C2ShadowEvaluationV2(
        evaluation_id=evaluation_id,
        evaluation_sequence=sequence,
        source_request_id=evidence.source_request_id,
        tradeplan_id=evidence.candidate.tradeplan_id,
        material_candidate_hash=evidence.candidate.material_candidate_hash,
        account_id=evidence.account_snapshot.account_id,
        executor_id=evidence.account_snapshot.executor_id,
        decision_at_utc=evidence.decision_at_utc,
        decision="REJECTED",
        reason_code=reason,
        evidence_hash=evidence.authority_hash(),
        material_evaluation_hash=material,
    )


def _payload_model(model: type[Any], row: Any) -> Any:
    payload = _json(_row(row, "payload"))
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise CandidateC2ShadowV2IntegrityError(f"C2_DURABLE_PAYLOAD_INVALID:{model.__name__}") from exc


def _validate_bundle_lifecycle(rows: Mapping[str, Any]) -> bool:
    """Validate the mutable lifecycle overlay and report whether it is live."""

    risk_state = str(_row(rows[RISK_LOCK_TABLE], "state"))
    reservation_state = str(_row(rows[RESERVATION_TABLE], "state"))
    campaign_state = str(_row(rows[CAMPAIGN_TABLE], "state"))
    outbox_status = str(_row(rows[OUTBOX_TABLE], "status"))
    states = (risk_state, reservation_state, campaign_state, outbox_status)
    clocks = (
        _row(rows[RISK_LOCK_TABLE], "closed_at"),
        _row(rows[RESERVATION_TABLE], "terminal_at"),
        _row(rows[CAMPAIGN_TABLE], "terminal_at"),
        _row(rows[OUTBOX_TABLE], "terminal_at"),
    )
    reasons = (
        _row(rows[RISK_LOCK_TABLE], "terminal_reason"),
        _row(rows[RESERVATION_TABLE], "terminal_reason"),
        _row(rows[CAMPAIGN_TABLE], "terminal_reason"),
        _row(rows[OUTBOX_TABLE], "terminal_reason"),
    )
    versions = tuple(
        int(_row(rows[table], "state_version"))
        for table in (RISK_LOCK_TABLE, RESERVATION_TABLE, CAMPAIGN_TABLE, OUTBOX_TABLE)
    )
    if states == ("ACTIVE", "RESERVED", "PARENT_PENDING", "PENDING"):
        if any(value is not None for value in (*clocks, *reasons)) or versions != (1, 1, 1, 1):
            raise CandidateC2ShadowV2IntegrityError("C2_ACTIVE_AUTHORITY_LIFECYCLE_DRIFT")
        return True
    terminal_campaign = {
        "RELEASED": "INVALIDATED",
        "INVALIDATED": "INVALIDATED",
        "EXPIRED": "EXPIRED",
        "RECONCILIATION_REQUIRED": "RECONCILIATION_REQUIRED",
    }.get(reservation_state)
    if states != ("CLOSED", reservation_state, terminal_campaign, "CANCELLED"):
        raise CandidateC2ShadowV2IntegrityError("C2_AUTHORITY_LIFECYCLE_STATE_DRIFT")
    if any(not isinstance(value, datetime) for value in clocks) or len(set(clocks)) != 1:
        raise CandidateC2ShadowV2IntegrityError("C2_AUTHORITY_LIFECYCLE_CLOCK_DRIFT")
    if any(not isinstance(value, str) or not value for value in reasons) or len(set(reasons)) != 1:
        raise CandidateC2ShadowV2IntegrityError("C2_AUTHORITY_LIFECYCLE_REASON_DRIFT")
    if versions != (2, 2, 2, 2):
        raise CandidateC2ShadowV2IntegrityError("C2_AUTHORITY_LIFECYCLE_VERSION_DRIFT")
    return False


@dataclass(frozen=True, slots=True)
class _ValidatedCandidateAuthority:
    candidate: TradePlanCandidateV2
    terminal: bool
    terminal_at: datetime
    terminal_reason: str


async def _validate_full_box_predecessor_chain(connection: Any, box: ExecutionBoxV1) -> None:
    """Reconstruct every immutable P5 version back to the first occurrence."""

    current = box
    seen = {current.execution_box_id}
    root_scope = (
        box.strategy_lifecycle_id,
        box.context_epoch_id,
        box.strategy_thesis_id,
        box.symbol,
        box.strategy_direction,
        box.route_type,
        box.thesis_semantic_identity_hash,
    )
    while current.box_version > 1:
        predecessor_id = current.previous_execution_box_id
        if predecessor_id is None or predecessor_id in seen:
            raise CandidateC2ShadowV2IntegrityError("C2_PARENT_BOX_PREDECESSOR_CYCLE")
        seen.add(predecessor_id)
        row = await connection.fetchrow(
            f"SELECT * FROM {BOX_TABLE} WHERE execution_box_id=$1 FOR UPDATE",
            predecessor_id,
        )
        if row is None:
            raise CandidateC2ShadowV2IntegrityError("C2_PARENT_BOX_PREDECESSOR_MISSING")
        predecessor = _box_from_row(row)
        predecessor_scope = (
            predecessor.strategy_lifecycle_id,
            predecessor.context_epoch_id,
            predecessor.strategy_thesis_id,
            predecessor.symbol,
            predecessor.strategy_direction,
            predecessor.route_type,
            predecessor.thesis_semantic_identity_hash,
        )
        if (
            predecessor_scope != root_scope
            or predecessor.execution_box_id != predecessor_id
            or predecessor.box_sequence != current.box_sequence - 1
            or predecessor.box_version != current.box_version - 1
            or predecessor.state != "SUPERSEDED"
        ):
            raise CandidateC2ShadowV2IntegrityError("C2_PARENT_BOX_PREDECESSOR_SCOPE_DRIFT")
        current = predecessor

    if current.box_version != 1 or current.previous_execution_box_id is not None:
        raise CandidateC2ShadowV2IntegrityError("C2_PARENT_BOX_PREDECESSOR_SCOPE_DRIFT")


async def _lock_and_validate_candidate_authority(
    connection: Any, tradeplan_id: str
) -> _ValidatedCandidateAuthority | None:
    """Lock and reconstruct the complete P3-P6 authority in global order.

    The preliminary candidate read chooses the lifecycle mutex only.  No
    authority is trusted until the same candidate row is locked and rebuilt.
    """

    preview = await connection.fetchrow(
        f"SELECT strategy_lifecycle_id FROM {CANDIDATE_TABLE} WHERE tradeplan_id=$1",
        tradeplan_id,
    )
    if preview is None:
        return None
    lifecycle_row = await connection.fetchrow(
        f"SELECT * FROM {LIFECYCLE_TABLE} WHERE strategy_lifecycle_id=$1 FOR UPDATE",
        str(_row(preview, "strategy_lifecycle_id")),
    )
    if lifecycle_row is None:
        raise CandidateC2ShadowV2IntegrityError("C2_PARENT_LIFECYCLE_MISSING")
    try:
        lifecycle = _lifecycle_from_row(lifecycle_row)
    except RuntimeError as exc:
        raise CandidateC2ShadowV2IntegrityError("C2_PARENT_LIFECYCLE_DRIFT") from exc
    candidate_row = await connection.fetchrow(
        f"SELECT * FROM {CANDIDATE_TABLE} WHERE tradeplan_id=$1 FOR UPDATE",
        tradeplan_id,
    )
    if candidate_row is None:
        raise CandidateC2ShadowV2IntegrityError("C2_PARENT_CANDIDATE_DISAPPEARED")
    try:
        candidate = _candidate_from_row(candidate_row)
        await _validate_candidate_predecessor_chain(connection, candidate)
    except RuntimeError as exc:
        raise CandidateC2ShadowV2IntegrityError("C2_PARENT_CANDIDATE_DRIFT") from exc
    if candidate.strategy_lifecycle_id != lifecycle.strategy_lifecycle_id or candidate.symbol != lifecycle.symbol:
        raise CandidateC2ShadowV2IntegrityError("C2_PARENT_LIFECYCLE_SCOPE_DRIFT")

    # The terminal lifecycle clock is sufficient to revoke downstream risk;
    # stale/bogus child rows must never keep an existing reservation alive.
    if lifecycle.state in TERMINAL_LIFECYCLE_STATES:
        return _ValidatedCandidateAuthority(
            candidate,
            True,
            _terminal_clock(lifecycle.last_event_at_utc, floor=candidate.decision_at_utc),
            "C2_PARENT_LIFECYCLE_TERMINAL",
        )

    context_row = await connection.fetchrow(
        f"SELECT * FROM {CONTEXT_TABLE} WHERE context_epoch_id=$1 AND strategy_lifecycle_id=$2 FOR UPDATE",
        candidate.context_epoch_id,
        candidate.strategy_lifecycle_id,
    )
    thesis_row = await connection.fetchrow(
        f"SELECT * FROM {THESIS_TABLE} WHERE strategy_thesis_id=$1 FOR UPDATE",
        candidate.strategy_thesis_id,
    )
    if context_row is None or thesis_row is None:
        raise CandidateC2ShadowV2IntegrityError("C2_PARENT_AUTHORITY_MISSING")
    try:
        context = _context_from_row(context_row)
        thesis = _p4_thesis_from_row(thesis_row)
        # Preserve the P4-P6 global order: the immutable H1/M15 proof
        # authority is locked before any execution-box row.
        await Strategy5SCRDirectionalThesisV1Repository._validate_thesis_proof_chain(connection, thesis)
    except RuntimeError as exc:
        raise CandidateC2ShadowV2IntegrityError("C2_PARENT_AUTHORITY_DRIFT") from exc
    box_row = await connection.fetchrow(
        f"SELECT * FROM {BOX_TABLE} WHERE execution_box_id=$1 FOR UPDATE",
        candidate.execution_box_id,
    )
    if box_row is None:
        raise CandidateC2ShadowV2IntegrityError("C2_PARENT_AUTHORITY_MISSING")
    try:
        box = _box_from_row(box_row)
        await _validate_full_box_predecessor_chain(connection, box)
    except CandidateC2ShadowV2IntegrityError:
        # The predecessor walk emits stable, actionable P7 integrity codes
        # for missing, cyclic, or scope-invalid immutable history. Preserve
        # those verdicts while still normalizing foreign P5 reconstruction
        # failures below.
        raise
    except RuntimeError as exc:
        raise CandidateC2ShadowV2IntegrityError("C2_PARENT_AUTHORITY_DRIFT") from exc
    durable_scope = (
        context.strategy_lifecycle_id,
        thesis.strategy_lifecycle_id,
        box.strategy_lifecycle_id,
        context.context_epoch_id,
        thesis.context_epoch_id,
        box.context_epoch_id,
        thesis.strategy_thesis_id,
        box.strategy_thesis_id,
        context.material_context_hash,
        thesis.semantic_identity_hash,
        box.material_box_hash,
        box.freeze_authority_hash,
        context.symbol,
        thesis.symbol,
        box.symbol,
        thesis.strategy_direction,
        box.strategy_direction,
    )
    candidate_scope = (
        candidate.strategy_lifecycle_id,
        candidate.strategy_lifecycle_id,
        candidate.strategy_lifecycle_id,
        candidate.context_epoch_id,
        candidate.context_epoch_id,
        candidate.context_epoch_id,
        candidate.strategy_thesis_id,
        candidate.strategy_thesis_id,
        candidate.material_context_hash,
        candidate.thesis_semantic_identity_hash,
        candidate.execution_box_material_hash,
        candidate.execution_box_freeze_authority_hash,
        candidate.symbol,
        candidate.symbol,
        candidate.symbol,
        candidate.direction,
        candidate.direction,
    )
    if durable_scope != candidate_scope:
        raise CandidateC2ShadowV2IntegrityError("C2_PARENT_AUTHORITY_SCOPE_DRIFT")
    terminal = (
        candidate.lifecycle_state != "ACTIVE"
        or context.state != "ACTIVE"
        or thesis.state != "ACTIVE"
        or box.state != "FROZEN"
    )
    terminal_clocks = (
        _row(candidate_row, "superseded_at"),
        _row(candidate_row, "invalidated_at"),
        _row(candidate_row, "expired_at"),
        context.closed_at_utc,
        thesis.closed_at_utc,
        box.superseded_at_utc,
        box.invalidated_at_utc,
        box.consumed_at_utc,
        box.expired_at_utc,
    )
    terminal_at = (
        _terminal_clock(*terminal_clocks, floor=candidate.decision_at_utc) if terminal else candidate.decision_at_utc
    )
    return _ValidatedCandidateAuthority(candidate, terminal, terminal_at, "C2_PARENT_AUTHORITY_TERMINAL")


def _bundle_from_rows(rows: Mapping[str, Any]) -> C2ShadowAuthorityBundleV2:
    handoff = _payload_model(CandidateC2ShadowHandoffV2, rows[HANDOFF_TABLE])
    risk_lock = _payload_model(C2ShadowCampaignRiskLockV2, rows[RISK_LOCK_TABLE])
    reservation = _payload_model(C2ShadowRiskReservationV2, rows[RESERVATION_TABLE])
    campaign = _payload_model(C2ShadowExecutionCampaignV2, rows[CAMPAIGN_TABLE])
    signal = _payload_model(C2ShadowFinalSignalV2, rows[OUTBOX_TABLE])
    try:
        bundle = C2ShadowAuthorityBundleV2(
            handoff=handoff,
            risk_lock=risk_lock,
            reservation=reservation,
            execution_campaign=campaign,
            final_signal=signal,
        )
    except ValidationError as exc:
        raise CandidateC2ShadowV2IntegrityError("C2_DURABLE_BUNDLE_SCOPE_DRIFT") from exc
    expected = {
        HANDOFF_TABLE: {
            "handoff_id": handoff.handoff_id,
            "tradeplan_id": handoff.tradeplan_id,
            "strategy_lifecycle_id": handoff.strategy_lifecycle_id,
            "context_epoch_id": handoff.context_epoch_id,
            "strategy_thesis_id": handoff.strategy_thesis_id,
            "execution_box_id": handoff.execution_box_id,
            "account_id": handoff.account_id,
            "executor_id": handoff.executor_id,
            "broker_server": handoff.broker_server,
            "account_snapshot_id": handoff.account_snapshot_id,
            "account_snapshot_hash": handoff.account_snapshot_hash,
            "symbol": handoff.symbol,
            "strategy_direction": handoff.direction,
            "material_context_hash": handoff.material_context_hash,
            "thesis_semantic_identity_hash": handoff.thesis_semantic_identity_hash,
            "candidate_sequence": handoff.candidate_sequence,
            "candidate_revision": handoff.candidate_revision,
            "material_candidate_hash": handoff.material_candidate_hash,
            "formation_evidence_hash": handoff.candidate_evidence_hash,
            "candidate_price": handoff.candidate_price,
            "stop_loss": handoff.stop_loss,
            "take_profit": handoff.take_profit,
            "target_authority_hash": handoff.target_authority_hash,
            "stop_authority_hash": handoff.stop_authority_hash,
            "broker_geometry_material_hash": handoff.broker_geometry_material_hash,
            "accepted_at": handoff.accepted_at_utc,
            "authority_hash": handoff.authority_hash,
            "execution_mode": "SHADOW",
            "execution_authority": False,
        },
        RISK_LOCK_TABLE: {
            "risk_lock_id": risk_lock.risk_lock_id,
            "execution_campaign_id": risk_lock.execution_campaign_id,
            "handoff_id": handoff.handoff_id,
            "tradeplan_id": risk_lock.tradeplan_id,
            "account_id": risk_lock.account_id,
            "account_snapshot_id": risk_lock.account_snapshot_id,
            "policy_id": risk_lock.policy_id,
            "balance_base": risk_lock.balance_base,
            "risk_percent_per_entry": risk_lock.risk_percent_per_entry,
            "risk_unit_usd": risk_lock.risk_unit_usd,
            "max_campaign_risk_usd": risk_lock.max_campaign_risk_usd,
            "locked_at": risk_lock.locked_at_utc,
            "authority_hash": risk_lock.authority_hash,
            "risk_authority": True,
            "broker_execution_authority": False,
        },
        RESERVATION_TABLE: {
            "reservation_id": reservation.reservation_id,
            "execution_campaign_id": reservation.execution_campaign_id,
            "risk_lock_id": reservation.risk_lock_id,
            "handoff_id": reservation.handoff_id,
            "tradeplan_id": reservation.tradeplan_id,
            "executor_id": reservation.executor_id,
            "account_id": reservation.account_id,
            "account_snapshot_id": reservation.account_snapshot_id,
            "account_snapshot_hash": reservation.account_snapshot_hash,
            "symbol_capability_hash": reservation.symbol_capability_hash,
            "governance_evidence_hash": reservation.governance_evidence_hash,
            "existing_risk_evidence_hash": reservation.existing_risk_evidence_hash,
            "broker_server": reservation.broker_server,
            "canonical_symbol": reservation.canonical_symbol,
            "broker_symbol": reservation.broker_symbol,
            "direction": reservation.direction,
            "entry_role": reservation.entry_role,
            "volume": reservation.volume,
            "entry_price": reservation.entry_price,
            "stop_loss": reservation.stop_loss,
            "take_profit": reservation.take_profit,
            "risk_unit_usd": reservation.risk_unit_usd,
            "reserved_risk_usd": reservation.reserved_risk_usd,
            "reserved_at": reservation.reserved_at_utc,
            "expires_at": reservation.expires_at_utc,
            "authority_hash": reservation.authority_hash,
            "risk_authority": True,
            "valid_for_execution": True,
            "execution_mode": "SHADOW",
            "broker_execution_authority": False,
            "command_authority": False,
        },
        CAMPAIGN_TABLE: {
            "execution_campaign_id": campaign.execution_campaign_id,
            "tradeplan_id": campaign.tradeplan_id,
            "reservation_id": campaign.reservation_id,
            "account_id": campaign.account_id,
            "canonical_symbol": campaign.canonical_symbol,
            "direction": campaign.direction,
            "execution_mode": campaign.execution_mode,
            "opened_at": campaign.opened_at_utc,
            "authority_hash": campaign.authority_hash,
            "risk_authority": True,
            "broker_execution_authority": False,
            "command_authority": False,
        },
        OUTBOX_TABLE: {
            "outbox_id": "5scr-c2-outbox-v2:" + hashlib.sha256(signal.signal_id.encode()).hexdigest()[:32],
            "signal_id": signal.signal_id,
            "execution_campaign_id": signal.execution_campaign_id,
            "reservation_id": signal.reservation_id,
            "tradeplan_id": signal.tradeplan_id,
            "account_snapshot_id": signal.risk_snapshot_id,
            "account_id": signal.account_id,
            "executor_id": signal.executor_id,
            "broker_server": signal.broker_server,
            "handoff_id": signal.handoff_id,
            "risk_lock_id": signal.risk_lock_id,
            "account_snapshot_hash": signal.account_snapshot_hash,
            "symbol_capability_hash": signal.symbol_capability_hash,
            "governance_evidence_hash": signal.governance_evidence_hash,
            "existing_risk_evidence_hash": signal.existing_risk_evidence_hash,
            "material_candidate_hash": signal.material_candidate_hash,
            "candidate_evidence_hash": signal.candidate_evidence_hash,
            "broker_symbol": signal.broker_symbol,
            "canonical_symbol": signal.canonical_symbol,
            "direction": signal.final_direction,
            "entry_role": signal.entry_role,
            "payload_hash": canonical_hash_v1(signal.model_dump(mode="json")),
            "authority_hash": signal.authority_hash,
            "created_at": signal.issued_at_utc,
            "delivery_authority": False,
            "broker_execution_authority": False,
            "command_authority": False,
        },
    }
    for table, fields in expected.items():
        for field, value in fields.items():
            actual = _row(rows[table], field)
            if not _durable_equal(actual, value):
                raise CandidateC2ShadowV2IntegrityError(f"C2_DURABLE_DRIFT:{table}.{field}")
    return bundle


class Strategy5SCRCandidateC2ShadowV2Repository:
    """Persist one atomic C2 SHADOW authority chain for one CandidateV2."""

    def __init__(self, pg: PostgresClient = pg_client) -> None:
        self._pg = pg

    async def _database_now(self, connection: Any) -> datetime:
        """Return the authoritative transaction clock; tests may pin it in a subclass."""

        value = await connection.fetchval("SELECT clock_timestamp()")
        if not isinstance(value, datetime):
            raise CandidateC2ShadowV2IntegrityError("C2_TRANSACTION_CLOCK_INVALID")
        return value

    async def schema_status(self) -> CandidateC2ShadowV2SchemaStatus:
        parent = await Strategy5SCRTradePlanCandidateV2Repository(self._pg).schema_status()
        if not self._pg.is_available:
            return CandidateC2ShadowV2SchemaStatus(
                missing_tables=tuple(sorted((*_TABLES, *_DEPENDENCY_TABLES))),
                invalid_tables=(),
                missing_columns=tuple(
                    sorted(f"{table}.{column}" for table, columns in _REQUIRED_COLUMNS.items() for column in columns)
                ),
                invalid_columns=(),
                missing_constraints=tuple(sorted(_CONSTRAINT_TABLES)),
                invalid_constraints=(),
                missing_indexes=tuple(sorted(_INDEX_TABLES)),
                invalid_indexes=(),
                missing_triggers=tuple(sorted(_TRIGGER_TABLES)),
                invalid_triggers=(),
            )
        tables = await self._pg.fetch(
            """SELECT cls.relname AS tablename,cls.relkind::text AS relkind,
                      cls.relpersistence::text AS relpersistence,cls.relispartition
               FROM pg_catalog.pg_class cls
               JOIN pg_catalog.pg_namespace ns ON ns.oid=cls.relnamespace
               WHERE ns.nspname=current_schema() AND cls.relname=ANY($1::text[])""",
            sorted((*_TABLES, *_DEPENDENCY_TABLES)),
        )
        columns = await self._pg.fetch(
            """SELECT table_name,column_name,is_nullable,data_type,character_maximum_length,
                      numeric_precision,numeric_scale,datetime_precision,column_default,
                      is_generated,generation_expression
               FROM information_schema.columns
               WHERE table_schema=current_schema() AND table_name=ANY($1::text[])""",
            sorted(_REQUIRED_COLUMNS),
        )
        constraints = await self._pg.fetch(
            """SELECT con.conname,cls.relname table_name,con.convalidated,pg_get_constraintdef(con.oid) definition
               FROM pg_constraint con JOIN pg_class cls ON cls.oid=con.conrelid
               JOIN pg_namespace ns ON ns.oid=cls.relnamespace
               WHERE ns.nspname=current_schema() AND con.conname=ANY($1::text[])""",
            sorted(_CONSTRAINT_TABLES),
        )
        indexes = await self._pg.fetch(
            """SELECT idxcls.relname index_name,cls.relname table_name,idx.indisvalid,idx.indisready,
                      pg_get_indexdef(idx.indexrelid) definition
               FROM pg_index idx JOIN pg_class cls ON cls.oid=idx.indrelid
               JOIN pg_class idxcls ON idxcls.oid=idx.indexrelid JOIN pg_namespace ns ON ns.oid=cls.relnamespace
               WHERE ns.nspname=current_schema() AND idxcls.relname=ANY($1::text[])""",
            sorted(_INDEX_TABLES),
        )
        triggers = await self._pg.fetch(
            """SELECT trg.tgname,cls.relname table_name,trg.tgenabled,pg_get_triggerdef(trg.oid) trigger_definition,
                      pg_get_functiondef(proc.oid) function_definition
               FROM pg_trigger trg JOIN pg_class cls ON cls.oid=trg.tgrelid
               JOIN pg_namespace ns ON ns.oid=cls.relnamespace JOIN pg_proc proc ON proc.oid=trg.tgfoid
               WHERE ns.nspname=current_schema() AND NOT trg.tgisinternal AND trg.tgname=ANY($1::text[])""",
            sorted(_TRIGGER_TABLES),
        )
        table_map = {str(_row(item, "tablename")): item for item in tables}
        table_names = set(table_map)
        invalid_tables = tuple(
            sorted(
                table
                for table in (*_TABLES, *_DEPENDENCY_TABLES)
                if (item := table_map.get(table)) is not None
                and (
                    str(_row(item, "relkind")) != "r"
                    or str(_row(item, "relpersistence")) != "p"
                    or bool(_row(item, "relispartition"))
                )
            )
        )
        column_names = {(str(_row(item, "table_name")), str(_row(item, "column_name"))) for item in columns}
        missing_columns = tuple(
            sorted(
                f"{table}.{column}"
                for table, required in _REQUIRED_COLUMNS.items()
                for column in required
                if (table, column) not in column_names
            )
        )
        required_column_labels = {
            f"{table}.{column}" for table, required in _REQUIRED_COLUMNS.items() for column in required
        }
        invalid_columns = tuple(
            sorted(
                label
                for item in columns
                if (label := f"{_row(item, 'table_name')}.{_row(item, 'column_name')}") in required_column_labels
                and _COLUMN_HASHES.get(label)
                != _fingerprint(
                    "|".join(
                        str(_row(item, field) or "")
                        for field in (
                            "data_type",
                            "is_nullable",
                            "character_maximum_length",
                            "numeric_precision",
                            "numeric_scale",
                            "datetime_precision",
                            "column_default",
                            "is_generated",
                            "generation_expression",
                        )
                    )
                )
            )
        )
        constraint_map = {str(_row(item, "conname")): item for item in constraints}
        invalid_constraints = tuple(
            sorted(
                name
                for name, table in _CONSTRAINT_TABLES.items()
                if (item := constraint_map.get(name)) is not None
                and (
                    str(_row(item, "table_name")) != table
                    or not bool(_row(item, "convalidated"))
                    or _CONSTRAINT_HASHES.get(name) != _fingerprint(_row(item, "definition"))
                )
            )
        )
        index_map = {str(_row(item, "index_name")): item for item in indexes}
        invalid_indexes = tuple(
            sorted(
                name
                for name, table in _INDEX_TABLES.items()
                if (item := index_map.get(name)) is not None
                and (
                    str(_row(item, "table_name")) != table
                    or not bool(_row(item, "indisvalid"))
                    or not bool(_row(item, "indisready"))
                    or _INDEX_HASHES.get(name) != _fingerprint(_row(item, "definition"))
                )
            )
        )
        trigger_map = {str(_row(item, "tgname")): item for item in triggers}
        invalid_triggers = tuple(
            sorted(
                name
                for name, table in _TRIGGER_TABLES.items()
                if (item := trigger_map.get(name)) is not None
                and (
                    str(_row(item, "table_name")) != table
                    or str(_row(item, "tgenabled")) not in {"O", "b'O'"}
                    or (hashes := _TRIGGER_HASHES.get(name)) is None
                    or hashes[0] != _fingerprint(_row(item, "trigger_definition"))
                    or hashes[1] != _fingerprint(_row(item, "function_definition"))
                )
            )
        )
        return CandidateC2ShadowV2SchemaStatus(
            missing_tables=tuple(
                sorted(
                    (
                        *(set((*_TABLES, *_DEPENDENCY_TABLES)) - table_names),
                        *(f"p6:{item}" for item in parent.missing_tables),
                    )
                )
            ),
            invalid_tables=tuple(sorted((*invalid_tables, *(f"p6:{item}" for item in parent.invalid_tables)))),
            missing_columns=missing_columns,
            invalid_columns=invalid_columns,
            missing_constraints=tuple(sorted(set(_CONSTRAINT_TABLES) - set(constraint_map))),
            invalid_constraints=tuple(
                sorted(
                    (
                        *invalid_constraints,
                        *(f"p6:missing:{item}" for item in parent.missing_constraints),
                        *(f"p6:invalid:{item}" for item in parent.invalid_constraints),
                        *(f"p6:missing-column:{item}" for item in parent.missing_columns),
                        *(f"p6:invalid-column:{item}" for item in parent.invalid_columns),
                    )
                )
            ),
            missing_indexes=tuple(sorted(set(_INDEX_TABLES) - set(index_map))),
            invalid_indexes=tuple(
                sorted(
                    (
                        *invalid_indexes,
                        *(f"p6:missing:{item}" for item in parent.missing_indexes),
                        *(f"p6:invalid:{item}" for item in parent.invalid_indexes),
                    )
                )
            ),
            missing_triggers=tuple(sorted(set(_TRIGGER_TABLES) - set(trigger_map))),
            invalid_triggers=tuple(
                sorted(
                    (
                        *invalid_triggers,
                        *(f"p6:missing:{item}" for item in parent.missing_triggers),
                        *(f"p6:invalid:{item}" for item in parent.invalid_triggers),
                    )
                )
            ),
        )

    async def load_authority(self, tradeplan_id: str) -> C2ShadowAuthorityBundleV2 | None:
        async with self._pg.transaction() as connection:
            parent = await _lock_and_validate_candidate_authority(connection, tradeplan_id)
            if parent is None:
                return None
            bundle = await self._load_bundle(connection, tradeplan_id, lock=True, require_live=True)
            if bundle is None:
                return None
            reservation_row = await connection.fetchrow(
                f"SELECT state,expires_at FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1", tradeplan_id
            )
            executor_row = await connection.fetchrow(
                "SELECT execution_mode,revoked_at,updated_at,mode_changed_at,account_id,broker_server "
                "FROM executor_instances WHERE executor_id=$1::uuid FOR NO KEY UPDATE",
                str(bundle.reservation.executor_id),
            )
            governance_row = await connection.fetchrow(
                "SELECT kill_switch_active,updated_at FROM executor_bridge_governance WHERE singleton_id=1 FOR UPDATE"
            )
            if str(_row(reservation_row, "state")) != "RESERVED":
                return None
            if parent.terminal:
                await self._terminalize(connection, tradeplan_id, parent.terminal_at, parent.terminal_reason)
                return None
            if (
                governance_row is None
                or bool(_row(governance_row, "kill_switch_active"))
                or executor_row is None
                or _row(executor_row, "revoked_at") is not None
                or str(_row(executor_row, "execution_mode")) != "SHADOW"
                or str(_row(executor_row, "account_id")) != bundle.reservation.account_id
                or str(_row(executor_row, "broker_server")) != bundle.reservation.broker_server
            ):
                # Reconciliation is observed now, after locking both durable
                # governance authorities.  Their stored timestamps are useful
                # evidence, but the database clock is the terminal authority.
                terminal_at = max(bundle.reservation.reserved_at_utc, await self._database_now(connection))
                await self._terminalize(
                    connection,
                    tradeplan_id,
                    terminal_at,
                    "C2_GOVERNANCE_RECONCILIATION_REQUIRED",
                    reservation_state="RECONCILIATION_REQUIRED",
                    campaign_state="RECONCILIATION_REQUIRED",
                )
                return None
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                bundle.reservation.account_id,
            )
            # Command writers do not all participate in the account advisory
            # mutex.  A SHARE fence prevents a QUEUED/CLAIMED command from
            # appearing after the zero-risk read but before this authority
            # transaction commits.
            await connection.execute("LOCK TABLE execution_commands IN SHARE MODE")
            await connection.execute("LOCK TABLE executor_account_snapshots IN SHARE MODE")
            latest_row = await connection.fetchrow(
                """SELECT * FROM executor_account_snapshots WHERE executor_id=$1::uuid AND account_id=$2
                   ORDER BY captured_at DESC,received_at DESC,snapshot_id DESC LIMIT 1 FOR UPDATE""",
                str(bundle.reservation.executor_id),
                bundle.reservation.account_id,
            )
            transaction_at = await self._database_now(connection)
            if latest_row is None:
                await self._terminalize(
                    connection,
                    tradeplan_id,
                    max(bundle.reservation.reserved_at_utc, transaction_at),
                    "C2_BROKER_RECONCILIATION_REQUIRED",
                    reservation_state="RECONCILIATION_REQUIRED",
                    campaign_state="RECONCILIATION_REQUIRED",
                )
                return None
            latest = self._snapshot_from_row(latest_row)
            expires_at = _row(reservation_row, "expires_at")
            if not isinstance(expires_at, datetime):
                raise CandidateC2ShadowV2IntegrityError("C2_RESERVATION_EXPIRY_DRIFT")
            if expires_at <= transaction_at:
                await self._terminalize(
                    connection,
                    tradeplan_id,
                    expires_at,
                    "C2_AUTHORITY_EXPIRED",
                    reservation_state="EXPIRED",
                    campaign_state="EXPIRED",
                )
                return None
            governance_clocks = tuple(
                value
                for value in (
                    _row(governance_row, "updated_at"),
                    _row(executor_row, "updated_at"),
                    _row(executor_row, "mode_changed_at"),
                )
                if isinstance(value, datetime)
            )
            governance_clock = max(governance_clocks, default=bundle.reservation.reserved_at_utc)
            snapshot_validation = validate_account_snapshot(
                latest,
                expected_account_id=bundle.reservation.account_id,
                policy=CampaignRiskPolicy(),
                now=transaction_at,
            )
            capability = find_symbol_capability(
                latest,
                canonical_symbol=bundle.reservation.canonical_symbol,
                broker_symbol=bundle.reservation.broker_symbol,
            )
            if (
                not snapshot_validation.allowed
                or latest.currency != "USD"
                or latest.executor_id != bundle.reservation.executor_id
                or governance_clock > transaction_at + timedelta(seconds=2)
                or governance_clock < transaction_at - timedelta(seconds=C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS)
                or not latest.broker_ledger_reconciled
                or latest.pending_orders
                or latest.open_positions
                or not latest.trade_allowed
                or not latest.autotrading_enabled
                or capability is None
                or symbol_capability_authority_hash_v2(capability) != bundle.reservation.symbol_capability_hash
            ):
                await self._terminalize(
                    connection,
                    tradeplan_id,
                    max(bundle.reservation.reserved_at_utc, transaction_at),
                    "C2_BROKER_RECONCILIATION_REQUIRED",
                    reservation_state="RECONCILIATION_REQUIRED",
                    campaign_state="RECONCILIATION_REQUIRED",
                )
                return None
            current_risk = await self._derive_existing_risk(
                connection,
                parent.candidate,
                latest,
                bundle.reservation.account_id,
                transaction_at,
            )
            if (
                current_risk.active_campaign_count
                or current_risk.active_reservation_count
                or current_risk.pending_order_count
                or current_risk.committed_or_reserved_campaign_risk_usd
                or current_risk.account_total_open_risk_usd
            ):
                await self._terminalize(
                    connection,
                    tradeplan_id,
                    max(bundle.reservation.reserved_at_utc, transaction_at),
                    "C2_EXISTING_RISK_NOT_FLAT",
                    reservation_state="RECONCILIATION_REQUIRED",
                    campaign_state="RECONCILIATION_REQUIRED",
                )
                return None
            return bundle

    async def load_evaluations(self, tradeplan_id: str) -> tuple[C2ShadowEvaluationV2, ...]:
        async with self._pg.transaction() as connection:
            parent = await _lock_and_validate_candidate_authority(connection, tradeplan_id)
            if parent is None:
                return ()
            rows = await connection.fetch(
                f"SELECT * FROM {EVALUATION_TABLE} WHERE tradeplan_id=$1 ORDER BY evaluation_sequence,evaluation_id",
                tradeplan_id,
            )
            evaluations: list[C2ShadowEvaluationV2] = []
            approved_bundle: C2ShadowAuthorityBundleV2 | None = None
            for row in rows:
                evaluation = self._evaluation_from_row(row)
                try:
                    build = CandidateC2ShadowBuildEvidenceV2.model_validate(_json(_row(row, "build_evidence_payload")))
                except ValidationError as exc:
                    raise CandidateC2ShadowV2IntegrityError("C2_EVALUATION_BUILD_EVIDENCE_INVALID") from exc
                if (
                    build.candidate.model_dump(mode="json", exclude={"lifecycle_state"})
                    != parent.candidate.model_dump(mode="json", exclude={"lifecycle_state"})
                    or build.authority_hash() != evaluation.evidence_hash
                    or build.source_request_id != evaluation.source_request_id
                    or build.decision_at_utc != evaluation.decision_at_utc
                ):
                    raise CandidateC2ShadowV2IntegrityError("C2_EVALUATION_BUILD_EVIDENCE_DRIFT")
                if evaluation.decision == "APPROVED":
                    if approved_bundle is None:
                        approved_bundle = await self._load_bundle(connection, tradeplan_id, lock=False)
                    if (
                        approved_bundle is None
                        or evaluation.result_execution_campaign_id
                        != approved_bundle.execution_campaign.execution_campaign_id
                        or evaluation.result_reservation_id != approved_bundle.reservation.reservation_id
                    ):
                        raise CandidateC2ShadowV2IntegrityError("C2_EVALUATION_AUTHORITY_CROSSLINK_DRIFT")
                evaluations.append(evaluation)
            return tuple(evaluations)

    async def _reconcile_existing_before_retry(
        self,
        connection: Any,
        candidate: TradePlanCandidateV2,
        existing: C2ShadowAuthorityBundleV2,
    ) -> CandidateC2ShadowPersistenceResult | None:
        """Reconcile admitted authority without trusting the incoming retry.

        A caller-controlled retry must not win a race against durable
        revocation evidence.  Until this preflight proves the existing bundle
        live, every selector and clock comes exclusively from the reconstructed
        bundle or from rows read under the authority locks.
        """

        tradeplan_id = candidate.tradeplan_id
        reservation = existing.reservation
        executor_row = await connection.fetchrow(
            "SELECT * FROM executor_instances WHERE executor_id=$1::uuid FOR NO KEY UPDATE",
            str(reservation.executor_id),
        )
        governance_row = await connection.fetchrow(
            "SELECT * FROM executor_bridge_governance WHERE singleton_id=1 FOR UPDATE"
        )
        governance_reason: str | None = None
        if executor_row is None or _row(executor_row, "revoked_at") is not None:
            governance_reason = "C2_EXECUTOR_NOT_ACTIVE"
        elif str(_row(executor_row, "execution_mode")) != "SHADOW":
            governance_reason = "C2_EXECUTOR_MODE_NOT_SHADOW"
        elif governance_row is None or bool(_row(governance_row, "kill_switch_active")):
            governance_reason = "C2_KILL_SWITCH_ENGAGED"
        elif str(_row(executor_row, "account_id")) != reservation.account_id:
            governance_reason = "C2_ACCOUNT_BINDING_MISMATCH"
        elif str(_row(executor_row, "broker_server")) != reservation.broker_server:
            governance_reason = "C2_BROKER_BINDING_MISMATCH"
        if governance_reason is not None:
            reconciliation_at = await self._database_now(connection)
            await self._terminalize(
                connection,
                tradeplan_id,
                max(reservation.reserved_at_utc, reconciliation_at),
                governance_reason,
            )
            return CandidateC2ShadowPersistenceResult("INVALIDATED", governance_reason)

        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
            reservation.account_id,
        )
        await connection.execute("LOCK TABLE execution_commands IN SHARE MODE")
        await connection.execute("LOCK TABLE executor_account_snapshots IN SHARE MODE")

        reservation_row = await connection.fetchrow(
            f"SELECT state,expires_at FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1",
            tradeplan_id,
        )
        if str(_row(reservation_row, "state")) != "RESERVED":
            return CandidateC2ShadowPersistenceResult("DUPLICATE", "C2_AUTHORITY_ALREADY_TERMINAL")
        expires_at = _row(reservation_row, "expires_at")
        if not isinstance(expires_at, datetime) or expires_at != reservation.expires_at_utc:
            raise CandidateC2ShadowV2IntegrityError("C2_RESERVATION_EXPIRY_DRIFT")

        latest_row = await connection.fetchrow(
            """SELECT * FROM executor_account_snapshots WHERE executor_id=$1::uuid AND account_id=$2
               ORDER BY captured_at DESC,received_at DESC,snapshot_id DESC LIMIT 1 FOR UPDATE""",
            str(reservation.executor_id),
            reservation.account_id,
        )
        liveness_at = await self._database_now(connection)
        if expires_at <= liveness_at:
            await self._terminalize(
                connection,
                tradeplan_id,
                expires_at,
                "C2_AUTHORITY_EXPIRED",
                reservation_state="EXPIRED",
                campaign_state="EXPIRED",
            )
            return CandidateC2ShadowPersistenceResult("INVALIDATED", "C2_AUTHORITY_EXPIRED")
        if latest_row is None:
            await self._terminalize(
                connection,
                tradeplan_id,
                max(reservation.reserved_at_utc, liveness_at),
                "C2_BROKER_RECONCILIATION_REQUIRED",
                reservation_state="RECONCILIATION_REQUIRED",
                campaign_state="RECONCILIATION_REQUIRED",
            )
            return CandidateC2ShadowPersistenceResult("INVALIDATED", "C2_BROKER_RECONCILIATION_REQUIRED")

        latest = self._snapshot_from_row(latest_row)
        governance_clocks = tuple(
            value
            for value in (
                _row(governance_row, "updated_at"),
                _row(executor_row, "updated_at"),
                _row(executor_row, "mode_changed_at"),
            )
            if isinstance(value, datetime)
        )
        governance_clock = max(governance_clocks, default=reservation.reserved_at_utc)
        snapshot_validation = validate_account_snapshot(
            latest,
            expected_account_id=reservation.account_id,
            policy=CampaignRiskPolicy(),
            now=liveness_at,
        )
        capability = find_symbol_capability(
            latest,
            canonical_symbol=reservation.canonical_symbol,
            broker_symbol=reservation.broker_symbol,
        )
        if (
            not snapshot_validation.allowed
            or latest.currency != "USD"
            or latest.executor_id != reservation.executor_id
            or governance_clock > liveness_at + timedelta(seconds=2)
            or governance_clock < liveness_at - timedelta(seconds=C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS)
            or not latest.broker_ledger_reconciled
            or latest.pending_orders
            or latest.open_positions
            or not latest.trade_allowed
            or not latest.autotrading_enabled
            or capability is None
            or symbol_capability_authority_hash_v2(capability) != reservation.symbol_capability_hash
        ):
            await self._terminalize(
                connection,
                tradeplan_id,
                max(reservation.reserved_at_utc, liveness_at),
                "C2_BROKER_RECONCILIATION_REQUIRED",
                reservation_state="RECONCILIATION_REQUIRED",
                campaign_state="RECONCILIATION_REQUIRED",
            )
            return CandidateC2ShadowPersistenceResult("INVALIDATED", "C2_BROKER_RECONCILIATION_REQUIRED")

        derived_risk = await self._derive_existing_risk(
            connection,
            candidate,
            latest,
            reservation.account_id,
            liveness_at,
        )
        if (
            derived_risk.active_campaign_count
            or derived_risk.active_reservation_count
            or derived_risk.pending_order_count
            or derived_risk.committed_or_reserved_campaign_risk_usd
            or derived_risk.account_total_open_risk_usd
            or not derived_risk.broker_ledger_reconciled
        ):
            await self._terminalize(
                connection,
                tradeplan_id,
                max(reservation.reserved_at_utc, liveness_at),
                "C2_BROKER_RECONCILIATION_REQUIRED",
                reservation_state="RECONCILIATION_REQUIRED",
                campaign_state="RECONCILIATION_REQUIRED",
            )
            return CandidateC2ShadowPersistenceResult("INVALIDATED", "C2_BROKER_RECONCILIATION_REQUIRED")

        # Refresh after the last potentially blocking catalog/risk read.  The
        # admitted authority is reusable only if its durable snapshot and
        # governance evidence are still live at this boundary.
        commit_at = await self._database_now(connection)
        if expires_at <= commit_at:
            await self._terminalize(
                connection,
                tradeplan_id,
                expires_at,
                "C2_AUTHORITY_EXPIRED",
                reservation_state="EXPIRED",
                campaign_state="EXPIRED",
            )
            return CandidateC2ShadowPersistenceResult("INVALIDATED", "C2_AUTHORITY_EXPIRED")
        if (
            not validate_account_snapshot(
                latest,
                expected_account_id=reservation.account_id,
                policy=CampaignRiskPolicy(),
                now=commit_at,
            ).allowed
            or governance_clock > commit_at + timedelta(seconds=2)
            or governance_clock < commit_at - timedelta(seconds=C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS)
        ):
            await self._terminalize(
                connection,
                tradeplan_id,
                max(reservation.reserved_at_utc, commit_at),
                "C2_BROKER_RECONCILIATION_REQUIRED",
                reservation_state="RECONCILIATION_REQUIRED",
                campaign_state="RECONCILIATION_REQUIRED",
            )
            return CandidateC2ShadowPersistenceResult("INVALIDATED", "C2_BROKER_RECONCILIATION_REQUIRED")
        return None

    async def process_evidence(self, evidence: CandidateC2ShadowBuildEvidenceV2) -> CandidateC2ShadowPersistenceResult:
        # Snapshot the recursively mutable protocol children synchronously,
        # before the first await gives the caller a chance to mutate them.
        # Full validation follows durable terminal reconciliation so forged
        # incoming evidence can never prevent closure of admitted authority.
        admitted_evidence = evidence.model_copy(deep=True)
        candidate_id = admitted_evidence.candidate.tradeplan_id
        async with self._pg.transaction() as connection:
            # Global lock order is the same as P3-P6: Lifecycle -> Candidate
            # chain -> Context -> Thesis/proofs -> ExecutionBox -> P7 rows ->
            # executor -> governance -> account mutex -> command/snapshot fences.
            parent = await _lock_and_validate_candidate_authority(connection, candidate_id)
            if parent is None:
                return CandidateC2ShadowPersistenceResult("REJECTED", "C2_CANDIDATE_MISSING")
            candidate = parent.candidate
            existing = await self._load_bundle(connection, candidate_id, lock=True)

            # Terminal durable parents always win over a stale/bogus request.
            if parent.terminal and existing is not None:
                # Revocation of admitted authority must depend only on the
                # durable parent/bundle.  Persisting an audit built from a
                # forged retry here could fail its snapshot FK and roll the
                # terminal transition back with the surrounding transaction.
                await self._terminalize(
                    connection,
                    candidate_id,
                    parent.terminal_at,
                    parent.terminal_reason,
                )
                return CandidateC2ShadowPersistenceResult("INVALIDATED", parent.terminal_reason)

            if existing is not None:
                durable_result = await self._reconcile_existing_before_retry(connection, candidate, existing)
                if durable_result is not None:
                    return durable_result

            try:
                canonical_evidence = snapshot_candidate_c2_build_evidence_v2(
                    admitted_evidence.model_copy(update={"candidate": candidate})
                )
            except (ValidationError, ValueError):
                return CandidateC2ShadowPersistenceResult("QUARANTINED", "C2_BUILD_EVIDENCE_INTEGRITY_INVALID")

            async def persist_rejection(reason: str) -> CandidateC2ShadowPersistenceResult:
                prior_row = await connection.fetchrow(
                    f"SELECT * FROM {EVALUATION_TABLE} WHERE tradeplan_id=$1 AND "
                    "(source_request_id=$2 OR decision_at=$3)",
                    candidate_id,
                    canonical_evidence.source_request_id,
                    canonical_evidence.decision_at_utc,
                )
                if prior_row is not None:
                    prior_evaluation = self._evaluation_from_row(prior_row)
                    if (
                        prior_evaluation.source_request_id != canonical_evidence.source_request_id
                        or prior_evaluation.decision_at_utc != canonical_evidence.decision_at_utc
                    ):
                        return CandidateC2ShadowPersistenceResult("QUARANTINED", "C2_AMBIGUOUS_EVIDENCE_CLOCK")
                    if prior_evaluation.evidence_hash != canonical_evidence.authority_hash():
                        return CandidateC2ShadowPersistenceResult("QUARANTINED", "C2_REQUEST_EVIDENCE_DRIFT")
                    if prior_evaluation.decision == "APPROVED":
                        if existing is None:
                            raise CandidateC2ShadowV2IntegrityError("C2_APPROVED_EVALUATION_AUTHORITY_MISSING")
                        return CandidateC2ShadowPersistenceResult("DUPLICATE", "C2_EVALUATION_ALREADY_PERSISTED")
                    return CandidateC2ShadowPersistenceResult(
                        "DUPLICATE", "C2_EVALUATION_ALREADY_PERSISTED", prior_evaluation
                    )
                sequence = int(
                    await connection.fetchval(
                        f"SELECT COALESCE(MAX(evaluation_sequence),0)+1 FROM {EVALUATION_TABLE} WHERE tradeplan_id=$1",
                        candidate_id,
                    )
                )
                evaluation = _rejected_evaluation(canonical_evidence, sequence=sequence, reason=reason)
                await self._insert_evaluation(connection, canonical_evidence, evaluation)
                return CandidateC2ShadowPersistenceResult("REJECTED", reason, evaluation)

            if parent.terminal:
                # No P7 authority exists to reconcile and the caller snapshot
                # has not yet been proven durable.  A terminal parent is
                # already a typed durable verdict; do not let an audit INSERT
                # manufacture an FK dependency on caller-only snapshot data.
                return CandidateC2ShadowPersistenceResult("REJECTED", parent.terminal_reason)
            if candidate != admitted_evidence.candidate:
                return CandidateC2ShadowPersistenceResult("QUARANTINED", "C2_CANDIDATE_DURABLE_DRIFT")
            # From this point onward, every check, hash, reduction and insert
            # uses only the validated deep snapshot, never the caller object.
            evidence = canonical_evidence

            if existing is not None and (
                evidence.governance.executor_id != existing.reservation.executor_id
                or evidence.governance.account_id != existing.reservation.account_id
                or evidence.governance.broker_server != existing.reservation.broker_server
                or evidence.account_snapshot.executor_id != existing.reservation.executor_id
                or evidence.account_snapshot.account_id != existing.reservation.account_id
                or evidence.broker_symbol != existing.reservation.broker_symbol
            ):
                return CandidateC2ShadowPersistenceResult("QUARANTINED", "C2_CURRENT_AUTHORITY_SCOPE_MISMATCH")

            governed_executor_id = (
                existing.reservation.executor_id if existing is not None else evidence.governance.executor_id
            )

            executor_row = await connection.fetchrow(
                "SELECT * FROM executor_instances WHERE executor_id=$1::uuid FOR NO KEY UPDATE",
                str(governed_executor_id),
            )
            governance_row = await connection.fetchrow(
                "SELECT * FROM executor_bridge_governance WHERE singleton_id=1 FOR UPDATE"
            )
            rejection: str | None = None
            if executor_row is None or _row(executor_row, "revoked_at") is not None:
                rejection = "C2_EXECUTOR_NOT_ACTIVE"
            elif str(_row(executor_row, "execution_mode")) != "SHADOW":
                rejection = "C2_EXECUTOR_MODE_NOT_SHADOW"
            elif governance_row is None or bool(_row(governance_row, "kill_switch_active")):
                rejection = "C2_KILL_SWITCH_ENGAGED"
            elif str(_row(executor_row, "account_id")) != evidence.governance.account_id:
                rejection = "C2_ACCOUNT_BINDING_MISMATCH"
            elif str(_row(executor_row, "broker_server")) != (
                existing.reservation.broker_server if existing is not None else evidence.governance.broker_server
            ):
                rejection = "C2_BROKER_BINDING_MISMATCH"
            if rejection is not None:
                if existing is not None:
                    # The rejection is observed after the executor/governance
                    # locks.  Never let caller or external component clocks
                    # become the terminal audit clock for admitted authority.
                    reconciliation_at = await self._database_now(connection)
                    await self._terminalize(
                        connection,
                        candidate_id,
                        max(existing.reservation.reserved_at_utc, reconciliation_at),
                        rejection,
                    )
                    return CandidateC2ShadowPersistenceResult("INVALIDATED", rejection)
                if executor_row is None or rejection in {
                    "C2_ACCOUNT_BINDING_MISMATCH",
                    "C2_BROKER_BINDING_MISMATCH",
                }:
                    # There is no trustworthy executor/account scope from
                    # which to prove the caller snapshot FK.  Return the typed
                    # non-authoritative verdict without an evaluation row.
                    return CandidateC2ShadowPersistenceResult("REJECTED", rejection)

            assert executor_row is not None
            account_id = str(_row(executor_row, "account_id"))
            await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", account_id)
            # Freeze the command predicate for the remainder of the authority
            # transaction.  This is a read fence only: P7 never writes C3.
            await connection.execute("LOCK TABLE execution_commands IN SHARE MODE")

            prior = await connection.fetchrow(
                f"SELECT * FROM {EVALUATION_TABLE} WHERE tradeplan_id=$1 AND (source_request_id=$2 OR decision_at=$3)",
                candidate_id,
                evidence.source_request_id,
                evidence.decision_at_utc,
            )
            saved: C2ShadowEvaluationV2 | None = None
            if prior is not None:
                saved = self._evaluation_from_row(prior)
                if (
                    saved.source_request_id != evidence.source_request_id
                    or saved.decision_at_utc != evidence.decision_at_utc
                ):
                    return CandidateC2ShadowPersistenceResult("QUARANTINED", "C2_AMBIGUOUS_EVIDENCE_CLOCK")
                if saved.evidence_hash != evidence.authority_hash():
                    return CandidateC2ShadowPersistenceResult("QUARANTINED", "C2_REQUEST_EVIDENCE_DRIFT")
                if existing is None:
                    if saved.decision == "APPROVED":
                        raise CandidateC2ShadowV2IntegrityError("C2_APPROVED_EVALUATION_AUTHORITY_MISSING")
                    return CandidateC2ShadowPersistenceResult("DUPLICATE", "C2_EVALUATION_ALREADY_PERSISTED", saved)
                # The exact persisted request/hash is already immutable and
                # the terminal-first durable preflight above proved the live
                # bundle healthy against the latest snapshot. Preserve
                # exactly-once replay even when a newer healthy heartbeat has
                # superseded the request's original frozen snapshot.
                return CandidateC2ShadowPersistenceResult(
                    "DUPLICATE", "C2_EVALUATION_ALREADY_PERSISTED", saved, existing
                )

            if existing is not None:
                reservation_row = await connection.fetchrow(
                    f"SELECT state,expires_at FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1",
                    candidate_id,
                )
                reservation_state = str(_row(reservation_row, "state"))
                if reservation_state != "RESERVED":
                    return CandidateC2ShadowPersistenceResult("DUPLICATE", "C2_AUTHORITY_ALREADY_TERMINAL")

            # Snapshot rows are append-only by convention but not by schema.
            # A SHARE table fence prevents a newer heartbeat phantom between
            # latest-snapshot selection and commit.
            await connection.execute("LOCK TABLE executor_account_snapshots IN SHARE MODE")
            snapshot_row = await connection.fetchrow(
                """SELECT * FROM executor_account_snapshots WHERE executor_id=$1::uuid AND account_id=$2
                   ORDER BY captured_at DESC,received_at DESC,snapshot_id DESC LIMIT 1 FOR UPDATE""",
                str(evidence.governance.executor_id),
                account_id,
            )
            if snapshot_row is None:
                return CandidateC2ShadowPersistenceResult("REJECTED", "C2_ACCOUNT_SNAPSHOT_MISSING")
            snapshot = self._snapshot_from_row(snapshot_row)
            if (
                snapshot != evidence.account_snapshot
                or account_snapshot_authority_hash_v2(snapshot) != evidence.account_snapshot_hash
            ):
                return CandidateC2ShadowPersistenceResult("QUARANTINED", "C2_ACCOUNT_SNAPSHOT_CHANGED_DURING_READ")
            if rejection is not None:
                # Exact latest durable snapshot equality above proves the
                # generated evaluation FK before any rejection audit INSERT.
                return await persist_rejection(rejection)
            liveness_at = await self._database_now(connection)
            expiry = existing.reservation.expires_at_utc if existing is not None else evidence.expires_at_utc
            if liveness_at >= expiry:
                if existing is not None:
                    await self._terminalize(
                        connection,
                        candidate_id,
                        existing.reservation.expires_at_utc,
                        "C2_AUTHORITY_EXPIRED",
                        reservation_state="EXPIRED",
                        campaign_state="EXPIRED",
                    )
                    return CandidateC2ShadowPersistenceResult("INVALIDATED", "C2_AUTHORITY_EXPIRED")
                return await persist_rejection("C2_AUTHORITY_EXPIRED")
            if (
                evidence.decision_at_utc > liveness_at + timedelta(seconds=2)
                or candidate.decision_at_utc < liveness_at - timedelta(seconds=C2_SHADOW_CANDIDATE_MAX_AGE_SECONDS)
                or evidence.existing_risk.captured_at_utc > liveness_at + timedelta(seconds=2)
                or evidence.existing_risk.captured_at_utc
                < liveness_at - timedelta(seconds=C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS)
            ):
                reason = (
                    "C2_CANDIDATE_STALE"
                    if candidate.decision_at_utc < liveness_at - timedelta(seconds=C2_SHADOW_CANDIDATE_MAX_AGE_SECONDS)
                    else "C2_EXISTING_RISK_STALE"
                )
                if existing is not None:
                    return CandidateC2ShadowPersistenceResult("QUARANTINED", reason)
                return await persist_rejection(reason)
            durable_governance_clock = max(
                value
                for value in (
                    _row(governance_row, "updated_at"),
                    _row(executor_row, "updated_at"),
                    _row(executor_row, "mode_changed_at"),
                )
                if isinstance(value, datetime)
            )
            snapshot_validation = validate_account_snapshot(
                snapshot,
                expected_account_id=account_id,
                policy=CampaignRiskPolicy(),
                now=liveness_at,
            )
            current_capability = find_symbol_capability(
                snapshot,
                canonical_symbol=candidate.symbol,
                broker_symbol=evidence.broker_symbol,
            )
            if (
                not snapshot_validation.allowed
                or snapshot.currency != "USD"
                or snapshot.executor_id != evidence.governance.executor_id
                or durable_governance_clock > liveness_at + timedelta(seconds=2)
                or durable_governance_clock < liveness_at - timedelta(seconds=C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS)
                or current_capability is None
                or (
                    existing is not None
                    and symbol_capability_authority_hash_v2(current_capability)
                    != existing.reservation.symbol_capability_hash
                )
            ):
                reason = (
                    "C2_ACCOUNT_CURRENCY_UNSUPPORTED"
                    if snapshot.currency != "USD"
                    else "C2_BROKER_RECONCILIATION_REQUIRED"
                )
                if existing is not None:
                    await self._terminalize(
                        connection,
                        candidate_id,
                        max(existing.reservation.reserved_at_utc, liveness_at),
                        reason,
                        reservation_state="RECONCILIATION_REQUIRED",
                        campaign_state="RECONCILIATION_REQUIRED",
                    )
                    return CandidateC2ShadowPersistenceResult("INVALIDATED", reason)
                return await persist_rejection(reason)
            if existing is not None and (
                not snapshot.broker_ledger_reconciled or snapshot.pending_orders or snapshot.open_positions
            ):
                await self._terminalize(
                    connection,
                    candidate_id,
                    max(existing.reservation.reserved_at_utc, liveness_at),
                    "C2_BROKER_RECONCILIATION_REQUIRED",
                    reservation_state="RECONCILIATION_REQUIRED",
                    campaign_state="RECONCILIATION_REQUIRED",
                )
                return CandidateC2ShadowPersistenceResult("INVALIDATED", "C2_BROKER_RECONCILIATION_REQUIRED")

            # Existing-risk evidence is derived inside the same transaction;
            # caller-provided counts cannot suppress durable P7/command state.
            derived_risk = await self._derive_existing_risk(
                connection,
                candidate,
                snapshot,
                account_id,
                evidence.decision_at_utc,
            )
            if derived_risk != evidence.existing_risk:
                if existing is not None and (
                    not derived_risk.broker_ledger_reconciled
                    or derived_risk.pending_order_count
                    or derived_risk.active_campaign_count
                    or derived_risk.active_reservation_count
                ):
                    await self._terminalize(
                        connection,
                        candidate_id,
                        max(existing.reservation.reserved_at_utc, liveness_at),
                        "C2_BROKER_RECONCILIATION_REQUIRED",
                        reservation_state="RECONCILIATION_REQUIRED",
                        campaign_state="RECONCILIATION_REQUIRED",
                    )
                    return CandidateC2ShadowPersistenceResult("INVALIDATED", "C2_BROKER_RECONCILIATION_REQUIRED")
                return CandidateC2ShadowPersistenceResult("QUARANTINED", "C2_EXISTING_RISK_EVIDENCE_DRIFT")

            governance = c2_shadow_governance_evidence_v2(
                executor_id=cast(UUID, evidence.governance.executor_id),
                account_id=account_id,
                broker_server=str(_row(executor_row, "broker_server")),
                verified_at_utc=durable_governance_clock,
            )
            if existing is None and governance != evidence.governance:
                return CandidateC2ShadowPersistenceResult("QUARANTINED", "C2_GOVERNANCE_EVIDENCE_DRIFT")

            # Refresh the wall clock after every potentially blocking authority
            # lock and immediately before either reusing or creating authority.
            commit_at = await self._database_now(connection)
            if commit_at >= expiry:
                if existing is not None:
                    await self._terminalize(
                        connection,
                        candidate_id,
                        existing.reservation.expires_at_utc,
                        "C2_AUTHORITY_EXPIRED",
                        reservation_state="EXPIRED",
                        campaign_state="EXPIRED",
                    )
                    return CandidateC2ShadowPersistenceResult("INVALIDATED", "C2_AUTHORITY_EXPIRED")
                return await persist_rejection("C2_AUTHORITY_EXPIRED")
            if (
                not validate_account_snapshot(
                    snapshot,
                    expected_account_id=account_id,
                    policy=CampaignRiskPolicy(),
                    now=commit_at,
                ).allowed
                or durable_governance_clock > commit_at + timedelta(seconds=2)
                or durable_governance_clock < commit_at - timedelta(seconds=C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS)
            ):
                if existing is not None:
                    await self._terminalize(
                        connection,
                        candidate_id,
                        max(existing.reservation.reserved_at_utc, commit_at),
                        "C2_BROKER_RECONCILIATION_REQUIRED",
                        reservation_state="RECONCILIATION_REQUIRED",
                        campaign_state="RECONCILIATION_REQUIRED",
                    )
                    return CandidateC2ShadowPersistenceResult("INVALIDATED", "C2_BROKER_RECONCILIATION_REQUIRED")
                return await persist_rejection("C2_BROKER_RECONCILIATION_REQUIRED")

            # Revalidate the complete admitted graph after every blocking lock
            # and bind it once more to the exact durable latest snapshot before
            # reduction/persistence.  This is the final TOCTOU boundary.
            try:
                evidence = snapshot_candidate_c2_build_evidence_v2(evidence)
            except (ValidationError, ValueError):
                return CandidateC2ShadowPersistenceResult("QUARANTINED", "C2_BUILD_EVIDENCE_INTEGRITY_INVALID")
            if (
                snapshot != evidence.account_snapshot
                or evidence.account_snapshot_hash != account_snapshot_authority_hash_v2(snapshot)
            ):
                return CandidateC2ShadowPersistenceResult("QUARANTINED", "C2_ACCOUNT_SNAPSHOT_HASH_DRIFT")

            if saved is not None:
                return CandidateC2ShadowPersistenceResult(
                    "DUPLICATE", "C2_EVALUATION_ALREADY_PERSISTED", saved, existing
                )

            sequence = int(
                await connection.fetchval(
                    f"SELECT COALESCE(MAX(evaluation_sequence),0)+1 FROM {EVALUATION_TABLE} WHERE tradeplan_id=$1",
                    candidate_id,
                )
            )
            reduced = evaluate_candidate_c2_shadow_v2(
                evidence,
                evaluation_sequence=sequence,
                current_authority=existing,
            )
            if reduced.decision == "DUPLICATE":
                return CandidateC2ShadowPersistenceResult("DUPLICATE", reduced.reason_code, authority_bundle=existing)
            if reduced.decision == "QUARANTINED":
                return CandidateC2ShadowPersistenceResult("QUARANTINED", reduced.reason_code)
            if reduced.evaluation is None:
                raise CandidateC2ShadowV2IntegrityError("C2_REDUCTION_EVALUATION_MISSING")
            if reduced.decision == "APPROVED":
                if reduced.authority_bundle is None:
                    raise CandidateC2ShadowV2IntegrityError("C2_REDUCTION_AUTHORITY_MISSING")
                await self._insert_bundle(connection, evidence, reduced.authority_bundle)
            await self._insert_evaluation(connection, evidence, reduced.evaluation)
            return CandidateC2ShadowPersistenceResult(
                cast(CandidateC2ShadowPersistenceStatus, reduced.decision),
                reduced.reason_code,
                reduced.evaluation,
                reduced.authority_bundle,
            )

    async def reconcile_terminal(self, tradeplan_id: str, occurred_at: datetime) -> CandidateC2ShadowPersistenceResult:
        async with self._pg.transaction() as connection:
            parent = await _lock_and_validate_candidate_authority(connection, tradeplan_id)
            if parent is None:
                return CandidateC2ShadowPersistenceResult("REJECTED", "C2_CANDIDATE_MISSING")
            bundle = await self._load_bundle(connection, tradeplan_id, lock=True)
            if bundle is None:
                return CandidateC2ShadowPersistenceResult("DUPLICATE", "C2_NO_ACTIVE_AUTHORITY")
            reservation_row = await connection.fetchrow(
                f"SELECT state FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1", tradeplan_id
            )
            if str(_row(reservation_row, "state")) != "RESERVED":
                return CandidateC2ShadowPersistenceResult("DUPLICATE", "C2_AUTHORITY_ALREADY_TERMINAL")
            if not parent.terminal:
                return CandidateC2ShadowPersistenceResult("REJECTED", "C2_CANDIDATE_STILL_ACTIVE")
            terminal_at = max(parent.terminal_at, parent.candidate.decision_at_utc)
            await self._terminalize(connection, tradeplan_id, terminal_at, parent.terminal_reason)
            return CandidateC2ShadowPersistenceResult("INVALIDATED", parent.terminal_reason)

    async def reconcile_expired(self, tradeplan_id: str, occurred_at: datetime) -> CandidateC2ShadowPersistenceResult:
        """Atomically expire a reserved chain without resurrecting it."""

        # ``occurred_at`` is audit lineage only.  A caller-supplied future clock
        # must never be able to revoke a still-live risk reservation early.
        del occurred_at
        async with self._pg.transaction() as connection:
            parent = await _lock_and_validate_candidate_authority(connection, tradeplan_id)
            if parent is None:
                return CandidateC2ShadowPersistenceResult("REJECTED", "C2_CANDIDATE_MISSING")
            bundle = await self._load_bundle(connection, tradeplan_id, lock=True)
            if bundle is None:
                return CandidateC2ShadowPersistenceResult("DUPLICATE", "C2_NO_ACTIVE_AUTHORITY")
            row = await connection.fetchrow(
                f"SELECT state,expires_at FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1", tradeplan_id
            )
            if str(_row(row, "state")) != "RESERVED":
                return CandidateC2ShadowPersistenceResult("DUPLICATE", "C2_AUTHORITY_ALREADY_TERMINAL")
            expires_at = _row(row, "expires_at")
            database_now = await self._database_now(connection)
            if not isinstance(expires_at, datetime) or database_now < expires_at:
                return CandidateC2ShadowPersistenceResult("REJECTED", "C2_AUTHORITY_NOT_EXPIRED")
            await self._terminalize(
                connection,
                tradeplan_id,
                expires_at,
                "C2_AUTHORITY_EXPIRED",
                reservation_state="EXPIRED",
                campaign_state="EXPIRED",
            )
            return CandidateC2ShadowPersistenceResult("INVALIDATED", "C2_AUTHORITY_EXPIRED")

    @staticmethod
    def _snapshot_from_row(row: Any) -> AccountSnapshotV1:
        payload = _json(_row(row, "payload"))
        try:
            snapshot = AccountSnapshotV1.model_validate(payload)
        except ValidationError as exc:
            raise CandidateC2ShadowV2IntegrityError("C2_ACCOUNT_SNAPSHOT_PAYLOAD_INVALID") from exc
        columns = {
            "snapshot_id": snapshot.snapshot_id,
            "executor_id": snapshot.executor_id,
            "account_id": snapshot.account_id,
            "captured_at": snapshot.captured_at_utc,
            "balance": snapshot.balance,
            "equity": snapshot.equity,
            "floating_pnl": snapshot.floating_pnl,
            "used_margin": snapshot.used_margin,
            "free_margin": snapshot.free_margin,
            "margin_level_pct": snapshot.margin_level_pct,
            "margin_mode": snapshot.margin_mode.value,
            "trade_allowed": snapshot.trade_allowed,
            "autotrading_enabled": snapshot.autotrading_enabled,
            "broker_ledger_reconciled": snapshot.broker_ledger_reconciled,
            "pending_order_count": len(snapshot.pending_orders),
        }
        for key, value in columns.items():
            if not _durable_equal(_row(row, key), value):
                raise CandidateC2ShadowV2IntegrityError(f"C2_ACCOUNT_SNAPSHOT_COLUMN_DRIFT:{key}")
        return snapshot

    @staticmethod
    async def _derive_existing_risk(
        connection: Any,
        candidate: TradePlanCandidateV2,
        snapshot: AccountSnapshotV1,
        account_id: str,
        captured_at: datetime,
    ) -> C2ShadowExistingRiskEvidenceV2:
        row = await connection.fetchrow(
            f"""SELECT
                (SELECT count(*) FROM {CAMPAIGN_TABLE} WHERE account_id=$1 AND state='PARENT_PENDING' AND tradeplan_id<>$2) active_campaigns,
                (SELECT count(*) FROM {RESERVATION_TABLE} WHERE account_id=$1 AND state='RESERVED' AND tradeplan_id<>$2) active_reservations,
                (SELECT COALESCE(sum(reserved_risk_usd),0) FROM {RESERVATION_TABLE} WHERE account_id=$1 AND state='RESERVED' AND tradeplan_id<>$2) account_risk,
                (SELECT count(*) FROM strategy_5scr_campaign_risk_locks WHERE account_id=$1 AND state='ACTIVE') legacy_campaigns,
                (SELECT count(*) FROM strategy_5scr_risk_reservations WHERE account_id=$1 AND state IN ('HELD','CONSUMED','OPEN')) legacy_reservations,
                (SELECT COALESCE(sum(reserved_risk_usd),0) FROM strategy_5scr_risk_reservations WHERE account_id=$1 AND state IN ('HELD','CONSUMED','OPEN')) legacy_risk,
                (SELECT count(*) FROM execution_commands c
                   WHERE (c.account_id=$1 OR c.executor_id=$4::uuid OR EXISTS (
                             SELECT 1 FROM executor_instances command_executor
                             WHERE command_executor.executor_id=c.executor_id
                               AND command_executor.account_id=$1
                         ))
                     AND (
                         c.state NOT IN ('REJECTED','FILLED','CANCELLED','COMPLETED','EXPIRED','SHADOW_COMPLETED','SHADOW_REJECTED')
                         -- FILLED opens broker exposure, COMPLETED also
                         -- represents MODIFIED, and CANCELLED/EXPIRED may follow
                         -- a partial fill.  None is safe until a reconciled broker
                         -- snapshot strictly postdates its terminal transition.
                         -- NULL/equal clocks fail closed.
                         OR (c.state IN ('FILLED','COMPLETED','CANCELLED','EXPIRED')
                             AND (c.terminal_at IS NULL OR $3 <= c.terminal_at))
                     )) pending_commands""",
            account_id,
            candidate.tradeplan_id,
            snapshot.captured_at_utc,
            str(snapshot.executor_id),
        )
        values = {
            "account_id": account_id,
            "tradeplan_id": candidate.tradeplan_id,
            "active_campaign_count": int(_row(row, "active_campaigns")) + int(_row(row, "legacy_campaigns")),
            "active_reservation_count": int(_row(row, "active_reservations")) + int(_row(row, "legacy_reservations")),
            "pending_order_count": len(snapshot.pending_orders) + int(_row(row, "pending_commands")),
            "broker_ledger_reconciled": snapshot.broker_ledger_reconciled,
            "committed_or_reserved_campaign_risk_usd": Decimal(str(_row(row, "account_risk")))
            + Decimal(str(_row(row, "legacy_risk"))),
            "account_total_open_risk_usd": Decimal(str(_row(row, "account_risk")))
            + Decimal(str(_row(row, "legacy_risk"))),
            "captured_at_utc": captured_at,
        }
        return C2ShadowExistingRiskEvidenceV2(
            **values,
            evidence_hash=canonical_hash_v1(values),
        )

    async def _load_bundle(
        self,
        connection: Any,
        tradeplan_id: str,
        *,
        lock: bool,
        require_live: bool = False,
    ) -> C2ShadowAuthorityBundleV2 | None:
        suffix = " FOR UPDATE" if lock else ""
        rows: dict[str, Any] = {}
        for table in (HANDOFF_TABLE, RISK_LOCK_TABLE, RESERVATION_TABLE, CAMPAIGN_TABLE, OUTBOX_TABLE):
            row = await connection.fetchrow(f"SELECT * FROM {table} WHERE tradeplan_id=$1{suffix}", tradeplan_id)
            if row is not None:
                rows[table] = row
        if not rows:
            return None
        if set(rows) != {HANDOFF_TABLE, RISK_LOCK_TABLE, RESERVATION_TABLE, CAMPAIGN_TABLE, OUTBOX_TABLE}:
            raise CandidateC2ShadowV2IntegrityError("C2_PARTIAL_AUTHORITY_CHAIN")
        live = _validate_bundle_lifecycle(rows)
        bundle = _bundle_from_rows(rows)
        try:
            handoff_build = CandidateC2ShadowBuildEvidenceV2.model_validate(
                _json(_row(rows[HANDOFF_TABLE], "build_evidence_payload"))
            )
        except ValidationError as exc:
            raise CandidateC2ShadowV2IntegrityError("C2_HANDOFF_BUILD_EVIDENCE_INVALID") from exc
        candidate_row = await connection.fetchrow(
            f"SELECT * FROM {CANDIDATE_TABLE} WHERE tradeplan_id=$1", tradeplan_id
        )
        if candidate_row is None:
            raise CandidateC2ShadowV2IntegrityError("C2_HANDOFF_CANDIDATE_MISSING")
        candidate = _candidate_from_row(candidate_row)
        if (
            handoff_build.candidate.model_dump(mode="json", exclude={"lifecycle_state"})
            != candidate.model_dump(mode="json", exclude={"lifecycle_state"})
            or handoff_build.account_snapshot_hash != bundle.reservation.account_snapshot_hash
            or handoff_build.governance.evidence_hash != bundle.reservation.governance_evidence_hash
            or handoff_build.existing_risk.evidence_hash != bundle.reservation.existing_risk_evidence_hash
            or handoff_build.broker_symbol != bundle.reservation.broker_symbol
        ):
            raise CandidateC2ShadowV2IntegrityError("C2_HANDOFF_BUILD_EVIDENCE_DRIFT")
        snapshot_row = await connection.fetchrow(
            "SELECT * FROM executor_account_snapshots WHERE snapshot_id=$1",
            bundle.reservation.account_snapshot_id,
        )
        if snapshot_row is None:
            raise CandidateC2ShadowV2IntegrityError("C2_AUTHORITY_ACCOUNT_SNAPSHOT_MISSING")
        snapshot = self._snapshot_from_row(snapshot_row)
        if (
            snapshot != handoff_build.account_snapshot
            or snapshot.executor_id != bundle.reservation.executor_id
            or snapshot.account_id != bundle.reservation.account_id
            or account_snapshot_authority_hash_v2(snapshot) != bundle.reservation.account_snapshot_hash
        ):
            raise CandidateC2ShadowV2IntegrityError("C2_AUTHORITY_ACCOUNT_SNAPSHOT_DRIFT")
        evaluation_row = await connection.fetchrow(
            f"SELECT * FROM {EVALUATION_TABLE} WHERE tradeplan_id=$1 AND decision='APPROVED' "
            "AND result_execution_campaign_id=$2 AND result_reservation_id=$3",
            tradeplan_id,
            bundle.execution_campaign.execution_campaign_id,
            bundle.reservation.reservation_id,
        )
        if evaluation_row is None:
            raise CandidateC2ShadowV2IntegrityError("C2_AUTHORITY_ORIGIN_EVALUATION_MISSING")
        evaluation = self._evaluation_from_row(evaluation_row)
        try:
            evaluation_build = CandidateC2ShadowBuildEvidenceV2.model_validate(
                _json(_row(evaluation_row, "build_evidence_payload"))
            )
        except ValidationError as exc:
            raise CandidateC2ShadowV2IntegrityError("C2_AUTHORITY_ORIGIN_EVIDENCE_INVALID") from exc
        if (
            evaluation_build != handoff_build
            or evaluation.evidence_hash != handoff_build.authority_hash()
            or evaluation.material_candidate_hash != candidate.material_candidate_hash
        ):
            raise CandidateC2ShadowV2IntegrityError("C2_AUTHORITY_ORIGIN_EVALUATION_DRIFT")
        rebuilt = evaluate_candidate_c2_shadow_v2(
            handoff_build,
            evaluation_sequence=evaluation.evaluation_sequence,
        )
        if rebuilt.decision != "APPROVED" or rebuilt.authority_bundle != bundle:
            raise CandidateC2ShadowV2IntegrityError("C2_AUTHORITY_CANONICAL_REDUCTION_DRIFT")
        if require_live and not live:
            return None
        return bundle

    @staticmethod
    def _evaluation_from_row(row: Any) -> C2ShadowEvaluationV2:
        evaluation = _payload_model(C2ShadowEvaluationV2, row)
        try:
            build = CandidateC2ShadowBuildEvidenceV2.model_validate(_json(_row(row, "build_evidence_payload")))
        except ValidationError as exc:
            raise CandidateC2ShadowV2IntegrityError("C2_EVALUATION_BUILD_EVIDENCE_INVALID") from exc
        candidate = build.candidate
        if (
            evaluation.source_request_id != build.source_request_id
            or evaluation.tradeplan_id != candidate.tradeplan_id
            or evaluation.material_candidate_hash != candidate.material_candidate_hash
            or evaluation.account_id != build.account_snapshot.account_id
            or evaluation.executor_id != build.account_snapshot.executor_id
            or evaluation.decision_at_utc != build.decision_at_utc
            or evaluation.evidence_hash != build.authority_hash()
        ):
            raise CandidateC2ShadowV2IntegrityError("C2_EVALUATION_BUILD_EVIDENCE_DRIFT")
        fields = {
            "evaluation_id": evaluation.evaluation_id,
            "evaluation_sequence": evaluation.evaluation_sequence,
            "source_request_id": build.source_request_id,
            "tradeplan_id": candidate.tradeplan_id,
            "strategy_lifecycle_id": candidate.strategy_lifecycle_id,
            "context_epoch_id": candidate.context_epoch_id,
            "strategy_thesis_id": candidate.strategy_thesis_id,
            "execution_box_id": candidate.execution_box_id,
            "symbol": candidate.symbol,
            "strategy_direction": candidate.direction,
            "material_context_hash": candidate.material_context_hash,
            "thesis_semantic_identity_hash": candidate.thesis_semantic_identity_hash,
            "candidate_sequence": candidate.candidate_sequence,
            "candidate_revision": candidate.candidate_revision,
            "material_candidate_hash": candidate.material_candidate_hash,
            "formation_evidence_hash": candidate.evidence_hash,
            "account_id": build.account_snapshot.account_id,
            "executor_id": build.account_snapshot.executor_id,
            "account_snapshot_id": build.account_snapshot.snapshot_id,
            "decision_at": build.decision_at_utc,
            "decision": evaluation.decision,
            "reason_code": evaluation.reason_code,
            "evidence_hash": build.authority_hash(),
            "material_evaluation_hash": evaluation.material_evaluation_hash,
            "result_execution_campaign_id": evaluation.result_execution_campaign_id,
            "result_reservation_id": evaluation.result_reservation_id,
            "rule_version": evaluation.rule_version,
            "execution_authority": False,
        }
        for key, value in fields.items():
            if str(_row(row, key)) != str(value):
                raise CandidateC2ShadowV2IntegrityError(f"C2_EVALUATION_DURABLE_DRIFT:{key}")
        return evaluation

    @staticmethod
    async def _insert_bundle(
        connection: Any, evidence: CandidateC2ShadowBuildEvidenceV2, bundle: C2ShadowAuthorityBundleV2
    ) -> None:
        handoff, risk_lock, reservation, campaign, signal = (
            bundle.handoff,
            bundle.risk_lock,
            bundle.reservation,
            bundle.execution_campaign,
            bundle.final_signal,
        )
        await connection.execute(
            f"""INSERT INTO {HANDOFF_TABLE} (
                handoff_id,tradeplan_id,strategy_lifecycle_id,context_epoch_id,strategy_thesis_id,execution_box_id,
                account_id,executor_id,broker_server,account_snapshot_hash,
                symbol,strategy_direction,material_context_hash,thesis_semantic_identity_hash,candidate_sequence,
                candidate_revision,material_candidate_hash,formation_evidence_hash,candidate_price,stop_loss,take_profit,
                target_authority_hash,stop_authority_hash,broker_geometry_material_hash,accepted_at,authority_hash,
                execution_mode,execution_authority,payload,build_evidence_payload)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8::uuid,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,'SHADOW',false,$27::jsonb,$28::jsonb)""",
            handoff.handoff_id,
            handoff.tradeplan_id,
            handoff.strategy_lifecycle_id,
            handoff.context_epoch_id,
            handoff.strategy_thesis_id,
            handoff.execution_box_id,
            handoff.account_id,
            str(handoff.executor_id),
            handoff.broker_server,
            handoff.account_snapshot_hash,
            handoff.symbol,
            handoff.direction,
            handoff.material_context_hash,
            handoff.thesis_semantic_identity_hash,
            handoff.candidate_sequence,
            handoff.candidate_revision,
            handoff.material_candidate_hash,
            handoff.candidate_evidence_hash,
            handoff.candidate_price,
            handoff.stop_loss,
            handoff.take_profit,
            handoff.target_authority_hash,
            handoff.stop_authority_hash,
            handoff.broker_geometry_material_hash,
            handoff.accepted_at_utc,
            handoff.authority_hash,
            _dump(handoff),
            _dump(evidence),
        )
        await connection.execute(
            f"""INSERT INTO {RISK_LOCK_TABLE} (risk_lock_id,execution_campaign_id,handoff_id,tradeplan_id,account_id,
                account_snapshot_id,policy_id,balance_base,risk_percent_per_entry,risk_unit_usd,max_campaign_risk_usd,
                locked_at,authority_hash,risk_authority,broker_execution_authority,state,payload)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,true,false,'ACTIVE',$14::jsonb)""",
            risk_lock.risk_lock_id,
            risk_lock.execution_campaign_id,
            handoff.handoff_id,
            risk_lock.tradeplan_id,
            risk_lock.account_id,
            risk_lock.account_snapshot_id,
            risk_lock.policy_id,
            risk_lock.balance_base,
            risk_lock.risk_percent_per_entry,
            risk_lock.risk_unit_usd,
            risk_lock.max_campaign_risk_usd,
            risk_lock.locked_at_utc,
            risk_lock.authority_hash,
            _dump(risk_lock),
        )
        await connection.execute(
            f"""INSERT INTO {RESERVATION_TABLE} (reservation_id,execution_campaign_id,risk_lock_id,handoff_id,tradeplan_id,
                executor_id,account_id,account_snapshot_id,account_snapshot_hash,symbol_capability_hash,
                governance_evidence_hash,existing_risk_evidence_hash,broker_server,canonical_symbol,broker_symbol,direction,
                entry_role,state,volume,entry_price,stop_loss,take_profit,risk_unit_usd,reserved_risk_usd,reserved_at,
                expires_at,authority_hash,risk_authority,valid_for_execution,execution_mode,broker_execution_authority,
                command_authority,payload)
                VALUES ($1,$2,$3,$4,$5,$6::uuid,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,'PARENT','RESERVED',$17,$18,$19,
                        $20,$21,$22,$23,$24,$25,true,true,'SHADOW',false,false,$26::jsonb)""",
            reservation.reservation_id,
            reservation.execution_campaign_id,
            reservation.risk_lock_id,
            reservation.handoff_id,
            reservation.tradeplan_id,
            str(reservation.executor_id),
            reservation.account_id,
            reservation.account_snapshot_id,
            reservation.account_snapshot_hash,
            reservation.symbol_capability_hash,
            reservation.governance_evidence_hash,
            reservation.existing_risk_evidence_hash,
            reservation.broker_server,
            reservation.canonical_symbol,
            reservation.broker_symbol,
            reservation.direction,
            reservation.volume,
            reservation.entry_price,
            reservation.stop_loss,
            reservation.take_profit,
            reservation.risk_unit_usd,
            reservation.reserved_risk_usd,
            reservation.reserved_at_utc,
            reservation.expires_at_utc,
            reservation.authority_hash,
            _dump(reservation),
        )
        await connection.execute(
            f"""INSERT INTO {CAMPAIGN_TABLE} (execution_campaign_id,tradeplan_id,reservation_id,account_id,canonical_symbol,
                direction,state,execution_mode,opened_at,authority_hash,risk_authority,broker_execution_authority,
                command_authority,payload) VALUES ($1,$2,$3,$4,$5,$6,'PARENT_PENDING','SHADOW',$7,$8,true,false,false,$9::jsonb)""",
            campaign.execution_campaign_id,
            campaign.tradeplan_id,
            campaign.reservation_id,
            campaign.account_id,
            campaign.canonical_symbol,
            campaign.direction,
            campaign.opened_at_utc,
            campaign.authority_hash,
            _dump(campaign),
        )
        outbox_id = "5scr-c2-outbox-v2:" + hashlib.sha256(signal.signal_id.encode()).hexdigest()[:32]
        full_payload_hash = canonical_hash_v1(signal.model_dump(mode="json"))
        await connection.execute(
            f"""INSERT INTO {OUTBOX_TABLE} (outbox_id,signal_id,execution_campaign_id,reservation_id,tradeplan_id,
                account_snapshot_id,account_id,executor_id,broker_server,handoff_id,risk_lock_id,account_snapshot_hash,
                symbol_capability_hash,governance_evidence_hash,existing_risk_evidence_hash,material_candidate_hash,
                candidate_evidence_hash,canonical_symbol,broker_symbol,direction,entry_role,payload,payload_hash,
                authority_hash,status,
                delivery_authority,broker_execution_authority,command_authority,created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8::uuid,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22::jsonb,
                        $23,$24,'PENDING',false,false,false,$25)""",
            outbox_id,
            signal.signal_id,
            signal.execution_campaign_id,
            signal.reservation_id,
            signal.tradeplan_id,
            signal.risk_snapshot_id,
            signal.account_id,
            str(signal.executor_id),
            signal.broker_server,
            signal.handoff_id,
            signal.risk_lock_id,
            signal.account_snapshot_hash,
            signal.symbol_capability_hash,
            signal.governance_evidence_hash,
            signal.existing_risk_evidence_hash,
            signal.material_candidate_hash,
            signal.candidate_evidence_hash,
            signal.canonical_symbol,
            signal.broker_symbol,
            signal.final_direction,
            signal.entry_role,
            _dump(signal),
            full_payload_hash,
            signal.authority_hash,
            signal.issued_at_utc,
        )

    @staticmethod
    async def _insert_evaluation(
        connection: Any, evidence: CandidateC2ShadowBuildEvidenceV2, evaluation: C2ShadowEvaluationV2
    ) -> None:
        c = evidence.candidate
        await connection.execute(
            f"""INSERT INTO {EVALUATION_TABLE} (evaluation_id,tradeplan_id,strategy_lifecycle_id,context_epoch_id,
                strategy_thesis_id,execution_box_id,symbol,strategy_direction,material_context_hash,
                thesis_semantic_identity_hash,candidate_sequence,candidate_revision,material_candidate_hash,
                formation_evidence_hash,evaluation_sequence,source_request_id,account_id,executor_id,decision_at,decision,
                reason_code,evidence_hash,material_evaluation_hash,result_execution_campaign_id,result_reservation_id,
                rule_version,execution_authority,payload,build_evidence_payload)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18::uuid,$19,$20,$21,$22,$23,$24,
                        $25,$26,false,$27::jsonb,$28::jsonb)""",
            evaluation.evaluation_id,
            c.tradeplan_id,
            c.strategy_lifecycle_id,
            c.context_epoch_id,
            c.strategy_thesis_id,
            c.execution_box_id,
            c.symbol,
            c.direction,
            c.material_context_hash,
            c.thesis_semantic_identity_hash,
            c.candidate_sequence,
            c.candidate_revision,
            c.material_candidate_hash,
            c.evidence_hash,
            evaluation.evaluation_sequence,
            evaluation.source_request_id,
            evaluation.account_id,
            str(evaluation.executor_id),
            evaluation.decision_at_utc,
            evaluation.decision,
            evaluation.reason_code,
            evaluation.evidence_hash,
            evaluation.material_evaluation_hash,
            evaluation.result_execution_campaign_id,
            evaluation.result_reservation_id,
            evaluation.rule_version,
            _dump(evaluation),
            _dump(evidence),
        )

    async def _terminalize(
        self,
        connection: Any,
        tradeplan_id: str,
        occurred_at: datetime,
        reason: str,
        *,
        reservation_state: str = "INVALIDATED",
        campaign_state: str = "INVALIDATED",
    ) -> None:
        reservation_clock = await connection.fetchrow(
            f"SELECT reserved_at,expires_at FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1 FOR UPDATE",
            tradeplan_id,
        )
        reserved_at = _row(reservation_clock, "reserved_at")
        expires_at = _row(reservation_clock, "expires_at")
        database_now = await self._database_now(connection)
        if not isinstance(reserved_at, datetime):
            raise CandidateC2ShadowV2IntegrityError("C2_TERMINAL_FORMATION_CLOCK_INVALID")
        if reason == "C2_AUTHORITY_EXPIRED":
            # Expiry is the one terminal event with an exact, previously
            # admitted durable clock.  Callers prove it is due before arriving
            # here; retain that exact boundary for deterministic replay.
            if not isinstance(expires_at, datetime) or expires_at < reserved_at or expires_at > database_now:
                raise CandidateC2ShadowV2IntegrityError("C2_TERMINAL_EXPIRY_CLOCK_INVALID")
            terminal_at = expires_at
        else:
            # External evidence may explain *why* authority closed, but never
            # controls its durable audit time.  Clamp it to both the P7
            # formation floor and PostgreSQL's current clock.
            terminal_at = max(reserved_at, min(occurred_at, database_now))
        await connection.execute(
            f"UPDATE {OUTBOX_TABLE} SET status='CANCELLED',terminal_at=$2,terminal_reason=$3,state_version=state_version+1 "
            "WHERE tradeplan_id=$1 AND status='PENDING'",
            tradeplan_id,
            terminal_at,
            reason,
        )
        await connection.execute(
            f"UPDATE {CAMPAIGN_TABLE} SET state=$4,terminal_at=$2,terminal_reason=$3,state_version=state_version+1 "
            "WHERE tradeplan_id=$1 AND state='PARENT_PENDING'",
            tradeplan_id,
            terminal_at,
            reason,
            campaign_state,
        )
        await connection.execute(
            f"UPDATE {RESERVATION_TABLE} SET state=$4,terminal_at=$2,terminal_reason=$3,state_version=state_version+1 "
            "WHERE tradeplan_id=$1 AND state='RESERVED'",
            tradeplan_id,
            terminal_at,
            reason,
            reservation_state,
        )
        await connection.execute(
            f"UPDATE {RISK_LOCK_TABLE} SET state='CLOSED',closed_at=$2,terminal_reason=$3,state_version=state_version+1 "
            "WHERE tradeplan_id=$1 AND state='ACTIVE'",
            tradeplan_id,
            terminal_at,
            reason,
        )


__all__ = [
    "CAMPAIGN_TABLE",
    "CandidateC2ShadowPersistenceResult",
    "CandidateC2ShadowV2IntegrityError",
    "CandidateC2ShadowV2RuntimeConfig",
    "CandidateC2ShadowV2SchemaStatus",
    "EVALUATION_TABLE",
    "HANDOFF_TABLE",
    "OUTBOX_TABLE",
    "RESERVATION_TABLE",
    "RISK_LOCK_TABLE",
    "Strategy5SCRCandidateC2ShadowV2Repository",
]
