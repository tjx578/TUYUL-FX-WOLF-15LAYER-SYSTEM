"""Pure target-first solver for shadow-only Strategy 5S-CR Candidate V2."""

from __future__ import annotations

import hashlib
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from contracts.strategy_5scr_context_epoch_v1 import StrategyContextEpochV1
from contracts.strategy_5scr_directional_thesis_v1 import DirectionalThesisV1
from contracts.strategy_5scr_execution_box_v1 import ExecutionBoxV1
from contracts.strategy_5scr_execution_policy import FX_MIN_TARGET_10P_V1
from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleV2
from contracts.strategy_5scr_tradeplan_candidate_v2 import (
    BrokerGeometryCostAuthorityV1,
    EvaluationDecision,
    PersistedEvaluationDecision,
    PriceIntervalV1,
    StructuralStopAuthorityV1,
    StructuralTargetAuthorityV1,
    StructuralTargetMapAuthorityV1,
    StructuralTargetMapEvidenceV1,
    TradePlanCandidateBuildEvidenceV2,
    TradePlanCandidateReductionResultV2,
    TradePlanCandidateTransitionV2,
    TradePlanCandidateV2,
    TradePlanEvaluationV2,
    broker_geometry_material_hash_v1,
    canonical_hash_v1,
    canonical_tradeplan_numeric_v2,
    structural_target_map_authority_hash_v1,
    structural_target_material_hash_v1,
    tradeplan_candidate_material_hash_v2,
)

_TEN = Decimal(str(FX_MIN_TARGET_10P_V1.minimum_fx_target_pips))
_RR = Decimal(str(FX_MIN_TARGET_10P_V1.minimum_rr))
_COST_MULTIPLIER = Decimal(str(FX_MIN_TARGET_10P_V1.spread_multiplier))


def _short_id(prefix: str, material: str) -> str:
    return prefix + hashlib.sha256(material.encode()).hexdigest()[:32]


def structural_target_id_v1(*, material_target_hash: str) -> str:
    return _short_id("5scr-target:", material_target_hash)


def structural_target_authority_hash_v1(target: StructuralTargetAuthorityV1) -> str:
    return canonical_hash_v1(target.model_dump(mode="json", exclude={"authority_hash"}))


def derive_structural_target_map_v1(evidence: StructuralTargetMapEvidenceV1) -> StructuralTargetMapAuthorityV1:
    """Derive strict three-H4-candle targets and H1 consumption, then select nearest."""

    targets: list[StructuralTargetAuthorityV1] = []
    candles = evidence.h4_candles
    for left, pivot, right in zip(candles, candles[1:], candles[2:], strict=False):
        if evidence.direction == "BUY":
            is_swing = pivot.high > left.high and pivot.high > right.high
            price = pivot.high
            kind = "H4_STRICT_SWING_HIGH"
            directional = price > evidence.selection_anchor.close
        else:
            is_swing = pivot.low < left.low and pivot.low < right.low
            price = pivot.low
            kind = "H4_STRICT_SWING_LOW"
            directional = price < evidence.selection_anchor.close
        if not is_swing or not directional:
            continue
        formed_at = right.close_time_utc
        consuming = next(
            (
                item
                for item in evidence.h1_consumption_candles
                if item.close_time_utc > formed_at
                and ((item.high >= price) if evidence.direction == "BUY" else (item.low <= price))
            ),
            None,
        )
        material_target_hash = structural_target_material_hash_v1(
            symbol=evidence.symbol,
            direction=evidence.direction,
            target_kind=kind,
            target_price=price,
            left_material_candle_hash=left.material_candle_hash,
            pivot_material_candle_hash=pivot.material_candle_hash,
            right_material_candle_hash=right.material_candle_hash,
            formed_at_utc=formed_at,
            target_map_version=evidence.target_map_version,
        )
        target_id = structural_target_id_v1(material_target_hash=material_target_hash)
        provisional = StructuralTargetAuthorityV1(
            target_id=target_id,
            authority_hash="sha256:" + "0" * 64,
            material_target_hash=material_target_hash,
            symbol=evidence.symbol,
            direction=evidence.direction,
            target_kind=kind,
            target_price=price,
            left_candle_id=left.candle_evidence_id,
            pivot_candle_id=pivot.candle_evidence_id,
            right_candle_id=right.candle_evidence_id,
            left_material_candle_hash=left.material_candle_hash,
            pivot_material_candle_hash=pivot.material_candle_hash,
            right_material_candle_hash=right.material_candle_hash,
            formed_at_utc=formed_at,
            consumed_at_utc=None if consuming is None else consuming.close_time_utc,
            consumed_by_h1_candle_id=None if consuming is None else consuming.candle_evidence_id,
            target_map_version=evidence.target_map_version,
        )
        targets.append(
            provisional.model_copy(update={"authority_hash": structural_target_authority_hash_v1(provisional)})
        )
    anchor = evidence.selection_anchor.close
    ordered = tuple(
        sorted(
            targets,
            key=lambda item: (
                abs(item.target_price - anchor),
                item.formed_at_utc,
                item.material_target_hash,
            ),
        )
    )
    selected = next((item for item in ordered if item.consumed_at_utc is None), None)
    source_evidence_hash = canonical_hash_v1(evidence.model_dump(mode="json"))
    provisional_map = StructuralTargetMapAuthorityV1.model_construct(
        target_map_id="5scr-target-map:" + "0" * 32,
        authority_hash=_HASH_SENTINEL,
        target_map_version=evidence.target_map_version,
        source_evidence_hash=source_evidence_hash,
        symbol=evidence.symbol,
        direction=evidence.direction,
        selection_anchor_price=anchor,
        selected_target_id=None if selected is None else selected.target_id,
        targets=ordered,
        latest_h4_confirmation_at_utc=candles[-1].close_time_utc,
        decision_at_utc=evidence.decision_at_utc,
    )
    authority_hash = structural_target_map_authority_hash_v1(provisional_map)
    return StructuralTargetMapAuthorityV1(
        **provisional_map.model_dump(mode="python", exclude={"target_map_id", "authority_hash"}),
        target_map_id=_short_id("5scr-target-map:", authority_hash),
        authority_hash=authority_hash,
    )


