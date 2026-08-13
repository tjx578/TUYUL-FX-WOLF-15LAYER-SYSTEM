"""Containment gates for inert P5 infrastructure."""

from __future__ import annotations

import ast
from pathlib import Path

from contracts.strategy_5scr_execution_box_v1 import ExecutionBoxEvidenceV1, ExecutionBoxV1
from storage.strategy_5scr_execution_box_v1_repository import ExecutionBoxV1RuntimeConfig

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    ROOT / "contracts" / "strategy_5scr_execution_box_v1.py",
    ROOT / "analysis" / "strategy_5scr_execution_box_v1.py",
    ROOT / "storage" / "strategy_5scr_execution_box_v1_repository.py",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_p5_has_no_tradeplan_risk_command_or_ea_dependency() -> None:
    forbidden = (
        "contracts.strategy_5scr_pressure",
        "storage.strategy_5scr_risk_reservation_repository",
        "contracts.mt5_execution_protocol",
        "execution",
        "services.trade",
    )
    imported = set().union(*(_imports(path) for path in RUNTIME_FILES))
    assert not any(module == item or module.startswith(item + ".") for module in imported for item in forbidden)


def test_p5_exposes_geometry_but_no_trade_or_broker_authority() -> None:
    expected_geometry = {"execution_box_id", "box_low", "box_high", "route_type"}
    forbidden = {
        "fill_price",
        "entry",
        "entry_price",
        "stop_loss",
        "structural_sl",
        "take_profit",
        "tp1",
        "risk_reward",
        "lot_size",
        "risk_reservation_id",
        "tradeplan_id",
        "execution_command_id",
        "broker_order_id",
        "broker_deal_id",
        "broker_position_id",
        "filled_volume",
    }
    assert expected_geometry <= set(ExecutionBoxV1.model_fields)
    assert forbidden.isdisjoint(ExecutionBoxV1.model_fields)
    assert forbidden.isdisjoint(ExecutionBoxEvidenceV1.model_fields)
    assert ExecutionBoxV1.model_fields["execution_authority"].default is False
    assert ExecutionBoxV1.model_fields["valid_for_execution"].default is False


def test_p5_has_no_existing_production_consumer() -> None:
    module_names = (
        "contracts.strategy_5scr_execution_box_v1",
        "analysis.strategy_5scr_execution_box_v1",
        "storage.strategy_5scr_execution_box_v1_repository",
    )
    runtime = {path.resolve() for path in RUNTIME_FILES}
    consumers: list[str] = []
    for root in ("analysis", "api", "contracts", "core", "execution", "services", "storage"):
        directory = ROOT / root
        if not directory.exists():
            continue
        for path in directory.rglob("*.py"):
            if path.resolve() in runtime:
                continue
            source = path.read_text(encoding="utf-8")
            if any(name in source for name in module_names):
                consumers.append(path.relative_to(ROOT).as_posix())
    assert consumers == [
        "analysis/strategy_5scr_tradeplan_candidate_v2.py",
        "storage/strategy_5scr_tradeplan_candidate_v2_repository.py",
    ]


def test_p5_runtime_defaults_off_and_shadow_only() -> None:
    config = ExecutionBoxV1RuntimeConfig.from_env({})
    assert config.enabled is False
    assert config.shadow_only is True
    config.validate()
