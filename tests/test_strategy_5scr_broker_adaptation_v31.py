"""Thin G4 broker/cost adaptation — owner GO 2026-09-27, source/test only.

Positive cases start from the REAL StructuralGeometryV31 of the A4 acceptance suite and end in the EXISTING risk
engine (``size_parent_v31``) to prove the request is consumable without a new engine.
"""

from __future__ import annotations

import ast
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_net_geometry_v31 import solve_net_geometry_v31
from analysis.strategy_5scr_structural_geometry_v31 import build_structural_geometry_v31
from contracts.mt5_execution_protocol import SymbolCapability
from contracts.strategy_5scr_broker_adaptation_v31 import (
    BROKER_ADAPTATION_STATUSES_V31,
    BrokerAdaptationDecisionV31,
    BrokerAdaptationPolicyV31,
    BrokerAdaptationV31,
    BrokerQuoteV31,
)
from contracts.strategy_5scr_net_geometry_v31 import NetCostSnapshotV31
from risk.strategy_5scr_broker_adaptation_v31 import adapt_structural_geometry_v31
from tests.test_strategy_5scr_execution_box_v31 import BOX_DECISION, _with_material
from tests.test_strategy_5scr_structural_geometry_v31 import CASES, _inputs, _selection_with, _with_target_price

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    ROOT / "contracts" / "strategy_5scr_broker_adaptation_v31.py",
    ROOT / "risk" / "strategy_5scr_broker_adaptation_v31.py",
)
NOW = BOX_DECISION
H = "sha256:" + "a" * 64


def _geometry(case: tuple[str, str, str] = CASES[0], **overrides: Any):
    decision = build_structural_geometry_v31(**{**_inputs(*case), **overrides})
    assert decision.geometry is not None, decision.status
    return decision.geometry


def _capability(**changes: Any) -> SymbolCapability:
    values: dict[str, Any] = {
        "canonical_symbol": "EURUSD",
        "broker_symbol": "EURUSD.a",
        "digits": 5,
        "point": 0.00001,
        "tick_size": 0.00001,
        "tick_value_profit": 1,
        "tick_value_loss": 1,
        "volume_min": 0.01,
        "volume_max": 100,
        "volume_step": 0.01,
        "stops_level_points": 0,
        "freeze_level_points": 0,
    }
    return SymbolCapability.model_validate({**values, **changes})


def _quote(**changes: Any) -> BrokerQuoteV31:
    values: dict[str, Any] = {
        "canonical_symbol": "EURUSD",
        "broker_symbol": "EURUSD.a",
        "bid": Decimal("1.10090"),
        "ask": Decimal("1.10095"),
        "observed_at": NOW - timedelta(seconds=1),
        "evidence_hash": "sha256:" + "b" * 64,
    }
    return BrokerQuoteV31.model_validate({**values, **changes})


def _scenario(spread: str = "0.00005", commission: str = "0.00002", slippage: str = "0.00001") -> dict[str, Decimal]:
    return {
        "spread_price": Decimal(spread),
        "commission_price": Decimal(commission),
        "slippage_price": Decimal(slippage),
        "swap_price": Decimal("0"),
    }


def _costs(**changes: Any) -> NetCostSnapshotV31:
    values: dict[str, Any] = {
        "symbol": "EURUSD",
        "source_hash": "sha256:" + "c" * 64,
        "cost_model_id": "EXPLICIT_SCENARIO_PRICE_COSTS_TEST_V1",
        "captured_at": NOW - timedelta(seconds=60),
        "valid_until": NOW + timedelta(seconds=60),
        "profit": _scenario(),
        "loss": _scenario(),
    }
    return NetCostSnapshotV31.model_validate({**values, **changes})


def _policy(**changes: Any) -> BrokerAdaptationPolicyV31:
    values: dict[str, Any] = {
        "profile": "TEST_ONLY",
        "policy_id": "fixture-g4-broker-adaptation",
        "policy_version": "v1",
        "policy_hash": "sha256:" + "d" * 64,
        "instrument_class": "FX",
        "max_quote_age_seconds": 5,
        "minimum_net_rr": Decimal("1.5"),
    }
    return BrokerAdaptationPolicyV31.model_validate({**values, **changes})


def _adapt(**overrides: Any) -> BrokerAdaptationDecisionV31:
    values: dict[str, Any] = {
        "geometry": _geometry(),
        "capability": _capability(),
        "quote": _quote(),
        "costs": _costs(),
        "policy": _policy(),
        "decision_time": NOW,
        **overrides,
    }
    return adapt_structural_geometry_v31(**values)


