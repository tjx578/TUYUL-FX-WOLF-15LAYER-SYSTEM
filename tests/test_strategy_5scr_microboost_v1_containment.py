"""Static containment gates for inert Microboost P2 infrastructure."""

from __future__ import annotations

import ast
from pathlib import Path

from contracts.strategy_5scr_microboost_pulse import MicroboostPulseEvent, MicroboostState

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    ROOT / "analysis" / "strategy_5scr_microboost_pulse_engine.py",
    ROOT / "storage" / "strategy_5scr_microboost_v1_repository.py",
)
REPOSITORY_MODULE = "storage.strategy_5scr_microboost_v1_repository"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_p2_has_no_risk_command_ea_or_tradeplan_dependency() -> None:
    forbidden_prefixes = (
        "execution",
        "services.trade",
        "storage.strategy_5scr_risk_reservation_repository",
        "contracts.strategy_5scr_risk_reservation",
    )
    imported = set().union(*(_imports(path) for path in RUNTIME_FILES))

    assert not any(
        module == prefix or module.startswith(prefix + ".") for module in imported for prefix in forbidden_prefixes
    )


def test_p2_contract_exposes_no_execution_or_thesis_authority() -> None:
    forbidden_fields = {
        "risk_reservation_id",
        "tradeplan_candidate_id",
        "execution_command_id",
        "execution_campaign_id",
        "directional_thesis_id",
        "broker_order_id",
        "broker_deal_id",
        "broker_position_id",
    }

    assert forbidden_fields.isdisjoint(MicroboostPulseEvent.model_fields)
    assert forbidden_fields.isdisjoint(MicroboostState.model_fields)
    assert MicroboostPulseEvent.model_fields["execution_authority"].default is False
    assert MicroboostState.model_fields["execution_authority"].default is False


def test_microboost_repository_has_no_production_consumer() -> None:
    consumers: list[str] = []
    for root_name in ("analysis", "api", "contracts", "core", "execution", "services", "storage"):
        production_root = ROOT / root_name
        if not production_root.exists():
            continue
        for path in production_root.rglob("*.py"):
            if path in RUNTIME_FILES:
                continue
            if REPOSITORY_MODULE in path.read_text(encoding="utf-8"):
                consumers.append(path.relative_to(ROOT).as_posix())

    assert consumers == []
