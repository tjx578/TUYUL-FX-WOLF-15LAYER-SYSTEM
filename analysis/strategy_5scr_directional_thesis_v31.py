"""Pure gap #11 producer: open, confirm, and terminate DirectionalThesisV31 (owner decisions D1–D9, 2026-09-19).

Inputs are immutable upstream objects: an active ContextEpochV31 and its #495 evaluation, the #494 hypothesis ledger
(read only), a #497 StructuralProofEvidenceV31, closed candles after that proof, and hashed policies. No wall clock,
no global safety input (a global veto is an overlay and can never change a thesis), no geometry, risk or broker.

A thesis never writes a hypothesis transition and never edits a proof. It never re-runs the H1/M15 proof
predicates either: it binds the #497 proof by reference and only asks whether that proof is still ACTIONABLE for
binding (D5): no later canonical structural evidence invalidates it, proven over contiguous closed candles.

Requalified on #504 (2026-09-20): the S1B ``AnalysisLifecycleV31`` is an explicit input at BOTH creation and
confirmation. It is read for containment only - never for identity, and never to widen authority. A
MATURE_ADVISORY lineage may reach STRUCTURALLY_CONFIRMED (analysis direction authority) while staying
SHADOW_ONLY; a CANONICAL_RAW thesis additionally requires that its admission is canonical in this lifecycle,
so an advisory candidate is never reused as canonical after an upgrade (§7A.6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError

from analysis.strategy_5scr_analysis_lifecycle_v31 import require_canonical_lineage_v31
from analysis.strategy_5scr_context_epoch_v31 import project_context_route_receipt_v31
from analysis.strategy_5scr_pressure_hypothesis_v31 import TERMINAL_LIFECYCLE_STATES_V31
from analysis.strategy_5scr_pressure_hypothesis_v31 import current_state as hypothesis_state
from contracts.strategy_5scr_analysis_lifecycle_v31 import AUTHORITY_RANK, AnalysisLifecycleV31
from contracts.strategy_5scr_candle_identity import candle_evidence_hash, candle_material_hash
from contracts.strategy_5scr_context_epoch_v31 import (
    ContextEpochTerminationV31,
    ContextEpochV31,
    ContextRouteEvaluationV31,
)
from contracts.strategy_5scr_context_route_v31 import context_route_receipt_hash_v31
from contracts.strategy_5scr_directional_thesis_v1 import ClosedCandleAuthorityRefV1
from contracts.strategy_5scr_directional_thesis_v31 import (
    CREATION_STATE,
    TERMINAL_STATES,
    DirectionalThesisStatusV31,
    DirectionalThesisStoreV31,
    DirectionalThesisTransitionV31,
    DirectionalThesisV31,
    StructuralProofActionabilityPolicyV31,
    ThesisClassRegistryV31,
    ThesisClockPolicyV31,
    direction_authority_v31,
    thesis_id_v31,
    thesis_record_hash_v31,
)
from contracts.strategy_5scr_identity_v31 import canonical_sha256_v31
from contracts.strategy_5scr_pressure_hypothesis_v31 import (
    TERMINAL_STATES as HYPOTHESIS_TERMINAL_STATES,
)
from contracts.strategy_5scr_pressure_hypothesis_v31 import (
    PressureDirectionalHypothesisV31,
    PressureHypothesisStoreV31,
    hypothesis_record_hash_v31,
)
from contracts.strategy_5scr_structural_proof_v31 import StructuralProofEvidenceV31

Outcome = Literal[
    "CREATED",
    "ALREADY_OPEN",
    "NOT_CREATED",
    "CONFIRMED",
    "ALREADY_CONFIRMED",
    "NOT_CONFIRMED",
    "TERMINATED",
    "NOT_CHANGED",
]
_STEP = {"H1": timedelta(hours=1), "M15": timedelta(minutes=15)}


@dataclass(frozen=True)
class ThesisDecisionV31:
    outcome: Outcome
    reason_code: str
    thesis: DirectionalThesisV31 | None = None
    transition: DirectionalThesisTransitionV31 | None = None


def _aware(moment: datetime, name: str) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _lineage_refusal(
    lifecycle: AnalysisLifecycleV31,
    *,
    epoch: ContextEpochV31,
    admission_id: UUID,
    admission_class: str,
) -> str | None:
    """Containment gate shared by creation and confirmation. Reads the lifecycle; grants nothing.

    The lifecycle's CURRENT authority may never be lower than the class this thesis claims, and a claim of
    CANONICAL_RAW additionally requires that the originating admission is canonical in this very lifecycle.
    """

    if (
        epoch.strategy_lifecycle_id != lifecycle.strategy_lifecycle_id
        or epoch.market_episode_id != lifecycle.market_episode_id
        or epoch.canonical_symbol != lifecycle.symbol
    ):
        return "EPOCH_LIFECYCLE_MISMATCH"
    if lifecycle.state in TERMINAL_LIFECYCLE_STATES_V31:
        return "LIFECYCLE_TERMINAL"
    if AUTHORITY_RANK[lifecycle.highest_analysis_authority] < AUTHORITY_RANK[admission_class]:
        return "LIFECYCLE_AUTHORITY_BELOW_THESIS_CLASS"
    if admission_class == "CANONICAL_RAW":
        return require_canonical_lineage_v31(lifecycle, admission_id)
    return None


def current_thesis_state(transitions: tuple[DirectionalThesisTransitionV31, ...]) -> str:
    return transitions[-1].to_state if transitions else CREATION_STATE


def _confirmation(transitions: tuple[DirectionalThesisTransitionV31, ...]) -> DirectionalThesisTransitionV31 | None:
    return next((t for t in transitions if t.to_state == "STRUCTURALLY_CONFIRMED"), None)


def thesis_status_v31(store: DirectionalThesisStoreV31, strategy_thesis_id: UUID) -> DirectionalThesisStatusV31:
    record = store.get_record(strategy_thesis_id)
    if record is None:
        raise ValueError("THESIS_NOT_FOUND")
    history = store.transitions(strategy_thesis_id)
    state = current_thesis_state(history)
    bound = _confirmation(history)
    return DirectionalThesisStatusV31(
        strategy_thesis_id=strategy_thesis_id,
        state=state,  # type: ignore[arg-type]
        direction=record.direction,
        direction_authority=direction_authority_v31(state),
        analysis_admission_class=record.analysis_admission_class,
        promotion_eligibility=record.promotion_eligibility,
        risk_handoff_allowed=record.risk_handoff_allowed,
        bound_structural_proof_id=None if bound is None else bound.bound_structural_proof_id,
        bound_structural_proof_hash=None if bound is None else bound.bound_structural_proof_hash,
    )


def _hypothesis_active(
    hypothesis_store: PressureHypothesisStoreV31,
    hypothesis_id: UUID,
    lifecycle_id: UUID,
    record_hash: str,
    decision_at: datetime,
) -> PressureDirectionalHypothesisV31 | None:
    """Read-only: the hypothesis is the lifecycle's active one, unchanged, non-terminal and inside its clock."""

    record = hypothesis_store.get_record(hypothesis_id)
    if record is None or hypothesis_store.active(lifecycle_id) != hypothesis_id:
        return None
    if hypothesis_record_hash_v31(record) != record_hash:
        return None
    if hypothesis_state(hypothesis_store.transitions(hypothesis_id)) in HYPOTHESIS_TERMINAL_STATES:
        return None
    if not record.valid_from <= decision_at < record.valid_until:
        return None
    return record