def _eligible(**overrides: Any) -> BrokerAdaptationV31:
    decision = _adapt(**overrides)
    assert decision.status == "ELIGIBLE_FOR_RISK_ENGINE", decision.reason
    assert decision.adaptation is not None
    return decision.adaptation


# --- executable domain and net RR on the real geometry ---------------------------------------------------------


@pytest.mark.parametrize("case", CASES)
def test_eligible_domain_is_inside_the_box_and_the_open_sl_tp1_interval(case):
    geometry = _geometry(case)
    adaptation = _eligible(geometry=geometry)
    buy = geometry.direction == "BUY"
    assert (adaptation.structural_sl, adaptation.tp1) == (geometry.material.structural_sl, geometry.material.tp1)
    assert geometry.entry_interval_low <= adaptation.executable_domain_low
    assert adaptation.executable_domain_high <= geometry.entry_interval_high
    near, far = (adaptation.structural_sl, adaptation.tp1) if buy else (adaptation.tp1, adaptation.structural_sl)
    assert near < adaptation.executable_domain_low <= adaptation.executable_domain_high < far
    worst = adaptation.executable_domain_high if buy else adaptation.executable_domain_low
    assert adaptation.worst_case_executable_entry == worst
    cost = Fraction(Decimal("0.00008"))
    e, s, t = (Fraction(v) for v in (worst, adaptation.structural_sl, adaptation.tp1))
    reward = (t - e if buy else e - t) - cost
    risk = (e - s if buy else s - e) + cost
    assert adaptation.net_rr.as_fraction() == reward / risk
    # gross RR stays strategy truth, untouched by costs.
    assert adaptation.gross_rr.as_fraction() == geometry.gross_rr.as_fraction()
    assert (adaptation.volume_decided, adaptation.submit_authorized) == (False, False)


def test_q_a4_1_a_box_reaching_past_the_sl_is_cut_at_the_sl_and_the_geometry_is_untouched():
    box = _with_material(_inputs()["box"], box_low=Decimal("1.0990"))
    geometry = _geometry(box=box)
    assert (geometry.entry_interval_low, geometry.material.structural_sl) == (Decimal("1.0990"), Decimal("1.0995"))
    adaptation = _eligible(geometry=geometry)
    assert adaptation.strategy_domain_low == Decimal("1.0995")
    assert adaptation.executable_domain_low == Decimal("1.09951")  # first tick strictly above the SL
    assert adaptation.structural_sl == Decimal("1.0995") and geometry.entry_interval_low == Decimal("1.0990")


def test_stops_and_freeze_distance_shrink_the_domain_and_an_empty_domain_is_no_executable_entry():
    # SL side: 1.0995 + 200 points (0.002) = 1.1015 > box high 1.1010.
    decision = _adapt(capability=_capability(stops_level_points=200))
    assert (decision.status, decision.reason, decision.adaptation) == (
        "NO_EXECUTABLE_ENTRY",
        "EXECUTABLE_DOMAIN_EMPTY",
        None,
    )
    # Freeze level counts like stops level: 1.0995 + 135 points = 1.10085 raises the low edge inside the box.
    shrunk = _eligible(capability=_capability(freeze_level_points=135))
    assert (shrunk.executable_domain_low, shrunk.executable_domain_high) == (Decimal("1.10085"), Decimal("1.1010"))
    assert shrunk.structural_sl == Decimal("1.0995")  # the SL never moves to make room


def test_off_grid_box_edges_are_rounded_inward_never_outward():
    box = _with_material(_inputs()["box"], box_low=Decimal("1.100805"), box_high=Decimal("1.101005"))
    adaptation = _eligible(geometry=_geometry(box=box))
    assert (adaptation.executable_domain_low, adaptation.executable_domain_high) == (
        Decimal("1.10081"),
        Decimal("1.1010"),
    )
    assert Decimal("1.100805") <= adaptation.executable_domain_low
    assert adaptation.executable_domain_high <= Decimal("1.101005")


def test_the_distance_also_applies_from_tp1():
    # TP1 1.1012 − 50 points = 1.1007 < box low 1.1008, while the SL side (1.0995 + 0.0005) does not bind.
    geometry = _geometry(target_selection=_with_target_price(_inputs()["target_selection"], "1.1012"))
    decision = _adapt(geometry=geometry, capability=_capability(stops_level_points=50))
    assert (decision.status, decision.reason) == ("NO_EXECUTABLE_ENTRY", "EXECUTABLE_DOMAIN_EMPTY")


