"""Source-contract tests for the D0 DEMO heartbeat symbol scope."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from contracts.mt5_execution_protocol import AccountSnapshotV1

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "ea_interface" / "wolf15_executor" / "Wolf15_DumbExecutor_Demo.mq5"
SHADOW = ROOT / "ea_interface" / "wolf15_executor" / "Wolf15_DumbExecutor_Shadow.mq5"
COMMAND_REPO = ROOT / "execution" / "mt5_command_repository.py"


def _body(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    finish = source.index(end, begin)
    return source[begin:finish]


def test_demo_heartbeat_uses_approved_symbol_helper_not_full_universe() -> None:
    source = DEMO.read_text(encoding="utf-8")
    heartbeat = _body(source, "bool SendDemoHeartbeat()", "bool ValidateDemoCommand")
    assert "BuildDemoApprovedSymbolJson()" in heartbeat
    assert "BuildSymbolsJson()" not in heartbeat


def test_demo_helper_is_scoped_to_exact_approved_pair() -> None:
    source = DEMO.read_text(encoding="utf-8")
    helper = _body(source, "string BuildDemoApprovedSymbolJson()", "bool RegisterDemoExecutor")
    assert "InpApprovedCanonicalSymbol" in helper
    assert "InpApprovedBrokerSymbol" in helper
    assert "SymbolPairIndex(canonical_symbol, broker_symbol) < 0" in helper
    assert "SymbolSelect(broker_symbol, true)" in helper
    assert "SymbolIsSynchronized(broker_symbol)" in helper
    assert "W15_SYMBOL_COUNT" not in helper
    assert "W15_CANONICAL_SYMBOLS" not in helper
    assert "W15_BROKER_SYMBOLS" not in helper


def test_demo_helper_fails_closed_when_approved_symbol_is_not_ready() -> None:
    source = DEMO.read_text(encoding="utf-8")
    helper = _body(source, "string BuildDemoApprovedSymbolJson()", "bool RegisterDemoExecutor")
    for token in (
        "!SymbolSelect(broker_symbol, true) || !SymbolIsSynchronized(broker_symbol)",
        "SYMBOL_TRADE_MODE_FULL",
        "point <= 0.0",
        "tick_size <= 0.0",
        "tick_value_profit <= 0.0",
        "tick_value_loss <= 0.0",
        "volume_min <= 0.0",
        "volume_max < volume_min",
        "volume_step <= 0.0",
    ):
        assert token in helper
    assert helper.count('return "";') >= 4


def test_demo_helper_serializes_complete_symbol_capability_shape() -> None:
    source = DEMO.read_text(encoding="utf-8")
    helper = _body(source, "string BuildDemoApprovedSymbolJson()", "bool RegisterDemoExecutor")
    for field in (
        "canonical_symbol",
        "broker_symbol",
        "digits",
        "point",
        "tick_size",
        "tick_value_profit",
        "tick_value_loss",
        "volume_min",
        "volume_max",
        "volume_step",
        "stops_level_points",
        "freeze_level_points",
        "expiration_modes",
    ):
        assert field in helper


def test_demo_helper_has_no_execution_primitive() -> None:
    source = DEMO.read_text(encoding="utf-8")
    helper = _body(source, "string BuildDemoApprovedSymbolJson()", "bool RegisterDemoExecutor")
    assert "OrderSend(" not in helper
    assert "OrderCheck(" not in helper


def test_shadow_keeps_full_universe_builder() -> None:
    shadow = SHADOW.read_text(encoding="utf-8")
    helper = _body(shadow, "string BuildSymbolsJson()", "bool RegisterExecutor")
    assert "for(int index = 0; index < W15_SYMBOL_COUNT; index++)" in helper
    assert "Symbol capability unavailable" in helper
    assert "BuildDemoApprovedSymbolJson" not in shadow


def test_account_snapshot_contract_accepts_one_symbol_capability() -> None:
    snapshot = AccountSnapshotV1.model_validate(
        {
            "snapshot_id": "snap-source-test",
            "captured_at_utc": datetime.now(UTC),
            "executor_id": UUID("53d3c627-acfe-448b-b9cd-d3cb059e1b46"),
            "account_id": "demo-account-ref",
            "currency": "USD",
            "balance": 1000.0,
            "equity": 1000.0,
            "floating_pnl": 0.0,
            "used_margin": 0.0,
            "free_margin": 1000.0,
            "margin_level_pct": None,
            "margin_mode": "HEDGING",
            "trade_allowed": True,
            "autotrading_enabled": False,
            "open_positions": [],
            "pending_orders": [],
            "broker_ledger_reconciled": False,
            "symbols": [
                {
                    "canonical_symbol": "EURUSD",
                    "broker_symbol": "EURUSD",
                    "digits": 5,
                    "point": 0.00001,
                    "tick_size": 0.00001,
                    "tick_value_profit": 1.0,
                    "tick_value_loss": 1.0,
                    "volume_min": 0.01,
                    "volume_max": 100.0,
                    "volume_step": 0.01,
                    "stops_level_points": 0,
                    "freeze_level_points": 0,
                    "expiration_modes": ["SPECIFIED"],
                }
            ],
        }
    )
    assert len(snapshot.symbols) == 1
    assert snapshot.symbols[0].canonical_symbol == "EURUSD"
    assert snapshot.symbols[0].broker_symbol == "EURUSD"


def test_engineering_canary_gate_requires_exactly_one_matching_capability() -> None:
    source = COMMAND_REPO.read_text(encoding="utf-8")
    assert "if len(symbol_capabilities) != 1" in source
    assert "item.canonical_symbol == command.order.canonical_symbol" in source
    assert "item.broker_symbol == command.order.broker_symbol" in source
    assert "engineering canary order is not bound to exact minimum symbol volume" in source
