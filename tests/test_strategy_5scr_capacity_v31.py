from datetime import timedelta
from fractions import Fraction
from uuid import UUID

import pytest
from pydantic import ValidationError

from contracts.strategy_5scr_capacity_v31 import CapacityLedgerV31, CapacityReleaseEvidenceV31
from contracts.strategy_5scr_risk_adapter_v31 import ExactAmountV31, ParentSizingRequestV31
from risk.strategy_5scr_capacity_v31 import (
    CapacityRejectedError,
    capacity_content_hash_v31,
    capacity_ledger_hash_v31,
    capacity_used_v31,
    reserve_parent_capacity_v31,
    transition_capacity_v31,
)
from risk.strategy_5scr_risk_adapter_v31 import parent_sizing_request_hash_v31
from tests.test_strategy_5scr_risk_adapter_v31 import NOW, data

H = "sha256:" + "5" * 64


def exact(value):
    value = Fraction(value)
    return ExactAmountV31(numerator=value.numerator, denominator=value.denominator)


def seed():
    payload = data()
    request = ParentSizingRequestV31.model_validate(payload)
    return CapacityLedgerV31(
        profile="TEST_ONLY",
        parent_slot_policy="ONE_PARENT_PER_THESIS_TEST_V1",
        account_id=payload["expected_account_id"],
        executor_id=payload["expected_executor_id"],
        account_snapshot_id=payload["snapshot"]["snapshot_id"],
        account_snapshot_hash=capacity_content_hash_v31(request.snapshot),
        closed_balance_usd=str(request.snapshot.balance),
        risk_policy_hash=payload["policy"]["policy_hash"],
        risk_policy_content_hash=capacity_content_hash_v31(request.policy),
        owner_epoch=1,
        version=0,
        as_of=NOW,
        baseline_captured_at=NOW,
        baseline_evidence_hash=H,
        baseline_external_risk_usd=exact(0),
        reservation_ttl_seconds=10,
        release_evidence_max_age_seconds=5,
        reservations=(),
    )


def request_for(ledger, n=1, now=NOW):
    payload = data()
    payload.update(
        tradeplan_id=f"fixture-plan-{n}",
        thesis_id=f"fixture-thesis-{n}",
        campaign_id=f"fixture-campaign-{n}",
        evaluated_at=now,
        risk_state_evidence_hash=capacity_ledger_hash_v31(ledger),
        risk_state_captured_at=ledger.baseline_captured_at,
        account_committed_and_reserved_risk_usd=exact(capacity_used_v31(ledger)),
        campaign_committed_and_reserved_risk_usd=exact(0),
    )
    payload["geometry"]["decision_at"] = now
    payload["geometry"]["costs"]["valid_until"] = now + timedelta(seconds=1)
    return ParentSizingRequestV31.model_validate(payload)


def reserve(ledger, request=None, *, n=1, now=NOW, **overrides):
    request = request or request_for(ledger, n, now)
    pinned = parent_sizing_request_hash_v31(request)
    args = dict(
        reservation_id=UUID(int=n),
        expires_at=now + timedelta(seconds=1),
        now=now,
        owner_epoch=ledger.owner_epoch,
        expected_version=ledger.version,
        verify_inputs=lambda _, digest: digest == pinned,
    )
    args.update(overrides)
    return reserve_parent_capacity_v31(ledger, request, **args)


def transition(ledger, action, *, now=NOW, **overrides):
    args = dict(
        reservation_id=UUID(int=1),
        action=action,
        now=now,
        owner_epoch=ledger.owner_epoch,
        expected_version=ledger.version,
    )
    args.update(overrides)
    return transition_capacity_v31(ledger, **args)


def release_proof(ledger, now):
    record = ledger.reservations[0]
    return CapacityReleaseEvidenceV31(
        account_id=ledger.account_id,
        reservation_id=record.reservation_id,
        reservation_envelope_hash=record.envelope_hash,
        ledger_before_hash=capacity_ledger_hash_v31(ledger),
        source_receipt_hash=H,
        delivery_terminal_receipt_hash=H,
        delivery_disposition="BROKER_TERMINAL",
        observed_at=now,
        outcome="BROKER_TERMINAL_RECONCILED",
    )