def test_net_rr_is_gated_at_exactly_one_point_five_and_fails_closed_below():
    # reward .009 − c == 1.5 × (.0015 + c)  ⇔  c = .0027 total per scenario.
    exact = _scenario(commission="0.00265", slippage="0")
    adaptation = _eligible(costs=_costs(profit=exact, loss=exact))
    assert adaptation.net_rr.as_fraction() == Fraction(3, 2)
    above = _scenario(commission="0.00266", slippage="0")
    decision = _adapt(costs=_costs(profit=above, loss=above))
    assert (decision.status, decision.adaptation) == ("NET_RR_BELOW_MINIMUM", None)


def test_a_worse_net_rr_never_selects_another_target_or_moves_anything():
    heavy = _scenario(commission="0.01", slippage="0")
    decision = _adapt(costs=_costs(profit=heavy, loss=heavy))
    assert decision.status == "NET_RR_BELOW_MINIMUM"
    assert decision.adaptation is None


# --- broker / cost measurement -----------------------------------------------------------------------------------


def test_an_off_grid_canonical_tp1_is_rejected_never_rounded():
    geometry = _geometry(target_selection=_with_target_price(_inputs()["target_selection"], "1.110037"))
    decision = _adapt(geometry=geometry)
    assert (decision.status, decision.reason) == ("BROKER_PRICE_OFF_TICK_GRID", "CANONICAL_SL_OR_TP1_OFF_TICK_GRID")


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"quote": _quote(observed_at=NOW - timedelta(seconds=6))}, "QUOTE_STALE_OR_FUTURE"),
        ({"quote": _quote(observed_at=NOW + timedelta(seconds=1))}, "QUOTE_STALE_OR_FUTURE"),
        ({"quote": _quote(broker_symbol="EURUSD.b")}, "BROKER_SYMBOL_BINDING_MISMATCH"),
        ({"capability": _capability(canonical_symbol="GBPUSD")}, "BROKER_SYMBOL_BINDING_MISMATCH"),
        ({"capability": _capability(digits=4)}, "BROKER_TICK_GRID_INCOHERENT"),
        ({"capability": _capability(tick_size=0.000015)}, "BROKER_TICK_GRID_INCOHERENT"),
    ],
)
def test_invalid_broker_measurement_fails_closed(overrides, reason):
    decision = _adapt(**overrides)
    assert (decision.status, decision.reason) == ("BROKER_MEASUREMENT_INVALID", reason)


def test_the_exact_quote_age_limit_is_accepted():
    assert _adapt(quote=_quote(observed_at=NOW - timedelta(seconds=5))).status == "ELIGIBLE_FOR_RISK_ENGINE"


@pytest.mark.parametrize(
    "costs",
    [
        _costs(symbol="GBPUSD"),
        _costs(captured_at=NOW + timedelta(seconds=1), valid_until=NOW + timedelta(seconds=60)),
        _costs(captured_at=NOW - timedelta(seconds=60), valid_until=NOW),
    ],
)
def test_cost_evidence_must_be_bound_and_as_of_decision(costs):
    assert _adapt(costs=costs).status == "COST_EVIDENCE_INVALID"


def test_a_cost_model_below_the_measured_spread_is_rejected():
    for side in ("profit", "loss"):
        understated = _costs(**{side: _scenario(spread="0.00004")})
        assert _adapt(costs=understated).status == "COST_SPREAD_UNDERSTATED"


def test_the_policy_has_no_defaults_and_the_net_gate_is_the_canonical_one_point_five():
    assert all(field.is_required() for field in BrokerAdaptationPolicyV31.model_fields.values())
    with pytest.raises(ValidationError, match="MINIMUM_NET_RR_IS_THE_CANONICAL_1_5"):
        _policy(minimum_net_rr=Decimal("1.2"))


# --- the existing risk engine consumes the request unchanged -------------------------------------------------------


