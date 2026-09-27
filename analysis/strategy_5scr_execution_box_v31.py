"""Canonical ExecutionBoxV31 builder — A3 (RATIFIED 2026-09-22), owner implementation GO 2026-09-22.

Consumes existing upstream truth only (R4): DirectionalThesisV31 + its status, StructuralProofEvidenceV31,
ContextRouteEvaluationV31, PressureRangeV31, StructuralTargetSelectionV31. No reasoning engine is duplicated here:
every upstream verdict is read, never recomputed. No fallback exists to M1, ExecutionBoxV1, a generic interval or
legacy geometry. The builder never solves SL/TP/RR, never reads a broker quote and never activates a route.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import TypeAdapter, ValidationError

from contracts.strategy_5scr_context_epoch_v31 import ROUTE_PERMITTING_OUTCOMES, ContextRouteEvaluationV31
from contracts.strategy_5scr_directional_thesis_v1 import ClosedCandleAuthorityRefV1
from contracts.strategy_5scr_directional_thesis_v31 import DirectionalThesisStatusV31, DirectionalThesisV31
from contracts.strategy_5scr_execution_box_v31 import (
    BOX_POLICIES_V31,
    CANONICAL_ROUTES_V31,
    TERMINAL_BOX_STATES_V31,
    ExecutionBoxDecisionV31,
    ExecutionBoxLineageV31,
    ExecutionBoxMaterialV31,
    ExecutionBoxPolicyV31,
    ExecutionBoxState,
    ExecutionBoxTransitionV31,
    ExecutionBoxVersionV31,
    execution_box_id_v31,
    material_box_hash_v31,
)
from contracts.strategy_5scr_net_geometry_v31 import Price
from contracts.strategy_5scr_pressure_range_v31 import PressureRangeV31
from contracts.strategy_5scr_structural_proof_v31 import StructuralProofEvidenceV31
from contracts.strategy_5scr_structural_target_canonical_v31 import StructuralTargetSelectionV31

_PRICE = TypeAdapter(Price)


def canonical_price_v31(value: float | Decimal) -> Decimal:
    """A3-05: cross the float boundary once with Decimal(str(x)); reject, never round, what does not fit Price.

    No broker tick-size quantization happens here or anywhere in strategy geometry.
    """

    if isinstance(value, bool) or not isinstance(value, float | Decimal):
        raise TypeError("CANONICAL_PRICE_REQUIRES_FLOAT_OR_DECIMAL")
    decimal = Decimal(str(value)) if isinstance(value, float) else value
    try:
        return _PRICE.validate_python(decimal)
    except ValidationError as error:
        raise ValueError("PRICE_DOES_NOT_FIT_CANONICAL_PRICE") from error


def _completion_candle(proof: StructuralProofEvidenceV31) -> ClosedCandleAuthorityRefV1:
    (candle,) = [c for c in proof.m15_source_candles if c.candle_evidence_id == proof.m15_completion_candle_id]
    return candle


def derive_box_material_v31(
    policy: ExecutionBoxPolicyV31, proof: StructuralProofEvidenceV31, direction: str
) -> ExecutionBoxMaterialV31 | str:
    """A3-R1 / A3-R2 geometry. Returns the material projection, or a reason code when no canonical box exists."""

    if proof.proof_class != policy.proof_class or proof.m15_completion_kind != policy.completion_kind:
        return "PROOF_FORM_NOT_ELIGIBLE_FOR_ROUTE_POLICY"
    level = canonical_price_v31(proof.m15_break_evidence.level)  # L, the break/reference level
    completion = _completion_candle(proof)  # C
    c_low, c_high = canonical_price_v31(completion.low), canonical_price_v31(completion.high)
    if policy.route == "BREAK_RETEST":
        low, high = (c_low, level) if direction == "BUY" else (level, c_high)
    else:
        # Strict accepted-side guard: never degenerate, never the full acceptance candle, no fallback.
        if direction == "BUY" and not c_low > level:
            return "ACCEPTANCE_SIDE_GUARD_FAILED"
        if direction == "SELL" and not c_high < level:
            return "ACCEPTANCE_SIDE_GUARD_FAILED"
        low, high = (level, c_low) if direction == "BUY" else (c_high, level)
    if low > high:
        return "EXECUTION_BOX_BOUNDS_INVERTED"
    return ExecutionBoxMaterialV31(
        box_low=low,
        box_high=high,
        structural_proof_id=proof.proof_id,
        context_epoch_id=proof.context_epoch_id,
        freeze_evidence_id=completion.candle_evidence_id,
    )


def _no_box(reason: str) -> ExecutionBoxDecisionV31:
    return ExecutionBoxDecisionV31(outcome="NO_CANONICAL_BOX", reason_code=reason, version=None, transitions=())


def _prerequisite_failure(
    *,
    thesis: DirectionalThesisV31,
    thesis_status: DirectionalThesisStatusV31,
    proof: StructuralProofEvidenceV31,
    route_evaluation: ContextRouteEvaluationV31,
    pressure_range: PressureRangeV31,
    target_selection: StructuralTargetSelectionV31,
    decision_time: datetime,
) -> str | None:
    """Every BUILDING prerequisite (A3-R1/R2 common predicate). The first failure is returned; None means all hold."""

    route = thesis.selected_route
    if route not in CANONICAL_ROUTES_V31:
        return "ROUTE_UNKNOWN_REJECTED"
    if route not in BOX_POLICIES_V31:
        return "ROUTE_NOT_YET_DEFINED_NO_CANONICAL_BOX"
    if proof.m15_completion_kind == "FAILED_RECLAIM":
        return "FAILED_RECLAIM_UNMAPPED_NO_CANONICAL_BOX"
    # Thesis: authoritative (derived from its own state) and bound to exactly this proof.
    if thesis_status.strategy_thesis_id != thesis.strategy_thesis_id or not thesis_status.direction_authority:
        return "THESIS_NOT_AUTHORITATIVE"
    if (thesis_status.bound_structural_proof_id, thesis_status.bound_structural_proof_hash) != (
        proof.proof_id,
        proof.material_evidence_hash,
    ):
        return "PROOF_NOT_BOUND_TO_THESIS"
    # One lineage: thesis, proof and route evaluation name the same lifecycle, epoch, evaluation, route, direction.
    if not (
        thesis.strategy_lifecycle_id == proof.strategy_lifecycle_id == route_evaluation.strategy_lifecycle_id
        and thesis.context_epoch_id == proof.context_epoch_id == route_evaluation.context_epoch_id
        and thesis.context_route_evaluation_id == proof.context_route_evaluation_id == route_evaluation.evaluation_id
        and thesis.canonical_symbol == proof.canonical_symbol == route_evaluation.canonical_symbol
        and thesis.direction == proof.proof_direction == route_evaluation.evaluated_direction
    ):
        return "UPSTREAM_LINEAGE_MISMATCH"
    if route_evaluation.outcome not in ROUTE_PERMITTING_OUTCOMES or not (
        route == proof.selected_route == route_evaluation.selected_route
    ):
        return "ROUTE_NOT_PERMITTED_BY_ROUTE_EVALUATION"
    # PressureRange authority is a box prerequisite (Q-R5), never a target predicate.
    if pressure_range.strategy_lifecycle_id != thesis.strategy_lifecycle_id:
        return "PRESSURE_RANGE_LINEAGE_MISMATCH"
    if not pressure_range.structural_authority:
        return "PRESSURE_RANGE_WITHOUT_STRUCTURAL_AUTHORITY"
    if not (
        target_selection.status == "SELECTED"
        and target_selection.selected_target is not None
        and target_selection.strategy_thesis_id == thesis.strategy_thesis_id
        and target_selection.thesis_direction == thesis.direction
        and target_selection.canonical_symbol == thesis.canonical_symbol
    ):
        return "STRUCTURAL_TARGET_NOT_SELECTED"
    # Future-evidence prohibition: every input closed and observed at or before decision_time.
    if (
        _completion_candle(proof).close_time_utc > decision_time
        or proof.m15_closed_at > decision_time
        or pressure_range.observed_through_utc > decision_time
        or target_selection.decision_time > decision_time
        or route_evaluation.evaluated_at > decision_time
    ):
        return "FUTURE_EVIDENCE_REJECTED"
    return None


def build_execution_box_v31(
    *,
    thesis: DirectionalThesisV31,
    thesis_status: DirectionalThesisStatusV31,
    proof: StructuralProofEvidenceV31,
    route_evaluation: ContextRouteEvaluationV31,
    pressure_range: PressureRangeV31,
    target_selection: StructuralTargetSelectionV31,
    decision_time: datetime,
    previous: ExecutionBoxVersionV31 | None = None,
    previous_state: ExecutionBoxState | None = None,
    next_ordinal: int = 0,
) -> ExecutionBoxDecisionV31:
    """Build version 1, or re-evaluate an existing logical box (``previous``).

    Re-evaluation re-derives the material projection: unchanged projection → NO_MATERIAL_CHANGE (no version,
    whatever lineage moved); changed projection → version n + 1 and the predecessor SUPERSEDED in the same ordered
    transaction. A failed prerequisite yields NO_CANONICAL_BOX; retiring the predecessor is then
    ``retire_execution_box_v31`` with or without a successor (A3-10).
    """

    failure = _prerequisite_failure(
        thesis=thesis,
        thesis_status=thesis_status,
        proof=proof,
        route_evaluation=route_evaluation,
        pressure_range=pressure_range,
        target_selection=target_selection,
        decision_time=decision_time,
    )
    if failure is not None:
        return _no_box(failure)
    policy = BOX_POLICIES_V31[thesis.selected_route]
    material = derive_box_material_v31(policy, proof, thesis.direction)
    if isinstance(material, str):
        return _no_box(material)
    box_id = execution_box_id_v31(
        strategy_thesis_id=thesis.strategy_thesis_id,
        route=policy.route,
        box_policy_id=policy.box_policy_id,
        box_policy_version=policy.box_policy_version,
    )
    material_hash = material_box_hash_v31(material)
    if previous is not None:
        if previous.execution_box_id != box_id:
            raise ValueError("REEVALUATION_ACROSS_DIFFERENT_LOGICAL_BOXES")
        if previous_state is None or previous_state in TERMINAL_BOX_STATES_V31:
            raise ValueError("TERMINAL_BOX_IS_NEVER_RESURRECTED")
        if previous.material_box_hash == material_hash:
            return ExecutionBoxDecisionV31(
                outcome="NO_MATERIAL_CHANGE", reason_code="MATERIAL_PROJECTION_UNCHANGED", version=None, transitions=()
            )
    completion = _completion_candle(proof)
    version = ExecutionBoxVersionV31(
        execution_box_id=box_id,
        box_version=1 if previous is None else previous.box_version + 1,
        strategy_thesis_id=thesis.strategy_thesis_id,
        strategy_lifecycle_id=thesis.strategy_lifecycle_id,
        canonical_symbol=thesis.canonical_symbol,
        direction=thesis.direction,
        route=policy.route,
        box_policy_id=policy.box_policy_id,
        box_policy_version=policy.box_policy_version,
        material=material,
        material_box_hash=material_hash,
        previous_box_version=None if previous is None else previous.box_version,
        previous_material_box_hash=None if previous is None else previous.material_box_hash,
        lineage=ExecutionBoxLineageV31(
            pressure_range_id=pressure_range.pressure_range_id,
            target_id=target_selection.selected_target.target_id,  # type: ignore[union-attr]
            structural_proof_hash=proof.material_evidence_hash,
            context_route_evaluation_id=route_evaluation.evaluation_id,
            freeze_evidence_close_utc=completion.close_time_utc,
        ),
    )
    transitions: list[ExecutionBoxTransitionV31] = []
    ordinal = next_ordinal
    if previous is not None:
        transitions.append(
            ExecutionBoxTransitionV31(
                execution_box_id=previous.execution_box_id,
                box_version=previous.box_version,
                ordinal=ordinal,
                from_state=previous_state,
                to_state="SUPERSEDED",
                reason_code="BOX_SUPERSEDED",
                authority_time=decision_time,
                evidence_id=version.material_box_hash,
            )
        )
        ordinal += 1
    # Q-R1: BUILDING and FROZEN share the completion close as authority time; the ordinal orders them.
    for from_state, to_state, reason in (
        (None, "BUILDING", "BOX_BUILDING"),
        ("BUILDING", "FROZEN", policy.freeze_reason),
    ):
        transitions.append(
            ExecutionBoxTransitionV31(
                execution_box_id=box_id,
                box_version=version.box_version,
                ordinal=ordinal,
                from_state=from_state,  # type: ignore[arg-type]
                to_state=to_state,  # type: ignore[arg-type]
                reason_code=reason,
                authority_time=completion.close_time_utc,
                evidence_id=completion.candle_evidence_id,
            )
        )
        ordinal += 1
    return ExecutionBoxDecisionV31(
        outcome="BOX_BUILT_AND_FROZEN" if previous is None else "NEW_BOX_VERSION",
        reason_code=policy.freeze_reason,
        version=version,
        transitions=tuple(transitions),
    )


def retire_execution_box_v31(
    version: ExecutionBoxVersionV31,
    current_state: ExecutionBoxState,
    *,
    successor: ExecutionBoxVersionV31 | None,
    authority_time: datetime,
    ordinal: int,
    evidence_id: str | None = None,
) -> ExecutionBoxTransitionV31:
    """A3-10: a valid successor exists → SUPERSEDED; basis lost with no successor → INVALIDATED.

    Loss of basis and a replacement derived in the same re-evaluation transaction is SUPERSEDED.
    """

    if current_state in TERMINAL_BOX_STATES_V31:
        raise ValueError("TERMINAL_BOX_IS_NEVER_RESURRECTED")
    if successor is not None:
        if successor.strategy_thesis_id != version.strategy_thesis_id:
            raise ValueError("SUCCESSOR_MUST_SHARE_THE_THESIS")
        if (successor.execution_box_id, successor.box_version) == (version.execution_box_id, version.box_version):
            raise ValueError("A_BOX_CANNOT_SUCCEED_ITSELF")
    superseded = successor is not None
    return ExecutionBoxTransitionV31(
        execution_box_id=version.execution_box_id,
        box_version=version.box_version,
        ordinal=ordinal,
        from_state=current_state,
        to_state="SUPERSEDED" if superseded else "INVALIDATED",
        reason_code="BOX_SUPERSEDED" if superseded else "BOX_INVALIDATED",
        authority_time=authority_time,
        evidence_id=successor.material_box_hash if successor is not None else evidence_id,
    )


def boundary_level_v31(version: ExecutionBoxVersionV31) -> Decimal:
    """L recovered from the ratified geometry: BREAK_RETEST BUY [C.low, L] / SELL [L, C.high];
    BREAKOUT_ACCEPTANCE BUY [L, C.low] / SELL [C.high, L]."""

    buy = version.direction == "BUY"
    if version.route == "BREAK_RETEST":
        return version.material.box_high if buy else version.material.box_low
    return version.material.box_low if buy else version.material.box_high


def post_freeze_invalidation_v31(
    version: ExecutionBoxVersionV31,
    current_state: ExecutionBoxState,
    candle: ClosedCandleAuthorityRefV1,
    *,
    decision_time: datetime,
) -> bool:
    """Q-R3: after FROZEN, an authoritative closed M15 close beyond L removes the route/box basis.

    BUY close < L, SELL close > L; close == L does not. Evidence must be strictly after the freeze evidence and at
    or before decision_time. This is a route-validity event, never a stop loss.
    """

    if current_state != "FROZEN":
        raise ValueError("POST_FREEZE_INVALIDATION_REQUIRES_A_FROZEN_BOX")
    if candle.symbol != version.canonical_symbol or candle.timeframe != "M15":
        raise ValueError("INVALIDATION_EVIDENCE_MUST_BE_SAME_SYMBOL_M15")
    if candle.candle_evidence_id == version.material.freeze_evidence_id:
        raise ValueError("FREEZE_EVIDENCE_CANNOT_INVALIDATE_ITS_OWN_BOX")
    if not candle.close_time_utc > version.lineage.freeze_evidence_close_utc:
        raise ValueError("INVALIDATION_EVIDENCE_NOT_AFTER_FREEZE")
    if candle.close_time_utc > decision_time:
        raise ValueError("FUTURE_INVALIDATION_EVIDENCE_REJECTED")
    close = canonical_price_v31(candle.close)
    level = boundary_level_v31(version)
    return close < level if version.direction == "BUY" else close > level


def requires_box_reevaluation_for_target_fact_v31(fact: str) -> bool:
    """A3-07: an obligation only. The resulting state is never mapped from the fact."""

    if fact not in {"TARGET_UNCHANGED", "TARGET_MATERIAL_CHANGE", "TARGET_NO_LONGER_ELIGIBLE", "TARGET_INVALIDATED"}:
        raise ValueError("UNKNOWN_TARGET_REVISION_FACT")
    return fact != "TARGET_UNCHANGED"


def requires_box_reevaluation_for_range_change_v31(change: str) -> bool:
    """A3-06: any A1-12 class requires re-derivation; it never forces a version by itself."""

    if change not in {"MATERIAL_RANGE_CHANGE", "COVERAGE_CHANGE", "EVIDENCE_REFRESH", "NO_MATERIAL_CHANGE"}:
        raise ValueError("UNKNOWN_PRESSURE_RANGE_CHANGE")
    return change != "NO_MATERIAL_CHANGE"


__all__ = [
    "boundary_level_v31",
    "build_execution_box_v31",
    "canonical_price_v31",
    "derive_box_material_v31",
    "post_freeze_invalidation_v31",
    "requires_box_reevaluation_for_range_change_v31",
    "requires_box_reevaluation_for_target_fact_v31",
    "retire_execution_box_v31",
]
