from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import timedelta

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_pair_activity import build_pair_activity_audit, pair_activity_ledger_hash
from analysis.strategy_5scr_pair_admission import build_pair_admission_audit
from analysis.strategy_5scr_raw_admission_blocks import build_raw_admission_population
from contracts.strategy_5scr_pair_activity import PairActivityAuditV31, PairActivityPolicyV31, RawActivityCoverageV31
from contracts.strategy_5scr_pair_admission import PairAdmissionGrant
from tests.test_strategy_5scr_raw_admission_blocks import START, _canary, _raw

POLICY = PairActivityPolicyV31(
    policy_id="fixture-only/gap300-ttl900", maximum_source_gap_seconds=300, grant_ttl_seconds=900
)


def coverage(events, *, status="COMPLETE", start=0, end=300):
    return RawActivityCoverageV31(
        status=status,
        ledger_id="fixture-ordered-ledger",
        deployment_id="deployment-A",
        window_start_utc=START + timedelta(seconds=start),
        window_end_utc=START + timedelta(seconds=end),
        source_ledger_hash=pair_activity_ledger_hash(events) if status == "COMPLETE" else None,
    )


def evaluate(events, *, status="COMPLETE", end=300, now=None, policy=POLICY, previous=(), proof=None):
    return build_pair_activity_audit(
        events,
        coverage=proof or coverage(events, status=status, end=end),
        policy=policy,
        decision_at_utc=START + timedelta(seconds=end if now is None else now),
        previous_evaluations=previous,
    )


def mixed():
    return [_raw(0), replace(_raw(150), direction="SELL", verdict="EXECUTE_SELL"), _raw(300)]


def test_mixed_direction_preserves_activity_but_never_hypothesis_or_order_authority():
    result = evaluate(mixed())
    assert len(result.evaluations) == 1
    receipt = result.evaluations[0]
    assert (receipt.decision, receipt.duration_seconds, receipt.direction_quality) == ("GRANTED", 300, "CONFLICT")
    assert receipt.admitted_at_utc == START + timedelta(seconds=300)
    assert receipt.hypothesis_authority is receipt.risk_authority is receipt.execution_authority is False
    with pytest.raises(ValidationError):
        PairAdmissionGrant.model_validate(receipt.model_dump(mode="json"))


def test_duplicate_and_reordered_replay_keep_ids_and_do_not_inflate_raw_count():
    events = mixed()
    first = evaluate(events)
    again = evaluate([events[2], events[0], events[1], events[1]])
    assert again.raw_event_count == 3
    assert again.duplicate_event_count == 1
    assert again.evaluations == first.evaluations


def test_source_gap_suspends_same_activity_instead_of_finalizing():
    events = [_raw(0), _raw(150), _raw(600)]
    result = evaluate(events, end=600)
    receipt = result.evaluations[0]
    assert len(result.evaluations) == 1
    assert (receipt.decision, receipt.reason_code) == ("SUSPENDED", "SUSPENDED_SOURCE_GAP")
    assert receipt.finalized_by_raw_event_id is None
    assert receipt.admission_id is None


def test_stopped_source_cannot_reuse_old_rows_inside_longer_admission_ttl():
    result = evaluate(mixed(), end=601)
    assert result.evaluations[0].reason_code == "SUSPENDED_SOURCE_GAP"
    assert result.evaluations[0].admission_id is None


@pytest.mark.parametrize("status", ["UNKNOWN", "INCOMPLETE"])
@pytest.mark.parametrize("events", [[], mixed()])
def test_unknown_coverage_never_becomes_not_applicable_or_granted(status, events):
    result = evaluate(events, status=status)
    assert result.coverage_status == status
    assert all(receipt.decision == "SUSPENDED" for receipt in result.evaluations)
    if not events:
        assert result.empty_reason == "INDETERMINATE_RAW_AUTHORITY_COVERAGE"


def test_complete_coverage_hash_must_match_actual_raw_population():
    result = evaluate(mixed(), proof=coverage([_raw(0), _raw(300)]))
    assert result.coverage_status == "INCOMPLETE"
    assert result.evaluations[0].decision == "SUSPENDED"


