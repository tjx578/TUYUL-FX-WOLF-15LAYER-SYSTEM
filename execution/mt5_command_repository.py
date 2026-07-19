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
    AccountSnapshotV1,
    ExecutionCommandV1,
    ExecutionReportState,
    ExecutionReportV1,
    ExecutorHeartbeatV1,
    ExecutorRegistrationV1,
    sha256_tag,
    verify_execution_command,
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


@dataclass(frozen=True, slots=True)
class CommandClaim:
    command: ExecutionCommandV1
    claim_token: str
    lease_expires_at: datetime


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


class MT5CommandRepository:
    def __init__(self, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client

    def _require_database(self) -> None:
        if not self._pg.is_available:
            raise ExecutorRepositoryError("PostgreSQL is required for the executor bridge")

    async def register_executor(self, request: ExecutorRegistrationV1) -> dict[str, Any]:
        """Register a pre-provisioned EDUMB agent; new registrations are shadow-only."""

        self._require_database()
        agent = await self._pg.fetchrow(
            """
            SELECT id, ea_subtype::text AS ea_subtype, locked
            FROM ea_agents
            WHERE id = $1::uuid
            """,
            str(request.executor_id),
        )
        if not agent:
            raise ExecutorNotFoundError("executor must be pre-provisioned in Agent Manager")
        if str(agent["ea_subtype"]) != "EDUMB" or bool(agent["locked"]):
            raise ExecutorBindingMismatchError("executor must be an unlocked EDUMB agent")

        row = await self._pg.fetchrow(
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
        return dict(row)

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
        return {
            "executor_id": str(heartbeat.executor_id),
            "status": status,
            "snapshot_id": snapshot.snapshot_id,
            "execution_mode": str(executor["execution_mode"]),
            "server_time_utc": datetime.now(UTC).isoformat(),
        }

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
        executor = await self.get_executor(command.executor_binding.executor_id)
        if executor["account_id"] != command.executor_binding.account_id:
            raise ExecutorBindingMismatchError("command account does not match executor binding")
        if str(executor["execution_mode"]) != command.executor_binding.execution_mode.value:
            raise ExecutorBindingMismatchError("command mode does not match governed executor mode")
        secret = os.getenv("EXECUTOR_COMMAND_SIGNING_SECRET", "").strip()
        if len(secret.encode("utf-8")) < 32 or not verify_execution_command(command, secret=secret):
            raise CommandConflictError("command signature is missing or invalid")
        payload = command.model_dump(mode="json")
        payload_hash = sha256_tag(payload)
        row = await self._pg.fetchrow(
            """
            INSERT INTO execution_commands (
                command_id, executor_id, account_id, source_signal_id, source_signal_hash,
                idempotency_key, revision, action, payload, payload_hash, state,
                issued_at, not_before, expires_at
            ) VALUES (
                $1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9::jsonb, $10,
                'QUEUED', $11, $12, $13
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
        )
        if row:
            return command

        existing = await self._pg.fetchrow(
            "SELECT payload, payload_hash FROM execution_commands WHERE account_id = $1 AND idempotency_key = $2",
            command.executor_binding.account_id,
            command.idempotency_key,
        )
        if not existing or existing["payload_hash"] != payload_hash:
            raise CommandConflictError("idempotency key already exists with a different payload")
        existing_payload = existing["payload"]
        if isinstance(existing_payload, str):
            existing_payload = json.loads(existing_payload)
        return cast(ExecutionCommandV1, ExecutionCommandV1.model_validate(existing_payload))

    async def next_command(self, executor_id: UUID | str) -> ExecutionCommandV1 | None:
        executor = await self.get_executor(executor_id)
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
            SELECT payload
            FROM execution_commands
            WHERE executor_id = $1::uuid
              AND account_id = $2
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
        )
        if not row:
            return None
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        command = cast(ExecutionCommandV1, ExecutionCommandV1.model_validate(payload))
        current_secret = os.getenv("EXECUTOR_COMMAND_SIGNING_SECRET", "").strip()
        previous_secret = os.getenv("EXECUTOR_COMMAND_SIGNING_SECRET_PREVIOUS", "").strip()
        valid_signature = any(
            len(secret.encode("utf-8")) >= 32 and verify_execution_command(command, secret=secret)
            for secret in (current_secret, previous_secret)
            if secret
        )
        if not valid_signature:
            raise CommandConflictError("stored command signature is invalid")
        return command

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
                    FROM executor_instances
                    WHERE executor_id = $1::uuid AND revoked_at IS NULL
                  )
              AND (
                    state = 'QUEUED'
                    OR (state = 'CLAIMED' AND lease_expires_at < now())
                  )
            RETURNING payload
            """,
            str(executor_id),
            str(command_id),
            token_hash,
            lease_expires,
        )
        if not row:
            raise CommandConflictError("command is unavailable, expired, terminal, or leased")
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return CommandClaim(
            command=ExecutionCommandV1.model_validate(payload),
            claim_token=raw_token,
            lease_expires_at=lease_expires,
        )

    async def append_report(self, report: ExecutionReportV1, *, claim_token: str) -> dict[str, Any]:
        await self.get_executor(report.executor_id)
        report_payload = report.model_dump(mode="json")
        report_hash = sha256_tag(report_payload)
        target_state = _REPORT_TO_COMMAND_STATE[report.state]
        async with self._pg.transaction() as connection:
            command_row = await connection.fetchrow(
                """
                SELECT c.payload, c.account_id, c.executor_id, c.idempotency_key,
                       c.claim_token_hash, c.last_report_sequence, c.state
                FROM execution_commands AS c
                JOIN executor_instances AS e ON e.executor_id = c.executor_id
                WHERE c.command_id = $1::uuid AND e.revoked_at IS NULL
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
    "CommandClaim",
    "MT5CommandRepository",
    "get_mt5_command_repository",
]