def _append(
    store: DirectionalThesisStoreV31,
    record: DirectionalThesisV31,
    *,
    to_state: str,
    reason_code: str,
    material_event_id: str,
    material_event_hash: str,
    occurred_at: datetime,
    binding: dict[str, Any] | None = None,
) -> DirectionalThesisTransitionV31:
    history = store.transitions(record.strategy_thesis_id)
    state = current_thesis_state(history)
    if state in TERMINAL_STATES:
        raise ValueError("TERMINAL_THESIS_NOT_REVIVED")
    if to_state == "EXPIRED":
        deadline = record.context_epoch_valid_until if reason_code == "CONTEXT_EPOCH_EXPIRED" else record.valid_until
        if occurred_at < deadline:
            raise ValueError("EXPIRY_BEFORE_DEADLINE")
    elif occurred_at >= record.valid_until:
        raise ValueError("THESIS_CLOCK_EXPIRED")
    if any(item.material_event_id == material_event_id for item in history):
        raise ValueError("DUPLICATE_MATERIAL_EVENT")
    binding = binding or {}
    payload: dict[str, Any] = {
        "strategy_thesis_id": record.strategy_thesis_id,
        "sequence": len(history) + 1,
        "from_state": state,
        "to_state": to_state,
        "reason_code": reason_code,
        "bound_structural_proof_id": binding.get("bound_structural_proof_id"),
        "bound_structural_proof_hash": binding.get("bound_structural_proof_hash"),
        "actionability_policy_version": binding.get("actionability_policy_version"),
        "actionability_policy_hash": binding.get("actionability_policy_hash"),
        "resolution_evidence_hash": binding.get("resolution_evidence_hash"),
        "material_event_id": material_event_id,
        "material_event_hash": material_event_hash,
        "occurred_at": occurred_at,
        "previous_transition_hash": history[-1].transition_hash if history else None,
    }
    probe = DirectionalThesisTransitionV31.model_construct(**payload, transition_hash="sha256:" + "0" * 64)
    body = {k: v for k, v in probe.model_dump(mode="json").items() if k != "transition_hash"}
    transition = DirectionalThesisTransitionV31.model_validate(
        {**payload, "transition_hash": canonical_sha256_v31(body)}
    )
    store.append_transition(transition)
    if to_state in TERMINAL_STATES and store.active(record.strategy_lifecycle_id) == record.strategy_thesis_id:
        store.swap_active(record.strategy_lifecycle_id, expected=record.strategy_thesis_id, new=None)
    return transition


