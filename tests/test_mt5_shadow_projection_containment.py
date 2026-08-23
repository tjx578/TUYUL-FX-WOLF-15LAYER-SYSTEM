"""Static containment for the manual C2-projection -> C3 SHADOW path."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from execution.execution_plane_flags import ExecutionPlaneFlags
from execution.mt5_shadow_projection_operator_wiring import (
    C3ShadowProjectionNotReadyError,
    C3ShadowProjectionOperatorAuthorityV1,
)

ROOT = Path(__file__).resolve().parents[1]
WIRING = ROOT / "execution" / "mt5_shadow_projection_operator_wiring.py"
PROMOTION = ROOT / "execution" / "mt5_shadow_projection_command_promotion.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_new_shadow_projection_path_has_no_legacy_risk_authority_calls() -> None:
    tree = ast.parse(_source(WIRING))
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    called_attributes = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "contracts.strategy_5scr_risk_reservation" not in imported_modules
    assert "storage.strategy_5scr_risk_reservation_repository" not in imported_modules
    assert "execution.mt5_risk_command_producer" not in imported_modules
    assert {"reserve_parent", "produce_next"}.isdisjoint(called_attributes)


def test_new_path_contains_no_ordersend_or_broker_api_call() -> None:
    source = _source(WIRING) + "\n" + _source(PROMOTION)

    assert re.search(r"\bOrderSend\s*\(", source) is None
    assert re.search(r"\border_send\s*\(", source, flags=re.IGNORECASE) is None
    assert "MetaTrader5" not in source


def test_no_service_or_api_runner_imports_manual_operator_wiring() -> None:
    consumers: list[Path] = []
    needle = "mt5_shadow_projection_operator_wiring"
    for folder in (ROOT / "services", ROOT / "api"):
        for path in folder.rglob("*.py"):
            if needle in _source(path):
                consumers.append(path.relative_to(ROOT))

    assert consumers == []


def test_operator_wiring_requires_real_risk_and_order_send_flags_off() -> None:
    authority = C3ShadowProjectionOperatorAuthorityV1(
        pg=object(),  # type: ignore[arg-type]
        flags=ExecutionPlaneFlags(
            execution_enabled=True,
            signed_command_bridge_enabled=True,
            execution_command_producer_enabled=True,
            risk_reservation_enabled=True,
            ea_command_delivery_enabled=True,
        ),
        environ={
            "EXECUTOR_COMMAND_SIGNING_SECRET": "x" * 32,
            "EXECUTOR_COMMAND_SIGNING_KEY_ID": "test.v1",
        },
    )

    try:
        authority._require_process_authority(new_issuance=True)
    except C3ShadowProjectionNotReadyError as exc:
        assert str(exc) == "C3_REAL_RISK_RESERVATION_MUST_REMAIN_DISABLED"
    else:  # pragma: no cover - explicit fail-closed assertion
        raise AssertionError("real risk reservation flag was accepted")


def test_schema_migrations_pin_all_broker_authority_flags_false() -> None:
    projection = _source(ROOT / "storage" / "migrations" / "versions" / "20260813_03_5scr_shadow_risk_projection_v1.py")
    issuance = _source(ROOT / "storage" / "migrations" / "versions" / "20260813_04_mt5_shadow_projection_command_v1.py")

    for source in (projection, issuance):
        normalized = " ".join(source.split()).lower()
        for field in (
            "execution_authority",
            "capital_reserved",
            "broker_side_effect_allowed",
            "order_send_eligible",
        ):
            assert f"{field} is false" in normalized or f"{field}=false" in normalized
