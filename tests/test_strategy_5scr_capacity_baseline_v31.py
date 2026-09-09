from datetime import timedelta
from decimal import Decimal
from fractions import Fraction
from uuid import UUID

import pytest
from pydantic import ValidationError

from contracts.strategy_5scr_capacity_v31 import CapacityBaselineRefreshV31, CapacityLedgerV31
from risk.strategy_5scr_capacity_v31 import (
    CapacityRejectedError,
    baseline_refresh_hash_v31,
    capacity_ledger_hash_v31,
    capacity_used_v31,
    refresh_capacity_baseline_v31,
)
from tests.test_strategy_5scr_capacity_v31 import NOW, H, exact, release_proof, request_for, reserve, seed, transition
from tests.test_strategy_5scr_risk_adapter_v31 import data


def evidence_for(ledger, *, n=1, now=NOW + timedelta(seconds=2), balance=1100, floating=30):
    payload = data()
    snapshot = payload["snapshot"]
    snapshot.update(
        snapshot_id=f"refresh-snapshot-{n}",
        captured_at_utc=now,
        balance=balance,
        equity=balance + floating,
        floating_pnl=floating,
        free_margin=balance + floating,
    )
    return CapacityBaselineRefreshV31(
        profile="TEST_ONLY",
        operation_id=UUID(int=100 + n),
        ledger_before_hash=capacity_ledger_hash_v31(ledger),
        source_receipt_hash=H,
        snapshot=snapshot,
        policy=payload["policy"],
        coverage_from=ledger.baseline_captured_at,
        coverage_to=now,
        realized_net_pnl_usd=Decimal(str(balance)) - ledger.closed_balance_usd,
        net_cashflow_usd="0",
        broker_adjustment_usd="0",
        external_risk_usd=exact(0),
        excluded_reservation_ids=tuple(
            r.reservation_id for r in ledger.reservations if r.state in {"HELD_UNISSUED", "PENDING_RECONCILIATION"}
        ),
    )


def refresh(ledger, evidence=None, *, now=NOW + timedelta(seconds=2), **overrides):
    evidence = evidence or evidence_for(ledger, now=now)
    pinned = baseline_refresh_hash_v31(evidence)
    kwargs = dict(
        now=now,
        owner_epoch=ledger.owner_epoch,
        expected_version=ledger.version,
        verify_refresh=lambda _, digest: digest == pinned,
    )
    kwargs.update(overrides)
    return refresh_capacity_baseline_v31(ledger, evidence, **kwargs)


def next_parent(ledger, evidence, *, n=2, now=NOW + timedelta(seconds=2)):
    request = request_for(ledger, n=n, now=now).model_copy(update={"snapshot": evidence.snapshot})
    return reserve(ledger, request, n=n, now=now)


def budget(record):
    amount = record.sizing.parent_risk_budget_usd
    return Fraction(amount.numerator, amount.denominator)


def test_balance_refresh_compounds_next_parent_without_resizing_old_lock():
    held = reserve(seed()).ledger
    old = held.reservations[0].model_dump_json()
    evidence = evidence_for(held)
    updated = refresh(held, evidence)
    assert updated.ledger.reservations[0].model_dump_json() == old
    assert budget(updated.ledger.reservations[0]) == Fraction("12.3")
    next_one = next_parent(updated.ledger, evidence)
    assert budget(next_one.reservation) == Fraction("13.53")
    assert budget(next_one.ledger.reservations[0]) == Fraction("12.3")
    assert updated.capacity_over_limit is False
    assert updated.capital_reservation_authority is updated.execution_authority is False


def test_released_parent_refresh_and_next_campaign_form_one_fixture_chain():
    pending = transition(reserve(seed()).ledger, "MARK_DISPATCHED").ledger
    closed_at = NOW + timedelta(seconds=2)
    closed = transition(
        pending,
        "RELEASE_RECONCILED",
        now=closed_at,
        release_evidence=release_proof(pending, closed_at),
        verify_release=lambda *_: True,
    ).ledger
    now = NOW + timedelta(seconds=3)
    evidence = evidence_for(closed, now=now, balance=1100)
    updated = refresh(closed, evidence, now=now).ledger
    new = next_parent(updated, evidence, now=now)
    assert new.ledger.reservations[0].state == "RELEASED"
    assert budget(new.reservation) == Fraction("13.53")
    assert capacity_used_v31(updated) == 0


