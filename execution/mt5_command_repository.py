"""PostgreSQL ledger for MT5 executor commands, leases, and reports."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from contracts.mt5_execution_protocol import (
    ENGINEERING_DEMO_CANARY_EA_VERSION,
    SHADOW_ACCEPTANCE_EA_VERSION,
    SIGNED_WIRE_VERSION,
    AccountSnapshotV1,
    EngineeringDemoCanaryGuards,
    EngineeringDemoCanarySource,
    ExecutionCommandV1,
    ExecutionReportState,
    ExecutionReportV1,
    ExecutorHeartbeatV1,
    ExecutorMode,
    ExecutorRegistrationV1,
    ShadowAcceptanceGuards,
    ShadowAcceptanceSource,
    SignedExecutionEnvelopeV2,
    build_signed_execution_envelope,
    sha256_tag,
    verify_execution_command,
    verify_signed_execution_envelope_with_root,
)
from execution.mt5_executor_governance import (
    ExecutorGovernanceError,
    GovernanceSnapshot,
    MT5ExecutorGovernanceRepository,
    acquire_canary_lifecycle_advisory_locks,
    acquire_executor_advisory_locks,
)
from storage.postgres_client import PostgresClient, pg_client


class ExecutorRepositoryError(RuntimeError):
    pass


class ExecutorNotFoundError(ExecutorRepositoryError):
    pass


class ExecutorBindingMismatchError(ExecutorRepositoryError):
    pass


class CommandConflictError(ExecutorRepositoryError):
    pass


class CommandNotFoundError(ExecutorRepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class CommandDelivery:
    command: ExecutionCommandV1
    signed_envelope: SignedExecutionEnvelopeV2 | None


@dataclass(frozen=True, slots=True)
class CommandClaim:
    command: ExecutionCommandV1
    claim_token: str
    lease_expires_at: datetime
    signed_envelope: SignedExecutionEnvelopeV2 | None = None


_REPORT_TO_COMMAND_STATE: dict[ExecutionReportState, str] = {
    ExecutionReportState.RECEIVED: "CLAIMED",
    ExecutionReportState.CLAIMED: "CLAIMED",
    ExecutionReportState.VALIDATION_REJECTED: "REJECTED",
    ExecutionReportState.PREFLIGHT_REJECTED: "REJECTED",
    ExecutionReportState.SUBMITTING: "SUBMITTING",
    ExecutionReportState.BROKER_ACCEPTED: "BROKER_ACCEPTED",
    ExecutionReportState.PENDING_ACTIVE: "ACTIVE",
    ExecutionReportState.PARTIALLY_FILLED: "ACTIVE",
    ExecutionReportState.FILLED: "FILLED",
    ExecutionReportState.CANCELLED: "CANCELLED",
    ExecutionReportState.MODIFIED: "COMPLETED",
    ExecutionReportState.CLOSED_TP: "COMPLETED",
    ExecutionReportState.CLOSED_SL: "COMPLETED",
    ExecutionReportState.CLOSED_COMMAND: "COMPLETED",
    ExecutionReportState.EXPIRED: "EXPIRED",
    ExecutionReportState.BROKER_REJECTED: "REJECTED",
    ExecutionReportState.AMBIGUOUS_REQUIRES_RECONCILIATION: "AMBIGUOUS",
    ExecutionReportState.WOULD_EXECUTE: "SHADOW_COMPLETED",
    ExecutionReportState.WOULD_REJECT: "SHADOW_REJECTED",
}

_TERMINAL_COMMAND_STATES = {
    "REJECTED",
    "FILLED",
    "CANCELLED",
    "COMPLETED",
    "EXPIRED",
    "SHADOW_COMPLETED",
    "SHADOW_REJECTED",
}

_ALLOWED_COMMAND_TRANSITIONS: dict[str, frozenset[str]] = {
    "CLAIMED": frozenset({"CLAIMED", "SUBMITTING", "REJECTED", "SHADOW_COMPLETED", "SHADOW_REJECTED"}),
    "SUBMITTING": frozenset({"BROKER_ACCEPTED", "ACTIVE", "FILLED", "REJECTED", "AMBIGUOUS"}),
    "BROKER_ACCEPTED": frozenset({"ACTIVE", "FILLED", "REJECTED", "AMBIGUOUS"}),
    "ACTIVE": frozenset({"ACTIVE", "FILLED", "CANCELLED", "COMPLETED", "EXPIRED", "AMBIGUOUS"}),
    "AMBIGUOUS": frozenset({"ACTIVE", "FILLED", "REJECTED", "CANCELLED", "EXPIRED"}),
    "REJECTED": frozenset(),
    "FILLED": frozenset(),
    "CANCELLED": frozenset(),
    "COMPLETED": frozenset(),
    "EXPIRED": frozenset(),
    "SHADOW_COMPLETED": frozenset(),
    "SHADOW_REJECTED": frozenset(),
}


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _claim_token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_exact_report_decimal(
    actual: float | None,
    expected: float,
    *,
    field: str,
) -> None:
    if actual is None or Decimal(str(actual)) != Decimal(str(expected)):
        raise CommandConflictError(f"engineering canary report {field} differs from signed order")


def _validate_engineering_canary_report_evidence(
    report: ExecutionReportV1,
    command: ExecutionCommandV1,
) -> None:
    """Require state-specific broker truth before advancing a D0 ledger."""

    order = command.order
    if order is None:
        raise CommandConflictError("engineering canary order payload is missing")
    execution = report.execution
    broker = report.broker
    _require_exact_report_decimal(execution.requested_volume, order.volume, field="volume")
    _require_exact_report_decimal(execution.requested_price, order.entry_price, field="requested price")
    _require_exact_report_decimal(execution.stop_loss, order.stop_loss, field="stop loss")
    _require_exact_report_decimal(execution.take_profit, order.take_profit, field="take profit")

    has_ticket = any(value is not None for value in (broker.order_ticket, broker.deal_ticket, broker.position_id))
    filled_volume = Decimal(str(execution.filled_volume or 0))
    pre_submit_states = {
        ExecutionReportState.RECEIVED,
        ExecutionReportState.CLAIMED,
        ExecutionReportState.VALIDATION_REJECTED,
        ExecutionReportState.PREFLIGHT_REJECTED,
        ExecutionReportState.SUBMITTING,
    }
    if report.state in pre_submit_states:
        if has_ticket or filled_volume != 0 or execution.filled_price is not None:
            raise CommandConflictError("pre-submit canary report cannot claim a broker effect")
        return

    if report.state is ExecutionReportState.BROKER_REJECTED:
        if broker.retcode is None or broker.retcode <= 0:
            raise CommandConflictError("engineering canary broker rejection requires a retcode")
        if has_ticket or filled_volume != 0 or execution.filled_price is not None:
            raise CommandConflictError("rejected engineering canary cannot claim a broker effect")
        return

    if report.state is ExecutionReportState.BROKER_ACCEPTED:
        if broker.order_ticket is None or broker.retcode is None or broker.retcode <= 0:
            raise CommandConflictError(
                "engineering canary broker acceptance requires order ticket and retcode evidence"
            )
        if (
            broker.deal_ticket is not None
            or broker.position_id is not None
            or filled_volume != 0
            or execution.filled_price is not None
        ):
            raise CommandConflictError("broker-accepted engineering canary cannot claim a fill")
        return

    if report.state is ExecutionReportState.PENDING_ACTIVE:
        if broker.order_ticket is None and broker.position_id is None:
            raise CommandConflictError("active engineering canary requires an order or position ticket")
        if filled_volume != 0 or execution.filled_price is not None:
            raise CommandConflictError("pending engineering canary cannot claim an unproven fill")
        return

    if report.state is ExecutionReportState.PARTIALLY_FILLED:
        raise CommandConflictError("partial engineering canary fill requires reconciliation")

    if report.state is ExecutionReportState.FILLED:
        if (
            broker.order_ticket is None
            or broker.deal_ticket is None
            or broker.position_id is None
            or execution.filled_price is None
        ):
            raise CommandConflictError("filled engineering canary requires order, deal, position, and price evidence")
        if filled_volume != Decimal(str(order.volume)):
            raise CommandConflictError("filled engineering canary volume differs from signed order")
        return

    if report.state is ExecutionReportState.AMBIGUOUS_REQUIRES_RECONCILIATION:
        has_fill_volume = filled_volume != 0
        has_fill_price = execution.filled_price is not None
        if has_fill_volume != has_fill_price or (has_fill_volume and broker.deal_ticket is None):
            raise CommandConflictError("ambiguous canary fill evidence is incomplete")
        return

    if report.state is ExecutionReportState.EXPIRED:
        raise CommandConflictError("engineering canary expiry is server-authoritative")

    if report.state in {ExecutionReportState.CANCELLED, ExecutionReportState.MODIFIED}:
        if not has_ticket:
            raise CommandConflictError("terminal engineering canary report requires broker lineage")
        if filled_volume != 0 or execution.filled_price is not None:
            raise CommandConflictError("cancelled or modified canary cannot claim an unproven fill")
        return

    if report.state in {
        ExecutionReportState.CLOSED_TP,
        ExecutionReportState.CLOSED_SL,
        ExecutionReportState.CLOSED_COMMAND,
    } and (broker.deal_ticket is None or execution.filled_price is None or filled_volume <= 0):
        raise CommandConflictError("closed engineering canary requires deal and fill evidence")


def _command_signing_secrets() -> tuple[str, ...]:
    current = os.getenv("EXECUTOR_COMMAND_SIGNING_SECRET", "").strip()
    previous = os.getenv("EXECUTOR_COMMAND_SIGNING_SECRET_PREVIOUS", "").strip()
    return tuple(secret for secret in (current, previous) if len(secret.encode("utf-8")) >= 32)


def _stored_envelope(row: Any) -> SignedExecutionEnvelopeV2 | None:
    values = dict(row)
    wire_format = str(values.get("wire_format") or "legacy-json-v1")
    if wire_format == "legacy-json-v1":
        return None
    if wire_format != SIGNED_WIRE_VERSION:
        raise CommandConflictError(f"unsupported stored command wire format: {wire_format}")
    try:
        return SignedExecutionEnvelopeV2.model_validate(
            {
                "wire_version": wire_format,
                "payload_encoding": values.get("payload_encoding"),
                "payload_b64": values.get("signed_payload_b64"),
                "payload_sha256": values.get("signed_payload_sha256"),
                "algorithm": values.get("signature_algorithm"),
                "key_id": values.get("signature_key_id"),
                "executor_id": values.get("executor_id"),
                "signature": values.get("signature_value"),
            }
        )
    except ValueError as exc:
        raise CommandConflictError("stored signed command envelope is malformed") from exc


class MT5CommandRepository:
    def __init__(self, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client
        self._governance = MT5ExecutorGovernanceRepository(pg=self._pg)

    def _require_database(self) -> None:
        if not self._pg.is_available:
            raise ExecutorRepositoryError("PostgreSQL is required for the executor bridge")

    def _delivery_from_row(self, row: Any) -> CommandDelivery:
        values = dict(row)
        payload = values["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        command = cast(ExecutionCommandV1, ExecutionCommandV1.model_validate(payload))
        envelope = _stored_envelope(values)
        secrets_to_try = _command_signing_secrets()
        if envelope is None:
            if not any(verify_execution_command(command, secret=secret) for secret in secrets_to_try):
                raise CommandConflictError("stored legacy command signature is invalid")
            return CommandDelivery(command=command, signed_envelope=None)

        if str(values.get("payload_hash") or "") != envelope.payload_sha256:
            raise CommandConflictError("stored command payload hash does not match signed wire bytes")
        for secret in secrets_to_try:
            envelope_command = verify_signed_execution_envelope_with_root(envelope, root_secret=secret)
            if envelope_command is None or not verify_execution_command(envelope_command, secret=secret):
                continue
            if envelope_command.model_dump(mode="json") != command.model_dump(mode="json"):
                raise CommandConflictError("stored JSON command differs from signed wire bytes")
            return CommandDelivery(command=envelope_command, signed_envelope=envelope)
        raise CommandConflictError("stored signed command envelope is invalid")

    async def register_executor(self, request: ExecutorRegistrationV1) -> dict[str, Any]:
        """Register a pre-provisioned EDUMB agent; new registrations are shadow-only."""

        self._require_database()
        async with self._pg.transaction() as connection:
            agent = await connection.fetchrow(
                """
                SELECT id, ea_subtype::text AS ea_subtype, locked,
                       execution_mode::text AS execution_mode
                FROM ea_agents
                WHERE id = $1::uuid
                FOR UPDATE
                """,
                str(request.executor_id),
            )
            if not agent:
                raise ExecutorNotFoundError("executor must be pre-provisioned in Agent Manager")
            if str(agent["ea_subtype"]) != "EDUMB" or bool(agent["locked"]):
                raise ExecutorBindingMismatchError("executor must be an unlocked EDUMB agent")

            existing = await connection.fetchrow(
                """
                SELECT execution_mode
                FROM executor_instances
                WHERE executor_id = $1::uuid
                FOR UPDATE
                """,
                str(request.executor_id),
            )
            if existing and str(existing["execution_mode"]) != str(agent["execution_mode"]):
                raise ExecutorBindingMismatchError("executor mode drift detected during registration")
            if not existing:
                await connection.execute(
                    """
                    UPDATE ea_agents
                    SET execution_mode = 'SHADOW'::execution_mode_enum, updated_at = now()
                    WHERE id = $1::uuid
                    """,
                    str(request.executor_id),
                )
            row = await connection.fetchrow(
                """
                INSERT INTO executor_instances (
                    executor_id, account_id, login_hash, broker_server, terminal_build,
                    ea_version, protocol_version, execution_mode, status, last_heartbeat_at
                ) VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, 'SHADOW', 'REGISTERED', now())
                ON CONFLICT (executor_id) DO UPDATE SET
                    terminal_build = EXCLUDED.terminal_build,
                    ea_version = EXCLUDED.ea_version,
                    protocol_version = EXCLUDED.protocol_version,
                    updated_at = now()
                WHERE executor_instances.account_id = EXCLUDED.account_id
                  AND executor_instances.login_hash = EXCLUDED.login_hash
                  AND executor_instances.broker_server = EXCLUDED.broker_server
                  AND executor_instances.revoked_at IS NULL
                RETURNING *
                """,
                str(request.executor_id),
                request.account_id,
                request.login_hash,
                request.broker_server,
                request.terminal_build,
                request.ea_version,
                request.protocol_version,
            )
        if not row:
            raise ExecutorBindingMismatchError("existing executor binding does not match registration")
        try:
            governance = await self._governance.executor_snapshot(request.executor_id)
        except ExecutorGovernanceError as exc:
            raise ExecutorRepositoryError(str(exc)) from exc
        return {**dict(row), **governance.to_dict()}

    async def get_executor(self, executor_id: UUID | str) -> dict[str, Any]:
        self._require_database()
        row = await self._pg.fetchrow(
            "SELECT * FROM executor_instances WHERE executor_id = $1::uuid AND revoked_at IS NULL",
            str(executor_id),
        )
        if not row:
            raise ExecutorNotFoundError(f"executor {executor_id} is not registered")
        return dict(row)

    async def record_heartbeat(self, heartbeat: ExecutorHeartbeatV1) -> dict[str, Any]:
        executor = await self.get_executor(heartbeat.executor_id)
        snapshot = heartbeat.account_snapshot
        if snapshot.account_id != executor["account_id"]:
            raise ExecutorBindingMismatchError("heartbeat account does not match executor binding")

        status = "ONLINE" if heartbeat.terminal_connected else "DEGRADED"
        operations = [
            (
                """
                UPDATE executor_instances
                SET status = $2, last_heartbeat_at = $3, updated_at = now()
                WHERE executor_id = $1::uuid AND revoked_at IS NULL
                """,
                (str(heartbeat.executor_id), status, heartbeat.sent_at_utc),
            ),
            (
                """
                INSERT INTO executor_account_snapshots (
                    snapshot_id, executor_id, account_id, captured_at, balance, equity,
                    floating_pnl, used_margin, free_margin, margin_level_pct, margin_mode,
                    trade_allowed, autotrading_enabled, payload
                ) VALUES (
                    $1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::jsonb
                ) ON CONFLICT (snapshot_id) DO NOTHING
                """,
                (
                    snapshot.snapshot_id,
                    str(snapshot.executor_id),
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
                    _json(snapshot),
                ),
            ),
        ]
        await self._pg.execute_in_transaction(operations)
        if str(executor.get("execution_mode")) == ExecutorMode.DEMO.value:
            await self.expire_engineering_demo_canary_windows()
        try:
            governance = await self._governance.executor_snapshot(heartbeat.executor_id)
        except ExecutorGovernanceError as exc:
            raise ExecutorRepositoryError(str(exc)) from exc
        return {
            "executor_id": str(heartbeat.executor_id),
            "status": status,
            "snapshot_id": snapshot.snapshot_id,
            "server_time_utc": datetime.now(UTC).isoformat(),
            **governance.to_dict(),
        }

    async def governance_snapshot(self, executor_id: UUID | str) -> GovernanceSnapshot:
        try:
            return await self._governance.executor_snapshot(executor_id)
        except ExecutorGovernanceError as exc:
            raise ExecutorRepositoryError(str(exc)) from exc

    async def signed_wire_schema_status(self) -> dict[str, Any]:
        """Prove that PostgreSQL enforces the immutable signed-wire contract."""

        self._require_database()
        row = await self._pg.fetchrow(
            """
            SELECT
                EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'execution_commands'
                      AND column_name = 'wire_format'
                      AND data_type = 'character varying'
                      AND is_nullable = 'NO'
                      AND column_default LIKE '%wolf15.mt5.exec.signed-bytes.v2%'
                ) AS wire_format_column,
                (
                    SELECT count(*) = 6
                       AND bool_and(is_nullable = 'YES')
                       AND bool_and(
                           data_type = CASE column_name
                               WHEN 'signed_payload_b64' THEN 'text'
                               ELSE 'character varying'
                           END
                       )
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'execution_commands'
                      AND column_name IN (
                          'payload_encoding', 'signed_payload_b64',
                          'signed_payload_sha256', 'signature_algorithm',
                          'signature_key_id', 'signature_value'
                      )
                ) AS envelope_columns,
                EXISTS (
                    SELECT 1
                    FROM pg_constraint AS constraint_row
                    JOIN pg_class AS table_row ON table_row.oid = constraint_row.conrelid
                    JOIN pg_namespace AS namespace_row ON namespace_row.oid = table_row.relnamespace
                    WHERE namespace_row.nspname = 'public'
                      AND table_row.relname = 'execution_commands'
                      AND constraint_row.conname = 'ck_execution_command_signed_wire_complete'
                      AND constraint_row.contype = 'c'
                      AND constraint_row.convalidated
                      AND pg_get_constraintdef(constraint_row.oid) ~ 'signed_payload_sha256.*=.*payload_hash'
                      AND pg_get_constraintdef(constraint_row.oid) LIKE '%signature_value IS NOT NULL%'
                      AND pg_get_constraintdef(constraint_row.oid) LIKE '%signature_key_id IS NOT NULL%'
                      AND pg_get_constraintdef(constraint_row.oid) LIKE '%signed_payload_b64 IS NOT NULL%'
                      AND pg_get_constraintdef(constraint_row.oid) LIKE '%HMAC-SHA256%'
                      AND pg_get_constraintdef(constraint_row.oid) LIKE '%base64url%'
                ) AS signed_wire_constraint,
                EXISTS (
                    SELECT 1
                    FROM pg_trigger AS trigger_row
                    JOIN pg_class AS table_row ON table_row.oid = trigger_row.tgrelid
                    JOIN pg_namespace AS namespace_row ON namespace_row.oid = table_row.relnamespace
                    JOIN pg_proc AS function_row ON function_row.oid = trigger_row.tgfoid
                    WHERE namespace_row.nspname = 'public'
                      AND table_row.relname = 'execution_commands'
                      AND trigger_row.tgname = 'trg_execution_command_require_signed_wire'
                      AND trigger_row.tgenabled <> 'D'
                      AND NOT trigger_row.tgisinternal
                      AND function_row.proname = 'reject_new_legacy_execution_command'
                      AND pg_get_triggerdef(trigger_row.oid) LIKE '%BEFORE INSERT ON public.execution_commands%'
                      AND pg_get_functiondef(function_row.oid) LIKE '%new execution commands require signed wire v2%'
                      AND pg_get_functiondef(function_row.oid) LIKE '%legacy-json-v1%'
                ) AS legacy_insert_guard
            """
        )
        if not row:
            return {"ready": False, "reason": "signed-wire schema status query returned no row"}
        details = dict(row)
        return {"ready": all(bool(value) for value in details.values()), **details}

    async def shadow_acceptance_schema_status(self) -> dict[str, Any]:
        """Prove PostgreSQL owns the acceptance-lineage safety boundary."""

        self._require_database()
        row = await self._pg.fetchrow(
            """
            SELECT
                (
                    SELECT count(*) = 4
                       AND bool_and(is_nullable = CASE column_name
                           WHEN 'source_event' THEN 'NO' ELSE 'YES' END)
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'execution_commands'
                      AND column_name IN (
                          'source_event', 'acceptance_run_id',
                          'operator_authority', 'acceptance_purpose'
                      )
                ) AS lineage_columns,
                (
                    SELECT count(*) = 2 AND bool_and(is_nullable = 'YES')
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'execution_commands'
                      AND column_name IN ('source_signal_id', 'source_signal_hash')
                ) AS nullable_signal_lineage,
                EXISTS (
                    SELECT 1 FROM pg_constraint AS c
                    WHERE c.conrelid = 'public.execution_commands'::regclass
                      AND c.conname = 'ck_execution_command_lineage_v2'
                      AND c.contype = 'c' AND c.convalidated
                      AND pg_get_constraintdef(c.oid) LIKE '%SHADOW_ACCEPTANCE%'
                      AND pg_get_constraintdef(c.oid) LIKE '%source_signal_id IS NULL%'
                      AND pg_get_constraintdef(c.oid) LIKE '%WOLF15_SHADOW_ACCEPTANCE_OPERATOR_V1%'
                ) AS lineage_constraint,
                EXISTS (
                    SELECT 1 FROM pg_constraint AS c
                    WHERE c.conrelid = 'public.execution_commands'::regclass
                      AND c.conname = 'ck_execution_command_payload_lineage_v2'
                      AND c.contype = 'c' AND c.convalidated
                      AND pg_get_constraintdef(c.oid) LIKE '%RECONCILE_ONLY%'
                      AND pg_get_constraintdef(c.oid) LIKE '%NOT%risk_reservation_id%'
                      AND pg_get_constraintdef(c.oid) LIKE '%execution_authority%false%'
                      AND pg_get_constraintdef(c.oid) LIKE '%kill_switch_required%true%'
                      AND pg_get_constraintdef(c.oid) LIKE '%00:15:00%'
                      AND pg_get_constraintdef(c.oid) LIKE '%not_before%issued_at%'
                      AND pg_get_constraintdef(c.oid) LIKE '%broker_execution%'
                      AND pg_get_constraintdef(c.oid) LIKE '%FORBIDDEN%'
                ) AS payload_constraint,
                EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'execution_commands'
                      AND indexname = 'uq_execution_command_acceptance_symbol'
                      AND indexdef LIKE 'CREATE UNIQUE INDEX%'
                      AND indexdef LIKE '%acceptance_run_id%'
                      AND indexdef LIKE '%canonical_symbol%'
                      AND indexdef LIKE '%SHADOW_ACCEPTANCE%'
                ) AS acceptance_symbol_uniqueness
                ,
                EXISTS (
                    SELECT 1
                    FROM pg_trigger AS t
                    JOIN pg_class AS table_row ON table_row.oid = t.tgrelid
                    JOIN pg_namespace AS namespace_row ON namespace_row.oid = table_row.relnamespace
                    JOIN pg_proc AS function_row ON function_row.oid = t.tgfoid
                    WHERE namespace_row.nspname = 'public'
                      AND table_row.relname = 'execution_reports'
                      AND t.tgname = 'trg_shadow_acceptance_report_broker_forbidden_v1'
                      AND t.tgenabled <> 'D'
                      AND NOT t.tgisinternal
                      AND function_row.proname = 'reject_shadow_acceptance_report_broker_effects_v1'
                      AND pg_get_functiondef(function_row.oid) LIKE '%SHADOW_ACCEPTANCE%'
                      AND pg_get_functiondef(function_row.oid) LIKE '%WOULD_EXECUTE%'
                      AND pg_get_functiondef(function_row.oid) LIKE '%WOULD_REJECT%'
                      AND pg_get_functiondef(function_row.oid) LIKE '%filled_volume%'
                      AND pg_get_functiondef(function_row.oid) LIKE '%order_ticket%'
                      AND pg_get_functiondef(function_row.oid) LIKE '%deal_ticket%'
                      AND pg_get_functiondef(function_row.oid) LIKE '%position_id%'
                ) AS acceptance_report_broker_guard,
                EXISTS (
                    SELECT 1
                    FROM pg_trigger AS t
                    JOIN pg_class AS table_row ON table_row.oid = t.tgrelid
                    JOIN pg_namespace AS namespace_row ON namespace_row.oid = table_row.relnamespace
                    JOIN pg_proc AS function_row ON function_row.oid = t.tgfoid
                    WHERE namespace_row.nspname = 'public'
                      AND table_row.relname = 'broker_entities'
                      AND t.tgname = 'trg_shadow_acceptance_broker_entity_forbidden_v1'
                      AND t.tgenabled <> 'D'
                      AND NOT t.tgisinternal
                      AND function_row.proname = 'reject_shadow_acceptance_broker_entity_v1'
                      AND pg_get_functiondef(function_row.oid) LIKE '%SHADOW_ACCEPTANCE%'
                ) AS acceptance_broker_entity_guard
            """
        )
        if not row:
            return {"ready": False, "reason": "acceptance schema status query returned no row"}
        details = dict(row)
        return {"ready": all(bool(value) for value in details.values()), **details}

    async def engineering_demo_canary_schema_status(self) -> dict[str, Any]:
        """Prove PostgreSQL owns D0 lineage and its one-open-window boundary."""

        self._require_database()
        row = await self._pg.fetchrow(
            """
            SELECT
                (
                    SELECT count(*) = 3 AND bool_and(is_nullable = 'YES')
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'execution_commands'
                      AND column_name IN (
                          'engineering_canary_id',
                          'canary_operator_authority',
                          'canary_purpose'
                      )
                ) AS canary_lineage_columns,
                EXISTS (
                    SELECT 1 FROM pg_constraint AS c
                    WHERE c.conrelid = 'public.execution_commands'::regclass
                      AND c.conname = 'ck_execution_command_lineage_v2'
                      AND c.contype = 'c' AND c.convalidated
                      AND pg_get_constraintdef(c.oid) LIKE '%ENGINEERING_DEMO_CANARY%'
                      AND pg_get_constraintdef(c.oid) LIKE '%WOLF15_ENGINEERING_DEMO_OPERATOR_V1%'
                      AND pg_get_constraintdef(c.oid) LIKE '%EXECUTION_PLUMBING_VALIDATION%'
                ) AS canary_lineage_constraint,
                EXISTS (
                    SELECT 1 FROM pg_constraint AS c
                    WHERE c.conrelid = 'public.execution_commands'::regclass
                      AND c.conname = 'ck_execution_command_payload_lineage_v2'
                      AND c.contype = 'c' AND c.convalidated
                      AND pg_get_constraintdef(c.oid) LIKE '%ENGINEERING_DEMO_CANARY%'
                      AND pg_get_constraintdef(c.oid) LIKE '%DEMO_ONLY%'
                      AND pg_get_constraintdef(c.oid) LIKE '%max_submit_attempts%'
                      AND pg_get_constraintdef(c.oid) LIKE '%max_broker_effects%'
                      AND pg_get_constraintdef(c.oid) LIKE '%150016%'
                      AND pg_get_constraintdef(c.oid) LIKE '%GTC%'
                      AND pg_get_constraintdef(c.oid) LIKE '%00:02:00%'
                ) AS canary_payload_constraint,
                to_regclass('public.engineering_demo_canary_windows') IS NOT NULL
                    AS canary_window_table,
                EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'engineering_demo_canary_windows'
                      AND indexname = 'uq_engineering_demo_canary_single_open'
                      AND indexdef LIKE 'CREATE UNIQUE INDEX%'
                      AND indexdef LIKE '%QUEUED%'
                      AND indexdef LIKE '%ARMED%'
                      AND indexdef LIKE '%RECONCILIATION_REQUIRED%'
                ) AS one_open_window_index,
                EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'execution_commands'
                      AND indexname = 'uq_execution_command_engineering_canary'
                      AND indexdef LIKE 'CREATE UNIQUE INDEX%'
                      AND indexdef LIKE '%engineering_canary_id%'
                      AND indexdef LIKE '%ENGINEERING_DEMO_CANARY%'
                ) AS canary_command_uniqueness
            """
        )
        if not row:
            return {"ready": False, "reason": "engineering canary schema status query returned no row"}
        details = dict(row)
        return {"ready": all(bool(value) for value in details.values()), **details}

    async def latest_snapshot(self, executor_id: UUID | str) -> AccountSnapshotV1 | None:
        self._require_database()
        row = await self._pg.fetchrow(
            """
            SELECT payload
            FROM executor_account_snapshots
            WHERE executor_id = $1::uuid
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            str(executor_id),
        )
        if not row:
            return None
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return cast(AccountSnapshotV1, AccountSnapshotV1.model_validate(payload))

    async def enqueue_command(self, command: ExecutionCommandV1) -> ExecutionCommandV1:
        """Persist an already signed command with idempotency conflict detection."""

        self._require_database()
        if isinstance(command.source, ShadowAcceptanceSource):
            raise CommandConflictError("SHADOW_ACCEPTANCE must use the dedicated acceptance authority")
        if isinstance(command.source, EngineeringDemoCanarySource):
            raise CommandConflictError("ENGINEERING_DEMO_CANARY must use the dedicated canary authority")
        executor = await self.get_executor(command.executor_binding.executor_id)
        if executor["account_id"] != command.executor_binding.account_id:
            raise ExecutorBindingMismatchError("command account does not match executor binding")
        if str(executor["execution_mode"]) != command.executor_binding.execution_mode.value:
            raise ExecutorBindingMismatchError("command mode does not match governed executor mode")
        if command.executor_binding.execution_mode is ExecutorMode.LIVE:
            raise CommandConflictError("LIVE command delivery is blocked by the B2 rollout contract")
        governance = await self.governance_snapshot(command.executor_binding.executor_id)
        if command.executor_binding.execution_mode is not ExecutorMode.SHADOW and governance.kill_switch_active:
            raise CommandConflictError("global executor kill switch blocks non-SHADOW commands")
        if command.executor_binding.execution_mode is ExecutorMode.DEMO:
            raise CommandConflictError(
                "generic DEMO command delivery is blocked; use the dedicated engineering canary authority"
            )
        secret = os.getenv("EXECUTOR_COMMAND_SIGNING_SECRET", "").strip()
        if len(secret.encode("utf-8")) < 32 or not verify_execution_command(command, secret=secret):
            raise CommandConflictError("command signature is missing or invalid")
        payload = command.model_dump(mode="json")
        payload_hash = sha256_tag(payload)
        envelope_key_id = os.getenv("EXECUTOR_COMMAND_SIGNING_KEY_ID", "").strip() or command.signature.key_id
        envelope = build_signed_execution_envelope(
            command,
            root_secret=secret,
            key_id=envelope_key_id,
        )
        row = await self._pg.fetchrow(
            """
            INSERT INTO execution_commands (
                command_id, executor_id, account_id, source_event, source_signal_id, source_signal_hash,
                idempotency_key, revision, action, payload, payload_hash, state,
                issued_at, not_before, expires_at, wire_format, payload_encoding,
                signed_payload_b64, signed_payload_sha256, signature_algorithm,
                signature_key_id, signature_value
            ) VALUES (
                $1::uuid, $2::uuid, $3, 'signal_json', $4, $5, $6, $7, $8, $9::jsonb, $10,
                'QUEUED', $11, $12, $13, $14, $15, $16, $17, $18, $19, $20
            )
            ON CONFLICT (account_id, idempotency_key) DO NOTHING
            RETURNING payload
            """,
            str(command.command_id),
            str(command.executor_binding.executor_id),
            command.executor_binding.account_id,
            command.source.source_signal_id,
            command.source.source_signal_hash,
            command.idempotency_key,
            command.revision,
            command.action.value,
            _json(payload),
            payload_hash,
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
        if row:
            return command

        existing = await self._pg.fetchrow(
            """
            SELECT command_id, executor_id, payload, payload_hash, wire_format,
                   payload_encoding, signed_payload_b64, signed_payload_sha256,
                   signature_algorithm, signature_key_id, signature_value
            FROM execution_commands
            WHERE account_id = $1 AND idempotency_key = $2
            """,
            command.executor_binding.account_id,
            command.idempotency_key,
        )
        if not existing or existing["payload_hash"] != payload_hash:
            raise CommandConflictError("idempotency key already exists with a different payload")
        return self._delivery_from_row(existing).command

    async def enqueue_engineering_demo_canary_command(
        self,
        command: ExecutionCommandV1,
    ) -> ExecutionCommandV1:
        """Atomically queue one D0 command and its still-closed scoped window."""

        self._require_database()
        source = command.source
        guards = command.guards
        if not isinstance(source, EngineeringDemoCanarySource) or not isinstance(guards, EngineeringDemoCanaryGuards):
            raise CommandConflictError("engineering canary authority received a different command lineage")
        if command.executor_binding.execution_mode is not ExecutorMode.DEMO:
            raise CommandConflictError("engineering canary command is not DEMO")
        if command.action.value != "PLACE_MARKET" or command.order is None:
            raise CommandConflictError("engineering canary requires one market order")
        now = datetime.now(UTC)
        if command.expires_at_utc <= now or command.not_before_utc > now:
            raise CommandConflictError("engineering canary command is expired or not active")
        secret = os.getenv("EXECUTOR_COMMAND_SIGNING_SECRET", "").strip()
        if len(secret.encode("utf-8")) < 32 or not verify_execution_command(command, secret=secret):
            raise CommandConflictError("engineering canary signature is missing or invalid")
        payload = command.model_dump(mode="json")
        payload_hash = sha256_tag(payload)
        envelope_key_id = os.getenv("EXECUTOR_COMMAND_SIGNING_KEY_ID", "").strip() or command.signature.key_id
        envelope = build_signed_execution_envelope(command, root_secret=secret, key_id=envelope_key_id)

        async with self._pg.transaction() as connection:
            await acquire_canary_lifecycle_advisory_locks(
                connection,
                (command.executor_binding.executor_id,),
            )
            governed = await connection.fetchrow(
                """
                SELECT e.account_id, e.login_hash, e.broker_server, e.execution_mode,
                       e.ea_version, e.protocol_version, e.status, e.last_heartbeat_at,
                       e.revoked_at, g.kill_switch_active
                FROM executor_instances AS e
                CROSS JOIN executor_bridge_governance AS g
                WHERE e.executor_id = $1::uuid AND g.singleton_id = 1
                FOR UPDATE OF e, g
                """,
                str(command.executor_binding.executor_id),
            )
            if not governed or governed["revoked_at"] is not None:
                raise ExecutorNotFoundError("engineering canary executor is unavailable")
            if str(governed["execution_mode"]) != ExecutorMode.DEMO.value:
                raise CommandConflictError("engineering canary executor is not governed as DEMO")
            if str(governed["ea_version"]) != ENGINEERING_DEMO_CANARY_EA_VERSION:
                raise CommandConflictError("engineering canary executor runtime is incompatible")
            if str(governed["protocol_version"]) != "wolf15.mt5.exec.v1":
                raise CommandConflictError("engineering canary executor protocol is incompatible")
            if str(governed["status"]) != "ONLINE":
                raise CommandConflictError("engineering canary executor is not ONLINE")
            heartbeat = governed["last_heartbeat_at"]
            heartbeat_age = (
                (now - heartbeat.astimezone(UTC)).total_seconds() if isinstance(heartbeat, datetime) else None
            )
            if heartbeat_age is None or not -5 <= heartbeat_age <= 30:
                raise CommandConflictError("engineering canary executor heartbeat is stale")
            if not bool(governed["kill_switch_active"]):
                raise CommandConflictError("engineering canary must be queued with kill switch engaged")
            binding = command.executor_binding
            if (
                governed["account_id"] != binding.account_id
                or governed["login_hash"] != binding.login_hash
                or governed["broker_server"] != binding.broker_server
            ):
                raise ExecutorBindingMismatchError("engineering canary binding differs from governed executor")

            snapshot_row = await connection.fetchrow(
                """
                SELECT captured_at, payload
                FROM executor_account_snapshots
                WHERE snapshot_id = $1 AND executor_id = $2::uuid AND account_id = $3
                FOR SHARE
                """,
                guards.account_snapshot_id,
                str(binding.executor_id),
                binding.account_id,
            )
            if not snapshot_row:
                raise CommandConflictError("engineering canary account snapshot is missing")
            snapshot_age = (now - snapshot_row["captured_at"].astimezone(UTC)).total_seconds()
            if not -5 <= snapshot_age <= 30:
                raise CommandConflictError("engineering canary account snapshot is stale")
            snapshot_payload = snapshot_row["payload"]
            if isinstance(snapshot_payload, str):
                snapshot_payload = json.loads(snapshot_payload)
            try:
                snapshot = AccountSnapshotV1.model_validate(snapshot_payload)
            except ValueError as exc:
                raise CommandConflictError("engineering canary account snapshot is malformed") from exc
            if (
                snapshot.snapshot_id != guards.account_snapshot_id
                or snapshot.executor_id != binding.executor_id
                or snapshot.account_id != binding.account_id
                or snapshot.margin_mode != guards.expected_margin_mode
                or Decimal(str(snapshot.balance)) != Decimal(str(guards.balance_snapshot))
                or Decimal(str(snapshot.equity)) != Decimal(str(guards.equity_snapshot))
            ):
                raise CommandConflictError("engineering canary account snapshot has drifted")
            if not snapshot.trade_allowed or not snapshot.autotrading_enabled:
                raise CommandConflictError("engineering canary terminal trading is unavailable")
            if not snapshot.broker_ledger_reconciled:
                raise CommandConflictError("engineering canary broker ledger is not reconciled")
            if snapshot.open_positions or snapshot.pending_orders:
                raise CommandConflictError("engineering canary requires a flat account")
            symbol_capabilities = [
                item
                for item in snapshot.symbols
                if item.canonical_symbol == command.order.canonical_symbol
                and item.broker_symbol == command.order.broker_symbol
            ]
            if len(symbol_capabilities) != 1 or Decimal(str(command.order.volume)) != Decimal(
                str(symbol_capabilities[0].volume_min)
            ):
                raise CommandConflictError("engineering canary order is not bound to exact minimum symbol volume")

            outstanding = await connection.fetchval(
                """
                SELECT count(*)
                FROM execution_commands
                WHERE account_id = $1
                  AND state NOT IN (
                      'REJECTED','FILLED','CANCELLED','COMPLETED','EXPIRED',
                      'SHADOW_COMPLETED','SHADOW_REJECTED'
                  )
                """,
                binding.account_id,
            )
            if int(outstanding or 0) != 0:
                raise CommandConflictError("engineering canary requires zero nonterminal account commands")

            global_canary_outstanding = await connection.fetchval(
                """
                SELECT count(*)
                FROM execution_commands
                WHERE source_event = 'ENGINEERING_DEMO_CANARY'
                  AND state NOT IN (
                      'REJECTED','FILLED','CANCELLED','COMPLETED','EXPIRED',
                      'SHADOW_COMPLETED','SHADOW_REJECTED'
                  )
                """
            )
            if int(global_canary_outstanding or 0) != 0:
                raise CommandConflictError("another engineering canary effect is still unresolved")

            inserted = await connection.fetchrow(
                """
                INSERT INTO execution_commands (
                    command_id, executor_id, account_id, source_event,
                    source_signal_id, source_signal_hash, acceptance_run_id,
                    operator_authority, acceptance_purpose, engineering_canary_id,
                    canary_operator_authority, canary_purpose, idempotency_key,
                    revision, action, payload, payload_hash, state, issued_at,
                    not_before, expires_at, wire_format, payload_encoding,
                    signed_payload_b64, signed_payload_sha256, signature_algorithm,
                    signature_key_id, signature_value
                ) VALUES (
                    $1::uuid, $2::uuid, $3, 'ENGINEERING_DEMO_CANARY',
                    NULL, NULL, NULL, NULL, NULL, $4, $5, $6, $7, $8, $9,
                    $10::jsonb, $11, 'QUEUED', $12, $13, $14, $15, $16,
                    $17, $18, $19, $20, $21
                )
                ON CONFLICT DO NOTHING
                RETURNING command_id
                """,
                str(command.command_id),
                str(binding.executor_id),
                binding.account_id,
                source.canary_id,
                source.operator_authority,
                source.purpose,
                command.idempotency_key,
                command.revision,
                command.action.value,
                _json(payload),
                payload_hash,
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
            if not inserted:
                raise CommandConflictError("engineering canary identity or idempotency key already exists")
            await connection.execute(
                """
                INSERT INTO engineering_demo_canary_windows (
                    canary_id, command_id, executor_id, account_id,
                    broker_server, canonical_symbol, broker_symbol,
                    state, max_broker_effects, expires_at
                ) VALUES ($1, $2::uuid, $3::uuid, $4, $5, $6, $7, 'QUEUED', 1, $8)
                """,
                source.canary_id,
                str(command.command_id),
                str(binding.executor_id),
                binding.account_id,
                binding.broker_server,
                source.approved_canonical_symbol,
                source.approved_broker_symbol,
                command.expires_at_utc,
            )
        return command

    async def arm_engineering_demo_canary(
        self,
        canary_id: str,
        *,
        actor: str,
        reason: str,
        expected_governance_version: int | None = None,
    ) -> dict[str, Any]:
        """Atomically open exactly one scoped D0 window and disengage delivery."""

        self._require_database()
        actor = actor.strip()
        reason = reason.strip()
        if not actor or not reason:
            raise CommandConflictError("canary actor and reason must not be blank")
        now = datetime.now(UTC)
        async with self._pg.transaction() as connection:
            executor_row = await connection.fetchrow(
                "SELECT executor_id FROM engineering_demo_canary_windows WHERE canary_id=$1",
                canary_id,
            )
            if not executor_row:
                raise CommandConflictError("engineering canary window does not exist")
            await acquire_canary_lifecycle_advisory_locks(
                connection,
                (executor_row["executor_id"],),
            )
            row = await connection.fetchrow(
                """
                SELECT w.canary_id, w.command_id, w.executor_id, w.account_id,
                       w.broker_server, w.canonical_symbol, w.broker_symbol,
                       w.state AS window_state, w.expires_at AS window_expires_at,
                       c.state AS command_state, c.payload,
                       e.account_id AS executor_account_id,
                       e.login_hash AS executor_login_hash,
                       e.broker_server AS executor_broker_server,
                       e.execution_mode, e.ea_version, e.protocol_version,
                       e.status AS executor_status,
                       e.last_heartbeat_at, e.revoked_at,
                       g.kill_switch_active, g.kill_switch_reason,
                       g.governance_version
                FROM engineering_demo_canary_windows AS w
                JOIN execution_commands AS c ON c.command_id = w.command_id
                JOIN executor_instances AS e ON e.executor_id = w.executor_id
                CROSS JOIN executor_bridge_governance AS g
                WHERE w.canary_id = $1 AND g.singleton_id = 1
                FOR UPDATE OF w, c, e, g
                """,
                canary_id,
            )
            if not row:
                raise CommandConflictError("engineering canary window does not exist")
            if row["window_state"] != "QUEUED" or row["command_state"] != "QUEUED":
                raise CommandConflictError("engineering canary is not in a queueable state")
            if row["window_expires_at"] <= now:
                raise CommandConflictError("engineering canary window has expired")
            if row["revoked_at"] is not None or str(row["executor_status"]) != "ONLINE":
                raise CommandConflictError("engineering canary executor is unavailable")
            if str(row["execution_mode"]) != ExecutorMode.DEMO.value:
                raise CommandConflictError("engineering canary executor is not DEMO")
            if str(row["ea_version"]) != ENGINEERING_DEMO_CANARY_EA_VERSION:
                raise CommandConflictError("engineering canary executor runtime is incompatible")
            if str(row["protocol_version"]) != "wolf15.mt5.exec.v1":
                raise CommandConflictError("engineering canary executor protocol is incompatible")
            heartbeat = row["last_heartbeat_at"]
            heartbeat_age = (
                (now - heartbeat.astimezone(UTC)).total_seconds() if isinstance(heartbeat, datetime) else None
            )
            if heartbeat_age is None or not -5 <= heartbeat_age <= 30:
                raise CommandConflictError("engineering canary executor heartbeat is stale")
            if not bool(row["kill_switch_active"]):
                raise CommandConflictError("global kill switch must be engaged before arming a canary")
            governance_version = int(row["governance_version"])
            if expected_governance_version is not None and governance_version != expected_governance_version:
                raise CommandConflictError(
                    f"stale governance version: expected {expected_governance_version}, current {governance_version}"
                )
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            try:
                command = ExecutionCommandV1.model_validate(payload)
            except ValueError as exc:
                raise CommandConflictError("engineering canary command payload is malformed") from exc
            signing_secrets = _command_signing_secrets()
            if not signing_secrets or not any(
                verify_execution_command(command, secret=secret) for secret in signing_secrets
            ):
                raise CommandConflictError("engineering canary stored signature is invalid")
            source = command.source
            guards = command.guards
            if not isinstance(source, EngineeringDemoCanarySource) or not isinstance(
                guards, EngineeringDemoCanaryGuards
            ):
                raise CommandConflictError("engineering canary window lineage is invalid")
            if (
                source.canary_id != canary_id
                or str(source.approved_executor_id) != str(row["executor_id"])
                or source.approved_account_id != row["account_id"]
                or source.approved_broker_server != row["broker_server"]
                or source.approved_canonical_symbol != row["canonical_symbol"]
                or source.approved_broker_symbol != row["broker_symbol"]
            ):
                raise CommandConflictError("engineering canary window scope differs from signed command")
            binding = command.executor_binding
            if (
                str(binding.executor_id) != str(row["executor_id"])
                or binding.account_id != row["executor_account_id"]
                or binding.login_hash != row["executor_login_hash"]
                or binding.broker_server != row["executor_broker_server"]
                or command.expires_at_utc <= now
                or command.order is None
            ):
                raise CommandConflictError("engineering canary signed runtime binding has drifted")
            snapshot_row = await connection.fetchrow(
                """
                SELECT captured_at, payload
                FROM executor_account_snapshots
                WHERE snapshot_id=$1 AND executor_id=$2::uuid AND account_id=$3
                FOR SHARE
                """,
                guards.account_snapshot_id,
                str(row["executor_id"]),
                row["account_id"],
            )
            if not snapshot_row:
                raise CommandConflictError("engineering canary approved snapshot is missing")
            snapshot_age = (now - snapshot_row["captured_at"].astimezone(UTC)).total_seconds()
            snapshot_payload = snapshot_row["payload"]
            if isinstance(snapshot_payload, str):
                snapshot_payload = json.loads(snapshot_payload)
            try:
                snapshot = AccountSnapshotV1.model_validate(snapshot_payload)
            except ValueError as exc:
                raise CommandConflictError("engineering canary approved snapshot is malformed") from exc
            if not -5 <= snapshot_age <= 30:
                raise CommandConflictError("engineering canary approved snapshot is stale")
            if (
                snapshot.snapshot_id != guards.account_snapshot_id
                or snapshot.executor_id != binding.executor_id
                or snapshot.account_id != binding.account_id
                or snapshot.margin_mode != guards.expected_margin_mode
                or Decimal(str(snapshot.balance)) != Decimal(str(guards.balance_snapshot))
                or Decimal(str(snapshot.equity)) != Decimal(str(guards.equity_snapshot))
            ):
                raise CommandConflictError("engineering canary approved snapshot has drifted")
            if (
                not snapshot.trade_allowed
                or not snapshot.autotrading_enabled
                or not snapshot.broker_ledger_reconciled
                or snapshot.open_positions
                or snapshot.pending_orders
            ):
                raise CommandConflictError("engineering canary account is no longer reconciled and flat")
            symbol_capabilities = [
                item
                for item in snapshot.symbols
                if item.canonical_symbol == command.order.canonical_symbol
                and item.broker_symbol == command.order.broker_symbol
            ]
            if len(symbol_capabilities) != 1 or Decimal(str(command.order.volume)) != Decimal(
                str(symbol_capabilities[0].volume_min)
            ):
                raise CommandConflictError("engineering canary approved symbol capability has drifted")
            nonterminal = await connection.fetch(
                """
                SELECT command_id
                FROM execution_commands
                WHERE account_id=$1
                  AND state NOT IN (
                      'REJECTED','FILLED','CANCELLED','COMPLETED','EXPIRED',
                      'SHADOW_COMPLETED','SHADOW_REJECTED'
                  )
                FOR SHARE
                """,
                row["account_id"],
            )
            if {str(item["command_id"]) for item in nonterminal} != {str(row["command_id"])}:
                raise CommandConflictError("engineering canary is not the only nonterminal account command")

            global_canaries = await connection.fetch(
                """
                SELECT command_id
                FROM execution_commands
                WHERE source_event = 'ENGINEERING_DEMO_CANARY'
                  AND state NOT IN (
                      'REJECTED','FILLED','CANCELLED','COMPLETED','EXPIRED',
                      'SHADOW_COMPLETED','SHADOW_REJECTED'
                  )
                FOR SHARE
                """
            )
            if {str(item["command_id"]) for item in global_canaries} != {str(row["command_id"])}:
                raise CommandConflictError("another engineering canary effect is still unresolved")

            await connection.execute(
                """
                UPDATE engineering_demo_canary_windows
                SET state='ARMED', armed_at=$2, updated_at=$2
                WHERE canary_id=$1
                """,
                canary_id,
                now,
            )
            updated_governance = await connection.fetchrow(
                """
                UPDATE executor_bridge_governance
                SET kill_switch_active=false,
                    kill_switch_reason=$1,
                    governance_version=governance_version+1,
                    updated_by=$2,
                    updated_at=$3
                WHERE singleton_id=1
                RETURNING governance_version
                """,
                f"ENGINEERING_DEMO_CANARY:{canary_id}",
                actor,
                now,
            )
            await connection.execute(
                """
                INSERT INTO executor_governance_audit (
                    executor_id, action, actor, reason, previous_state, new_state
                ) VALUES ($1::uuid, 'ENGINEERING_DEMO_CANARY_ARMED', $2, $3, $4::jsonb, $5::jsonb)
                """,
                str(row["executor_id"]),
                actor,
                reason,
                _json(
                    {
                        "kill_switch_active": True,
                        "kill_switch_reason": str(row["kill_switch_reason"]),
                        "governance_version": governance_version,
                        "window_state": "QUEUED",
                    }
                ),
                _json(
                    {
                        "kill_switch_active": False,
                        "kill_switch_reason": f"ENGINEERING_DEMO_CANARY:{canary_id}",
                        "governance_version": int(updated_governance["governance_version"]),
                        "window_state": "ARMED",
                        "command_id": str(row["command_id"]),
                        "max_broker_effects": 1,
                    }
                ),
            )
        return {
            "canary_id": canary_id,
            "command_id": str(row["command_id"]),
            "executor_id": str(row["executor_id"]),
            "account_id": str(row["account_id"]),
            "broker_server": str(row["broker_server"]),
            "canonical_symbol": str(row["canonical_symbol"]),
            "broker_symbol": str(row["broker_symbol"]),
            "window_state": "ARMED",
            "max_broker_effects": 1,
            "governance_version": int(updated_governance["governance_version"]),
        }

    async def expire_engineering_demo_canary_windows(self) -> int:
        """Close expired D0 scope and restore the global fail-closed default."""

        self._require_database()
        now = datetime.now(UTC)
        async with self._pg.transaction() as connection:
            await acquire_canary_lifecycle_advisory_locks(connection)
            executor_rows = await connection.fetch(
                """
                SELECT DISTINCT executor_id
                FROM engineering_demo_canary_windows
                WHERE state IN ('QUEUED','ARMED') AND expires_at <= $1
                ORDER BY executor_id
                """,
                now,
            )
            await acquire_executor_advisory_locks(
                connection,
                (executor_row["executor_id"] for executor_row in executor_rows),
            )
            rows = await connection.fetch(
                """
                SELECT w.canary_id, w.command_id, w.executor_id,
                       w.state AS window_state, c.state AS command_state
                FROM engineering_demo_canary_windows AS w
                JOIN execution_commands AS c ON c.command_id = w.command_id
                WHERE w.state IN ('QUEUED','ARMED')
                  AND w.expires_at <= $1
                FOR UPDATE OF w, c
                """,
                now,
            )
            if not rows:
                return 0
            inconsistent = [
                row for row in rows if str(row["window_state"]) == "QUEUED" and str(row["command_state"]) != "QUEUED"
            ]
            if inconsistent:
                raise CommandConflictError("queued engineering canary window has an in-flight command")

            queued_rows = [row for row in rows if str(row["command_state"]) == "QUEUED"]
            inflight_rows = [row for row in rows if str(row["command_state"]) != "QUEUED"]
            if queued_rows:
                queued_canary_ids = [str(row["canary_id"]) for row in queued_rows]
                queued_command_ids = [UUID(str(row["command_id"])) for row in queued_rows]
                await connection.execute(
                    """
                    UPDATE engineering_demo_canary_windows
                    SET state='EXPIRED', terminal_at=$2, updated_at=$2
                    WHERE canary_id=ANY($1::text[])
                    """,
                    queued_canary_ids,
                    now,
                )
                await connection.execute(
                    """
                    UPDATE execution_commands
                    SET state='EXPIRED', terminal_at=$2, updated_at=$2
                    WHERE command_id=ANY($1::uuid[]) AND state='QUEUED'
                    """,
                    queued_command_ids,
                    now,
                )
            if inflight_rows:
                inflight_canary_ids = [str(row["canary_id"]) for row in inflight_rows]
                await connection.execute(
                    """
                    UPDATE engineering_demo_canary_windows
                    SET state='RECONCILIATION_REQUIRED', terminal_at=NULL, updated_at=$2
                    WHERE canary_id=ANY($1::text[]) AND state='ARMED'
                    """,
                    inflight_canary_ids,
                    now,
                )
            governance = await connection.fetchrow(
                """
                SELECT kill_switch_active, kill_switch_reason, governance_version
                FROM executor_bridge_governance
                WHERE singleton_id=1
                FOR UPDATE
                """
            )
            if governance and not bool(governance["kill_switch_active"]):
                updated = await connection.fetchrow(
                    """
                    UPDATE executor_bridge_governance
                    SET kill_switch_active=true,
                        kill_switch_reason='ENGINEERING_DEMO_CANARY_WINDOW_EXPIRED',
                        governance_version=governance_version+1,
                        updated_by='SYSTEM:D0_CANARY', updated_at=$1
                    WHERE singleton_id=1
                    RETURNING governance_version
                    """,
                    now,
                )
                await connection.execute(
                    """
                    INSERT INTO executor_governance_audit (
                        executor_id, action, actor, reason, previous_state, new_state
                    ) VALUES (
                        $1::uuid, 'ENGINEERING_DEMO_CANARY_AUTO_REENGAGED',
                        'SYSTEM:D0_CANARY', 'scoped canary window expired',
                        $2::jsonb, $3::jsonb
                    )
                    """,
                    str(rows[0]["executor_id"]),
                    _json(
                        {
                            "kill_switch_active": False,
                            "kill_switch_reason": str(governance["kill_switch_reason"]),
                            "governance_version": int(governance["governance_version"]),
                        }
                    ),
                    _json(
                        {
                            "kill_switch_active": True,
                            "kill_switch_reason": "ENGINEERING_DEMO_CANARY_WINDOW_EXPIRED",
                            "governance_version": int(updated["governance_version"]),
                            "expired_canary_ids": [str(row["canary_id"]) for row in queued_rows],
                            "reconciliation_required_canary_ids": [str(row["canary_id"]) for row in inflight_rows],
                        }
                    ),
                )
        return len(rows)

    async def enqueue_shadow_acceptance_commands(
        self,
        commands: tuple[ExecutionCommandV1, ...],
    ) -> tuple[ExecutionCommandV1, ...]:
        """Atomically persist one bounded, signed SHADOW acceptance run."""

        self._require_database()
        if not 1 <= len(commands) <= 30:
            raise CommandConflictError("acceptance run must contain between 1 and 30 commands")
        now = datetime.now(UTC)
        first = commands[0]
        if not isinstance(first.source, ShadowAcceptanceSource):
            raise CommandConflictError("acceptance authority received a production command")
        executor_id = first.executor_binding.executor_id
        account_id = first.executor_binding.account_id
        run_id = first.source.acceptance_run_id
        phase = first.source.phase
        expected_count = 1 if phase == "A1" else 30
        if len(commands) != expected_count:
            raise CommandConflictError(f"acceptance phase {phase} requires {expected_count} commands")
        first_guards = cast(ShadowAcceptanceGuards, first.guards)
        snapshot_id = first_guards.account_snapshot_id
        secret = os.getenv("EXECUTOR_COMMAND_SIGNING_SECRET", "").strip()
        if len(secret.encode("utf-8")) < 32:
            raise CommandConflictError("command signing secret is unavailable")
        envelope_key_id = os.getenv("EXECUTOR_COMMAND_SIGNING_KEY_ID", "").strip()
        prepared: list[tuple[ExecutionCommandV1, dict[str, Any], str, SignedExecutionEnvelopeV2]] = []
        seen_symbols: set[str] = set()
        for command in commands:
            source = command.source
            if not isinstance(source, ShadowAcceptanceSource):
                raise CommandConflictError("acceptance run contains a production command")
            if (
                command.executor_binding.executor_id != executor_id
                or command.executor_binding.account_id != account_id
                or source.acceptance_run_id != run_id
                or source.phase != phase
            ):
                raise CommandConflictError("acceptance run identities are inconsistent")
            guards = cast(ShadowAcceptanceGuards, command.guards)
            if guards.account_snapshot_id != snapshot_id:
                raise CommandConflictError("acceptance run spans multiple account snapshots")
            if command.executor_binding.execution_mode is not ExecutorMode.SHADOW:
                raise CommandConflictError("acceptance command is not SHADOW")
            if command.expires_at_utc <= now or command.not_before_utc > now:
                raise CommandConflictError("acceptance command is expired or not active")
            if source.canonical_symbol in seen_symbols:
                raise CommandConflictError("acceptance run repeats a canonical symbol")
            if phase == "A1" and source.canonical_symbol != "EURUSD":
                raise CommandConflictError("acceptance A1 is restricted to EURUSD")
            seen_symbols.add(source.canonical_symbol)
            if not verify_execution_command(command, secret=secret):
                raise CommandConflictError("acceptance command signature is invalid")
            payload = command.model_dump(mode="json")
            envelope = build_signed_execution_envelope(
                command,
                root_secret=secret,
                key_id=envelope_key_id or command.signature.key_id,
            )
            prepared.append((command, payload, sha256_tag(payload), envelope))

        async with self._pg.transaction() as connection:
            governed = await connection.fetchrow(
                """
                SELECT e.account_id, e.login_hash, e.broker_server, e.execution_mode,
                       e.ea_version, e.protocol_version, e.last_heartbeat_at,
                       e.revoked_at, g.kill_switch_active
                FROM executor_instances AS e
                CROSS JOIN executor_bridge_governance AS g
                WHERE e.executor_id = $1::uuid AND g.singleton_id = 1
                FOR UPDATE OF e, g
                """,
                str(executor_id),
            )
            if not governed or governed["revoked_at"] is not None:
                raise ExecutorNotFoundError("acceptance executor is unavailable")
            if str(governed["execution_mode"]) != ExecutorMode.SHADOW.value:
                raise CommandConflictError("acceptance executor is not governed as SHADOW")
            if (
                governed["ea_version"] != SHADOW_ACCEPTANCE_EA_VERSION
                or governed["protocol_version"] != "wolf15.mt5.exec.v1"
            ):
                raise CommandConflictError("acceptance executor runtime is incompatible")
            heartbeat = governed["last_heartbeat_at"]
            heartbeat_age = (
                (now - heartbeat.astimezone(UTC)).total_seconds() if isinstance(heartbeat, datetime) else None
            )
            if heartbeat_age is None or not -5 <= heartbeat_age <= 30:
                raise CommandConflictError("acceptance executor heartbeat is stale")
            if not bool(governed["kill_switch_active"]):
                raise CommandConflictError("acceptance requires the global kill switch to remain engaged")
            binding = first.executor_binding
            if (
                governed["account_id"] != binding.account_id
                or governed["login_hash"] != binding.login_hash
                or governed["broker_server"] != binding.broker_server
            ):
                raise ExecutorBindingMismatchError("acceptance binding does not match the governed executor")

            snapshot_row = await connection.fetchrow(
                """
                SELECT captured_at, balance, equity, margin_mode, payload
                FROM executor_account_snapshots
                WHERE snapshot_id = $1 AND executor_id = $2::uuid AND account_id = $3
                """,
                snapshot_id,
                str(executor_id),
                account_id,
            )
            if not snapshot_row:
                raise CommandConflictError("acceptance account snapshot is missing")
            snapshot_age = (now - snapshot_row["captured_at"].astimezone(UTC)).total_seconds()
            if (
                not -5 <= snapshot_age <= 30
                or float(snapshot_row["balance"]) != first_guards.balance_snapshot
                or float(snapshot_row["equity"]) != first_guards.equity_snapshot
                or str(snapshot_row["margin_mode"]) != first_guards.expected_margin_mode.value
            ):
                raise CommandConflictError("acceptance account snapshot has drifted")
            snapshot_payload = snapshot_row["payload"]
            if isinstance(snapshot_payload, str):
                snapshot_payload = json.loads(snapshot_payload)
            if not isinstance(snapshot_payload, dict):
                raise CommandConflictError("acceptance account snapshot payload is malformed")
            snapshot_pairs = tuple(
                (str(item.get("canonical_symbol")), str(item.get("broker_symbol")))
                for item in snapshot_payload.get("symbols", [])
                if isinstance(item, dict)
            )
            open_positions = snapshot_payload.get("open_positions")
            if not isinstance(open_positions, list) or open_positions:
                raise CommandConflictError("acceptance requires a zero-position account snapshot")
            command_pairs = tuple(
                (source.canonical_symbol, source.broker_symbol)
                for command, _payload, _payload_hash, _envelope in prepared
                if isinstance((source := command.source), ShadowAcceptanceSource)
            )
            if (
                len(snapshot_pairs) != 30
                or len(set(snapshot_pairs)) != 30
                or len({canonical for canonical, _broker in snapshot_pairs}) != 30
                or len({broker for _canonical, broker in snapshot_pairs}) != 30
            ):
                raise ExecutorBindingMismatchError("acceptance snapshot is not a unique 30-symbol universe")
            if phase == "A1":
                expected_pairs = tuple(pair for pair in snapshot_pairs if pair[0] == "EURUSD")
                if command_pairs != expected_pairs:
                    raise ExecutorBindingMismatchError("acceptance A1 symbol differs from the bound snapshot")
            elif command_pairs != snapshot_pairs:
                raise ExecutorBindingMismatchError("acceptance A2 symbols differ from the bound snapshot")

            for command, payload, payload_hash, envelope in prepared:
                source = cast(ShadowAcceptanceSource, command.source)
                guards = cast(ShadowAcceptanceGuards, command.guards)
                if (
                    float(snapshot_row["balance"]) != guards.balance_snapshot
                    or float(snapshot_row["equity"]) != guards.equity_snapshot
                    or str(snapshot_row["margin_mode"]) != guards.expected_margin_mode.value
                ):
                    raise CommandConflictError("acceptance account snapshot has drifted")

                inserted = await connection.fetchrow(
                    """
                    INSERT INTO execution_commands (
                        command_id, executor_id, account_id, source_event,
                        source_signal_id, source_signal_hash, acceptance_run_id,
                        operator_authority, acceptance_purpose, idempotency_key,
                        revision, action, payload, payload_hash, state, issued_at,
                        not_before, expires_at, wire_format, payload_encoding,
                        signed_payload_b64, signed_payload_sha256, signature_algorithm,
                        signature_key_id, signature_value
                    ) VALUES (
                        $1::uuid, $2::uuid, $3, 'SHADOW_ACCEPTANCE', NULL, NULL,
                        $4, $5, $6, $7, $8, $9, $10::jsonb, $11, 'QUEUED',
                        $12, $13, $14, $15, $16, $17, $18, $19, $20, $21
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING command_id
                    """,
                    str(command.command_id),
                    str(executor_id),
                    account_id,
                    source.acceptance_run_id,
                    source.operator_authority,
                    source.purpose,
                    command.idempotency_key,
                    command.revision,
                    command.action.value,
                    _json(payload),
                    payload_hash,
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
                if inserted:
                    continue
                existing = await connection.fetchrow(
                    """
                    SELECT payload_hash FROM execution_commands
                    WHERE account_id = $1 AND idempotency_key = $2
                    """,
                    account_id,
                    command.idempotency_key,
                )
                if not existing or existing["payload_hash"] != payload_hash:
                    raise CommandConflictError("acceptance command conflicts with existing lineage")
        return commands

    async def next_command(self, executor_id: UUID | str) -> CommandDelivery | None:
        executor = await self.get_executor(executor_id)
        if str(executor["execution_mode"]) == ExecutorMode.DEMO.value:
            await self.expire_engineering_demo_canary_windows()
        governance = await self.governance_snapshot(executor_id)
        if governance.execution_mode == ExecutorMode.LIVE.value:
            return None
        if governance.execution_mode != ExecutorMode.SHADOW.value and governance.kill_switch_active:
            return None
        await self._pg.execute(
            """
            UPDATE execution_commands
            SET state = 'EXPIRED', terminal_at = now(), updated_at = now()
            WHERE executor_id = $1::uuid
              AND state IN ('QUEUED', 'CLAIMED')
              AND expires_at <= now()
            """,
            str(executor_id),
        )
        row = await self._pg.fetchrow(
            """
            SELECT command_id, executor_id, payload, payload_hash, wire_format,
                   payload_encoding, signed_payload_b64, signed_payload_sha256,
                   signature_algorithm, signature_key_id, signature_value
            FROM execution_commands
            WHERE executor_id = $1::uuid
              AND account_id = $2
              AND payload #>> '{executor_binding,execution_mode}' = $3
              AND (source_event <> 'SHADOW_ACCEPTANCE' OR $4::boolean)
              AND (
                    $3 = 'SHADOW'
                    OR (
                        $3 = 'DEMO'
                        AND source_event = 'ENGINEERING_DEMO_CANARY'
                        AND EXISTS (
                            SELECT 1
                            FROM engineering_demo_canary_windows AS w
                            WHERE w.command_id = execution_commands.command_id
                              AND w.executor_id = execution_commands.executor_id
                              AND w.account_id = execution_commands.account_id
                              AND w.state = 'ARMED'
                              AND w.expires_at > now()
                        )
                    )
                  )
              AND not_before <= now()
              AND expires_at > now()
              AND (
                    state = 'QUEUED'
                    OR (state = 'CLAIMED' AND lease_expires_at < now())
                  )
            ORDER BY issued_at, command_id
            LIMIT 1
            """,
            str(executor_id),
            executor["account_id"],
            str(executor["execution_mode"]),
            governance.kill_switch_active,
        )
        if not row:
            return None
        return self._delivery_from_row(row)

    async def claim_command(
        self,
        *,
        executor_id: UUID | str,
        command_id: UUID | str,
        lease_seconds: int = 30,
    ) -> CommandClaim:
        executor = await self.get_executor(executor_id)
        if str(executor["execution_mode"]) == ExecutorMode.DEMO.value:
            await self.expire_engineering_demo_canary_windows()
        lease_seconds = max(10, min(int(lease_seconds), 120))
        raw_token = secrets.token_urlsafe(32)
        token_hash = _claim_token_hash(raw_token)
        lease_expires = datetime.now(UTC) + timedelta(seconds=lease_seconds)
        row = await self._pg.fetchrow(
            """
            UPDATE execution_commands
            SET state = 'CLAIMED', claim_token_hash = $3, claimed_by = $1::uuid,
                claimed_at = now(), lease_expires_at = $4, updated_at = now()
            WHERE command_id = $2::uuid
              AND executor_id = $1::uuid
              AND expires_at > now()
              AND EXISTS (
                    SELECT 1
                    FROM executor_instances AS e
                    JOIN executor_bridge_governance AS g ON g.singleton_id = 1
                    WHERE e.executor_id = $1::uuid
                      AND e.revoked_at IS NULL
                      AND execution_commands.payload #>> '{executor_binding,execution_mode}' = e.execution_mode
                      AND (
                            (
                                e.execution_mode = 'SHADOW'
                                AND (
                                    execution_commands.source_event <> 'SHADOW_ACCEPTANCE'
                                    OR g.kill_switch_active = true
                                )
                            )
                            OR (
                                e.execution_mode = 'DEMO'
                                AND g.kill_switch_active = false
                                AND execution_commands.source_event = 'ENGINEERING_DEMO_CANARY'
                                AND EXISTS (
                                    SELECT 1
                                    FROM engineering_demo_canary_windows AS w
                                    WHERE w.command_id = execution_commands.command_id
                                      AND w.executor_id = e.executor_id
                                      AND w.account_id = execution_commands.account_id
                                      AND w.state = 'ARMED'
                                      AND w.expires_at > now()
                                )
                            )
                          )
                  )
              AND (
                    state = 'QUEUED'
                    OR (state = 'CLAIMED' AND lease_expires_at < now())
                  )
            RETURNING command_id, executor_id, payload, payload_hash, wire_format,
                      payload_encoding, signed_payload_b64, signed_payload_sha256,
                      signature_algorithm, signature_key_id, signature_value
            """,
            str(executor_id),
            str(command_id),
            token_hash,
            lease_expires,
        )
        if not row:
            raise CommandConflictError("command is unavailable, expired, terminal, or leased")
        delivery = self._delivery_from_row(row)
        return CommandClaim(
            command=delivery.command,
            claim_token=raw_token,
            lease_expires_at=lease_expires,
            signed_envelope=delivery.signed_envelope,
        )

    async def command_status(
        self,
        *,
        executor_id: UUID | str,
        command_id: UUID | str,
    ) -> dict[str, Any]:
        """Return read-only reconciliation state without exposing a claim token."""

        await self.get_executor(executor_id)
        row = await self._pg.fetchrow(
            """
            SELECT c.command_id, c.state, c.payload_hash, c.signed_payload_sha256,
                   c.wire_format, c.last_report_sequence, c.terminal_at,
                   r.report_id, r.sequence AS report_sequence,
                   r.state AS report_state, r.payload_hash AS report_payload_hash,
                   r.payload #>> '{request_hash}' AS report_request_hash
            FROM execution_commands AS c
            LEFT JOIN LATERAL (
                SELECT report_id, sequence, state, payload_hash, payload
                FROM execution_reports
                WHERE command_id = c.command_id
                ORDER BY sequence DESC
                LIMIT 1
            ) AS r ON true
            WHERE c.command_id = $1::uuid
              AND c.executor_id = $2::uuid
            """,
            str(command_id),
            str(executor_id),
        )
        if not row:
            raise CommandNotFoundError("command is not available to this executor")
        latest_report = None
        if row["report_id"] is not None:
            latest_report = {
                "report_id": str(row["report_id"]),
                "sequence": int(row["report_sequence"]),
                "state": str(row["report_state"]),
                "payload_hash": str(row["report_payload_hash"]),
                "request_hash": str(row["report_request_hash"]),
            }
        state = str(row["state"])
        return {
            "command_id": str(row["command_id"]),
            "command_state": state,
            "terminal": state in _TERMINAL_COMMAND_STATES,
            "request_hash": str(row["signed_payload_sha256"] or row["payload_hash"]),
            "wire_format": str(row["wire_format"]),
            "last_report_sequence": int(row["last_report_sequence"]),
            "terminal_at_utc": row["terminal_at"].isoformat() if row["terminal_at"] else None,
            "latest_report": latest_report,
            "server_time_utc": datetime.now(UTC).isoformat(),
        }

    async def append_report(self, report: ExecutionReportV1, *, claim_token: str) -> dict[str, Any]:
        await self.get_executor(report.executor_id)
        report_payload = report.model_dump(mode="json")
        report_hash = sha256_tag(report_payload)
        target_state = _REPORT_TO_COMMAND_STATE[report.state]
        async with self._pg.transaction() as connection:
            scope_row = await connection.fetchrow(
                "SELECT executor_id, source_event FROM execution_commands WHERE command_id=$1::uuid",
                str(report.command_id),
            )
            if not scope_row:
                raise CommandConflictError("report references an unknown command")
            if str(scope_row["executor_id"]) != str(report.executor_id):
                raise ExecutorBindingMismatchError("report binding does not match command")
            if str(scope_row["source_event"]) == "ENGINEERING_DEMO_CANARY":
                await acquire_canary_lifecycle_advisory_locks(connection, (scope_row["executor_id"],))
            else:
                await acquire_executor_advisory_locks(connection, (scope_row["executor_id"],))
            command_row = await connection.fetchrow(
                """
                SELECT c.payload, c.account_id, c.executor_id, c.idempotency_key,
                       c.claim_token_hash, c.last_report_sequence, c.state,
                       c.source_event, e.execution_mode, g.kill_switch_active
                FROM execution_commands AS c
                JOIN executor_instances AS e ON e.executor_id = c.executor_id
                CROSS JOIN executor_bridge_governance AS g
                WHERE c.command_id = $1::uuid AND e.revoked_at IS NULL
                  AND g.singleton_id = 1
                FOR UPDATE OF c
                """,
                str(report.command_id),
            )
            if not command_row:
                raise CommandConflictError("report references an unknown or revoked command")
            if (
                str(command_row["executor_id"]) != str(report.executor_id)
                or command_row["account_id"] != report.account_id
            ):
                raise ExecutorBindingMismatchError("report binding does not match command")
            if command_row["idempotency_key"] != report.idempotency_key:
                raise CommandConflictError("report idempotency key does not match command")
            is_engineering_canary = str(command_row["source_event"]) == "ENGINEERING_DEMO_CANARY"
            if str(command_row["execution_mode"]) == "SHADOW" and not is_engineering_canary:
                if not bool(command_row["kill_switch_active"]):
                    raise CommandConflictError("SHADOW report requires the kill switch to remain engaged")
                broker = report.broker
                execution = report.execution
                if report.state not in {
                    ExecutionReportState.WOULD_EXECUTE,
                    ExecutionReportState.WOULD_REJECT,
                }:
                    raise CommandConflictError("SHADOW report must be WOULD_EXECUTE or WOULD_REJECT")
                if (
                    broker.order_ticket is not None
                    or broker.deal_ticket is not None
                    or broker.position_id is not None
                    or execution.filled_volume not in {None, 0}
                ):
                    raise CommandConflictError("SHADOW report must prove zero broker effects")
            expected_claim_hash = str(command_row["claim_token_hash"] or "")
            if not expected_claim_hash or not hmac_compare(expected_claim_hash, _claim_token_hash(claim_token)):
                raise ExecutorBindingMismatchError("invalid or missing command claim token")

            command_payload = command_row["payload"]
            if isinstance(command_payload, str):
                command_payload = json.loads(command_payload)
            if report.request_hash != sha256_tag(command_payload):
                raise CommandConflictError("report request_hash does not match command payload")
            current_state = str(command_row["state"])
            existing = await connection.fetchrow(
                """
                SELECT report_id, state, payload_hash
                FROM execution_reports
                WHERE command_id = $1::uuid AND sequence = $2
                """,
                str(report.command_id),
                report.sequence,
            )
            if existing and existing["payload_hash"] != report_hash:
                raise CommandConflictError("report sequence already exists with a different payload")

            if existing and not (
                is_engineering_canary
                and report.state is ExecutionReportState.SUBMITTING
                and current_state == "SUBMITTING"
            ):
                acknowledged_state = _REPORT_TO_COMMAND_STATE[ExecutionReportState(str(existing["state"]))]
                return {
                    "accepted": True,
                    "duplicate": True,
                    "command_id": str(report.command_id),
                    "report_id": str(existing["report_id"]),
                    "sequence": report.sequence,
                    "report_state": str(existing["state"]),
                    "ack_command_state": acknowledged_state,
                    "current_command_state": current_state,
                    "command_state": current_state,
                    "request_hash": report.request_hash,
                    "server_time_utc": datetime.now(UTC).isoformat(),
                }

            canary_command: ExecutionCommandV1 | None = None
            if is_engineering_canary:
                try:
                    canary_command = ExecutionCommandV1.model_validate(command_payload)
                except ValueError as exc:
                    raise CommandConflictError("engineering canary command payload is malformed") from exc
                if not isinstance(canary_command.source, EngineeringDemoCanarySource):
                    raise CommandConflictError("engineering canary report lineage is invalid")
                if report.state in {
                    ExecutionReportState.WOULD_EXECUTE,
                    ExecutionReportState.WOULD_REJECT,
                }:
                    raise CommandConflictError("engineering canary must report actual DEMO execution state")
                _validate_engineering_canary_report_evidence(report, canary_command)
                canary_window = await connection.fetchrow(
                    """
                    SELECT state, expires_at
                    FROM engineering_demo_canary_windows
                    WHERE command_id=$1::uuid
                    FOR UPDATE
                    """,
                    str(report.command_id),
                )
                if not canary_window:
                    raise CommandConflictError("engineering canary window is missing")
                window_state = str(canary_window["state"])
                if report.state is ExecutionReportState.SUBMITTING:
                    if bool(command_row["kill_switch_active"]):
                        raise CommandConflictError("engineering canary submit is blocked by the kill switch")
                    if window_state != "ARMED" or canary_window["expires_at"] <= datetime.now(UTC):
                        raise CommandConflictError("engineering canary submit window is not armed and current")
                elif not existing and window_state not in {"ARMED", "RECONCILIATION_REQUIRED"}:
                    raise CommandConflictError("engineering canary report window is no longer active")
                if report.broker.order_ticket is not None:
                    existing_order_tickets = await connection.fetch(
                        """
                        SELECT broker_ticket
                        FROM broker_entities
                        WHERE command_id=$1::uuid AND entity_type='ORDER'
                        FOR SHARE
                        """,
                        str(report.command_id),
                    )
                    existing_values = {int(item["broker_ticket"]) for item in existing_order_tickets}
                    if existing_values and report.broker.order_ticket not in existing_values:
                        raise CommandConflictError("engineering canary attempted a second broker order")

            if existing:
                acknowledged_state = _REPORT_TO_COMMAND_STATE[ExecutionReportState(str(existing["state"]))]
                return {
                    "accepted": True,
                    "duplicate": True,
                    "command_id": str(report.command_id),
                    "report_id": str(existing["report_id"]),
                    "sequence": report.sequence,
                    "report_state": str(existing["state"]),
                    "ack_command_state": acknowledged_state,
                    "current_command_state": current_state,
                    "command_state": current_state,
                    "request_hash": report.request_hash,
                    "server_time_utc": datetime.now(UTC).isoformat(),
                }
            expected_sequence = int(command_row["last_report_sequence"]) + 1
            if report.sequence != expected_sequence:
                raise CommandConflictError(
                    f"report sequence must be contiguous; expected {expected_sequence}, got {report.sequence}"
                )
            allowed_targets = _ALLOWED_COMMAND_TRANSITIONS.get(current_state, frozenset())
            if target_state not in allowed_targets:
                raise CommandConflictError(f"invalid command state transition {current_state} -> {target_state}")

            inserted = await connection.fetchrow(
                """
                INSERT INTO execution_reports (
                    report_id, command_id, executor_id, sequence, state, payload, payload_hash, event_time
                ) VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6::jsonb, $7, $8)
                ON CONFLICT DO NOTHING
                RETURNING report_id
                """,
                str(report.report_id),
                str(report.command_id),
                str(report.executor_id),
                report.sequence,
                report.state.value,
                _json(report_payload),
                report_hash,
                report.event_time_utc,
            )
            if not inserted:
                raise CommandConflictError("report id or sequence conflicts with an existing report")

            if is_engineering_canary and canary_command is not None and canary_command.order is not None:
                broker_entities = (
                    ("ORDER", report.broker.order_ticket),
                    ("DEAL", report.broker.deal_ticket),
                    ("POSITION", report.broker.position_id),
                )
                for entity_type, broker_ticket in broker_entities:
                    if broker_ticket is None:
                        continue
                    await connection.execute(
                        """
                        INSERT INTO broker_entities (
                            command_id, entity_type, broker_ticket, symbol, payload
                        ) VALUES ($1::uuid, $2, $3, $4, $5::jsonb)
                        ON CONFLICT (command_id, entity_type, broker_ticket)
                        DO UPDATE SET payload=EXCLUDED.payload, last_seen_at=now()
                        """,
                        str(report.command_id),
                        entity_type,
                        broker_ticket,
                        canary_command.order.broker_symbol,
                        _json(report_payload),
                    )

            terminal_at = datetime.now(UTC) if target_state in _TERMINAL_COMMAND_STATES else None
            await connection.execute(
                """
                UPDATE execution_commands
                SET state = $2, last_report_sequence = $3,
                    terminal_at = COALESCE($4, terminal_at), updated_at = now()
                WHERE command_id = $1::uuid
                """,
                str(report.command_id),
                target_state,
                report.sequence,
                terminal_at,
            )
            if is_engineering_canary and target_state in {
                "BROKER_ACCEPTED",
                "ACTIVE",
                "FILLED",
                "REJECTED",
                "AMBIGUOUS",
                "CANCELLED",
                "COMPLETED",
                "EXPIRED",
            }:
                window_state = (
                    "RECONCILIATION_REQUIRED"
                    if target_state in {"BROKER_ACCEPTED", "ACTIVE", "AMBIGUOUS"}
                    else "CLOSED"
                )
                window_terminal_at = None if window_state == "RECONCILIATION_REQUIRED" else datetime.now(UTC)
                await connection.execute(
                    """
                    UPDATE engineering_demo_canary_windows
                    SET state=$2, terminal_at=$3, updated_at=now()
                    WHERE command_id=$1::uuid
                      AND state IN ('ARMED','RECONCILIATION_REQUIRED')
                    """,
                    str(report.command_id),
                    window_state,
                    window_terminal_at,
                )
                governance_row = await connection.fetchrow(
                    """
                    SELECT kill_switch_active, kill_switch_reason, governance_version
                    FROM executor_bridge_governance
                    WHERE singleton_id=1
                    FOR UPDATE
                    """
                )
                if governance_row and not bool(governance_row["kill_switch_active"]):
                    updated_governance = await connection.fetchrow(
                        """
                        UPDATE executor_bridge_governance
                        SET kill_switch_active=true,
                            kill_switch_reason='ENGINEERING_DEMO_CANARY_AUTO_REENGAGED',
                            governance_version=governance_version+1,
                            updated_by='SYSTEM:D0_CANARY', updated_at=now()
                        WHERE singleton_id=1
                        RETURNING governance_version
                        """
                    )
                    await connection.execute(
                        """
                        INSERT INTO executor_governance_audit (
                            executor_id, action, actor, reason, previous_state, new_state
                        ) VALUES (
                            $1::uuid, 'ENGINEERING_DEMO_CANARY_AUTO_REENGAGED',
                            'SYSTEM:D0_CANARY', $2, $3::jsonb, $4::jsonb
                        )
                        """,
                        str(report.executor_id),
                        f"canary broker outcome {target_state}",
                        _json(
                            {
                                "kill_switch_active": False,
                                "kill_switch_reason": str(governance_row["kill_switch_reason"]),
                                "governance_version": int(governance_row["governance_version"]),
                            }
                        ),
                        _json(
                            {
                                "kill_switch_active": True,
                                "kill_switch_reason": "ENGINEERING_DEMO_CANARY_AUTO_REENGAGED",
                                "governance_version": int(updated_governance["governance_version"]),
                                "window_state": window_state,
                                "command_id": str(report.command_id),
                            }
                        ),
                    )
        return {
            "accepted": True,
            "duplicate": False,
            "command_id": str(report.command_id),
            "report_id": str(report.report_id),
            "sequence": report.sequence,
            "report_state": report.state.value,
            "ack_command_state": target_state,
            "current_command_state": target_state,
            "command_state": target_state,
            "request_hash": report.request_hash,
            "server_time_utc": datetime.now(UTC).isoformat(),
        }


def hmac_compare(left: str, right: str) -> bool:
    return secrets.compare_digest(left, right)


_repository = MT5CommandRepository()


def get_mt5_command_repository() -> MT5CommandRepository:
    return _repository


__all__ = [
    "ExecutorRepositoryError",
    "ExecutorNotFoundError",
    "ExecutorBindingMismatchError",
    "CommandConflictError",
    "CommandNotFoundError",
    "CommandDelivery",
    "CommandClaim",
    "MT5CommandRepository",
    "get_mt5_command_repository",
]