def select_nearest_structural_target_v1(
    target_map: StructuralTargetMapAuthorityV1,
) -> StructuralTargetAuthorityV1 | None:
    if target_map.selected_target_id is None:
        return None
    return next(item for item in target_map.targets if item.target_id == target_map.selected_target_id)


def derive_structural_stop_authority_v1(
    *, box: ExecutionBoxV1, broker: BrokerGeometryCostAuthorityV1
) -> StructuralStopAuthorityV1:
    extreme = Decimal(str(box.box_low if box.strategy_direction == "BUY" else box.box_high))
    stop = extreme - broker.tick_size if box.strategy_direction == "BUY" else extreme + broker.tick_size
    payload = {
        "execution_box_id": box.execution_box_id,
        "execution_box_material_hash": box.material_box_hash,
        "freeze_authority_hash": box.freeze_authority_hash,
        "direction": box.strategy_direction,
        "policy_id": "P5_ROUTE_EXTREME_1_TICK_V1",
        "route_extreme": extreme,
        "buffer_price": broker.tick_size,
        "structural_stop_price": stop,
    }
    authority_hash = canonical_hash_v1(payload)
    return StructuralStopAuthorityV1(
        authority_id=_short_id("5scr-stop:", authority_hash),
        authority_hash=authority_hash,
        execution_box_id=box.execution_box_id,
        direction=box.strategy_direction,
        route_extreme=extreme,
        buffer_price=broker.tick_size,
        structural_stop_price=stop,
    )


def _ceil_grid(value: Decimal, tick: Decimal) -> Decimal:
    return (value / tick).to_integral_value(rounding=ROUND_CEILING) * tick


def _floor_grid(value: Decimal, tick: Decimal) -> Decimal:
    return (value / tick).to_integral_value(rounding=ROUND_FLOOR) * tick


def _interval(low: Decimal, high: Decimal, source: str, tick: Decimal) -> PriceIntervalV1 | None:
    low_grid, high_grid = _ceil_grid(low, tick), _floor_grid(high, tick)
    if high_grid < low_grid:
        return None
    return PriceIntervalV1(low=low_grid, high=high_grid, source=source)


