"""StructuralGeometryV31 acceptance — A4 (RATIFIED 2026-09-27), owner implementation GO 2026-09-27.

Every positive case runs on the REAL native lineage of the ExecutionBoxV31 acceptance suite: a real FROZEN box
built from a real thesis, structural proof, PressureRange and canonical StructuralTarget selection.
"""

from __future__ import annotations

import ast
import inspect
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_structural_geometry_v31 import (
    build_structural_geometry_v31,
    geometry_revision_fact_v31,
    requires_geometry_reevaluation_v31,
    structural_sl_anchor_v31,
)
from contracts.strategy_5scr_structural_geometry_v31 import (
    GEOMETRY_POLICIES_V31,
    GEOMETRY_REASON_CODES_V31,
    GeometryReasonCode,
    GrossRRV31,
    StructuralGeometryDecisionV31,
    StructuralGeometryMaterialV31,
    StructuralGeometryV31,
    material_geometry_hash_v31,
)
from tests.test_strategy_5scr_execution_box_v31 import BOX_DECISION, _built, _lineage, _selection, _with_material

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    ROOT / "contracts" / "strategy_5scr_structural_geometry_v31.py",
    ROOT / "analysis" / "strategy_5scr_structural_geometry_v31.py",
)
POLICY = {
    "BREAK_RETEST": ("5scr.geometry-policy.break-retest", "v1"),
    "BREAKOUT_ACCEPTANCE": ("5scr.geometry-policy.breakout-acceptance", "v1"),
}
CASES = (
    ("BUY", "BREAK_RETEST", "RETEST"),
    ("SELL", "BREAK_RETEST", "RETEST"),
    ("BUY", "BREAKOUT_ACCEPTANCE", "ACCEPTANCE"),
    ("SELL", "BREAKOUT_ACCEPTANCE", "ACCEPTANCE"),
)


def _inputs(direction: str = "BUY", route: str = "BREAK_RETEST", kind: str = "RETEST") -> dict[str, Any]:
    lineage = _lineage(direction, route, kind)
    policy_id, policy_version = POLICY[route]
    return {
        "box": _built(direction, route, kind).version,  # type: ignore[arg-type]
        "box_state": "FROZEN",
        "proof": lineage.proof,
        "target_selection": _selection(lineage),
        "geometry_policy_id": policy_id,
        "geometry_policy_version": policy_version,
        "decision_time": BOX_DECISION,
    }


def _geometry(**overrides: Any) -> StructuralGeometryDecisionV31:
    return build_structural_geometry_v31(**{**_inputs(), **overrides})


def _with_target_price(selection: Any, price: str) -> Any:
    data = selection.model_dump()
    data["selected_target"] = {**data["selected_target"], "price": Decimal(price)}
    return type(selection).model_validate(data)


# --- A4-G1 / A4-G2 values on the real lineage --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "interval", "sl", "reference", "tp1", "rr"),
    [
        (CASES[0], ("1.1008", "1.101"), "1.0995", "1.101", "1.1100", Fraction(6)),
        (CASES[1], ("1.1", "1.1002"), "1.1015", "1.1", "1.0900", Fraction(20, 3)),
        (CASES[2], ("1.101", "1.1012"), "1.0995", "1.1012", "1.1100", Fraction(88, 17)),
        (CASES[3], ("1.0995", "1.1"), "1.1015", "1.0995", "1.0900", Fraction(19, 4)),
    ],
)
def test_ratified_geometry_on_the_real_lineage(case, interval, sl, reference, tp1, rr):
    decision = build_structural_geometry_v31(**_inputs(*case))
    assert (decision.status, decision.cause, decision.net_rr_status) == (
        "STRUCTURAL_GEOMETRY_READY",
        None,
        "NET_RR_NOT_EVALUATED",
    )
    geometry = decision.geometry
    assert geometry is not None
    m = geometry.material
    assert (geometry.entry_interval_low, geometry.entry_interval_high) == tuple(Decimal(v) for v in interval)
    assert (m.structural_sl_anchor, m.structural_sl, m.rr_reference_entry, m.tp1) == (
        Decimal(sl),
        Decimal(sl),
        Decimal(reference),
        Decimal(tp1),
    )
    assert geometry.gross_rr.as_fraction() == rr
    assert (geometry.gross_rr.numerator, geometry.gross_rr.denominator) == (rr.numerator, rr.denominator)


