"""Verify a non-executable v3.1 candidate before TEST_ONLY capacity proposal.

The S3-S5 receipt verifier must bind inherited admission/thesis authority and
individual domain clocks to the selected source. This module does not derive
those proofs or promote a TEST_ONLY result to a final signal.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, localcontext
from fractions import Fraction
from uuid import UUID

from analysis.strategy_5scr_target_selection_v31 import solve_target_geometry_v31, target_universe_hash_v31
from contracts.strategy_5scr_candidate_handoff_v31 import CandidateHandoffV31
from contracts.strategy_5scr_capacity_v31 import CapacityLedgerV31, CapacityProposalV31
from contracts.strategy_5scr_net_geometry_v31 import NetGeometryContextV31
from contracts.strategy_5scr_risk_adapter_v31 import ParentSizingRequestV31
from contracts.strategy_5scr_target_selection_v31 import TargetUniverseV31
from risk.strategy_5scr_capacity_v31 import CapacityRejectedError, reserve_parent_capacity_v31


def candidate_handoff_hash_v31(handoff: CandidateHandoffV31) -> str:
    payload = handoff.model_dump(mode="json")
    payload["target_universe"] = target_universe_hash_v31(handoff.target_universe)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def propose_canonical_parent_v31(
    ledger: CapacityLedgerV31,
    handoff: CandidateHandoffV31,
    request: ParentSizingRequestV31,
    *,
    reservation_id: UUID,
    expires_at: datetime,
    now: datetime,
    owner_epoch: int,
    expected_version: int,
    verify_handoff: Callable[[CandidateHandoffV31, str], bool] | None,
    verify_universe: Callable[[TargetUniverseV31, str], bool] | None,
    verify_risk_inputs: Callable[[ParentSizingRequestV31, str], bool] | None,
) -> CapacityProposalV31:
    handoff = CandidateHandoffV31.model_validate(handoff.model_dump())
    request = ParentSizingRequestV31.model_validate(request.model_dump())
    candidate = handoff.candidate
    if candidate.analysis_admission_class != "CANONICAL_RAW":
        raise CapacityRejectedError("STRATEGY_ADVISORY_RISK_HANDOFF_PROHIBITED")
    digest = candidate_handoff_hash_v31(handoff)
    if request.strategy_candidate_receipt_hash != digest:
        raise CapacityRejectedError("STRATEGY_HANDOFF_RECEIPT_MISMATCH")
    if (request.tradeplan_id, request.tradeplan_revision, request.thesis_id) != (
        str(candidate.tradeplan_id),
        candidate.tradeplan_revision,
        str(candidate.strategy_thesis_id),
    ):
        raise CapacityRejectedError("STRATEGY_HANDOFF_IDENTITY_MISMATCH")
    if any(r.reservation_id == reservation_id for r in ledger.reservations):
        # A retry acknowledges the exact prior proposal, even after proof expiry.
        # The reducer checks owner epoch and the full immutable request envelope;
        # its returned record is not fresh permission to issue a command.
        return reserve_parent_capacity_v31(
            ledger,
            request,
            reservation_id=reservation_id,
            expires_at=expires_at,
            now=now,
            owner_epoch=owner_epoch,
            expected_version=expected_version,
            verify_inputs=verify_risk_inputs,
        )
    geometry = request.geometry
    if (candidate.symbol, candidate.direction, candidate.decision_at) != (
        geometry.symbol,
        geometry.direction,
        request.evaluated_at,
    ) or candidate.decision_at != geometry.decision_at:
        raise CapacityRejectedError("STRATEGY_HANDOFF_CONTEXT_MISMATCH")
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or not candidate.decision_at <= now < handoff.handoff_receipt_valid_until
    ):
        raise CapacityRejectedError("STRATEGY_HANDOFF_RECEIPT_EXPIRED")
    if not isinstance(expires_at, datetime) or expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise CapacityRejectedError("STRATEGY_RESERVATION_WINDOW_INVALID")
    if expires_at > handoff.handoff_receipt_valid_until:
        raise CapacityRejectedError("STRATEGY_RESERVATION_EXCEEDS_HANDOFF_WINDOW")
    if geometry.policy is None or candidate.execution_policy_id != geometry.policy.policy_id:
        raise CapacityRejectedError("STRATEGY_HANDOFF_POLICY_MISMATCH")
    if verify_handoff is None or verify_handoff(handoff, digest) is not True:
        raise CapacityRejectedError("STRATEGY_HANDOFF_VERIFICATION_REJECTED")
    if candidate_handoff_hash_v31(handoff) != digest:
        raise CapacityRejectedError("STRATEGY_HANDOFF_EVIDENCE_CHANGED")
    selected = solve_target_geometry_v31(
        universe=handoff.target_universe,
        context=NetGeometryContextV31(**geometry.model_dump(exclude={"target_price", "target_evidence_hash"})),
        verify_universe=verify_universe,
    )
    solved = selected.geometry
    if solved is None or solved.status != "FEASIBLE_TEST_ONLY":
        raise CapacityRejectedError("STRATEGY_TARGET_GEOMETRY_REJECTED:" + selected.reason)
    if (
        selected.selected_target_id != str(candidate.target_id)
        or selected.universe_hash != geometry.target_evidence_hash
    ):
        raise CapacityRejectedError("STRATEGY_TARGET_IDENTITY_MISMATCH")
    selected_target = next(t for t in handoff.target_universe.targets if t.target_id == selected.selected_target_id)
    if (candidate.structural_sl, candidate.tp1, candidate.tp1) != (
        geometry.stop_price,
        geometry.target_price,
        selected_target.price,
    ):
        raise CapacityRejectedError("STRATEGY_FIXED_GEOMETRY_MISMATCH")
    if (candidate.candidate_entry, candidate.entry_interval, candidate.net_rr) != (
        solved.candidate_entry,
        solved.feasible_interval,
        solved.net_rr,
    ):
        raise CapacityRejectedError("STRATEGY_GEOMETRY_REPLAY_MISMATCH")
    gross = abs(Fraction(candidate.tp1) - Fraction(candidate.candidate_entry)) / abs(
        Fraction(candidate.candidate_entry) - Fraction(candidate.structural_sl)
    )
    with localcontext() as context:
        context.prec = 80
        expected_gross = Decimal(gross.numerator) / Decimal(gross.denominator)
    if candidate.gross_rr != expected_gross:
        raise CapacityRejectedError("STRATEGY_GROSS_RR_MISMATCH")
    if candidate_handoff_hash_v31(handoff) != digest:
        raise CapacityRejectedError("STRATEGY_HANDOFF_EVIDENCE_CHANGED")
    return reserve_parent_capacity_v31(
        ledger,
        request,
        reservation_id=reservation_id,
        expires_at=expires_at,
        now=now,
        owner_epoch=owner_epoch,
        expected_version=expected_version,
        verify_inputs=verify_risk_inputs,
    )