@pytest.mark.parametrize("now,end", [(299, 300), (300, 450)])
def test_future_raw_or_coverage_is_not_authoritative(now, end):
    result = evaluate(mixed(), now=now, end=end)
    assert result.evaluations[0].reason_code == "FUTURE_RAW_EVIDENCE"


def test_unbound_policy_does_not_adopt_a_default():
    assert evaluate(mixed(), policy=None).evaluations[0].reason_code == "PAIR_ACTIVITY_POLICY_UNBOUND"
    with pytest.raises(ValidationError):
        PairActivityPolicyV31(policy_id="unbound")


def test_cross_symbol_event_finalizes_activity_without_merging_later_return():
    events = [_raw(0), _raw(100, "GBPUSD"), _raw(300)]
    result = evaluate(events)
    assert [receipt.symbol for receipt in result.evaluations] == ["EURUSD", "GBPUSD", "EURUSD"]
    assert all(receipt.admission_id is None for receipt in result.evaluations)
    assert result.evaluations[0].finalized_by_raw_event_id is not None


def test_latest_direction_quality_changes_while_original_grant_is_immutable():
    first_events = [_raw(0), _raw(150), _raw(300)]
    old = evaluate(first_events).evaluations[0]
    events = [*first_events, replace(_raw(350), direction="SELL", verdict="EXECUTE_SELL")]
    new = evaluate(events, end=350, previous=(old,)).evaluations[0]
    assert old.direction_quality == "BUY"
    assert new.direction_quality == "CONFLICT"
    assert new.admission_id == old.admission_id
    assert new.admission_lineage_hash == old.admission_lineage_hash
    assert new.admitted_at_utc == old.admitted_at_utc
    assert new.valid_until_utc == old.valid_until_utc
    assert new.evaluation_id != old.evaluation_id


def test_late_cross_symbol_backfill_requires_reconciliation_of_original_grant():
    events = [_raw(0), _raw(150), _raw(300)]
    old = evaluate(events).evaluations[0]
    new = evaluate([*events, _raw(75, "GBPUSD")], previous=(old,))
    related = [receipt for receipt in new.evaluations if receipt.symbol == "EURUSD"]
    assert len(related) == 2
    assert all(receipt.decision == "RECONCILIATION_REQUIRED" for receipt in related)
    assert all(receipt.previous_admission_id == old.admission_id for receipt in related)
    assert all(receipt.admission_id is None for receipt in related)
    assert old.admission_id is not None


def test_gap_backfill_before_any_grant_recovers_original_activity_identity():
    sparse = [_raw(0), _raw(600)]
    old = evaluate(sparse, end=600).evaluations[0]
    complete = [_raw(0), _raw(150), _raw(300), _raw(450), _raw(600)]
    new = evaluate(complete, end=600, previous=(old,)).evaluations[0]
    assert new.activity_id == old.activity_id
    assert new.decision == "GRANTED"


def test_local_json_persistence_and_restart_replay_preserve_all_receipts(tmp_path):
    original = evaluate(mixed())
    path = tmp_path / "activity-receipt.json"
    path.write_text(original.model_dump_json(), encoding="utf-8")
    recovered = PairActivityAuditV31.model_validate_json(path.read_text(encoding="utf-8"))
    replay = evaluate(mixed(), previous=recovered.evaluations)
    assert recovered == original == replay


@pytest.mark.parametrize(
    "field,value",
    [
        ("direction_quality", "BUY"),
        ("duration_seconds", 900),
        ("execution_authority", True),
        ("source_lineage_hash", "sha256:" + "0" * 64),
    ],
)
def test_persisted_receipt_tampering_fails_closed(field, value):
    payload = evaluate(mixed()).model_dump(mode="json")
    payload["evaluations"][0][field] = value
    with pytest.raises(ValidationError):
        PairActivityAuditV31.model_validate(payload)