def intersect_price_intervals_v1(
    intervals: tuple[PriceIntervalV1, ...], *, tick_size: Decimal, source: str = "FEASIBLE_INTERSECTION"
) -> PriceIntervalV1 | None:
    return _interval(max(item.low for item in intervals), min(item.high for item in intervals), source, tick_size)


def _parent_reason(
    lifecycle: StrategyLifecycleV2,
    context: StrategyContextEpochV1,
    thesis: DirectionalThesisV1,
    box: ExecutionBoxV1,
    target_evidence: StructuralTargetMapEvidenceV1,
) -> str | None:
    scope = (lifecycle.strategy_lifecycle_id, context.context_epoch_id, thesis.strategy_thesis_id, box.execution_box_id)
    evidence_scope = (
        target_evidence.strategy_lifecycle_id,
        target_evidence.context_epoch_id,
        target_evidence.strategy_thesis_id,
        target_evidence.execution_box_id,
    )
    if scope != evidence_scope:
        return "NO_TRADE_PARENT_AUTHORITY_INVALID"
    if not lifecycle.is_active or context.state != "ACTIVE" or thesis.state != "ACTIVE":
        return "NO_TRADE_PARENT_AUTHORITY_INVALID"
    if box.state != "FROZEN":
        return "WAIT_EXECUTION_BOX_NOT_FROZEN"
    if not box.freeze_authority_hash:
        return "NO_TRADE_PARENT_AUTHORITY_INVALID"
    material = (
        context.material_context_hash,
        thesis.semantic_identity_hash,
        box.material_box_hash,
        lifecycle.symbol,
        thesis.strategy_direction,
    )
    claimed = (
        target_evidence.material_context_hash,
        target_evidence.thesis_semantic_identity_hash,
        target_evidence.execution_box_material_hash,
        target_evidence.symbol,
        target_evidence.direction,
    )
    if material != claimed or context.strategy_lifecycle_id != lifecycle.strategy_lifecycle_id:
        return "NO_TRADE_PARENT_AUTHORITY_INVALID"
    if (
        thesis.context_epoch_id != context.context_epoch_id
        or thesis.strategy_lifecycle_id != lifecycle.strategy_lifecycle_id
    ):
        return "NO_TRADE_PARENT_AUTHORITY_INVALID"
    if box.context_epoch_id != context.context_epoch_id or box.strategy_thesis_id != thesis.strategy_thesis_id:
        return "NO_TRADE_PARENT_AUTHORITY_INVALID"
    if (
        box.strategy_lifecycle_id != lifecycle.strategy_lifecycle_id
        or box.strategy_direction != thesis.strategy_direction
    ):
        return "NO_TRADE_PARENT_AUTHORITY_INVALID"
    if context.target_map_version is None or context.target_map_version != target_evidence.target_map_version:
        return "NO_TRADE_TARGET_NOT_AUTHORITATIVE"
    if target_evidence.coverage_start_utc != context.opened_at_utc:
        return "NO_TRADE_TARGET_NOT_AUTHORITATIVE"
    if target_evidence.decision_at_utc < max(
        lifecycle.last_event_at_utc,
        context.last_observed_at_utc,
        thesis.liveness_checked_through_utc,
        box.last_observed_at_utc,
    ):
        return "NO_TRADE_PARENT_AUTHORITY_INVALID"
    return None


def _material_candidate_payload(
    *,
    context: StrategyContextEpochV1,
    thesis: DirectionalThesisV1,
    box: ExecutionBoxV1,
    target_map: StructuralTargetMapAuthorityV1,
    target: StructuralTargetAuthorityV1,
    stop: StructuralStopAuthorityV1,
    broker: BrokerGeometryCostAuthorityV1,
    intervals: tuple[PriceIntervalV1, ...],
    candidate_price: Decimal,
) -> dict[str, object]:
    return {
        "context_material_hash": context.material_context_hash,
        "thesis_semantic_identity_hash": thesis.semantic_identity_hash,
        "execution_box_id": box.execution_box_id,
        "execution_box_material_hash": box.material_box_hash,
        "execution_box_freeze_authority_hash": box.freeze_authority_hash,
        "material_target_hash": target.material_target_hash,
        "stop_authority_hash": stop.authority_hash,
        "broker_geometry_material_hash": broker_geometry_material_hash_v1(broker),
        "intervals": [item.model_dump(mode="json") for item in intervals],
        "candidate_price": candidate_price,
        "execution_policy_id": "FX_MIN_TARGET_10P_V1",
        "rule_version": "5scr.tradeplan-candidate.v2",
    }


