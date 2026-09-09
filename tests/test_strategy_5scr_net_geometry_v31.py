from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_net_geometry_v31 import solve_net_geometry_v31
from contracts.strategy_5scr_net_geometry_v31 import NetGeometryRequestV31, NetGeometryResultV31

NOW = datetime(2026, 9, 9, tzinfo=UTC)
H = "sha256:" + "1" * 64


def request_data(direction="BUY", symbol="EURUSD", cost_ticks=0):
    # Deliberately different pip/unit conventions, supplied explicitly per symbol.
    digits, tick, unit, anchor, instrument = {
        "EURUSD": (5, Decimal("0.00001"), Decimal("0.0001"), Decimal("1.1"), "FX"),
        "USDJPY": (3, Decimal("0.001"), Decimal("0.01"), Decimal("150"), "FX"),
        "XAUUSD": (2, Decimal("0.05"), Decimal("0.1"), Decimal("2500"), "METAL"),
    }[symbol]
    sign = 1 if direction == "BUY" else -1
    interval = {"low": anchor - 15 * tick, "high": anchor + 15 * tick}
    costs = {name: cost_ticks * tick for name in ("spread_price", "commission_price", "slippage_price", "swap_price")}
    return {
        "symbol": symbol,
        "instrument_class": instrument,
        "direction": direction,
        "decision_at": NOW,
        "target_price": anchor + sign * 120 * tick,
        "stop_price": anchor - sign * 50 * tick,
        "target_evidence_hash": H,
        "stop_evidence_hash": H,
        "digits": digits,
        "point": Decimal(1).scaleb(-digits),
        "tick_size": tick,
        "target_unit_size": unit,
        "structural_interval": interval,
        "route_interval": interval,
        "broker_interval": interval,
        "policy": {
            "profile": "TEST_ONLY",
            "policy_id": f"TEST_{symbol}_NET_V1",
            "policy_hash": H,
            "instrument_class": instrument,
            "minimum_target_units": "10",
            "minimum_net_rr": "1.5",
        },
        "costs": {
            "symbol": symbol,
            "source_hash": H,
            "cost_model_id": "EXPLICIT_SCENARIO_PRICE_COSTS_TEST_V1",
            "captured_at": NOW - timedelta(seconds=1),
            "valid_until": NOW + timedelta(seconds=1),
            "profit": costs.copy(),
            "loss": costs.copy(),
        },
    }


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
@pytest.mark.parametrize("symbol", ["EURUSD", "USDJPY", "XAUUSD"])
@pytest.mark.parametrize("cost_ticks", [0, 1, 5, 20])
def test_feasible_interval_matches_exhaustive_tick_oracle(direction, symbol, cost_ticks):
    data = request_data(direction, symbol, cost_ticks)
    request = NetGeometryRequestV31.model_validate(data)
    before = request.model_dump_json()
    result = solve_net_geometry_v31(request)
    tick, target, stop = map(Fraction, (request.tick_size, request.target_price, request.stop_price))
    profit_cost = sum(map(Fraction, data["costs"]["profit"].values()))
    loss_cost = sum(map(Fraction, data["costs"]["loss"].values()))
    interval = request.structural_interval
    legal = []
    for index in range(int(Fraction(interval.low) / tick), int(Fraction(interval.high) / tick) + 1):
        entry = index * tick
        reward, risk = abs(target - entry), abs(entry - stop)
        directional = stop < entry < target if direction == "BUY" else target < entry < stop
        if (
            directional
            and reward >= 10 * Fraction(request.target_unit_size)
            and reward - profit_cost >= Fraction("1.5") * (risk + loss_cost)
        ):
            legal.append(entry)
    if legal:
        assert result.status == "FEASIBLE_TEST_ONLY"
        assert Fraction(result.feasible_interval.low) == min(legal)
        assert Fraction(result.feasible_interval.high) == max(legal)
        assert Fraction(result.candidate_entry) == (max(legal) if direction == "BUY" else min(legal))
        assert result.net_rr >= Decimal("1.5")
    else:
        assert result.status == "NO_VALID_ENTRY_DOMAIN"
        assert result.feasible_interval is result.candidate_entry is result.net_rr is None
    assert request.model_dump_json() == before
    assert not any((result.hypothesis_authority, result.capital_reservation_authority, result.execution_authority))


