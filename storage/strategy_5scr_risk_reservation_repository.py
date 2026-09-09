"""Atomic PostgreSQL authority for Strategy 5S-CR parent risk reservations.

The repository deliberately ends at a dark final-signal outbox.  It does not
create, sign, or deliver an MT5 command.  That separation makes durable risk
authority reviewable before any broker-connected execution path can consume it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Literal, cast
from uuid import UUID, uuid5

from analysis.strategy_5scr_m1_outcome import tradeplan_from_candidate_payload
from contracts.mt5_execution_protocol import AccountSnapshotV1, canonical_json_bytes, sha256_tag
from contracts.strategy_5scr_pressure import Strategy5SCRTradePlan
from contracts.strategy_5scr_risk_reservation import (
    FINAL_SIGNAL_SCHEMA_VERSION,
    RISK_POLICY_ID,
    DurableRiskReservation,
    RiskReservationRequest,
    RiskReservationResult,
    validate_final_signal_reservation,
)
from risk.s5_campaign_risk import (
    CampaignRiskLock,
    CampaignRiskPolicy,
    S5RiskReason,
    authorize_campaign_risk,
    find_symbol_capability,
    size_position_for_locked_risk,
    validate_account_snapshot,
)
from storage.postgres_client import PostgresClient, pg_client

_IDENTITY_NAMESPACE: Final = UUID("42b7b84b-41d7-4d28-9cf4-719670c03c88")
_APPROVED_PARENT: Final = S5RiskReason.APPROVED_PARENT
_ACTIVE_RISK_STATES: Final = ("HELD", "CONSUMED", "OPEN")


class RiskReservationError(RuntimeError):
    """Base class for fail-closed durable risk authority errors."""


class RiskReservationNotReadyError(RiskReservationError):
    """The database or its enforcement schema is unavailable."""


class RiskReservationRejectedError(RiskReservationError):
    """A candidate failed an explicit risk-authority gate."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


class RiskReservationConflictError(RiskReservationError):
    """An immutable identity was reused with different content."""


@dataclass(frozen=True, slots=True)
class DurableRiskReservationPolicy:
    campaign: CampaignRiskPolicy = CampaignRiskPolicy()
    candidate_max_age_seconds: int = 120
    request_clock_skew_seconds: int = 5
    commission_buffer_per_lot: float = 0.0
    slippage_buffer_per_lot: float = 0.0

    def __post_init__(self) -> None:
        if self.candidate_max_age_seconds < 1:
            raise ValueError("candidate_max_age_seconds must be positive")
        if self.request_clock_skew_seconds < 0:
            raise ValueError("request_clock_skew_seconds cannot be negative")
        if self.commission_buffer_per_lot < 0 or self.slippage_buffer_per_lot < 0:
            raise ValueError("loss buffers cannot be negative")


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise RiskReservationConflictError("stored JSON value is not an object")
    return dict(value)


def _candidate_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


def _identity_uuid(kind: str, identity: str) -> UUID:
    return uuid5(_IDENTITY_NAMESPACE, f"{kind}:{identity}")


def _signal_id(reservation_id: UUID) -> str:
    digest = hashlib.sha256(f"5scr-final-signal:{reservation_id}".encode("ascii")).hexdigest()
    return f"5scr-signal:{digest[:32]}"


def _assert_candidate_is_non_executable(payload: Mapping[str, Any]) -> None:
    required = {
        "event": "strategy_5scr_tradeplan_candidate",
        "final_direction": "WAIT",
        "signal_valid": False,
        "is_final_signal": False,
        "execution_valid_now": False,
        "valid_for_execution": False,
        "next_required_stage": "RISK_RESERVATION",
    }
    drift = [key for key, expected in required.items() if payload.get(key) != expected]
    if drift:
        raise RiskReservationRejectedError(
            "RISK_CANDIDATE_AUTHORITY_INVALID",
            "candidate authority fields drifted: " + ", ".join(sorted(drift)),
        )
    if payload.get("tradeplan_valid") is not True:
        raise RiskReservationRejectedError("RISK_CANDIDATE_INVALID", "candidate tradeplan_valid is not true")


