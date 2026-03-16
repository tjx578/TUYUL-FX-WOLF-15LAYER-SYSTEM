"""Focused registry tests for execution.state_machine."""

from __future__ import annotations

from execution.state_machine import OrderState, StateMachineRegistry


def test_registry_provides_independent_per_symbol_state() -> None:
    registry = StateMachineRegistry()
    registry.reset_all()

    eurusd = registry.get("EURUSD")
    usdjpy = registry.get("USDJPY")

    eurusd.set_pending({"order_id": "EU-1"})
    assert eurusd.state == OrderState.PENDING_ACTIVE
    assert usdjpy.state == OrderState.IDLE


def test_registry_snapshot_all_contains_each_symbol_state() -> None:
    registry = StateMachineRegistry()
    registry.reset_all()

    registry.get("EURUSD").set_pending({"order_id": "EU-1"})
    registry.get("USDJPY").set_pending({"order_id": "UJ-1"})
    registry.get("USDJPY").set_cancelled("manual")

    snap = registry.snapshot_all()
    assert snap["EURUSD"]["state"] == "PENDING_ACTIVE"
    assert snap["USDJPY"]["state"] == "CANCELLED"


def test_registry_backward_compat_default_symbol_path() -> None:
    registry = StateMachineRegistry()
    registry.reset_all()
    registry._init()

    registry.set_pending({"order_id": "DEF-1"})
    assert registry.is_pending()
    assert registry.snapshot()["state"] == "PENDING_ACTIVE"