def test_model_copy_cannot_bypass_previous_receipt_validation():
    original = evaluate(mixed()).evaluations[0]
    forged = original.model_copy(update={"direction_quality": "BUY"})
    with pytest.raises(ValidationError):
        evaluate(mixed(), previous=(forged,))


def test_derived_pressure_and_canary_cannot_create_activity():
    result = evaluate([_canary(0), _canary(300)])
    assert result.raw_event_count == 0
    assert result.evaluations == ()
    assert result.skipped_non_authority_event_count == 2


def test_legacy_v2_grant_receipts_are_unchanged_by_activity_evaluation():
    events = [_raw(0), _raw(150), _raw(300)]
    population = build_raw_admission_population(events)
    old = build_pair_admission_audit(population.blocks, raw_events=population.events)
    before = json.dumps(old.to_payload(), sort_keys=True)
    evaluate(events)
    again = build_pair_admission_audit(population.blocks, raw_events=population.events)
    assert json.dumps(again.to_payload(), sort_keys=True) == before
    assert len(build_raw_admission_population(mixed()).blocks) == 3


def test_omitted_prior_admitted_activity_requires_reconciliation():
    old = evaluate(mixed()).evaluations[0]
    with pytest.raises(ValueError, match="missing from raw replay"):
        evaluate([], previous=(old,))


def test_future_cross_symbol_finalizer_cannot_authorize_earlier_block():
    events = [*mixed(), _raw(450, "GBPUSD")]
    result = evaluate(events, end=300, now=300)
    assert result.coverage_status == "INCOMPLETE"
    assert all(item.decision != "GRANTED" for item in result.evaluations)


def test_global_window_mismatch_suspends_all_blocks():
    events = [_raw(0, "GBPUSD"), _raw(100), _raw(250), _raw(400)]
    result = evaluate(events, end=400, proof=coverage(events, start=50, end=400))
    assert result.coverage_status == "INCOMPLETE"
    assert all(item.decision != "GRANTED" for item in result.evaluations)


def test_future_empty_coverage_is_not_no_raw_activity():
    result = evaluate([], end=450, now=300)
    assert result.coverage_status == "INCOMPLETE"
    assert result.empty_reason == "INDETERMINATE_RAW_AUTHORITY_COVERAGE"


def test_empty_unknown_receipt_cannot_be_tampered_to_no_raw_activity():
    payload = evaluate([], status="UNKNOWN").model_dump(mode="json")
    payload["empty_reason"] = "NO_RAW_ACTIVITY"
    with pytest.raises(ValidationError):
        PairActivityAuditV31.model_validate(payload)


def test_model_construct_cannot_bypass_coverage_validation():
    proof = coverage(mixed()).model_copy(update={"source_ledger_hash": None})
    with pytest.raises(ValidationError):
        evaluate(mixed(), proof=proof)


def test_changed_policy_does_not_reauthorize_original_admission():
    old = evaluate(mixed()).evaluations[0]
    changed = POLICY.model_copy(update={"policy_id": "fixture-new-policy"})
    result = evaluate(mixed(), policy=changed, previous=(old,)).evaluations[0]
    assert result.decision == "RECONCILIATION_REQUIRED"
    assert result.previous_admission_id == old.admission_id


def test_admission_expiry_never_extends_from_later_telemetry():
    events = [_raw(0), _raw(150), _raw(300)]
    old = evaluate(events).evaluations[0]
    expanded = [*events, *[_raw(second) for second in (450, 600, 750, 900, 1050, 1200)]]
    new = evaluate(expanded, end=1200, previous=(old,)).evaluations[0]
    assert new.reason_code == "EXPIRED_GRANT"
    assert new.admission_id is None
    assert new.previous_admission_id == old.admission_id


def test_persisted_activity_order_cannot_hide_global_symbol_interruptions():
    events = [_raw(0), _raw(100, "GBPUSD"), _raw(300)]
    payload = evaluate(events).model_dump(mode="json")
    payload["evaluations"] = list(reversed(payload["evaluations"]))
    with pytest.raises(ValidationError):
        PairActivityAuditV31.model_validate(payload)


