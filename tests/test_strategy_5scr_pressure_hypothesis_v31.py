"""Gap #7 acceptance, requalified on #504: PressureDirectionalHypothesisV31 from the S1B admission lineage.

Authority decisions H1–H5 (2026-09-19), H1 updated 2026-09-20: the admission source is the S1B
``StrategyAnalysisAdmissionReceiptV31`` (CANONICAL_RAW or MATURE_ADVISORY), the lifecycle comes from the market
episode, and the hypothesis id (lifecycle, direction, opening pressure evidence) never depends on the admission.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_analysis_admission_v31 import evaluate_canonical_raw_admission_v31
from analysis.strategy_5scr_analysis_lifecycle_v31 import InMemoryAnalysisLifecycleLedgerV31, lifecycle_view_v31
from analysis.strategy_5scr_pair_admission_coverage_v31 import classify_pair_admission_coverage_v31
from analysis.strategy_5scr_pressure_hypothesis_v31 import (
    InMemoryPressureHypothesisLedgerV31,
    admit_hypothesis_v31,
    build_pressure_hypothesis_v31,
    current_state,
    make_transition_v31,
    maturity_evidence_from_lineage,
)
from contracts.strategy_5scr_identity_v31 import canonical_sha256_v31
from contracts.strategy_5scr_pair_admission_coverage_v31 import (
    PairAdmissionEvaluationRefV31,
    RawAuthorityBlockRefV31,
    RawAuthorityCoverageObservationV31,
)
from contracts.strategy_5scr_pressure_authority_v31 import PressureAuthorityV31
from contracts.strategy_5scr_pressure_hypothesis_v31 import (
    MaturityTierV31,
    PressureDirectionalHypothesisV31,
    PressureHypothesisClockPolicyV31,
    PressureHypothesisTransitionV31,
    PressureMaturityPolicyV31,
)
from tests.test_strategy_5scr_admission_receipt_v31 import _receipt
from tests.test_strategy_5scr_analysis_admission_v31 import ADMISSION, _advisory, _evidence
from tests.test_strategy_5scr_analysis_lifecycle_v31 import _apply
from tests.test_strategy_5scr_market_episode_v31 import POLICY as MERGE_POLICY
from tests.test_strategy_5scr_market_episode_v31 import _event, _reduce
from tests.test_strategy_5scr_pair_admission_coverage_v31 import POLICY as COVERAGE_POLICY
from tests.test_strategy_5scr_pair_admission_coverage_v31 import _classify
from tests.test_strategy_5scr_per_symbol_admission import START, _raw, _safety
from tests.test_strategy_5scr_per_symbol_admission import _evaluate as _pair_admission

TIERS = (
    MaturityTierV31(status="QUALIFIED", min_duration_seconds=300, min_effective_ticks=2, min_direction_stability=1.0),
    MaturityTierV31(status="MATURE", min_duration_seconds=600, min_effective_ticks=4, min_direction_stability=1.0),
)
_PROJECTION_NS = UUID("00000000-0000-4000-8000-000000000492")  # test-local projection of a #492 lineage


def _maturity(minimum: str = "QUALIFIED") -> PressureMaturityPolicyV31:
    return PressureMaturityPolicyV31(
        policy_version="test-maturity.v1",
        tiers=TIERS,
        minimum_hypothesis_maturity=minimum,  # type: ignore[arg-type]
        policy_hash=PressureMaturityPolicyV31.compute_hash("test-maturity.v1", TIERS, minimum),
    )


CLOCK = PressureHypothesisClockPolicyV31(
    clock_policy_version="test-clock.v1",
    ttl_seconds=900,
    clock_source="INJECTED_DECISION_CLOCK",
    policy_hash=PressureHypothesisClockPolicyV31.compute_hash("test-clock.v1", 900, "INJECTED_DECISION_CLOCK"),
)
DECISION = START + timedelta(seconds=400)


def _authority(direction: str = "BUY", *, ids=("p1", "p2"), consensus: str | None = None, **overrides):
    values = {
        "symbol": "EURUSD",
        "source_event_ids": tuple(sorted(ids)),
        "pressure_authority_mode": "RADAR_ONLY",
        "pressure_contract_status": "OPEN",
        "pressure_contract_version": "radar.v1",
        "pressure_contract_invalidated_at": None,
        "observed_at_utc": START + timedelta(seconds=390),
        "valid_until_utc": START + timedelta(seconds=3600),
        "raw_direction": direction,
        "candidate_direction": direction,
        "watch_direction": direction,
        "block_direction": direction,
        "direction_lineage_alignment": "ALIGNED",
        "pressure_consensus_status": consensus or direction,
        **overrides,
    }
    return PressureAuthorityV31(**values)


# --- S1B lineage fixtures (#501 → #502 → #503 → #504) --------------------------------------------------------


@dataclass
class S1B:
    receipt: Any
    admission: Any
    lifecycle: Any
    ledger: Any
    episode: Any
    state: Any
    lineage: Any


def _episode(*moves: tuple[int, str], confirmed_flip_at: int | None = None):
    """Market episode at START from (seconds, direction) moves; optional confirmed opposite transition."""

    events = [
        _event(i, 0, event_time=START + timedelta(seconds=s), direction=d, deployment_id=f"deploy-{i}")
        for i, (s, d) in enumerate(moves or ((0, "BUY"), (120, "BUY")))
    ]
    if confirmed_flip_at is not None:
        events.append(
            _event(
                99,
                0,
                event_time=START + timedelta(seconds=confirmed_flip_at),
                direction="SELL",
                confirmed_opposite_transition_evidence_id="formal-flip-1",
            )
        )
    reduction = _reduce(events, MERGE_POLICY)
    return reduction


def _open_episode(reduction, at: datetime):
    candidates = [e for e in reduction.episodes.values() if e.opened_at <= at]
    episode = max(candidates, key=lambda e: e.opened_at)
    return episode, reduction.states[episode.market_episode_id]


def _canonical_s1b(
    direction: str = "BUY",
    *,
    events: Any = None,
    safety: Any = None,
    reduction: Any = None,
    ledger: Any = None,
    decided_at: datetime | None = None,
) -> S1B | None:
    """Real #492 lineage → coverage EVALUATED → CANONICAL_RAW admission → lifecycle → receipt (None if not granted)."""

    lineage = _pair_admission(
        events or [_raw(0, direction=direction), _raw(300, direction=direction)], safety=safety
    ).lineages["EURUSD"][-1]
    if lineage.decision != "GRANTED" or lineage.granted_at is None:
        return None
    evaluation = PairAdmissionEvaluationRefV31(
        admission_evaluation_id=uuid5(_PROJECTION_NS, lineage.lineage_id),
        raw_authority_block_id=lineage.lineage_id,
        canonical_symbol="EURUSD",
        decision="GRANTED",
        reason_code=lineage.reason_code,
        evaluated_at=lineage.granted_at,
        admission_rule_version=lineage.rule_version,
        evaluation_hash=canonical_sha256_v31(lineage.model_dump(mode="json")),
    )
    window_end = lineage.granted_at + timedelta(seconds=60)
    coverage = classify_pair_admission_coverage_v31(
        observation=RawAuthorityCoverageObservationV31(
            canonical_symbol="EURUSD",
            observed_window_start_utc=START,
            observed_window_end_utc=window_end,
            raw_authority_coverage_status="COMPLETE",
            coverage_evidence_hash=canonical_sha256_v31(["coverage", lineage.lineage_id]),
            block=RawAuthorityBlockRefV31(
                raw_authority_block_id=lineage.lineage_id,
                canonical_symbol="EURUSD",
                block_started_at=lineage.opened_at,
                eligible=True,
                eligible_at=lineage.granted_at,
                raw_lineage_hash=evaluation.evaluation_hash,
            ),
        ),
        evaluation=evaluation,
        advisory_pressure_maturity="UNKNOWN",
        policy=COVERAGE_POLICY,
        as_of=window_end,
    ).coverage
    assert coverage is not None
    at = decided_at or window_end
    reduction = reduction or _episode((0, direction), (120, direction))
    episode, state = _open_episode(reduction, at)
    admission = evaluate_canonical_raw_admission_v31(
        episode=episode,
        episode_state=state,
        coverage=coverage,
        evaluation=evaluation,
        pressure_direction=direction,  # type: ignore[arg-type]
        direction_lineage_alignment="ALIGNED",
        direction_evidence_hash=evaluation.evaluation_hash,
        policy=ADMISSION,
        decision_at=at,
    ).admission
    assert admission is not None and admission.admission_status == "GRANTED"
    ledger = ledger or InMemoryAnalysisLifecycleLedgerV31()
    _apply(ledger, episode, state, admission)
    receipt = _receipt(ledger, episode, state, admission, coverage=coverage, evaluation=evaluation)
    lifecycle = lifecycle_view_v31(ledger, episode.strategy_lifecycle_id, state)
    return S1B(receipt, admission, lifecycle, ledger, episode, state, lineage)


