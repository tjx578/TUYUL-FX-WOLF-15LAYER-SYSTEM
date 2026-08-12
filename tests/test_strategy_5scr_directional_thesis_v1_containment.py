"""Static and runtime containment gates for inert P4 infrastructure."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from contracts.strategy_5scr_directional_thesis_v1 import (
    ClosedCandleAuthorityRefV1,
    DirectionalThesisEvidenceV1,
    DirectionalThesisV1,
    H1StructureProofV1,
    M15StructuralProofV1,
    PressureDirectionAuthorityV1,
    RouteDirectionAuthorizationV1,
)
from storage.strategy_5scr_directional_thesis_v1_repository import (
    DIRECTIONAL_THESIS_V1_SHADOW_ONLY_FLAG,
    DIRECTIONAL_THESIS_V1_WRITER_FLAG,
    DirectionalThesisV1RuntimeConfig,
)

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    ROOT / "contracts" / "strategy_5scr_directional_thesis_v1.py",
    ROOT / "analysis" / "strategy_5scr_directional_thesis_v1.py",
    ROOT / "analysis" / "strategy_5scr_structural_proof_provider_v1.py",
    ROOT / "storage" / "strategy_5scr_directional_thesis_v1_repository.py",
)
P4_MODULES = frozenset(
    {
        "contracts.strategy_5scr_directional_thesis_v1",
        "analysis.strategy_5scr_directional_thesis_v1",
        "analysis.strategy_5scr_structural_proof_provider_v1",
        "storage.strategy_5scr_directional_thesis_v1_repository",
    }
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


def test_p4_has_no_execution_box_tradeplan_risk_command_or_ea_dependency() -> None:
    forbidden_prefixes = (
        "execution",
        "services.trade",
        "contracts.mt5_execution_protocol",
        "contracts.strategy_5scr_pressure",
        "storage.strategy_5scr_risk_reservation_repository",
        "storage.strategy_5scr_final_signal_outbox",
    )
    imported = set().union(*(_imports(path) for path in RUNTIME_FILES))

    assert not any(
        module == prefix or module.startswith(prefix + ".") for module in imported for prefix in forbidden_prefixes
    )


def test_p4_contracts_expose_no_downstream_or_broker_authority() -> None:
    forbidden_fields = {
        "execution_box_id",
        "tradeplan_id",
        "tradeplan_candidate_id",
        "entry",
        "entry_price",
        "stop_loss",
        "structural_sl",
        "take_profit",
        "tp1",
        "risk_reservation_id",
        "execution_campaign_id",
        "execution_command_id",
        "broker_order_id",
        "broker_deal_id",
        "broker_position_id",
        "filled_volume",
        "lot_size",
    }
    contracts = (
        ClosedCandleAuthorityRefV1,
        PressureDirectionAuthorityV1,
        RouteDirectionAuthorizationV1,
        DirectionalThesisEvidenceV1,
        H1StructureProofV1,
        M15StructuralProofV1,
        DirectionalThesisV1,
    )

    for contract in contracts:
        assert forbidden_fields.isdisjoint(contract.model_fields), contract.__name__
        if "execution_authority" in contract.model_fields:
            assert contract.model_fields["execution_authority"].default is False
    assert DirectionalThesisV1.model_fields["valid_for_execution"].default is False


def test_p4_runtime_defaults_off_and_requires_shadow_mode() -> None:
    config = DirectionalThesisV1RuntimeConfig.from_env({})

    assert config.enabled is False
    assert config.shadow_only is True
    config.validate()
    DirectionalThesisV1RuntimeConfig.from_env(
        {
            DIRECTIONAL_THESIS_V1_WRITER_FLAG: "true",
            DIRECTIONAL_THESIS_V1_SHADOW_ONLY_FLAG: "true",
        }
    ).validate()
    with pytest.raises(RuntimeError, match="SHADOW_ONLY_REQUIRED"):
        DirectionalThesisV1RuntimeConfig.from_env(
            {
                DIRECTIONAL_THESIS_V1_WRITER_FLAG: "true",
                DIRECTIONAL_THESIS_V1_SHADOW_ONLY_FLAG: "false",
            }
        ).validate()


def test_p4_has_no_production_consumer_or_runtime_wiring() -> None:
    allowed_p5_consumers = {
        (
            "analysis/strategy_5scr_execution_box_v1.py",
            "contracts.strategy_5scr_directional_thesis_v1",
        ),
        (
            "storage/strategy_5scr_execution_box_v1_repository.py",
            "contracts.strategy_5scr_directional_thesis_v1",
        ),
        (
            "storage/strategy_5scr_execution_box_v1_repository.py",
            "storage.strategy_5scr_directional_thesis_v1_repository",
        ),
        (
            "analysis/strategy_5scr_tradeplan_candidate_v2.py",
            "contracts.strategy_5scr_directional_thesis_v1",
        ),
        (
            "storage/strategy_5scr_tradeplan_candidate_v2_repository.py",
            "storage.strategy_5scr_directional_thesis_v1_repository",
        ),
    }
    consumers: list[tuple[str, str]] = []
    runtime_paths = {path.resolve() for path in RUNTIME_FILES}
    for root_name in ("analysis", "api", "contracts", "core", "execution", "services", "storage"):
        production_root = ROOT / root_name
        if not production_root.exists():
            continue
        for path in production_root.rglob("*.py"):
            if path.resolve() in runtime_paths:
                continue
            source = path.read_text(encoding="utf-8")
            if not any(module in source for module in P4_MODULES):
                continue
            imports = _imports(path)
            for module in sorted(P4_MODULES & imports):
                consumers.append((path.relative_to(ROOT).as_posix(), module))

    assert set(consumers) == allowed_p5_consumers


def test_p4_does_not_change_railway_or_mql5_surface() -> None:
    p4_names = (
        "strategy_5scr_directional_thesis_v1",
        "strategy_5scr_structural_proof_provider_v1",
        "20260812_02_5scr_directional_thesis_v1",
    )
    forbidden_roots = (ROOT / "railway", ROOT / "mql5", ROOT / "mt5", ROOT / "ea")
    matches: list[str] = []
    for directory in forbidden_roots:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and any(name in path.name.lower() for name in p4_names):
                matches.append(path.relative_to(ROOT).as_posix())

    assert matches == []
