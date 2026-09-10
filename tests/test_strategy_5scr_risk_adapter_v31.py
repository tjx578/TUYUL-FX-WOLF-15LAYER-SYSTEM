from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from uuid import UUID

import pytest
from pydantic import ValidationError

from contracts.strategy_5scr_risk_adapter_v31 import ParentSizingRequestV31, ParentSizingResultV31
from risk.strategy_5scr_risk_adapter_v31 import parent_sizing_request_hash_v31, size_parent_v31
from tests.test_strategy_5scr_net_geometry_v31 import NOW, request_data


def data(direction="BUY"):
    return {
        "profile": "TEST_ONLY",
        "entry_role": "PARENT",
        "tradeplan_id": "fixture-plan-001",
        "tradeplan_revision": 1,
        "thesis_id": "fixture-thesis-001",
        "campaign_id": "fixture-campaign-001",
        "expected_account_id": "fixture-account",
        "expected_executor_id": UUID(int=1),
        "broker_symbol": "EURUSD.a",
        "tick_value_currency": "USD",
        "tick_value_model_id": "ACCOUNT_CURRENCY_PER_LOT_TEST_V1",
        "evaluated_at": NOW,
        "snapshot": {
            "snapshot_id": "fixture-snapshot",
            "captured_at_utc": NOW,
            "executor_id": UUID(int=1),
            "account_id": "fixture-account",
            "currency": "USD",
            "balance": 1000,
            "equity": 1030,
            "floating_pnl": 30,
            "used_margin": 0,
            "free_margin": 1030,
            "margin_mode": "HEDGING",
            "trade_allowed": True,
            "autotrading_enabled": True,
            "symbols": [
                {
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
            ],
        },
        "geometry": request_data(direction=direction, cost_ticks=1),
        "policy": {
            "profile": "TEST_ONLY",
            "policy_id": "FIXTURE_RISK_V31",
            "policy_hash": "sha256:" + "2" * 64,
            "account_currency": "USD",
            "risk_fraction": "0.0123",
            "maximum_account_open_risk_fraction": "0.03",
            "snapshot_max_age_seconds": 20,
            "risk_state_max_age_seconds": 10,
            "equity_tolerance_usd": "0.01",
            "volume_limit_behavior": "REJECT_ABOVE_MAX",
        },
        "account_committed_and_reserved_risk_usd": "0",
        "campaign_committed_and_reserved_risk_usd": "0",
        "risk_state_evidence_hash": "sha256:" + "3" * 64,
        "risk_state_captured_at": NOW,
    }


def evaluate(payload):
    request = ParentSizingRequestV31.model_validate(payload)
    pinned = parent_sizing_request_hash_v31(request)
    return size_parent_v31(request, verify_inputs=lambda _, digest: digest == pinned)


def fraction(amount):
    return Fraction(amount.numerator, amount.denominator)


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_geometry_to_parent_sizing_exact_cost_and_step_oracle(direction):
    payload = data(direction)
    result = evaluate(payload)
    assert result.status == "SIZED_TEST_ONLY"
    volume = fraction(result.volume)
    entry = Fraction(result.candidate_entry)
    geometry = payload["geometry"]
    costs = sum(map(Fraction, geometry["costs"]["loss"].values()))
    loss_per_lot = (abs(entry - Fraction(geometry["stop_price"])) + costs) / Fraction(geometry["tick_size"])
    budget = Fraction("12.3")
    assert fraction(result.parent_risk_budget_usd) == budget
    assert fraction(result.planned_loss_usd) == volume * loss_per_lot <= budget
    assert (volume + Fraction("0.01")) * loss_per_lot > budget
    assert (volume / Fraction("0.01")).denominator == 1
    assert fraction(result.net_reward_usd) >= Fraction("1.5") * fraction(result.planned_loss_usd)
    assert result.capital_reservation_authority is result.execution_authority is False


@pytest.mark.parametrize(
    "change,reason",
    [
        ("account", "RISK_ACCOUNT_EXECUTOR_MISMATCH"),
        ("executor", "RISK_ACCOUNT_EXECUTOR_MISMATCH"),
        ("currency", "RISK_ACCOUNT_CURRENCY_UNSUPPORTED"),
        ("clock", "RISK_GEOMETRY_CLOCK_MISMATCH"),
        ("stale", "RISK_SNAPSHOT_STALE_OR_FUTURE"),
        ("future", "RISK_SNAPSHOT_STALE_OR_FUTURE"),
        ("disabled", "RISK_TRADE_DISABLED"),
        ("equity", "RISK_EQUITY_INCONSISTENT"),
        ("missing_spec", "RISK_SYMBOL_BINDING_MISSING_OR_AMBIGUOUS"),
        ("duplicate_spec", "RISK_SYMBOL_BINDING_MISSING_OR_AMBIGUOUS"),
        ("tick", "RISK_GEOMETRY_SPEC_MISMATCH"),
        ("profit_tick", "RISK_MONETARY_NET_RR_INSUFFICIENT"),
        ("campaign_risk", "RISK_PARENT_CAMPAIGN_ALREADY_HAS_EXPOSURE"),
        ("account_risk", "RISK_ACCOUNT_CAPACITY_EXCEEDED"),
        ("min_volume", "RISK_VOLUME_BELOW_MINIMUM"),
        ("max_volume", "RISK_VOLUME_ABOVE_MAXIMUM"),
        ("costs", "RISK_GEOMETRY_COST_EVIDENCE_UNBOUND"),
    ],
)
def test_risk_adapter_rejects_incomplete_or_conflicting_inputs(change, reason):
    payload = data()
    snapshot = payload["snapshot"]
    spec = snapshot["symbols"][0]
    if change == "account":
        snapshot["account_id"] = "different"
    elif change == "executor":
        snapshot["executor_id"] = UUID(int=2)
    elif change == "currency":
        snapshot["currency"] = "EUR"
    elif change == "clock":
        payload["evaluated_at"] += timedelta(seconds=1)
    elif change == "stale":
        snapshot["captured_at_utc"] -= timedelta(seconds=21)
    elif change == "future":
        snapshot["captured_at_utc"] += timedelta(microseconds=1)
    elif change == "disabled":
        snapshot["trade_allowed"] = False
    elif change == "equity":
        snapshot["equity"] = 999
    elif change == "missing_spec":
        snapshot["symbols"] = []
    elif change == "duplicate_spec":
        snapshot["symbols"].append(deepcopy(spec))
    elif change == "tick":
        spec["tick_size"] = 0.0001
    elif change == "profit_tick":
        spec["tick_value_profit"] = 0.25
    elif change == "campaign_risk":
        payload["campaign_committed_and_reserved_risk_usd"] = "0.01"
    elif change == "account_risk":
        payload["account_committed_and_reserved_risk_usd"] = "29"
    elif change == "min_volume":
        spec["volume_min"] = 1
    elif change == "max_volume":
        spec["volume_max"] = 0.02
    elif change == "costs":
        payload["geometry"]["costs"] = None
    result = evaluate(payload)
    assert result.reason == reason
    assert result.status != "SIZED_TEST_ONLY"
    assert result.volume is None and result.capital_reservation_authority is False


def test_floating_profit_cannot_increase_parent_budget():
    payload = data()
    original = evaluate(payload)
    payload["snapshot"].update(equity=2000, floating_pnl=1000, free_margin=2000)
    assert evaluate(payload).parent_risk_budget_usd == original.parent_risk_budget_usd
    assert evaluate(payload).volume == original.volume


def test_input_verifier_required_and_exact_true():
    request = ParentSizingRequestV31.model_validate(data())
    assert size_parent_v31(request, verify_inputs=None).reason == "RISK_INPUT_VERIFIER_UNBOUND"
    assert size_parent_v31(request, verify_inputs=lambda *_: 1).reason == "RISK_INPUT_VERIFICATION_REJECTED"
    assert size_parent_v31(request, verify_inputs=lambda *_: False).reason == "RISK_INPUT_VERIFICATION_REJECTED"


def test_verifier_cannot_mutate_bound_snapshot():
    def mutate(request, digest):
        request.snapshot.balance = 5000
        return True

    assert (
        size_parent_v31(ParentSizingRequestV31.model_validate(data()), verify_inputs=mutate).reason
        == "RISK_INPUT_CHANGED_DURING_VERIFICATION"
    )


def test_decimal_context_cannot_change_risk_size_or_cap():
    payload = data()
    expected = evaluate(payload)
    with localcontext() as context:
        context.prec = 5
        assert evaluate(payload) == expected


@pytest.mark.parametrize("field", ["risk_fraction", "snapshot_max_age_seconds", "equity_tolerance_usd"])
def test_no_default_risk_numbers(field):
    payload = data()
    del payload["policy"][field]
    with pytest.raises(ValidationError):
        ParentSizingRequestV31.model_validate(payload)


def test_cannot_relabel_profile_or_grant_execution_authority():
    payload = data()
    payload["profile"] = "DEMO"
    with pytest.raises(ValidationError):
        ParentSizingRequestV31.model_validate(payload)
    result = evaluate(data()).model_dump()
    result["execution_authority"] = True
    with pytest.raises(ValidationError):
        ParentSizingResultV31.model_validate(result)


@pytest.mark.parametrize("offset", [-11, 1])
def test_capacity_state_has_its_own_bound_freshness(offset):
    payload = data()
    payload["risk_state_captured_at"] += timedelta(seconds=offset)
    assert evaluate(payload).reason == "RISK_CAPACITY_STATE_STALE_OR_FUTURE"


@pytest.mark.parametrize("field", ["risk_state_evidence_hash", "tick_value_currency", "tick_value_model_id"])
def test_missing_capacity_or_tick_denomination_binding_rejected(field):
    payload = data()
    del payload[field]
    with pytest.raises(ValidationError):
        ParentSizingRequestV31.model_validate(payload)


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_nonfinite_account_input_cannot_produce_sizing(value):
    payload = data()
    payload["snapshot"]["balance"] = value
    with pytest.raises(ValueError):
        evaluate(payload)


@pytest.mark.parametrize("change", ["policy", "revision", "exposure", "geometry", "snapshot"])
def test_input_receipt_binds_strategy_policy_geometry_account_and_exposure(change):
    payload = data()
    pinned = parent_sizing_request_hash_v31(ParentSizingRequestV31.model_validate(payload))
    if change == "policy":
        payload["policy"]["risk_fraction"] = "0.01"
    elif change == "revision":
        payload["tradeplan_revision"] = 2
    elif change == "exposure":
        payload["account_committed_and_reserved_risk_usd"] = "1"
    elif change == "geometry":
        payload["geometry"]["costs"]["source_hash"] = "sha256:" + "4" * 64
    elif change == "snapshot":
        payload["snapshot"]["snapshot_id"] = "different-snapshot"
    result = size_parent_v31(
        ParentSizingRequestV31.model_validate(payload), verify_inputs=lambda _, digest: digest == pinned
    )
    assert result.reason == "RISK_INPUT_VERIFICATION_REJECTED"


def test_exact_account_capacity_boundary_has_no_epsilon_allowance():
    payload = data()
    sizing = evaluate(payload)
    remainder = Fraction(30) - fraction(sizing.planned_loss_usd)
    remaining = Decimal(remainder.numerator) / Decimal(remainder.denominator)
    payload["account_committed_and_reserved_risk_usd"] = remaining
    assert evaluate(payload).status == "SIZED_TEST_ONLY"
    payload["account_committed_and_reserved_risk_usd"] = remaining + Decimal("0.000000000001")
    assert evaluate(payload).reason == "RISK_ACCOUNT_CAPACITY_EXCEEDED"


def test_snapshot_and_risk_state_exact_age_limits_are_accepted():
    payload = data()
    payload["snapshot"]["captured_at_utc"] -= timedelta(seconds=20)
    payload["risk_state_captured_at"] -= timedelta(seconds=10)
    assert evaluate(payload).status == "SIZED_TEST_ONLY"