def _hypothesis_from(
    s1b: S1B, *, authority=None, maturity: Any = "default", clock: Any = CLOCK, decision_at=DECISION, direction="BUY"
):
    canonical = s1b.receipt.admission_class == "CANONICAL_RAW"
    return build_pressure_hypothesis_v31(
        receipt=s1b.receipt,
        admission=s1b.admission,
        lifecycle=s1b.lifecycle,
        pressure_authority=authority or _authority(direction),
        maturity_evidence=maturity_evidence_from_lineage(s1b.lineage) if canonical else None,
        maturity_policy=(_maturity() if maturity == "default" else maturity) if canonical else None,
        clock_policy=clock,
        decision_at=decision_at,
    )


def _build(
    direction: str = "BUY",
    *,
    authority=None,
    maturity: Any = "default",
    clock: Any = CLOCK,
    decision_at=DECISION,
    safety=None,
    events=None,
):
    """Kept for the downstream suites (#495, #497): one CANONICAL_RAW hypothesis on a fresh S1B lineage."""

    s1b = _canonical_s1b(direction, events=events, safety=safety)
    assert s1b is not None
    return _hypothesis_from(
        s1b,
        authority=authority or _authority(direction),
        maturity=maturity,
        clock=clock,
        decision_at=decision_at,
        direction=direction,
    )


