"""Canonical StructuralGeometryV31 builder — A4 (RATIFIED 2026-09-27), owner implementation GO 2026-09-27.

Consumes existing upstream truth only: a FROZEN ExecutionBoxV31 revision, a SELECTED canonical StructuralTarget
selection and the exact StructuralProofEvidenceV31 the box was frozen from (its M15 reference candle R). Every
upstream verdict is read, never recomputed.

It never reads a broker quote, spread, tick size, commission, slippage, volume or margin, never evaluates net RR,
never chooses an order type and never moves the SL, TP1 or the box (A4-02, A4-07, A4-09). Placement restriction to
(SL, TP1) belongs to G4 (Q-A4-1), not here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from analysis.strategy_5scr_execution_box_v31 import canonical_price_v31
from contracts.strategy_5scr_execution_box_v31 import ExecutionBoxState, ExecutionBoxVersionV31
from contracts.strategy_5scr_structural_geometry_v31 import (
    GEOMETRY_POLICIES_V31,
    GeometryStatus,
    GrossRRV31,
    NoValidEntryDomainCause,
    StructuralGeometryDecisionV31,
    StructuralGeometryLineageV31,
    StructuralGeometryMaterialV31,
    StructuralGeometryPolicyV31,
    StructuralGeometryV31,
    gross_rr_v31,
    material_geometry_hash_v31,
)
from contracts.strategy_5scr_structural_proof_v31 import StructuralProofEvidenceV31
from contracts.strategy_5scr_structural_target_canonical_v31 import StructuralTargetSelectionV31


def _no_geometry(status: GeometryStatus, cause: NoValidEntryDomainCause | None = None) -> StructuralGeometryDecisionV31:
    return StructuralGeometryDecisionV31(status=status, cause=cause, geometry=None)


def resolve_geometry_policy_v31(
    *, geometry_policy_id: str, geometry_policy_version: str, box: ExecutionBoxVersionV31
) -> StructuralGeometryPolicyV31 | None:
    """A4-14: exact (id, version) lookup, bound to the box's route and ratified box policy. No default, no env."""

    policy = GEOMETRY_POLICIES_V31.get((geometry_policy_id, geometry_policy_version))
    if policy is None:
        return None
    if (policy.route, policy.box_policy_id, policy.box_policy_version) != (
        box.route,
        box.box_policy_id,
        box.box_policy_version,
    ):
        return None
    return policy


def structural_sl_anchor_v31(proof: StructuralProofEvidenceV31, direction: str) -> Decimal | None:
    """A4-01: canon(R.low) for BUY, canon(R.high) for SELL, R the proof's M15 reference candle — the exact candle
    the break evidence names. None when R cannot serve as SL authority (no rounding, no fallback)."""

    reference = proof.m15_source_candles[0]
    if reference.candle_evidence_id != proof.m15_break_evidence.reference_candle_id:
        return None
    if reference.symbol != proof.canonical_symbol or reference.timeframe != "M15":
        return None
    try:
        return canonical_price_v31(reference.low if direction == "BUY" else reference.high)
    except (TypeError, ValueError):
        return None


