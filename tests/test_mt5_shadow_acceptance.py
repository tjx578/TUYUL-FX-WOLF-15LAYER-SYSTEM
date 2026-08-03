"""Contracts for the isolated ShadowAcceptanceAuthority V1."""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from contracts.mt5_execution_protocol import (
    AccountSnapshotV1,
    ExecutionAction,
    ExecutorMode,
    MarginMode,
    ShadowAcceptanceSource,
    SymbolCapability,
    sign_execution_command,
    verify_execution_command,
)
from execution.mt5_shadow_acceptance import (
    SHADOW_ACCEPTANCE_EA_VERSION,
    ShadowAcceptanceError,
    ShadowAcceptanceRequest,
    acceptance_manifest,
    build_shadow_acceptance_commands,
)

SECRET = "a" * 64
BROKER_MAP = (
    Path(__file__).resolve().parents[1] / "ea_interface" / "wolf15_executor" / "broker_maps" / "xmglobal-mt5-10.csv"
)


def _pairs() -> tuple[tuple[str, str], ...]:
    with BROKER_MAP.open(newline="", encoding="utf-8-sig") as handle:
        return tuple((row["canonical_symbol"], row["broker_symbol"]) for row in csv.DictReader(handle))


def _snapshot(executor_id: UUID) -> AccountSnapshotV1:
    return AccountSnapshotV1(
        snapshot_id="snapshot-acceptance-001",
        captured_at_utc=datetime.now(UTC),
        executor_id=executor_id,
        account_id="account-identity-01",
        currency="USD",
        balance=1000,
        equity=1000,
        floating_pnl=0,
        used_margin=0,
        free_margin=1000,
        margin_level_pct=None,
        margin_mode=MarginMode.HEDGING,
        trade_allowed=True,
        autotrading_enabled=True,
        open_positions=[],
        symbols=[
            SymbolCapability(
                canonical_symbol=canonical,
                broker_symbol=broker,
                digits=5,
                point=0.00001,
                tick_size=0.00001,
                tick_value_profit=1,
                tick_value_loss=1,
                volume_min=0.01,
                volume_max=50,
                volume_step=0.01,
                stops_level_points=0,
                freeze_level_points=0,
                expiration_modes=["SPECIFIED"],
            )
            for canonical, broker in _pairs()
        ],
    )


def _request(executor_id: UUID, *, phase: Literal["A1", "A2"] = "A1") -> ShadowAcceptanceRequest:
    now = datetime.now(UTC)
    return ShadowAcceptanceRequest(
        acceptance_run_id="acceptance-20260803-a1",
        phase=phase,
        executor_id=executor_id,
        issued_at_utc=now,
        expires_at_utc=now + timedelta(minutes=5),
    )


def _executor(executor_id: UUID) -> dict[str, object]:
    return {
        "executor_id": executor_id,
        "account_id": "account-identity-01",
        "login_hash": "sha256:" + "1" * 64,
        "broker_server": "XMGlobal-MT5 10",
        "execution_mode": "SHADOW",
        "ea_version": SHADOW_ACCEPTANCE_EA_VERSION,
        "protocol_version": "wolf15.mt5.exec.v1",
    }


def test_a1_builds_one_signed_reconcile_only_command_without_risk_authority() -> None:
    executor_id = uuid4()
    commands = build_shadow_acceptance_commands(
        _request(executor_id),
        executor=_executor(executor_id),
        snapshot=_snapshot(executor_id),
        signing_secret=SECRET,
        signing_key_id="acceptance-test.v1",
    )

    assert len(commands) == 1
    command = commands[0]
    assert command.action is ExecutionAction.RECONCILE_ONLY
    assert command.order is None
    assert command.executor_binding.execution_mode is ExecutorMode.SHADOW
    assert isinstance(command.source, ShadowAcceptanceSource)
    assert command.source.source_event == "SHADOW_ACCEPTANCE"
    assert command.source.canonical_symbol == "EURUSD"
    assert command.source.execution_authority is False
    assert command.source.broker_execution == "FORBIDDEN"
    assert "risk_reservation_id" not in command.guards.model_dump()
    assert "risk_snapshot_id" not in command.guards.model_dump()
    assert verify_execution_command(command, secret=SECRET)