def _expire_by_clock(store: DirectionalThesisStoreV31, record: DirectionalThesisV31, at: datetime) -> None:
    _append(
        store,
        record,
        to_state="EXPIRED",
        reason_code="CONTEXT_EPOCH_EXPIRED"
        if record.valid_until_bound == "CONTEXT_EPOCH_DEADLINE"
        else "THESIS_CLOCK_EXPIRED",
        material_event_id=f"thesis-clock-expiry:{record.strategy_thesis_id}",
        material_event_hash=canonical_sha256_v31(
            ["EXPIRED", str(record.strategy_thesis_id), record.valid_until.isoformat()]
        ),
        occurred_at=at,
    )


def open_thesis_v31(
    store: DirectionalThesisStoreV31,
    *,
    lifecycle: AnalysisLifecycleV31,
    epoch: ContextEpochV31,
    evaluation: ContextRouteEvaluationV31,
    hypothesis: PressureDirectionalHypothesisV31 | None,
    hypothesis_store: PressureHypothesisStoreV31,
    class_registry: ThesisClassRegistryV31 | None,
    clock_policy: ThesisClockPolicyV31 | None,
    decision_at: datetime,
) -> ThesisDecisionV31:
    """D2: ALIGN + active same-direction hypothesis → thesis PENDING_H1 (no direction authority yet).

    Either admission class may open a thesis. The class is inherited from the hypothesis as provenance and caps
    how far this thesis may ever travel; it never changes the identity and never grants anything.
    """

    _aware(decision_at, "decision_at")
    if class_registry is None:
        return ThesisDecisionV31("NOT_CREATED", "THESIS_CLASS_REGISTRY_MISSING")
    if clock_policy is None:
        return ThesisDecisionV31("NOT_CREATED", "THESIS_CLOCK_POLICY_MISSING")
    class_registry = ThesisClassRegistryV31.model_validate(class_registry.model_dump())
    clock_policy = ThesisClockPolicyV31.model_validate(clock_policy.model_dump())
    # D4: hypothesis-less and counter-pressure theses are not implemented; never fall back to continuation.
    if hypothesis is None:
        return ThesisDecisionV31("NOT_CREATED", "THESIS_WITHOUT_HYPOTHESIS_NOT_IMPLEMENTED_BY_DESIGN")
    if (
        evaluation.outcome == "AUTHORIZE_PROOF_REQUIRED_COUNTER_PRESSURE"
        or evaluation.evaluated_direction != hypothesis.direction
    ):
        return ThesisDecisionV31("NOT_CREATED", "COUNTER_PRESSURE_THESIS_NOT_IMPLEMENTED_BY_DESIGN")
    if evaluation.outcome == "DEFER":
        return ThesisDecisionV31("NOT_CREATED", "CONTEXT_DEFERRED_NO_THESIS")
    if evaluation.outcome == "CONFLICT":
        return ThesisDecisionV31("NOT_CREATED", "CONTEXT_CONFLICT")  # §12.4: same-direction thesis not authorized
    if evaluation.outcome != "ALIGN" or evaluation.selected_route is None:
        return ThesisDecisionV31("NOT_CREATED", "CONTEXT_ROUTE_NOT_PERMITTED")
    if evaluation.context_epoch_id != epoch.context_epoch_id:
        return ThesisDecisionV31("NOT_CREATED", "EVALUATION_EPOCH_MISMATCH")
    if evaluation.pressure_hypothesis_id != hypothesis.pressure_hypothesis_id:
        return ThesisDecisionV31("NOT_CREATED", "EVALUATION_HYPOTHESIS_MISMATCH")
    if (hypothesis.strategy_lifecycle_id, hypothesis.canonical_symbol) != (
        epoch.strategy_lifecycle_id,
        epoch.canonical_symbol,
    ):
        return ThesisDecisionV31("NOT_CREATED", "THESIS_SCOPE_MISMATCH")
    if evaluation.evaluated_at > decision_at:
        return ThesisDecisionV31("NOT_CREATED", "FUTURE_LEAKAGE_BLOCK")
    if not epoch.valid_from <= decision_at < epoch.valid_until:
        return ThesisDecisionV31("NOT_CREATED", "CONTEXT_EPOCH_NOT_ACTIVE")
    if hypothesis.direction not in epoch.material.allowed_directions:
        return ThesisDecisionV31("NOT_CREATED", "DIRECTION_OUTSIDE_DOMAIN")  # §21.5
    hypothesis_hash = hypothesis_record_hash_v31(hypothesis)
    if (
        _hypothesis_active(
            hypothesis_store,
            hypothesis.pressure_hypothesis_id,
            epoch.strategy_lifecycle_id,
            hypothesis_hash,
            decision_at,
        )
        is None
    ):
        return ThesisDecisionV31("NOT_CREATED", "HYPOTHESIS_NOT_ACTIVE")
    route = evaluation.selected_route
    thesis_class = class_registry.thesis_class(route)
    if thesis_class is None:
        return ThesisDecisionV31("NOT_CREATED", "THESIS_CLASS_MAPPING_MISSING")
    if thesis_class != "CONTINUATION":
        return ThesisDecisionV31("NOT_CREATED", "THESIS_CLASS_NOT_IMPLEMENTED_BY_DESIGN")
    lifecycle = AnalysisLifecycleV31.model_validate(lifecycle.model_dump())
    refusal = _lineage_refusal(
        lifecycle,
        epoch=epoch,
        admission_id=hypothesis.strategy_analysis_admission_id,
        admission_class=hypothesis.analysis_admission_class,
    )
    if refusal is not None:
        return ThesisDecisionV31("NOT_CREATED", refusal)

    thesis_id = thesis_id_v31(
        strategy_lifecycle_id=epoch.strategy_lifecycle_id,
        context_epoch_id=epoch.context_epoch_id,
        direction=hypothesis.direction,
        thesis_class=thesis_class,
        selected_route=route,
        pressure_hypothesis_id=hypothesis.pressure_hypothesis_id,
    )
    existing = store.get_record(thesis_id)
    if existing is not None:  # §15.2: the same identity re-observed is never a new thesis and never revived
        if current_thesis_state(store.transitions(thesis_id)) in TERMINAL_STATES:
            return ThesisDecisionV31("NOT_CREATED", "TERMINAL_THESIS_NOT_REVIVED")
        return ThesisDecisionV31("ALREADY_OPEN", "DUPLICATE_THESIS_IDENTITY", existing)
    active_id = store.active(epoch.strategy_lifecycle_id)
    if active_id is not None:
        active = store.get_record(active_id)
        assert active is not None
        if decision_at >= active.valid_until:
            _expire_by_clock(store, active, decision_at)
        if store.active(epoch.strategy_lifecycle_id) is not None:
            return ThesisDecisionV31("NOT_CREATED", "ACTIVE_THESIS_EXISTS", active)  # D6: one per lifecycle
    ttl_deadline = decision_at + timedelta(seconds=clock_policy.ttl_seconds)
    record = DirectionalThesisV31(
        strategy_thesis_id=thesis_id,
        canonical_symbol=epoch.canonical_symbol,
        strategy_lifecycle_id=epoch.strategy_lifecycle_id,
        market_episode_id=epoch.market_episode_id,
        strategy_analysis_admission_id=hypothesis.strategy_analysis_admission_id,
        admission_receipt_hash=hypothesis.admission_receipt_hash,
        analysis_admission_class=hypothesis.analysis_admission_class,
        analysis_authority=hypothesis.analysis_authority,
        promotion_eligibility=hypothesis.promotion_eligibility,
        risk_handoff_allowed=hypothesis.risk_handoff_allowed,
        pressure_hypothesis_id=hypothesis.pressure_hypothesis_id,
        hypothesis_record_hash=hypothesis_hash,
        pressure_authority_mode=hypothesis.pressure_authority_mode,
        pressure_contract_status_at_creation=hypothesis.pressure_contract_status_at_creation,
        context_epoch_id=epoch.context_epoch_id,
        material_context_hash=epoch.material_context_hash,
        context_epoch_valid_until=epoch.valid_until,
        context_route_evaluation_id=evaluation.evaluation_id,
        context_route_evaluation_hash=canonical_sha256_v31(evaluation.model_dump(mode="json")),
        context_route_receipt_hash=context_route_receipt_hash_v31(project_context_route_receipt_v31(epoch, evaluation)),  # type: ignore[arg-type]
        direction=hypothesis.direction,
        thesis_class="CONTINUATION",
        thesis_class_registry_version=class_registry.registry_version,
        thesis_class_registry_hash=class_registry.registry_hash,
        selected_route=route,
        created_at_decision_time=decision_at,
        valid_from=decision_at,
        valid_until=min(ttl_deadline, epoch.valid_until),
        valid_until_bound="THESIS_CLOCK_TTL" if ttl_deadline <= epoch.valid_until else "CONTEXT_EPOCH_DEADLINE",
        clock_ttl_seconds=clock_policy.ttl_seconds,
        clock_policy_version=clock_policy.clock_policy_version,
        clock_policy_hash=clock_policy.policy_hash,
    )
    store.insert_record(record)
    store.swap_active(epoch.strategy_lifecycle_id, expected=None, new=thesis_id)
    return ThesisDecisionV31("CREATED", "THESIS_OPENED_PENDING_H1", record)