def test_sizing_reserve_restart_lost_ack_and_duplicate_are_one_record():
    ledger = seed()
    request = request_for(ledger)
    original = ledger.model_dump_json()
    result = reserve(ledger, request)
    restored = CapacityLedgerV31.model_validate_json(result.ledger.model_dump_json())
    replay = reserve(restored, request, expected_version=0)
    assert replay.status == "DUPLICATE_TEST_ONLY"
    assert replay.ledger == result.ledger
    assert replay.reservation == result.reservation
    assert len(restored.reservations) == restored.version == 1
    assert capacity_used_v31(restored) == Fraction(
        result.reservation.sizing.planned_loss_usd.numerator, result.reservation.sizing.planned_loss_usd.denominator
    )
    assert ledger.model_dump_json() == original
    assert result.execution_authority is result.capital_reservation_authority is False


def test_changed_payload_with_same_reservation_id_is_conflict():
    initial = seed()
    request = request_for(initial)
    committed = reserve(initial, request).ledger
    with pytest.raises(CapacityRejectedError, match="CAPACITY_REPLAY_PAYLOAD_CONFLICT"):
        reserve(committed, request.model_copy(update={"tradeplan_revision": 2}))


def test_stale_version_competitor_must_reload_instead_of_overwrite():
    original = seed()
    stale_request = request_for(original, n=2)
    committed = reserve(original).ledger
    with pytest.raises(CapacityRejectedError, match="CAPACITY_VERSION_CONFLICT"):
        reserve(committed, stale_request, n=2, expected_version=0)
    with pytest.raises(CapacityRejectedError, match="CAPACITY_STATE_RECEIPT_MISMATCH"):
        reserve(committed, stale_request, n=2)
    second = reserve(committed, n=2)
    assert second.ledger.version == 2 and len(second.ledger.reservations) == 2
    with pytest.raises(CapacityRejectedError, match="RISK_ACCOUNT_CAPACITY_EXCEEDED"):
        reserve(second.ledger, n=3)


def test_new_epoch_fences_previous_owner_even_for_duplicate():
    initial = seed()
    request = request_for(initial)
    committed = reserve(initial, request).ledger
    # Storage/election owns this epoch change; this test supplies its result.
    new_owner = CapacityLedgerV31.model_validate({**committed.model_dump(), "owner_epoch": 2})
    with pytest.raises(CapacityRejectedError, match="CAPACITY_OWNER_FENCED"):
        reserve(new_owner, request, owner_epoch=1)
    with pytest.raises(CapacityRejectedError, match="CAPACITY_OWNER_FENCED"):
        transition(new_owner, "MARK_DISPATCHED", owner_epoch=1)
    assert reserve(new_owner, request).status == "DUPLICATE_TEST_ONLY"


def test_expiry_releases_only_unissued_and_retains_parent_tombstone():
    initial = seed()
    request = request_for(initial)
    held = reserve(initial, request).ledger
    with pytest.raises(CapacityRejectedError, match="CAPACITY_RESERVATION_NOT_EXPIRED"):
        transition(held, "EXPIRE_UNISSUED")
    now = NOW + timedelta(seconds=1)
    expired = transition(held, "EXPIRE_UNISSUED", now=now)
    assert capacity_used_v31(expired.ledger) == 0
    assert expired.reservation.state == "EXPIRED_UNISSUED"
    # Retry original bytes after expiry must return terminal record, not recreate.
    replay = reserve(expired.ledger, request, now=now, expires_at=now, expected_version=0)
    assert replay.status == "DUPLICATE_TEST_ONLY" and replay.reservation.state == "EXPIRED_UNISSUED"
    with pytest.raises(CapacityRejectedError, match="CAPACITY_PARENT_IDENTITY_ALREADY_USED"):
        reserve(expired.ledger, request_for(expired.ledger, now=now), n=2, now=now)


