"""Canonical ExecutionBoxV31 contract — authority: SSOT v3.1 §16 + amendment A3 (RATIFIED 2026-09-22).

A3 ratified bytes sha256 76f9cad5… (blob 176cd419…); approved successor 538b3b6f…. Owner implementation GO
2026-09-22. Scope: the two SPEC_DEFINED routes only (A3-R1 BREAK_RETEST, A3-R2 BREAKOUT_ACCEPTANCE); the four
NOT_YET_DEFINED routes produce no canonical box; FAILED_RECLAIM stays unmapped.

First-increment FSM (A3-10): BUILDING → FROZEN; BUILDING | FROZEN → SUPERSEDED | INVALIDATED. CONSUMED and EXPIRED
are deliberately absent from the state vocabulary (no producer / reserved unreachable), and the box has no clock.

The box is class-free (containment travels beside it), grants no risk or execution authority, and every route is
RUNTIME_DISABLED until replay + shadow + OOS evidence passes (A3-04).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_identity_v31 import canonical_sha256_v31, identity_uuid_v31
from contracts.strategy_5scr_net_geometry_v31 import Price

V31_EXECUTION_BOX_NAMESPACE = UUID("7d75d925-b1c5-4270-8cfc-80bc6db6c64e")
EXECUTION_BOX_IDENTITY_DERIVATION_VERSION = "5scr.execution-box-identity.v31.v1"

_DIGEST = r"^sha256:[0-9a-f]{64}$"
_SYMBOL = r"^[A-Z0-9._-]{3,32}$"
_Digest = Annotated[str, Field(pattern=_DIGEST)]

Direction = Literal["BUY", "SELL"]
# A3-04: the closed six-route vocabulary. Anything else is an unknown route and is rejected.
CanonicalRoute = Literal[
    "BREAK_RETEST",
    "BREAKOUT_ACCEPTANCE",
    "PULLBACK_CONTINUATION",
    "FAILED_BREAKOUT_SELL",
    "FAILED_BREAKDOWN_BUY",
    "RANGE_FADE",
]
CANONICAL_ROUTES_V31: tuple[str, ...] = (
    "BREAK_RETEST",
    "BREAKOUT_ACCEPTANCE",
    "PULLBACK_CONTINUATION",
    "FAILED_BREAKOUT_SELL",
    "FAILED_BREAKDOWN_BUY",
    "RANGE_FADE",
)
SpecifiedRoute = Literal["BREAK_RETEST", "BREAKOUT_ACCEPTANCE"]
# A3-10 first increment. CONSUMED / EXPIRED are not members on purpose.
ExecutionBoxState = Literal["BUILDING", "FROZEN", "SUPERSEDED", "INVALIDATED"]
TERMINAL_BOX_STATES_V31 = frozenset({"SUPERSEDED", "INVALIDATED"})
ALLOWED_BOX_TRANSITIONS_V31: dict[str | None, frozenset[str]] = {
    None: frozenset({"BUILDING"}),
    "BUILDING": frozenset({"FROZEN", "SUPERSEDED", "INVALIDATED"}),
    "FROZEN": frozenset({"SUPERSEDED", "INVALIDATED"}),
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ExecutionBoxPolicyV31(_Strict):
    """One ratified route policy (A3-03 contract, A3-R1 / A3-R2 content). Identity is id + version, not a hash."""

    route: SpecifiedRoute
    box_policy_id: str = Field(min_length=3, max_length=120)
    box_policy_version: str = Field(min_length=1, max_length=40)
    proof_class: Literal["CONTINUATION"]
    completion_kind: Literal["RETEST", "ACCEPTANCE"]
    closed_candle_authority: Literal["M15"]
    freeze_reason: Literal["M15_RETEST_COMPLETION_CLOSED", "M15_ACCEPTANCE_COMPLETION_CLOSED"]
    runtime_status: Literal["RUNTIME_DISABLED"] = "RUNTIME_DISABLED"


# The ratified A3 route policies. Four routes have no entry: NOT_YET_DEFINED → no canonical box (A3-03).
BOX_POLICIES_V31: dict[str, ExecutionBoxPolicyV31] = {
    "BREAK_RETEST": ExecutionBoxPolicyV31(
        route="BREAK_RETEST",
        box_policy_id="5scr.box-policy.break-retest",
        box_policy_version="v1",
        proof_class="CONTINUATION",
        completion_kind="RETEST",
        closed_candle_authority="M15",
        freeze_reason="M15_RETEST_COMPLETION_CLOSED",
    ),
    "BREAKOUT_ACCEPTANCE": ExecutionBoxPolicyV31(
        route="BREAKOUT_ACCEPTANCE",
        box_policy_id="5scr.box-policy.breakout-acceptance",
        box_policy_version="v1",
        proof_class="CONTINUATION",
        completion_kind="ACCEPTANCE",
        closed_candle_authority="M15",
        freeze_reason="M15_ACCEPTANCE_COMPLETION_CLOSED",
    ),
}


def execution_box_id_v31(*, strategy_thesis_id: UUID, route: str, box_policy_id: str, box_policy_version: str) -> UUID:
    """A3-08 logical identity. Nothing else enters: no PressureRange, target, proof revision, evidence, clock,
    admission class, deployment or request. A route or policy change therefore yields a new id."""

    return identity_uuid_v31(
        V31_EXECUTION_BOX_NAMESPACE,
        [EXECUTION_BOX_IDENTITY_DERIVATION_VERSION, str(strategy_thesis_id), route, box_policy_id, box_policy_version],
    )


def canonical_price_text_v31(value: Decimal) -> str:
    """A3-05 hashing form: fixed-point, no exponent, no trailing zeros, so 1.1000 and 1.1 hash identically."""

    text = format(value.normalize(), "f")
    return text


class ExecutionBoxMaterialV31(_Strict):
    """A3-09 material projection: GEOMETRY + AUTHORITY only. Lineage is never part of it."""

    box_low: Price
    box_high: Price
    structural_proof_id: UUID
    context_epoch_id: UUID
    freeze_evidence_id: _Digest

    @model_validator(mode="after")
    def _ordered(self) -> ExecutionBoxMaterialV31:
        if self.box_low > self.box_high:
            raise ValueError("EXECUTION_BOX_BOUNDS_INVERTED")
        return self


def material_box_hash_v31(material: ExecutionBoxMaterialV31) -> str:
    return canonical_sha256_v31(
        {
            "box_low": canonical_price_text_v31(material.box_low),
            "box_high": canonical_price_text_v31(material.box_high),
            "structural_proof_id": str(material.structural_proof_id),
            "context_epoch_id": str(material.context_epoch_id),
            "freeze_evidence_id": material.freeze_evidence_id,
        }
    )


class ExecutionBoxLineageV31(_Strict):
    """Provenance and revision drivers (A3-09 LINEAGE). Never hashed into the material projection."""

    pressure_range_id: UUID
    target_id: str
    structural_proof_hash: _Digest
    context_route_evaluation_id: UUID
    freeze_evidence_close_utc: datetime


class ExecutionBoxVersionV31(_Strict):
    """One immutable, append-only box revision: (execution_box_id, box_version). State lives in transitions."""

    derivation_version: Literal["5scr.execution-box-identity.v31.v1"] = EXECUTION_BOX_IDENTITY_DERIVATION_VERSION
    execution_box_id: UUID
    box_version: int = Field(ge=1)
    strategy_thesis_id: UUID
    strategy_lifecycle_id: UUID
    canonical_symbol: str = Field(pattern=_SYMBOL)
    direction: Direction
    route: SpecifiedRoute
    box_policy_id: str
    box_policy_version: str
    material: ExecutionBoxMaterialV31
    material_box_hash: _Digest
    previous_box_version: int | None
    previous_material_box_hash: _Digest | None
    lineage: ExecutionBoxLineageV31
    runtime_status: Literal["RUNTIME_DISABLED"] = "RUNTIME_DISABLED"
    valid_for_execution: Literal[False] = False
    risk_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _bound(self) -> ExecutionBoxVersionV31:
        policy = BOX_POLICIES_V31[self.route]
        if (self.box_policy_id, self.box_policy_version) != (policy.box_policy_id, policy.box_policy_version):
            raise ValueError("EXECUTION_BOX_POLICY_NOT_RATIFIED_FOR_ROUTE")
        expected = execution_box_id_v31(
            strategy_thesis_id=self.strategy_thesis_id,
            route=self.route,
            box_policy_id=self.box_policy_id,
            box_policy_version=self.box_policy_version,
        )
        if self.execution_box_id != expected:
            raise ValueError("EXECUTION_BOX_ID_NOT_DERIVED")
        if self.material_box_hash != material_box_hash_v31(self.material):
            raise ValueError("MATERIAL_BOX_HASH_MISMATCH")
        # A3-08 version lock: 1 has no predecessor; n > 1 names exactly n − 1 and its material hash.
        if self.box_version == 1:
            if self.previous_box_version is not None or self.previous_material_box_hash is not None:
                raise ValueError("FIRST_BOX_VERSION_HAS_NO_PREDECESSOR")
        elif self.previous_box_version != self.box_version - 1 or self.previous_material_box_hash is None:
            raise ValueError("BOX_VERSION_MUST_FOLLOW_ITS_PREDECESSOR_BY_EXACTLY_ONE")
        if self.previous_material_box_hash == self.material_box_hash:
            raise ValueError("A_NEW_BOX_VERSION_REQUIRES_A_MATERIAL_CHANGE")
        return self


class ExecutionBoxTransitionV31(_Strict):
    """Ordered state change. BUILDING and FROZEN may share one authority time; the ordinal orders them (Q-R1)."""

    execution_box_id: UUID
    box_version: int = Field(ge=1)
    ordinal: int = Field(ge=0)
    from_state: ExecutionBoxState | None
    to_state: ExecutionBoxState
    reason_code: str = Field(min_length=3, max_length=120)
    authority_time: datetime
    evidence_id: _Digest | None

    @model_validator(mode="after")
    def _legal(self) -> ExecutionBoxTransitionV31:
        if self.to_state not in ALLOWED_BOX_TRANSITIONS_V31.get(self.from_state, frozenset()):
            raise ValueError("EXECUTION_BOX_TRANSITION_NOT_ALLOWED")
        return self


class ExecutionBoxDecisionV31(_Strict):
    outcome: Literal["NO_CANONICAL_BOX", "BOX_BUILT_AND_FROZEN", "NO_MATERIAL_CHANGE", "NEW_BOX_VERSION"]
    reason_code: str
    version: ExecutionBoxVersionV31 | None
    transitions: tuple[ExecutionBoxTransitionV31, ...]
    risk_authority: Literal[False] = False
    execution_authority: Literal[False] = False


__all__ = [
    "ALLOWED_BOX_TRANSITIONS_V31",
    "BOX_POLICIES_V31",
    "CANONICAL_ROUTES_V31",
    "EXECUTION_BOX_IDENTITY_DERIVATION_VERSION",
    "TERMINAL_BOX_STATES_V31",
    "V31_EXECUTION_BOX_NAMESPACE",
    "CanonicalRoute",
    "ExecutionBoxDecisionV31",
    "ExecutionBoxLineageV31",
    "ExecutionBoxMaterialV31",
    "ExecutionBoxPolicyV31",
    "ExecutionBoxState",
    "ExecutionBoxTransitionV31",
    "ExecutionBoxVersionV31",
    "canonical_price_text_v31",
    "execution_box_id_v31",
    "material_box_hash_v31",
]
