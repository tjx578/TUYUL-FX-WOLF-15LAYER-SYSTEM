"""Pure TEST_ONLY capacity transitions with replay, version and epoch checks.

Persistence must compare-and-swap version AND owner epoch while atomically
writing the proposal and the authority/outbox records. These functions do not
provide database isolation, a lease, a final signal or execution permission.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from uuid import UUID

from contracts.strategy_5scr_capacity_v31 import (
    BaselineRefreshReceiptV31,
    CapacityBaselineProposalV31,
    CapacityBaselineRefreshV31,
    CapacityLedgerV31,
    CapacityProposalV31,
    CapacityReleaseEvidenceV31,
    CapacityReservationV31,
)
from contracts.strategy_5scr_risk_adapter_v31 import ExactAmountV31, ParentSizingRequestV31, risk_amount_fraction_v31
from risk.strategy_5scr_risk_adapter_v31 import parent_sizing_request_hash_v31, size_parent_v31


class CapacityRejectedError(ValueError):
    pass


def _hash(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def capacity_ledger_hash_v31(ledger: CapacityLedgerV31) -> str:
    return _hash(ledger.model_dump(mode="json"))


def capacity_content_hash_v31(value) -> str:
    return _hash(value.model_dump(mode="json"))


def capacity_used_v31(ledger: CapacityLedgerV31) -> Fraction:
    return risk_amount_fraction_v31(ledger.baseline_external_risk_usd) + sum(
        (
            risk_amount_fraction_v31(r.sizing.planned_loss_usd)
            for r in ledger.reservations
            if r.state in {"HELD_UNISSUED", "PENDING_RECONCILIATION"}
        ),
        Fraction(0),
    )


def _control(ledger, owner_epoch, now):
    if type(owner_epoch) is not int or owner_epoch != ledger.owner_epoch:
        raise CapacityRejectedError("CAPACITY_OWNER_FENCED")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None or now < ledger.as_of:
        raise CapacityRejectedError("CAPACITY_CLOCK_INVALID")


def _version(ledger, expected_version):
    if type(expected_version) is not int or expected_version != ledger.version:
        raise CapacityRejectedError("CAPACITY_VERSION_CONFLICT")


def _proposal(ledger, record, now, *, duplicate=False):
    if duplicate:
        return CapacityProposalV31(status="DUPLICATE_TEST_ONLY", ledger=ledger, reservation=record)
    records = [r for r in ledger.reservations if r.reservation_id != record.reservation_id] + [record]
    updated = CapacityLedgerV31.model_validate(
        {**ledger.model_dump(), "version": ledger.version + 1, "as_of": now, "reservations": records}
    )
    return CapacityProposalV31(status="APPLIED_TEST_ONLY", ledger=updated, reservation=record)


def reserve_parent_capacity_v31(
    ledger: CapacityLedgerV31,
    request: ParentSizingRequestV31,
    *,
    reservation_id: UUID,
    expires_at: datetime,
    now: datetime,
    owner_epoch: int,
    expected_version: int,
    verify_inputs: Callable[[ParentSizingRequestV31, str], bool] | None,
) -> CapacityProposalV31:
    ledger = CapacityLedgerV31.model_validate(ledger.model_dump())
    request = ParentSizingRequestV31.model_validate(request.model_dump())
    _control(ledger, owner_epoch, now)
    if (
        not isinstance(reservation_id, UUID)
        or not isinstance(expires_at, datetime)
        or expires_at.tzinfo is None
        or expires_at.utcoffset() is None
    ):
        raise CapacityRejectedError("CAPACITY_RESERVATION_ID_OR_CLOCK_INVALID")
    envelope_hash = _hash(
        {
            "request_hash": parent_sizing_request_hash_v31(request),
            "reservation_id": str(reservation_id),
            "expires_at": expires_at.isoformat(),
        }
    )
    existing = next((r for r in ledger.reservations if r.reservation_id == reservation_id), None)
    if existing is not None:
        if existing.envelope_hash != envelope_hash:
            raise CapacityRejectedError("CAPACITY_REPLAY_PAYLOAD_CONFLICT")
        # Acknowledging a committed historical record never resurrects it or
        # grants delivery authority; its terminal/current state is returned.
        return _proposal(ledger, existing, now, duplicate=True)
    _version(ledger, expected_version)
    if any(
        r.campaign_id == request.campaign_id
        or r.thesis_id == request.thesis_id
        or (r.tradeplan_id, r.tradeplan_revision) == (request.tradeplan_id, request.tradeplan_revision)
        for r in ledger.reservations
    ):
        raise CapacityRejectedError("CAPACITY_PARENT_IDENTITY_ALREADY_USED")
    if (ledger.account_id, ledger.executor_id, ledger.account_snapshot_id, ledger.risk_policy_hash) != (
        request.expected_account_id,
        request.expected_executor_id,
        request.snapshot.snapshot_id,
        request.policy.policy_hash,
    ):
        raise CapacityRejectedError("CAPACITY_ACCOUNT_SNAPSHOT_POLICY_MISMATCH")
    if request.risk_state_evidence_hash != capacity_ledger_hash_v31(ledger):
        raise CapacityRejectedError("CAPACITY_STATE_RECEIPT_MISMATCH")
    if (capacity_content_hash_v31(request.snapshot), capacity_content_hash_v31(request.policy)) != (
        ledger.account_snapshot_hash,
        ledger.risk_policy_content_hash,
    ) or Fraction(Decimal(str(request.snapshot.balance))) != Fraction(ledger.closed_balance_usd):
        raise CapacityRejectedError("CAPACITY_SNAPSHOT_OR_POLICY_CONTENT_MISMATCH")
    if request.risk_state_captured_at != ledger.baseline_captured_at:
        raise CapacityRejectedError("CAPACITY_BASELINE_CLOCK_MISMATCH")
    if risk_amount_fraction_v31(request.account_committed_and_reserved_risk_usd) != capacity_used_v31(ledger):
        raise CapacityRejectedError("CAPACITY_TOTAL_MISMATCH")
    if not request.evaluated_at == now or not now < expires_at <= now + timedelta(
        seconds=ledger.reservation_ttl_seconds
    ):
        raise CapacityRejectedError("CAPACITY_RESERVATION_WINDOW_INVALID")
    if request.geometry.costs is not None and expires_at > request.geometry.costs.valid_until:
        raise CapacityRejectedError("CAPACITY_COST_EXPIRY_EXCEEDED")
    sizing = size_parent_v31(request, verify_inputs=verify_inputs)
    if sizing.status != "SIZED_TEST_ONLY":
        raise CapacityRejectedError("CAPACITY_SIZING_REJECTED:" + sizing.reason)
    record = CapacityReservationV31(
        reservation_id=reservation_id,
        envelope_hash=envelope_hash,
        tradeplan_id=request.tradeplan_id,
        tradeplan_revision=request.tradeplan_revision,
        campaign_id=request.campaign_id,
        thesis_id=request.thesis_id,
        sizing=sizing,
        reserved_at=now,
        expires_at=expires_at,
        changed_at=now,
        state="HELD_UNISSUED",
    )
    return _proposal(ledger, record, now)


def transition_capacity_v31(
    ledger: CapacityLedgerV31,
    *,
    reservation_id: UUID,
    action: str,
    now: datetime,
    owner_epoch: int,
    expected_version: int,
    release_evidence: CapacityReleaseEvidenceV31 | None = None,
    verify_release: Callable[[CapacityReleaseEvidenceV31, str], bool] | None = None,
) -> CapacityProposalV31:
    ledger = CapacityLedgerV31.model_validate(ledger.model_dump())
    _control(ledger, owner_epoch, now)
    record = next((r for r in ledger.reservations if r.reservation_id == reservation_id), None)
    if record is None:
        raise CapacityRejectedError("CAPACITY_RESERVATION_MISSING")
    release_hash = None
    if action == "RELEASE_RECONCILED":
        if release_evidence is None:
            raise CapacityRejectedError("CAPACITY_RELEASE_EVIDENCE_UNBOUND")
        release_evidence = CapacityReleaseEvidenceV31.model_validate(release_evidence.model_dump())
        release_hash = _hash(release_evidence.model_dump(mode="json"))
    duplicate = (
        (action == "MARK_DISPATCHED" and record.state == "PENDING_RECONCILIATION")
        or (action == "EXPIRE_UNISSUED" and record.state == "EXPIRED_UNISSUED")
        or (
            action == "RELEASE_RECONCILED"
            and record.state == "RELEASED"
            and release_hash == record.release_evidence_hash
        )
    )
    if duplicate:
        return _proposal(ledger, record, now, duplicate=True)
    _version(ledger, expected_version)
    if record.state in {"RELEASED", "EXPIRED_UNISSUED"}:
        raise CapacityRejectedError("CAPACITY_TERMINAL_RESERVATION")
    if action == "MARK_DISPATCHED":
        if now >= record.expires_at:
            raise CapacityRejectedError("CAPACITY_RESERVATION_EXPIRED")
        state = "PENDING_RECONCILIATION"
    elif action == "EXPIRE_UNISSUED":
        if record.state != "HELD_UNISSUED":
            raise CapacityRejectedError("CAPACITY_BROKER_RECONCILIATION_REQUIRED")
        if now < record.expires_at:
            raise CapacityRejectedError("CAPACITY_RESERVATION_NOT_EXPIRED")
        state = "EXPIRED_UNISSUED"
    elif action == "RELEASE_RECONCILED":
        assert release_evidence is not None
        evidence = release_evidence
        if (
            evidence.account_id,
            evidence.reservation_id,
            evidence.reservation_envelope_hash,
            evidence.ledger_before_hash,
        ) != (ledger.account_id, record.reservation_id, record.envelope_hash, capacity_ledger_hash_v31(ledger)):
            raise CapacityRejectedError("CAPACITY_RELEASE_SCOPE_MISMATCH")
        if evidence.observed_at.tzinfo is None or evidence.observed_at.utcoffset() is None:
            raise CapacityRejectedError("CAPACITY_RELEASE_CLOCK_INVALID")
        if (
            not record.changed_at <= evidence.observed_at <= now
            or (now - evidence.observed_at).total_seconds() > ledger.release_evidence_max_age_seconds
        ):
            raise CapacityRejectedError("CAPACITY_RELEASE_STALE_OR_FUTURE")
        allowed = (
            {("NO_BROKER_EFFECT_CONFIRMED", "NEVER_ISSUED")}
            if record.state == "HELD_UNISSUED"
            else {("NO_BROKER_EFFECT_CONFIRMED", "CANCELLED_FENCED"), ("BROKER_TERMINAL_RECONCILED", "BROKER_TERMINAL")}
        )
        if (evidence.outcome, evidence.delivery_disposition) not in allowed:
            raise CapacityRejectedError("CAPACITY_DELIVERY_NOT_TERMINALLY_BOUND")
        if verify_release is None or verify_release(evidence, release_hash) is not True:
            raise CapacityRejectedError("CAPACITY_RELEASE_VERIFICATION_REJECTED")
        if _hash(evidence.model_dump(mode="json")) != release_hash:
            raise CapacityRejectedError("CAPACITY_RELEASE_EVIDENCE_CHANGED")
        state = "RELEASED"
    else:
        raise CapacityRejectedError("CAPACITY_ACTION_INVALID")
    changed = CapacityReservationV31.model_validate(
        {
            **record.model_dump(),
            "state": state,
            "changed_at": now,
            "release_evidence_hash": release_hash,
        }
    )
    return _proposal(ledger, changed, now)


def baseline_refresh_hash_v31(evidence: CapacityBaselineRefreshV31) -> str:
    payload = evidence.model_dump(mode="json")
    payload["excluded_reservation_ids"] = sorted(payload["excluded_reservation_ids"])
    return _hash(payload)


def refresh_capacity_baseline_v31(
    ledger: CapacityLedgerV31,
    evidence: CapacityBaselineRefreshV31,
    *,
    now: datetime,
    owner_epoch: int,
    expected_version: int,
    verify_refresh: Callable[[CapacityBaselineRefreshV31, str], bool] | None,
) -> CapacityBaselineProposalV31:
    """Propose a new observed baseline while preserving every prior risk lock.

    The verifier must reconcile the complete balance bridge and disjoint risk
    partition against independent receipts. Hashes alone do not attest either.
    """
    ledger = CapacityLedgerV31.model_validate(ledger.model_dump())
    evidence = CapacityBaselineRefreshV31.model_validate(evidence.model_dump())
    _control(ledger, owner_epoch, now)
    digest = baseline_refresh_hash_v31(evidence)

    def result(updated, duplicate=False):
        limit = Fraction(updated.closed_balance_usd) * Fraction(evidence.policy.maximum_account_open_risk_fraction)
        return CapacityBaselineProposalV31(
            status="DUPLICATE_TEST_ONLY" if duplicate else "APPLIED_TEST_ONLY",
            ledger=updated,
            account_capacity_limit_usd=ExactAmountV31(numerator=limit.numerator, denominator=limit.denominator),
            capacity_over_limit=capacity_used_v31(updated) > limit,
        )

    existing = next((r for r in ledger.baseline_refreshes if r.operation_id == evidence.operation_id), None)
    if existing is not None:
        if existing.request_hash != digest:
            raise CapacityRejectedError("CAPACITY_BASELINE_REPLAY_CONFLICT")
        # Policy migration is a separate operation, not implicit baseline refresh.
        if capacity_content_hash_v31(evidence.policy) != ledger.risk_policy_content_hash:
            raise CapacityRejectedError("CAPACITY_BASELINE_POLICY_MISMATCH")
        return result(ledger, duplicate=True)
    _version(ledger, expected_version)
    snapshot, policy = evidence.snapshot, evidence.policy
    if (snapshot.account_id, snapshot.executor_id, snapshot.currency) != (
        ledger.account_id,
        ledger.executor_id,
        policy.account_currency,
    ):
        raise CapacityRejectedError("CAPACITY_BASELINE_ACCOUNT_MISMATCH")
    if (
        policy.policy_hash != ledger.risk_policy_hash
        or capacity_content_hash_v31(policy) != ledger.risk_policy_content_hash
    ):
        raise CapacityRejectedError("CAPACITY_BASELINE_POLICY_MISMATCH")
    if evidence.ledger_before_hash != capacity_ledger_hash_v31(ledger):
        raise CapacityRejectedError("CAPACITY_BASELINE_PREDECESSOR_MISMATCH")
    if evidence.coverage_from != ledger.baseline_captured_at:
        raise CapacityRejectedError("CAPACITY_BASELINE_COVERAGE_GAP")
    age = (now - snapshot.captured_at_utc).total_seconds()
    if not ledger.as_of <= snapshot.captured_at_utc <= now or not 0 <= age <= min(
        policy.snapshot_max_age_seconds, policy.risk_state_max_age_seconds
    ):
        raise CapacityRejectedError("CAPACITY_BASELINE_STALE_OR_FUTURE")
    used_ids = {ledger.account_snapshot_id}
    for receipt in ledger.baseline_refreshes:
        used_ids.update((receipt.previous_snapshot_id, receipt.next_snapshot_id))
    if snapshot.snapshot_id in used_ids:
        raise CapacityRejectedError("CAPACITY_BASELINE_SNAPSHOT_ID_REUSED")
    active = {r.reservation_id for r in ledger.reservations if r.state in {"HELD_UNISSUED", "PENDING_RECONCILIATION"}}
    if set(evidence.excluded_reservation_ids) != active:
        raise CapacityRejectedError("CAPACITY_BASELINE_PARTITION_MISMATCH")
    balance, equity, floating = (Decimal(str(v)) for v in (snapshot.balance, snapshot.equity, snapshot.floating_pnl))
    if any(not v.is_finite() for v in (balance, equity, floating)):
        raise CapacityRejectedError("CAPACITY_BASELINE_NONFINITE")
    if abs(Fraction(equity) - Fraction(balance) - Fraction(floating)) > Fraction(policy.equity_tolerance_usd):
        raise CapacityRejectedError("CAPACITY_BASELINE_EQUITY_MISMATCH")
    expected_balance = Fraction(ledger.closed_balance_usd) + sum(
        (
            Fraction(v)
            for v in (evidence.realized_net_pnl_usd, evidence.net_cashflow_usd, evidence.broker_adjustment_usd)
        ),
        Fraction(0),
    )
    if expected_balance != Fraction(balance):
        raise CapacityRejectedError("CAPACITY_BASELINE_BALANCE_BRIDGE_MISMATCH")
    if verify_refresh is None or verify_refresh(evidence, digest) is not True:
        raise CapacityRejectedError("CAPACITY_BASELINE_VERIFICATION_REJECTED")
    if baseline_refresh_hash_v31(evidence) != digest:
        raise CapacityRejectedError("CAPACITY_BASELINE_EVIDENCE_CHANGED")
    receipt = BaselineRefreshReceiptV31(
        operation_id=evidence.operation_id,
        request_hash=digest,
        previous_snapshot_id=ledger.account_snapshot_id,
        next_snapshot_id=snapshot.snapshot_id,
        applied_version=ledger.version + 1,
        applied_at=now,
    )
    updated = CapacityLedgerV31.model_validate(
        {
            **ledger.model_dump(),
            "version": ledger.version + 1,
            "as_of": now,
            "account_snapshot_id": snapshot.snapshot_id,
            "account_snapshot_hash": capacity_content_hash_v31(snapshot),
            "closed_balance_usd": balance,
            "baseline_captured_at": snapshot.captured_at_utc,
            "baseline_evidence_hash": evidence.source_receipt_hash,
            "baseline_external_risk_usd": evidence.external_risk_usd,
            "baseline_refreshes": (*ledger.baseline_refreshes, receipt),
        }
    )
    return result(updated)