def test_floating_profit_does_not_change_next_parent_budget():
    held = reserve(seed()).ledger
    evidence = evidence_for(held, balance=1000, floating=500)
    updated = refresh(held, evidence).ledger
    assert budget(next_parent(updated, evidence).reservation) == budget(held.reservations[0])


def test_balance_loss_updates_truth_and_flags_overcapacity_without_releasing_locks():
    two = reserve(reserve(seed()).ledger, n=2).ledger
    evidence = evidence_for(two, balance=500)
    result = refresh(two, evidence)
    assert result.capacity_over_limit is True
    assert result.ledger.closed_balance_usd == 500
    assert result.ledger.reservations == two.reservations
    assert capacity_used_v31(result.ledger) == capacity_used_v31(two)
    with pytest.raises(CapacityRejectedError, match="RISK_ACCOUNT_CAPACITY_EXCEEDED"):
        next_parent(result.ledger, evidence, n=3)


def test_restart_duplicate_and_old_receipt_after_new_refresh_never_roll_back():
    original = seed()
    first = evidence_for(original)
    updated = refresh(original, first).ledger
    reloaded = CapacityLedgerV31.model_validate_json(updated.model_dump_json())
    assert refresh(reloaded, first, expected_version=0).ledger == updated
    later = NOW + timedelta(seconds=3)
    second = evidence_for(updated, n=2, now=later, balance=1200)
    newest = refresh(updated, second, now=later).ledger
    duplicate = refresh(newest, first, now=later, expected_version=0, verify_refresh=None)
    assert duplicate.status == "DUPLICATE_TEST_ONLY" and duplicate.ledger == newest


@pytest.mark.parametrize(
    "change,reason",
    [
        ("account", "CAPACITY_BASELINE_ACCOUNT_MISMATCH"),
        ("policy", "CAPACITY_BASELINE_POLICY_MISMATCH"),
        ("predecessor", "CAPACITY_BASELINE_PREDECESSOR_MISMATCH"),
        ("coverage", "CAPACITY_BASELINE_COVERAGE_GAP"),
        ("equity", "CAPACITY_BASELINE_EQUITY_MISMATCH"),
        ("balance", "CAPACITY_BASELINE_BALANCE_BRIDGE_MISMATCH"),
        ("partition", "CAPACITY_BASELINE_PARTITION_MISMATCH"),
        ("snapshot_id", "CAPACITY_BASELINE_SNAPSHOT_ID_REUSED"),
        ("verifier", "CAPACITY_BASELINE_VERIFICATION_REJECTED"),
    ],
)
def test_refresh_rejects_inconsistent_or_unbound_evidence_without_state_change(change, reason):
    ledger = reserve(seed()).ledger
    evidence = evidence_for(ledger).model_dump()
    if change == "account":
        evidence["snapshot"]["account_id"] = "different"
    elif change == "policy":
        evidence["policy"]["risk_fraction"] = "0.01"
    elif change == "predecessor":
        evidence["ledger_before_hash"] = H
    elif change == "coverage":
        evidence["coverage_from"] = NOW - timedelta(seconds=1)
    elif change == "equity":
        evidence["snapshot"]["equity"] = 1000
    elif change == "balance":
        evidence["realized_net_pnl_usd"] = "90"
    elif change == "partition":
        evidence["excluded_reservation_ids"] = ()
    elif change == "snapshot_id":
        evidence["snapshot"]["snapshot_id"] = ledger.account_snapshot_id
    before = ledger.model_dump_json()
    kwargs = {"verify_refresh": None} if change == "verifier" else {}
    with pytest.raises(CapacityRejectedError, match=reason):
        refresh(ledger, CapacityBaselineRefreshV31.model_validate(evidence), **kwargs)
    assert ledger.model_dump_json() == before


def test_cashflow_and_adjustment_are_explicit_and_reconcile_exactly():
    ledger = seed()
    evidence = evidence_for(ledger).model_copy(
        update={
            "realized_net_pnl_usd": Decimal("40"),
            "net_cashflow_usd": Decimal("70"),
            "broker_adjustment_usd": Decimal("-10"),
        }
    )
    assert refresh(ledger, evidence).ledger.closed_balance_usd == 1100
    missing = evidence.model_dump()
    del missing["net_cashflow_usd"]
    with pytest.raises(ValidationError):
        CapacityBaselineRefreshV31.model_validate(missing)