def test_sl_anchor_is_the_reference_candle_extreme_and_never_l_or_the_completion_candle():
    for direction, route, kind in CASES:
        proof = _lineage(direction, route, kind).proof
        reference, _, completion = proof.m15_source_candles
        anchor = structural_sl_anchor_v31(proof, direction)
        assert anchor == Decimal(str(reference.low if direction == "BUY" else reference.high))
        assert anchor != Decimal(str(proof.m15_break_evidence.level))
        assert anchor not in {Decimal(str(completion.low)), Decimal(str(completion.high))}


def test_no_buffer_the_sl_equals_its_anchor_and_the_contract_refuses_a_moved_sl():
    geometry = _geometry().geometry
    assert geometry is not None and geometry.material.structural_sl == geometry.material.structural_sl_anchor
    moved = {**geometry.material.model_dump(), "structural_sl": Decimal("1.0994")}
    with pytest.raises(ValidationError, match="STRUCTURAL_SL_MUST_EQUAL_ITS_ANCHOR"):
        StructuralGeometryV31.model_validate({**geometry.model_dump(), "material": moved})


def test_tp1_is_the_selected_target_price_exactly_with_no_tick_or_spread_offset():
    selection = _with_target_price(_inputs()["target_selection"], "1.110037")
    geometry = _geometry(target_selection=selection).geometry
    assert geometry is not None
    assert geometry.material.tp1 == Decimal("1.110037")
    assert geometry.gross_rr.as_fraction() == Fraction(Decimal("0.009037")) / Fraction(Decimal("0.0015"))


def test_rr_reference_entry_is_the_worst_case_box_edge_and_the_contract_refuses_another():
    geometry = _geometry().geometry
    assert geometry is not None and geometry.material.rr_reference_entry == geometry.entry_interval_high
    better = {**geometry.material.model_dump(), "rr_reference_entry": geometry.entry_interval_low}
    with pytest.raises(ValidationError, match="RR_REFERENCE_ENTRY_NOT_THE_WORST_CASE_BOX_EDGE"):
        StructuralGeometryV31.model_validate({**geometry.model_dump(), "material": better})


# --- Q-A4-2: ROUTE_NO_VALID_ENTRY_DOMAIN with a mandatory, risk-first cause ------------------------------------


def test_non_positive_risk_is_no_valid_entry_domain_with_the_risk_cause():
    box = _with_material(_inputs()["box"], box_low=Decimal("1.0990"), box_high=Decimal("1.0995"))
    decision = _geometry(box=box)
    assert (decision.status, decision.cause, decision.geometry) == (
        "ROUTE_NO_VALID_ENTRY_DOMAIN",
        "STRUCTURAL_RISK_NON_POSITIVE",
        None,
    )


def test_non_positive_reward_is_no_valid_entry_domain_with_the_reward_cause():
    for price in ("1.1010", "1.1005"):  # reward == 0, reward < 0
        decision = _geometry(target_selection=_with_target_price(_inputs()["target_selection"], price))
        assert (decision.status, decision.cause) == ("ROUTE_NO_VALID_ENTRY_DOMAIN", "STRUCTURAL_REWARD_NON_POSITIVE")


def test_a_setup_failing_both_carries_the_risk_cause():
    box = _with_material(_inputs()["box"], box_low=Decimal("1.0990"), box_high=Decimal("1.0994"))
    decision = _geometry(box=box, target_selection=_with_target_price(_inputs()["target_selection"], "1.0980"))
    assert (decision.status, decision.cause) == ("ROUTE_NO_VALID_ENTRY_DOMAIN", "STRUCTURAL_RISK_NON_POSITIVE")


