"""Durable repository for command-inert C2 SHADOW risk projections only."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from contracts.mt5_execution_protocol import AccountSnapshotV1
from contracts.strategy_5scr_candidate_c2_shadow_v2 import account_snapshot_authority_hash_v2
from contracts.strategy_5scr_shadow_risk_projection import C2ShadowRiskProjectionV1
from storage.postgres_client import PostgresClient, pg_client
from storage.strategy_5scr_tradeplan_candidate_v2_repository import (
    TradePlanCandidateV2IntegrityError,
    _candidate_from_row,
)

SHADOW_RISK_PROJECTION_TABLE = "strategy_5scr_shadow_risk_projections_v1"


class ShadowRiskProjectionIntegrityError(RuntimeError):
    """A durable projection disagrees with its frozen authority contract."""


class ShadowRiskProjectionStateError(RuntimeError):
    """A projection is unavailable, expired, or concurrently consumed."""


def _row(row: Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, TypeError):
        return getattr(row, key, None)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ShadowRiskProjectionIntegrityError("C2_SHADOW_PROJECTION_JSON_INVALID")
    return dict(value)


def _projection_from_row(row: Any) -> C2ShadowRiskProjectionV1:
    if row is None:
        raise ShadowRiskProjectionIntegrityError("C2_SHADOW_PROJECTION_ROW_MISSING")
    payload = {
        "shadow_authority_id": str(_row(row, "shadow_authority_id")),
        "source_admission_class": str(_row(row, "source_admission_class")),
        "tradeplan_id": str(_row(row, "tradeplan_id")),
        "strategy_lifecycle_id": str(_row(row, "strategy_lifecycle_id")),
        "context_epoch_id": str(_row(row, "context_epoch_id")),
        "strategy_thesis_id": str(_row(row, "strategy_thesis_id")),
        "execution_box_id": str(_row(row, "execution_box_id")),
        "candidate_sequence": int(_row(row, "candidate_sequence")),
        "candidate_revision": int(_row(row, "candidate_revision")),
        "material_context_hash": str(_row(row, "material_context_hash")),
        "thesis_semantic_identity_hash": str(_row(row, "thesis_semantic_identity_hash")),
        "material_candidate_hash": str(_row(row, "material_candidate_hash")),
        "candidate_evidence_hash": str(_row(row, "candidate_evidence_hash")),
        "executor_id": _row(row, "executor_id"),
        "account_id": str(_row(row, "account_id")),
        "account_snapshot_id": str(_row(row, "account_snapshot_id")),
        "account_snapshot_hash": str(_row(row, "account_snapshot_hash")),
        "broker_server": str(_row(row, "broker_server")),
        "symbol": str(_row(row, "symbol")),
        "broker_symbol": str(_row(row, "broker_symbol")),
        "direction": str(_row(row, "direction")),
        "entry_price": Decimal(_row(row, "entry_price")),
        "stop_loss": Decimal(_row(row, "stop_loss")),
        "target_price": Decimal(_row(row, "target_price")),
        "would_volume": (None if _row(row, "would_volume") is None else Decimal(_row(row, "would_volume"))),
        "would_risk_usd": (None if _row(row, "would_risk_usd") is None else Decimal(_row(row, "would_risk_usd"))),
        "would_margin_usd": (None if _row(row, "would_margin_usd") is None else Decimal(_row(row, "would_margin_usd"))),
        "would_margin_status": str(_row(row, "would_margin_status")),
        "would_open_risk_after_usd": (
            None if _row(row, "would_open_risk_after_usd") is None else Decimal(_row(row, "would_open_risk_after_usd"))
        ),
        "decision": str(_row(row, "decision")),
        "reason_code": str(_row(row, "reason_code")),
        "state": str(_row(row, "state")),
        "state_version": int(_row(row, "state_version")),
        "kill_switch_observed": str(_row(row, "kill_switch_observed")),
        "projected_at_utc": _row(row, "projected_at"),
        "expires_at_utc": _row(row, "expires_at"),
        "evidence_hash": str(_row(row, "evidence_hash")),
        "authority_hash": str(_row(row, "authority_hash")),
        "rule_version": str(_row(row, "rule_version")),
        "execution_authority": bool(_row(row, "execution_authority")),
        "capital_reserved": bool(_row(row, "capital_reserved")),
        "broker_side_effect_allowed": bool(_row(row, "broker_side_effect_allowed")),
        "order_send_eligible": bool(_row(row, "order_send_eligible")),
    }
    try:
        return C2ShadowRiskProjectionV1.model_validate(payload)
    except (TypeError, ValueError) as exc:
        raise ShadowRiskProjectionIntegrityError("C2_SHADOW_PROJECTION_DURABLE_DRIFT") from exc


_INSERT_FIELDS = (
    "shadow_authority_id",
    "source_admission_class",
    "tradeplan_id",
    "strategy_lifecycle_id",
    "context_epoch_id",
    "strategy_thesis_id",
    "execution_box_id",
    "candidate_sequence",
    "candidate_revision",
    "material_context_hash",
    "thesis_semantic_identity_hash",
    "material_candidate_hash",
    "candidate_evidence_hash",
    "executor_id",
    "account_id",
    "account_snapshot_id",
    "account_snapshot_hash",
    "broker_server",
    "symbol",
    "broker_symbol",
    "direction",
    "entry_price",
    "stop_loss",
    "target_price",
    "would_volume",
    "would_risk_usd",
    "would_margin_usd",
    "would_margin_status",
    "would_open_risk_after_usd",
    "decision",
    "reason_code",
    "state",
    "state_version",
    "kill_switch_observed",
    "projected_at",
    "expires_at",
    "evidence_hash",
    "authority_hash",
    "rule_version",
    "execution_authority",
    "capital_reserved",
    "broker_side_effect_allowed",
    "order_send_eligible",
)


def _insert_values(projection: C2ShadowRiskProjectionV1) -> tuple[Any, ...]:
    values = projection.model_dump(mode="python")
    values["projected_at"] = values.pop("projected_at_utc")
    values["expires_at"] = values.pop("expires_at_utc")
    return tuple(values[field] for field in _INSERT_FIELDS)


class Strategy5SCRShadowRiskProjectionRepository:
    """Persist projections without touching risk reservations or command outboxes."""

    def __init__(self, pg: PostgresClient = pg_client) -> None:
        self._pg = pg

    @staticmethod
    async def _validate_dependencies(connection: Any, projection: C2ShadowRiskProjectionV1) -> None:
        candidate_row = await connection.fetchrow(
            "SELECT * FROM strategy_5scr_tradeplan_candidates_v2 WHERE tradeplan_id=$1 FOR UPDATE",
            projection.tradeplan_id,
        )
        if candidate_row is None:
            raise ShadowRiskProjectionStateError("C2_SHADOW_CANONICAL_CANDIDATE_MISSING")
        try:
            candidate = _candidate_from_row(candidate_row)
        except (TradePlanCandidateV2IntegrityError, TypeError, ValidationError, ValueError) as exc:
            raise ShadowRiskProjectionIntegrityError("C2_SHADOW_CANONICAL_CANDIDATE_DRIFT") from exc
        candidate_scope = (
            candidate.tradeplan_id,
            candidate.strategy_lifecycle_id,
            candidate.context_epoch_id,
            candidate.strategy_thesis_id,
            candidate.execution_box_id,
            candidate.candidate_sequence,
            candidate.candidate_revision,
            candidate.material_context_hash,
            candidate.thesis_semantic_identity_hash,
            candidate.material_candidate_hash,
            candidate.evidence_hash,
            candidate.symbol,
            candidate.direction,
            candidate.candidate_price,
            candidate.stop_authority.structural_stop_price,
            candidate.target_authority.target_price,
        )
        projection_scope = (
            projection.tradeplan_id,
            projection.strategy_lifecycle_id,
            projection.context_epoch_id,
            projection.strategy_thesis_id,
            projection.execution_box_id,
            projection.candidate_sequence,
            projection.candidate_revision,
            projection.material_context_hash,
            projection.thesis_semantic_identity_hash,
            projection.material_candidate_hash,
            projection.candidate_evidence_hash,
            projection.symbol,
            projection.direction.value if hasattr(projection.direction, "value") else projection.direction,
            projection.entry_price,
            projection.stop_loss,
            projection.target_price,
        )
        if candidate.lifecycle_state != "ACTIVE" or candidate_scope != projection_scope:
            raise ShadowRiskProjectionStateError("C2_SHADOW_CANONICAL_CANDIDATE_NOT_CURRENT")
        successor = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM strategy_5scr_tradeplan_candidates_v2 WHERE previous_tradeplan_id=$1)",
            projection.tradeplan_id,
        )
        if bool(successor):
            raise ShadowRiskProjectionStateError("C2_SHADOW_CANONICAL_CANDIDATE_SUPERSEDED")

        executor = await connection.fetchrow(
            "SELECT executor_id,account_id,broker_server,execution_mode,revoked_at,status "
            "FROM executor_instances WHERE executor_id=$1::uuid FOR NO KEY UPDATE",
            str(projection.executor_id),
        )
        if (
            executor is None
            or _row(executor, "revoked_at") is not None
            or str(_row(executor, "execution_mode")) != "SHADOW"
            or str(_row(executor, "account_id")) != projection.account_id
            or str(_row(executor, "broker_server")) != projection.broker_server
        ):
            raise ShadowRiskProjectionStateError("C2_SHADOW_EXECUTOR_BINDING_NOT_CURRENT")
        governance = await connection.fetchrow(
            "SELECT kill_switch_active,governance_version FROM executor_bridge_governance "
            "WHERE singleton_id=1 FOR UPDATE"
        )
        if governance is None or not bool(_row(governance, "kill_switch_active")):
            raise ShadowRiskProjectionStateError("C2_SHADOW_KILL_SWITCH_NOT_ENGAGED")

        snapshot_row = await connection.fetchrow(
            "SELECT * FROM executor_account_snapshots "
            "WHERE snapshot_id=$1 AND executor_id=$2::uuid AND account_id=$3 FOR NO KEY UPDATE",
            projection.account_snapshot_id,
            str(projection.executor_id),
            projection.account_id,
        )
        if snapshot_row is None:
            raise ShadowRiskProjectionStateError("C2_SHADOW_ACCOUNT_SNAPSHOT_MISSING")
        try:
            snapshot = AccountSnapshotV1.model_validate(_json_object(_row(snapshot_row, "payload")))
        except (TypeError, ValidationError, ValueError) as exc:
            raise ShadowRiskProjectionIntegrityError("C2_SHADOW_ACCOUNT_SNAPSHOT_INVALID") from exc
        snapshot_scope = (
            snapshot.snapshot_id,
            snapshot.executor_id,
            snapshot.account_id,
            snapshot.captured_at_utc,
            snapshot.balance,
            snapshot.equity,
            snapshot.floating_pnl,
            snapshot.used_margin,
            snapshot.free_margin,
            snapshot.margin_level_pct,
            snapshot.margin_mode.value,
            snapshot.trade_allowed,
            snapshot.autotrading_enabled,
            snapshot.broker_ledger_reconciled,
            len(snapshot.pending_orders),
        )
        durable_scope = (
            str(_row(snapshot_row, "snapshot_id")),
            _row(snapshot_row, "executor_id"),
            str(_row(snapshot_row, "account_id")),
            _row(snapshot_row, "captured_at"),
            float(_row(snapshot_row, "balance")),
            float(_row(snapshot_row, "equity")),
            float(_row(snapshot_row, "floating_pnl")),
            float(_row(snapshot_row, "used_margin")),
            float(_row(snapshot_row, "free_margin")),
            None if _row(snapshot_row, "margin_level_pct") is None else float(_row(snapshot_row, "margin_level_pct")),
            str(_row(snapshot_row, "margin_mode")),
            bool(_row(snapshot_row, "trade_allowed")),
            bool(_row(snapshot_row, "autotrading_enabled")),
            bool(_row(snapshot_row, "broker_ledger_reconciled")),
            int(_row(snapshot_row, "pending_order_count")),
        )
        if (
            snapshot_scope != durable_scope
            or account_snapshot_authority_hash_v2(snapshot) != projection.account_snapshot_hash
        ):
            raise ShadowRiskProjectionIntegrityError("C2_SHADOW_ACCOUNT_SNAPSHOT_HASH_DRIFT")
        database_now = await connection.fetchval("SELECT clock_timestamp()")
        if not isinstance(database_now, datetime) or not (
            projection.projected_at_utc <= database_now < projection.expires_at_utc
        ):
            raise ShadowRiskProjectionStateError("C2_SHADOW_PROJECTION_CLOCK_INVALID")

    async def persist_projection(self, projection: C2ShadowRiskProjectionV1) -> C2ShadowRiskProjectionV1:
        projection = C2ShadowRiskProjectionV1.model_validate(projection.model_dump(mode="python"))
        columns = ",".join(_INSERT_FIELDS)
        placeholders = ",".join(f"${index}" for index in range(1, len(_INSERT_FIELDS) + 1))
        async with self._pg.transaction() as connection:
            await self._validate_dependencies(connection, projection)
            await connection.execute(
                f"INSERT INTO {SHADOW_RISK_PROJECTION_TABLE} ({columns}) "
                f"VALUES ({placeholders}) ON CONFLICT DO NOTHING",
                *_insert_values(projection),
            )
            rows = await connection.fetch(
                f"""SELECT * FROM {SHADOW_RISK_PROJECTION_TABLE}
                    WHERE shadow_authority_id=$1
                       OR (tradeplan_id=$2 AND candidate_sequence=$3 AND candidate_revision=$4
                           AND executor_id=$5::uuid AND account_id=$6 AND account_snapshot_id=$7)
                    FOR UPDATE""",
                projection.shadow_authority_id,
                projection.tradeplan_id,
                projection.candidate_sequence,
                projection.candidate_revision,
                str(projection.executor_id),
                projection.account_id,
                projection.account_snapshot_id,
            )
            if len(rows) != 1:
                raise ShadowRiskProjectionIntegrityError("C2_SHADOW_PROJECTION_IDENTITY_COLLISION")
            persisted = _projection_from_row(rows[0])
            if persisted != projection:
                raise ShadowRiskProjectionIntegrityError("C2_SHADOW_PROJECTION_IMMUTABLE_CONFLICT")
            return persisted

    async def load_projection(self, shadow_authority_id: str) -> C2ShadowRiskProjectionV1 | None:
        row = await self._pg.fetchrow(
            f"SELECT * FROM {SHADOW_RISK_PROJECTION_TABLE} WHERE shadow_authority_id=$1",
            shadow_authority_id,
        )
        return None if row is None else _projection_from_row(row)

    async def lock_available(
        self,
        connection: Any,
        shadow_authority_id: str,
    ) -> C2ShadowRiskProjectionV1:
        row = await connection.fetchrow(
            f"""SELECT * FROM {SHADOW_RISK_PROJECTION_TABLE}
                WHERE shadow_authority_id=$1 AND state='AVAILABLE' AND expires_at>clock_timestamp()
                FOR UPDATE""",
            shadow_authority_id,
        )
        if row is None:
            raise ShadowRiskProjectionStateError("C2_SHADOW_PROJECTION_NOT_AVAILABLE")
        return _projection_from_row(row)

    async def mark_command_issued(
        self,
        connection: Any,
        *,
        shadow_authority_id: str,
        expected_authority_hash: str,
        expected_state_version: int,
    ) -> C2ShadowRiskProjectionV1:
        """Transition inside the caller's command-insert transaction."""

        row = await connection.fetchrow(
            f"""UPDATE {SHADOW_RISK_PROJECTION_TABLE}
                SET state='COMMAND_ISSUED',state_version=state_version+1,updated_at=clock_timestamp()
                WHERE shadow_authority_id=$1 AND authority_hash=$2 AND state='AVAILABLE'
                  AND state_version=$3 AND expires_at>clock_timestamp()
                RETURNING *""",
            shadow_authority_id,
            expected_authority_hash,
            expected_state_version,
        )
        if row is None:
            raise ShadowRiskProjectionStateError("C2_SHADOW_PROJECTION_CONCURRENT_OR_EXPIRED")
        return _projection_from_row(row)


__all__ = [
    "SHADOW_RISK_PROJECTION_TABLE",
    "ShadowRiskProjectionIntegrityError",
    "ShadowRiskProjectionStateError",
    "Strategy5SCRShadowRiskProjectionRepository",
]