def test_dispatch_timeout_keeps_capacity_until_bound_terminal_reconciliation():
    held = reserve(seed()).ledger
    pending = transition(held, "MARK_DISPATCHED").ledger
    used = capacity_used_v31(pending)
    now = NOW + timedelta(seconds=2)
    with pytest.raises(CapacityRejectedError, match="CAPACITY_BROKER_RECONCILIATION_REQUIRED"):
        transition(pending, "EXPIRE_UNISSUED", now=now)
    with pytest.raises(CapacityRejectedError, match="CAPACITY_RELEASE_EVIDENCE_UNBOUND"):
        transition(pending, "RELEASE_RECONCILED", now=now)
    assert capacity_used_v31(pending) == used > 0
    proof = release_proof(pending, now)
    released = transition(
        pending, "RELEASE_RECONCILED", now=now, release_evidence=proof, verify_release=lambda *_: True
    )
    assert capacity_used_v31(released.ledger) == 0 and released.reservation.state == "RELEASED"
    duplicate = transition(released.ledger, "RELEASE_RECONCILED", now=now, expected_version=0, release_evidence=proof)
    assert duplicate.status == "DUPLICATE_TEST_ONLY" and duplicate.ledger == released.ledger
    with pytest.raises(CapacityRejectedError, match="CAPACITY_TERMINAL_RESERVATION"):
        transition(released.ledger, "MARK_DISPATCHED", now=now)


@pytest.mark.parametrize(
    "change,reason",
    [
        ("account", "CAPACITY_RELEASE_SCOPE_MISMATCH"),
        ("state", "CAPACITY_RELEASE_SCOPE_MISMATCH"),
        ("future", "CAPACITY_RELEASE_STALE_OR_FUTURE"),
        ("stale", "CAPACITY_RELEASE_STALE_OR_FUTURE"),
        ("unfenced", "CAPACITY_DELIVERY_NOT_TERMINALLY_BOUND"),
        ("verifier", "CAPACITY_RELEASE_VERIFICATION_REJECTED"),
    ],
)
def test_release_cannot_free_capacity_on_incomplete_evidence(change, reason):
    pending = transition(reserve(seed()).ledger, "MARK_DISPATCHED").ledger
    now = NOW + timedelta(seconds=10)
    evidence = release_proof(pending, now).model_dump()

    def verifier(*_):
        return 1 if change == "verifier" else True

    if change == "account":
        evidence["account_id"] = "other"
    elif change == "state":
        evidence["ledger_before_hash"] = H
    elif change == "future":
        evidence["observed_at"] = now + timedelta(seconds=1)
    elif change == "stale":
        evidence["observed_at"] = NOW
    elif change == "unfenced":
        evidence.update(outcome="NO_BROKER_EFFECT_CONFIRMED", delivery_disposition="NEVER_ISSUED")
    before = pending.model_dump_json()
    with pytest.raises(CapacityRejectedError, match=reason):
        transition(
            pending,
            "RELEASE_RECONCILED",
            now=now,
            release_evidence=CapacityReleaseEvidenceV31(**evidence),
            verify_release=verifier,
        )
    assert pending.model_dump_json() == before


def test_rational_baseline_is_not_rounded_between_ledger_and_sizing():
    ledger = seed().model_copy(update={"baseline_external_risk_usd": exact(Fraction(1, 3))})
    result = reserve(ledger)
    used = Fraction(
        result.reservation.sizing.planned_loss_usd.numerator, result.reservation.sizing.planned_loss_usd.denominator
    )
    assert capacity_used_v31(result.ledger) == used + Fraction(1, 3)
    second = reserve(result.ledger, n=2)
    assert capacity_used_v31(second.ledger) > capacity_used_v31(result.ledger)


@pytest.mark.parametrize("control", ["owner", "version"])
def test_boolean_control_token_is_not_integer_revision(control):
    kwargs = {"owner_epoch": True} if control == "owner" else {"expected_version": False}
    with pytest.raises(CapacityRejectedError):
        reserve(seed(), **kwargs)


def test_schema_rejects_duplicate_tombstones_and_negative_exact_exposure():
    held = reserve(seed()).ledger
    with pytest.raises(ValidationError):
        CapacityLedgerV31.model_validate({**held.model_dump(), "reservations": held.reservations * 2})
    with pytest.raises(ValidationError):
        ExactAmountV31(numerator=-1, denominator=3)


