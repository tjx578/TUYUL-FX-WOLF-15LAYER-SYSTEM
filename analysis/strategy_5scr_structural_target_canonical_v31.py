"""Canonical StructuralTarget V31 adapter: six predicates, directional nearest, A2-07 revision facts.

Authority: SSOT v3.1 §17 + A2-01 … A2-07. This is a separate canonical path; the legacy selector and the
net-geometry solver are neither called nor changed. The adapter never solves geometry, never reads RR, never reads a
broker quote, never mutates PressureRange and never emits any ExecutionBox reaction (that mapping is 12C).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from fractions import Fraction

from contracts.strategy_5scr_identity_v31 import canonical_sha256_v31
from contracts.strategy_5scr_structural_target_canonical_v31 import (
    TARGET_MATERIAL_FIELDS_V31,
    CanonicalStructuralTargetV31,
    Direction,
    StructuralTargetSelectionRequestV31,
    StructuralTargetSelectionV31,
    TargetEligibilityV31,
    TargetInteractionV31,
    TargetPredicate,
    TargetRevisionV31,
)


def _passes_directionally(price: Decimal, decision_price: Decimal, direction: Direction) -> bool:
    # A2-02: BUY eligible iff target > decision_price; SELL iff target < decision_price. Equality is passed.
    return price > decision_price if direction == "BUY" else price < decision_price


def _directional_distance(price: Decimal, decision_price: Decimal, direction: Direction) -> Fraction:
    # Stated explicitly (A2-06) rather than abs() over a pre-filtered set; exact arithmetic, no float.
    return (
        Fraction(price) - Fraction(decision_price) if direction == "BUY" else Fraction(decision_price) - Fraction(price)
    )


def evaluate_target_predicates_v31(
    candidate: CanonicalStructuralTargetV31,
    *,
    thesis_direction: Direction,
    decision_time: datetime,
    decision_price: Decimal,
) -> tuple[TargetPredicate, ...]:
    """Every A2-05 predicate the candidate fails, in amendment order. Empty means eligible.

    All six are evaluated (no short-circuit) so the audit shows each failure. Nothing else is a predicate: not
    PressureRange, not RR, not valid_until, not tested_count, not formed_at, not TargetSource.
    """

    target = candidate.target
    invalidated = candidate.invalidated_at is not None and candidate.invalidated_at <= decision_time
    consumed = target.consumed_at is not None and target.consumed_at <= decision_time
    failed: list[TargetPredicate] = []
    if candidate.structural_basis != "STRUCTURAL" or invalidated:
        failed.append("STRUCTURAL")
    if candidate.authority != "AUTHORITATIVE":
        failed.append("AUTHORITATIVE")
    if candidate.thesis_direction != thesis_direction:
        failed.append("IN_THESIS_DIRECTION")
    if candidate.freshness_status != "FRESH":
        failed.append("FRESH")
    if consumed:
        failed.append("UNCONSUMED")
    if not _passes_directionally(target.price, decision_price, thesis_direction):
        failed.append("NOT_PASSED_AT_DECISION_TIME")
    return tuple(failed)


def _candidates_hash(request: StructuralTargetSelectionRequestV31) -> str:
    # Input order never changes the cohort identity.
    rows = sorted((c.model_dump(mode="json") for c in request.candidates), key=lambda row: row["target"]["target_id"])
    return canonical_sha256_v31(rows)


def select_structural_target_v31(request: StructuralTargetSelectionRequestV31) -> StructuralTargetSelectionV31:
    request = StructuralTargetSelectionRequestV31.model_validate(request.model_dump())
    decision_price = request.decision_price
    base = {
        "canonical_symbol": request.canonical_symbol,
        "strategy_thesis_id": request.strategy_thesis_id,
        "thesis_direction": request.thesis_direction,
        "decision_time": request.decision_time,
        "decision_price_evidence_hash": decision_price.evidence_hash,
        "pressure_range_id": None if request.pressure_range is None else request.pressure_range.pressure_range_id,
        "candidates_hash": _candidates_hash(request),
    }

    def rejected(reason: str) -> StructuralTargetSelectionV31:
        return StructuralTargetSelectionV31(
            **base,
            status="REJECTED",
            reason=reason,
            selected_target=None,
            selected_directional_distance=None,
            eligibility=(),
        )

    if decision_price.canonical_symbol != request.canonical_symbol:
        return rejected("DECISION_PRICE_SYMBOL_MISMATCH")
    if decision_price.observed_at > request.decision_time:
        return rejected("DECISION_PRICE_FUTURE_EVIDENCE")
    # Context consistency only: a range for another symbol is the wrong context, not a target filter.
    if request.pressure_range is not None and request.pressure_range.canonical_symbol != request.canonical_symbol:
        return rejected("PRESSURE_RANGE_CONTEXT_MISMATCH")
    ids = [c.target.target_id for c in request.candidates]
    if len(ids) != len(set(ids)):
        return rejected("DUPLICATE_TARGET_IDENTITY")
    if any(c.canonical_symbol != request.canonical_symbol for c in request.candidates):
        return rejected("TARGET_SYMBOL_MISMATCH")
    if any(c.observed_through_utc > request.decision_time for c in request.candidates):
        return rejected("TARGET_FUTURE_EVIDENCE")

    eligibility: list[TargetEligibilityV31] = []
    eligible: list[CanonicalStructuralTargetV31] = []
    for candidate in sorted(request.candidates, key=lambda c: c.target.target_id):
        failed = evaluate_target_predicates_v31(
            candidate,
            thesis_direction=request.thesis_direction,
            decision_time=request.decision_time,
            decision_price=decision_price.price,
        )
        eligibility.append(TargetEligibilityV31(target_id=candidate.target.target_id, failed_predicates=failed))
        if not failed:
            eligible.append(candidate)
    if not eligible:
        return StructuralTargetSelectionV31(
            **base,
            status="NO_ELIGIBLE_TARGET",
            reason="NO_ELIGIBLE_STRUCTURAL_TARGET",
            selected_target=None,
            selected_directional_distance=None,
            eligibility=tuple(eligibility),
        )
    # A2-05/A2-06: nearest AFTER all six filters; (directional distance, target_id) and nothing else.
    selected = min(
        eligible,
        key=lambda c: (
            _directional_distance(c.target.price, decision_price.price, request.thesis_direction),
            c.target.target_id,
        ),
    )
    distance = _directional_distance(selected.target.price, decision_price.price, request.thesis_direction)
    return StructuralTargetSelectionV31(
        **base,
        status="SELECTED",
        reason="NEAREST_ELIGIBLE_STRUCTURAL_TARGET",
        selected_target=selected.target,
        selected_directional_distance=Decimal(distance.numerator) / Decimal(distance.denominator),
        eligibility=tuple(eligibility),
    )


def apply_target_interaction_v31(
    candidate: CanonicalStructuralTargetV31, interaction: TargetInteractionV31
) -> CanonicalStructuralTargetV31:
    """A2-04: TEST ≠ CONSUME. Returns a new record; nothing is mutated in place.

    TEST increments tested_count and records the source policy's freshness verdict; it never consumes.
    COMPLETION sets consumed_at to the FIRST authoritative completion evidence under the source's own completion
    policy. The adapter chooses no candle field and no completion rule of its own.
    """

    if interaction.target_id != candidate.target.target_id:
        raise ValueError("TARGET_INTERACTION_FOR_ANOTHER_TARGET")
    if interaction.authority != "AUTHORITATIVE":
        raise ValueError("TARGET_INTERACTION_NOT_AUTHORITATIVE")
    if interaction.observed_at < candidate.target.formed_at:
        raise ValueError("TARGET_INTERACTION_BEFORE_FORMATION")
    body = candidate.model_dump()
    body["freshness_status"] = interaction.freshness_status_after
    body["observed_through_utc"] = max(candidate.observed_through_utc, interaction.observed_at)
    if interaction.kind == "TEST":
        if interaction.policy != candidate.freshness_policy:
            raise ValueError("TARGET_TEST_POLICY_MISMATCH")
        body["tested_count"] = candidate.tested_count + 1
        return CanonicalStructuralTargetV31.model_validate(body)
    if candidate.completion_policy is None:
        raise ValueError("TARGET_WITHOUT_COMPLETION_RULE_CANNOT_BE_CONSUMED")
    if interaction.policy != candidate.completion_policy:
        raise ValueError("TARGET_COMPLETION_POLICY_MISMATCH")
    consumed_at = candidate.target.consumed_at
    if consumed_at is None or interaction.observed_at < consumed_at:
        body["target"] = {**body["target"], "consumed_at": interaction.observed_at}
        body["completion_evidence_hash"] = interaction.evidence_hash
    return CanonicalStructuralTargetV31.model_validate(body)


def classify_target_revision_v31(
    *,
    previous: StructuralTargetSelectionV31,
    current_request: StructuralTargetSelectionRequestV31,
) -> TargetRevisionV31:
    """A2-07: exactly one fact, highest-semantic cause first. Reports target-side facts only.

    TARGET_INVALIDATED > TARGET_NO_LONGER_ELIGIBLE > TARGET_MATERIAL_CHANGE > TARGET_UNCHANGED. The result maps to
    no ExecutionBox state or version; that is 12C authority. A revision needs a previously selected target: the
    first selection is not a revision.
    """

    if previous.status != "SELECTED" or previous.selected_target is None:
        raise ValueError("TARGET_REVISION_REQUIRES_PREVIOUS_SELECTION")
    if (previous.canonical_symbol, previous.strategy_thesis_id, previous.thesis_direction) != (
        current_request.canonical_symbol,
        current_request.strategy_thesis_id,
        current_request.thesis_direction,
    ):
        raise ValueError("TARGET_REVISION_ACROSS_DIFFERENT_THESES")
    if current_request.decision_time < previous.decision_time:
        raise ValueError("TARGET_REVISION_OUT_OF_ORDER")
    current = select_structural_target_v31(current_request)
    if current.status == "REJECTED":
        raise ValueError(f"TARGET_REVISION_CURRENT_SELECTION_REJECTED:{current.reason}")
    before = previous.selected_target
    matches = [c for c in current_request.candidates if c.target.target_id == before.target_id]
    if not matches:
        # A known target is never silently deleted; its absence is undecidable, not a fact.
        raise ValueError("TARGET_REVISION_PREVIOUS_TARGET_RECORD_MISSING")
    (now,) = matches
    selected_id = None if current.selected_target is None else current.selected_target.target_id
    failed = next(e.failed_predicates for e in current.eligibility if e.target_id == before.target_id)
    changed = tuple(f for f in TARGET_MATERIAL_FIELDS_V31 if getattr(before, f) != getattr(now.target, f))

    def fact(value: str) -> TargetRevisionV31:
        return TargetRevisionV31(
            previous_target_id=before.target_id,
            current_selected_target_id=selected_id,
            fact=value,  # type: ignore[arg-type]
            failed_predicates=failed,
            material_fields_changed=changed,
        )

    if now.invalidated_at is not None and now.invalidated_at <= current_request.decision_time:
        return fact("TARGET_INVALIDATED")
    if failed:
        return fact("TARGET_NO_LONGER_ELIGIBLE")
    if selected_id != before.target_id or changed:
        return fact("TARGET_MATERIAL_CHANGE")
    return fact("TARGET_UNCHANGED")


__all__ = [
    "apply_target_interaction_v31",
    "classify_target_revision_v31",
    "evaluate_target_predicates_v31",
    "select_structural_target_v31",
]