def _advisory_s1b(reduction: Any = None, ledger: Any = None) -> S1B:
    """MATURE_ADVISORY admission at START+360 (no PairAdmission) → lifecycle → receipt."""

    at = START + timedelta(seconds=360)
    reduction = reduction or _episode()
    episode, state = _open_episode(reduction, at)
    window = RawAuthorityCoverageObservationV31(
        canonical_symbol="EURUSD",
        observed_window_start_utc=START,
        observed_window_end_utc=at,
        raw_authority_coverage_status="COMPLETE",
        coverage_evidence_hash=canonical_sha256_v31(["coverage", "advisory"]),
        block=None,
    )
    coverage = _classify(window, maturity="MATURE", as_of=at).coverage
    evidence_times = {
        "observed_from": START,
        "observed_until": START + timedelta(seconds=300),
        "pressure_valid_until": START + timedelta(hours=1),
    }
    admission = _advisory(episode, state, coverage=coverage, at=at, **evidence_times).admission
    assert admission is not None and admission.admission_status == "GRANTED"
    ledger = ledger or InMemoryAnalysisLifecycleLedgerV31()
    _apply(ledger, episode, state, admission)
    receipt = _receipt(
        ledger, episode, state, admission, coverage=coverage, evidence=_evidence(episode, **evidence_times)
    )
    return S1B(
        receipt,
        admission,
        lifecycle_view_v31(ledger, episode.strategy_lifecycle_id, state),
        ledger,
        episode,
        state,
        None,
    )


# --- CANONICAL_RAW path (unchanged semantics) ------------------------------------------------------------------


