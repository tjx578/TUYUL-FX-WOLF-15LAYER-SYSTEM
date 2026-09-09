"""TEST_ONLY target universe interface; target derivation/attestation is external."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from contracts.strategy_5scr_net_geometry_v31 import GeometryContract, NetGeometryResultV31, Price

TargetSource = Literal["SWING", "D1_SR", "H4_SR", "H1_SR", "RANGE", "BREAKOUT", "LIQUIDITY", "FIBONACCI"]


class StructuralTargetV31(GeometryContract):
    target_id: str = Field(min_length=1, max_length=200)
    source: TargetSource
    price: Price
    evidence_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    formed_at: datetime
    valid_until: datetime
    consumed_at: datetime | None

    @model_validator(mode="after")
    def clocks(self) -> "StructuralTargetV31":
        values = (self.formed_at, self.valid_until, self.consumed_at)
        if any(t is not None and (t.tzinfo is None or t.utcoffset() is None) for t in values):
            raise ValueError("target clocks must be timezone-aware")
        if self.valid_until <= self.formed_at or (self.consumed_at is not None and self.consumed_at < self.formed_at):
            raise ValueError("target clock ordering is invalid")
        return self


class TargetUniverseV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    symbol: str = Field(min_length=3, max_length=32)
    direction: Literal["BUY", "SELL"]
    decision_at: datetime
    anchor_price: Price
    anchor_evidence_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    policy_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    # Source completeness requires an external verifier over the entire snapshot.
    # A source with zero targets must still appear in covered_sources.
    required_sources: tuple[TargetSource, ...] = Field(min_length=1, max_length=8)
    covered_sources: tuple[TargetSource, ...] = Field(max_length=8)
    targets: tuple[StructuralTargetV31, ...] = Field(max_length=10000)

    @model_validator(mode="after")
    def identities(self) -> "TargetUniverseV31":
        if self.decision_at.tzinfo is None or self.decision_at.utcoffset() is None:
            raise ValueError("universe decision clock must be timezone-aware")
        for values in (self.required_sources, self.covered_sources, tuple(t.target_id for t in self.targets)):
            if len(values) != len(set(values)):
                raise ValueError("duplicate source or target identity")
        return self


class TargetGeometryResultV31(GeometryContract):
    profile: Literal["TEST_ONLY"] = "TEST_ONLY"
    universe_hash: str
    reason: str
    selected_target_id: str | None = None
    geometry: NetGeometryResultV31 | None = None
    hypothesis_authority: Literal[False] = False
    capital_reservation_authority: Literal[False] = False
    execution_authority: Literal[False] = False
