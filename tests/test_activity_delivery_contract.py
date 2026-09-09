"""Offline protocol identities, never transaction/transport acceptance."""

from dataclasses import replace
from datetime import timedelta

import pytest
from pydantic import ValidationError

from contracts.strategy_5scr_activity_delivery import (
    ActivityConsumerScopeV1,
    ActivityDeliveryV1,
    ActivityLifecycleEmissionLinkV1,
    activity_delivery,
    classify_delivery_order,
    classify_delivery_replay,
    validate_existing_activity_owner,
)
from tests.test_strategy_5scr_pair_activity import START, evaluate, mixed


def scope(**changes):
    data = dict(
        consumer_scope_id="fixture-analysis-scope",
        producer_binding_hash="sha256:" + "1" * 64,
        lifecycle_owner_id="fixture-existing-owner",
        lifecycle_policy_hash="sha256:" + "2" * 64,
        environment_class="DISPOSABLE_TEST",
    )
    data.update(changes)
    return ActivityConsumerScopeV1(**data)


def delivery(evaluation=None, **changes):
    args = dict(
        scope=scope(),
        source_snapshot_id="sha256:" + "3" * 64,
        source_revision=3,
        activity_sequence=1,
        previous_delivery_id=None,
        evaluation=evaluation or evaluate(mixed()).evaluations[0],
    )
    args.update(changes)
    return activity_delivery(**args)


def link(event=None, **changes):
    args = dict(
        delivery=event or delivery(),
        strategy_lifecycle_id="5scr-lifecycle:" + "4" * 32,
        material_state_hash="5" * 64,
        emission_purpose="ACTIVITY_ATTACHED",
    )
    args.update(changes)
    return ActivityLifecycleEmissionLinkV1(**args)


def test_mixed_direction_300_seconds_keeps_evaluation_and_has_no_authority():
    event = delivery()
    assert event.evaluation.duration_seconds == 300
    assert event.evaluation.direction_quality == "CONFLICT"
    assert event.evaluation.decision == "GRANTED"
    assert classify_delivery_replay(event, None) == "NEW_REQUIRES_OWNER_VALIDATION"
    for obj in (event, event.scope, link(event)):
        assert obj.hypothesis_authority is obj.risk_authority is obj.execution_authority is False


def test_duplicate_and_serialized_restart_keep_delivery_attachment_and_emission_ids():
    event = delivery()
    restored = ActivityDeliveryV1.model_validate_json(event.model_dump_json())
    assert classify_delivery_replay(restored, event) == "DUPLICATE_NO_EFFECT"
    first = link(event)
    restored_link = ActivityLifecycleEmissionLinkV1.model_validate_json(first.model_dump_json())
    assert restored_link.attachment_id == first.attachment_id
    assert restored_link.analysis_emission_id == first.analysis_emission_id
    validate_existing_activity_owner(first, restored_link)


def test_same_delivery_key_changed_snapshot_is_quarantined_not_overwritten():
    first = delivery()
    changed = delivery(source_snapshot_id="sha256:" + "6" * 64)
    assert changed.delivery_id == first.delivery_id
    assert classify_delivery_replay(changed, first) == "QUARANTINE_PAYLOAD_CONFLICT"


def test_different_inbox_key_cannot_be_compared_as_duplicate():
    with pytest.raises(ValueError, match="INBOX_KEY_MISMATCH"):
        classify_delivery_replay(delivery(scope=scope(consumer_scope_id="other")), delivery())


def test_new_evaluation_does_not_mint_lifecycle_or_duplicate_unchanged_emission():
    first = delivery()
    events = mixed()
    events.append(replace(events[-1], timestamp=START + timedelta(seconds=350), scanner_cycle_id="scan-350"))
    update = delivery(evaluate(events, end=350, previous=(first.evaluation,)).evaluations[0], source_revision=4)
    assert first.delivery_id != update.delivery_id
    assert first.evaluation.activity_id == update.evaluation.activity_id
    before, after = link(first), link(update)
    assert before.attachment_id == after.attachment_id
    assert before.analysis_emission_id == after.analysis_emission_id
    validate_existing_activity_owner(before, after)
    assert link(update, material_state_hash="7" * 64).analysis_emission_id != before.analysis_emission_id


def test_one_activity_cannot_silently_rebind_lifecycle():
    first = link()
    changed = link(strategy_lifecycle_id="5scr-lifecycle:" + "8" * 32)
    assert first.attachment_id == changed.attachment_id
    with pytest.raises(ValueError, match="ACTIVITY_OWNER_REBIND"):
        validate_existing_activity_owner(first, changed)