def _checked_candle(candle: ClosedCandleAuthorityRefV1) -> ClosedCandleAuthorityRefV1 | None:
    candle = ClosedCandleAuthorityRefV1.model_validate(candle.model_dump())
    if candle.material_candle_hash != candle_material_hash(candle) or candle.candle_evidence_id != candle_evidence_hash(
        candle
    ):
        return None
    return candle


def proof_actionability_failure_v31(
    *,
    proof: StructuralProofEvidenceV31,
    later_h1: tuple[ClosedCandleAuthorityRefV1, ...],
    later_m15: tuple[ClosedCandleAuthorityRefV1, ...],
    policy: StructuralProofActionabilityPolicyV31,
    decision_at: datetime,
) -> tuple[str, str | None] | None:
    """D5: None if the immutable proof is actionable at ``decision_at``; else (reason, invalidating candle id).

    Coverage first (fail closed): every H1/M15 candle that closed after the proof and by ``decision_at`` must be
    supplied, contiguous. Then the earliest invalidating candle wins, by close time.
    """

    policy = StructuralProofActionabilityPolicyV31.model_validate(policy.model_dump())
    _aware(decision_at, "decision_at")
    if proof.m15_closed_at > decision_at:
        return ("FUTURE_LEAKAGE_BLOCK", None)
    for timeframe, candles, start in (("H1", later_h1, proof.h1_closed_at), ("M15", later_m15, proof.m15_closed_at)):
        previous_close = start
        for raw in candles:
            candle = _checked_candle(raw)
            if candle is None:
                return ("CANDLE_HASH_MISMATCH", None)
            if candle.symbol != proof.canonical_symbol or candle.timeframe != timeframe:
                return ("PROOF_ACTIONABILITY_CANDLE_SCOPE_MISMATCH", None)
            if candle.close_time_utc > decision_at:
                return ("FUTURE_LEAKAGE_BLOCK", None)
            if candle.open_time_utc != previous_close:
                return ("PROOF_ACTIONABILITY_EVIDENCE_INCOMPLETE", None)
            previous_close = candle.close_time_utc
        if previous_close + _STEP[timeframe] <= decision_at:
            return ("PROOF_ACTIONABILITY_EVIDENCE_INCOMPLETE", None)

    buy = proof.proof_direction == "BUY"
    failures: list[tuple[datetime, str, str]] = []
    h1_chain = (proof.h1_source_candles[1], *later_h1)
    for anchor, confirmation in zip(h1_chain, h1_chain[1:], strict=False):
        if confirmation.close < anchor.low if buy else confirmation.close > anchor.high:
            failures.append(
                (confirmation.close_time_utc, "PROOF_NOT_ACTIONABLE_COUNTER_H1_BREAK", confirmation.candle_evidence_id)
            )
    level = proof.m15_break_evidence.level
    for candle in later_m15:
        if candle.close <= level if buy else candle.close >= level:
            failures.append(
                (candle.close_time_utc, "PROOF_NOT_ACTIONABLE_M15_BREAK_LEVEL_FAILED", candle.candle_evidence_id)
            )
    if not failures:
        return None
    _, reason, candle_id = min(failures, key=lambda item: item[0])
    return (reason, candle_id)