def _evaluation(
    *,
    evidence: TradePlanCandidateBuildEvidenceV2,
    target_evidence: StructuralTargetMapEvidenceV1,
    box: ExecutionBoxV1,
    sequence: int,
    decision: PersistedEvaluationDecision,
    reasons: tuple[str, ...],
    evidence_hash: str,
    material_hash: str,
    result_id: str | None = None,
) -> TradePlanEvaluationV2:
    evaluation_id = _short_id(
        "5scr-tradeplan-eval:",
        f"{target_evidence.strategy_lifecycle_id}|{sequence}|{evidence_hash}|{decision}|{'|'.join(reasons)}",
    )
    return TradePlanEvaluationV2(
        evaluation_id=evaluation_id,
        evaluation_sequence=sequence,
        source_request_id=evidence.source_request_id,
        strategy_lifecycle_id=target_evidence.strategy_lifecycle_id,
        context_epoch_id=target_evidence.context_epoch_id,
        strategy_thesis_id=target_evidence.strategy_thesis_id,
        execution_box_id=target_evidence.execution_box_id,
        material_context_hash=target_evidence.material_context_hash,
        thesis_semantic_identity_hash=target_evidence.thesis_semantic_identity_hash,
        execution_box_material_hash=target_evidence.execution_box_material_hash,
        execution_box_freeze_authority_hash=box.freeze_authority_hash or _HASH_SENTINEL,
        symbol=target_evidence.symbol,
        direction=target_evidence.direction,
        decision_at_utc=evidence.decision_at_utc,
        decision=decision,
        reason_codes=reasons,
        evidence_hash=evidence_hash,
        material_evaluation_hash=material_hash,
        result_tradeplan_id=result_id,
    )


_HASH_SENTINEL = "sha256:" + "0" * 64