def test_the_cause_is_mandatory_exactly_for_no_valid_entry_domain():
    with pytest.raises(ValidationError, match="CAUSE_REQUIRED_IFF_ROUTE_NO_VALID_ENTRY_DOMAIN"):
        StructuralGeometryDecisionV31(status="ROUTE_NO_VALID_ENTRY_DOMAIN", cause=None, geometry=None)
    with pytest.raises(ValidationError, match="CAUSE_REQUIRED_IFF_ROUTE_NO_VALID_ENTRY_DOMAIN"):
        StructuralGeometryDecisionV31(
            status="EXECUTION_BOX_NOT_FROZEN", cause="STRUCTURAL_RISK_NON_POSITIVE", geometry=None
        )
    with pytest.raises(ValidationError, match="GEOMETRY_PRESENT_IFF_READY"):
        StructuralGeometryDecisionV31(status="STRUCTURAL_GEOMETRY_READY", cause=None, geometry=None)


# --- prerequisites ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["BUILDING", "SUPERSEDED", "INVALIDATED"])
def test_only_a_frozen_box_has_geometry(state):
    assert _geometry(box_state=state).status == "EXECUTION_BOX_NOT_FROZEN"


def test_a_box_frozen_after_decision_time_has_no_geometry():
    freeze = _inputs()["box"].lineage.freeze_evidence_close_utc
    assert _geometry(decision_time=freeze - timedelta(seconds=1)).status == "EXECUTION_BOX_NOT_FROZEN"


@pytest.mark.parametrize(
    ("policy_id", "version"),
    [
        ("5scr.geometry-policy.unknown", "v1"),
        ("5scr.geometry-policy.break-retest", "v2"),
        ("5scr.geometry-policy.breakout-acceptance", "v1"),  # a real policy, but for the other route
    ],
)
def test_an_unknown_or_foreign_policy_is_rejected(policy_id, version):
    assert _geometry(geometry_policy_id=policy_id, geometry_policy_version=version).status == "GEOMETRY_POLICY_UNKNOWN"


def test_there_is_no_default_policy():
    parameters = inspect.signature(build_structural_geometry_v31).parameters
    for name in ("geometry_policy_id", "geometry_policy_version", "decision_time", "box_state"):
        assert parameters[name].default is inspect.Parameter.empty, name
    assert set(GEOMETRY_POLICIES_V31) == {POLICY["BREAK_RETEST"], POLICY["BREAKOUT_ACCEPTANCE"]}
    for policy in GEOMETRY_POLICIES_V31.values():
        assert (policy.sl_buffer, policy.gross_rr_minimum, policy.runtime_status) == (None, None, "RUNTIME_DISABLED")


def _selection_with(**changes: Any) -> Any:
    selection = _inputs()["target_selection"]
    return type(selection).model_validate({**selection.model_dump(), **changes})


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "NO_ELIGIBLE_TARGET", "selected_target": None},
        {"status": "NO_ELIGIBLE_TARGET"},  # a target is present but the selection did not select it
        {"status": "REJECTED"},
        {"thesis_direction": "SELL"},  # the same thesis, the wrong direction
        {"decision_time": BOX_DECISION + timedelta(seconds=1)},  # future evidence
        {"canonical_symbol": "GBPUSD"},
    ],
)
def test_an_unselected_misbound_or_future_target_is_unavailable(changes):
    assert _geometry(target_selection=_selection_with(**changes)).status == "STRUCTURAL_TARGET_UNAVAILABLE"


def test_a_selection_for_another_thesis_in_the_same_direction_is_unavailable():
    foreign = _selection(_lineage("BUY", "BREAKOUT_ACCEPTANCE", "ACCEPTANCE"))
    assert foreign.thesis_direction == "BUY" and foreign.canonical_symbol == "EURUSD"
    assert foreign.strategy_thesis_id != _inputs()["box"].strategy_thesis_id
    assert _geometry(target_selection=foreign).status == "STRUCTURAL_TARGET_UNAVAILABLE"


def test_the_contract_refuses_a_policy_of_another_route():
    geometry = _geometry().geometry
    assert geometry is not None
    foreign_policy = {
        **geometry.material.model_dump(),
        "geometry_policy_id": "5scr.geometry-policy.breakout-acceptance",
    }
    material = StructuralGeometryMaterialV31.model_validate(foreign_policy)
    forged = {
        **geometry.model_dump(),
        "material": material,
        "material_geometry_hash": material_geometry_hash_v31(material),
    }
    with pytest.raises(ValidationError, match="GEOMETRY_POLICY_UNKNOWN"):
        StructuralGeometryV31.model_validate(forged)