def confirm_thesis_v31(
    store: DirectionalThesisStoreV31,
    *,
    lifecycle: AnalysisLifecycleV31,
    strategy_thesis_id: UUID,
    proof: StructuralProofEvidenceV31,
    epoch: ContextEpochV31,
    evaluation: ContextRouteEvaluationV31,
    hypothesis_store: PressureHypothesisStoreV31,
    actionability_policy: StructuralProofActionabilityPolicyV31 | None,
    later_h1: tuple[ClosedCandleAuthorityRefV1, ...],
    later_m15: tuple[ClosedCandleAuthorityRefV1, ...],
    decision_at: datetime,
) -> ThesisDecisionV31:
    """D2/D5: PENDING_H1 + actionable complete #497 proof with exact lineage → STRUCTURALLY_CONFIRMED.

    Failures never write. ``evaluation`` is the CURRENT evaluation of the same identity (same id, re-evaluated), so a
    context that has since become DEFER/BLOCK blocks the binding.
    """

    _aware(decision_at, "decision_at")
    if actionability_policy is None:
        return ThesisDecisionV31("NOT_CONFIRMED", "PROOF_ACTIONABILITY_POLICY_MISSING")
    actionability_policy = StructuralProofActionabilityPolicyV31.model_validate(actionability_policy.model_dump())
    record = store.get_record(strategy_thesis_id)
    if record is None:
        return ThesisDecisionV31("NOT_CONFIRMED", "THESIS_NOT_FOUND")
    history = store.transitions(strategy_thesis_id)
    state = current_thesis_state(history)
    if state in TERMINAL_STATES:
        return ThesisDecisionV31("NOT_CONFIRMED", "THESIS_TERMINAL", record)
    bound = _confirmation(history)
    if bound is not None:  # §19.4: the thesis is immutable; another trigger is a child concern, not a rebinding
        reason = (
            "SAME_PROOF_ALREADY_BOUND"
            if bound.bound_structural_proof_id == proof.proof_id
            else "ADDITIONAL_PROOF_NOT_BOUND_CHILD_TRIGGER_OUT_OF_SCOPE"
        )
        return ThesisDecisionV31("ALREADY_CONFIRMED", reason, record, bound)
    if state != "PENDING_H1":
        return ThesisDecisionV31("NOT_CONFIRMED", "THESIS_NOT_PENDING", record)
    # Containment is re-checked at confirmation: this is where analysis direction authority is born.
    lifecycle = AnalysisLifecycleV31.model_validate(lifecycle.model_dump())
    refusal = _lineage_refusal(
        lifecycle,
        epoch=epoch,
        admission_id=record.strategy_analysis_admission_id,
        admission_class=record.analysis_admission_class,
    )
    if refusal is not None:
        return ThesisDecisionV31("NOT_CONFIRMED", refusal, record)
    if not record.valid_from <= decision_at < record.valid_until:
        return ThesisDecisionV31("NOT_CONFIRMED", "THESIS_CLOCK_NOT_ACTIVE", record)
    try:
        proof = StructuralProofEvidenceV31.model_validate(proof.model_dump())
    except ValidationError:
        return ThesisDecisionV31("NOT_CONFIRMED", "STRUCTURAL_PROOF_INVALID", record)
    if proof.proof_direction != record.direction:
        return ThesisDecisionV31("NOT_CONFIRMED", "COUNTER_PRESSURE_THESIS_NOT_IMPLEMENTED_BY_DESIGN", record)
    if (
        proof.strategy_lifecycle_id,
        proof.context_epoch_id,
        proof.canonical_symbol,
        proof.selected_route,
        proof.context_route_evaluation_id,
    ) != (
        record.strategy_lifecycle_id,
        record.context_epoch_id,
        record.canonical_symbol,
        record.selected_route,
        record.context_route_evaluation_id,
    ):
        return ThesisDecisionV31("NOT_CONFIRMED", "PROOF_LINEAGE_MISMATCH", record)
    if proof.proof_class != record.thesis_class:
        return ThesisDecisionV31("NOT_CONFIRMED", "PROOF_CLASS_NOT_THESIS_CLASS", record)
    if (
        epoch.context_epoch_id != record.context_epoch_id
        or evaluation.evaluation_id != record.context_route_evaluation_id
    ):
        return ThesisDecisionV31("NOT_CONFIRMED", "CONTEXT_LINEAGE_MISMATCH", record)
    if not epoch.valid_from <= decision_at < epoch.valid_until:
        return ThesisDecisionV31("NOT_CONFIRMED", "CONTEXT_EPOCH_NOT_ACTIVE", record)
    if evaluation.evaluated_at > decision_at:
        return ThesisDecisionV31("NOT_CONFIRMED", "FUTURE_LEAKAGE_BLOCK", record)
    if evaluation.outcome == "DEFER":
        return ThesisDecisionV31("NOT_CONFIRMED", "CONTEXT_DEFERRED_NO_THESIS_CONFIRMATION", record)
    if evaluation.outcome != "ALIGN" or evaluation.selected_route != record.selected_route:
        return ThesisDecisionV31("NOT_CONFIRMED", "CONTEXT_ROUTE_NOT_PERMITTED", record)
    hypothesis = _hypothesis_active(
        hypothesis_store,
        record.pressure_hypothesis_id,
        record.strategy_lifecycle_id,
        record.hypothesis_record_hash,
        decision_at,
    )
    if hypothesis is None or hypothesis.direction != record.direction:
        return ThesisDecisionV31("NOT_CONFIRMED", "HYPOTHESIS_NOT_ACTIVE", record)
    failure = proof_actionability_failure_v31(
        proof=proof, later_h1=later_h1, later_m15=later_m15, policy=actionability_policy, decision_at=decision_at
    )
    if failure is not None:
        return ThesisDecisionV31("NOT_CONFIRMED", failure[0], record)

    later_ids = [c.candle_evidence_id for c in (*later_h1, *later_m15)]
    resolution = canonical_sha256_v31(
        {
            "strategy_thesis_id": str(record.strategy_thesis_id),
            "structural_proof_id": str(proof.proof_id),
            "structural_proof_hash": proof.material_evidence_hash,
            "context_route_evaluation_hash": canonical_sha256_v31(evaluation.model_dump(mode="json")),
            "context_epoch_id": str(epoch.context_epoch_id),
            "pressure_hypothesis_id": str(record.pressure_hypothesis_id),
            "hypothesis_record_hash": record.hypothesis_record_hash,
            "actionability_policy_hash": actionability_policy.policy_hash,
            "later_candle_ids": later_ids,
        }
    )
    transition = _append(
        store,
        record,
        to_state="STRUCTURALLY_CONFIRMED",
        reason_code="STRUCTURAL_PROOF_BOUND",
        material_event_id=f"proof-binding:{proof.proof_id}",
        material_event_hash=proof.material_evidence_hash,
        occurred_at=decision_at,
        binding={
            "bound_structural_proof_id": proof.proof_id,
            "bound_structural_proof_hash": proof.material_evidence_hash,
            "actionability_policy_version": actionability_policy.policy_version,
            "actionability_policy_hash": actionability_policy.policy_hash,
            "resolution_evidence_hash": resolution,
        },
    )
    return ThesisDecisionV31("CONFIRMED", "STRUCTURAL_PROOF_BOUND", record, transition)


