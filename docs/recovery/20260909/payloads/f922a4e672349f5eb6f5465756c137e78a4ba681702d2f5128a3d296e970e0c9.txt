from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest

from contracts.mt5_execution_protocol import ExecutorMode
from execution.mt5_demo_canary_authority_packet import (
    DemoCanaryAuthorityPacketV1,
    command_content_sha256_from_fields,
    emitted_command_content_sha256,
)
from execution.mt5_engineering_demo_canary import EngineeringDemoCanaryRequest, build_engineering_demo_canary_command
from tests.test_mt5_engineering_demo_canary import SECRET, _executor, _snapshot

NOW = datetime(2026, 9, 5, 1, 0, tzinfo=UTC)
COMMAND_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _packet_values() -> dict[str, object]:
    values: dict[str, object] = {
        "authority_packet_id": "d0-control-v3",
        "canary_id": "d0-control-v3",
        "approved_by": "operator-fixture",
        "approved_at_utc": NOW - timedelta(seconds=2),
        "command_id": COMMAND_ID,
        "idempotency_key": "acct-demo:engineering-demo-canary:d0-control-v3:PLACE_MARKET",
        "executor_id": UUID("99999999-9999-4999-8999-999999999999"),
        "expected_account_snapshot_id": "d0-snapshot",
        "account_reference": "acct-demo",
        "broker_server": "Broker-Demo",
        "canonical_symbol": "EURUSD",
        "broker_symbol": "EURUSD",
        "side": "BUY",
        "order_type": "BUY",
        "volume": Decimal("0.01"),
        "entry_price": Decimal("1.10000"),
        "stop_loss": Decimal("1.09500"),
        "take_profit": Decimal("1.11000"),
        "issued_at_utc": NOW - timedelta(seconds=1),
        "expires_at_utc": NOW + timedelta(seconds=89),
        "max_spread_points": 30,
        "max_price_drift_points": 20,
        "max_slippage_points": 20,
        "magic_number": 150016,
        "order_check_max": 2,
        "order_send_max": 1,
        "child_allowed": False,
        "automatic_retry": False,
        "max_commands": 1,
        "issuer_source_revision": "132a428106bcc9e9c3e4303f48d6075a77b8a6ab",
    }
    values["command_content_sha256"] = command_content_sha256_from_fields(values)
    return values


def test_frozen_packet_command_id_reaches_signed_command() -> None:
    packet = DemoCanaryAuthorityPacketV1.model_validate(_packet_values())
    executor = _executor()
    snapshot = _snapshot()
    executor["executor_id"] = str(packet.executor_id)
    executor["account_id"] = packet.account_reference
    executor["broker_server"] = packet.broker_server
    snapshot = snapshot.model_copy(
        update={
            "snapshot_id": packet.expected_account_snapshot_id,
            "executor_id": packet.executor_id,
            "account_id": packet.account_reference,
        }
    )
    request = EngineeringDemoCanaryRequest(
        canary_id=packet.canary_id,
        command_id=packet.command_id,
        idempotency_key=packet.idempotency_key,
        executor_id=packet.executor_id,
        approved_account_id=packet.account_reference,
        approved_broker_server=packet.broker_server,
        approved_canonical_symbol=packet.canonical_symbol,
        approved_broker_symbol=packet.broker_symbol,
        expected_account_snapshot_id=packet.expected_account_snapshot_id,
        side=packet.side,
        volume=float(packet.volume),
        entry_price=float(packet.entry_price),
        stop_loss=float(packet.stop_loss),
        take_profit=float(packet.take_profit),
        max_spread_points=packet.max_spread_points,
        max_price_drift_points=packet.max_price_drift_points,
        max_slippage_points=packet.max_slippage_points,
        magic_number=packet.magic_number,
        issued_at_utc=packet.issued_at_utc,
        expires_at_utc=packet.expires_at_utc,
    )
    command = build_engineering_demo_canary_command(
        request,
        executor=executor,
        snapshot=snapshot,
        signing_secret=SECRET,
        signing_key_id="fixture-key",
    )
    assert command.command_id == COMMAND_ID
    assert command.idempotency_key == packet.idempotency_key
    assert command.order is not None and command.order.magic == packet.magic_number
    assert emitted_command_content_sha256(command) == packet.command_content_sha256
    tampered_order = command.order.model_copy(update={"entry_price": command.order.entry_price + 0.0001})
    assert (
        emitted_command_content_sha256(command.model_copy(update={"order": tampered_order}))
        != packet.command_content_sha256
    )
    assert command.executor_binding.execution_mode is ExecutorMode.DEMO


def test_control_migration_is_single_head_and_contains_all_ledgers() -> None:
    path = Path(__file__).parents[1] / "storage/migrations/versions/20260905_01_d0_canary_control_capabilities.py"
    source = path.read_text(encoding="utf-8")
    assert 'down_revision = "20260823_01"' in source
    for table in (
        "engineering_demo_canary_authority_packets",
        "direct_broker_reconciliation_receipts",
        "executor_mode_transition_authority_packets",
        "executor_mode_transition_receipts",
    ):
        assert table in source
    assert "BEFORE UPDATE OR DELETE" in source


def test_demo_ea_static_broker_call_limits_remain_bounded() -> None:
    source = (Path(__file__).parents[1] / "ea_interface/wolf15_executor/Wolf15_DumbExecutor_Demo.mq5").read_text(
        encoding="utf-8"
    )
    executable = "\n".join(line.split("//", 1)[0] for line in source.splitlines())
    assert executable.count("OrderCheck(") <= 2
    assert executable.count("OrderSend(") <= 1
    assert "automatic_retry" not in executable.lower()


@pytest.mark.parametrize("forbidden", ("--side", "--volume", "--entry-price", "--stop-loss", "--take-profit"))
def test_frozen_cli_does_not_accept_mutable_trade_parameters(forbidden: str) -> None:
    from scripts.issue_mt5_engineering_demo_canary import build_parser

    parser = build_parser()
    subparsers = cast(Any, next(action for action in parser._actions if action.dest == "operation"))
    frozen = subparsers.choices["issue-frozen"]
    assert forbidden not in frozen._option_string_actions