def test_policy_or_writer_change_needs_explicit_migration():
    first = link()
    changed = link(delivery(scope=scope(lifecycle_owner_id="other-owner")))
    with pytest.raises(ValueError, match="ACTIVITY_OWNER_REBIND"):
        validate_existing_activity_owner(first, changed)


@pytest.mark.parametrize("field", ["hypothesis_authority", "risk_authority", "execution_authority"])
@pytest.mark.parametrize("value", [True, 0, "false"])
def test_authority_injection_is_rejected(field, value):
    with pytest.raises(ValidationError):
        scope(**{field: value})


def test_model_copy_cannot_bypass_nested_authority_or_evaluation_integrity():
    original = delivery()
    for changed in (
        original.model_copy(update={"scope": original.scope.model_copy(update={"execution_authority": True})}),
        original.model_copy(update={"evaluation": original.evaluation.model_copy(update={"duration_seconds": 301})}),
        original.model_copy(update={"execution_authority": True}),
    ):
        with pytest.raises(ValidationError):
            classify_delivery_replay(changed, None)


@pytest.mark.parametrize("extra", ["retry_count", "attempt_id", "command_id", "account_id"])
def test_transport_attempt_and_execution_fields_are_not_delivery_facts(extra):
    data = delivery().model_dump(mode="json")
    data[extra] = "injected"
    with pytest.raises(ValidationError):
        ActivityDeliveryV1.model_validate(data)


def test_pending_evaluation_cannot_claim_lifecycle_attachment():
    pending = evaluate(mixed(), policy=None).evaluations[0]
    with pytest.raises(ValidationError, match="DELIVERY_EFFECT_DECISION_MISMATCH"):
        link(delivery(pending))


def test_suspension_preserves_existing_mapping_and_has_distinct_emission_purpose():
    granted = evaluate(mixed()).evaluations[0]
    suspended = evaluate(mixed(), status="INCOMPLETE", previous=(granted,)).evaluations[0]
    event = delivery(suspended)
    with pytest.raises(ValidationError, match="DELIVERY_EFFECT_DECISION_MISMATCH"):
        link(event)
    before, after = link(delivery(granted)), link(event, emission_purpose="ACTIVITY_SUSPENDED")
    validate_existing_activity_owner(before, after)
    assert before.attachment_id == after.attachment_id
    assert before.analysis_emission_id != after.analysis_emission_id


def _second(first, **changes):
    # No raw append: decision time changes while ledger revision stays constant.
    evaluation = evaluate(mixed(), now=301, previous=(first.evaluation,)).evaluations[0]
    return delivery(evaluation, activity_sequence=2, previous_delivery_id=first.delivery_id, **changes)


def test_delivery_sequence_handles_new_evaluation_without_raw_revision_change():
    first = delivery()
    second = _second(first)
    assert first.source_revision == second.source_revision
    assert first.delivery_id != second.delivery_id
    assert classify_delivery_order(first, None) == "NEXT_REQUIRES_OWNER_VALIDATION"
    assert classify_delivery_order(second, first) == "NEXT_REQUIRES_OWNER_VALIDATION"
    assert classify_delivery_order(second, None) == "WAITING_PREDECESSOR"
    assert classify_delivery_order(first, second) == "STALE_REQUIRES_RECONCILIATION"


def test_missing_predecessor_and_conflicting_chain_do_not_apply():
    first = delivery()
    second = _second(first)
    gap = second.model_copy(update={"activity_sequence": 3})
    assert classify_delivery_order(gap, first) == "WAITING_PREDECESSOR"
    conflict = second.model_copy(update={"previous_delivery_id": "5scr-activity-delivery:" + "f" * 32})
    assert classify_delivery_order(conflict, first) == "QUARANTINE_CHAIN_CONFLICT"
    regressed = second.model_copy(update={"source_revision": 2})
    assert classify_delivery_order(regressed, first) == "QUARANTINE_SOURCE_REGRESSION"


@pytest.mark.parametrize("sequence,previous", [(1, "5scr-activity-delivery:" + "f" * 32), (2, None), (0, None)])
def test_sequence_and_predecessor_shape_are_required(sequence, previous):
    with pytest.raises(ValidationError):
        delivery(activity_sequence=sequence, previous_delivery_id=previous)
