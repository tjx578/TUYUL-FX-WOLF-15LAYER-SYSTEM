"""Explicit TEST_ONLY inputs for the SSOT v3.1 net-RR interval kernel.

Price-equivalent costs are supplied by a caller, never inferred from an account
or converted from money here. This contract is not an active policy registry or
a TradePlan authorization. Profit and loss scenarios each carry total costs.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Price = Annotated[Decimal, Field(gt=0, max_digits=28, decimal_places=12, allow_inf_nan=False)]
Cost = Annotated[Decimal, Field(ge=0, max_digits=28, decimal_places=12, allow_inf_nan=False)]


class GeometryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EntryIntervalV31(GeometryContract):
    low: Price
    high: Price

    @model_validator(mode="after")
    def ordered(self) -> EntryIntervalV31:
        if self.high < self.low:
            raise ValueError("entry interval is reversed")
        return self


class ScenarioCostV31(GeometryContract):
    # Each field is mandatory, including explicit zero for non-applicable costs.
    spread_price: Cost
    commission_price: Cost
    slippage_price: Cost
    swap_price: Cost


class NetCostSnapshotV31(GeometryContract):
    symbol: str = Field(min_length=3, max_length=32)
    source_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    cost_model_id: Literal["EXPLICIT_SCENARIO_PRICE_COSTS_TEST_V1"]
    captured_at: datetime
    valid_until: datetime
    profit: ScenarioCostV31
    loss: ScenarioCostV31

    @model_validator(mode="after")
    def validity(self) -> NetCostSnapshotV31:
        if any(t.tzinfo is None or t.utcoffset() is None for t in (self.captured_at, self.valid_until)):
            raise ValueError("cost clocks must be timezone-aware")
        if self.valid_until <= self.captured_at:
            raise ValueError("cost expiry must follow capture")
        return self


class NetGeometryPolicyV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    policy_id: str = Field(min_length=3, max_length=100)
    policy_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    instrument_class: Literal["FX", "METAL", "OTHER"]
    minimum_target_units: Price
    minimum_net_rr: Annotated[Decimal, Field(ge=Decimal("1.5"), max_digits=28, decimal_places=12)]


class NetGeometryContextV31(GeometryContract):
    symbol: str = Field(min_length=3, max_length=32)
    instrument_class: Literal["FX", "METAL", "OTHER"]
    direction: Literal["BUY", "SELL"]
    decision_at: datetime
    stop_price: Price
    stop_evidence_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    digits: int = Field(ge=0, le=12, strict=True)
    point: Price
    tick_size: Price
    target_unit_size: Price
    structural_interval: EntryIntervalV31
    route_interval: EntryIntervalV31
    broker_interval: EntryIntervalV31
    policy: NetGeometryPolicyV31 | None
    costs: NetCostSnapshotV31 | None


class NetGeometryRequestV31(NetGeometryContextV31):
    # Already-selected nearest target and structural SL; the kernel cannot
    # search for a farther target or tighten a stop to improve RR.
    target_price: Price
    target_evidence_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def geometry(self) -> NetGeometryRequestV31:
        if self.decision_at.tzinfo is None or self.decision_at.utcoffset() is None:
            raise ValueError("decision clock must be timezone-aware")
        if self.point != Decimal(1).scaleb(-self.digits):
            raise ValueError("digits and point disagree")
        if any(
            (Fraction(value) / Fraction(self.point)).denominator != 1
            for value in (self.tick_size, self.target_unit_size)
        ):
            raise ValueError("tick and target unit must be integral point multiples")
        if any((Fraction(p) / Fraction(self.tick_size)).denominator != 1 for p in (self.target_price, self.stop_price)):
            raise ValueError("fixed target and stop must be on the broker tick grid")
        return self


class NetGeometryResultV31(GeometryContract):
    profile: Literal["TEST_ONLY"] = "TEST_ONLY"
    status: Literal["FEASIBLE_TEST_ONLY", "WAIT", "NO_VALID_ENTRY_DOMAIN"]
    reason: str
    request_hash: str
    feasible_interval: EntryIntervalV31 | None = None
    candidate_entry: Decimal | None = None
    net_rr: Decimal | None = None
    hypothesis_authority: Literal[False] = False
    capital_reservation_authority: Literal[False] = False
    execution_authority: Literal[False] = False