def test_granted_and_sufficient_maturity_creates_priority_only_hypothesis():
    decision = _build()
    record = decision.hypothesis
    assert (decision.outcome, decision.reason_code) == ("CREATED", "HYPOTHESIS_CREATED")
    assert record is not None and record.pressure_hypothesis_id.version == 5
    assert (record.direction, record.pressure_maturity_status, record.analysis_admission_class) == (
        "BUY",
        "QUALIFIED",
        "CANONICAL_RAW",
    )
    assert record.authority == "ANALYSIS_PRIORITY_ONLY"
    assert record.legal_direction_authority is False  # FINAL_DIRECTION_AUTHORITY_FROM_PRESSURE = FALSE
    assert record.final_signal_allowed is False and record.execution_command_allowed is False
    assert record.valid_until - record.valid_from == timedelta(seconds=900)


def test_the_lifecycle_comes_from_the_s1b_lineage_never_from_the_admission():
    s1b = _canonical_s1b()
    assert s1b is not None
    record = _hypothesis_from(s1b).hypothesis
    assert record is not None
    assert record.strategy_lifecycle_id == s1b.receipt.strategy_lifecycle_id == s1b.episode.strategy_lifecycle_id
    assert record.strategy_lifecycle_id != record.strategy_analysis_admission_id


def test_granted_but_insufficient_maturity_creates_nothing():
    decision = _build(maturity=_maturity("MATURE"))
    assert (decision.outcome, decision.reason_code) == ("NOT_CREATED", "PRESSURE_MATURITY_INSUFFICIENT")


def test_without_a_granted_pair_admission_there_is_no_canonical_receipt_to_build_from():
    assert _canonical_s1b(events=[_raw(0), _raw(100)]) is None  # below threshold: PENDING_THRESHOLD
    s1b = _canonical_s1b()
    assert s1b is not None
    with pytest.raises(ValidationError):  # a receipt only ever exists for a GRANTED admission
        type(s1b.receipt).model_validate({**s1b.receipt.model_dump(), "admission_status": "REJECTED"})


def test_conflicting_consensus_creates_no_hypothesis():
    conflict = _authority(
        "BUY",
        watch_direction="SELL",
        direction_lineage_alignment="CONFLICT",
        consensus="CONFLICT",
    )
    decision = _build(authority=conflict)
    assert (decision.outcome, decision.reason_code) == ("NOT_CREATED", "DIRECTION_LINEAGE_NOT_ALIGNED")


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"maturity": None}, "PRESSURE_MATURITY_POLICY_MISSING"),
        ({"clock": None}, "HYPOTHESIS_CLOCK_POLICY_MISSING"),
        ({"decision_at": START + timedelta(seconds=3600)}, "PRESSURE_EVIDENCE_STALE_OR_EXPIRED"),
        ({"decision_at": START + timedelta(seconds=300)}, "ADMISSION_NOT_ACTIVE"),
    ],
)
def test_missing_policy_stale_evidence_or_inactive_admission_fails_closed(kwargs, reason):
    decision = _build(**kwargs)
    assert (decision.outcome, decision.reason_code) == ("NOT_CREATED", reason)


def test_locked_contract_forbids_the_opposite_direction():
    locked = _authority(
        "BUY",
        pressure_authority_mode="CONSOLIDATED_DIRECTION_CONTRACT",
        pressure_contract_status="LOCKED",
        contract_direction="SELL",
        formal_transition_event_id="p1",
    )
    assert _build(authority=locked).reason_code == "LOCKED_CONTRACT_DIRECTION_MISMATCH"


def test_pressure_direction_must_match_the_admission_direction():
    s1b = _canonical_s1b()
    assert s1b is not None
    decision = _hypothesis_from(s1b, authority=_authority("SELL", ids=("s1",)))
    assert decision.reason_code == "DIRECTION_LINEAGE_CONFLICT"


def test_replay_gives_same_uuid_and_other_direction_gives_different_uuid():
    first, again = _build().hypothesis, _build().hypothesis
    assert first == again
    sell = _build("SELL", authority=_authority("SELL")).hypothesis
    assert first is not None and sell is not None and first.pressure_hypothesis_id != sell.pressure_hypothesis_id