@pytest.mark.parametrize("field,reason", [("policy", "POLICY_UNBOUND"), ("costs", "COST_EVIDENCE_UNBOUND")])
def test_missing_binding_waits(field, reason):
    data = request_data()
    data[field] = None
    assert solve_net_geometry_v31(NetGeometryRequestV31(**data)).reason == reason


@pytest.mark.parametrize("offset", [-2, 1, 2])
def test_cost_time_boundary_is_fail_closed(offset):
    data = request_data()
    data["decision_at"] = NOW + timedelta(seconds=offset)
    assert solve_net_geometry_v31(NetGeometryRequestV31(**data)).reason == "COST_NOT_AS_OF_DECISION"


def test_capture_boundary_is_accepted():
    data = request_data()
    data["decision_at"] = data["costs"]["captured_at"]
    assert solve_net_geometry_v31(NetGeometryRequestV31(**data)).status == "FEASIBLE_TEST_ONLY"


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_gross_rr_pass_does_not_hide_net_rr_failure(direction):
    data = request_data(direction, cost_ticks=10)
    anchor = Decimal("1.1")
    data["route_interval"] = {"low": anchor, "high": anchor}
    assert abs(data["target_price"] - anchor) / abs(anchor - data["stop_price"]) == Decimal("2.4")
    assert solve_net_geometry_v31(NetGeometryRequestV31(**data)).status == "NO_VALID_ENTRY_DOMAIN"


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_exact_boundary_and_one_tick_outside(direction):
    data = request_data(direction)
    data["policy"]["minimum_target_units"] = "1"
    data["target_price"] = Decimal("1.101") if direction == "BUY" else Decimal("1.099")
    data["stop_price"] = Decimal("1.0995") if direction == "BUY" else Decimal("1.1005")
    result = solve_net_geometry_v31(NetGeometryRequestV31(**data))
    assert result.candidate_entry == (Decimal("1.1001") if direction == "BUY" else Decimal("1.0999"))
    assert result.net_rr == Decimal("1.5")
    outside = result.candidate_entry + (1 if direction == "BUY" else -1) * data["tick_size"]
    data["broker_interval"] = {"low": outside, "high": outside}
    assert solve_net_geometry_v31(NetGeometryRequestV31(**data)).status == "NO_VALID_ENTRY_DOMAIN"


def test_cost_scenarios_are_separate_and_hash_is_bound():
    data = request_data()
    first = solve_net_geometry_v31(NetGeometryRequestV31(**data))
    data["costs"]["loss"]["commission_price"] = Decimal("0.0004")
    second = solve_net_geometry_v31(NetGeometryRequestV31(**data))
    assert second.candidate_entry < first.candidate_entry
    assert second.request_hash != first.request_hash


@pytest.mark.parametrize("field,value", [("symbol", "USDJPY"), ("instrument_class", "METAL")])
def test_cross_binding_is_rejected(field, value):
    data = request_data()
    data[field] = value
    assert solve_net_geometry_v31(NetGeometryRequestV31(**data)).status == "WAIT"


@pytest.mark.parametrize("mutation", ["tick", "naive", "negative_cost", "nan", "omitted_cost", "active_profile"])
def test_invalid_inputs_are_not_defaulted(mutation):
    data = request_data()
    if mutation == "tick":
        data["target_price"] += Decimal("0.000001")
    elif mutation == "naive":
        data["decision_at"] = NOW.replace(tzinfo=None)
    elif mutation == "negative_cost":
        data["costs"]["profit"]["swap_price"] = -1
    elif mutation == "nan":
        data["tick_size"] = Decimal("NaN")
    elif mutation == "omitted_cost":
        del data["costs"]["profit"]["swap_price"]
    else:
        data["policy"]["profile"] = "ACTIVE"
    with pytest.raises(ValidationError):
        NetGeometryRequestV31.model_validate(data)


def test_solver_revalidates_model_copy_and_authority_cannot_be_enabled():
    request = NetGeometryRequestV31(**request_data())
    with pytest.raises(ValidationError):
        solve_net_geometry_v31(request.model_copy(update={"tick_size": Decimal(0)}))
    result = solve_net_geometry_v31(request).model_dump()
    result["execution_authority"] = True
    with pytest.raises(ValidationError):
        NetGeometryResultV31.model_validate(result)


def test_decimal_context_does_not_change_tick_selection():
    request = NetGeometryRequestV31(**request_data(cost_ticks=1))
    expected = solve_net_geometry_v31(request)
    with localcontext() as context:
        context.prec = 6
        actual = solve_net_geometry_v31(request)
    assert actual == expected