def test_smaller_explicit_gap_policy_does_not_inherit_fixture_300_seconds():
    policy = PairActivityPolicyV31(policy_id="fixture-gap100", maximum_source_gap_seconds=100, grant_ttl_seconds=900)
    result = evaluate(mixed(), policy=policy)
    assert len(result.evaluations) == 1
    assert result.evaluations[0].reason_code == "SUSPENDED_SOURCE_GAP"


def test_policy_instance_with_nan_is_revalidated():
    policy = POLICY.model_copy(update={"maximum_source_gap_seconds": float("nan")})
    with pytest.raises(ValidationError):
        evaluate(mixed(), policy=policy)


def test_coverage_incomplete_does_not_delete_previous_admission_provenance():
    old = evaluate(mixed()).evaluations[0]
    new = evaluate(mixed(), status="UNKNOWN", previous=(old,)).evaluations[0]
    assert new.decision == "SUSPENDED"
    assert new.previous_admission_id == old.admission_id
    assert new.admission_id is None


def test_finalized_activity_uses_cross_symbol_boundary_with_fresh_global_source():
    policy = PairActivityPolicyV31(policy_id="fixture-gap60", maximum_source_gap_seconds=60, grant_ttl_seconds=900)
    first_events = [_raw(second) for second in (0, 60, 120, 180, 240, 300)]
    old = evaluate(first_events, policy=policy).evaluations[0]
    events = [*first_events, _raw(301, "GBPUSD"), _raw(350, "GBPUSD"), _raw(370, "GBPUSD")]
    result = evaluate(events, end=370, policy=policy, previous=(old,))
    first = result.evaluations[0]
    assert first.decision == "GRANTED"
    assert first.admission_id == old.admission_id
    assert first.finalized_at_utc == START + timedelta(seconds=301)
    assert first.global_observed_through_utc == START + timedelta(seconds=370)
    assert evaluate(first_events, end=370, policy=policy).evaluations[0].reason_code == "SUSPENDED_SOURCE_GAP"


def test_forged_finalizer_timestamp_cannot_bypass_global_audit_ordering():
    from contracts.strategy_5scr_pair_activity import activity_hash

    events = [*mixed(), _raw(310, "GBPUSD"), _raw(350, "GBPUSD")]
    payload = evaluate(events, end=350).model_dump(mode="json")
    first = payload["evaluations"][0]
    first["finalized_at_utc"] = (START + timedelta(seconds=305)).isoformat().replace("+00:00", "Z")
    first["evaluation_id"] = (
        "5scr-activity-eval-v31:"
        + activity_hash({key: value for key, value in first.items() if key != "evaluation_id"})[7:39]
    )
    with pytest.raises(ValidationError, match="watermark mismatch"):
        PairActivityAuditV31.model_validate(payload)


def test_finalized_grant_does_not_hide_a_stopped_global_source():
    policy = PairActivityPolicyV31(policy_id="fixture-gap60", maximum_source_gap_seconds=60, grant_ttl_seconds=900)
    events = [_raw(second) for second in (0, 60, 120, 180, 240, 300)] + [_raw(301, "GBPUSD")]
    result = evaluate(events, end=370, policy=policy)
    assert all(item.reason_code == "SUSPENDED_SOURCE_GAP" for item in result.evaluations)


# A source observation groups raw delivery facts, not Microboost transitions.
def source_observation(event, source_id):
    payload = asdict(event)
    payload.update(source_observation_id=source_id, source_observation_schema="signal-throttle-observation.v1")
    return payload


def test_explicit_twins_reduce_logical_count_and_preserve_raw_fact_lineage():
    from analysis.strategy_5scr_pair_activity import normalize_pair_activity_observations
    from tests.test_strategy_5scr_raw_admission_blocks import _runtime_throttle_pair

    raw = [event for second in (0, 150, 300) for event in _runtime_throttle_pair(second)]
    bound = [source_observation(event, f"producer-call-{index // 2}") for index, event in enumerate(raw)]
    result = normalize_pair_activity_observations(bound)
    assert (result.raw_event_count, result.logical_observation_count) == (6, 3)
    assert all(len(item.source_raw_event_ids) == 2 for item in result.logical_observations)
    bound_receipt = evaluate(bound).evaluations[0]
    legacy_receipt = evaluate(raw).evaluations[0]
    assert bound_receipt.duration_seconds == legacy_receipt.duration_seconds == 300
    assert bound_receipt.direction_quality == legacy_receipt.direction_quality == "BUY"
    assert bound_receipt.admission_id != legacy_receipt.admission_id
    assert len(bound_receipt.observations) == 6
    assert result.execution_authority is False