def test_refreshed_telemetry_with_same_material_evidence_is_not_a_new_hypothesis():
    ledger = InMemoryPressureHypothesisLedgerV31()
    first = admit_hypothesis_v31(ledger, _build(), decision_at=DECISION)
    refreshed = _authority(observed_at_utc=START + timedelta(seconds=395))  # same source ids, new observation time
    again = admit_hypothesis_v31(ledger, _build(authority=refreshed), decision_at=DECISION)
    assert first.outcome == "CREATED" and again.outcome == "ALREADY_ACTIVE"
    assert again.hypothesis == first.hypothesis
    new_evidence_same_direction = admit_hypothesis_v31(
        ledger, _build(authority=_authority(ids=("p1", "p2", "p3"))), decision_at=DECISION
    )
    assert (new_evidence_same_direction.outcome, new_evidence_same_direction.reason_code) == (
        "ALREADY_ACTIVE",
        "SAME_DIRECTION_ALREADY_ACTIVE",
    )


@pytest.mark.parametrize("override", [{"kill_switch_active": True}, {"database_and_governance_ok": False}])
def test_global_veto_toggle_leaves_the_hypothesis_record_unchanged(override):
    assert _build(safety=_safety(**override)).hypothesis == _build().hypothesis


# --- MATURE_ADVISORY path (new: §10.2) -------------------------------------------------------------------------


def test_mature_advisory_receipt_opens_a_contained_priority_only_hypothesis_without_pair_admission():
    s1b = _advisory_s1b()
    decision = _hypothesis_from(s1b)
    record = decision.hypothesis
    assert (decision.outcome, decision.reason_code) == ("CREATED", "HYPOTHESIS_CREATED")
    assert record is not None and s1b.receipt.pair_admission_evaluation_id is None
    assert (record.analysis_admission_class, record.analysis_authority, record.promotion_eligibility) == (
        "MATURE_ADVISORY",
        "FULL_SHADOW_ANALYSIS",
        "SHADOW_ONLY",
    )
    assert (record.risk_handoff_allowed, record.pressure_maturity_status) == (False, "MATURE")
    assert record.pressure_maturity_policy_hash == s1b.admission.advisory_maturity_policy_hash
    assert (
        record.authority,
        record.legal_direction_authority,
        record.final_signal_allowed,
        record.execution_command_allowed,
    ) == (
        "ANALYSIS_PRIORITY_ONLY",
        False,
        False,
        False,
    )
    wrong_inputs = build_pressure_hypothesis_v31(
        receipt=s1b.receipt,
        admission=s1b.admission,
        lifecycle=s1b.lifecycle,
        pressure_authority=_authority(),
        maturity_evidence=None,
        maturity_policy=_maturity(),
        clock_policy=CLOCK,
        decision_at=DECISION,
    )
    assert wrong_inputs.reason_code == "CANONICAL_MATURITY_INPUT_NOT_APPLICABLE"


def test_authority_upgrade_keeps_the_same_lifecycle_and_hypothesis_and_never_mutates_it():
    reduction = _episode()
    advisory = _advisory_s1b(reduction)
    ledger = InMemoryPressureHypothesisLedgerV31()
    shadow = admit_hypothesis_v31(ledger, _hypothesis_from(advisory), decision_at=DECISION).hypothesis
    assert shadow is not None
    canonical = _canonical_s1b(reduction=reduction, ledger=advisory.ledger, decided_at=START + timedelta(seconds=370))
    assert canonical is not None
    assert canonical.receipt.strategy_lifecycle_id == advisory.receipt.strategy_lifecycle_id  # SAME lifecycle L
    assert canonical.lifecycle.highest_analysis_authority == "CANONICAL_RAW"
    later = admit_hypothesis_v31(ledger, _hypothesis_from(canonical), decision_at=DECISION)
    assert (later.outcome, later.reason_code) == ("ALREADY_ACTIVE", "DUPLICATE_MATERIAL_IDENTITY")
    assert later.hypothesis == shadow  # same id, historical provenance untouched
    assert (shadow.analysis_admission_class, shadow.strategy_analysis_admission_id) == (
        "MATURE_ADVISORY",
        advisory.receipt.strategy_analysis_admission_id,
    )
    assert ledger.get_record(shadow.pressure_hypothesis_id) == shadow