def test_a2_is_exactly_the_frozen_serial_30_symbol_lineage() -> None:
    executor_id = uuid4()
    commands = build_shadow_acceptance_commands(
        _request(executor_id, phase="A2"),
        executor=_executor(executor_id),
        snapshot=_snapshot(executor_id),
        signing_secret=SECRET,
        signing_key_id="acceptance-test.v1",
    )

    assert len(commands) == 30
    assert (
        tuple(
            (command.source.canonical_symbol, command.source.broker_symbol)
            for command in commands
            if isinstance(command.source, ShadowAcceptanceSource)
        )
        == _pairs()
    )


def test_manifest_contains_identity_and_lineage_but_no_credentials_or_account() -> None:
    executor_id = uuid4()
    request = _request(executor_id)
    executor = _executor(executor_id)
    commands = build_shadow_acceptance_commands(
        request,
        executor=executor,
        snapshot=_snapshot(executor_id),
        signing_secret=SECRET,
        signing_key_id="acceptance-test.v1",
    )

    manifest = acceptance_manifest(request, executor=executor, commands=commands)
    serialized = str(manifest).lower()

    assert manifest["acceptance_run_id"] == request.acceptance_run_id
    assert manifest["executor_id"] == str(executor_id)
    for forbidden in (
        "account_id",
        "account_number",
        "login_hash",
        "executor_token",
        "signing_secret",
        "verification_key",
        "risk_reservation_id",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize("mode", ["DEMO", "LIVE"])
def test_acceptance_contract_rejects_non_shadow_modes(mode: str) -> None:
    executor_id = uuid4()
    command = build_shadow_acceptance_commands(
        _request(executor_id),
        executor=_executor(executor_id),
        snapshot=_snapshot(executor_id),
        signing_secret=SECRET,
        signing_key_id="acceptance-test.v1",
    )[0]
    unsigned = command.model_dump(mode="python", exclude={"signature"})
    unsigned["executor_binding"]["execution_mode"] = mode

    with pytest.raises(ValidationError, match="SHADOW_ACCEPTANCE requires SHADOW"):
        sign_execution_command(unsigned, secret=SECRET, key_id="acceptance-test.v1")


def test_acceptance_contract_rejects_risk_reservation_injection() -> None:
    executor_id = uuid4()
    command = build_shadow_acceptance_commands(
        _request(executor_id),
        executor=_executor(executor_id),
        snapshot=_snapshot(executor_id),
        signing_secret=SECRET,
        signing_key_id="acceptance-test.v1",
    )[0]
    unsigned = command.model_dump(mode="python", exclude={"signature"})
    unsigned["guards"]["risk_reservation_id"] = "fake-reservation"

    with pytest.raises(ValidationError, match="risk_reservation_id"):
        sign_execution_command(unsigned, secret=SECRET, key_id="acceptance-test.v1")


def test_request_rejects_expired_or_overlong_authority_windows() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="acceptance TTL"):
        ShadowAcceptanceRequest(
            acceptance_run_id="acceptance-expired",
            phase="A1",
            executor_id=uuid4(),
            issued_at_utc=now,
            expires_at_utc=now - timedelta(seconds=1),
        )
    with pytest.raises(ValidationError, match="acceptance TTL"):
        ShadowAcceptanceRequest(
            acceptance_run_id="acceptance-too-long",
            phase="A1",
            executor_id=uuid4(),
            issued_at_utc=now,
            expires_at_utc=now + timedelta(hours=1),
        )


def test_builder_rejects_symbol_universe_drift() -> None:
    executor_id = uuid4()
    snapshot = _snapshot(executor_id)
    snapshot = snapshot.model_copy(update={"symbols": snapshot.symbols[:-1]})

    with pytest.raises(ShadowAcceptanceError, match="frozen 30-symbol"):
        build_shadow_acceptance_commands(
            _request(executor_id),
            executor=_executor(executor_id),
            snapshot=snapshot,
            signing_secret=SECRET,
            signing_key_id="acceptance-test.v1",
        )


def test_builder_rejects_an_executor_identity_mismatch() -> None:
    executor_id = uuid4()
    executor = _executor(uuid4())

    with pytest.raises(ShadowAcceptanceError, match="executor identity"):
        build_shadow_acceptance_commands(
            _request(executor_id),
            executor=executor,
            snapshot=_snapshot(executor_id),
            signing_secret=SECRET,
            signing_key_id="acceptance-test.v1",
        )


def test_acceptance_authority_does_not_import_the_strategy_promotion_path() -> None:
    source = Path(__import__("execution.mt5_shadow_acceptance", fromlist=["__file__"]).__file__).read_text(
        encoding="utf-8"
    )

    assert "mt5_command_promotion" not in source
    assert "promote_final_signal_to_command" not in source