def terminate_thesis_for_epoch_v31(
    store: DirectionalThesisStoreV31, *, strategy_thesis_id: UUID, termination: ContextEpochTerminationV31
) -> ThesisDecisionV31:
    """D6: epoch superseded → SUPERSEDED; epoch expired → EXPIRED. If the thesis clock ran out first, EXPIRED."""

    record = store.get_record(strategy_thesis_id)
    if record is None:
        return ThesisDecisionV31("NOT_CHANGED", "THESIS_NOT_FOUND")
    if termination.context_epoch_id != record.context_epoch_id:
        return ThesisDecisionV31("NOT_CHANGED", "CONTEXT_EPOCH_MISMATCH", record)
    if current_thesis_state(store.transitions(strategy_thesis_id)) in TERMINAL_STATES:
        return ThesisDecisionV31("NOT_CHANGED", "THESIS_ALREADY_TERMINAL", record)
    at = termination.terminated_at
    if at >= record.valid_until:
        _expire_by_clock(store, record, at)
        return ThesisDecisionV31("TERMINATED", "THESIS_EXPIRED", record, store.transitions(strategy_thesis_id)[-1])
    if termination.terminal_state == "EXPIRED":  # an expired epoch at `at` < thesis.valid_until is impossible
        raise ValueError("CONTEXT_EPOCH_EXPIRY_BEFORE_THESIS_DEADLINE")
    transition = _append(
        store,
        record,
        to_state="SUPERSEDED",
        reason_code="THESIS_SUPERSEDED",
        material_event_id=f"context-epoch-superseded:{termination.context_epoch_id}->{termination.superseded_by}",
        material_event_hash=canonical_sha256_v31(termination.model_dump(mode="json")),
        occurred_at=at,
    )
    return ThesisDecisionV31("TERMINATED", "THESIS_SUPERSEDED", record, transition)


