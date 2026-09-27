"""Pure gap #10 producer: promote closed-candle witnesses to StructuralProofEvidenceV31 (CONTINUATION only).

Inputs are an active ContextEpochV31, a #495 route evaluation, candle witnesses in their canonical positions and
a hash-bound StructuralPatternRegistryV31. No thesis, no hypothesis input (a proof never edits a hypothesis),
no wall clock, no geometry, risk or broker state.

Requalified on #504 (2026-09-20): the S1B ``AnalysisLifecycleV31`` is an explicit input and the epoch and the
evaluation must bind to it exactly. The admission class is never read, so a proof is identical whether the
lifecycle is currently MATURE_ADVISORY or CANONICAL_RAW; authority never travels through this object.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from analysis.strategy_5scr_context_epoch_v31 import project_context_route_receipt_v31
from analysis.strategy_5scr_pressure_hypothesis_v31 import TERMINAL_LIFECYCLE_STATES_V31
from contracts.strategy_5scr_analysis_lifecycle_v31 import AnalysisLifecycleV31
from contracts.strategy_5scr_candle_identity import candle_evidence_hash, candle_material_hash
from contracts.strategy_5scr_context_epoch_v31 import ContextEpochV31, ContextRouteEvaluationV31
from contracts.strategy_5scr_context_route_v31 import context_route_receipt_hash_v31
from contracts.strategy_5scr_directional_thesis_v1 import ClosedCandleAuthorityRefV1, classify_m15_completion
from contracts.strategy_5scr_structural_proof_v31 import (
    StructuralLevelEvidenceV31,
    StructuralPatternRegistryV31,
    StructuralProofEvidenceV31,
    structural_material_hash_v31,
    structural_proof_id_v31,
)


@dataclass(frozen=True)
class StructuralProofDecisionV31:
    outcome: Literal["PROMOTED", "NOT_PROMOTED"]
    reason_code: str
    proof: StructuralProofEvidenceV31 | None = None


def _no(reason: str) -> StructuralProofDecisionV31:
    return StructuralProofDecisionV31("NOT_PROMOTED", reason)


_CONTEXT_REFUSAL: dict[str, str] = {
    # Counter-pressure proof is deferred by design (gap #10 decision) and never falls back to continuation.
    "AUTHORIZE_PROOF_REQUIRED_COUNTER_PRESSURE": "COUNTER_PRESSURE_PROOF_NOT_IMPLEMENTED_BY_DESIGN",
    "DEFER": "CONTEXT_DEFERRED_NO_PROOF_PROMOTION",
}


def build_structural_proof_v31(
    *,
    lifecycle: AnalysisLifecycleV31,
    epoch: ContextEpochV31,
    evaluation: ContextRouteEvaluationV31,
    proof_direction: Literal["BUY", "SELL"],
    h1_witnesses: tuple[ClosedCandleAuthorityRefV1, ...],
    m15_witnesses: tuple[ClosedCandleAuthorityRefV1, ...],
    level_version: str,
    pattern_id: str,
    registry: StructuralPatternRegistryV31 | None,
    decision_at: datetime,
) -> StructuralProofDecisionV31:
    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ValueError("decision_at must be timezone-aware")
    if registry is None:
        return _no("STRUCTURAL_PATTERN_REGISTRY_MISSING")
    registry = StructuralPatternRegistryV31.model_validate(registry.model_dump())
    # Lineage root (#503/#504). The admission class is deliberately not read anywhere in this function.
    lifecycle = AnalysisLifecycleV31.model_validate(lifecycle.model_dump())
    if (
        epoch.strategy_lifecycle_id != lifecycle.strategy_lifecycle_id
        or epoch.market_episode_id != lifecycle.market_episode_id
        or epoch.canonical_symbol != lifecycle.symbol
    ):
        return _no("EPOCH_LIFECYCLE_MISMATCH")
    if evaluation.strategy_lifecycle_id != lifecycle.strategy_lifecycle_id:
        return _no("EVALUATION_LIFECYCLE_MISMATCH")
    if lifecycle.state in TERMINAL_LIFECYCLE_STATES_V31:
        return _no("LIFECYCLE_TERMINAL")
    # Context gate (#495), deliberately a SINGLE gate: only ALIGN with a selected route may promote. Each refused
    # outcome keeps its own reason code, so no ordering between separate checks can let an outcome slip through.
    if evaluation.outcome != "ALIGN" or evaluation.selected_route is None:
        return _no(_CONTEXT_REFUSAL.get(evaluation.outcome, "CONTEXT_ROUTE_NOT_PERMITTED"))
    if evaluation.context_epoch_id != epoch.context_epoch_id:
        return _no("EVALUATION_EPOCH_MISMATCH")
    if not epoch.valid_from <= decision_at < epoch.valid_until:
        return _no("CONTEXT_EPOCH_NOT_ACTIVE")
    if proof_direction != evaluation.evaluated_direction:
        return _no("PROOF_DIRECTION_NOT_ROUTE_DIRECTION")
    if proof_direction not in epoch.material.allowed_directions:
        return _no("DIRECTION_OUTSIDE_LEGAL_DOMAIN")
    route = evaluation.selected_route
    pattern = registry.pattern(pattern_id, route)
    if pattern is None:
        return _no("PATTERN_NOT_IN_REGISTRY")
    if len(h1_witnesses) != pattern.h1_witness_count or len(m15_witnesses) != pattern.m15_witness_count:
        return _no("PATTERN_WITNESS_COUNT_INVALID")
    # Candle authority (§11.5): closed as of the decision, no future leakage, content-bound, in scope.
    for timeframe, candles in (("H1", h1_witnesses), ("M15", m15_witnesses)):
        for candle in candles:
            candle = ClosedCandleAuthorityRefV1.model_validate(candle.model_dump())
            if candle.symbol != epoch.canonical_symbol or candle.timeframe != timeframe:
                return _no("CANDLE_SCOPE_MISMATCH")
            if candle.material_candle_hash != candle_material_hash(
                candle
            ) or candle.candle_evidence_id != candle_evidence_hash(candle):
                return _no("CANDLE_HASH_MISMATCH")
            if candle.open_time_utc > decision_at:
                return _no("FUTURE_LEAKAGE_BLOCK")
            if candle.close_time_utc > decision_at:
                return _no("CANDLE_NOT_CLOSED_AS_OF_DECISION")
    anchor, confirmation = h1_witnesses
    reference, breaking, completion = m15_witnesses
    if pattern.adjacent_witnesses_required and not (
        anchor.close_time_utc == confirmation.open_time_utc
        and reference.close_time_utc == breaking.open_time_utc
        and breaking.close_time_utc == completion.open_time_utc
    ):
        return _no("PATTERN_WITNESS_GAP")
    if not (
        anchor.close_time_utc <= confirmation.close_time_utc <= breaking.close_time_utc < completion.close_time_utc
        and reference.close_time_utc <= breaking.close_time_utc
        and completion.close_time_utc <= decision_at
    ):
        return _no("PROOF_SEQUENCE_INVALID")
    buy = proof_direction == "BUY"
    h1_level = anchor.high if buy else anchor.low
    if not (confirmation.close > h1_level if buy else confirmation.close < h1_level):
        return _no("H1_STRUCTURE_UNCONFIRMED")  # SSOT §21.5 reason code
    m15_level = reference.high if buy else reference.low
    if not (breaking.close > m15_level if buy else breaking.close < m15_level):
        return _no("M15_ORDERED_PROOF_MISSING")  # SSOT §21.5 reason code
    kind = classify_m15_completion(proof_direction, completion, m15_level)
    if kind is None or kind not in pattern.completion_kinds:
        return _no("M15_ORDERED_PROOF_MISSING")

    receipt = project_context_route_receipt_v31(epoch, evaluation)
    assert receipt is not None  # ALIGN always projects
    body: dict[str, Any] = {
        "proof_id": structural_proof_id_v31(
            strategy_lifecycle_id=epoch.strategy_lifecycle_id,
            context_epoch_id=epoch.context_epoch_id,
            proof_direction=proof_direction,
            selected_route=route,
            level_version=level_version,
            h1_confirmation_candle_id=confirmation.candle_evidence_id,
            m15_break_candle_id=breaking.candle_evidence_id,
            m15_completion_candle_id=completion.candle_evidence_id,
            m15_completion_kind=kind,
            pattern_registry_hash=registry.registry_hash,
        ),
        "strategy_lifecycle_id": epoch.strategy_lifecycle_id,
        "market_episode_id": epoch.market_episode_id,
        "context_epoch_id": epoch.context_epoch_id,
        "context_route_evaluation_id": evaluation.evaluation_id,
        "context_route_receipt_hash": context_route_receipt_hash_v31(receipt),
        "canonical_symbol": epoch.canonical_symbol,
        "proof_class": pattern.proof_class,
        "proof_direction": proof_direction,
        "selected_route": route,
        "level_version": level_version,
        "pattern_id": pattern.pattern_id,
        "pattern_registry_version": registry.registry_version,
        "pattern_registry_hash": registry.registry_hash,
        "h1_source_candles": (anchor, confirmation),
        "m15_source_candles": (reference, breaking, completion),
        "h1_closed_at": confirmation.close_time_utc,
        "h1_structure_evidence": StructuralLevelEvidenceV31(
            rule=pattern.h1_rule,
            reference_candle_id=anchor.candle_evidence_id,
            level=h1_level,
            evidence_candle_id=confirmation.candle_evidence_id,
            evidence_close=confirmation.close,
        ),
        "m15_break_candle_id": breaking.candle_evidence_id,
        "m15_break_evidence": StructuralLevelEvidenceV31(
            rule=pattern.m15_break_rule,
            reference_candle_id=reference.candle_evidence_id,
            level=m15_level,
            evidence_candle_id=breaking.candle_evidence_id,
            evidence_close=breaking.close,
        ),
        "m15_completion_kind": kind,
        "m15_completion_candle_id": completion.candle_evidence_id,
        "m15_closed_at": completion.close_time_utc,
        "source_evidence_ids": tuple(c.candle_evidence_id for c in (*h1_witnesses, *m15_witnesses)),
    }
    probe = StructuralProofEvidenceV31.model_construct(**body, material_evidence_hash="sha256:" + "0" * 64)
    proof = StructuralProofEvidenceV31.model_validate(
        {**body, "material_evidence_hash": structural_material_hash_v31(probe)}
    )
    return StructuralProofDecisionV31("PROMOTED", "STRUCTURAL_PROOF_PROMOTED", proof)


__all__ = ["StructuralProofDecisionV31", "build_structural_proof_v31"]
