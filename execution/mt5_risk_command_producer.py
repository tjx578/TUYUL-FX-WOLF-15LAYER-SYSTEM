"""Atomic, default-off producer for risk-authorized MT5 SHADOW commands.

The producer is deliberately not wired into a service loop.  A caller must
explicitly enable every execution-plane prerequisite before one final-signal
outbox row can be consumed.  One PostgreSQL transaction creates the signed
command, consumes its reservation, and publishes its outbox record.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from contracts.mt5_execution_protocol import (
    AccountSnapshotV1,
    CommandSource,
    ExecutionAction,
    ExecutionCommandV1,
    ExecutorMode,
    MarginMode,
    build_signed_execution_envelope,
    sha256_tag,
)
from contracts.strategy_5scr_risk_reservation import validate_final_signal_reservation
from execution.execution_plane_flags import ExecutionPlaneFlags, validate_execution_plane
from execution.mt5_command_promotion import PromotionContext, promote_final_signal_to_command
from storage.postgres_client import PostgresClient, pg_client

_FINAL_SIGNAL_SCHEMA: Final = "wolf15.strategy-5scr.final-signal.v1"
_PRODUCER_ID: Final = "wolf15-mt5-risk-command-producer-v1"


class RiskCommandProducerError(RuntimeError):
    pass


class RiskCommandProducerNotReadyError(RiskCommandProducerError):
    pass


class RiskCommandProducerRejectedError(RiskCommandProducerError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class RiskCommandProductionPolicy:
    magic: int = 150_015
    max_spread_points: int = 25
    max_price_drift_points: int = 15
    heartbeat_max_age_seconds: int = 30
    snapshot_max_age_seconds: int = 30
    command_ttl_seconds: int = 30
    minimum_command_window_seconds: int = 5

    def __post_init__(self) -> None:
        positive = (
            self.magic,
            self.heartbeat_max_age_seconds,
            self.snapshot_max_age_seconds,
            self.command_ttl_seconds,
            self.minimum_command_window_seconds,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("risk command production policy values must be positive")
        if self.max_spread_points < 0 or self.max_price_drift_points < 0:
            raise ValueError("command market guards cannot be negative")
        if self.minimum_command_window_seconds >= self.command_ttl_seconds:
            raise ValueError("minimum command window must be shorter than command TTL")


@dataclass(frozen=True, slots=True)
class RiskCommandProductionResult:
    command: ExecutionCommandV1
    outbox_id: UUID
    reservation_id: UUID


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise RiskCommandProducerRejectedError("COMMAND_PAYLOAD_INVALID", "stored JSON is not an object")
        return cast(dict[str, Any], decoded)
    if isinstance(value, Mapping):
        return dict(value)
    raise RiskCommandProducerRejectedError("COMMAND_PAYLOAD_INVALID", "stored value is not a mapping")


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _age_seconds(now: datetime, value: datetime) -> float:
    return (now - value.astimezone(UTC)).total_seconds()


class MT5RiskCommandProducer:
    """Consume exactly one durable final signal into one signed SHADOW command."""

    def __init__(
        self,
        pg: PostgresClient | None = None,
        *,
        flags: ExecutionPlaneFlags | None = None,
        environ: Mapping[str, str] | None = None,
        policy: RiskCommandProductionPolicy | None = None,
        clock: Any | None = None,
    ) -> None:
        self._pg = pg or pg_client
        self._environ = os.environ if environ is None else environ
        self._flags = flags or ExecutionPlaneFlags.from_env(self._environ, strict=True)
        self._policy = policy or RiskCommandProductionPolicy()
        self._clock = clock or (lambda: datetime.now(UTC))

    def _require_ready(self) -> tuple[str, str]:
        validate_execution_plane(self._flags)
        required = {
            "EXECUTION_ENABLED": self._flags.execution_enabled,
            "SIGNED_COMMAND_BRIDGE_ENABLED": self._flags.signed_command_bridge_enabled,
            "EXECUTION_COMMAND_PRODUCER_ENABLED": self._flags.execution_command_producer_enabled,
            "RISK_RESERVATION_ENABLED": self._flags.risk_reservation_enabled,
            "TRADE_OUTBOX_WRITE_ENABLED": self._flags.trade_outbox_write_enabled,
        }
        missing = sorted(name for name, enabled in required.items() if not enabled)
        if missing:
            raise RiskCommandProducerNotReadyError("COMMAND_PRODUCER_DISABLED:" + ",".join(missing))
        if self._flags.legacy_push_execution_enabled:
            raise RiskCommandProducerNotReadyError("COMMAND_PRODUCER_LEGACY_PATH_FORBIDDEN")
        if self._flags.mt5_order_send_enabled:
            raise RiskCommandProducerNotReadyError("COMMAND_PRODUCER_REQUIRES_ORDER_SEND_DISABLED")
        if not self._pg.is_available:
            raise RiskCommandProducerNotReadyError("PostgreSQL is required for MT5 command production")
        secret = str(self._environ.get("EXECUTOR_COMMAND_SIGNING_SECRET", "")).strip()
        key_id = str(self._environ.get("EXECUTOR_COMMAND_SIGNING_KEY_ID", "")).strip()
        if len(secret.encode("utf-8")) < 32:
            raise RiskCommandProducerNotReadyError("EXECUTOR_COMMAND_SIGNING_SECRET is missing or too short")
        if not key_id:
            raise RiskCommandProducerNotReadyError("EXECUTOR_COMMAND_SIGNING_KEY_ID is required")
        return secret, key_id

    async def schema_status(self) -> dict[str, Any]:
        """Verify the exact C2 columns, relational binding, checks, and triggers."""

        if not self._pg.is_available:
            raise RiskCommandProducerNotReadyError("PostgreSQL is required for schema readiness")
        required_columns = {
            "risk_reservation_id": ("uuid", "YES"),
            "risk_snapshot_id": ("character varying", "YES"),
        }
        column_rows = await self._pg.fetch(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'execution_commands'
              AND column_name = ANY($1::text[])
            """,
            list(required_columns),
        )
        columns = {str(row["column_name"]): (str(row["data_type"]), str(row["is_nullable"])) for row in column_rows}
        missing_columns = sorted(name for name, shape in required_columns.items() if columns.get(name) != shape)

        required_constraints: dict[str, tuple[str, ...]] = {
            "fk_5scr_risk_reservation_command_v2": (
                "FOREIGN KEY",
                "command_id",
                "DEFERRABLE INITIALLY DEFERRED",
            ),
            "uq_5scr_reservation_command_binding_v1": ("UNIQUE", "command_id", "signal_hash"),
            "fk_execution_command_risk_reservation_v1": (
                "FOREIGN KEY",
                "risk_reservation_id",
                "source_signal_hash",
                "DEFERRABLE INITIALLY DEFERRED",
            ),
            "ck_execution_command_risk_authority_v1": (
                "CHECK",
                _FINAL_SIGNAL_SCHEMA,
                "PLACE_MARKET",
                "SHADOW",
                "PARENT",
            ),
        }
        constraint_rows = await self._pg.fetch(
            """
            SELECT conname, pg_get_constraintdef(oid) AS definition
            FROM pg_constraint
            WHERE conname = ANY($1::text[])
            """,
            list(required_constraints),
        )
        definitions = {str(row["conname"]): str(row["definition"]) for row in constraint_rows}
        missing_constraints = sorted(
            name
            for name, fragments in required_constraints.items()
            if name not in definitions or not all(fragment in definitions[name] for fragment in fragments)
        )

        index_rows = await self._pg.fetch(
            """
            SELECT indexname, indexdef FROM pg_indexes
            WHERE schemaname = 'public' AND indexname = 'uq_execution_command_risk_reservation_v1'
            """
        )
        index_definition = str(index_rows[0]["indexdef"]) if index_rows else ""
        missing_indexes = []
        if not all(fragment in index_definition for fragment in ("UNIQUE", "risk_reservation_id", "IS NOT NULL")):
            missing_indexes.append("uq_execution_command_risk_reservation_v1")

        required_triggers: dict[str, tuple[str, ...]] = {
            "trg_shadow_report_broker_forbidden_v2": ("execution_reports", "BEFORE INSERT OR UPDATE"),
            "trg_shadow_broker_entity_forbidden_v2": ("broker_entities", "BEFORE INSERT OR UPDATE"),
        }
        trigger_rows = await self._pg.fetch(
            """
            SELECT t.tgname, c.relname AS table_name, pg_get_triggerdef(t.oid) AS definition,
                   pg_get_functiondef(p.oid) AS function_definition
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_proc p ON p.oid = t.tgfoid
            WHERE n.nspname = 'public' AND NOT t.tgisinternal AND t.tgenabled <> 'D'
              AND t.tgname = ANY($1::text[])
            """,
            list(required_triggers),
        )
        trigger_defs = {
            str(row["tgname"]): " ".join(
                (str(row["table_name"]), str(row["definition"]), str(row["function_definition"]))
            )
            for row in trigger_rows
        }
        missing_triggers = sorted(
            name
            for name, fragments in required_triggers.items()
            if name not in trigger_defs
            or not all(fragment in trigger_defs[name] for fragment in (*fragments, "SHADOW"))
        )
        return {
            "ready": not (missing_columns or missing_constraints or missing_indexes or missing_triggers),
            "missing_columns": missing_columns,
            "missing_constraints": missing_constraints,
            "missing_indexes": missing_indexes,
            "missing_triggers": missing_triggers,
        }

    async def _expire_stale(self, connection: Any, *, now: datetime) -> None:
        await connection.execute(
            """
            UPDATE strategy_5scr_final_signal_outbox o
            SET status = 'DEAD', last_error = 'RISK_RESERVATION_EXPIRED', updated_at = $1
            FROM strategy_5scr_risk_reservations r
            WHERE o.reservation_id = r.reservation_id
              AND o.status = 'PENDING' AND r.state = 'HELD' AND r.expires_at <= $1
            """,
            now,
        )
        await connection.execute(
            """
            UPDATE strategy_5scr_risk_reservations r
            SET state = 'EXPIRED', expired_at = $1
            WHERE r.state = 'HELD' AND r.expires_at <= $1
              AND EXISTS (
                  SELECT 1 FROM strategy_5scr_final_signal_outbox o
                  WHERE o.reservation_id = r.reservation_id AND o.status = 'DEAD'
              )
            """,
            now,
        )

    def _validate_row(self, row: Mapping[str, Any], *, now: datetime) -> tuple[dict[str, Any], AccountSnapshotV1]:
        if row["revoked_at"] is not None or str(row["executor_status"]) != "ONLINE":
            raise RiskCommandProducerRejectedError("COMMAND_EXECUTOR_UNAVAILABLE", "executor is offline or revoked")
        if str(row["execution_mode"]) != "SHADOW":
            raise RiskCommandProducerRejectedError("COMMAND_SHADOW_ONLY", "risk command producer requires SHADOW")
        if not bool(row["kill_switch_active"]):
            raise RiskCommandProducerRejectedError(
                "COMMAND_KILL_SWITCH_DISENGAGED", "risk command production requires the kill switch engaged"
            )
        heartbeat = row["last_heartbeat_at"]
        if heartbeat is None or not 0 <= _age_seconds(now, heartbeat) <= self._policy.heartbeat_max_age_seconds:
            raise RiskCommandProducerRejectedError("COMMAND_HEARTBEAT_STALE", "executor heartbeat is not fresh")
        if str(row["latest_snapshot_id"]) != str(row["account_snapshot_id"]):
            raise RiskCommandProducerRejectedError(
                "COMMAND_RISK_SNAPSHOT_SUPERSEDED", "a newer account snapshot exists after reservation"
            )
        snapshot = AccountSnapshotV1.model_validate(_mapping(row["snapshot_payload"]))
        if snapshot.snapshot_id != str(row["account_snapshot_id"]):
            raise RiskCommandProducerRejectedError("COMMAND_SNAPSHOT_ID_MISMATCH", "snapshot payload identity drifted")
        if str(snapshot.executor_id) != str(row["executor_id"]) or snapshot.account_id != str(row["account_id"]):
            raise RiskCommandProducerRejectedError("COMMAND_SNAPSHOT_BINDING_MISMATCH", "snapshot binding drifted")
        snapshot_age = _age_seconds(now, snapshot.captured_at_utc)
        if not 0 <= snapshot_age <= self._policy.snapshot_max_age_seconds:
            raise RiskCommandProducerRejectedError("COMMAND_SNAPSHOT_STALE", "reserved account snapshot is not fresh")
        if not snapshot.trade_allowed or not snapshot.autotrading_enabled:
            raise RiskCommandProducerRejectedError("COMMAND_TERMINAL_NOT_READY", "terminal trading is not enabled")
        if snapshot.open_positions:
            raise RiskCommandProducerRejectedError(
                "COMMAND_PARENT_REQUIRES_FLAT_ACCOUNT", "parent command requires zero reconciled positions"
            )
        remaining = (row["reservation_expires_at"] - now).total_seconds()
        if remaining <= self._policy.minimum_command_window_seconds:
            raise RiskCommandProducerRejectedError(
                "COMMAND_RESERVATION_EXPIRING", "reservation has insufficient command validity remaining"
            )

        signal = _mapping(row["signal_payload"])
        if sha256_tag(signal) != str(row["outbox_payload_hash"]):
            raise RiskCommandProducerRejectedError("COMMAND_SIGNAL_HASH_MISMATCH", "outbox payload hash drifted")
        if str(row["reservation_signal_hash"]) != str(row["outbox_payload_hash"]):
            raise RiskCommandProducerRejectedError(
                "COMMAND_RESERVATION_HASH_MISMATCH", "reservation signal hash drifted"
            )
        proof = validate_final_signal_reservation(signal)
        exact = {
            "reservation_id": (str(proof.reservation_id), str(row["reservation_id"])),
            "campaign_id": (proof.campaign_id, str(row["campaign_id"])),
            "tradeplan_id": (proof.tradeplan_id, str(row["tradeplan_id"])),
            "canonical_symbol": (proof.canonical_symbol, str(row["canonical_symbol"])),
            "broker_symbol": (proof.broker_symbol, str(row["broker_symbol"])),
            "direction": (proof.direction, str(row["direction"])),
            "risk_snapshot_id": (proof.risk_snapshot_id, str(row["account_snapshot_id"])),
            "signal_id": (str(signal.get("signal_id")), str(row["signal_id"])),
        }
        drift = sorted(name for name, values in exact.items() if values[0] != values[1])
        if drift:
            raise RiskCommandProducerRejectedError(
                "COMMAND_AUTHORITY_BINDING_MISMATCH", "binding drift: " + ",".join(drift)
            )
        if not math.isclose(proof.reserved_volume, float(row["volume"]), rel_tol=1e-9, abs_tol=1e-9):
            raise RiskCommandProducerRejectedError("COMMAND_VOLUME_MISMATCH", "reserved volume drifted")
        return signal, snapshot

    async def produce_next(
        self,
        *,
        reservation_id: UUID | str | None = None,
    ) -> RiskCommandProductionResult | None:
        """Produce one command, optionally constrained to an operator-selected reservation.

        The unconstrained form is retained for a future supervised worker.  C3
        operator wiring must always pass ``reservation_id`` so an older pending
        outbox row cannot be consumed in place of the operator's explicit
        target.
        """

        secret, signing_key_id = self._require_ready()
        now = cast(datetime, self._clock()).astimezone(UTC)
        async with self._pg.transaction() as connection:
            await self._expire_stale(connection, now=now)
            row = await connection.fetchrow(
                """
                SELECT o.outbox_id, o.reservation_id, o.campaign_id, o.tradeplan_id,
                       o.executor_id, o.account_id, o.account_snapshot_id,
                       o.canonical_symbol, o.broker_symbol, o.direction, o.signal_id,
                       o.payload AS signal_payload, o.payload_hash AS outbox_payload_hash,
                       r.signal_hash AS reservation_signal_hash, r.entry_role, r.volume,
                       r.entry_price, r.stop_loss, r.take_profit, r.balance_snapshot,
                       r.equity_snapshot, r.reserved_at, r.expires_at AS reservation_expires_at,
                       e.login_hash, e.broker_server, e.execution_mode, e.status AS executor_status,
                       e.last_heartbeat_at, e.revoked_at, s.payload AS snapshot_payload,
                       latest.snapshot_id AS latest_snapshot_id, g.kill_switch_active
                FROM strategy_5scr_final_signal_outbox o
                JOIN strategy_5scr_risk_reservations r ON r.reservation_id = o.reservation_id
                JOIN executor_instances e ON e.executor_id = o.executor_id AND e.account_id = o.account_id
                JOIN executor_account_snapshots s ON s.snapshot_id = o.account_snapshot_id
                JOIN LATERAL (
                    SELECT snapshot_id
                    FROM executor_account_snapshots current_snapshot
                    WHERE current_snapshot.executor_id = o.executor_id
                      AND current_snapshot.account_id = o.account_id
                    ORDER BY captured_at DESC, received_at DESC
                    LIMIT 1
                ) latest ON TRUE
                CROSS JOIN executor_bridge_governance g
                WHERE o.status = 'PENDING' AND r.state = 'HELD' AND g.singleton_id = 1
                  AND ($1::uuid IS NULL OR o.reservation_id = $1::uuid)
                ORDER BY o.created_at, o.outbox_id
                LIMIT 1
                FOR UPDATE OF o, r, e, s, g SKIP LOCKED
                """,
                str(reservation_id) if reservation_id is not None else None,
            )
            if row is None:
                return None
            values = dict(row)
            signal, snapshot = self._validate_row(values, now=now)
            command_id = uuid5(NAMESPACE_URL, f"wolf15:risk-command:{values['reservation_id']}")
            command_expires_at = min(
                values["reservation_expires_at"],
                now + timedelta(seconds=self._policy.command_ttl_seconds),
            )
            context = PromotionContext(
                executor_id=values["executor_id"],
                account_id=str(values["account_id"]),
                login_hash=str(values["login_hash"]),
                broker_server=str(values["broker_server"]),
                execution_mode=ExecutorMode.SHADOW,
                campaign_id=str(values["campaign_id"]),
                block_id=str(values["tradeplan_id"]),
                block_role="PARENT",
                revision=1,
                action=ExecutionAction.PLACE_MARKET,
                canonical_symbol=str(values["canonical_symbol"]),
                broker_symbol=str(values["broker_symbol"]),
                order_type=cast(Literal["BUY", "SELL"], str(values["direction"])),
                volume=float(values["volume"]),
                entry_price=float(values["entry_price"]),
                stop_loss=float(values["stop_loss"]),
                take_profit=float(values["take_profit"]),
                magic=self._policy.magic,
                issued_at_utc=now,
                not_before_utc=now,
                expires_at_utc=command_expires_at,
                expected_margin_mode=MarginMode(snapshot.margin_mode),
                max_spread_points=self._policy.max_spread_points,
                max_price_drift_points=self._policy.max_price_drift_points,
                risk_snapshot_id=str(values["account_snapshot_id"]),
                risk_reservation_id=str(values["reservation_id"]),
                balance_snapshot=float(values["balance_snapshot"]),
                equity_snapshot=float(values["equity_snapshot"]),
            )
            command = promote_final_signal_to_command(
                signal,
                context=context,
                signing_secret=secret,
                signing_key_id=signing_key_id,
                command_id=command_id,
            )
            payload = command.model_dump(mode="json")
            command_source = cast(CommandSource, command.source)
            envelope = build_signed_execution_envelope(command, root_secret=secret, key_id=signing_key_id)

            await connection.execute(
                """
                UPDATE strategy_5scr_final_signal_outbox
                SET status = 'CLAIMED', attempts = attempts + 1, lease_owner = $2,
                    lease_expires_at = $3, updated_at = $3
                WHERE outbox_id = $1::uuid AND status = 'PENDING'
                """,
                str(values["outbox_id"]),
                _PRODUCER_ID,
                now,
            )
            await connection.execute(
                """
                INSERT INTO execution_commands (
                    command_id, executor_id, account_id, source_event,
                    source_signal_id, source_signal_hash, risk_reservation_id, risk_snapshot_id,
                    idempotency_key, revision, action, payload, payload_hash, state,
                    issued_at, not_before, expires_at, wire_format, payload_encoding,
                    signed_payload_b64, signed_payload_sha256, signature_algorithm,
                    signature_key_id, signature_value
                ) VALUES (
                    $1::uuid,$2::uuid,$3,'signal_json',$4,$5,$6::uuid,$7,$8,$9,$10,
                    $11::jsonb,$12,'QUEUED',$13,$14,$15,$16,$17,$18,$19,$20,$21,$22
                )
                """,
                str(command.command_id),
                str(command.executor_binding.executor_id),
                command.executor_binding.account_id,
                command_source.source_signal_id,
                command_source.source_signal_hash,
                str(values["reservation_id"]),
                str(values["account_snapshot_id"]),
                command.idempotency_key,
                command.revision,
                command.action.value,
                _json(payload),
                envelope.payload_sha256,
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
            await connection.execute(
                """
                UPDATE strategy_5scr_risk_reservations
                SET state = 'CONSUMED', command_id = $2::uuid, consumed_at = $3
                WHERE reservation_id = $1::uuid AND state = 'HELD'
                """,
                str(values["reservation_id"]),
                str(command.command_id),
                now,
            )
            await connection.execute(
                """
                UPDATE strategy_5scr_final_signal_outbox
                SET status = 'PUBLISHED', lease_owner = NULL, lease_expires_at = NULL,
                    published_at = $2, updated_at = $2
                WHERE outbox_id = $1::uuid AND status = 'CLAIMED'
                """,
                str(values["outbox_id"]),
                now,
            )
            return RiskCommandProductionResult(
                command=command,
                outbox_id=values["outbox_id"],
                reservation_id=values["reservation_id"],
            )


__all__ = [
    "MT5RiskCommandProducer",
    "RiskCommandProducerError",
    "RiskCommandProducerNotReadyError",
    "RiskCommandProducerRejectedError",
    "RiskCommandProductionPolicy",
    "RiskCommandProductionResult",
]
