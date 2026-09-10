"""Explicit TEST_ONLY parent sizing boundary; no reservation or command schema."""

from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from contracts.mt5_execution_protocol import AccountSnapshotV1
from contracts.strategy_5scr_net_geometry_v31 import GeometryContract, NetGeometryRequestV31, Price

Amount = Annotated[Decimal, Field(ge=0, max_digits=28, decimal_places=12, allow_inf_nan=False)]
Percent = Annotated[Decimal, Field(gt=0, le=1, max_digits=28, decimal_places=12, allow_inf_nan=False)]


class ParentSizingPolicyV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    policy_id: str = Field(min_length=3, max_length=100)
    policy_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    account_currency: Literal["USD"]
    risk_fraction: Percent
    maximum_account_open_risk_fraction: Percent
    snapshot_max_age_seconds: int = Field(gt=0, strict=True)
    risk_state_max_age_seconds: int = Field(gt=0, strict=True)
    equity_tolerance_usd: Amount
    volume_limit_behavior: Literal["REJECT_ABOVE_MAX"]

    @model_validator(mode="after")
    def cap(self):
        if self.maximum_account_open_risk_fraction < self.risk_fraction:
            raise ValueError("account cap is below parent risk fraction")
        return self


class ExactAmountV31(GeometryContract):
    numerator: int = Field(ge=0, strict=True)
    denominator: int = Field(gt=0, strict=True)


def risk_amount_fraction_v31(value: Decimal | ExactAmountV31) -> Fraction:
    if isinstance(value, ExactAmountV31):
        return Fraction(value.numerator, value.denominator)
    return Fraction(value)


class ParentSizingRequestV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    entry_role: Literal["PARENT"]
    # Semantic IDs are supplied by the strategy owner, not derived from payload
    # hashes, transport events or timestamps by this adapter.
    tradeplan_id: str = Field(min_length=3, max_length=200)
    tradeplan_revision: int = Field(ge=1, strict=True)
    strategy_candidate_receipt_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    thesis_id: str = Field(min_length=3, max_length=200)
    campaign_id: str = Field(min_length=3, max_length=200)
    expected_account_id: str = Field(min_length=1, max_length=100)
    expected_executor_id: UUID
    broker_symbol: str = Field(min_length=1, max_length=64)
    tick_value_currency: Literal["USD"]
    tick_value_model_id: Literal["ACCOUNT_CURRENCY_PER_LOT_TEST_V1"]
    evaluated_at: datetime
    snapshot: AccountSnapshotV1
    geometry: NetGeometryRequestV31
    policy: ParentSizingPolicyV31
    # Held reservations and broker exposure must both be included by the
    # independent risk-state provider. Zero is explicit, never inferred.
    account_committed_and_reserved_risk_usd: Amount | ExactAmountV31
    campaign_committed_and_reserved_risk_usd: Amount | ExactAmountV31
    risk_state_evidence_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    risk_state_captured_at: datetime

    @model_validator(mode="after")
    def clock(self):
        if any(t.tzinfo is None or t.utcoffset() is None for t in (self.evaluated_at, self.risk_state_captured_at)):
            raise ValueError("evaluation clock must be timezone-aware")
        return self


class ParentSizingResultV31(GeometryContract):
    profile: Literal["TEST_ONLY"] = "TEST_ONLY"
    status: Literal["SIZED_TEST_ONLY", "WAIT", "REJECTED"]
    reason: str
    request_hash: str
    geometry_request_hash: str | None = None
    candidate_entry: Price | None = None
    volume: ExactAmountV31 | None = None
    parent_risk_budget_usd: ExactAmountV31 | None = None
    planned_loss_usd: ExactAmountV31 | None = None
    net_reward_usd: ExactAmountV31 | None = None
    capital_reservation_authority: Literal[False] = False
    execution_authority: Literal[False] = False