def test_unbound_twins_remain_distinct_even_with_identical_time_and_cycle():
    from analysis.strategy_5scr_pair_activity import normalize_pair_activity_observations
    from tests.test_strategy_5scr_raw_admission_blocks import _runtime_throttle_pair

    result = normalize_pair_activity_observations(_runtime_throttle_pair(0))
    assert result.logical_observation_count == result.raw_event_count == 2
    assert all(item.identity_basis == "RAW_EVENT_ID" for item in result.logical_observations)


def test_reordered_duplicate_delivery_and_restart_keep_logical_ids_and_duration():
    from analysis.strategy_5scr_pair_activity import normalize_pair_activity_observations
    from contracts.strategy_5scr_pair_activity import PairActivityObservationNormalizationV1

    bound = [source_observation(event, f"source-{index}") for index, event in enumerate(mixed())]
    first = normalize_pair_activity_observations(bound)
    replay = normalize_pair_activity_observations([bound[2], bound[0], bound[1], bound[1]])
    restored = PairActivityObservationNormalizationV1.model_validate_json(first.model_dump_json())
    assert restored == first
    assert replay.logical_observations == restored.logical_observations
    assert replay.raw_population_hash == restored.raw_population_hash
    assert replay.duplicate_delivery_count == 1
    result = evaluate([*bound, bound[1]])
    receipt = result.evaluations[0]
    assert (receipt.duration_seconds, receipt.direction_quality) == (300, "CONFLICT")
    assert len(result.evaluations) == 1
    assert receipt.execution_authority is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("timestamp", START + timedelta(seconds=300)),
        ("symbol", "GBPUSD"),
        ("scanner_cycle_id", "another-cycle"),
        ("direction", "SELL"),
    ],
)
def test_reused_source_observation_with_conflicting_facts_fails_closed(field, value):
    from analysis.strategy_5scr_pair_activity import normalize_pair_activity_observations

    original = source_observation(_raw(0), "immutable-source-call")
    conflicting = {**original, field: value}
    with pytest.raises(ValueError, match="conflict"):
        normalize_pair_activity_observations([original, conflicting])
    unknown = coverage([], status="UNKNOWN")
    with pytest.raises(ValueError, match="conflict"):
        evaluate([original, conflicting], proof=unknown)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_observation_schema": None},
        {"source_observation_schema": "future-unsupported.v2"},
        {"source_observation_id": None},
        {"source_observation_id": " "},
        {"source_observation_id": 42},
    ],
)
def test_partial_or_unknown_source_identity_is_never_silently_ignored(changes):
    from analysis.strategy_5scr_pair_activity import normalize_pair_activity_observations

    event = {**source_observation(_raw(0), "call-1"), **changes}
    with pytest.raises(ValueError, match="identity requires"):
        normalize_pair_activity_observations([event])


def test_distinct_source_observations_at_identical_timestamp_and_payload_remain_distinct():
    from analysis.strategy_5scr_pair_activity import normalize_pair_activity_observations

    result = normalize_pair_activity_observations(
        [
            source_observation(_raw(0), "first"),
            source_observation(_raw(0), "second"),
            source_observation(_raw(0), "first"),
        ]
    )
    assert result.logical_observation_count == result.raw_event_count == 2
    assert result.duplicate_delivery_count == 1
    assert len({item.observation_id for item in result.logical_observations}) == 2
    assert len({item.raw_event_id for item in result.raw_observations}) == 2


