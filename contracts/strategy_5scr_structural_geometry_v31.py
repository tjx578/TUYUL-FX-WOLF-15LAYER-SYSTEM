"""Canonical StructuralGeometryV31 contract — authority: SSOT v3.1 §17 + amendment A4 (RATIFIED 2026-09-27).

A4 ratified bytes sha256 3afd4339… (blob f84aa607…, 22334 bytes, PR #511 head 2564a581); owner implementation GO
2026-09-27, source/test only. Scope: the two approved geometry policies (A4-G1 BREAK_RETEST, A4-G2
BREAKOUT_ACCEPTANCE) on a FROZEN ExecutionBoxV31 revision.

Strategy geometry only (A4-07): canonical Decimal entry interval, structural SL, TP1 and the exact gross RR. No
broker quote, spread, tick size, cost, net RR, volume, margin or order type exists here; net RR is always
NET_RR_NOT_EVALUATED (A4-03, A4-08). The record grants no risk or execution authority and every policy is
RUNTIME_DISABLED until the evidence each A4 entry requires passes.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from math import gcd
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_execution_box_v31 import canonical_price_text_v31
from contracts.strategy_5scr_identity_v31 import canonical_sha256_v31
from contracts.strategy_5scr_net_geometry_v31 import Price

_DIGEST = r"^sha256:[0-9a-f]{64}$"
_SYMBOL = r"^[A-Z0-9._-]{3,32}$"
_Digest = Annotated[str, Field(pattern=_DIGEST)]

Direction = Literal["BUY", "SELL"]
SpecifiedRoute = Literal["BREAK_RETEST", "BREAKOUT_ACCEPTANCE"]

# A4-13: the closed geometry vocabulary. Nothing else is ever emitted by this step.
GeometryReasonCode = Literal[
    "STRUCTURAL_GEOMETRY_READY",
    "STRUCTURAL_SL_UNAVAILABLE",
    "STRUCTURAL_TARGET_UNAVAILABLE",
    "ROUTE_NO_VALID_ENTRY_DOMAIN",
    "STRUCTURAL_RISK_NON_POSITIVE",
    "STRUCTURAL_REWARD_NON_POSITIVE",
    "STRUCTURAL_GEOMETRY_MATERIAL_CHANGE",
    "EXECUTION_BOX_NOT_FROZEN",
    "GEOMETRY_POLICY_UNKNOWN",
]
GEOMETRY_REASON_CODES_V31: tuple[str, ...] = (
    "STRUCTURAL_GEOMETRY_READY",
    "STRUCTURAL_SL_UNAVAILABLE",
    "STRUCTURAL_TARGET_UNAVAILABLE",
    "ROUTE_NO_VALID_ENTRY_DOMAIN",
    "STRUCTURAL_RISK_NON_POSITIVE",
    "STRUCTURAL_REWARD_NON_POSITIVE",
    "STRUCTURAL_GEOMETRY_MATERIAL_CHANGE",
    "EXECUTION_BOX_NOT_FROZEN",
    "GEOMETRY_POLICY_UNKNOWN",
)
# A4-11 / Q-A4-2: the mandatory cause of ROUTE_NO_VALID_ENTRY_DOMAIN; risk is evaluated first.
NoValidEntryDomainCause = Literal["STRUCTURAL_RISK_NON_POSITIVE", "STRUCTURAL_REWARD_NON_POSITIVE"]
# The status of the decision itself. The two causes and the revision fact are never a status.
GeometryStatus = Literal[
    "STRUCTURAL_GEOMETRY_READY",
    "STRUCTURAL_SL_UNAVAILABLE",
    "STRUCTURAL_TARGET_UNAVAILABLE",
    "ROUTE_NO_VALID_ENTRY_DOMAIN",
    "EXECUTION_BOX_NOT_FROZEN",
    "GEOMETRY_POLICY_UNKNOWN",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class StructuralGeometryPolicyV31(_Strict):
    """One ratified geometry policy (A4-14). Identity is id + version; it fixes the SL anchor, entry-reference,
    TP1 and gross RR rules, and has no buffer, no minimum and no cost input."""

    route: SpecifiedRoute
    geometry_policy_id: str = Field(min_length=3, max_length=120)
    geometry_policy_version: str = Field(min_length=1, max_length=40)
    box_policy_id: str = Field(min_length=3, max_length=120)
    box_policy_version: str = Field(min_length=1, max_length=40)
    sl_anchor_rule: Literal["REFERENCE_CANDLE_LOW_FOR_BUY_HIGH_FOR_SELL"]  # A4-01
    sl_buffer: None = None  # A4-02: no strategy-side buffer
    entry_reference_rule: Literal["BOX_HIGH_FOR_BUY_BOX_LOW_FOR_SELL"]  # A4-05 worst-case strategy entry
    tp1_rule: Literal["SELECTED_TARGET_PRICE_EXACT"]  # A4-09: no offset
    gross_rr_rule: Literal["EXACT_REWARD_OVER_RISK"]  # A4-11
    gross_rr_minimum: None = None  # A4-03
    runtime_status: Literal["RUNTIME_DISABLED"] = "RUNTIME_DISABLED"


def _policy(route: SpecifiedRoute, geometry_policy_id: str, box_policy_id: str) -> StructuralGeometryPolicyV31:
    return StructuralGeometryPolicyV31(
        route=route,
        geometry_policy_id=geometry_policy_id,
        geometry_policy_version="v1",
        box_policy_id=box_policy_id,
        box_policy_version="v1",
        sl_anchor_rule="REFERENCE_CANDLE_LOW_FOR_BUY_HIGH_FOR_SELL",
        entry_reference_rule="BOX_HIGH_FOR_BUY_BOX_LOW_FOR_SELL",
        tp1_rule="SELECTED_TARGET_PRICE_EXACT",
        gross_rr_rule="EXACT_REWARD_OVER_RISK",
    )


# A4-G1 / A4-G2, keyed by (id, version). There is no default policy and no environment selection (A4-14).
GEOMETRY_POLICIES_V31: dict[tuple[str, str], StructuralGeometryPolicyV31] = {
    (p.geometry_policy_id, p.geometry_policy_version): p
    for p in (
        _policy("BREAK_RETEST", "5scr.geometry-policy.break-retest", "5scr.box-policy.break-retest"),
        _policy(
            "BREAKOUT_ACCEPTANCE", "5scr.geometry-policy.breakout-acceptance", "5scr.box-policy.breakout-acceptance"
        ),
    )
}


class GrossRRV31(_Strict):
    """A4-11 serialization: an exact reduced rational. No binary float, no quantum, no rounding mode."""

    numerator: int = Field(gt=0)
    denominator: int = Field(gt=0)

    @model_validator(mode="after")
    def _reduced(self) -> GrossRRV31:
        if gcd(self.numerator, self.denominator) != 1:
            raise ValueError("GROSS_RR_NOT_REDUCED")
        return self

    @classmethod
    def of(cls, value: Fraction) -> GrossRRV31:
        return cls(numerator=value.numerator, denominator=value.denominator)

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


def gross_rr_v31(*, direction: str, rr_reference_entry: Decimal, structural_sl: Decimal, tp1: Decimal) -> Fraction:
    """A4-11 exact formula. Callers must have checked risk > 0 and reward > 0."""

    buy = direction == "BUY"
    risk = Fraction(rr_reference_entry - structural_sl if buy else structural_sl - rr_reference_entry)
    reward = Fraction(tp1 - rr_reference_entry if buy else rr_reference_entry - tp1)
    return reward / risk


class StructuralGeometryMaterialV31(_Strict):
    """A4-10 material projection. gross_rr is derived from it and is not an extra material field."""

    execution_box_id: UUID
    box_version: int = Field(ge=1)
    structural_sl_anchor: Price
    structural_sl: Price
    target_id: str = Field(min_length=1, max_length=200)
    tp1: Price
    rr_reference_entry: Price
    geometry_policy_id: str
    geometry_policy_version: str


def material_geometry_hash_v31(material: StructuralGeometryMaterialV31) -> str:
    """Canonical sha256 of the projection; prices as A3-05 decimal text, so 1.1000 and 1.1 hash identically."""

    return canonical_sha256_v31(
        {
            "execution_box_id": str(material.execution_box_id),
            "box_version": material.box_version,
            "structural_sl_anchor": canonical_price_text_v31(material.structural_sl_anchor),
            "structural_sl": canonical_price_text_v31(material.structural_sl),
            "target_id": material.target_id,
            "tp1": canonical_price_text_v31(material.tp1),
            "rr_reference_entry": canonical_price_text_v31(material.rr_reference_entry),
            "geometry_policy_id": material.geometry_policy_id,
            "geometry_policy_version": material.geometry_policy_version,
        }
    )


class StructuralGeometryLineageV31(_Strict):
    """Provenance only; never hashed into the material projection."""

    material_box_hash: _Digest
    structural_proof_id: UUID
    structural_proof_hash: _Digest
    reference_candle_id: _Digest
    target_evidence_hash: _Digest
    target_selection_decision_price_hash: str


class StructuralGeometryV31(_Strict):
    """One immutable geometry observation for a FROZEN box revision. It has no logical id of its own (A4-10):
    it is identified by its material projection; the entry interval is identified by the box revision (A4-06)."""

    strategy_thesis_id: UUID
    strategy_lifecycle_id: UUID
    canonical_symbol: str = Field(pattern=_SYMBOL)
    direction: Direction
    route: SpecifiedRoute
    entry_interval_low: Price
    entry_interval_high: Price
    material: StructuralGeometryMaterialV31
    material_geometry_hash: _Digest
    gross_rr: GrossRRV31
    net_rr_status: Literal["NET_RR_NOT_EVALUATED"] = "NET_RR_NOT_EVALUATED"
    lineage: StructuralGeometryLineageV31
    runtime_status: Literal["RUNTIME_DISABLED"] = "RUNTIME_DISABLED"
    valid_for_execution: Literal[False] = False
    risk_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _bound(self) -> StructuralGeometryV31:
        m = self.material
        policy = GEOMETRY_POLICIES_V31.get((m.geometry_policy_id, m.geometry_policy_version))
        if policy is None or policy.route != self.route:
            raise ValueError("GEOMETRY_POLICY_UNKNOWN")
        if self.entry_interval_low > self.entry_interval_high:
            raise ValueError("ENTRY_INTERVAL_INVERTED")
        buy = self.direction == "BUY"
        if m.rr_reference_entry != (self.entry_interval_high if buy else self.entry_interval_low):
            raise ValueError("RR_REFERENCE_ENTRY_NOT_THE_WORST_CASE_BOX_EDGE")
        if m.structural_sl != m.structural_sl_anchor:
            raise ValueError("STRUCTURAL_SL_MUST_EQUAL_ITS_ANCHOR")
        risk = m.rr_reference_entry - m.structural_sl if buy else m.structural_sl - m.rr_reference_entry
        reward = m.tp1 - m.rr_reference_entry if buy else m.rr_reference_entry - m.tp1
        if not (risk > 0 and reward > 0):
            raise ValueError("GEOMETRY_REQUIRES_POSITIVE_RISK_AND_REWARD")
        expected = gross_rr_v31(
            direction=self.direction, rr_reference_entry=m.rr_reference_entry, structural_sl=m.structural_sl, tp1=m.tp1
        )
        if self.gross_rr.as_fraction() != expected:
            raise ValueError("GROSS_RR_NOT_EXACT")
        if self.material_geometry_hash != material_geometry_hash_v31(m):
            raise ValueError("MATERIAL_GEOMETRY_HASH_MISMATCH")
        return self


class StructuralGeometryDecisionV31(_Strict):
    status: GeometryStatus
    cause: NoValidEntryDomainCause | None
    geometry: StructuralGeometryV31 | None
    net_rr_status: Literal["NET_RR_NOT_EVALUATED"] = "NET_RR_NOT_EVALUATED"
    risk_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _consistent(self) -> StructuralGeometryDecisionV31:
        # Q-A4-2: the cause is mandatory exactly when the category is ROUTE_NO_VALID_ENTRY_DOMAIN.
        if (self.status == "ROUTE_NO_VALID_ENTRY_DOMAIN") != (self.cause is not None):
            raise ValueError("CAUSE_REQUIRED_IFF_ROUTE_NO_VALID_ENTRY_DOMAIN")
        if (self.status == "STRUCTURAL_GEOMETRY_READY") != (self.geometry is not None):
            raise ValueError("GEOMETRY_PRESENT_IFF_READY")
        return self


__all__ = [
    "GEOMETRY_POLICIES_V31",
    "GEOMETRY_REASON_CODES_V31",
    "GeometryReasonCode",
    "GeometryStatus",
    "GrossRRV31",
    "NoValidEntryDomainCause",
    "StructuralGeometryDecisionV31",
    "StructuralGeometryLineageV31",
    "StructuralGeometryMaterialV31",
    "StructuralGeometryPolicyV31",
    "StructuralGeometryV31",
    "gross_rr_v31",
    "material_geometry_hash_v31",
]
