"""Gap #7 acceptance: PressureDirectionalHypothesisV31, CANONICAL_RAW only (authority decisions H1-H5, 2026-09-19)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from analysis.strategy_5scr_pressure_hypothesis_v31 import (
    InMemoryPressureHypothesisLedgerV31,
    admit_hypothesis_v31,
    build_pressure_hypothesis_v31,
    current_state,
    make_transition_v31,
    maturity_evidence_from_lineage,
)
from contracts.strategy_5scr_admission_identity_v31 import admission_receipt_hash_v31, build_admission_receipt_v31
from contracts.strategy_5scr_pressure_authority_v31 import PressureAuthorityV31
from contracts.strategy_5scr_pressure_hypothesis_v31 import (
    MaturityTierV31,
    PressureDirectionalHypothesisV31,
    PressureHypothesisClockPolicyV31,
    PressureHypothesisTransitionV31,
    PressureMaturityPolicyV31,
    canonical_sha256_v31,
)
from tests.test_strategy_5scr_per_symbol_admission import POLICY, START, _evaluate, _raw, _safety

TIERS = (
    MaturityTierV31(status="QUALIFIED", min_duration_seconds=300, min_effective_ticks=2, min_direction_stability=1.0),
    MaturityTierV31(status="MATURE", min_duration_seconds=600, min_effective_ticks=4, min_direction_stability=1.0),
)


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


def _inputs(direction: str = "BUY", *, safety=None, events=None):
    evaluation = _evaluate(events or [_raw(0, direction=direction), _raw(300, direction=direction)], safety=safety)
    lineage = evaluation.lineages["EURUSD"][-1]
    receipt = build_admission_receipt_v31(lineage, policy=POLICY)
    return lineage, receipt


def _build(direction: str = "BUY", *, authority=None, maturity=None, clock=CLOCK, decision_at=DECISION, **kw):
    lineage, receipt = _inputs(direction, **kw)
    return build_pressure_hypothesis_v31(
        admission_receipt=receipt,
        admission_receipt_hash=admission_receipt_hash_v31(receipt),
        lifecycle_anchor="eurusd-lifecycle-1",
        pressure_authority=authority or _authority(direction),
        maturity_evidence=maturity_evidence_from_lineage(lineage) if lineage.direction else None,  # type: ignore[arg-type]
        maturity_policy=_maturity() if maturity is None else maturity,
        clock_policy=clock,
        decision_at=decision_at,
    )


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


def test_granted_but_insufficient_maturity_creates_nothing():
    decision = _build(maturity=_maturity("MATURE"))
    assert (decision.outcome, decision.reason_code) == ("NOT_CREATED", "PRESSURE_MATURITY_INSUFFICIENT")


def test_not_granted_admission_creates_no_canonical_raw_hypothesis_even_if_mature():
    events = [_raw(0), _raw(100)]  # below the admission threshold: decision None / PENDING_THRESHOLD
    decision = _build(
        events=events,
        maturity=PressureMaturityPolicyV31(
            policy_version="lenient.v1",
            tiers=(
                MaturityTierV31(
                    status="EXTREME", min_duration_seconds=0, min_effective_ticks=0, min_direction_stability=0
                ),
            ),
            minimum_hypothesis_maturity="QUALIFIED",
            policy_hash=PressureMaturityPolicyV31.compute_hash(
                "lenient.v1",
                (
                    MaturityTierV31(
                        status="EXTREME", min_duration_seconds=0, min_effective_ticks=0, min_direction_stability=0
                    ),
                ),
                "QUALIFIED",
            ),
        ),
    )
    assert (decision.outcome, decision.reason_code) == ("NOT_CREATED", "ADMISSION_NOT_GRANTED")


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
        ({"maturity": None}, None),
        ({"clock": None}, "HYPOTHESIS_CLOCK_POLICY_MISSING"),
        ({"decision_at": START + timedelta(seconds=3600)}, "PRESSURE_EVIDENCE_STALE_OR_EXPIRED"),
    ],
)
def test_missing_policy_or_stale_evidence_fails_closed(kwargs, reason):
    if "maturity" in kwargs:
        lineage, receipt = _inputs()
        decision = build_pressure_hypothesis_v31(
            admission_receipt=receipt,
            admission_receipt_hash=admission_receipt_hash_v31(receipt),
            lifecycle_anchor="a",
            pressure_authority=_authority(),
            maturity_evidence=maturity_evidence_from_lineage(lineage),
            maturity_policy=None,
            clock_policy=CLOCK,
            decision_at=DECISION,
        )
        assert (decision.outcome, decision.reason_code) == ("NOT_CREATED", "PRESSURE_MATURITY_POLICY_MISSING")
    else:
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


def test_pressure_level_flip_in_one_lifecycle_supersedes_and_moves_the_single_active_pointer():
    ledger = InMemoryPressureHypothesisLedgerV31()
    buy = admit_hypothesis_v31(ledger, _build(), decision_at=DECISION).hypothesis
    lineage, receipt = _inputs()
    sell_evidence = maturity_evidence_from_lineage(lineage).model_copy(update={"direction": "SELL"})
    sell_decision = build_pressure_hypothesis_v31(
        admission_receipt=receipt,
        admission_receipt_hash=admission_receipt_hash_v31(receipt),
        lifecycle_anchor="eurusd-lifecycle-1",
        pressure_authority=_authority("SELL", ids=("s1",)),
        maturity_evidence=sell_evidence,
        maturity_policy=_maturity(),
        clock_policy=CLOCK,
        decision_at=DECISION + timedelta(seconds=30),
    )
    assert buy is not None and sell_decision.hypothesis is not None
    assert sell_decision.hypothesis.strategy_lifecycle_id == buy.strategy_lifecycle_id
    sell = admit_hypothesis_v31(ledger, sell_decision, decision_at=DECISION + timedelta(seconds=30)).hypothesis
    assert sell is not None and sell.pressure_hypothesis_id != buy.pressure_hypothesis_id
    last = ledger.transitions(buy.pressure_hypothesis_id)[-1]
    assert (last.to_state, last.reason_code) == ("INVALIDATED", "OPPOSITE_DIRECTION_SUPERSEDED")
    assert ledger.active(buy.strategy_lifecycle_id) == sell.pressure_hypothesis_id
    assert ledger.get_record(buy.pressure_hypothesis_id) == buy  # historical BUY kept, direction never mutated
    assert (buy.direction, sell.direction) == ("BUY", "SELL")


def test_admission_level_flip_opens_a_new_lifecycle_and_leaves_the_old_one_untouched():
    ledger = InMemoryPressureHypothesisLedgerV31()
    buy = admit_hypothesis_v31(ledger, _build(), decision_at=DECISION).hypothesis
    flip_events = [_raw(0), _raw(50), _raw(60, direction="SELL"), _raw(360, direction="SELL")]  # all before as_of=400
    sell = admit_hypothesis_v31(
        ledger,
        _build(
            "SELL",
            authority=_authority("SELL", ids=("s1",), observed_at_utc=START + timedelta(seconds=390)),
            events=flip_events,
            decision_at=DECISION,
        ),
        decision_at=DECISION,
    ).hypothesis
    assert buy is not None and sell is not None
    assert sell.strategy_lifecycle_id != buy.strategy_lifecycle_id  # #492 flip = new admission lineage
    assert ledger.active(buy.strategy_lifecycle_id) == buy.pressure_hypothesis_id
    assert ledger.active(sell.strategy_lifecycle_id) == sell.pressure_hypothesis_id


def test_record_identity_is_bound_and_advisory_is_not_implemented():
    record = _build().hypothesis
    assert record is not None
    with pytest.raises(ValueError, match="HYPOTHESIS_ID_NOT_DERIVED"):
        PressureDirectionalHypothesisV31.model_validate({**record.model_dump(), "direction": "SELL"})
    with pytest.raises(ValueError):
        PressureDirectionalHypothesisV31.model_validate(
            {**record.model_dump(), "analysis_admission_class": "MATURE_ADVISORY"}
        )
    with pytest.raises(ValueError, match="MATURITY_POLICY_HASH_MISMATCH"):
        PressureMaturityPolicyV31(
            policy_version="x.v1",
            tiers=TIERS,
            minimum_hypothesis_maturity="QUALIFIED",
            policy_hash="sha256:" + "0" * 64,
        )
