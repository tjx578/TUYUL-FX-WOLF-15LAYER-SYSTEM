"""Explicit one-shot C3 wiring from risk authority to an MT5 SHADOW command.

This module is intentionally not imported by a service runner.  It requires a
fresh operator request, exact governance version, an engaged kill switch, and
all C1/C2 flags enabled only in the invoking process.  Broker order submission
must remain disabled.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID

from contracts.mt5_operator_shadow import OperatorShadowManifest, OperatorShadowRequest
from contracts.strategy_5scr_risk_reservation import RiskReservationRequest, RiskReservationResult
from execution.execution_plane_flags import ExecutionPlaneFlags, validate_execution_plane
from execution.mt5_risk_command_producer import MT5RiskCommandProducer, RiskCommandProductionResult
from storage.postgres_client import PostgresClient, pg_client
from storage.strategy_5scr_risk_reservation_repository import Strategy5SCRRiskReservationRepository

_TERMINAL_COMMAND_STATES = (
    "REJECTED",
    "FILLED",
    "CANCELLED",
    "COMPLETED",
    "EXPIRED",
    "SHADOW_COMPLETED",
    "SHADOW_REJECTED",
)
_REQUEST_CLOCK_SKEW_SECONDS = 5.0


class OperatorShadowWiringError(RuntimeError):
    """Base class for stable, fail-closed C3 failures."""

    reason_code = "C3_OPERATOR_SHADOW_ERROR"


class OperatorShadowNotReadyError(OperatorShadowWiringError):
    reason_code = "C3_OPERATOR_SHADOW_NOT_READY"


class OperatorShadowConflictError(OperatorShadowWiringError):
    reason_code = "C3_OPERATOR_SHADOW_CONFLICT"


class _ReservationAuthority(Protocol):
    async def schema_status(self) -> dict[str, Any]: ...

    async def reserve_parent(self, request: RiskReservationRequest) -> RiskReservationResult: ...


class _CommandAuthority(Protocol):
    async def schema_status(self) -> dict[str, Any]: ...

    async def produce_next(
        self,
        *,
        reservation_id: UUID | str | None = None,
    ) -> RiskCommandProductionResult | None: ...


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), default=str)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise OperatorShadowConflictError("stored operator audit state is not an object")
    return dict(value)


class OperatorControlledShadowAuthorityV1:
    """Reserve and queue exactly one operator-selected Strategy 5S-CR command."""

    def __init__(
        self,
        pg: PostgresClient | None = None,
        *,
        flags: ExecutionPlaneFlags | None = None,
        environ: Mapping[str, str] | None = None,
        reservations: _ReservationAuthority | None = None,
        commands: _CommandAuthority | None = None,
        clock: Any | None = None,
    ) -> None:
        self._pg = pg or pg_client
        self._environ = environ
        self._flags = flags or ExecutionPlaneFlags.from_env(environ, strict=True)
        self._reservations = reservations or Strategy5SCRRiskReservationRepository(pg=self._pg)
        self._commands = commands or MT5RiskCommandProducer(
            pg=self._pg,
            flags=self._flags,
            environ=environ,
        )
        self._clock = clock or (lambda: datetime.now(UTC))

    def _require_process_authority(self) -> None:
        validate_execution_plane(self._flags)
        required = {
            "EXECUTION_ENABLED": self._flags.execution_enabled,
            "SIGNED_COMMAND_BRIDGE_ENABLED": self._flags.signed_command_bridge_enabled,
            "EXECUTION_COMMAND_PRODUCER_ENABLED": self._flags.execution_command_producer_enabled,
            "RISK_RESERVATION_ENABLED": self._flags.risk_reservation_enabled,
            "TRADE_OUTBOX_WRITE_ENABLED": self._flags.trade_outbox_write_enabled,
            "EA_COMMAND_DELIVERY_ENABLED": self._flags.ea_command_delivery_enabled,
        }
        missing = sorted(name for name, enabled in required.items() if not enabled)
        if missing:
            raise OperatorShadowNotReadyError("C3_FLAGS_DISABLED:" + ",".join(missing))
        if self._flags.legacy_push_execution_enabled:
            raise OperatorShadowNotReadyError("C3_LEGACY_EXECUTION_FORBIDDEN")
        if self._flags.mt5_order_send_enabled:
            raise OperatorShadowNotReadyError("C3_ORDER_SEND_MUST_REMAIN_DISABLED")

    def _require_request_time(self, request: OperatorShadowRequest) -> datetime:
        now = cast(datetime, self._clock()).astimezone(UTC)
        skew = abs((now - request.requested_at_utc).total_seconds())
        if skew > _REQUEST_CLOCK_SKEW_SECONDS:
            raise OperatorShadowNotReadyError(f"C3_OPERATOR_REQUEST_STALE:{skew:.3f}s")
        if request.expires_at_utc <= now:
            raise OperatorShadowNotReadyError("C3_OPERATOR_REQUEST_EXPIRED")
        return now

    async def _queued_manifest(self, request: OperatorShadowRequest) -> OperatorShadowManifest | None:
        row = await self._pg.fetchrow(
            """
            SELECT new_state
            FROM executor_governance_audit
            WHERE action = 'C3_SHADOW_QUEUED'
              AND new_state ->> 'operator_run_id' = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            request.operator_run_id,
        )
        if row is None:
            return None
        manifest = OperatorShadowManifest.model_validate(_mapping(row["new_state"]))
        if (
            manifest.tradeplan_id != request.tradeplan_id
            or manifest.executor_id != request.executor_id
            or manifest.broker_symbol != request.broker_symbol
        ):
            raise OperatorShadowConflictError("operator_run_id is already bound to a different target")
        return manifest

    async def _latest_request_audit(self, request: OperatorShadowRequest) -> datetime | None:
        row = await self._pg.fetchrow(
            """
            SELECT new_state
            FROM executor_governance_audit
            WHERE action = 'C3_SHADOW_REQUESTED'
              AND new_state ->> 'operator_run_id' = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            request.operator_run_id,
        )
        if row is None:
            return None
        state = _mapping(row["new_state"])
        expected = {
            "tradeplan_id": request.tradeplan_id,
            "executor_id": str(request.executor_id),
            "broker_symbol": request.broker_symbol,
        }
        if any(str(state.get(name)) != value for name, value in expected.items()):
            raise OperatorShadowConflictError("operator_run_id request audit is bound to a different target")
        raw_requested_at = state.get("requested_at_utc")
        if not isinstance(raw_requested_at, str):
            raise OperatorShadowConflictError("operator request audit is missing requested_at_utc")
        try:
            requested_at = datetime.fromisoformat(raw_requested_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise OperatorShadowConflictError("operator request audit has invalid requested_at_utc") from exc
        if requested_at.tzinfo is None or requested_at.utcoffset() is None:
            raise OperatorShadowConflictError("operator request audit requested_at_utc is timezone-naive")
        return requested_at.astimezone(UTC)

    async def _append_audit(
        self,
        request: OperatorShadowRequest,
        *,
        action: str,
        previous_state: Mapping[str, Any],
        new_state: Mapping[str, Any],
    ) -> datetime:
        row = await self._pg.fetchrow(
            """
            INSERT INTO executor_governance_audit (
                executor_id, action, actor, reason, previous_state, new_state
            ) VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6::jsonb)
            RETURNING created_at
            """,
            str(request.executor_id),
            action,
            request.actor,
            request.reason,
            _json(previous_state),
            _json(new_state),
        )
        if row is None:
            raise OperatorShadowNotReadyError("C3_AUDIT_WRITE_FAILED")
        return cast(datetime, row["created_at"]).astimezone(UTC)

    async def _preflight(self, request: OperatorShadowRequest) -> dict[str, Any]:
        if not self._pg.is_available:
            raise OperatorShadowNotReadyError("C3_POSTGRES_REQUIRED")
        self._require_process_authority()
        self._require_request_time(request)

        reservation_schema = await self._reservations.schema_status()
        command_schema = await self._commands.schema_status()
        if not reservation_schema.get("ready"):
            raise OperatorShadowNotReadyError("C3_RISK_SCHEMA_NOT_READY")
        if not command_schema.get("ready"):
            raise OperatorShadowNotReadyError("C3_COMMAND_SCHEMA_NOT_READY")

        row = await self._pg.fetchrow(
            """
            SELECT e.execution_mode, e.status, e.revoked_at,
                   g.kill_switch_active, g.kill_switch_reason, g.governance_version,
                   (SELECT count(*)
                    FROM execution_commands c
                    WHERE c.executor_id = e.executor_id
                      AND c.state <> ALL($2::text[])) AS active_commands
            FROM executor_instances e
            CROSS JOIN executor_bridge_governance g
            WHERE e.executor_id = $1::uuid AND g.singleton_id = 1
            """,
            str(request.executor_id),
            list(_TERMINAL_COMMAND_STATES),
        )
        if row is None or row["revoked_at"] is not None:
            raise OperatorShadowNotReadyError("C3_EXECUTOR_UNAVAILABLE")
        if str(row["execution_mode"]) != "SHADOW":
            raise OperatorShadowNotReadyError("C3_EXECUTOR_NOT_SHADOW")
        if str(row["status"]) != "ONLINE":
            raise OperatorShadowNotReadyError("C3_EXECUTOR_NOT_ONLINE")
        if not bool(row["kill_switch_active"]):
            raise OperatorShadowNotReadyError("C3_KILL_SWITCH_DISENGAGED")
        if int(row["governance_version"]) != request.expected_governance_version:
            raise OperatorShadowConflictError(
                "C3_GOVERNANCE_VERSION_STALE:"
                f"expected={request.expected_governance_version}:current={int(row['governance_version'])}"
            )
        if int(row["active_commands"]) != 0:
            raise OperatorShadowConflictError("C3_ACTIVE_COMMAND_EXISTS")
        return {
            "execution_mode": str(row["execution_mode"]),
            "kill_switch_active": bool(row["kill_switch_active"]),
            "kill_switch_reason": str(row["kill_switch_reason"]),
            "governance_version": int(row["governance_version"]),
            "active_commands": int(row["active_commands"]),
            "mt5_order_send_enabled": self._flags.mt5_order_send_enabled,
        }

    async def _manifest_from_database(
        self,
        request: OperatorShadowRequest,
        *,
        request_started_at: datetime,
    ) -> OperatorShadowManifest | None:
        row = await self._pg.fetchrow(
            """
            SELECT r.reservation_id, r.tradeplan_id, r.executor_id,
                   r.canonical_symbol, r.broker_symbol, r.account_snapshot_id,
                   r.signal_id, r.signal_hash, r.command_id,
                   o.outbox_id, c.issued_at, c.expires_at,
                   c.payload #>> '{executor_binding,execution_mode}' AS execution_mode
            FROM strategy_5scr_risk_reservations r
            JOIN strategy_5scr_final_signal_outbox o ON o.reservation_id = r.reservation_id
            JOIN execution_commands c ON c.command_id = r.command_id
            WHERE r.tradeplan_id = $1 AND r.executor_id = $2::uuid
              AND r.broker_symbol = $3
              AND c.issued_at >= $4::timestamptz - interval '5 seconds'
            """,
            request.tradeplan_id,
            str(request.executor_id),
            request.broker_symbol,
            request_started_at,
        )
        if row is None:
            return None
        if str(row["execution_mode"]) != "SHADOW":
            raise OperatorShadowConflictError("recovered command is not SHADOW")
        return OperatorShadowManifest(
            operator_run_id=request.operator_run_id,
            tradeplan_id=str(row["tradeplan_id"]),
            executor_id=row["executor_id"],
            canonical_symbol=str(row["canonical_symbol"]),
            broker_symbol=str(row["broker_symbol"]),
            risk_reservation_id=row["reservation_id"],
            risk_snapshot_id=str(row["account_snapshot_id"]),
            final_signal_id=str(row["signal_id"]),
            final_signal_hash=str(row["signal_hash"]),
            outbox_id=row["outbox_id"],
            command_id=row["command_id"],
            requested_at_utc=request.requested_at_utc,
            command_expires_at_utc=row["expires_at"],
        )

    async def issue(self, request: OperatorShadowRequest) -> OperatorShadowManifest:
        """Create or recover exactly one audited C3 SHADOW command."""

        if not self._pg.is_available:
            raise OperatorShadowNotReadyError("C3_POSTGRES_REQUIRED")
        existing = await self._queued_manifest(request)
        if existing is not None:
            return existing

        previous_request_at = await self._latest_request_audit(request)
        if previous_request_at is not None:
            recovered = await self._manifest_from_database(request, request_started_at=previous_request_at)
            if recovered is not None:
                await self._append_audit(
                    request,
                    action="C3_SHADOW_QUEUED",
                    previous_state={"recovered_after_interruption": True},
                    new_state=recovered.model_dump(mode="json"),
                )
                return recovered

        preflight = await self._preflight(request)
        await self._append_audit(
            request,
            action="C3_SHADOW_REQUESTED",
            previous_state=preflight,
            new_state={
                "operator_run_id": request.operator_run_id,
                "operator_authority": request.operator_authority,
                "tradeplan_id": request.tradeplan_id,
                "executor_id": str(request.executor_id),
                "broker_symbol": request.broker_symbol,
                "requested_at_utc": request.requested_at_utc.isoformat(),
                "execution_mode": "SHADOW",
                "broker_execution": "FORBIDDEN",
            },
        )
        try:
            reservation = await self._reservations.reserve_parent(
                RiskReservationRequest(
                    tradeplan_id=request.tradeplan_id,
                    executor_id=request.executor_id,
                    broker_symbol=request.broker_symbol,
                    requested_at_utc=request.requested_at_utc,
                    expires_at_utc=request.expires_at_utc,
                )
            )
            await self._commands.produce_next(reservation_id=reservation.reservation.reservation_id)
            manifest = await self._manifest_from_database(request, request_started_at=request.requested_at_utc)
            if manifest is None:
                raise OperatorShadowConflictError("C3_TARGET_COMMAND_NOT_CREATED")
            await self._append_audit(
                request,
                action="C3_SHADOW_QUEUED",
                previous_state={
                    "risk_reservation_id": str(reservation.reservation.reservation_id),
                    "outbox_id": str(reservation.outbox_id),
                },
                new_state=manifest.model_dump(mode="json"),
            )
            return manifest
        except Exception as exc:
            reason_code = str(getattr(exc, "reason_code", type(exc).__name__))
            with suppress(Exception):
                await self._append_audit(
                    request,
                    action="C3_SHADOW_ABORTED",
                    previous_state={"operator_run_id": request.operator_run_id},
                    new_state={
                        "operator_run_id": request.operator_run_id,
                        "tradeplan_id": request.tradeplan_id,
                        "executor_id": str(request.executor_id),
                        "broker_symbol": request.broker_symbol,
                        "reason_code": reason_code,
                    },
                )
            raise


__all__ = [
    "OperatorControlledShadowAuthorityV1",
    "OperatorShadowConflictError",
    "OperatorShadowNotReadyError",
    "OperatorShadowWiringError",
]