def test_receipt_admission_and_lifecycle_must_bind_exactly():
    s1b = _canonical_s1b()
    advisory = _advisory_s1b()
    assert s1b is not None
    mismatched_admission = build_pressure_hypothesis_v31(
        receipt=s1b.receipt,
        admission=advisory.admission,
        lifecycle=s1b.lifecycle,
        pressure_authority=_authority(),
        maturity_evidence=maturity_evidence_from_lineage(s1b.lineage),
        maturity_policy=_maturity(),
        clock_policy=CLOCK,
        decision_at=DECISION,
    )
    assert mismatched_admission.reason_code == "ADMISSION_RECEIPT_MISMATCH"
    foreign_lifecycle = build_pressure_hypothesis_v31(
        receipt=s1b.receipt,
        admission=s1b.admission,
        lifecycle=advisory.lifecycle,
        pressure_authority=_authority(),
        maturity_evidence=maturity_evidence_from_lineage(s1b.lineage),
        maturity_policy=_maturity(),
        clock_policy=CLOCK,
        decision_at=DECISION,
    )
    assert foreign_lifecycle.reason_code == "LIFECYCLE_BINDING_MISMATCH"
    with pytest.raises(ValidationError):  # a PairAdmission lineage is never an admission receipt
        build_pressure_hypothesis_v31(
            receipt=s1b.lineage,
            admission=s1b.admission,
            lifecycle=s1b.lifecycle,
            pressure_authority=_authority(),
            maturity_evidence=None,
            maturity_policy=None,
            clock_policy=CLOCK,
            decision_at=DECISION,
        )


# --- durability (H4/H5), unchanged ------------------------------------------------------------------------------


def _transition(ledger, record, to_state, *, event, at, context="UNRESOLVED", location="UNKNOWN", classification=None):
    item = make_transition_v31(
        record=record,
        history=ledger.transitions(record.pressure_hypothesis_id),
        to_state=to_state,
        context_alignment=context,
        location_alignment=location,
        reason_code=f"TEST_{to_state}",
        material_event_id=event,
        material_event_hash=canonical_sha256_v31([event]),
        occurred_at=at,
        classification=classification,
    )
    ledger.append_transition(item)
    return item


def test_context_conflict_changes_state_not_direction_and_price_failure_keeps_it_durable():
    ledger = InMemoryPressureHypothesisLedgerV31()
    record = admit_hypothesis_v31(ledger, _build(), decision_at=DECISION).hypothesis
    assert record is not None
    _transition(
        ledger,
        record,
        "CONTEXT_CONFLICT",
        event="ctx-1",
        at=DECISION + timedelta(seconds=10),
        context="CONFLICT",
        classification="COUNTER_PRESSURE_PENDING_PROOF",
    )
    _transition(
        ledger,
        record,
        "WAITING_PRICE_QUALITY",
        event="quote-1",
        at=DECISION + timedelta(seconds=20),
        context="CONFLICT",
    )
    assert current_state(ledger.transitions(record.pressure_hypothesis_id)) == "WAITING_PRICE_QUALITY"
    assert ledger.get_record(record.pressure_hypothesis_id) == record  # immutable record, direction BUY
    assert ledger.active(record.strategy_lifecycle_id) == record.pressure_hypothesis_id
    with pytest.raises(ValueError, match="DUPLICATE_MATERIAL_EVENT"):
        _transition(ledger, record, "WAITING_STRUCTURE", event="quote-1", at=DECISION + timedelta(seconds=30))