def expire_thesis_clock_v31(
    store: DirectionalThesisStoreV31, *, strategy_thesis_id: UUID, decision_at: datetime
) -> ThesisDecisionV31:
    _aware(decision_at, "decision_at")
    record = store.get_record(strategy_thesis_id)
    if record is None:
        return ThesisDecisionV31("NOT_CHANGED", "THESIS_NOT_FOUND")
    if current_thesis_state(store.transitions(strategy_thesis_id)) in TERMINAL_STATES:
        return ThesisDecisionV31("NOT_CHANGED", "THESIS_ALREADY_TERMINAL", record)
    if decision_at < record.valid_until:
        return ThesisDecisionV31("NOT_CHANGED", "THESIS_CLOCK_ACTIVE", record)
    _expire_by_clock(store, record, decision_at)
    return ThesisDecisionV31("TERMINATED", "THESIS_EXPIRED", record, store.transitions(strategy_thesis_id)[-1])


def invalidate_thesis_structurally_v31(
    store: DirectionalThesisStoreV31,
    *,
    strategy_thesis_id: UUID,
    proof: StructuralProofEvidenceV31,
    actionability_policy: StructuralProofActionabilityPolicyV31,
    later_h1: tuple[ClosedCandleAuthorityRefV1, ...],
    later_m15: tuple[ClosedCandleAuthorityRefV1, ...],
    decision_at: datetime,
) -> ThesisDecisionV31:
    """D6: canonical structural invalidation of a CONFIRMED thesis → INVALIDATED (THESIS_INVALIDATED).

    Uses the SAME bound proof and the SAME actionability policy that confirmed it. Missing coverage is never
    read as "still valid" and never as "invalidated": the thesis is left unchanged with the coverage reason.
    """

    _aware(decision_at, "decision_at")
    record = store.get_record(strategy_thesis_id)
    if record is None:
        return ThesisDecisionV31("NOT_CHANGED", "THESIS_NOT_FOUND")
    history = store.transitions(strategy_thesis_id)
    if current_thesis_state(history) != "STRUCTURALLY_CONFIRMED":
        return ThesisDecisionV31("NOT_CHANGED", "THESIS_NOT_STRUCTURALLY_CONFIRMED", record)
    bound = _confirmation(history)
    assert bound is not None
    if (proof.proof_id, proof.material_evidence_hash) != (
        bound.bound_structural_proof_id,
        bound.bound_structural_proof_hash,
    ):
        return ThesisDecisionV31("NOT_CHANGED", "PROOF_IS_NOT_THE_BOUND_PROOF", record)
    if actionability_policy.policy_hash != bound.actionability_policy_hash:
        return ThesisDecisionV31("NOT_CHANGED", "ACTIONABILITY_POLICY_MISMATCH", record)
    if decision_at >= record.valid_until:
        return ThesisDecisionV31("NOT_CHANGED", "THESIS_CLOCK_NOT_ACTIVE", record)
    failure = proof_actionability_failure_v31(
        proof=proof, later_h1=later_h1, later_m15=later_m15, policy=actionability_policy, decision_at=decision_at
    )
    if failure is None:
        return ThesisDecisionV31("NOT_CHANGED", "STRUCTURE_STILL_VALID", record)
    reason, candle_id = failure
    if candle_id is None:
        return ThesisDecisionV31("NOT_CHANGED", reason, record)
    transition = _append(
        store,
        record,
        to_state="INVALIDATED",
        reason_code="THESIS_INVALIDATED",
        material_event_id=f"structural-invalidation:{candle_id}",
        material_event_hash=canonical_sha256_v31([reason, candle_id]),
        occurred_at=decision_at,
    )
    return ThesisDecisionV31("TERMINATED", reason, record, transition)