def test_raw_identity_version_changes_only_explicit_source_bound_facts():
    from analysis.strategy_5scr_pair_activity import pair_activity_raw_event_id
    from analysis.strategy_5scr_raw_admission_blocks import raw_signal_throttle_event_id

    event = _raw(0)
    assert pair_activity_raw_event_id(event) == raw_signal_throttle_event_id(event)
    assert pair_activity_raw_event_id(asdict(event)) == raw_signal_throttle_event_id(event)
    bound = source_observation(event, "source-1")
    assert pair_activity_raw_event_id(bound) != raw_signal_throttle_event_id(event)
    assert pair_activity_raw_event_id(dict(bound)) == pair_activity_raw_event_id(bound)


def test_same_scanner_cycle_does_not_collapse_distinct_source_observations():
    from analysis.strategy_5scr_pair_activity import normalize_pair_activity_observations

    events = [
        source_observation(replace(_raw(second), scanner_cycle_id="one-window"), f"call-{second}")
        for second in (0, 150, 300)
    ]
    result = normalize_pair_activity_observations(events)
    assert result.logical_observation_count == 3
    assert evaluate(events).evaluations[0].duration_seconds == 300


def test_normalization_rejects_forged_nested_identity_and_incomplete_raw_mapping():
    from analysis.strategy_5scr_pair_activity import normalize_pair_activity_observations
    from contracts.strategy_5scr_pair_activity import PairActivityObservationNormalizationV1

    result = normalize_pair_activity_observations([source_observation(_raw(0), "call-1")])
    forged = result.logical_observations[0].model_copy(update={"observation_id": "sha256:" + "0" * 64})
    with pytest.raises(ValueError, match="identity mismatch"):
        PairActivityObservationNormalizationV1(**{**result.model_dump(), "logical_observations": (forged,)})
    with pytest.raises(ValueError, match="cover each raw fact"):
        PairActivityObservationNormalizationV1(
            **{**result.model_dump(), "logical_observations": (), "logical_observation_count": 0}
        )


def test_source_identity_does_not_override_gap_or_backfill_reconciliation():
    bound = [source_observation(event, f"source-{index}") for index, event in enumerate(mixed())]
    initial = evaluate(bound).evaluations[0]
    stale = evaluate(bound, end=601, previous=(initial,)).evaluations[0]
    assert stale.reason_code == "SUSPENDED_SOURCE_GAP"
    backfill = source_observation(_raw(75, "GBPUSD"), "late-source")
    replay = evaluate([*bound, backfill], previous=(initial,))
    related = [item for item in replay.evaluations if item.symbol == "EURUSD"]
    assert all(item.decision == "RECONCILIATION_REQUIRED" for item in related)
    assert all(item.previous_admission_id == initial.admission_id for item in related)


@pytest.mark.parametrize("reverse", [False, True])
def test_explicit_equal_time_cross_symbol_order_never_manufactures_threshold_grant(reverse):
    from analysis.strategy_5scr_pair_activity import normalize_pair_activity_observations

    events = [
        source_observation(_raw(0), "start"),
        source_observation(_raw(300, "GBPUSD"), "earlier-B"),
        source_observation(_raw(300), "later-A"),
    ]
    if reverse:
        events.reverse()
    with pytest.raises(ValueError, match="AMBIGUOUS_GLOBAL_SOURCE_ORDER"):
        normalize_pair_activity_observations(events)
    with pytest.raises(ValueError, match="AMBIGUOUS_GLOBAL_SOURCE_ORDER"):
        evaluate(events, proof=coverage([], status="UNKNOWN"))


def test_legacy_equal_time_population_remains_compatible_but_mixed_binding_is_ambiguous():
    from analysis.strategy_5scr_pair_activity import normalize_pair_activity_observations

    legacy = [_raw(0), _raw(300, "GBPUSD"), _raw(300)]
    assert normalize_pair_activity_observations(legacy).raw_event_count == 3
    with pytest.raises(ValueError, match="AMBIGUOUS_GLOBAL_SOURCE_ORDER"):
        normalize_pair_activity_observations([*legacy[:2], source_observation(legacy[2], "bound-A")])
