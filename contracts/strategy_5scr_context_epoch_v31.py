"""ContextEpochV31 + ContextRouteEvaluationV31 (gap #9, authority decisions 2026-09-19, Option A).

Requalified on #504 (2026-09-20): the lifecycle is the MarketEpisode-rooted ``strategy_lifecycle_id`` of the S1B
lineage (#501-#503), never derived from an admission. Both records bind the episode and prove the 1:1 derivation,
so an advisory-to-canonical authority upgrade cannot fork the epoch: neither the admission id nor the admission
class appears in any identity tuple or in any stored field.

SSOT §12 separates a direction-neutral Material ContextEpoch (§12.1, §12.3) from the evaluation of context for
one direction (§12.2 location, §12.4 outcome, §28.14 alignment). The existing ``ContextRouteReceiptV31`` stays
unchanged and is only a POSITIVE projection of an evaluation that permits a route.

- Epoch id: UUIDv5 over [encoding, lifecycle, material_context_hash]; own immutable clock; it ends by clock
  expiry or by supersession when the material hash changes. Never refreshed, never revived.
- Evaluation id: UUIDv5 over [encoding, epoch, evaluated_direction, pressure_hypothesis_id|null].
- Registries/policies are explicit hash-bound objects; missing or mismatched means fail closed.
- Out of scope: the §13 liquidity FSM and §12.6 rejection/resolution (liquidity arrives as opaque material).

Neither object carries direction, thesis, geometry, risk, broker or execution authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_context_route_v31 import MaterialContextV31, material_context_hash_v31
from contracts.strategy_5scr_identity_v31 import (
    IDENTITY_ENCODING_VERSION,
    SELECTED_SSOT_HASH,
    canonical_sha256_v31,
    identity_uuid_v31,
)
from contracts.strategy_5scr_market_episode_v31 import strategy_lifecycle_id_from_episode_v31

CONTEXT_EPOCH_V31_RULE_VERSION = "5scr.context-epoch.v31.v2"
CONTEXT_ROUTE_EVALUATION_V31_RULE_VERSION = "5scr.context-route-evaluation.v31.v2"
V31_CONTEXT_EPOCH_NAMESPACE = UUID("7977ee0b-5780-4c9d-baf5-0bdf14f4f881")
V31_CONTEXT_ROUTE_EVALUATION_NAMESPACE = UUID("501f6b98-e095-4084-aad9-1ae3a02c32d2")

Direction = Literal["BUY", "SELL"]
Domain = Literal["BUY_ONLY", "SELL_ONLY", "BOTH_CONDITIONAL", "UNRESOLVED", "EMPTY"]
LocationAlignment = Literal["FAVORABLE", "NEUTRAL", "UNFAVORABLE", "UNKNOWN"]
ContextAlignment = Literal["ALIGNED", "CONFLICT", "UNRESOLVED", "EMPTY"]  # SSOT §28.14
ContextOutcome = Literal[  # SSOT §12.4, verbatim
    "ALIGN",
    "CONFLICT",
    "DEFER",
    "BLOCK_ROUTE",
    "AUTHORIZE_PROOF_REQUIRED_COUNTER_PRESSURE",
    "INVALIDATE",
]
ROUTE_PERMITTING_OUTCOMES = frozenset({"ALIGN", "AUTHORIZE_PROOF_REQUIRED_COUNTER_PRESSURE"})
_DIGEST = r"^sha256:[0-9a-f]{64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def _aware(*moments: datetime | None) -> None:
    for moment in moments:
        if moment is not None and (moment.tzinfo is None or moment.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")


def _payload_hash(model: BaseModel, hash_field: str) -> str:
    return canonical_sha256_v31({k: v for k, v in model.model_dump(mode="json").items() if k != hash_field})


class DirectionDomainEntryV31(_Strict):
    domain: Domain
    directions: tuple[Direction, ...] = Field(max_length=2)


class DirectionDomainRegistryV31(_Strict):
    registry_version: str = Field(min_length=3, max_length=120)
    entries: tuple[DirectionDomainEntryV31, ...] = Field(min_length=1)
    registry_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _valid(self) -> DirectionDomainRegistryV31:
        if len({entry.domain for entry in self.entries}) != len(self.entries):
            raise ValueError("one entry per domain")
        if self.registry_hash != _payload_hash(self, "registry_hash"):
            raise ValueError("DIRECTION_DOMAIN_REGISTRY_HASH_MISMATCH")
        return self

    def directions_for(self, domain: str) -> tuple[str, ...] | None:
        return next((entry.directions for entry in self.entries if entry.domain == domain), None)


class RouteRuleV31(_Strict):
    route: str = Field(min_length=1, max_length=160)
    direction: Direction
    permitted_location_alignments: tuple[LocationAlignment, ...] = Field(min_length=1)
    requires_authoritative_quote: bool


class LocationRoutePolicyV31(_Strict):
    policy_version: str = Field(min_length=3, max_length=120)
    route_registry_version: str = Field(min_length=3, max_length=120)
    routes: tuple[RouteRuleV31, ...] = Field(min_length=1)
    policy_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _valid(self) -> LocationRoutePolicyV31:
        keys = [(rule.route, rule.direction) for rule in self.routes]
        if len(set(keys)) != len(keys):
            raise ValueError("one rule per route and direction")
        if self.policy_hash != _payload_hash(self, "policy_hash"):
            raise ValueError("LOCATION_ROUTE_POLICY_HASH_MISMATCH")
        return self

    def rule(self, route: str, direction: str) -> RouteRuleV31 | None:
        return next((r for r in self.routes if r.route == route and r.direction == direction), None)


class ContextClockPolicyV31(_Strict):
    clock_policy_version: str = Field(min_length=3, max_length=120)
    ttl_seconds: int = Field(gt=0)
    clock_source: Literal["INJECTED_DECISION_CLOCK"]
    policy_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _valid(self) -> ContextClockPolicyV31:
        if self.policy_hash != _payload_hash(self, "policy_hash"):
            raise ValueError("CONTEXT_CLOCK_POLICY_HASH_MISMATCH")
        return self


_M = TypeVar("_M", bound=BaseModel)


def with_hash(model_type: type[_M], hash_field: str, **values: Any) -> _M:
    """Build a hash-bound policy/registry fixture (tests, fixtures). The hash covers every other field."""

    probe = model_type.model_construct(None, **{**values, hash_field: "sha256:" + "0" * 64})
    return model_type.model_validate({**values, hash_field: _payload_hash(probe, hash_field)})


def context_epoch_id_v31(*, strategy_lifecycle_id: UUID, material_context_hash: str) -> UUID:
    """Lifecycle + material only. No admission id, no admission class, no clock, no direction: an authority upgrade
    inside the same market episode therefore cannot produce a second epoch for the same material context."""

    return identity_uuid_v31(V31_CONTEXT_EPOCH_NAMESPACE, [str(strategy_lifecycle_id), material_context_hash])


def context_route_evaluation_id_v31(
    *, context_epoch_id: UUID, evaluated_direction: str, pressure_hypothesis_id: UUID | None
) -> UUID:
    """The hypothesis id is admission-free (#494), so the evaluation id is stable across an authority upgrade too."""

    return identity_uuid_v31(
        V31_CONTEXT_ROUTE_EVALUATION_NAMESPACE,
        [
            str(context_epoch_id),
            evaluated_direction,
            None if pressure_hypothesis_id is None else str(pressure_hypothesis_id),
        ],
    )


class ContextEpochV31(_Strict):
    """Direction-neutral material context truth. Immutable; ends only by clock or material supersession."""

    rule_version: Literal["5scr.context-epoch.v31.v2"] = CONTEXT_EPOCH_V31_RULE_VERSION
    identity_encoding_version: Literal["v31.native-identity.v1"] = IDENTITY_ENCODING_VERSION
    selected_ssot_hash: Literal["sha256:6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902"] = (
        SELECTED_SSOT_HASH
    )
    context_epoch_id: UUID
    strategy_lifecycle_id: UUID
    market_episode_id: UUID  # section 8.1 provenance; audit only, deliberately absent from the identity tuple
    canonical_symbol: str = Field(pattern=r"^[A-Z0-9._-]{3,32}$")
    material: MaterialContextV31
    material_context_hash: str = Field(pattern=_DIGEST)
    direction_domain_registry_version: str
    direction_domain_registry_hash: str = Field(pattern=_DIGEST)
    source_closed_through: datetime
    valid_from: datetime
    valid_until: datetime
    clock_policy_version: str
    clock_policy_hash: str = Field(pattern=_DIGEST)
    authority: Literal["CONTEXT_ONLY"] = "CONTEXT_ONLY"
    direction_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _bound(self) -> ContextEpochV31:
        _aware(self.source_closed_through, self.valid_from, self.valid_until)
        if self.material_context_hash != material_context_hash_v31(self.canonical_symbol, self.material):
            raise ValueError("CONTEXT_MATERIAL_HASH_MISMATCH")
        expected = context_epoch_id_v31(
            strategy_lifecycle_id=self.strategy_lifecycle_id, material_context_hash=self.material_context_hash
        )
        if self.context_epoch_id != expected:
            raise ValueError("CONTEXT_EPOCH_ID_NOT_DERIVED")
        if self.strategy_lifecycle_id != strategy_lifecycle_id_from_episode_v31(self.market_episode_id):
            raise ValueError("CONTEXT_EPOCH_LIFECYCLE_NOT_EPISODE_ROOTED")
        if not self.source_closed_through <= self.valid_from < self.valid_until:
            raise ValueError("CONTEXT_EPOCH_CLOCK_ORDER_INVALID")
        return self


class ContextEpochTerminationV31(_Strict):
    context_epoch_id: UUID
    terminal_state: Literal["SUPERSEDED", "EXPIRED"]
    reason_code: Literal["MATERIAL_CONTEXT_CHANGED", "CONTEXT_EPOCH_CLOCK_EXPIRED"]
    superseded_by: UUID | None
    terminated_at: datetime

    @model_validator(mode="after")
    def _shape(self) -> ContextEpochTerminationV31:
        _aware(self.terminated_at)
        if (self.terminal_state == "SUPERSEDED") != (self.superseded_by is not None):
            raise ValueError("superseded_by is required exactly for SUPERSEDED")
        return self


class ContextRouteEvaluationV31(_Strict):
    """Context evaluated for ONE direction. It can only ALIGN/CONFLICT/DEFER/BLOCK/authorize proof/INVALIDATE."""

    rule_version: Literal["5scr.context-route-evaluation.v31.v2"] = CONTEXT_ROUTE_EVALUATION_V31_RULE_VERSION
    identity_encoding_version: Literal["v31.native-identity.v1"] = IDENTITY_ENCODING_VERSION
    evaluation_id: UUID
    context_epoch_id: UUID
    strategy_lifecycle_id: UUID
    market_episode_id: UUID  # section 8.1 provenance; audit only, never part of the identity tuple
    canonical_symbol: str = Field(pattern=r"^[A-Z0-9._-]{3,32}$")
    evaluated_direction: Direction
    pressure_hypothesis_id: UUID | None
    direction_domain_registry_version: str
    location_route_policy_version: str
    location_route_policy_hash: str = Field(pattern=_DIGEST)
    route_registry_version: str
    location_alignment: LocationAlignment
    context_alignment: ContextAlignment
    counter_pressure_classification: Literal["PROHIBITED", "PROOF_REQUIRED", "AUTHORIZED"] | None
    quote_authoritative: bool
    outcome: ContextOutcome
    reason_code: str = Field(min_length=3, max_length=200)
    defer_reason: Literal["PRICE_QUALITY", "LOCATION_NOT_READY", "DOMAIN_UNRESOLVED"] | None
    selected_route: str | None
    resolution_evidence_hash: str = Field(pattern=_DIGEST)
    evaluated_at: datetime
    authority: Literal["ROUTE_EVALUATION_ONLY"] = "ROUTE_EVALUATION_ONLY"
    direction_authority: Literal[False] = False
    final_signal_allowed: Literal[False] = False
    execution_command_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _bound(self) -> ContextRouteEvaluationV31:
        _aware(self.evaluated_at)
        expected = context_route_evaluation_id_v31(
            context_epoch_id=self.context_epoch_id,
            evaluated_direction=self.evaluated_direction,
            pressure_hypothesis_id=self.pressure_hypothesis_id,
        )
        if self.evaluation_id != expected:
            raise ValueError("CONTEXT_ROUTE_EVALUATION_ID_NOT_DERIVED")
        if self.strategy_lifecycle_id != strategy_lifecycle_id_from_episode_v31(self.market_episode_id):
            raise ValueError("CONTEXT_EVALUATION_LIFECYCLE_NOT_EPISODE_ROOTED")
        if (self.selected_route is not None) != (self.outcome in ROUTE_PERMITTING_OUTCOMES):
            raise ValueError("selected_route is set exactly when the outcome permits a route")
        if (self.outcome == "DEFER") != (self.defer_reason is not None):
            raise ValueError("defer_reason is set exactly for DEFER")
        if self.outcome == "ALIGN" and self.context_alignment != "ALIGNED":
            raise ValueError("ALIGN requires context_alignment=ALIGNED")
        if self.outcome == "CONFLICT" and self.context_alignment != "CONFLICT":
            raise ValueError("CONFLICT requires context_alignment=CONFLICT")
        if self.outcome == "AUTHORIZE_PROOF_REQUIRED_COUNTER_PRESSURE" and self.counter_pressure_classification not in {
            "PROOF_REQUIRED",
            "AUTHORIZED",
        }:
            raise ValueError("counter-pressure route requires a non-prohibited classification")
        return self


__all__ = [
    "CONTEXT_EPOCH_V31_RULE_VERSION",
    "CONTEXT_ROUTE_EVALUATION_V31_RULE_VERSION",
    "ROUTE_PERMITTING_OUTCOMES",
    "V31_CONTEXT_EPOCH_NAMESPACE",
    "V31_CONTEXT_ROUTE_EVALUATION_NAMESPACE",
    "ContextClockPolicyV31",
    "ContextEpochTerminationV31",
    "ContextEpochV31",
    "ContextRouteEvaluationV31",
    "DirectionDomainEntryV31",
    "DirectionDomainRegistryV31",
    "LocationRoutePolicyV31",
    "RouteRuleV31",
    "context_epoch_id_v31",
    "context_route_evaluation_id_v31",
    "with_hash",
]