def build_final_signal_payload(
    *,
    candidate_payload: Mapping[str, Any],
    tradeplan: Strategy5SCRTradePlan,
    reservation: DurableRiskReservation,
    signal_id: str,
) -> dict[str, Any]:
    """Promote one immutable candidate into a credential-free final signal."""

    _assert_candidate_is_non_executable(candidate_payload)
    if tradeplan.tradeplan_id != reservation.tradeplan_id:
        raise RiskReservationConflictError("tradeplan and reservation identity mismatch")
    if tradeplan.campaign_id != reservation.campaign_id:
        raise RiskReservationConflictError("campaign and reservation identity mismatch")
    if tradeplan.symbol != reservation.canonical_symbol:
        raise RiskReservationConflictError("symbol and reservation identity mismatch")
    if tradeplan.direction != reservation.direction:
        raise RiskReservationConflictError("direction and reservation identity mismatch")

    payload = deepcopy(dict(candidate_payload))
    payload.update(
        {
            "event": "signal_json",
            "schema_version": FINAL_SIGNAL_SCHEMA_VERSION,
            "signal_id": signal_id,
            "final_direction": tradeplan.direction,
            "signal_valid": True,
            "is_final_signal": True,
            "execution_valid_now": True,
            "valid_for_execution": True,
            "next_required_stage": "MT5_COMMAND_PROMOTION",
            "risk_reservation_id": str(reservation.reservation_id),
            "risk_snapshot_id": reservation.account_snapshot_id,
            "broker_symbol": reservation.broker_symbol,
            "reserved_volume": reservation.volume,
            "risk_reservation": reservation.signal_proof().model_dump(mode="json"),
        }
    )
    validate_final_signal_reservation(payload)
    return payload


def _reservation_from_row(row: Mapping[str, Any]) -> DurableRiskReservation:
    return DurableRiskReservation(
        reservation_id=row["reservation_id"],
        campaign_id=str(row["campaign_id"]),
        tradeplan_id=str(row["tradeplan_id"]),
        executor_id=row["executor_id"],
        account_id=str(row["account_id"]),
        account_snapshot_id=str(row["account_snapshot_id"]),
        state=cast(Literal["HELD"], str(row["state"])),
        canonical_symbol=str(row["canonical_symbol"]),
        broker_symbol=str(row["broker_symbol"]),
        entry_role=cast(Literal["PARENT"], str(row["entry_role"])),
        direction=cast(Literal["BUY", "SELL"], str(row["direction"])),
        volume=float(row["volume"]),
        entry_price=float(row["entry_price"]),
        stop_loss=float(row["stop_loss"]),
        take_profit=float(row["take_profit"]),
        risk_unit_usd=float(row["risk_unit_usd"]),
        reserved_risk_usd=float(row["reserved_risk_usd"]),
        balance_snapshot=float(row["balance_snapshot"]),
        equity_snapshot=float(row["equity_snapshot"]),
        reserved_at_utc=row["reserved_at"],
        expires_at_utc=row["expires_at"],
    )


def _result_from_rows(reservation_row: Mapping[str, Any], outbox_row: Mapping[str, Any]) -> RiskReservationResult:
    payload = _mapping(outbox_row["payload"])
    reservation = _reservation_from_row(reservation_row)
    if str(outbox_row["reservation_id"]) != str(reservation.reservation_id):
        raise RiskReservationConflictError("stored reservation/outbox binding mismatch")
    if str(outbox_row["account_snapshot_id"]) != reservation.account_snapshot_id:
        raise RiskReservationConflictError("stored snapshot/outbox binding mismatch")
    if sha256_tag(payload) != str(outbox_row["payload_hash"]):
        raise RiskReservationConflictError("stored final-signal payload hash mismatch")
    proof = validate_final_signal_reservation(payload)
    row_bindings = {
        "campaign_id": proof.campaign_id,
        "tradeplan_id": proof.tradeplan_id,
        "canonical_symbol": proof.canonical_symbol,
        "broker_symbol": proof.broker_symbol,
        "direction": proof.direction,
    }
    for field, expected in row_bindings.items():
        if str(outbox_row[field]) != expected:
            raise RiskReservationConflictError(f"stored {field}/outbox binding mismatch")
    return RiskReservationResult(
        reservation=reservation,
        outbox_id=outbox_row["outbox_id"],
        signal_id=str(outbox_row["signal_id"]),
        signal_payload=payload,
        signal_payload_hash=str(outbox_row["payload_hash"]),
    )