def test_transition_contract_rejects_unfounded_states_and_broken_chains():
    ledger = InMemoryPressureHypothesisLedgerV31()
    record = admit_hypothesis_v31(ledger, _build(), decision_at=DECISION).hypothesis
    assert record is not None
    with pytest.raises(ValueError):
        _transition(
            ledger, record, "CONTEXT_CONFLICT", event="c", at=DECISION + timedelta(seconds=1), context="ALIGNED"
        )
    with pytest.raises(ValueError):
        _transition(
            ledger,
            record,
            "WAITING_VALID_LOCATION",
            event="l",
            at=DECISION + timedelta(seconds=1),
            location="FAVORABLE",
        )
    good = _transition(
        ledger,
        record,
        "CONTEXT_ALIGNED",
        event="a",
        at=DECISION + timedelta(seconds=1),
        context="ALIGNED",
        location="FAVORABLE",
    )
    with pytest.raises(ValueError, match="APPEND_ONLY_CHAIN_VIOLATION"):
        ledger.append_transition(good)
    forged = {**good.model_dump(), "to_state": "WAITING_STRUCTURE"}
    with pytest.raises(ValueError, match="TRANSITION_HASH_MISMATCH"):
        PressureHypothesisTransitionV31.model_validate(forged)


def test_clock_is_immutable_expiry_is_terminal_and_never_revived():
    ledger = InMemoryPressureHypothesisLedgerV31()
    record = admit_hypothesis_v31(ledger, _build(), decision_at=DECISION).hypothesis
    assert record is not None
    _transition(ledger, record, "WAITING_STRUCTURE", event="m1", at=DECISION + timedelta(seconds=60))
    stored = ledger.get_record(record.pressure_hypothesis_id)
    assert stored is not None and stored.valid_until == record.valid_until  # no reset
    with pytest.raises(ValueError, match="HYPOTHESIS_CLOCK_EXPIRED"):
        _transition(ledger, record, "CONTEXT_ALIGNED", event="late", at=record.valid_until, context="ALIGNED")
    _transition(ledger, record, "EXPIRED", event="expiry", at=record.valid_until)
    with pytest.raises(ValueError, match="TERMINAL_HYPOTHESIS_NOT_REVIVED"):
        _transition(ledger, record, "WAITING_STRUCTURE", event="after", at=record.valid_until + timedelta(seconds=1))
    replay = admit_hypothesis_v31(ledger, _build(), decision_at=DECISION)
    assert (replay.outcome, replay.reason_code) == ("NOT_CREATED", "TERMINAL_HYPOTHESIS_NOT_REVIVED")


def test_new_valid_condition_after_expiry_gets_a_new_hypothesis_id():
    ledger = InMemoryPressureHypothesisLedgerV31()
    first = admit_hypothesis_v31(ledger, _build(), decision_at=DECISION).hypothesis
    assert first is not None
    later = first.valid_until + timedelta(seconds=5)
    fresh_authority = _authority(ids=("p9",), observed_at_utc=later, valid_until_utc=later + timedelta(hours=1))
    second = admit_hypothesis_v31(
        ledger, _build(authority=fresh_authority, decision_at=later), decision_at=later
    ).hypothesis
    assert second is not None and second.pressure_hypothesis_id != first.pressure_hypothesis_id
    assert current_state(ledger.transitions(first.pressure_hypothesis_id)) == "EXPIRED"
    assert ledger.active(first.strategy_lifecycle_id) == second.pressure_hypothesis_id


# --- direction flips under the S1B lineage (semantics changed vs #493: see test names) --------------------------

_FLIP_EVENTS = [_raw(0), _raw(50), _raw(60, direction="SELL"), _raw(360, direction="SELL")]


