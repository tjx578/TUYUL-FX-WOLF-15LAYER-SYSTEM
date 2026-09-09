"""Connect fixed-target net geometry to exact USD parent sizing in TEST_ONLY.

The verifier must bind the complete request to its account, strategy, policy,
cost and exposure sources. A true callback in a fixture is not live authority.
"""

import hashlib
import json
from collections.abc import Callable
from decimal import Decimal
from fractions import Fraction

from analysis.strategy_5scr_net_geometry_v31 import solve_net_geometry_v31
from contracts.strategy_5scr_risk_adapter_v31 import (
    ExactAmountV31,
    ParentSizingRequestV31,
    ParentSizingResultV31,
    risk_amount_fraction_v31,
)


def parent_sizing_request_hash_v31(request: ParentSizingRequestV31) -> str:
    encoded = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def _exact(value: Fraction) -> ExactAmountV31:
    return ExactAmountV31(numerator=value.numerator, denominator=value.denominator)


def size_parent_v31(
    request: ParentSizingRequestV31,
    *,
    verify_inputs: Callable[[ParentSizingRequestV31, str], bool] | None,
) -> ParentSizingResultV31:
    request = ParentSizingRequestV31.model_validate(request.model_dump())
    digest = parent_sizing_request_hash_v31(request)

    def reject(reason: str, status="WAIT"):
        return ParentSizingResultV31(status=status, reason=reason, request_hash=digest)

    if verify_inputs is None:
        return reject("RISK_INPUT_VERIFIER_UNBOUND")
    if verify_inputs(request, digest) is not True:
        return reject("RISK_INPUT_VERIFICATION_REJECTED")
    if parent_sizing_request_hash_v31(request) != digest:
        return reject("RISK_INPUT_CHANGED_DURING_VERIFICATION")
    snapshot, geometry, policy = request.snapshot, request.geometry, request.policy
    if (snapshot.account_id, snapshot.executor_id) != (request.expected_account_id, request.expected_executor_id):
        return reject("RISK_ACCOUNT_EXECUTOR_MISMATCH")
    if snapshot.currency != policy.account_currency:
        return reject("RISK_ACCOUNT_CURRENCY_UNSUPPORTED")
    if request.evaluated_at != geometry.decision_at:
        return reject("RISK_GEOMETRY_CLOCK_MISMATCH")
    age = (request.evaluated_at - snapshot.captured_at_utc).total_seconds()
    if not 0 <= age <= policy.snapshot_max_age_seconds:
        return reject("RISK_SNAPSHOT_STALE_OR_FUTURE")
    state_age = (request.evaluated_at - request.risk_state_captured_at).total_seconds()
    if not 0 <= state_age <= policy.risk_state_max_age_seconds:
        return reject("RISK_CAPACITY_STATE_STALE_OR_FUTURE")
    if not snapshot.trade_allowed or not snapshot.autotrading_enabled:
        return reject("RISK_TRADE_DISABLED")
    account_values = [Decimal(str(value)) for value in (snapshot.balance, snapshot.equity, snapshot.floating_pnl)]
    if any(not value.is_finite() for value in account_values):
        return reject("RISK_ACCOUNT_NONFINITE")
    balance, equity, floating = map(Fraction, account_values)
    if abs(equity - balance - floating) > Fraction(policy.equity_tolerance_usd):
        return reject("RISK_EQUITY_INCONSISTENT")
    specs = [
        spec
        for spec in snapshot.symbols
        if (spec.canonical_symbol, spec.broker_symbol) == (geometry.symbol, request.broker_symbol)
    ]
    if len(specs) != 1:
        return reject("RISK_SYMBOL_BINDING_MISSING_OR_AMBIGUOUS")
    spec = specs[0]
    values = [
        Decimal(str(value))
        for value in (
            spec.point,
            spec.tick_size,
            spec.tick_value_profit,
            spec.tick_value_loss,
            spec.volume_min,
            spec.volume_max,
            spec.volume_step,
        )
    ]
    if any(not value.is_finite() or value <= 0 for value in values):
        return reject("RISK_SYMBOL_SPEC_INVALID")
    point, tick, tick_profit, tick_loss, minimum, maximum, step = map(Fraction, values)
    if (spec.digits, point, tick) != (geometry.digits, Fraction(geometry.point), Fraction(geometry.tick_size)):
        return reject("RISK_GEOMETRY_SPEC_MISMATCH")
    if risk_amount_fraction_v31(request.campaign_committed_and_reserved_risk_usd) != 0:
        return reject("RISK_PARENT_CAMPAIGN_ALREADY_HAS_EXPOSURE", "REJECTED")
    solved = solve_net_geometry_v31(geometry)
    if solved.status != "FEASIBLE_TEST_ONLY":
        return reject("RISK_GEOMETRY_" + solved.reason)
    assert solved.candidate_entry is not None and geometry.costs is not None and geometry.policy is not None
    entry = Fraction(solved.candidate_entry)
    stop, target = Fraction(geometry.stop_price), Fraction(geometry.target_price)
    # Costs are the explicit price-equivalent profit/loss scenarios used by the
    # geometry kernel; no zero-cost defaults and no second cost addition.
    profit_cost = sum((Fraction(x) for x in geometry.costs.profit.model_dump().values()), Fraction(0))
    loss_cost = sum((Fraction(x) for x in geometry.costs.loss.model_dump().values()), Fraction(0))
    reward_per_lot = (abs(target - entry) - profit_cost) / tick * tick_profit
    loss_per_lot = (abs(entry - stop) + loss_cost) / tick * tick_loss
    # A feasible price ratio can fail the monetary ratio with asymmetric tick values.
    if (
        reward_per_lot <= 0
        or loss_per_lot <= 0
        or reward_per_lot < Fraction(geometry.policy.minimum_net_rr) * loss_per_lot
    ):
        return reject("RISK_MONETARY_NET_RR_INSUFFICIENT", "REJECTED")
    budget = balance * Fraction(policy.risk_fraction)
    volume = (budget / loss_per_lot // step) * step
    if volume < minimum:
        return reject("RISK_VOLUME_BELOW_MINIMUM", "REJECTED")
    if volume > maximum:
        return reject("RISK_VOLUME_ABOVE_MAXIMUM", "REJECTED")
    planned = volume * loss_per_lot
    account_risk = risk_amount_fraction_v31(request.account_committed_and_reserved_risk_usd)
    if account_risk + planned > balance * Fraction(policy.maximum_account_open_risk_fraction):
        return reject("RISK_ACCOUNT_CAPACITY_EXCEEDED", "REJECTED")
    return ParentSizingResultV31(
        status="SIZED_TEST_ONLY",
        reason="PARENT_SIZED_TEST_ONLY",
        request_hash=digest,
        geometry_request_hash=solved.request_hash,
        candidate_entry=solved.candidate_entry,
        volume=_exact(volume),
        parent_risk_budget_usd=_exact(budget),
        planned_loss_usd=_exact(planned),
        net_reward_usd=_exact(volume * reward_per_lot),
    )
