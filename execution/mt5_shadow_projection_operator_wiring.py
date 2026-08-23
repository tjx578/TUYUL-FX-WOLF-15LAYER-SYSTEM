"""Manual, one-shot C3 issuance from a C2 SHADOW risk projection.

Nothing imports this module from a service runner.  One explicit operator
request executes one PostgreSQL transaction that locks every authority input,
marks the projection consumed, inserts one signed command, and appends one
immutable issuance record.  No real risk reservation or broker call exists in
this path.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from contracts.mt5_execution_protocol import (
    AccountSnapshotV1,
    ExecutionCommandV1,
    build_signed_execution_envelope,
    sha256_tag,
)
from contracts.mt5_shadow_projection_command import (
    C3ShadowProjectionCommandManifest,
    C3ShadowProjectionCommandRequest,
)
from contracts.strategy_5scr_shadow_risk_projection import C2ShadowRiskProjectionV1
from execution.execution_plane_flags import ExecutionPlaneFlags, validate_execution_plane
from execution.mt5_shadow_projection_command_promotion import promote_shadow_projection_to_command
from storage.postgres_client import PostgresClient, pg_client

PROJECTION_TABLE = "strategy_5scr_shadow_risk_projections_v1"
ISSUANCE_TABLE = "strategy_5scr_c3_shadow_issuances_v1"
_REQUEST_CLOCK_SKEW_SECONDS = 5.0
_SNAPSHOT_MAX_AGE_SECONDS = 30.0


class C3ShadowProjectionWiringError(RuntimeError):
    reason_code = "C3_SHADOW_PROJECTION_ERROR"


class C3ShadowProjectionNotReadyError(C3ShadowProjectionWiringError):
    reason_code = "C3_SHADOW_PROJECTION_NOT_READY"


class C3ShadowProjectionConflictError(C3ShadowProjectionWiringError):
    reason_code = "C3_SHADOW_PROJECTION_CONFLICT"


class C3ShadowProjectionIntegrityError(C3ShadowProjectionWiringError):
    reason_code = "C3_SHADOW_PROJECTION_INTEGRITY"


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), default=str)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise C3ShadowProjectionIntegrityError("C3_DURABLE_JSON_NOT_OBJECT")
    return dict(value)


def _projection_from_row(row: Any) -> C2ShadowRiskProjectionV1:
    data = dict(row)
    data["projected_at_utc"] = data.pop("projected_at")
    data["expires_at_utc"] = data.pop("expires_at")
    data.pop("created_at", None)
    data.pop("updated_at", None)
    try:
        return C2ShadowRiskProjectionV1.model_validate(data)
    except (TypeError, ValueError) as exc:
        raise C3ShadowProjectionIntegrityError("C3_PROJECTION_DURABLE_DRIFT") from exc


def _manifest_from_row(row: Any) -> C3ShadowProjectionCommandManifest:
    try:
        manifest = C3ShadowProjectionCommandManifest.model_validate(_mapping(row["manifest"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise C3ShadowProjectionIntegrityError("C3_ISSUANCE_MANIFEST_DRIFT") from exc
    if str(row["command_id"]) != str(manifest.command_id):
        raise C3ShadowProjectionIntegrityError("C3_ISSUANCE_COMMAND_ID_DRIFT")
    return manifest


class C3ShadowProjectionOperatorAuthorityV1:
    """Issue or recover exactly one signed command for one projection revision."""

    def __init__(
        self,
        pg: PostgresClient | None = None,
        *,
        flags: ExecutionPlaneFlags | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._pg = pg or pg_client
        self._environ = os.environ if environ is None else environ
        self._flags = flags or ExecutionPlaneFlags.from_env(self._environ, strict=True)

    def _require_process_authority(self, *, new_issuance: bool) -> None:
        validate_execution_plane(self._flags)
        if self._flags.legacy_push_execution_enabled:
            raise C3ShadowProjectionNotReadyError("C3_LEGACY_EXECUTION_FORBIDDEN")
        if self._flags.mt5_order_send_enabled:
            raise C3ShadowProjectionNotReadyError("C3_ORDER_SEND_MUST_REMAIN_DISABLED")
        if self._flags.risk_reservation_enabled:
            raise C3ShadowProjectionNotReadyError("C3_REAL_RISK_RESERVATION_MUST_REMAIN_DISABLED")
        if self._flags.trade_outbox_write_enabled:
            raise C3ShadowProjectionNotReadyError("C3_TRADE_OUTBOX_MUST_REMAIN_DISABLED")
        if not new_issuance:
            return
        required = {
            "EXECUTION_ENABLED": self._flags.execution_enabled,
            "SIGNED_COMMAND_BRIDGE_ENABLED": self._flags.signed_command_bridge_enabled,
            "EXECUTION_COMMAND_PRODUCER_ENABLED": self._flags.execution_command_producer_enabled,
            "EA_COMMAND_DELIVERY_ENABLED": self._flags.ea_command_delivery_enabled,
        }
        missing = sorted(name for name, enabled in required.items() if not enabled)
        if missing:
            raise C3ShadowProjectionNotReadyError("C3_FLAGS_DISABLED:" + ",".join(missing))

    def _signing_material(self) -> tuple[str, str]:
        secret = str(self._environ.get("EXECUTOR_COMMAND_SIGNING_SECRET") or "").strip()
        key_id = str(self._environ.get("EXECUTOR_COMMAND_SIGNING_KEY_ID") or "").strip()
        if len(secret.encode("utf-8")) < 32 or not key_id:
            raise C3ShadowProjectionNotReadyError("C3_SIGNING_MATERIAL_UNAVAILABLE")
        return secret, key_id

    @staticmethod
    def _target_matches(request: C3ShadowProjectionCommandRequest, projection: C2ShadowRiskProjectionV1) -> bool:
        return (
            request.shadow_authority_id == projection.shadow_authority_id
            and request.source_candidate_id == projection.tradeplan_id
            and request.source_candidate_revision == projection.candidate_revision
            and request.executor_id == projection.executor_id
            and request.account_id == projection.account_id
            and request.broker_symbol == projection.broker_symbol
        )

    async def issue(
        self,
        request: C3ShadowProjectionCommandRequest,
    ) -> C3ShadowProjectionCommandManifest:
        """Atomically issue a new command or recover the exact prior request."""

        if not self._pg.is_available:
            raise C3ShadowProjectionNotReadyError("C3_POSTGRES_REQUIRED")
        self._require_process_authority(new_issuance=False)

        async with self._pg.transaction() as connection:
            projection_row = await connection.fetchrow(
                f"SELECT * FROM {PROJECTION_TABLE} WHERE shadow_authority_id=$1 FOR UPDATE",
                request.shadow_authority_id,
            )
            if projection_row is None:
                raise C3ShadowProjectionConflictError("C3_PROJECTION_NOT_FOUND")
            projection = _projection_from_row(projection_row)
            if not self._target_matches(request, projection):
                raise C3ShadowProjectionConflictError("C3_OPERATOR_TARGET_MISMATCH")

            candidate_row = await connection.fetchrow(
                """
                SELECT candidate.tradeplan_id,candidate.candidate_sequence,candidate.candidate_revision,
                       candidate.candidate_status,candidate.lifecycle_state,
                       candidate.material_candidate_hash,candidate.formation_evidence_hash,
                       EXISTS (
                           SELECT 1 FROM strategy_5scr_tradeplan_candidates_v2 successor
                           WHERE successor.previous_tradeplan_id=candidate.tradeplan_id
                       ) AS has_successor
                FROM strategy_5scr_tradeplan_candidates_v2 candidate
                WHERE candidate.tradeplan_id=$1
                FOR UPDATE
                """,
                projection.tradeplan_id,
            )
            executor_row = await connection.fetchrow(
                "SELECT * FROM executor_instances WHERE executor_id=$1::uuid FOR UPDATE",
                str(projection.executor_id),
            )
            governance_row = await connection.fetchrow(
                "SELECT * FROM executor_bridge_governance WHERE singleton_id=1 FOR UPDATE"
            )
            # Prevent a heartbeat from inserting a newer snapshot between the
            # latest-row lock and the command insert.  Lock order mirrors the
            # database trigger: projection, candidate, executor, governance,
            # then snapshot table/latest row.
            await connection.execute("LOCK TABLE executor_account_snapshots IN SHARE MODE")
            snapshot_row = await connection.fetchrow(
                """
                SELECT * FROM executor_account_snapshots
                WHERE executor_id=$1::uuid
                ORDER BY captured_at DESC
                LIMIT 1
                FOR UPDATE
                """,
                str(projection.executor_id),
            )
            if candidate_row is None or executor_row is None or governance_row is None or snapshot_row is None:
                raise C3ShadowProjectionNotReadyError("C3_LOCKED_AUTHORITY_INCOMPLETE")

            by_request = await connection.fetchrow(
                f"SELECT * FROM {ISSUANCE_TABLE} WHERE operator_run_id=$1 FOR UPDATE",
                request.operator_run_id,
            )
            if by_request is not None:
                manifest = _manifest_from_row(by_request)
                if (
                    manifest.source_shadow_authority_id != request.shadow_authority_id
                    or manifest.source_candidate_id != request.source_candidate_id
                    or manifest.source_candidate_revision != request.source_candidate_revision
                    or manifest.executor_id != request.executor_id
                    or manifest.account_id != request.account_id
                    or manifest.broker_symbol != request.broker_symbol
                ):
                    raise C3ShadowProjectionConflictError("C3_OPERATOR_RUN_ALREADY_BOUND")
                if projection.state.value != "COMMAND_ISSUED":
                    raise C3ShadowProjectionIntegrityError("C3_ISSUANCE_WITHOUT_CONSUMED_PROJECTION")
                return manifest

            by_projection = await connection.fetchrow(
                f"SELECT * FROM {ISSUANCE_TABLE} WHERE source_shadow_authority_id=$1 FOR UPDATE",
                projection.shadow_authority_id,
            )
            if by_projection is not None:
                raise C3ShadowProjectionConflictError("C3_PROJECTION_ALREADY_BOUND_TO_OTHER_REQUEST")
            if projection.state.value != "AVAILABLE":
                raise C3ShadowProjectionIntegrityError("C3_CONSUMED_PROJECTION_WITHOUT_ISSUANCE")

            self._require_process_authority(new_issuance=True)
            clock_row = await connection.fetchrow("SELECT clock_timestamp() AS now")
            if clock_row is None:
                raise C3ShadowProjectionNotReadyError("C3_DATABASE_CLOCK_UNAVAILABLE")
            issued_at = cast(datetime, clock_row["now"]).astimezone(UTC)
            if abs((issued_at - request.requested_at_utc).total_seconds()) > _REQUEST_CLOCK_SKEW_SECONDS:
                raise C3ShadowProjectionNotReadyError("C3_OPERATOR_REQUEST_STALE")
            if request.expires_at_utc <= issued_at:
                raise C3ShadowProjectionNotReadyError("C3_OPERATOR_REQUEST_EXPIRED")

            if (
                str(candidate_row["candidate_status"]) != "TRADEPLAN_CANDIDATE"
                or str(candidate_row["lifecycle_state"]) != "ACTIVE"
                or int(candidate_row["candidate_sequence"]) != projection.candidate_sequence
                or int(candidate_row["candidate_revision"]) != projection.candidate_revision
                or str(candidate_row["material_candidate_hash"]) != projection.material_candidate_hash
                or str(candidate_row["formation_evidence_hash"]) != projection.candidate_evidence_hash
                or bool(candidate_row["has_successor"])
            ):
                raise C3ShadowProjectionConflictError("C3_CANDIDATE_NOT_CURRENT")
            if (
                str(executor_row["account_id"]) != projection.account_id
                or str(executor_row["broker_server"]) != projection.broker_server
                or str(executor_row["execution_mode"]) != "SHADOW"
                or str(executor_row["status"]) != "ONLINE"
                or executor_row["revoked_at"] is not None
            ):
                raise C3ShadowProjectionNotReadyError("C3_EXECUTOR_NOT_CURRENT_SHADOW")
            if not bool(governance_row["kill_switch_active"]):
                raise C3ShadowProjectionNotReadyError("C3_KILL_SWITCH_DISENGAGED")
            if int(governance_row["governance_version"]) != request.expected_governance_version:
                raise C3ShadowProjectionConflictError("C3_GOVERNANCE_VERSION_STALE")

            snapshot = AccountSnapshotV1.model_validate(_mapping(snapshot_row["payload"]))
            if str(snapshot_row["snapshot_id"]) != projection.account_snapshot_id:
                raise C3ShadowProjectionConflictError("C3_PROJECTION_SNAPSHOT_NOT_LATEST")
            captured_at = cast(datetime, snapshot_row["captured_at"]).astimezone(UTC)
            age = (issued_at - captured_at).total_seconds()
            if age < -2 or age > _SNAPSHOT_MAX_AGE_SECONDS:
                raise C3ShadowProjectionNotReadyError("C3_ACCOUNT_SNAPSHOT_STALE")

            signing_secret, signing_key_id = self._signing_material()
            command: ExecutionCommandV1 = promote_shadow_projection_to_command(
                projection,
                request,
                snapshot,
                executor_login_hash=str(executor_row["login_hash"]),
                governance_version=int(governance_row["governance_version"]),
                issued_at_utc=issued_at,
                signing_secret=signing_secret,
                signing_key_id=signing_key_id,
            )
            command_payload = command.model_dump(mode="json")
            command_payload_hash = sha256_tag(command_payload)
            envelope = build_signed_execution_envelope(
                command,
                root_secret=signing_secret,
                key_id=signing_key_id,
            )

            transitioned = await connection.fetchrow(
                f"""
                UPDATE {PROJECTION_TABLE}
                SET state='COMMAND_ISSUED', state_version=state_version+1, updated_at=$2
                WHERE shadow_authority_id=$1 AND state='AVAILABLE' AND state_version=$3
                RETURNING state,state_version
                """,
                projection.shadow_authority_id,
                issued_at,
                projection.state_version,
            )
            if transitioned is None:
                raise C3ShadowProjectionConflictError("C3_PROJECTION_CONCURRENTLY_CONSUMED")

            inserted = await connection.fetchrow(
                """
                INSERT INTO execution_commands (
                    command_id,executor_id,account_id,source_event,source_signal_id,source_signal_hash,
                    operator_run_id,source_shadow_authority_id,source_candidate_id,
                    source_candidate_sequence,source_candidate_revision,source_account_snapshot_id,
                    execution_authority,capital_reserved,broker_side_effect_allowed,order_send_eligible,
                    idempotency_key,revision,action,payload,payload_hash,state,issued_at,not_before,expires_at,
                    wire_format,payload_encoding,signed_payload_b64,signed_payload_sha256,
                    signature_algorithm,signature_key_id,signature_value
                ) VALUES (
                    $1::uuid,$2::uuid,$3,'signal_json',$4,$5,$6,$7,$8,$9,$10,$11,
                    false,false,false,false,$12,$13,$14,$15::jsonb,$16,'QUEUED',$17,$18,$19,
                    $20,$21,$22,$23,$24,$25,$26
                )
                ON CONFLICT DO NOTHING
                RETURNING command_id
                """,
                str(command.command_id),
                str(command.executor_binding.executor_id),
                command.executor_binding.account_id,
                projection.shadow_authority_id,
                projection.authority_hash,
                request.operator_run_id,
                projection.shadow_authority_id,
                projection.tradeplan_id,
                projection.candidate_sequence,
                projection.candidate_revision,
                projection.account_snapshot_id,
                command.idempotency_key,
                command.revision,
                command.action.value,
                _json(command_payload),
                command_payload_hash,
                command.issued_at_utc,
                command.not_before_utc,
                command.expires_at_utc,
                envelope.wire_version,
                envelope.payload_encoding,
                envelope.payload_b64,
                envelope.payload_sha256,
                envelope.algorithm,
                envelope.key_id,
                envelope.signature,
            )
            if inserted is None:
                raise C3ShadowProjectionConflictError("C3_COMMAND_IDEMPOTENCY_CONFLICT")

            manifest = C3ShadowProjectionCommandManifest(
                operator_run_id=request.operator_run_id,
                source_shadow_authority_id=projection.shadow_authority_id,
                source_candidate_id=projection.tradeplan_id,
                source_candidate_sequence=projection.candidate_sequence,
                source_candidate_revision=projection.candidate_revision,
                executor_id=projection.executor_id,
                account_id=projection.account_id,
                canonical_symbol=projection.symbol,
                broker_symbol=projection.broker_symbol,
                account_snapshot_id=projection.account_snapshot_id,
                governance_version=int(governance_row["governance_version"]),
                command_id=command.command_id,
                issued_at_utc=command.issued_at_utc,
                command_expires_at_utc=command.expires_at_utc,
            )
            request_payload_hash = sha256_tag(request.model_dump(mode="json"))
            await connection.execute(
                f"""
                INSERT INTO {ISSUANCE_TABLE} (
                    command_id,operator_run_id,operator_authority,actor,reason,
                    source_shadow_authority_id,source_candidate_id,source_candidate_sequence,
                    source_candidate_revision,executor_id,account_id,account_snapshot_id,
                    governance_version,issued_at,command_expires_at,request_payload_hash,
                    command_payload_hash,manifest,execution_authority,capital_reserved,
                    broker_side_effect_allowed,order_send_eligible
                ) VALUES (
                    $1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10::uuid,$11,$12,$13,$14,$15,
                    $16,$17,$18::jsonb,false,false,false,false
                )
                """,
                str(command.command_id),
                request.operator_run_id,
                request.operator_authority,
                request.actor,
                request.reason,
                projection.shadow_authority_id,
                projection.tradeplan_id,
                projection.candidate_sequence,
                projection.candidate_revision,
                str(projection.executor_id),
                projection.account_id,
                projection.account_snapshot_id,
                int(governance_row["governance_version"]),
                command.issued_at_utc,
                command.expires_at_utc,
                request_payload_hash,
                command_payload_hash,
                _json(manifest.model_dump(mode="json")),
            )
            return manifest


__all__ = [
    "C3ShadowProjectionConflictError",
    "C3ShadowProjectionIntegrityError",
    "C3ShadowProjectionNotReadyError",
    "C3ShadowProjectionOperatorAuthorityV1",
    "C3ShadowProjectionWiringError",
]