@pytest.mark.parametrize("change", ["snapshot", "policy"])
def test_reserve_cannot_change_content_while_reusing_bound_id_or_policy_hash(change):
    ledger = seed()
    request = request_for(ledger)
    if change == "snapshot":
        request = request.model_copy(
            update={"snapshot": request.snapshot.model_copy(update={"balance": 2000, "equity": 2030})}
        )
    else:
        request = request.model_copy(
            update={"policy": request.policy.model_copy(update={"risk_fraction": Decimal("0.01")})}
        )
    with pytest.raises(CapacityRejectedError, match="CAPACITY_SNAPSHOT_OR_POLICY_CONTENT_MISMATCH"):
        reserve(ledger, request)


@pytest.mark.parametrize("which", ["owner_epoch", "expected_version"])
def test_refresh_rejects_stale_owner_or_version(which):
    ledger = seed()
    with pytest.raises(CapacityRejectedError):
        refresh(ledger, **{which: 9})


def test_same_operation_id_with_new_content_is_conflict():
    ledger = seed()
    evidence = evidence_for(ledger)
    updated = refresh(ledger, evidence).ledger
    with pytest.raises(CapacityRejectedError, match="CAPACITY_BASELINE_REPLAY_CONFLICT"):
        refresh(updated, evidence.model_copy(update={"external_risk_usd": exact(1)}))


@pytest.mark.parametrize("now", [NOW + timedelta(seconds=1), NOW + timedelta(seconds=13)])
def test_refresh_rejects_future_or_stale_capture(now):
    with pytest.raises(CapacityRejectedError, match="CAPACITY_BASELINE_STALE_OR_FUTURE"):
        refresh(seed(), evidence_for(seed()), now=now)


def test_verifier_cannot_modify_snapshot_after_receipt_binding():
    def mutate(evidence, digest):
        evidence.snapshot.balance = 9000
        return True

    with pytest.raises(CapacityRejectedError, match="CAPACITY_BASELINE_EVIDENCE_CHANGED"):
        refresh(seed(), verify_refresh=mutate)


def test_disabled_snapshot_is_recorded_and_blocks_new_sizing():
    ledger = seed()
    evidence = evidence_for(ledger)
    evidence = evidence.model_copy(update={"snapshot": evidence.snapshot.model_copy(update={"trade_allowed": False})})
    updated = refresh(ledger, evidence).ledger
    with pytest.raises(CapacityRejectedError, match="RISK_TRADE_DISABLED"):
        next_parent(updated, evidence)
    assert updated.account_snapshot_id == evidence.snapshot.snapshot_id


def test_external_fraction_is_added_once_and_exclusion_order_does_not_change_receipt():
    ledger = reserve(reserve(seed()).ledger, n=2).ledger
    evidence = evidence_for(ledger).model_copy(update={"external_risk_usd": exact(Fraction(1, 3))})
    updated = refresh(ledger, evidence).ledger
    assert capacity_used_v31(updated) == capacity_used_v31(ledger) + Fraction(1, 3)
    reordered = evidence.model_copy(
        update={"excluded_reservation_ids": tuple(reversed(evidence.excluded_reservation_ids))}
    )
    assert baseline_refresh_hash_v31(reordered) == baseline_refresh_hash_v31(evidence)
    assert refresh(updated, reordered).status == "DUPLICATE_TEST_ONLY"


def test_prior_snapshot_id_cannot_be_reused_after_multiple_refreshes():
    original = seed()
    first = refresh(original).ledger
    later = NOW + timedelta(seconds=3)
    second = refresh(first, evidence_for(first, n=2, now=later), now=later).ledger
    now = NOW + timedelta(seconds=4)
    evidence = evidence_for(second, n=3, now=now)
    evidence = evidence.model_copy(
        update={"snapshot": evidence.snapshot.model_copy(update={"snapshot_id": original.account_snapshot_id})}
    )
    with pytest.raises(CapacityRejectedError, match="CAPACITY_BASELINE_SNAPSHOT_ID_REUSED"):
        refresh(second, evidence, now=now)


def test_retired_owner_cannot_acknowledge_old_refresh():
    original = seed()
    evidence = evidence_for(original)
    updated = refresh(original, evidence).ledger.model_copy(update={"owner_epoch": 2})
    with pytest.raises(CapacityRejectedError, match="CAPACITY_OWNER_FENCED"):
        refresh(updated, evidence, owner_epoch=1)


def test_missing_snapshot_content_binding_is_not_accepted_as_legacy_state():
    payload = seed().model_dump()
    del payload["account_snapshot_hash"]
    with pytest.raises(ValidationError):
        CapacityLedgerV31.model_validate(payload)