def test_the_sl_needs_the_exact_proof_the_box_was_frozen_from():
    assert _geometry(proof=_lineage("SELL").proof).status == "STRUCTURAL_SL_UNAVAILABLE"
    acceptance_proof = _lineage("BUY", "BREAKOUT_ACCEPTANCE", "ACCEPTANCE").proof
    assert _geometry(proof=acceptance_proof).status == "STRUCTURAL_SL_UNAVAILABLE"


def test_a_reference_candle_not_named_by_the_break_evidence_is_no_sl_authority():
    proof = _inputs()["proof"]
    wrong = {
        **proof.m15_break_evidence.model_dump(),
        "reference_candle_id": proof.m15_source_candles[1].candle_evidence_id,
    }
    forged = proof.model_construct(**{**dict(proof), "m15_break_evidence": type(proof.m15_break_evidence)(**wrong)})
    assert structural_sl_anchor_v31(forged, "BUY") is None


# --- A4-10 / A4-15 revision ------------------------------------------------------------------------------------------


def test_material_hash_is_deterministic_and_prices_hash_by_value():
    first = _geometry().geometry
    second = _geometry().geometry
    assert first is not None and second is not None
    assert first.material_geometry_hash == second.material_geometry_hash
    padded = StructuralGeometryMaterialV31.model_validate({**first.material.model_dump(), "tp1": Decimal("1.110000")})
    assert material_geometry_hash_v31(padded) == first.material_geometry_hash


def test_a_different_target_at_the_same_price_is_still_a_material_change():
    before = _geometry().geometry
    selection = _inputs()["target_selection"]
    data = selection.model_dump()
    data["selected_target"] = {**data["selected_target"], "target_id": "other-structural-target"}
    after = _geometry(target_selection=type(selection).model_validate(data)).geometry
    assert before is not None and after is not None
    assert after.material.tp1 == before.material.tp1
    assert geometry_revision_fact_v31(before, after) == "STRUCTURAL_GEOMETRY_MATERIAL_CHANGE"


def test_a_target_change_is_a_geometry_material_change_that_keeps_the_box_version():
    before = _geometry().geometry
    after = _geometry(target_selection=_with_target_price(_inputs()["target_selection"], "1.1200")).geometry
    assert before is not None and after is not None
    assert after.material.box_version == before.material.box_version
    assert after.lineage.material_box_hash == before.lineage.material_box_hash
    assert geometry_revision_fact_v31(before, after) == "STRUCTURAL_GEOMETRY_MATERIAL_CHANGE"
    assert geometry_revision_fact_v31(before, before) is None


def test_a_new_box_version_is_a_geometry_material_change():
    box = _inputs()["box"]
    before = _geometry().geometry
    successor = type(box).model_validate(
        {
            **_with_material(box, box_low=Decimal("1.1009")).model_dump(),
            "box_version": 2,
            "previous_box_version": 1,
            "previous_material_box_hash": box.material_box_hash,
        }
    )
    after = _geometry(box=successor).geometry
    assert before is not None and after is not None
    assert after.material.box_version == 2
    assert geometry_revision_fact_v31(before, after) == "STRUCTURAL_GEOMETRY_MATERIAL_CHANGE"


def test_lineage_only_changes_never_move_the_material_hash():
    geometry = _geometry().geometry
    assert geometry is not None
    relabelled = {**geometry.lineage.model_dump(), "target_selection_decision_price_hash": "sha256:" + "0" * 64}
    moved = StructuralGeometryV31.model_validate({**geometry.model_dump(), "lineage": relabelled})
    assert geometry_revision_fact_v31(geometry, moved) is None


def test_revision_is_never_compared_across_theses():
    buy, sell = _geometry().geometry, build_structural_geometry_v31(**_inputs("SELL")).geometry
    assert buy is not None and sell is not None
    with pytest.raises(ValueError, match="GEOMETRY_REVISION_ACROSS_DIFFERENT_THESES"):
        geometry_revision_fact_v31(buy, sell)