class Strategy5SCRRiskReservationRepository:
    """Create one parent reservation and final-signal outbox row atomically."""

    def __init__(
        self,
        pg: PostgresClient | None = None,
        *,
        policy: DurableRiskReservationPolicy | None = None,
        clock: Any | None = None,
    ) -> None:
        self._pg = pg or pg_client
        self._policy = policy or DurableRiskReservationPolicy()
        self._clock = clock or (lambda: datetime.now(UTC))

    def _require_database(self) -> None:
        if not self._pg.is_available:
            raise RiskReservationNotReadyError("PostgreSQL is required for durable risk authority")

    async def schema_status(self) -> dict[str, Any]:
        """Inspect exact tables, constraints, indexes, and immutable triggers."""

        self._require_database()
        tables = {
            "strategy_5scr_campaign_risk_locks",
            "strategy_5scr_risk_reservations",
            "strategy_5scr_final_signal_outbox",
        }
        table_rows = await self._pg.fetch(
            """
            SELECT c.relname
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname = ANY($1::text[])
            """,
            list(tables),
        )
        found_tables = {str(row["relname"]) for row in table_rows}

        required_constraints: dict[str, tuple[str, ...]] = {
            "pk_5scr_campaign_risk_locks_v1": ("PRIMARY KEY", "campaign_id", "account_id"),
            "ck_5scr_campaign_risk_lock_amounts_v1": ("CHECK", "risk_unit_usd"),
            "ck_5scr_risk_reservation_parent_only_v1": ("CHECK", "PARENT"),
            "ck_5scr_risk_reservation_lifecycle_v1": ("CHECK", "HELD", "CONSUMED", "OPEN"),
            "fk_5scr_risk_reservation_campaign_lock_v1": ("FOREIGN KEY", "campaign_id", "account_id"),
            "fk_5scr_final_signal_outbox_reservation_binding_v1": (
                "FOREIGN KEY",
                "reservation_id",
                "account_snapshot_id",
            ),
            "ck_5scr_final_signal_outbox_payload_v1": (
                "CHECK",
                "signal_json",
                "risk_reservation_id",
                "account_snapshot_id",
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

        required_indexes = {
            "uq_5scr_risk_reservation_active_parent",
            "ix_5scr_risk_reservations_account_state",
            "ix_5scr_final_signal_outbox_delivery",
        }
        index_rows = await self._pg.fetch(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname = ANY($1::text[])",
            list(required_indexes),
        )
        index_defs = {str(row["indexname"]): str(row["indexdef"]) for row in index_rows}
        missing_indexes = sorted(required_indexes - set(index_defs))
        active_index = index_defs.get("uq_5scr_risk_reservation_active_parent", "")
        if active_index and not all(fragment in active_index for fragment in ("UNIQUE", "HELD", "CONSUMED", "OPEN")):
            missing_indexes.append("uq_5scr_risk_reservation_active_parent")

        required_triggers = {
            "trg_5scr_campaign_risk_lock_update_v1",
            "trg_5scr_risk_reservation_update_v1",
            "trg_5scr_final_signal_outbox_update_v1",
        }
        trigger_rows = await self._pg.fetch(
            """
            SELECT t.tgname, pg_get_triggerdef(t.oid) AS definition
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND NOT t.tgisinternal
              AND t.tgenabled <> 'D' AND t.tgname = ANY($1::text[])
            """,
            list(required_triggers),
        )
        found_triggers = {str(row["tgname"]) for row in trigger_rows}
        missing_triggers = sorted(required_triggers - found_triggers)
        missing_tables = sorted(tables - found_tables)
        ready = not (missing_tables or missing_constraints or missing_indexes or missing_triggers)
        return {
            "ready": ready,
            "missing_tables": missing_tables,
            "missing_constraints": missing_constraints,
            "missing_indexes": sorted(set(missing_indexes)),
            "missing_triggers": missing_triggers,
        }

    async def _expire_stale_held(self, connection: Any, *, account_id: str, now: datetime) -> None:
        await connection.execute(
            """
            UPDATE strategy_5scr_final_signal_outbox o
            SET status = 'DEAD', last_error = 'RISK_RESERVATION_EXPIRED', updated_at = $2
            FROM strategy_5scr_risk_reservations r
            WHERE o.reservation_id = r.reservation_id
              AND r.account_id = $1 AND r.state = 'HELD' AND r.expires_at <= $2
              AND o.status = 'PENDING'
            """,
            account_id,
            now,
        )
        await connection.execute(
            """
            UPDATE strategy_5scr_risk_reservations
            SET state = 'EXPIRED', expired_at = $2
            WHERE account_id = $1 AND state = 'HELD' AND expires_at <= $2
              AND NOT EXISTS (
                  SELECT 1 FROM strategy_5scr_final_signal_outbox o
                  WHERE o.reservation_id = strategy_5scr_risk_reservations.reservation_id
                    AND o.status <> 'DEAD'
              )
            """,
            account_id,
            now,
        )

    async def reserve_parent(self, request: RiskReservationRequest) -> RiskReservationResult:
        """Reserve parent risk and enqueue final SignalJSON in one transaction."""

        self._require_database()
        now = cast(datetime, self._clock()).astimezone(UTC)
        skew = abs((now - request.requested_at_utc).total_seconds())
        if skew > self._policy.request_clock_skew_seconds:
            raise RiskReservationRejectedError("RISK_REQUEST_STALE", f"request clock skew is {skew:.3f}s")
        if request.expires_at_utc <= now:
            raise RiskReservationRejectedError("RISK_REQUEST_EXPIRED", "reservation request already expired")

        async with self._pg.transaction() as connection:
            governed = await connection.fetchrow(
                """
                SELECT e.executor_id, e.account_id, e.execution_mode, e.revoked_at,
                       g.kill_switch_active
                FROM executor_instances e
                CROSS JOIN executor_bridge_governance g
                WHERE e.executor_id = $1::uuid AND g.singleton_id = 1
                FOR UPDATE OF e, g
                """,
                str(request.executor_id),
            )
            if not governed or governed["revoked_at"] is not None:
                raise RiskReservationRejectedError("RISK_EXECUTOR_NOT_FOUND", "executor binding is unavailable")
            if str(governed["execution_mode"]) != "SHADOW":
                raise RiskReservationRejectedError("RISK_SHADOW_ONLY", "risk authority V1 requires SHADOW mode")
            if not bool(governed["kill_switch_active"]):
                raise RiskReservationRejectedError(
                    "RISK_KILL_SWITCH_DISENGAGED",
                    "risk authority V1 requires the global kill switch engaged",
                )
            account_id = str(governed["account_id"])
            await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", account_id)
            await self._expire_stale_held(connection, account_id=account_id, now=now)

            existing = await connection.fetchrow(
                """
                SELECT r.*, o.outbox_id, o.reservation_id AS outbox_reservation_id,
                       o.campaign_id AS outbox_campaign_id,
                       o.tradeplan_id AS outbox_tradeplan_id,
                       o.account_snapshot_id AS outbox_account_snapshot_id,
                       o.canonical_symbol AS outbox_canonical_symbol,
                       o.broker_symbol AS outbox_broker_symbol,
                       o.direction AS outbox_direction,
                       o.signal_id AS outbox_signal_id, o.payload, o.payload_hash, o.status AS outbox_status
                FROM strategy_5scr_risk_reservations r
                JOIN strategy_5scr_final_signal_outbox o ON o.reservation_id = r.reservation_id
                WHERE r.tradeplan_id = $1
                FOR UPDATE OF r, o
                """,
                request.tradeplan_id,
            )
            if existing:
                if (
                    str(existing["executor_id"]) != str(request.executor_id)
                    or str(existing["broker_symbol"]) != request.broker_symbol
                    or str(existing["entry_role"]) != request.entry_role
                    or existing["expires_at"] != request.expires_at_utc
                ):
                    raise RiskReservationConflictError("tradeplan already has a differently bound reservation")
                if str(existing["state"]) != "HELD" or str(existing["outbox_status"]) != "PENDING":
                    raise RiskReservationConflictError("tradeplan reservation is no longer reusable")
                outbox = {
                    "outbox_id": existing["outbox_id"],
                    "reservation_id": existing["outbox_reservation_id"],
                    "campaign_id": existing["outbox_campaign_id"],
                    "tradeplan_id": existing["outbox_tradeplan_id"],
                    "account_snapshot_id": existing["outbox_account_snapshot_id"],
                    "canonical_symbol": existing["outbox_canonical_symbol"],
                    "broker_symbol": existing["outbox_broker_symbol"],
                    "direction": existing["outbox_direction"],
                    "signal_id": existing["outbox_signal_id"],
                    "payload": existing["payload"],
                    "payload_hash": existing["payload_hash"],
                }
                return _result_from_rows(dict(existing), outbox)

            snapshot_row = await connection.fetchrow(
                """
                SELECT snapshot_id, payload
                FROM executor_account_snapshots
                WHERE executor_id = $1::uuid AND account_id = $2
                ORDER BY captured_at DESC, received_at DESC
                LIMIT 1 FOR UPDATE
                """,
                str(request.executor_id),
                account_id,
            )
            if not snapshot_row:
                raise RiskReservationRejectedError("RISK_SNAPSHOT_MISSING", "executor has no account snapshot")
            snapshot = AccountSnapshotV1.model_validate(_mapping(snapshot_row["payload"]))
            snapshot_verdict = validate_account_snapshot(
                snapshot,
                expected_account_id=account_id,
                policy=self._policy.campaign,
                now=now,
            )
            if not snapshot_verdict.allowed:
                reason = snapshot_verdict.reason or S5RiskReason.RISK_STATE_INVALID
                raise RiskReservationRejectedError(str(reason), snapshot_verdict.detail)
            if snapshot.executor_id != request.executor_id:
                raise RiskReservationRejectedError(
                    "RISK_SNAPSHOT_EXECUTOR_MISMATCH", "snapshot executor binding mismatch"
                )
            if snapshot.open_positions:
                raise RiskReservationRejectedError(
                    "RISK_PARENT_REQUIRES_FLAT_ACCOUNT",
                    "parent-only V1 requires zero reconciled broker positions",
                )

            candidate_row = await connection.fetchrow(
                """
                SELECT tradeplan_id, lifecycle_id, symbol, direction, decision_at, payload, payload_hash
                FROM strategy_5scr_tradeplan_candidates
                WHERE tradeplan_id = $1
                FOR UPDATE
                """,
                request.tradeplan_id,
            )
            if not candidate_row:
                raise RiskReservationRejectedError("RISK_CANDIDATE_MISSING", "tradeplan candidate is unavailable")
            candidate = _mapping(candidate_row["payload"])
            _assert_candidate_is_non_executable(candidate)
            if _candidate_hash(candidate) != str(candidate_row["payload_hash"]):
                raise RiskReservationConflictError("stored candidate payload hash mismatch")
            tradeplan = tradeplan_from_candidate_payload(candidate)
            if tradeplan.tradeplan_id != request.tradeplan_id:
                raise RiskReservationConflictError("candidate payload tradeplan identity mismatch")
            age = (now - tradeplan.decision_at_utc).total_seconds()
            if age < -self._policy.request_clock_skew_seconds or age > self._policy.candidate_max_age_seconds:
                raise RiskReservationRejectedError("RISK_CANDIDATE_STALE", f"candidate age is {age:.3f}s")

            symbol_spec = find_symbol_capability(
                snapshot,
                canonical_symbol=tradeplan.symbol,
                broker_symbol=request.broker_symbol,
            )
            if symbol_spec is None:
                raise RiskReservationRejectedError(
                    "RISK_SYMBOL_CAPABILITY_MISSING",
                    "requested broker symbol is absent from the latest account snapshot",
                )

            lock_row = await connection.fetchrow(
                """
                SELECT * FROM strategy_5scr_campaign_risk_locks
                WHERE campaign_id = $1 AND account_id = $2
                FOR UPDATE
                """,
                tradeplan.campaign_id,
                account_id,
            )
            if lock_row:
                if (
                    str(lock_row["state"]) != "ACTIVE"
                    or str(lock_row["executor_id"]) != str(request.executor_id)
                    or str(lock_row["policy_id"]) != RISK_POLICY_ID
                    or Decimal(str(lock_row["risk_percent_per_entry"])) != self._policy.campaign.risk_percent_per_entry
                ):
                    raise RiskReservationConflictError("campaign risk lock cannot be reused")
                risk_lock = CampaignRiskLock(
                    campaign_id=str(lock_row["campaign_id"]),
                    account_id=str(lock_row["account_id"]),
                    balance_base=Decimal(str(lock_row["balance_base"])),
                    risk_percent_per_entry=Decimal(str(lock_row["risk_percent_per_entry"])),
                    risk_unit_usd=Decimal(str(lock_row["risk_unit_usd"])),
                    max_campaign_risk_usd=Decimal(str(lock_row["max_campaign_risk_usd"])),
                    locked_at_utc=lock_row["locked_at"],
                )
            else:
                risk_lock = CampaignRiskLock.create(
                    campaign_id=tradeplan.campaign_id,
                    account_id=account_id,
                    closed_balance=snapshot.balance,
                    policy=self._policy.campaign,
                    now=now,
                )
                await connection.execute(
                    """
                    INSERT INTO strategy_5scr_campaign_risk_locks (
                        campaign_id, account_id, executor_id, account_snapshot_id, policy_id,
                        state, balance_base, risk_percent_per_entry, risk_unit_usd,
                        max_campaign_risk_usd, locked_at
                    ) VALUES ($1,$2,$3::uuid,$4,$5,'ACTIVE',$6,$7,$8,$9,$10)
                    """,
                    risk_lock.campaign_id,
                    risk_lock.account_id,
                    str(request.executor_id),
                    snapshot.snapshot_id,
                    RISK_POLICY_ID,
                    risk_lock.balance_base,
                    risk_lock.risk_percent_per_entry,
                    risk_lock.risk_unit_usd,
                    risk_lock.max_campaign_risk_usd,
                    risk_lock.locked_at_utc,
                )

            sizing = size_position_for_locked_risk(
                risk_lock=risk_lock,
                symbol_spec=symbol_spec,
                entry_price=tradeplan.entry,
                stop_loss=tradeplan.stop_loss,
                entry_role=request.entry_role,
                commission_buffer_per_lot=self._policy.commission_buffer_per_lot,
                slippage_buffer_per_lot=self._policy.slippage_buffer_per_lot,
            )
            totals = await connection.fetchrow(
                """
                SELECT
                    COALESCE(sum(reserved_risk_usd) FILTER (WHERE account_id = $1), 0) AS account_risk,
                    COALESCE(sum(reserved_risk_usd) FILTER (
                        WHERE account_id = $1 AND campaign_id = $2
                    ), 0) AS campaign_risk
                FROM strategy_5scr_risk_reservations
                WHERE state = ANY($3::text[])
                """,
                account_id,
                tradeplan.campaign_id,
                list(_ACTIVE_RISK_STATES),
            )
            verdict = authorize_campaign_risk(
                risk_lock=risk_lock,
                candidate=sizing,
                entry_role=request.entry_role,
                parent_is_open=False,
                child_already_exists=False,
                committed_or_reserved_campaign_risk_usd=float(totals["campaign_risk"]),
                account_total_open_risk_usd=float(totals["account_risk"]),
                policy=self._policy.campaign,
            )
            if verdict != _APPROVED_PARENT:
                raise RiskReservationRejectedError(str(verdict), "campaign risk policy rejected parent reservation")

            reservation_id = _identity_uuid("reservation", f"{account_id}:{request.tradeplan_id}")
            outbox_id = _identity_uuid("final-signal-outbox", str(reservation_id))
            signal_id = _signal_id(reservation_id)
            reservation = DurableRiskReservation(
                reservation_id=reservation_id,
                campaign_id=tradeplan.campaign_id,
                tradeplan_id=tradeplan.tradeplan_id,
                executor_id=request.executor_id,
                account_id=account_id,
                account_snapshot_id=snapshot.snapshot_id,
                canonical_symbol=tradeplan.symbol,
                broker_symbol=request.broker_symbol,
                direction=tradeplan.direction,
                volume=float(sizing.final_volume),
                entry_price=tradeplan.entry,
                stop_loss=tradeplan.stop_loss,
                take_profit=tradeplan.tp1,
                risk_unit_usd=float(risk_lock.risk_unit_usd),
                reserved_risk_usd=float(sizing.actual_planned_risk_usd),
                balance_snapshot=snapshot.balance,
                equity_snapshot=snapshot.equity,
                reserved_at_utc=now,
                expires_at_utc=request.expires_at_utc,
            )
            signal_payload = build_final_signal_payload(
                candidate_payload=candidate,
                tradeplan=tradeplan,
                reservation=reservation,
                signal_id=signal_id,
            )
            signal_hash = sha256_tag(signal_payload)
            await connection.execute(
                """
                INSERT INTO strategy_5scr_risk_reservations (
                    reservation_id, campaign_id, tradeplan_id, executor_id, account_id,
                    account_snapshot_id, source_candidate_hash, signal_id, signal_hash,
                    policy_id, state, canonical_symbol, broker_symbol, entry_role, direction,
                    volume, entry_price, stop_loss, take_profit, risk_unit_usd,
                    reserved_risk_usd, balance_snapshot, equity_snapshot, reserved_at, expires_at
                ) VALUES (
                    $1::uuid,$2,$3,$4::uuid,$5,$6,$7,$8,$9,$10,'HELD',$11,$12,'PARENT',$13,
                    $14,$15,$16,$17,$18,$19,$20,$21,$22,$23
                )
                """,
                str(reservation.reservation_id),
                reservation.campaign_id,
                reservation.tradeplan_id,
                str(reservation.executor_id),
                reservation.account_id,
                reservation.account_snapshot_id,
                str(candidate_row["payload_hash"]),
                signal_id,
                signal_hash,
                RISK_POLICY_ID,
                reservation.canonical_symbol,
                reservation.broker_symbol,
                reservation.direction,
                Decimal(str(reservation.volume)),
                Decimal(str(reservation.entry_price)),
                Decimal(str(reservation.stop_loss)),
                Decimal(str(reservation.take_profit)),
                Decimal(str(reservation.risk_unit_usd)),
                Decimal(str(reservation.reserved_risk_usd)),
                Decimal(str(reservation.balance_snapshot)),
                Decimal(str(reservation.equity_snapshot)),
                reservation.reserved_at_utc,
                reservation.expires_at_utc,
            )
            await connection.execute(
                """
                INSERT INTO strategy_5scr_final_signal_outbox (
                    outbox_id, reservation_id, campaign_id, tradeplan_id, executor_id, account_id,
                    account_snapshot_id, canonical_symbol, broker_symbol, direction,
                    signal_id, payload, payload_hash, status,
                    attempts, created_at, updated_at
                ) VALUES (
                    $1::uuid,$2::uuid,$3,$4,$5::uuid,$6,$7,$8,$9,$10,
                    $11,$12::jsonb,$13,'PENDING',0,$14,$14
                )
                """,
                str(outbox_id),
                str(reservation.reservation_id),
                reservation.campaign_id,
                reservation.tradeplan_id,
                str(reservation.executor_id),
                reservation.account_id,
                reservation.account_snapshot_id,
                reservation.canonical_symbol,
                reservation.broker_symbol,
                reservation.direction,
                signal_id,
                json.dumps(signal_payload, sort_keys=True, separators=(",", ":")),
                signal_hash,
                now,
            )
            return RiskReservationResult(
                reservation=reservation,
                outbox_id=outbox_id,
                signal_id=signal_id,
                signal_payload=signal_payload,
                signal_payload_hash=signal_hash,
            )


__all__ = [
    "DurableRiskReservationPolicy",
    "RiskReservationConflictError",
    "RiskReservationError",
    "RiskReservationNotReadyError",
    "RiskReservationRejectedError",
    "Strategy5SCRRiskReservationRepository",
    "build_final_signal_payload",
]