def test_stale_capacity_number_or_clock_does_not_consume_state():
    ledger = seed()
    for update, reason in [
        ({"account_committed_and_reserved_risk_usd": exact(1)}, "CAPACITY_TOTAL_MISMATCH"),
        ({"risk_state_captured_at": NOW - timedelta(seconds=1)}, "CAPACITY_BASELINE_CLOCK_MISMATCH"),
    ]:
        with pytest.raises(CapacityRejectedError, match=reason):
            reserve(ledger, request_for(ledger).model_copy(update=update))
    assert ledger.version == 0 and ledger.reservations == ()


def test_sizing_verifier_exception_leaves_no_partial_proposal():
    ledger = seed()
    before = ledger.model_dump_json()

    def fail(*_):
        raise RuntimeError("fixture-verifier-failure")

    with pytest.raises(RuntimeError, match="fixture-verifier-failure"):
        reserve(ledger, verify_inputs=fail)
    assert ledger.model_dump_json() == before


def test_dispatch_at_expiry_is_rejected_and_duplicate_dispatch_keeps_risk():
    held = reserve(seed()).ledger
    with pytest.raises(CapacityRejectedError, match="CAPACITY_RESERVATION_EXPIRED"):
        transition(held, "MARK_DISPATCHED", now=NOW + timedelta(seconds=1))
    pending = transition(held, "MARK_DISPATCHED").ledger
    duplicate = transition(pending, "MARK_DISPATCHED", now=NOW + timedelta(seconds=2), expected_version=0)
    assert duplicate.status == "DUPLICATE_TEST_ONLY"
    assert duplicate.ledger == pending and capacity_used_v31(duplicate.ledger) > 0


def test_no_effect_release_requires_cancelled_fenced_delivery_after_dispatch():
    pending = transition(reserve(seed()).ledger, "MARK_DISPATCHED").ledger
    now = NOW + timedelta(seconds=2)
    proof = release_proof(pending, now).model_copy(
        update={"outcome": "NO_BROKER_EFFECT_CONFIRMED", "delivery_disposition": "CANCELLED_FENCED"}
    )
    released = transition(
        pending, "RELEASE_RECONCILED", now=now, release_evidence=proof, verify_release=lambda *_: True
    )
    assert released.reservation.state == "RELEASED" and capacity_used_v31(released.ledger) == 0


@pytest.mark.parametrize(
    "control,reason",
    [
        ("expiry", "CAPACITY_COST_EXPIRY_EXCEEDED"),
        ("ttl", "CAPACITY_RESERVATION_WINDOW_INVALID"),
        ("policy", "CAPACITY_ACCOUNT_SNAPSHOT_POLICY_MISMATCH"),
    ],
)
def test_reservation_is_bound_to_cost_expiry_ttl_and_policy(control, reason):
    ledger = seed()
    kwargs = {}
    request = request_for(ledger)
    if control == "expiry":
        kwargs["expires_at"] = NOW + timedelta(seconds=2)
    elif control == "ttl":
        kwargs["expires_at"] = NOW + timedelta(seconds=11)
    elif control == "policy":
        request = request.model_copy(update={"policy": request.policy.model_copy(update={"policy_hash": H})})
    with pytest.raises(CapacityRejectedError, match=reason):
        reserve(ledger, request, **kwargs)


def test_new_campaign_after_release_uses_available_capacity_without_reusing_tombstone():
    pending = transition(reserve(seed()).ledger, "MARK_DISPATCHED").ledger
    now = NOW + timedelta(seconds=2)
    released = transition(
        pending,
        "RELEASE_RECONCILED",
        now=now,
        release_evidence=release_proof(pending, now),
        verify_release=lambda *_: True,
    ).ledger
    next_campaign = reserve(released, n=2, now=now)
    assert len(next_campaign.ledger.reservations) == 2
    assert next_campaign.ledger.reservations[0].state == "RELEASED"
    assert capacity_used_v31(next_campaign.ledger) == Fraction(
        next_campaign.reservation.sizing.planned_loss_usd.numerator,
        next_campaign.reservation.sizing.planned_loss_usd.denominator,
    )
