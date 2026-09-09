"""TEST_ONLY versioned capacity proposals; persistence owns the actual commit."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from contracts.strategy_5scr_net_geometry_v31 import GeometryContract
from contracts.strategy_5scr_risk_adapter_v31 import ExactAmountV31, ParentSizingResultV31


class CapacityReservationV31(GeometryContract):
    reservation_id: UUID
    envelope_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    tradeplan_id: str
    tradeplan_revision: int = Field(ge=1, strict=True)
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


class CapacityLedgerV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    parent_slot_policy: Literal["ONE_PARENT_PER_THESIS_TEST_V1"]
    account_id: str = Field(min_length=1, max_length=100)
    executor_id: UUID
    account_snapshot_id: str
    risk_policy_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
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
