"""Pure producer for PressureDirectionalHypothesisV31 (both admission classes) plus an in-memory reference ledger.

Requalified on #504 (2026-09-20): the admission source is the S1B ``StrategyAnalysisAdmissionReceiptV31`` bound to its
admission record and ``AnalysisLifecycleV31``. The lifecycle id is taken from that lineage, never derived here.

No database, no worker, no wall clock: every time comes from an injected decision clock. Global safety is not
an input, so a global veto can never change a hypothesis record (it stays an overlay, as in #492).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from contracts.strategy_5scr_admission_receipt_v31 import (
    StrategyAnalysisAdmissionReceiptV31,
    admission_receipt_hash_v31,
)
from contracts.strategy_5scr_analysis_admission_v31 import (
    StrategyAnalysisAdmissionV31,
    strategy_analysis_admission_hash_v31,
)
from contracts.strategy_5scr_analysis_lifecycle_v31 import AnalysisLifecycleV31
from contracts.strategy_5scr_per_symbol_admission import SymbolAdmissionLineageV3
from contracts.strategy_5scr_pressure_authority_v31 import PressureAuthorityV31
from contracts.strategy_5scr_pressure_hypothesis_v31 import (
    MATURITY_ORDER,
    TERMINAL_STATES,
    PressureDirectionalHypothesisV31,
    PressureHypothesisClockPolicyV31,
    PressureHypothesisStoreV31,
    PressureHypothesisTransitionV31,
    PressureMaturityEvidenceV31,
    PressureMaturityPolicyV31,
    canonical_sha256_v31,
    hypothesis_id_v31,
    hypothesis_record_hash_v31,
    opening_pressure_evidence_hash_v31,
)

Outcome = Literal["CREATED", "ALREADY_ACTIVE", "NOT_CREATED"]


@dataclass(frozen=True)
class HypothesisDecisionV31:
    outcome: Outcome
    reason_code: str
    hypothesis: PressureDirectionalHypothesisV31 | None = None


def maturity_evidence_from_lineage(lineage: SymbolAdmissionLineageV3) -> PressureMaturityEvidenceV31:
    """Measure one per-symbol lineage. A v3 lineage is single-direction by construction (G1b)."""

    if lineage.direction is None:
        raise ValueError("lineage has no resolved direction")
    return PressureMaturityEvidenceV31(
        canonical_symbol=lineage.canonical_symbol,
        direction=lineage.direction,
        duration_seconds=(lineage.last_event_at - lineage.opened_at).total_seconds(),
        effective_ticks=lineage.effective_ticks,
        direction_stability=1.0,
        source_event_ids=lineage.source_event_ids,
    )


def classify_pressure_maturity_v31(
    evidence: PressureMaturityEvidenceV31, policy: PressureMaturityPolicyV31
) -> str | None:
    """Highest policy tier whose every threshold is met, or None. All numbers come from the policy."""

    met = [
        tier.status
        for tier in policy.tiers
        if evidence.duration_seconds >= tier.min_duration_seconds
        and evidence.effective_ticks >= tier.min_effective_ticks
        and evidence.direction_stability >= tier.min_direction_stability
    ]
    return max(met, key=MATURITY_ORDER.__getitem__) if met else None


# Shared by every downstream V31 producer (#495 onwards): a terminal lifecycle admits no further analysis.
TERMINAL_LIFECYCLE_STATES_V31 = frozenset({"TERMINAL_NO_TRADE", "INVALIDATED", "SUPERSEDED"})


def build_pressure_hypothesis_v31(
    *,
    receipt: StrategyAnalysisAdmissionReceiptV31,
    admission: StrategyAnalysisAdmissionV31,
    lifecycle: AnalysisLifecycleV31,
    pressure_authority: PressureAuthorityV31,
    maturity_evidence: PressureMaturityEvidenceV31 | None,
    maturity_policy: PressureMaturityPolicyV31 | None,
    clock_policy: PressureHypothesisClockPolicyV31 | None,
    decision_at: datetime,
) -> HypothesisDecisionV31:
    """Every SSOT §10.2 clause is an explicit, independently reasoned gate. Fail closed.

    CANONICAL_RAW: pressure maturity from the hashed PressureMaturityPolicyV31 (QUALIFIED or above).
    MATURE_ADVISORY: maturity is the admission's advisory maturity (MATURE/EXTREME); no PairAdmission is involved and
    the canonical maturity inputs must be absent. Either way the hypothesis is ANALYSIS_PRIORITY_ONLY.
    """

    if decision_at.tzinfo is None or decision_at.utcoffset() is None:
        raise ValueError("decision_at must be timezone-aware")
    if clock_policy is None:
        return HypothesisDecisionV31("NOT_CREATED", "HYPOTHESIS_CLOCK_POLICY_MISSING")
    # Gate 1 (H3): the S1B admission lineage, independent of maturity. Revalidated, never trusted as constructed.
    receipt = StrategyAnalysisAdmissionReceiptV31.model_validate(receipt.model_dump())
    admission = StrategyAnalysisAdmissionV31.model_validate(admission.model_dump())
    lifecycle = AnalysisLifecycleV31.model_validate(lifecycle.model_dump())
    if (receipt.strategy_analysis_admission_id, receipt.admission_record_hash) != (
        admission.strategy_analysis_admission_id,
        strategy_analysis_admission_hash_v31(admission),
    ):
        return HypothesisDecisionV31("NOT_CREATED", "ADMISSION_RECEIPT_MISMATCH")
    lineage = dict(zip(lifecycle.admission_lineage_ids, lifecycle.admission_lineage_classes, strict=True))
    if (
        receipt.strategy_lifecycle_id != lifecycle.strategy_lifecycle_id
        or lineage.get(receipt.strategy_analysis_admission_id) != receipt.admission_class
    ):
        return HypothesisDecisionV31("NOT_CREATED", "LIFECYCLE_BINDING_MISMATCH")
    if lifecycle.state in TERMINAL_LIFECYCLE_STATES_V31:
        return HypothesisDecisionV31("NOT_CREATED", "LIFECYCLE_TERMINAL")
    if not receipt.granted_at_utc <= decision_at < receipt.expires_at_utc:
        return HypothesisDecisionV31("NOT_CREATED", "ADMISSION_NOT_ACTIVE")
    # Pressure observation (§10.2, §10.5, §10.6): revalidated, never trusted as constructed.
    authority = PressureAuthorityV31.model_validate(pressure_authority.model_dump(mode="json"))
    symbol = receipt.symbol
    if authority.symbol != symbol:
        return HypothesisDecisionV31("NOT_CREATED", "SYMBOL_SCOPE_MISMATCH")
    if authority.direction_lineage_alignment != "ALIGNED":
        return HypothesisDecisionV31("NOT_CREATED", "DIRECTION_LINEAGE_NOT_ALIGNED")
    if authority.pressure_consensus_status not in {"BUY", "SELL"}:
        return HypothesisDecisionV31("NOT_CREATED", "PRESSURE_CONSENSUS_NOT_DIRECTIONAL")
    direction: Literal["BUY", "SELL"] = "BUY" if authority.pressure_consensus_status == "BUY" else "SELL"
    if not authority.observed_at_utc <= decision_at < authority.valid_until_utc:
        return HypothesisDecisionV31("NOT_CREATED", "PRESSURE_EVIDENCE_STALE_OR_EXPIRED")
    if authority.pressure_contract_status not in {"OPEN", "LOCKED", "TRANSITION_PENDING"}:
        return HypothesisDecisionV31("NOT_CREATED", "PRESSURE_CONTRACT_NOT_USABLE")
    if authority.pressure_contract_status == "LOCKED" and authority.contract_direction != direction:
        return HypothesisDecisionV31("NOT_CREATED", "LOCKED_CONTRACT_DIRECTION_MISMATCH")
    if receipt.pressure_direction != direction:
        return HypothesisDecisionV31("NOT_CREATED", "DIRECTION_LINEAGE_CONFLICT")
    # Gate 2 (H2/H3): maturity, independent of admission, per the admission class (§10.2).
    if receipt.admission_class == "CANONICAL_RAW":
        if maturity_policy is None:
            return HypothesisDecisionV31("NOT_CREATED", "PRESSURE_MATURITY_POLICY_MISSING")
        if maturity_evidence is None:
            return HypothesisDecisionV31("NOT_CREATED", "PRESSURE_MATURITY_EVIDENCE_MISSING")
        if maturity_evidence.canonical_symbol != symbol:
            return HypothesisDecisionV31("NOT_CREATED", "SYMBOL_SCOPE_MISMATCH")
        if maturity_evidence.direction != direction:
            return HypothesisDecisionV31("NOT_CREATED", "DIRECTION_LINEAGE_CONFLICT")
        status = classify_pressure_maturity_v31(maturity_evidence, maturity_policy)
        if status is None or MATURITY_ORDER[status] < MATURITY_ORDER[maturity_policy.minimum_hypothesis_maturity]:
            return HypothesisDecisionV31("NOT_CREATED", "PRESSURE_MATURITY_INSUFFICIENT")
        policy_version, policy_hash = maturity_policy.policy_version, maturity_policy.policy_hash
    else:
        if maturity_policy is not None or maturity_evidence is not None:
            return HypothesisDecisionV31("NOT_CREATED", "CANONICAL_MATURITY_INPUT_NOT_APPLICABLE")
        status = admission.advisory_maturity
        assert admission.advisory_maturity_policy_version is not None
        assert admission.advisory_maturity_policy_hash is not None
        policy_version = admission.advisory_maturity_policy_version
        policy_hash = admission.advisory_maturity_policy_hash

    lifecycle_id = receipt.strategy_lifecycle_id  # bound from the S1B lineage, never derived here
    opening_hash = opening_pressure_evidence_hash_v31(
        canonical_symbol=symbol, direction=direction, source_event_ids=authority.source_event_ids
    )
    record = PressureDirectionalHypothesisV31(
        pressure_hypothesis_id=hypothesis_id_v31(
            strategy_lifecycle_id=lifecycle_id, direction=direction, opening_pressure_evidence_hash=opening_hash
        ),
        canonical_symbol=symbol,
        strategy_lifecycle_id=lifecycle_id,
        strategy_analysis_admission_id=receipt.strategy_analysis_admission_id,
        admission_receipt_hash=admission_receipt_hash_v31(receipt),
        analysis_admission_class=receipt.admission_class,
        analysis_authority=receipt.analysis_authority,
        promotion_eligibility=receipt.promotion_eligibility,
        risk_handoff_allowed=receipt.admission_class == "CANONICAL_RAW",
        direction=direction,
        pressure_authority_mode=authority.pressure_authority_mode,
        pressure_contract_status_at_creation=authority.pressure_contract_status,  # type: ignore[arg-type]
        pressure_authority_snapshot_hash=canonical_sha256_v31(authority.model_dump(mode="json")),
        pressure_maturity_status=status,  # type: ignore[arg-type]
        pressure_maturity_policy_version=policy_version,
        pressure_maturity_policy_hash=policy_hash,
        opening_pressure_evidence_hash=opening_hash,
        source_evidence_ids=tuple(sorted(set(authority.source_event_ids))),
        valid_from=decision_at,
        valid_until=decision_at + timedelta(seconds=clock_policy.ttl_seconds),
        clock_policy_version=clock_policy.clock_policy_version,
        clock_policy_hash=clock_policy.policy_hash,
    )
    return HypothesisDecisionV31("CREATED", "HYPOTHESIS_CREATED", record)


def current_state(transitions: tuple[PressureHypothesisTransitionV31, ...]) -> str:
    return transitions[-1].to_state if transitions else "OPEN"


def make_transition_v31(
    *,
    record: PressureDirectionalHypothesisV31,
    history: tuple[PressureHypothesisTransitionV31, ...],
    to_state: str,
    context_alignment: str,
    location_alignment: str,
    reason_code: str,
    material_event_id: str,
    material_event_hash: str,
    occurred_at: datetime,
    classification: str | None = None,
) -> PressureHypothesisTransitionV31:
    """Next link of the append-only chain. Direction is not a parameter: a transition cannot change it."""

    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("occurred_at must be timezone-aware")
    state = current_state(history)
    if state in TERMINAL_STATES:
        raise ValueError("TERMINAL_HYPOTHESIS_NOT_REVIVED")
    if to_state != "EXPIRED" and occurred_at >= record.valid_until:
        raise ValueError("HYPOTHESIS_CLOCK_EXPIRED")
    if to_state == "EXPIRED" and occurred_at < record.valid_until:
        raise ValueError("EXPIRY_BEFORE_DEADLINE")
    if any(item.material_event_id == material_event_id for item in history):
        raise ValueError("DUPLICATE_MATERIAL_EVENT")
    payload: dict[str, Any] = {
        "pressure_hypothesis_id": record.pressure_hypothesis_id,
        "sequence": len(history) + 1,
        "from_state": state,
        "to_state": to_state,
        "context_alignment": context_alignment,
        "location_alignment": location_alignment,
        "classification": classification,
        "reason_code": reason_code,
        "material_event_id": material_event_id,
        "material_event_hash": material_event_hash,
        "occurred_at": occurred_at,
        "previous_transition_hash": history[-1].transition_hash if history else None,
    }
    probe = PressureHypothesisTransitionV31.model_construct(**payload, transition_hash="sha256:" + "0" * 64)
    payload["transition_hash"] = PressureHypothesisTransitionV31.compute_hash(probe.model_dump(mode="json"))
    return PressureHypothesisTransitionV31.model_validate(payload)


class InMemoryPressureHypothesisLedgerV31(PressureHypothesisStoreV31):
    """Reference implementation of the durability invariants (not persistence)."""

    def __init__(self) -> None:
        self._records: dict[UUID, PressureDirectionalHypothesisV31] = {}
        self._transitions: dict[UUID, list[PressureHypothesisTransitionV31]] = {}
        self._active: dict[UUID, UUID] = {}

    def get_record(self, pressure_hypothesis_id: UUID) -> PressureDirectionalHypothesisV31 | None:
        return self._records.get(pressure_hypothesis_id)

    def insert_record(self, record: PressureDirectionalHypothesisV31) -> None:
        existing = self._records.get(record.pressure_hypothesis_id)
        if existing is not None and hypothesis_record_hash_v31(existing) != hypothesis_record_hash_v31(record):
            raise ValueError("IMMUTABLE_RECORD_CONFLICT")
        self._records.setdefault(record.pressure_hypothesis_id, record)
        self._transitions.setdefault(record.pressure_hypothesis_id, [])

    def transitions(self, pressure_hypothesis_id: UUID) -> tuple[PressureHypothesisTransitionV31, ...]:
        return tuple(self._transitions.get(pressure_hypothesis_id, ()))

    def append_transition(self, transition: PressureHypothesisTransitionV31) -> None:
        chain = self._transitions.get(transition.pressure_hypothesis_id)
        if chain is None:
            raise ValueError("UNKNOWN_HYPOTHESIS")
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


def admit_hypothesis_v31(
    store: PressureHypothesisStoreV31, decision: HypothesisDecisionV31, *, decision_at: datetime
) -> HypothesisDecisionV31:
    """Persist a CREATED decision under the one-active-per-lifecycle rule.

    Same material identity → no duplicate. Terminal id → never revived. Same direction already active →
    keep it (§23.5). Opposite direction → old one INVALIDATED (OPPOSITE_DIRECTION_SUPERSEDED), new one active.
    """

    record = decision.hypothesis
    if decision.outcome != "CREATED" or record is None:
        return decision
    existing = store.get_record(record.pressure_hypothesis_id)
    if existing is not None:
        if current_state(store.transitions(record.pressure_hypothesis_id)) in TERMINAL_STATES:
            return HypothesisDecisionV31("NOT_CREATED", "TERMINAL_HYPOTHESIS_NOT_REVIVED")
        return HypothesisDecisionV31("ALREADY_ACTIVE", "DUPLICATE_MATERIAL_IDENTITY", existing)
    active_id = store.active(record.strategy_lifecycle_id)
    if active_id is not None:
        active = store.get_record(active_id)
        assert active is not None
        history = store.transitions(active_id)
        if current_state(history) not in TERMINAL_STATES and decision_at >= active.valid_until:
            store.append_transition(
                make_transition_v31(
                    record=active,
                    history=history,
                    to_state="EXPIRED",
                    context_alignment=history[-1].context_alignment if history else "UNRESOLVED",
                    location_alignment=history[-1].location_alignment if history else "UNKNOWN",
                    reason_code="HYPOTHESIS_CLOCK_EXPIRED",
                    material_event_id=f"clock-expiry:{active_id}",
                    material_event_hash=canonical_sha256_v31(
                        ["EXPIRED", str(active_id), active.valid_until.isoformat()]
                    ),
                    occurred_at=decision_at,
                )
            )
            history = store.transitions(active_id)
        if current_state(history) not in TERMINAL_STATES:
            if active.direction == record.direction:
                return HypothesisDecisionV31("ALREADY_ACTIVE", "SAME_DIRECTION_ALREADY_ACTIVE", active)
            store.append_transition(
                make_transition_v31(
                    record=active,
                    history=history,
                    to_state="INVALIDATED",
                    context_alignment=history[-1].context_alignment if history else "UNRESOLVED",
                    location_alignment=history[-1].location_alignment if history else "UNKNOWN",
                    reason_code="OPPOSITE_DIRECTION_SUPERSEDED",
                    material_event_id=f"superseded-by:{record.pressure_hypothesis_id}",
                    material_event_hash=record.opening_pressure_evidence_hash,
                    occurred_at=decision_at,
                )
            )
    store.insert_record(record)
    store.swap_active(record.strategy_lifecycle_id, expected=active_id, new=record.pressure_hypothesis_id)
    return decision


__all__ = [
    "TERMINAL_LIFECYCLE_STATES_V31",
    "HypothesisDecisionV31",
    "InMemoryPressureHypothesisLedgerV31",
    "admit_hypothesis_v31",
    "build_pressure_hypothesis_v31",
    "classify_pressure_maturity_v31",
    "current_state",
    "make_transition_v31",
    "maturity_evidence_from_lineage",
]
