"""TEST_ONLY versioned capacity proposals; persistence owns the actual commit."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from contracts.mt5_execution_protocol import AccountSnapshotV1
from contracts.strategy_5scr_net_geometry_v31 import GeometryContract, Price
from contracts.strategy_5scr_risk_adapter_v31 import ExactAmountV31, ParentSizingPolicyV31, ParentSizingResultV31

SignedAmount = Annotated[Decimal, Field(max_digits=28, decimal_places=12, allow_inf_nan=False)]


class CapacityReservationV31(GeometryContract):
    reservation_id: UUID
    envelope_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    tradeplan_id: str
    tradeplan_revision: int = Field(ge=1, strict=True)
    strategy_candidate_receipt_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    campaign_id: str
    thesis_id: str
    sizing: ParentSizingResultV31
    reserved_at: datetime
    expires_at: datetime
    changed_at: datetime
    state: Literal["HELD_UNISSUED", "PENDING_RECONCILIATION", "EXPIRED_UNISSUED", "RELEASED"]
    release_evidence_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def coherent(self):
        times = (self.reserved_at, self.expires_at, self.changed_at)
        if any(t.tzinfo is None or t.utcoffset() is None for t in times):
            raise ValueError("reservation clocks must be aware")
        if not self.reserved_at < self.expires_at or self.changed_at < self.reserved_at:
            raise ValueError("reservation clocks are unordered")
        if self.sizing.status != "SIZED_TEST_ONLY" or self.sizing.planned_loss_usd is None:
            raise ValueError("capacity record requires successful sizing")
        if self.sizing.planned_loss_usd.numerator <= 0:
            raise ValueError("capacity amount must be positive")
        if self.state == "HELD_UNISSUED" and self.changed_at != self.reserved_at:
            raise ValueError("unissued record must retain its reservation clock")
        if self.state == "PENDING_RECONCILIATION" and self.changed_at >= self.expires_at:
            raise ValueError("dispatch must precede reservation expiry")
        if (self.state == "RELEASED") != (self.release_evidence_hash is not None):
            raise ValueError("release requires reconciliation evidence identity")
        if self.state == "EXPIRED_UNISSUED" and self.changed_at < self.expires_at:
            raise ValueError("unissued reservation cannot expire early")
        return self


class BaselineRefreshReceiptV31(GeometryContract):
    operation_id: UUID
    request_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    previous_snapshot_id: str
    next_snapshot_id: str
    applied_version: int = Field(ge=1, strict=True)
    applied_at: datetime


class CapacityLedgerV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    parent_slot_policy: Literal["ONE_PARENT_PER_THESIS_TEST_V1"]
    account_id: str = Field(min_length=1, max_length=100)
    executor_id: UUID
    account_snapshot_id: str
    account_snapshot_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    closed_balance_usd: Price
    risk_policy_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    risk_policy_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    owner_epoch: int = Field(ge=1, strict=True)
    version: int = Field(ge=0, strict=True)
    as_of: datetime
    baseline_captured_at: datetime
    baseline_evidence_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    # Verified exposure OUTSIDE records in this ledger. The source must exclude
    # these reservations/positions even after dispatch, preventing double count.
    baseline_external_risk_usd: ExactAmountV31
    reservation_ttl_seconds: int = Field(gt=0, strict=True)
    release_evidence_max_age_seconds: int = Field(gt=0, strict=True)
    reservations: tuple[CapacityReservationV31, ...] = Field(max_length=10000)
    baseline_refreshes: tuple[BaselineRefreshReceiptV31, ...] = Field(default=(), max_length=10000)

    @model_validator(mode="after")
    def coherent(self):
        if any(t.tzinfo is None or t.utcoffset() is None for t in (self.as_of, self.baseline_captured_at)):
            raise ValueError("ledger clocks must be aware")
        if self.baseline_captured_at > self.as_of or any(r.changed_at > self.as_of for r in self.reservations):
            raise ValueError("ledger clock precedes evidence")
        for values in (
            [r.reservation_id for r in self.reservations],
            [(r.tradeplan_id, r.tradeplan_revision) for r in self.reservations],
            [r.campaign_id for r in self.reservations],
            [r.thesis_id for r in self.reservations],
        ):
            if len(values) != len(set(values)):
                raise ValueError("duplicate parent identity or tombstone")
        if len({r.operation_id for r in self.baseline_refreshes}) != len(self.baseline_refreshes):
            raise ValueError("duplicate baseline operation")
        versions = [r.applied_version for r in self.baseline_refreshes]
        if versions != sorted(set(versions)) or any(v > self.version for v in versions):
            raise ValueError("baseline receipt versions are invalid")
        if any(
            r.applied_at.tzinfo is None or r.applied_at.utcoffset() is None or r.applied_at > self.as_of
            for r in self.baseline_refreshes
        ):
            raise ValueError("baseline receipt clock is invalid")
        return self


class CapacityReleaseEvidenceV31(GeometryContract):
    account_id: str
    reservation_id: UUID
    reservation_envelope_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    ledger_before_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_receipt_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    delivery_terminal_receipt_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    delivery_disposition: Literal["NEVER_ISSUED", "CANCELLED_FENCED", "BROKER_TERMINAL"]
    observed_at: datetime
    outcome: Literal["NO_BROKER_EFFECT_CONFIRMED", "BROKER_TERMINAL_RECONCILED"]


class CapacityProposalV31(GeometryContract):
    status: Literal["APPLIED_TEST_ONLY", "DUPLICATE_TEST_ONLY"]
    ledger: CapacityLedgerV31
    reservation: CapacityReservationV31
    capital_reservation_authority: Literal[False] = False
    execution_authority: Literal[False] = False


class CapacityBaselineRefreshV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    operation_id: UUID
    ledger_before_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_receipt_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    snapshot: AccountSnapshotV1
    policy: ParentSizingPolicyV31
    coverage_from: datetime
    coverage_to: datetime
    realized_net_pnl_usd: SignedAmount
    net_cashflow_usd: SignedAmount
    broker_adjustment_usd: SignedAmount
    external_risk_usd: ExactAmountV31
    excluded_reservation_ids: tuple[UUID, ...] = Field(max_length=10000)

    @model_validator(mode="after")
    def coverage(self):
        if any(t.tzinfo is None or t.utcoffset() is None for t in (self.coverage_from, self.coverage_to)):
            raise ValueError("balance bridge clocks must be aware")
        if not self.coverage_from < self.coverage_to or self.coverage_to != self.snapshot.captured_at_utc:
            raise ValueError("balance bridge must end at the new snapshot")
        if len(self.excluded_reservation_ids) != len(set(self.excluded_reservation_ids)):
            raise ValueError("duplicate excluded reservation")
        return self


class CapacityBaselineProposalV31(GeometryContract):
    status: Literal["APPLIED_TEST_ONLY", "DUPLICATE_TEST_ONLY"]
    ledger: CapacityLedgerV31
    account_capacity_limit_usd: ExactAmountV31
    capacity_over_limit: bool
    capital_reservation_authority: Literal[False] = False
    execution_authority: Literal[False] = False
