"""Strategy analysis lifecycle V2 -- durable market-episode identity.

A market story is not a transport event.  The existing identities
(``event_id``, ``pressure_outbox_id``, transport ``lifecycle_id``,
``source_clean_block_id``, ``source_watch_id``, ``cluster_id``) remain the
source lineage and are untouched by this contract.  What they cannot express is
*which market episode* an emission belongs to: measured on the repo's own
archive cohort, ``cluster_id`` is unique in all 1985 records, so keying an
analysis lifecycle on transport identity splits one story into as many
lifecycles as there were emissions.

``strategy_lifecycle_id`` is that missing identity, and only that:

    transport_lifecycle_id != strategy_lifecycle_id != execution_campaign_id

This layer is shadow-only.  ``execution_authority`` is pinned ``False`` and no
object here routes pressure, resolves direction, gates evidence, or authorizes
anything.  Canonical anchors are *linked* to an episode rather than replaced by
it, so clean-block lineage keeps all of its existing value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MARKET_EPISODE_RULE_VERSION = "5scr.market-episode.v1"

LifecycleState = Literal[
    "ANALYSIS_OPEN",
    "TRANSITION_PENDING",
    "TERMINAL_NO_TRADE",
    "INVALIDATED",
    "SUPERSEDED",
]
DirectionState = Literal["BUY", "SELL", "INCOMPLETE", "CONFLICT"]

#: A terminal lifecycle is never reopened; later evidence starts a new episode.
TERMINAL_LIFECYCLE_STATES: frozenset[str] = frozenset(
    {"TERMINAL_NO_TRADE", "INVALIDATED", "SUPERSEDED"}
)
ACTIVE_LIFECYCLE_STATES: frozenset[str] = frozenset({"ANALYSIS_OPEN", "TRANSITION_PENDING"})

LinkReason = Literal[
    "EPISODE_OPENED",
    "EPISODE_CONTINUED",
    "DIRECTION_TRANSITION_PENDING",
    "CANONICAL_ANCHOR_ATTACHED",
]


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


class StrategyLifecycleV2(FrozenContract):
    """One durable market episode for one symbol."""

    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    state: LifecycleState = "ANALYSIS_OPEN"
    direction_state: DirectionState = "INCOMPLETE"
    opened_at_utc: datetime
    #: Every valid, deduplicated event -- including a non-pressure heartbeat.
    last_event_at_utc: datetime
    #: Every event that still proves the pressure episode is alive.  This is
    #: the clock the episode gap measures against: repeated same-direction
    #: pressure keeps a story going even though nothing about it changed.
    last_continuity_event_at_utc: datetime
    #: Only a material change in analysis state (direction, Microboost
    #: transition, new canonical lineage, material context change).  A sticky
    #: snapshot or telemetry refresh must never advance this.
    last_material_event_at_utc: datetime
    rule_version: Literal["5scr.market-episode.v1"] = MARKET_EPISODE_RULE_VERSION
    material_state_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    event_count: int = Field(default=0, ge=0)
    clean_block_count: int = Field(default=0, ge=0)
    watch_count: int = Field(default=0, ge=0)
    #: Shadow-only.  A market episode never grants execution authority.
    execution_authority: Literal[False] = False

    @field_validator(
        "opened_at_utc",
        "last_event_at_utc",
        "last_continuity_event_at_utc",
        "last_material_event_at_utc",
    )
    @classmethod
    def _times_are_utc(cls, value: datetime) -> datetime:
        return _utc(value, "lifecycle timestamp")

    @model_validator(mode="after")
    def _time_order_is_valid(self) -> StrategyLifecycleV2:
        if self.last_event_at_utc < self.opened_at_utc:
            raise ValueError("last_event_at_utc cannot precede opened_at_utc")
        if self.last_continuity_event_at_utc < self.opened_at_utc:
            raise ValueError("last_continuity_event_at_utc cannot precede opened_at_utc")
        if self.last_material_event_at_utc < self.opened_at_utc:
            raise ValueError("last_material_event_at_utc cannot precede opened_at_utc")
        # Each clock is a subset of the one above it.
        if self.last_continuity_event_at_utc > self.last_event_at_utc:
            raise ValueError("a continuity event cannot follow the latest observed event")
        if self.last_material_event_at_utc > self.last_continuity_event_at_utc:
            raise ValueError("a material event cannot follow the latest continuity event")
        if self.state == "TRANSITION_PENDING" and self.direction_state != "CONFLICT":
            raise ValueError("TRANSITION_PENDING requires a CONFLICT direction state")
        return self

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_LIFECYCLE_STATES

    @property
    def is_active(self) -> bool:
        return self.state in ACTIVE_LIFECYCLE_STATES


class StrategyLifecycleEventLink(FrozenContract):
    """Binds one pressure event to its episode, preserving transport lineage."""

    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    # Format is owned by the producer (UUID in the outbox, ``sha256:`` in
    # replay); this contract only requires that an id exists.
    pressure_event_id: str = Field(..., min_length=1, max_length=240)
    transport_lifecycle_id: str = Field(..., min_length=1, max_length=240)
    source_clean_block_id: str | None = Field(default=None, max_length=240)
    source_watch_id: str | None = Field(default=None, max_length=240)
    linked_at_utc: datetime
    link_reason: LinkReason

    @field_validator("linked_at_utc")
    @classmethod
    def _linked_at_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "linked_at_utc")


__all__ = [
    "ACTIVE_LIFECYCLE_STATES",
    "MARKET_EPISODE_RULE_VERSION",
    "TERMINAL_LIFECYCLE_STATES",
    "DirectionState",
    "LifecycleState",
    "LinkReason",
    "StrategyLifecycleEventLink",
    "StrategyLifecycleV2",
]