def solve_tradeplan_candidate_v2(
    *,
    lifecycle: StrategyLifecycleV2,
    context: StrategyContextEpochV1,
    thesis: DirectionalThesisV1,
    execution_box: ExecutionBoxV1,
    evidence: TradePlanCandidateBuildEvidenceV2,
    evaluation_sequence: int,
    candidate_sequence: int,
    current_candidate: TradePlanCandidateV2 | None = None,
) -> TradePlanCandidateReductionResultV2:
    """Evaluate one immutable authority snapshot without creating execution authority."""

    target_evidence = evidence.target_map_evidence
    evidence_hash = canonical_hash_v1(
        evidence.model_dump(mode="json", exclude={"source_deployment_id", "source_replica_id"})
    )

    def reject(
        decision: EvaluationDecision,
        reason: str,
        material: str = _HASH_SENTINEL,
        *,
        invalidate_current_reason: str | None = None,
    ) -> TradePlanCandidateReductionResultV2:
        if decision == "QUARANTINED":
            return TradePlanCandidateReductionResultV2(decision=decision, reason_code=reason)
        persisted_decision: PersistedEvaluationDecision = "WAIT" if decision == "WAIT" else "NO_TRADE"
        evaluation = _evaluation(
            evidence=evidence,
            target_evidence=target_evidence,
            box=execution_box,
            sequence=evaluation_sequence,
            decision=persisted_decision,
            reasons=(reason,),
            evidence_hash=evidence_hash,
            material_hash=material,
        )
        transition = None
        previous_candidate = None
        if invalidate_current_reason is not None and current_candidate is not None:
            transition_material = canonical_hash_v1(
                {
                    "from": current_candidate.tradeplan_id,
                    "to": None,
                    "occurred_at": evidence.decision_at_utc,
                    "reason": invalidate_current_reason,
                }
            )
            transition = TradePlanCandidateTransitionV2(
                transition_id=_short_id("5scr-tradeplan-transition:", transition_material),
                tradeplan_id=current_candidate.tradeplan_id,
                from_state="ACTIVE",
                to_state="INVALIDATED",
                reason_code=invalidate_current_reason,
                occurred_at_utc=evidence.decision_at_utc,
                successor_tradeplan_id=None,
                authority_hash=transition_material,
            )
            previous_candidate = current_candidate
        return TradePlanCandidateReductionResultV2(
            decision=decision,
            reason_code=reason,
            evaluation=evaluation,
            previous_candidate=previous_candidate,
            transition=transition,
        )

    if current_candidate is not None:
        try:
            verified_current = TradePlanCandidateV2.model_validate(current_candidate.model_dump(mode="python"))
        except ValueError:
            return reject("QUARANTINED", "TRADEPLAN_CURRENT_CANDIDATE_INTEGRITY_DRIFT")
        current_scope = (
            verified_current.strategy_lifecycle_id,
            verified_current.context_epoch_id,
            verified_current.strategy_thesis_id,
            verified_current.execution_box_id,
            verified_current.material_context_hash,
            verified_current.thesis_semantic_identity_hash,
            verified_current.execution_box_material_hash,
            verified_current.execution_box_freeze_authority_hash,
            verified_current.symbol,
            verified_current.direction,
        )
        requested_scope = (
            lifecycle.strategy_lifecycle_id,
            context.context_epoch_id,
            thesis.strategy_thesis_id,
            execution_box.execution_box_id,
            context.material_context_hash,
            thesis.semantic_identity_hash,
            execution_box.material_box_hash,
            execution_box.freeze_authority_hash,
            lifecycle.symbol,
            thesis.strategy_direction,
        )
        if current_scope != requested_scope or verified_current.lifecycle_state != "ACTIVE":
            return reject("QUARANTINED", "TRADEPLAN_CURRENT_CANDIDATE_SCOPE_DRIFT")
        # The repository normally resolves this against the existing request
        # ledger first.  Keeping it ahead of liveness gates makes direct pure
        # replay deterministic even after parent observation clocks advance.
        if verified_current.evidence_hash == evidence_hash:
            return TradePlanCandidateReductionResultV2(
                decision="DUPLICATE",
                reason_code="TRADEPLAN_EXACT_REQUEST_ALREADY_EVALUATED",
                candidate=verified_current,
            )

    parent_reason = _parent_reason(lifecycle, context, thesis, execution_box, target_evidence)
    if parent_reason:
        return reject("WAIT" if parent_reason.startswith("WAIT_") else "NO_TRADE", parent_reason)
    broker = evidence.broker_geometry
    if broker.symbol != lifecycle.symbol or not (
        broker.captured_at_utc <= evidence.decision_at_utc <= broker.valid_until_utc
    ):
        return reject("NO_TRADE", "NO_TRADE_BROKER_CONSTRAINT")

    try:
        target_map = derive_structural_target_map_v1(target_evidence)
    except ValueError:
        return reject("QUARANTINED", "NO_TRADE_TARGET_NOT_AUTHORITATIVE")
    target = select_nearest_structural_target_v1(target_map)
    if target is None:
        reason = (
            "NO_TRADE_TARGET_ALREADY_CONSUMED"
            if target_map.targets and all(item.consumed_at_utc is not None for item in target_map.targets)
            else "NO_TRADE_TARGET_NOT_AUTHORITATIVE"
        )
        return reject(
            "NO_TRADE",
            reason,
            target_map.authority_hash,
            invalidate_current_reason="TRADEPLAN_TARGET_AUTHORITY_LOST",
        )

    raw_box_low = Decimal(str(execution_box.box_low))
    raw_box_high = Decimal(str(execution_box.box_high))
    if any(value % broker.tick_size != 0 for value in (raw_box_low, raw_box_high, target.target_price)):
        return reject(
            "NO_TRADE",
            "NO_TRADE_BROKER_CONSTRAINT",
            target_map.authority_hash,
            invalidate_current_reason="TRADEPLAN_GEOMETRY_AUTHORITY_LOST",
        )
    stop = derive_structural_stop_authority_v1(box=execution_box, broker=broker)
    low = raw_box_low
    high = raw_box_high
    route = _interval(low, high, "P5_ROUTE_INTERVAL", broker.tick_size)
    structural = _interval(low, high, "P5_STRUCTURAL_INTERVAL", broker.tick_size)
    if route is None or structural is None:
        return reject(
            "NO_TRADE",
            "NO_TRADE_BROKER_CONSTRAINT",
            target_map.authority_hash,
            invalidate_current_reason="TRADEPLAN_GEOMETRY_AUTHORITY_LOST",
        )
    target_floor = _TEN * broker.pip_size
    cost_floor = _COST_MULTIPLIER * broker.spread_price
    if thesis.strategy_direction == "BUY":
        target_room = _interval(low, min(high, target.target_price - target_floor), "TARGET_ROOM_10P", broker.tick_size)
        cost_room = _interval(low, min(high, target.target_price - cost_floor), "COST_ROOM", broker.tick_size)
        rr_bound = (target.target_price + _RR * stop.structural_stop_price) / (Decimal("1") + _RR)
        rr_interval = _interval(low, min(high, rr_bound), "RR_MIN_1_5", broker.tick_size)
    else:
        target_room = _interval(max(low, target.target_price + target_floor), high, "TARGET_ROOM_10P", broker.tick_size)
        cost_room = _interval(max(low, target.target_price + cost_floor), high, "COST_ROOM", broker.tick_size)
        rr_bound = (target.target_price + _RR * stop.structural_stop_price) / (Decimal("1") + _RR)
        rr_interval = _interval(max(low, rr_bound), high, "RR_MIN_1_5", broker.tick_size)
    if target_room is None:
        return reject(
            "NO_TRADE",
            "NO_TRADE_TARGET_BELOW_10_PIPS",
            target_map.authority_hash,
            invalidate_current_reason="TRADEPLAN_GEOMETRY_AUTHORITY_LOST",
        )
    if cost_room is None:
        return reject(
            "NO_TRADE",
            "NO_TRADE_EXECUTION_COST",
            target_map.authority_hash,
            invalidate_current_reason="TRADEPLAN_GEOMETRY_AUTHORITY_LOST",
        )
    if rr_interval is None:
        return reject(
            "NO_TRADE",
            "NO_TRADE_RR_BELOW_MINIMUM",
            target_map.authority_hash,
            invalidate_current_reason="TRADEPLAN_GEOMETRY_AUTHORITY_LOST",
        )
    components = (structural, route, target_room, cost_room, rr_interval)
    feasible = intersect_price_intervals_v1(components, tick_size=broker.tick_size)
    if feasible is None:
        return reject(
            "NO_TRADE",
            "NO_TRADE_EMPTY_ENTRY_DOMAIN",
            target_map.authority_hash,
            invalidate_current_reason="TRADEPLAN_GEOMETRY_AUTHORITY_LOST",
        )
    candidate_price = feasible.high if thesis.strategy_direction == "BUY" else feasible.low
    target_pips = abs(target.target_price - candidate_price) / broker.pip_size
    risk_pips = abs(candidate_price - stop.structural_stop_price) / broker.pip_size
    raw_gross_rr = target_pips / risk_pips
    if raw_gross_rr < _RR:  # compare before durable rounding at the policy boundary
        return reject(
            "NO_TRADE",
            "NO_TRADE_RR_BELOW_MINIMUM",
            target_map.authority_hash,
            invalidate_current_reason="TRADEPLAN_GEOMETRY_AUTHORITY_LOST",
        )
    gross_rr = canonical_tradeplan_numeric_v2(raw_gross_rr)
    material_payload = _material_candidate_payload(
        context=context,
        thesis=thesis,
        box=execution_box,
        target_map=target_map,
        target=target,
        stop=stop,
        broker=broker,
        intervals=(*components, feasible),
        candidate_price=candidate_price,
    )
    material_hash = canonical_hash_v1(material_payload)
    if current_candidate is not None:
        if current_candidate.lifecycle_state != "ACTIVE":
            return reject("NO_TRADE", "NO_TRADE_PARENT_AUTHORITY_INVALID", material_hash)
        if current_candidate.material_candidate_hash == material_hash:
            evaluation = _evaluation(
                evidence=evidence,
                target_evidence=target_evidence,
                box=execution_box,
                sequence=evaluation_sequence,
                decision="CANDIDATE",
                reasons=("TRADEPLAN_CANDIDATE_REUSED",),
                evidence_hash=evidence_hash,
                material_hash=material_hash,
                result_id=current_candidate.tradeplan_id,
            )
            return TradePlanCandidateReductionResultV2(
                decision="DUPLICATE",
                reason_code="TRADEPLAN_CANDIDATE_ALREADY_PERSISTED",
                evaluation=evaluation,
                candidate=current_candidate,
                target_map=target_map,
            )
        candidate_sequence = current_candidate.candidate_sequence + 1
    tradeplan_id = _short_id(
        "5scr-tradeplan-v2:",
        f"{execution_box.execution_box_id}|{candidate_sequence}|1|{material_hash}|5scr.tradeplan-candidate.v2",
    )
    candidate = TradePlanCandidateV2(
        tradeplan_id=tradeplan_id,
        candidate_sequence=candidate_sequence,
        previous_tradeplan_id=None if current_candidate is None else current_candidate.tradeplan_id,
        strategy_lifecycle_id=lifecycle.strategy_lifecycle_id,
        context_epoch_id=context.context_epoch_id,
        strategy_thesis_id=thesis.strategy_thesis_id,
        execution_box_id=execution_box.execution_box_id,
        material_context_hash=context.material_context_hash,
        thesis_semantic_identity_hash=thesis.semantic_identity_hash,
        execution_box_material_hash=execution_box.material_box_hash,
        execution_box_freeze_authority_hash=execution_box.freeze_authority_hash or _HASH_SENTINEL,
        box_sequence=execution_box.box_sequence,
        box_version=execution_box.box_version,
        symbol=lifecycle.symbol,
        direction=thesis.strategy_direction,
        route_type=execution_box.route_type,
        decision_at_utc=evidence.decision_at_utc,
        target_authority=target,
        target_map_authority_hash=target_map.authority_hash,
        stop_authority=stop,
        broker_authority_hash=broker.authority_hash,
        broker_geometry_material_hash=broker_geometry_material_hash_v1(broker),
        broker_digits=broker.digits,
        broker_point=broker.point,
        broker_tick_size=broker.tick_size,
        broker_pip_size=broker.pip_size,
        broker_spread_price=broker.spread_price,
        structural_interval=structural,
        route_interval=route,
        target_room_interval=target_room,
        cost_room_interval=cost_room,
        rr_interval=rr_interval,
        feasible_interval=feasible,
        candidate_price=candidate_price,
        target_distance_pips=target_pips,
        risk_distance_pips=risk_pips,
        gross_rr=gross_rr,
        material_candidate_hash=material_hash,
        evidence_hash=evidence_hash,
    )
    assert tradeplan_candidate_material_hash_v2(candidate) == material_hash
    transition = None
    if current_candidate is not None:
        transition_material = canonical_hash_v1(
            {
                "from": current_candidate.tradeplan_id,
                "to": candidate.tradeplan_id,
                "occurred_at": evidence.decision_at_utc,
                "reason": "TRADEPLAN_MATERIAL_SUCCESSOR",
            }
        )
        transition = TradePlanCandidateTransitionV2(
            transition_id=_short_id("5scr-tradeplan-transition:", transition_material),
            tradeplan_id=current_candidate.tradeplan_id,
            from_state="ACTIVE",
            to_state="SUPERSEDED",
            reason_code="TRADEPLAN_MATERIAL_SUCCESSOR",
            occurred_at_utc=evidence.decision_at_utc,
            successor_tradeplan_id=candidate.tradeplan_id,
            authority_hash=transition_material,
        )
    evaluation = _evaluation(
        evidence=evidence,
        target_evidence=target_evidence,
        box=execution_box,
        sequence=evaluation_sequence,
        decision="CANDIDATE",
        reasons=("TRADEPLAN_CANDIDATE_CREATED",),
        evidence_hash=evidence_hash,
        material_hash=material_hash,
        result_id=candidate.tradeplan_id,
    )
    return TradePlanCandidateReductionResultV2(
        decision="CANDIDATE",
        reason_code="TRADEPLAN_CANDIDATE_CREATED",
        evaluation=evaluation,
        candidate=candidate,
        previous_candidate=current_candidate,
        transition=transition,
        target_map=target_map,
    )


__all__ = [
    "derive_structural_stop_authority_v1",
    "derive_structural_target_map_v1",
    "intersect_price_intervals_v1",
    "select_nearest_structural_target_v1",
    "solve_tradeplan_candidate_v2",
    "structural_target_authority_hash_v1",
    "structural_target_id_v1",
]
