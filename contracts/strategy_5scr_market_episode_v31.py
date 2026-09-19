"""MarketEpisodeV31: the identity root of the V31 analysis chain (S1B-0, owner decision S3, 2026-09-20).

SSOT v3.1 §4.1/§4.2/§8.1/§8.3: a GRANTED StrategyAnalysisAdmission opens or joins a market episode and its
strategy lifecycle. The lifecycle holds 1..N admissions, and an advisory → canonical upgrade keeps the SAME
lifecycle id (§7A.6, §8.6). Identity therefore flows

    MarketEpisodeV31 → strategy_lifecycle_id → 1..N StrategyAnalysisAdmission

and never the other way round. The episode id is derived only from the symbol, the opening time and the hashed
merge policy (LifecycleMergePolicyRegistry, §26). Deployment, cluster, clean block, watch id, transport lifecycle,
admission class and telemetry refresh never enter any identity (§8.3). Grouping semantics mirror the repository's
market-episode rule (three clocks: event / continuity / material; one opposite snapshot = TRANSITION_PENDING, not a
split) without its hidden 900 s default: every threshold is policy data.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Same encoding/hash as the rest of the native V31 family; consolidated with #493 in its rework.
IDENTITY_ENCODING_VERSION = "v31.native-identity.v1"
MARKET_EPISODE_RULE_VERSION = "5scr.market-episode.v31.v1"
V31_MARKET_EPISODE_NAMESPACE = UUID("cbb3a046-9efb-48a1-a507-e2a07ff30b6c")
V31_LIFECYCLE_FROM_EPISODE_NAMESPACE = UUID("0c71acaa-17bb-41de-8cba-095d51fbe2bf")

Direction = Literal["BUY", "SELL"]
DirectionState = Literal["BUY", "SELL", "INCOMPLETE", "CONFLICT"]  # §8.2 direction_state
EpisodeState = Literal["OPEN", "TRANSITION_PENDING", "CLOSED"]
MicroboostTransition = Literal["FORMED", "REINFORCED", "WEAKENED", "INVALIDATED", "EXPIRED"]
SplitReason = Literal[
    "NO_ACTIVE_EPISODE",
    "CONTINUITY_GAP_EXCEEDED",
    "HARD_STRUCTURAL_INVALIDATION",
    "CONFIRMED_OPPOSITE_TRANSITION",
    "MERGE_POLICY_CHANGED",
]
LinkReason = Literal[
    "EPISODE_OPENED",
    "EPISODE_CONTINUED",
    "DIRECTION_RESOLVED",
    "DIRECTION_TRANSITION_PENDING",
    "DIRECTION_RESTATED",
    "DUPLICATE_EVENT_IGNORED",
]
_DIGEST = r"^sha256:[0-9a-f]{64}$"
_SYMBOL = r"^[A-Z0-9._-]{3,32}$"


def canonical_sha256_v31(value: object) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def _aware(*moments: datetime | None) -> None:
    for moment in moments:
        if moment is not None and (moment.tzinfo is None or moment.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")


def _payload_hash(model: BaseModel, hash_field: str) -> str:
    return canonical_sha256_v31({k: v for k, v in model.model_dump(mode="json").items() if k != hash_field})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class LifecycleMergePolicyV31(_Strict):
    """§8.3 'merge policy version sama'. No default gap: the value is always explicit policy data."""

    policy_version: str = Field(min_length=3, max_length=120)
    rule_version: Literal["5scr.market-episode.v31.v1"]
    max_continuity_gap_seconds: int = Field(gt=0)
    policy_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _valid(self) -> LifecycleMergePolicyV31:
        if self.policy_hash != _payload_hash(self, "policy_hash"):
            raise ValueError("LIFECYCLE_MERGE_POLICY_HASH_MISMATCH")
        return self


class MarketEpisodeEventV31(_Strict):
    """Typed subset of one deduplicated pressure event that episode grouping reads.

    Transport identities are carried for audit lineage only and never read by grouping or identity.
    """

    pressure_event_id: str = Field(min_length=1, max_length=240)
    canonical_symbol: str = Field(pattern=_SYMBOL)
    event_time: datetime
    direction: Direction | None
    # Continuity evidence (any one proves the episode is alive; a bare heartbeat carries none).
    pressure_seen: bool
    pair_eligible_for_analysis: bool
    allowed_quorum_reached: bool
    microboost_detected: bool
    pressure_event_count: int = Field(ge=0)
    # Material-change signals.
    microboost_transition: MicroboostTransition | None
    material_context_hash: str | None = Field(pattern=_DIGEST)
    # §8.3 hard boundaries, each only with an explicit evidence reference.
    hard_structural_invalidation_evidence_id: str | None = Field(max_length=240)
    confirmed_opposite_transition_evidence_id: str | None = Field(max_length=240)
    # Audit lineage only (§8.3: none of these may open a lifecycle).
    transport_lifecycle_id: str | None = Field(max_length=240)
    source_clean_block_id: str | None = Field(max_length=240)
    source_watch_id: str | None = Field(max_length=240)
    cluster_id: str | None = Field(max_length=240)
    deployment_id: str | None = Field(max_length=240)

    @model_validator(mode="after")
    def _bound(self) -> MarketEpisodeEventV31:
        _aware(self.event_time)
        if self.confirmed_opposite_transition_evidence_id is not None and self.direction is None:
            raise ValueError("a confirmed opposite transition must carry its new direction")
        return self

    @property
    def is_continuity_evidence(self) -> bool:
        return (
            self.pressure_seen
            or self.pair_eligible_for_analysis
            or self.allowed_quorum_reached
            or self.microboost_detected
            or self.pressure_event_count > 0
        )


def market_episode_id_v31(*, canonical_symbol: str, opened_at: datetime, merge_policy_hash: str) -> UUID:
    """Symbol + opening time + merge policy. No transport, deployment or admission input."""

    _aware(opened_at)
    name = json.dumps(
        [IDENTITY_ENCODING_VERSION, canonical_symbol, opened_at.isoformat(), merge_policy_hash],
        separators=(",", ":"),
    )
    return uuid5(V31_MARKET_EPISODE_NAMESPACE, name)


def strategy_lifecycle_id_from_episode_v31(market_episode_id: UUID) -> UUID:
    """1:1 with the market episode (§8.1); admissions attach to it and never derive it."""

    name = json.dumps([IDENTITY_ENCODING_VERSION, str(market_episode_id)], separators=(",", ":"))
    return uuid5(V31_LIFECYCLE_FROM_EPISODE_NAMESPACE, name)


class MarketEpisodeV31(_Strict):
    """Immutable identity record of one market episode for one symbol."""

    identity_encoding_version: Literal["v31.native-identity.v1"] = IDENTITY_ENCODING_VERSION
    rule_version: Literal["5scr.market-episode.v31.v1"] = MARKET_EPISODE_RULE_VERSION
    market_episode_id: UUID
    strategy_lifecycle_id: UUID
    canonical_symbol: str = Field(pattern=_SYMBOL)
    opened_at: datetime
    opening_pressure_event_id: str = Field(min_length=1, max_length=240)  # audit only, not identity
    opening_split_reason: SplitReason
    merge_policy_version: str
    merge_policy_hash: str = Field(pattern=_DIGEST)
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _derived(self) -> MarketEpisodeV31:
        expected = market_episode_id_v31(
            canonical_symbol=self.canonical_symbol, opened_at=self.opened_at, merge_policy_hash=self.merge_policy_hash
        )
        if self.market_episode_id != expected:
            raise ValueError("MARKET_EPISODE_ID_NOT_DERIVED")
        if self.strategy_lifecycle_id != strategy_lifecycle_id_from_episode_v31(self.market_episode_id):
            raise ValueError("STRATEGY_LIFECYCLE_ID_NOT_DERIVED_FROM_EPISODE")
        return self


class MarketEpisodeStateV31(_Strict):
    """Reducer snapshot. Clocks are nested: material ⊆ continuity ⊆ event."""

    market_episode_id: UUID
    state: EpisodeState
    direction_state: DirectionState
    last_event_at: datetime
    last_continuity_event_at: datetime
    last_material_event_at: datetime
    event_count: int = Field(ge=1)
    closed_reason: SplitReason | None
    closed_at: datetime | None

    @model_validator(mode="after")
    def _clocks(self) -> MarketEpisodeStateV31:
        _aware(self.last_event_at, self.last_continuity_event_at, self.last_material_event_at, self.closed_at)
        if not self.last_material_event_at <= self.last_continuity_event_at <= self.last_event_at:
            raise ValueError("EPISODE_CLOCKS_NOT_NESTED")
        if (self.state == "TRANSITION_PENDING") != (self.direction_state == "CONFLICT"):
            raise ValueError("TRANSITION_PENDING is exactly direction CONFLICT")
        if (self.state == "CLOSED") != (self.closed_reason is not None) or (self.closed_reason is None) != (
            self.closed_at is None
        ):
            raise ValueError("a CLOSED episode carries exactly a close reason and time")
        return self


class MarketEpisodeLinkV31(_Strict):
    market_episode_id: UUID
    pressure_event_id: str
    link_reason: LinkReason
    linked_at: datetime
    transport_lifecycle_id: str | None
    source_clean_block_id: str | None
    source_watch_id: str | None


__all__ = [
    "IDENTITY_ENCODING_VERSION",
    "MARKET_EPISODE_RULE_VERSION",
    "V31_LIFECYCLE_FROM_EPISODE_NAMESPACE",
    "V31_MARKET_EPISODE_NAMESPACE",
    "LifecycleMergePolicyV31",
    "MarketEpisodeEventV31",
    "MarketEpisodeLinkV31",
    "MarketEpisodeStateV31",
    "MarketEpisodeV31",
    "canonical_sha256_v31",
    "market_episode_id_v31",
    "strategy_lifecycle_id_from_episode_v31",
]
