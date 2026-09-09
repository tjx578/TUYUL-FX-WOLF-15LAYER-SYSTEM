"""TEST_ONLY material context and route receipt, not a policy or source attestor."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from contracts.strategy_5scr_net_geometry_v31 import GeometryContract

Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Label = Annotated[str, Field(min_length=1, max_length=160, pattern=r"^\S(?:.*\S)?$")]
Direction = Literal["BUY", "SELL"]


def content_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class MaterialContextV31(GeometryContract):
    d1_source_ids: tuple[Digest, ...] = Field(min_length=1, max_length=1000)
    h4_source_ids: tuple[Digest, ...] = Field(min_length=1, max_length=1000)
    d1_structure: Label
    h4_structure: Label
    price_location: Label
    liquidity_state: Label
    primary_direction_domain: Literal["BUY_ONLY", "SELL_ONLY", "BOTH_CONDITIONAL", "UNRESOLVED", "EMPTY"]
    allowed_directions: tuple[Direction, ...] = Field(max_length=2)
    counter_pressure_policy_hash: Digest
    counter_pressure_observation_allowed: bool = Field(strict=True)
    counter_pressure_thesis_status: Literal["PROHIBITED", "PROOF_REQUIRED", "AUTHORIZED"]
    allowed_routes: tuple[Label, ...] = Field(max_length=100)
    blocked_routes: tuple[Label, ...] = Field(max_length=100)
    target_map_version: Label
    structural_invalidation_version: Label
    pressure_contract_status: Literal["OPEN", "LOCKED", "TRANSITION_PENDING", "INVALIDATED", "EXPIRED"]

    @model_validator(mode="after")
    def coherent(self):
        for values in (
            self.d1_source_ids,
            self.h4_source_ids,
            self.allowed_directions,
            self.allowed_routes,
            self.blocked_routes,
        ):
            if values != tuple(sorted(set(values))):
                raise ValueError("CONTEXT_IDENTITIES_MUST_BE_SORTED_UNIQUE")
        if set(self.d1_source_ids) & set(self.h4_source_ids):
            raise ValueError("CONTEXT_SOURCE_TIMEFRAME_ID_CONFLICT")
        if set(self.allowed_routes) & set(self.blocked_routes):
            raise ValueError("CONTEXT_ROUTE_CONFLICT")
        domain = {
            "BUY_ONLY": {"BUY"},
            "SELL_ONLY": {"SELL"},
            "BOTH_CONDITIONAL": {"BUY", "SELL"},
            "UNRESOLVED": set(),
            "EMPTY": set(),
        }[self.primary_direction_domain]
        if not set(self.allowed_directions) <= domain:
            raise ValueError("CONTEXT_DIRECTION_DOMAIN_CONFLICT")
        return self


class ContextRouteReceiptV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    context_epoch_id: UUID
    strategy_lifecycle_id: UUID
    symbol: str = Field(pattern=r"^[A-Z0-9._-]{3,32}$")
    state: Literal["ACTIVE", "SUPERSEDED", "INVALIDATED", "EXPIRED"]
    material: MaterialContextV31
    material_context_hash: Digest
    registry_version: Label
    location_route_policy_hash: Digest
    location_alignment: Literal["FAVORABLE", "NEUTRAL", "UNFAVORABLE", "UNKNOWN"]
    selected_route: Label
    direction: Direction
    resolution_evidence_hash: Digest
    source_closed_through: datetime
    evaluated_at: datetime
    valid_until: datetime

    @field_validator("source_closed_through", "evaluated_at", "valid_until")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CONTEXT_CLOCK_MUST_BE_AWARE")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent(self):
        if self.material_context_hash != material_context_hash_v31(self.symbol, self.material):
            raise ValueError("CONTEXT_MATERIAL_HASH_MISMATCH")
        if not self.source_closed_through <= self.evaluated_at < self.valid_until:
            raise ValueError("CONTEXT_CLOCK_ORDER_INVALID")
        return self


def material_context_hash_v31(symbol: str, material: MaterialContextV31) -> str:
    material = MaterialContextV31.model_validate(material.model_dump())
    return content_hash({"symbol": symbol, "material": material.model_dump(mode="json")})


def context_route_receipt_hash_v31(receipt: ContextRouteReceiptV31) -> str:
    receipt = ContextRouteReceiptV31.model_validate(receipt.model_dump())
    return content_hash(receipt.model_dump(mode="json"))
