"""Thin G4 broker/cost adaptation of StructuralGeometryV31 — owner GO 2026-09-27, source/test only.

Q-A4-1 (A4-07): strategy_domain = ExecutionBox ∩ (structural_sl, TP1) for BUY and ExecutionBox ∩ (TP1, structural_sl)
for SELL; executable_domain = strategy_domain ∩ broker constraints (tick grid, stops level, freeze level); an empty
domain is NO_EXECUTABLE_ENTRY. Net RR is evaluated exactly at the worst-case executable entry and fails closed below
the canonical 1.5. The output is the request the existing risk engine (``size_parent_v31``) consumes; this step
decides no volume and authorizes no submit.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from fractions import Fraction

from contracts.mt5_execution_protocol import SymbolCapability
from contracts.strategy_5scr_broker_adaptation_v31 import (
    MINIMUM_NET_RR_V31,
    BrokerAdaptationDecisionV31,
    BrokerAdaptationPolicyV31,
    BrokerAdaptationStatus,
    BrokerAdaptationV31,
    BrokerQuoteV31,
    ExactRatioV31,
)
from contracts.strategy_5scr_identity_v31 import canonical_sha256_v31
from contracts.strategy_5scr_net_geometry_v31 import (
    EntryIntervalV31,
    NetCostSnapshotV31,
    NetGeometryPolicyV31,
    NetGeometryRequestV31,
    ScenarioCostV31,
)
from contracts.strategy_5scr_structural_geometry_v31 import StructuralGeometryV31


def _reject(status: BrokerAdaptationStatus, reason: str) -> BrokerAdaptationDecisionV31:
    return BrokerAdaptationDecisionV31(status=status, reason=reason, adaptation=None)


def _measured(value: float) -> Decimal:
    """Broker capability floats cross into Decimal once, by their shortest repr; never rounded."""

    return Decimal(str(value))


def _on_grid(price: Decimal, tick: Decimal) -> bool:
    return (Fraction(price) / Fraction(tick)).denominator == 1


def _total(cost: ScenarioCostV31) -> Fraction:
    return sum((Fraction(value) for value in cost.model_dump().values()), Fraction(0))


def adapt_structural_geometry_v31(
    *,
    geometry: StructuralGeometryV31,
    capability: SymbolCapability,
    quote: BrokerQuoteV31,
    costs: NetCostSnapshotV31,
    policy: BrokerAdaptationPolicyV31,
    decision_time: datetime,
) -> BrokerAdaptationDecisionV31:
    policy = BrokerAdaptationPolicyV31.model_validate(policy.model_dump())
    geometry = StructuralGeometryV31.model_validate(geometry.model_dump())
    symbol = geometry.canonical_symbol
    if policy.minimum_net_rr != MINIMUM_NET_RR_V31:
        return _reject("BROKER_ADAPTATION_POLICY_INVALID", "MINIMUM_NET_RR_NOT_CANONICAL")

    # Broker measurement: one symbol binding, a coherent tick grid and a quote as of decision_time.
    if (capability.canonical_symbol, quote.canonical_symbol) != (symbol, symbol):
        return _reject("BROKER_MEASUREMENT_INVALID", "BROKER_SYMBOL_BINDING_MISMATCH")
    if quote.broker_symbol != capability.broker_symbol:
        return _reject("BROKER_MEASUREMENT_INVALID", "BROKER_SYMBOL_BINDING_MISMATCH")
    point, tick = _measured(capability.point), _measured(capability.tick_size)
    if point != Decimal(1).scaleb(-capability.digits) or not _on_grid(tick, point):
        return _reject("BROKER_MEASUREMENT_INVALID", "BROKER_TICK_GRID_INCOHERENT")
    age = (decision_time - quote.observed_at).total_seconds()
    if not 0 <= age <= policy.max_quote_age_seconds:
        return _reject("BROKER_MEASUREMENT_INVALID", "QUOTE_STALE_OR_FUTURE")

    # Costs: explicit, versioned, as of decision_time, and never below the measured spread.
    if costs.symbol != symbol or not costs.captured_at <= decision_time < costs.valid_until:
        return _reject("COST_EVIDENCE_INVALID", "COST_NOT_BOUND_OR_NOT_AS_OF_DECISION")
    spread = quote.ask - quote.bid
    if costs.profit.spread_price < spread or costs.loss.spread_price < spread:
        return _reject("COST_SPREAD_UNDERSTATED", "COST_SPREAD_BELOW_MEASURED_SPREAD")

    # Canonical SL / TP1 must be placeable as they are: broker feasibility may reject, never move them.
    material = geometry.material
    sl, tp1 = material.structural_sl, material.tp1
    if not (_on_grid(sl, tick) and _on_grid(tp1, tick)):
        return _reject("BROKER_PRICE_OFF_TICK_GRID", "CANONICAL_SL_OR_TP1_OFF_TICK_GRID")

    buy = geometry.direction == "BUY"
    near, far = (sl, tp1) if buy else (tp1, sl)  # the open (near, far) interval, in price order
    # Strategy domain: the box inside the open (SL, TP1) interval; nothing is clamped, moved or expanded.
    strategy_low = max(geometry.entry_interval_low, near)
    strategy_high = min(geometry.entry_interval_high, far)
    if strategy_low > strategy_high:
        return _reject("NO_EXECUTABLE_ENTRY", "STRATEGY_DOMAIN_EMPTY")
    s, t, k = Fraction(sl), Fraction(tp1), Fraction(tick)
    # Broker constraints: one tick strictly inside (SL, TP1) and the stops/freeze distance from both.
    distance = max(capability.stops_level_points, capability.freeze_level_points) * Fraction(point)
    low = max(Fraction(strategy_low), Fraction(near) + k, Fraction(near) + distance)
    high = min(Fraction(strategy_high), Fraction(far) - k, Fraction(far) - distance)
    # Executable domain: inward to the broker tick grid (ceil the low, floor the high), never outward.
    first = -((-low.numerator * k.denominator) // (low.denominator * k.numerator))
    last = (high.numerator * k.denominator) // (high.denominator * k.numerator)
    if first > last:
        return _reject("NO_EXECUTABLE_ENTRY", "EXECUTABLE_DOMAIN_EMPTY")
    executable_low, executable_high = Decimal(first) * tick, Decimal(last) * tick
    worst = executable_high if buy else executable_low

    e = Fraction(worst)
    reward = (t - e if buy else e - t) - _total(costs.profit)
    risk = (e - s if buy else s - e) + _total(costs.loss)
    if reward <= 0 or risk <= 0 or reward / risk < Fraction(MINIMUM_NET_RR_V31):
        return _reject("NET_RR_BELOW_MINIMUM", "NET_RR_BELOW_CANONICAL_1_5_AT_WORST_CASE_ENTRY")

    domain = EntryIntervalV31(low=executable_low, high=executable_high)
    box = EntryIntervalV31(low=geometry.entry_interval_low, high=geometry.entry_interval_high)
    request = NetGeometryRequestV31(
        symbol=symbol,
        instrument_class=policy.instrument_class,
        direction=geometry.direction,
        decision_at=decision_time,
        stop_price=sl,
        stop_evidence_hash=geometry.lineage.reference_candle_id,
        digits=capability.digits,
        point=point,
        tick_size=tick,
        # The kernel always applies minimum_target_units × target_unit_size. One tick equals its own exclusive
        # (SL, TP1) step, so it adds no floor beyond A4 (A4-04: no minimum target distance).
        target_unit_size=tick,
        structural_interval=box,
        route_interval=box,
        broker_interval=domain,
        policy=NetGeometryPolicyV31(
            profile="TEST_ONLY",
            policy_id=policy.policy_id,
            policy_hash=policy.policy_hash,
            instrument_class=policy.instrument_class,
            minimum_target_units=Decimal(1),
            minimum_net_rr=MINIMUM_NET_RR_V31,
        ),
        costs=costs,
        target_price=tp1,
        target_evidence_hash=geometry.lineage.target_evidence_hash,
    )
    adaptation = BrokerAdaptationV31(
        material_geometry_hash=geometry.material_geometry_hash,
        canonical_symbol=symbol,
        broker_symbol=capability.broker_symbol,
        direction=geometry.direction,
        structural_sl=sl,
        tp1=tp1,
        strategy_domain_low=strategy_low,
        strategy_domain_high=strategy_high,
        executable_domain_low=executable_low,
        executable_domain_high=executable_high,
        worst_case_executable_entry=worst,
        measured_spread=spread,
        gross_rr=ExactRatioV31(numerator=geometry.gross_rr.numerator, denominator=geometry.gross_rr.denominator),
        net_rr=ExactRatioV31.of(reward / risk),
        minimum_net_rr=MINIMUM_NET_RR_V31,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_hash=policy.policy_hash,
        quote_evidence_hash=quote.evidence_hash,
        cost_source_hash=costs.source_hash,
        capability_digest=canonical_sha256_v31(capability.model_dump(mode="json")),
        risk_engine_request=request,
    )
    return BrokerAdaptationDecisionV31(
        status="ELIGIBLE_FOR_RISK_ENGINE", reason="EXECUTABLE_DOMAIN_NET_RR_OK", adaptation=adaptation
    )


__all__ = ["adapt_structural_geometry_v31"]