class InMemoryDirectionalThesisLedgerV31(DirectionalThesisStoreV31):
    """Reference implementation of the durability invariants (not persistence)."""

    def __init__(self) -> None:
        self._records: dict[UUID, DirectionalThesisV31] = {}
        self._transitions: dict[UUID, list[DirectionalThesisTransitionV31]] = {}
        self._active: dict[UUID, UUID] = {}

    def get_record(self, strategy_thesis_id: UUID) -> DirectionalThesisV31 | None:
        return self._records.get(strategy_thesis_id)

    def insert_record(self, record: DirectionalThesisV31) -> None:
        existing = self._records.get(record.strategy_thesis_id)
        if existing is not None and thesis_record_hash_v31(existing) != thesis_record_hash_v31(record):
            raise ValueError("IMMUTABLE_RECORD_CONFLICT")
        self._records.setdefault(record.strategy_thesis_id, record)
        self._transitions.setdefault(record.strategy_thesis_id, [])

    def transitions(self, strategy_thesis_id: UUID) -> tuple[DirectionalThesisTransitionV31, ...]:
        return tuple(self._transitions.get(strategy_thesis_id, ()))

    def append_transition(self, transition: DirectionalThesisTransitionV31) -> None:
        chain = self._transitions.get(transition.strategy_thesis_id)
        if chain is None:
            raise ValueError("UNKNOWN_THESIS")
        expected_previous = chain[-1].transition_hash if chain else None
        if transition.sequence != len(chain) + 1 or transition.previous_transition_hash != expected_previous:
            raise ValueError("APPEND_ONLY_CHAIN_VIOLATION")
        chain.append(transition)

    def active(self, strategy_lifecycle_id: UUID) -> UUID | None:
        return self._active.get(strategy_lifecycle_id)

    def swap_active(self, strategy_lifecycle_id: UUID, *, expected: UUID | None, new: UUID | None) -> None:
        if self._active.get(strategy_lifecycle_id) != expected:
            raise ValueError("ACTIVE_POINTER_CAS_FAILED")
        if new is None:
            self._active.pop(strategy_lifecycle_id, None)
        else:
            self._active[strategy_lifecycle_id] = new


__all__ = [
    "InMemoryDirectionalThesisLedgerV31",
    "ThesisDecisionV31",
    "confirm_thesis_v31",
    "current_thesis_state",
    "expire_thesis_clock_v31",
    "invalidate_thesis_structurally_v31",
    "open_thesis_v31",
    "proof_actionability_failure_v31",
    "terminate_thesis_for_epoch_v31",
    "thesis_status_v31",
]