def test_reevaluation_obligations():
    assert (
        requires_geometry_reevaluation_v31(box_changed=False, target_fact="TARGET_UNCHANGED", sl_evidence_changed=False)
        is False
    )
    for kwargs in (
        {"box_changed": True, "target_fact": "TARGET_UNCHANGED", "sl_evidence_changed": False},
        {"box_changed": False, "target_fact": "TARGET_MATERIAL_CHANGE", "sl_evidence_changed": False},
        {"box_changed": False, "target_fact": "TARGET_UNCHANGED", "sl_evidence_changed": True},
    ):
        assert requires_geometry_reevaluation_v31(**kwargs) is True
    with pytest.raises(ValueError, match="UNKNOWN_TARGET_REVISION_FACT"):
        requires_geometry_reevaluation_v31(box_changed=False, target_fact="SOMETHING", sl_evidence_changed=False)


# --- A4-11 numeric representation ------------------------------------------------------------------------------------


def test_gross_rr_is_an_exact_reduced_rational_and_never_a_float():
    with pytest.raises(ValidationError, match="GROSS_RR_NOT_REDUCED"):
        GrossRRV31(numerator=12, denominator=2)
    with pytest.raises(ValidationError):
        GrossRRV31(numerator=1.5, denominator=1)  # type: ignore[arg-type]
    geometry = _geometry().geometry
    assert geometry is not None
    dumped = geometry.model_dump(mode="json")
    assert dumped["gross_rr"] == {"numerator": 6, "denominator": 1}
    forged = {**geometry.model_dump(), "gross_rr": {"numerator": 7, "denominator": 1}}
    with pytest.raises(ValidationError, match="GROSS_RR_NOT_EXACT"):
        StructuralGeometryV31.model_validate(forged)


# --- A4-07 / A4-13 boundary --------------------------------------------------------------------------------------


def test_reason_vocabulary_is_exactly_a4_13():
    assert (
        GEOMETRY_REASON_CODES_V31
        == get_args(GeometryReasonCode)
        == (
            "STRUCTURAL_GEOMETRY_READY",
            "STRUCTURAL_SL_UNAVAILABLE",
            "STRUCTURAL_TARGET_UNAVAILABLE",
            "ROUTE_NO_VALID_ENTRY_DOMAIN",
            "STRUCTURAL_RISK_NON_POSITIVE",
            "STRUCTURAL_REWARD_NON_POSITIVE",
            "STRUCTURAL_GEOMETRY_MATERIAL_CHANGE",
            "EXECUTION_BOX_NOT_FROZEN",
            "GEOMETRY_POLICY_UNKNOWN",
        )
    )


def test_no_broker_cost_volume_or_order_field_and_no_authority():
    forbidden = {
        "spread", "bid", "ask", "tick_size", "tick_value", "stops_level", "freeze_level", "commission", "slippage",
        "swap", "volume", "lot", "margin", "order_type", "order_price", "net_rr", "candidate_entry",
        "gross_rr_minimum_value", "buffer",
    }  # fmt: skip
    for model in (StructuralGeometryV31, StructuralGeometryMaterialV31, StructuralGeometryDecisionV31):
        assert forbidden.isdisjoint(model.model_fields), model.__name__
    geometry = _geometry().geometry
    assert geometry is not None
    assert (geometry.risk_authority, geometry.execution_authority, geometry.valid_for_execution) == (
        False,
        False,
        False,
    )
    assert geometry.runtime_status == "RUNTIME_DISABLED"


def _imports(path: Path) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_no_broker_risk_execution_cost_or_legacy_imports():
    forbidden_prefixes = (
        "execution",
        "services",
        "risk",
        "ea_interface",
        "ops",
        "storage",
        "contracts.mt5_execution_protocol",
        "contracts.strategy_5scr_execution_policy",
        "contracts.strategy_5scr_risk",
        "contracts.strategy_5scr_candidate_handoff_v31",
        "analysis.strategy_5scr_net_geometry_v31",
        "analysis.strategy_5scr_tradeplan_candidate_v2",
        "analysis.strategy_5scr_target_selection_v31",
        "analysis.formulas",
    )
    imported = set().union(*(_imports(path) for path in SOURCES))
    assert not any(m == p or m.startswith(p + ".") for m in imported for p in forbidden_prefixes), imported
    for path in SOURCES:
        assert "quantize" not in path.read_text(encoding="utf-8"), path.name
