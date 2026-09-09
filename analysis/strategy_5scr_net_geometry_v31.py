"""Pure TEST_ONLY fixed-target net-RR solve; no broker, policy lookup or I/O."""

import hashlib
import json
from decimal import Decimal, localcontext
from fractions import Fraction

from contracts.strategy_5scr_net_geometry_v31 import (
    EntryIntervalV31,
    NetGeometryRequestV31,
    NetGeometryResultV31,
    ScenarioCostV31,
)


def _cost(cost: ScenarioCostV31) -> Fraction:
    return sum((Fraction(value) for value in cost.model_dump().values()), Fraction(0))


def solve_net_geometry_v31(request: NetGeometryRequestV31) -> NetGeometryResultV31:
    # Revalidate at the public boundary, including objects made with model_copy.
    request = NetGeometryRequestV31.model_validate(request.model_dump())
    encoded = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    request_hash = "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def reject(status: str, reason: str) -> NetGeometryResultV31:
        return NetGeometryResultV31(status=status, reason=reason, request_hash=request_hash)

    policy, costs = request.policy, request.costs
    if policy is None:
        return reject("WAIT", "POLICY_UNBOUND")
    if costs is None:
        return reject("WAIT", "COST_EVIDENCE_UNBOUND")
    if policy.instrument_class != request.instrument_class:
        return reject("WAIT", "INSTRUMENT_POLICY_MISMATCH")
    if costs.symbol != request.symbol:
        return reject("WAIT", "COST_SYMBOL_MISMATCH")
    if not costs.captured_at <= request.decision_at < costs.valid_until:
        return reject("WAIT", "COST_NOT_AS_OF_DECISION")

    target, stop, tick = map(Fraction, (request.target_price, request.stop_price, request.tick_size))
    buying = request.direction == "BUY"
    if (buying and stop >= target) or (not buying and stop <= target):
        return reject("NO_VALID_ENTRY_DOMAIN", "FIXED_TARGET_STOP_DIRECTION_CONFLICT")
    profit_cost, loss_cost = _cost(costs.profit), _cost(costs.loss)
    ratio = Fraction(policy.minimum_net_rr)
    floor = Fraction(policy.minimum_target_units) * Fraction(request.target_unit_size)
    intervals = (request.structural_interval, request.route_interval, request.broker_interval)
    low = max(Fraction(item.low) for item in intervals)
    high = min(Fraction(item.high) for item in intervals)
    # BUY: (T-E-Cprofit)/(E-S+Closs) >= R.
    # SELL: (E-T-Cprofit)/(S-E+Closs) >= R.
    # Rational arithmetic prevents an outward tick due to division rounding.
    if buying:
        bound = (target + ratio * stop - profit_cost - ratio * loss_cost) / (1 + ratio)
        low, high = max(low, stop + tick), min(high, target - tick, target - floor, bound)
    else:
        bound = (target + ratio * stop + profit_cost + ratio * loss_cost) / (1 + ratio)
        low, high = max(low, target + tick, target + floor, bound), min(high, stop - tick)
    lo, hi = low / tick, high / tick
    first_tick = -(-lo.numerator // lo.denominator)
    last_tick = hi.numerator // hi.denominator
    if first_tick > last_tick:
        return reject("NO_VALID_ENTRY_DOMAIN", "NET_GEOMETRY_INTERSECTION_EMPTY")
    entry = (last_tick if buying else first_tick) * tick
    net_reward, net_risk = abs(target - entry) - profit_cost, abs(entry - stop) + loss_cost
    if net_reward <= 0 or net_risk <= 0 or net_reward < ratio * net_risk:
        raise AssertionError("net geometry solver violated its exact feasibility invariant")
    with localcontext() as context:
        context.prec = 80
        low_price = Decimal(first_tick) * request.tick_size
        high_price = Decimal(last_tick) * request.tick_size
        reported_rr = Decimal((net_reward / net_risk).numerator) / Decimal((net_reward / net_risk).denominator)
    return NetGeometryResultV31(
        status="FEASIBLE_TEST_ONLY",
        reason="FIXED_TARGET_NET_GEOMETRY_FEASIBLE_TEST_ONLY",
        request_hash=request_hash,
        feasible_interval=EntryIntervalV31(low=low_price, high=high_price),
        candidate_entry=high_price if buying else low_price,
        net_rr=reported_rr,
    )
