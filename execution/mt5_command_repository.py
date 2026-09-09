"""PostgreSQL ledger for MT5 executor commands, leases, and reports."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from contracts.mt5_execution_protocol import (
    SHADOW_ACCEPTANCE_EA_VERSION,
    SIGNED_WIRE_VERSION,
    AccountSnapshotV1,
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
                      AND c.conname = 'ck_execution_command_lineage_v1'
                      AND c.contype = 'c' AND c.convalidated
                      AND pg_get_constraintdef(c.oid) LIKE '%SHADOW_ACCEPTANCE%'
                      AND pg_get_constraintdef(c.oid) LIKE '%source_signal_id IS NULL%'
                      AND pg_get_constraintdef(c.oid) LIKE '%WOLF15_SHADOW_ACCEPTANCE_OPERATOR_V1%'
                ) AS lineage_constraint,
                EXISTS (
                    SELECT 1 FROM pg_constraint AS c
                    WHERE c.conrelid = 'public.execution_commands'::regclass
                      AND c.conname = 'ck_execution_command_payload_lineage_v1'
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
        await self.get_executor(executor_id)
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
                            execution_commands.source_event <> 'SHADOW_ACCEPTANCE'
                            OR g.kill_switch_active = true
                          )
                      AND (
                            e.execution_mode = 'SHADOW'
                            OR (e.execution_mode = 'DEMO' AND g.kill_switch_active = false)
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
            if str(command_row["execution_mode"]) == "SHADOW":
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
                SELECT payload_hash
                FROM execution_reports
                WHERE command_id = $1::uuid AND sequence = $2
                """,
                str(report.command_id),
                report.sequence,
            )
            if existing:
                if existing["payload_hash"] != report_hash:
                    raise CommandConflictError("report sequence already exists with a different payload")
                return {
                    "accepted": True,
                    "duplicate": True,
                    "command_id": str(report.command_id),
                    "sequence": report.sequence,
                    "command_state": current_state,
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
        return {
            "accepted": True,
            "duplicate": False,
            "command_id": str(report.command_id),
            "sequence": report.sequence,
            "command_state": target_state,
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