def test_the_existing_net_kernel_agrees_with_the_executable_domain_and_worst_case_entry():
    for case in CASES:
        adaptation = _eligible(geometry=_geometry(case))
        solved = solve_net_geometry_v31(adaptation.risk_engine_request)
        assert solved.status == "FEASIBLE_TEST_ONLY", solved.reason
        assert solved.candidate_entry == adaptation.worst_case_executable_entry
        assert solved.feasible_interval is not None
        assert (solved.feasible_interval.low, solved.feasible_interval.high) == (
            adaptation.executable_domain_low,
            adaptation.executable_domain_high,
        )


def test_the_existing_risk_engine_sizes_the_request_and_g4_decides_no_volume():
    from tests.test_strategy_5scr_risk_adapter_v31 import data, evaluate

    adaptation = _eligible()
    payload = data()
    payload["geometry"] = adaptation.risk_engine_request.model_dump()
    payload["evaluated_at"] = NOW
    payload["risk_state_captured_at"] = NOW
    payload["snapshot"]["captured_at_utc"] = NOW
    result = evaluate(payload)
    assert result.status == "SIZED_TEST_ONLY", result.reason
    assert result.candidate_entry == adaptation.worst_case_executable_entry
    assert "volume" not in BrokerAdaptationV31.model_fields


# --- contract boundary -----------------------------------------------------------------------------------------------


def test_the_contract_refuses_a_domain_outside_sl_tp1_a_moved_sl_or_a_net_below_minimum():
    adaptation = _eligible()
    dumped = adaptation.model_dump()
    with pytest.raises(ValidationError, match="EXECUTABLE_DOMAIN_NOT_INSIDE_SL_TP1"):
        BrokerAdaptationV31.model_validate(
            {
                **dumped,
                "structural_sl": dumped["executable_domain_low"],
                "strategy_domain_low": dumped["executable_domain_low"],
            }
        )
    moved_request = {**dumped["risk_engine_request"], "stop_price": Decimal("1.09949")}
    with pytest.raises(ValidationError, match="RISK_ENGINE_REQUEST_MOVED_SL_OR_TP1"):
        BrokerAdaptationV31.model_validate({**dumped, "risk_engine_request": moved_request})
    with pytest.raises(ValidationError, match="NET_RR_BELOW_MINIMUM"):
        BrokerAdaptationV31.model_validate({**dumped, "net_rr": {"numerator": 7, "denominator": 5}})
    with pytest.raises(ValidationError, match="NET_RR_NOT_AT_THE_WORST_CASE_EXECUTABLE_ENTRY"):
        BrokerAdaptationV31.model_validate({**dumped, "worst_case_executable_entry": dumped["executable_domain_low"]})
    with pytest.raises(ValidationError, match="ADAPTATION_PRESENT_IFF_ELIGIBLE"):
        BrokerAdaptationDecisionV31(status="ELIGIBLE_FOR_RISK_ENGINE", reason="x" * 3, adaptation=None)


def test_status_vocabulary_is_closed():
    assert BROKER_ADAPTATION_STATUSES_V31 == (
        "ELIGIBLE_FOR_RISK_ENGINE",
        "NO_EXECUTABLE_ENTRY",
        "NET_RR_BELOW_MINIMUM",
        "BROKER_PRICE_OFF_TICK_GRID",
        "BROKER_MEASUREMENT_INVALID",
        "COST_EVIDENCE_INVALID",
        "COST_SPREAD_UNDERSTATED",
        "BROKER_ADAPTATION_POLICY_INVALID",
    )


def _imports(path: Path) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_no_hidden_numbers_no_new_engine_and_no_execution_path():
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        floats = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, float)]
        assert floats == [], path.name
        ints = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and type(n.value) is int}
        assert ints <= {0, 1, 3, 40, 64, 120, 3600}, (path.name, ints)  # field bounds and digests only
        text = path.read_text(encoding="utf-8")
        for hidden in ("spread_multiplier", "5 *", "* 5", "pip", "default_slippage", "commission_rate"):
            assert hidden not in text, (path.name, hidden)
    forbidden = ("execution", "services", "ea_interface", "ops", "storage", "api", "analysis.formulas")
    imported = set().union(*(_imports(path) for path in SOURCES))
    assert not any(m == p or m.startswith(p + ".") for m in imported for p in forbidden), imported
    assert "risk.strategy_5scr_risk_adapter_v31" not in imported  # G4 hands off; it does not size


def test_a_foreign_selection_never_reaches_g4():
    decision = build_structural_geometry_v31(**{**_inputs(), "target_selection": _selection_with(status="REJECTED")})
    assert decision.geometry is None  # G4 accepts only a READY StructuralGeometryV31
