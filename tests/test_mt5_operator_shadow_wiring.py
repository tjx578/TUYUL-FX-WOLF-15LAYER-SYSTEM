"""Unit gates for one-shot, operator-controlled C3 SHADOW wiring."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from contracts.mt5_operator_shadow import OperatorShadowManifest, OperatorShadowRequest
from execution.execution_plane_flags import ExecutionPlaneFlags
from execution.mt5_operator_shadow_wiring import (
    OperatorControlledShadowAuthorityV1,
    OperatorShadowConflictError,
    OperatorShadowNotReadyError,
)

_NOW = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)
_TRADEPLAN_ID = "5scr-plan:" + "a" * 32
_SIGNAL_ID = "5scr-signal:" + "b" * 32
_SIGNAL_HASH = "sha256:" + "c" * 64


def _flags(
    *,
    risk_reservation_enabled: bool = True,
    mt5_order_send_enabled: bool = False,
) -> ExecutionPlaneFlags:
    return ExecutionPlaneFlags(
        execution_enabled=True,
        signed_command_bridge_enabled=True,
        execution_command_producer_enabled=True,
        risk_reservation_enabled=risk_reservation_enabled,
        trade_outbox_write_enabled=True,
        ea_command_delivery_enabled=True,
        mt5_order_send_enabled=mt5_order_send_enabled,
    )


def _request(*, executor_id: UUID | None = None, governance_version: int = 7) -> OperatorShadowRequest:
    return OperatorShadowRequest(
        operator_run_id="c3-eurusd-001",
        confirm_run_id="c3-eurusd-001",
        actor="operator:test",
        reason="C3 EURUSD broker-connected SHADOW acceptance",
        tradeplan_id=_TRADEPLAN_ID,
        executor_id=executor_id or uuid4(),
        broker_symbol="EURUSD",
        expected_governance_version=governance_version,
        requested_at_utc=_NOW,
        expires_at_utc=_NOW + timedelta(seconds=120),
    )


class _FakePostgres:
    is_available = True

    def __init__(self, request: OperatorShadowRequest) -> None:
        self.request = request
        self.reservation_id = uuid4()
        self.outbox_id = uuid4()
        self.command_id = uuid4()
        self.command_created = False
        self.queued_manifest: dict[str, Any] | None = None
        self.audits: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.governance_version = request.expected_governance_version
        self.active_commands = 0

    async def fetchrow(self, query: str, *args: Any) -> Any | None:
        if "action = 'C3_SHADOW_QUEUED'" in query:
            return {"new_state": self.queued_manifest} if self.queued_manifest is not None else None
        if "action = 'C3_SHADOW_REQUESTED'" in query:
            return None
        if "SELECT e.execution_mode" in query:
            return {
                "execution_mode": "SHADOW",
                "status": "ONLINE",
                "revoked_at": None,
                "kill_switch_active": True,
                "kill_switch_reason": "DEFAULT_ENGAGED",
                "governance_version": self.governance_version,
                "active_commands": self.active_commands,
            }
        if "INSERT INTO executor_governance_audit" in query:
            action = str(args[1])
            previous_state = json.loads(str(args[4]))
            new_state = json.loads(str(args[5]))
            self.audits.append((action, previous_state, new_state))
            if action == "C3_SHADOW_QUEUED":
                self.queued_manifest = new_state
            return {"created_at": _NOW + timedelta(milliseconds=len(self.audits))}
        if "SELECT r.reservation_id" in query:
            if not self.command_created:
                return None
            return {
                "reservation_id": self.reservation_id,
                "tradeplan_id": self.request.tradeplan_id,
                "executor_id": self.request.executor_id,
                "canonical_symbol": "EURUSD",
                "broker_symbol": self.request.broker_symbol,
                "account_snapshot_id": "snapshot-c3-001",
                "signal_id": _SIGNAL_ID,
                "signal_hash": _SIGNAL_HASH,
                "command_id": self.command_id,
                "outbox_id": self.outbox_id,
                "issued_at": _NOW + timedelta(seconds=1),
                "expires_at": _NOW + timedelta(seconds=30),
                "execution_mode": "SHADOW",
            }
        raise AssertionError(f"unexpected SQL: {query}")


class _FakeReservations:
    def __init__(self, pg: _FakePostgres) -> None:
        self.pg = pg
        self.requests: list[Any] = []

    async def schema_status(self) -> dict[str, Any]:
        return {"ready": True}

    async def reserve_parent(self, request: Any) -> Any:
        self.requests.append(request)
        return SimpleNamespace(
            reservation=SimpleNamespace(reservation_id=self.pg.reservation_id),
            outbox_id=self.pg.outbox_id,
        )


class _FakeCommands:
    def __init__(self, pg: _FakePostgres, *, create: bool = True) -> None:
        self.pg = pg
        self.create = create
        self.selected: list[UUID | str | None] = []

    async def schema_status(self) -> dict[str, Any]:
        return {"ready": True}

    async def produce_next(self, *, reservation_id: UUID | str | None = None) -> None:
        self.selected.append(reservation_id)
        self.pg.command_created = self.create


def _authority(
    pg: _FakePostgres,
    *,
    flags: ExecutionPlaneFlags | None = None,
    create: bool = True,
) -> tuple[OperatorControlledShadowAuthorityV1, _FakeReservations, _FakeCommands]:
    reservations = _FakeReservations(pg)
    commands = _FakeCommands(pg, create=create)
    authority = OperatorControlledShadowAuthorityV1(
        pg=pg,  # type: ignore[arg-type]
        flags=flags or _flags(),
        reservations=reservations,
        commands=commands,
        clock=lambda: _NOW,
    )
    return authority, reservations, commands


def test_request_requires_run_specific_confirmation() -> None:
    with pytest.raises(ValidationError, match="confirm_run_id"):
        OperatorShadowRequest(
            **{
                **_request().model_dump(),
                "confirm_run_id": "different-run",
            }
        )


@pytest.mark.asyncio
async def test_c3_fails_closed_when_any_required_flag_is_off() -> None:
    request = _request()
    pg = _FakePostgres(request)
    authority, _, _ = _authority(pg, flags=_flags(risk_reservation_enabled=False))

    with pytest.raises(OperatorShadowNotReadyError, match="RISK_RESERVATION_ENABLED"):
        await authority.issue(request)
    assert pg.audits == []


@pytest.mark.asyncio
async def test_c3_refuses_order_send_even_for_an_explicit_operator() -> None:
    request = _request()
    pg = _FakePostgres(request)
    authority, _, _ = _authority(pg, flags=_flags(mt5_order_send_enabled=True))

    with pytest.raises(OperatorShadowNotReadyError, match="ORDER_SEND"):
        await authority.issue(request)


@pytest.mark.asyncio
async def test_c3_rejects_a_stale_governance_version_before_mutation() -> None:
    request = _request(governance_version=7)
    pg = _FakePostgres(request)
    pg.governance_version = 8
    authority, reservations, commands = _authority(pg)

    with pytest.raises(OperatorShadowConflictError, match="GOVERNANCE_VERSION_STALE"):
        await authority.issue(request)
    assert reservations.requests == []
    assert commands.selected == []


@pytest.mark.asyncio
async def test_c3_queues_only_the_operator_selected_reservation_and_audits_it() -> None:
    request = _request()
    pg = _FakePostgres(request)
    authority, reservations, commands = _authority(pg)

    manifest = await authority.issue(request)

    assert len(reservations.requests) == 1
    assert commands.selected == [pg.reservation_id]
    assert [audit[0] for audit in pg.audits] == ["C3_SHADOW_REQUESTED", "C3_SHADOW_QUEUED"]
    assert manifest.execution_mode == "SHADOW"
    assert manifest.broker_execution == "FORBIDDEN"
    assert manifest.command_id == pg.command_id
    serialized = json.dumps(manifest.model_dump(mode="json"), sort_keys=True)
    for forbidden in ("account_id", "account_number", "login_hash", "token", "secret", "verification_key"):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_c3_returns_an_existing_queued_manifest_even_after_flags_are_off() -> None:
    request = _request()
    pg = _FakePostgres(request)
    manifest = OperatorShadowManifest(
        operator_run_id=request.operator_run_id,
        tradeplan_id=request.tradeplan_id,
        executor_id=request.executor_id,
        canonical_symbol="EURUSD",
        broker_symbol=request.broker_symbol,
        risk_reservation_id=pg.reservation_id,
        risk_snapshot_id="snapshot-c3-001",
        final_signal_id=_SIGNAL_ID,
        final_signal_hash=_SIGNAL_HASH,
        outbox_id=pg.outbox_id,
        command_id=pg.command_id,
        requested_at_utc=request.requested_at_utc,
        command_expires_at_utc=request.requested_at_utc + timedelta(seconds=30),
    )
    pg.queued_manifest = manifest.model_dump(mode="json")
    authority, reservations, commands = _authority(pg, flags=ExecutionPlaneFlags())

    recovered = await authority.issue(request)

    assert recovered == manifest
    assert reservations.requests == []
    assert commands.selected == []


@pytest.mark.asyncio
async def test_c3_records_a_redacted_abort_when_target_command_is_not_created() -> None:
    request = _request()
    pg = _FakePostgres(request)
    authority, _, commands = _authority(pg, create=False)

    with pytest.raises(OperatorShadowConflictError, match="TARGET_COMMAND_NOT_CREATED"):
        await authority.issue(request)
    assert commands.selected == [pg.reservation_id]
    assert [audit[0] for audit in pg.audits] == ["C3_SHADOW_REQUESTED", "C3_SHADOW_ABORTED"]
    aborted = pg.audits[-1][2]
    assert aborted["reason_code"] == "C3_OPERATOR_SHADOW_CONFLICT"
    assert "detail" not in aborted