def test_admission_level_flip_inside_one_market_episode_keeps_the_lifecycle_and_supersedes_the_hypothesis():
    # Under #493 a #492 flip opened a new lifecycle. Under v3.1 the lifecycle belongs to the market episode:
    # a single opposite snapshot is TRANSITION_PENDING, not a new episode (§8.3).
    reduction = _episode((0, "BUY"), (60, "SELL"))
    buy = _canonical_s1b(reduction=reduction)
    assert buy is not None
    sell = _canonical_s1b(
        "SELL", events=_FLIP_EVENTS, reduction=reduction, ledger=buy.ledger, decided_at=START + timedelta(seconds=420)
    )
    assert sell is not None and sell.receipt.strategy_lifecycle_id == buy.receipt.strategy_lifecycle_id
    ledger = InMemoryPressureHypothesisLedgerV31()
    first = admit_hypothesis_v31(ledger, _hypothesis_from(buy), decision_at=DECISION).hypothesis
    at = START + timedelta(seconds=430)
    flipped = admit_hypothesis_v31(
        ledger,
        _hypothesis_from(
            sell, authority=_authority("SELL", ids=("s1",), observed_at_utc=at), decision_at=at, direction="SELL"
        ),
        decision_at=at,
    ).hypothesis
    assert first is not None and flipped is not None and flipped.pressure_hypothesis_id != first.pressure_hypothesis_id
    last = ledger.transitions(first.pressure_hypothesis_id)[-1]
    assert (last.to_state, last.reason_code) == ("INVALIDATED", "OPPOSITE_DIRECTION_SUPERSEDED")
    assert ledger.active(first.strategy_lifecycle_id) == flipped.pressure_hypothesis_id
    assert ledger.get_record(first.pressure_hypothesis_id) == first  # historical BUY kept, direction never mutated


def test_a_confirmed_opposite_transition_opens_a_new_episode_and_lifecycle():
    reduction = _episode((0, "BUY"), (60, "BUY"), confirmed_flip_at=200)
    buy_episode, _ = _open_episode(reduction, START + timedelta(seconds=100))
    sell = _canonical_s1b("SELL", events=_FLIP_EVENTS, reduction=reduction, decided_at=START + timedelta(seconds=420))
    assert sell is not None
    assert sell.receipt.strategy_lifecycle_id != buy_episode.strategy_lifecycle_id
    assert reduction.split_reasons.get("CONFIRMED_OPPOSITE_TRANSITION") == 1


def test_record_identity_and_class_scope_are_bound():
    record = _build().hypothesis
    assert record is not None
    with pytest.raises(ValueError, match="HYPOTHESIS_ID_NOT_DERIVED"):
        PressureDirectionalHypothesisV31.model_validate({**record.model_dump(), "direction": "SELL"})
    with pytest.raises(ValueError, match="MATURE_ADVISORY hypothesis must be"):
        PressureDirectionalHypothesisV31.model_validate(
            {**record.model_dump(), "analysis_admission_class": "MATURE_ADVISORY"}
        )
    shadow = _hypothesis_from(_advisory_s1b()).hypothesis
    assert shadow is not None
    with pytest.raises(ValueError, match="MATURE_ADVISORY hypothesis must be"):
        PressureDirectionalHypothesisV31.model_validate({**shadow.model_dump(), "risk_handoff_allowed": True})
    with pytest.raises(ValueError, match="MATURITY_POLICY_HASH_MISMATCH"):
        PressureMaturityPolicyV31(
            policy_version="x.v1",
            tiers=TIERS,
            minimum_hypothesis_maturity="QUALIFIED",
            policy_hash="sha256:" + "0" * 64,
        )


def test_advisory_admission_direction_must_match_the_pressure_direction():
    # The advisory path has no canonical maturity evidence, so only the receipt direction gate can catch this.
    decision = _hypothesis_from(_advisory_s1b(), authority=_authority("SELL", ids=("s1",)))
    assert decision.reason_code == "DIRECTION_LINEAGE_CONFLICT"


def test_hypothesis_identity_formula_is_pinned_and_admission_free():
    import json

    from contracts.strategy_5scr_identity_v31 import IDENTITY_ENCODING_VERSION
    from contracts.strategy_5scr_pressure_hypothesis_v31 import WOLF15_V31_HYPOTHESIS_NAMESPACE

    record = _build().hypothesis
    assert record is not None
    name = json.dumps(
        [
            IDENTITY_ENCODING_VERSION,
            str(record.strategy_lifecycle_id),
            record.direction,
            record.opening_pressure_evidence_hash,
        ],
        separators=(",", ":"),
    )
    assert record.pressure_hypothesis_id == uuid5(WOLF15_V31_HYPOTHESIS_NAMESPACE, name)