def build_structural_geometry_v31(
    *,
    box: ExecutionBoxVersionV31,
    box_state: ExecutionBoxState,
    proof: StructuralProofEvidenceV31,
    target_selection: StructuralTargetSelectionV31,
    geometry_policy_id: str,
    geometry_policy_version: str,
    decision_time: datetime,
) -> StructuralGeometryDecisionV31:
    """A4 geometry for one FROZEN box revision. The first failed prerequisite decides the status."""

    policy = resolve_geometry_policy_v31(
        geometry_policy_id=geometry_policy_id, geometry_policy_version=geometry_policy_version, box=box
    )
    if policy is None:
        return _no_geometry("GEOMETRY_POLICY_UNKNOWN")
    if box_state != "FROZEN" or box.lineage.freeze_evidence_close_utc > decision_time:
        return _no_geometry("EXECUTION_BOX_NOT_FROZEN")
    target = target_selection.selected_target
    if (
        target_selection.status != "SELECTED"
        or target is None
        or target_selection.strategy_thesis_id != box.strategy_thesis_id
        or target_selection.canonical_symbol != box.canonical_symbol
        or target_selection.thesis_direction != box.direction
        or target_selection.decision_time > decision_time
    ):
        return _no_geometry("STRUCTURAL_TARGET_UNAVAILABLE")
    # The SL comes from the exact proof the box was frozen from, and only from evidence closed by decision_time.
    if (
        proof.proof_id != box.material.structural_proof_id
        or proof.material_evidence_hash != box.lineage.structural_proof_hash
        or proof.canonical_symbol != box.canonical_symbol
        or proof.proof_direction != box.direction
        or proof.m15_source_candles[0].close_time_utc > decision_time
    ):
        return _no_geometry("STRUCTURAL_SL_UNAVAILABLE")
    anchor = structural_sl_anchor_v31(proof, box.direction)
    if anchor is None:
        return _no_geometry("STRUCTURAL_SL_UNAVAILABLE")

    buy = box.direction == "BUY"
    structural_sl = anchor  # A4-02: buffer NONE
    tp1 = target.price  # A4-09: exact, no offset
    reference = box.material.box_high if buy else box.material.box_low  # A4-05
    risk = reference - structural_sl if buy else structural_sl - reference
    reward = tp1 - reference if buy else reference - tp1
    # Q-A4-2: risk first; a setup failing both carries the risk cause.
    if risk <= 0:
        return _no_geometry("ROUTE_NO_VALID_ENTRY_DOMAIN", "STRUCTURAL_RISK_NON_POSITIVE")
    if reward <= 0:
        return _no_geometry("ROUTE_NO_VALID_ENTRY_DOMAIN", "STRUCTURAL_REWARD_NON_POSITIVE")

    material = StructuralGeometryMaterialV31(
        execution_box_id=box.execution_box_id,
        box_version=box.box_version,
        structural_sl_anchor=anchor,
        structural_sl=structural_sl,
        target_id=target.target_id,
        tp1=tp1,
        rr_reference_entry=reference,
        geometry_policy_id=policy.geometry_policy_id,
        geometry_policy_version=policy.geometry_policy_version,
    )
    geometry = StructuralGeometryV31(
        strategy_thesis_id=box.strategy_thesis_id,
        strategy_lifecycle_id=box.strategy_lifecycle_id,
        canonical_symbol=box.canonical_symbol,
        direction=box.direction,
        route=box.route,
        entry_interval_low=box.material.box_low,
        entry_interval_high=box.material.box_high,
        material=material,
        material_geometry_hash=material_geometry_hash_v31(material),
        gross_rr=GrossRRV31.of(
            gross_rr_v31(direction=box.direction, rr_reference_entry=reference, structural_sl=structural_sl, tp1=tp1)
        ),
        lineage=StructuralGeometryLineageV31(
            material_box_hash=box.material_box_hash,
            structural_proof_id=proof.proof_id,
            structural_proof_hash=proof.material_evidence_hash,
            reference_candle_id=proof.m15_source_candles[0].candle_evidence_id,
            target_evidence_hash=target.evidence_hash,
            target_selection_decision_price_hash=target_selection.decision_price_evidence_hash,
        ),
    )
    return StructuralGeometryDecisionV31(status="STRUCTURAL_GEOMETRY_READY", cause=None, geometry=geometry)


def geometry_revision_fact_v31(previous: StructuralGeometryV31, current: StructuralGeometryV31) -> str | None:
    """A4-10: STRUCTURAL_GEOMETRY_MATERIAL_CHANGE when the projection moved (→ a new TradePlanCandidate revision
    downstream), None when it did not. It never touches the box: a target change alone keeps box_version."""

    if (previous.strategy_thesis_id, previous.direction, previous.route) != (
        current.strategy_thesis_id,
        current.direction,
        current.route,
    ):
        raise ValueError("GEOMETRY_REVISION_ACROSS_DIFFERENT_THESES")
    if previous.material_geometry_hash == current.material_geometry_hash:
        return None
    return "STRUCTURAL_GEOMETRY_MATERIAL_CHANGE"


def requires_geometry_reevaluation_v31(*, box_changed: bool, target_fact: str, sl_evidence_changed: bool) -> bool:
    """A4-15: any upstream box, target or SL material change obliges re-evaluation; nothing else does."""

    if target_fact not in {
        "TARGET_UNCHANGED",
        "TARGET_MATERIAL_CHANGE",
        "TARGET_NO_LONGER_ELIGIBLE",
        "TARGET_INVALIDATED",
    }:
        raise ValueError("UNKNOWN_TARGET_REVISION_FACT")
    return box_changed or sl_evidence_changed or target_fact != "TARGET_UNCHANGED"


__all__ = [
    "build_structural_geometry_v31",
    "geometry_revision_fact_v31",
    "requires_geometry_reevaluation_v31",
    "resolve_geometry_policy_v31",
    "structural_sl_anchor_v31",
]
