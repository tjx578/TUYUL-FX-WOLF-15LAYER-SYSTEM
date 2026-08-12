"""Containment gates for inert, shadow-only TradePlanCandidate V2 infrastructure."""

from __future__ import annotations

import ast
from pathlib import Path

from contracts.strategy_5scr_tradeplan_candidate_v2 import (
    TradePlanCandidateBuildEvidenceV2,
    TradePlanCandidateV2,
)

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    ROOT / "contracts" / "strategy_5scr_tradeplan_candidate_v2.py",
    ROOT / "analysis" / "strategy_5scr_tradeplan_candidate_v2.py",
    ROOT / "storage" / "strategy_5scr_tradeplan_candidate_v2_repository.py",
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


def test_p6_has_no_legacy_risk_command_or_ea_dependency() -> None:
    forbidden = (
        "analysis.strategy_5scr_pressure_to_tradeplan",
        "contracts.strategy_5scr_pressure",
        "contracts.strategy_5scr_risk_reservation",
        "storage.strategy_5scr_risk_reservation_repository",
        "contracts.mt5_execution_protocol",
        "analysis.signal_json_emitter",
        "analysis.signal_execution_gates",
        "execution",
        "services.trade",
    )
    imported = set().union(*(_imports(path) for path in RUNTIME_FILES))
    assert not any(module == item or module.startswith(item + ".") for module in imported for item in forbidden)


def test_p6_exposes_plan_geometry_but_no_broker_or_risk_authority() -> None:
    expected = {
        "tradeplan_id",
        "execution_box_id",
        "candidate_price",
        "target_authority",
        "stop_authority",
        "gross_rr",
    }
    forbidden = {
        "risk_reservation_id",
        "risk_snapshot_id",
        "account_id",
        "account_number",
        "executor_id",
        "broker_symbol",
        "reserved_volume",
        "volume",
        "lot_size",
        "signal_id",
        "execution_command_id",
        "broker_order_id",
        "broker_deal_id",
        "broker_position_id",
        "filled_volume",
    }
    assert expected <= set(TradePlanCandidateV2.model_fields)
    assert forbidden.isdisjoint(TradePlanCandidateV2.model_fields)
    assert forbidden.isdisjoint(TradePlanCandidateBuildEvidenceV2.model_fields)
    assert TradePlanCandidateV2.model_fields["execution_authority"].default is False
    assert TradePlanCandidateV2.model_fields["valid_for_execution"].default is False
    assert TradePlanCandidateV2.model_fields["next_required_stage"].default == "RISK_RESERVATION"


def test_p6_has_no_existing_production_consumer() -> None:
    module_names = (
        "contracts.strategy_5scr_tradeplan_candidate_v2",
        "analysis.strategy_5scr_tradeplan_candidate_v2",
        "storage.strategy_5scr_tradeplan_candidate_v2_repository",
    )
    runtime = {path.resolve() for path in RUNTIME_FILES}
    # P6's own migration is allowed to name its tables; it is schema, not a
    # runtime consumer.  All other production call sites must remain absent.
    runtime.add((ROOT / "storage" / "migrations" / "versions" / "20260813_01_5scr_tradeplan_candidate_v2.py").resolve())
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
    assert consumers == []


def test_p6_runtime_defaults_off_and_shadow_only() -> None:
    from storage.strategy_5scr_tradeplan_candidate_v2_repository import TradePlanCandidateV2RuntimeConfig

    config = TradePlanCandidateV2RuntimeConfig.from_env({})
    assert config.enabled is False
    assert config.shadow_only is True
    config.validate()


def test_p6_does_not_modify_railway_or_mql5_runtime_artifacts() -> None:
    for path in RUNTIME_FILES:
        source = path.read_text(encoding="utf-8")
        assert "OrderSend" not in source
        assert "execution_commands" not in source
        assert "strategy_5scr_risk_reservations" not in source
        assert "strategy_5scr_final_signal_outbox" not in source
