"""Decide whether a pressure event continues a market episode or opens one.

The decision is a pure function of the event, the active lifecycle and the
policy, so replay and live reach the same answer.  Nothing here writes.

Three clocks, three different questions:

``last_event_at``
    Did anything arrive at all?  Advances for every valid, deduplicated event,
    including a non-pressure heartbeat.

``last_continuity_event_at``
    Is the market episode still alive?  Advances for every event that still
    carries pressure evidence, even when nothing about the analysis changed.
    **This is the clock the episode gap measures against.**

``last_material_event_at``
    Did the analysis change?  Advances only on a real domain transition.

Splitting on the material clock would confuse "nothing changed" with "the
episode stopped", and would shatter a long stretch of steady pressure.
Splitting on the event clock would let an unrelated heartbeat keep a dead
episode alive forever.  Continuity is the honest middle.

Direction is the other thing that is easy to get wrong: a single opposite
pressure snapshot is *not* a reversal.  It moves the episode to
TRANSITION_PENDING and waits.  Formal direction-transition proof is a later
increment; until it exists the only deterministic exits are a return to a
definite direction or a continuity gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from analysis.strategy_5scr_v3.episode_policy import MarketEpisodePolicyV1
from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleV2

GroupingAction = str

CONTINUE_EPISODE: GroupingAction = "CONTINUE_EPISODE"
OPEN_EPISODE: GroupingAction = "OPEN_EPISODE"
MARK_TRANSITION_PENDING: GroupingAction = "MARK_TRANSITION_PENDING"
RESOLVE_TRANSITION: GroupingAction = "RESOLVE_TRANSITION"

# Why an episode boundary was drawn -- surfaced as shadow metrics.
SPLIT_NO_ACTIVE_EPISODE = "NO_ACTIVE_EPISODE"
SPLIT_CONTINUITY_GAP = "CONTINUITY_GAP_EXCEEDED"
SPLIT_TERMINAL_LIFECYCLE = "TERMINAL_LIFECYCLE"
SPLIT_HARD_CONTEXT_RESET = "HARD_CONTEXT_RESET"

#: Microboost transitions that count as a material change (from a later
#: increment; carried here so the rule exists rather than being implied).
MATERIAL_MICROBOOST_TRANSITIONS: frozenset[str] = frozenset(
    {"FORMED", "REINFORCED", "WEAKENED", "INVALIDATED", "EXPIRED"}
)


@dataclass(frozen=True, slots=True)
class EpisodeEvent:
    """The subset of a pressure event that episode grouping reads."""

    pressure_event_id: str
    symbol: str
    event_time_utc: datetime
    transport_lifecycle_id: str
    raw_direction: str | None = None
    source_clean_block_id: str | None = None
    source_watch_id: str | None = None

    # --- continuity evidence -------------------------------------------
    # Any of these proves the pressure episode is still running.  A generic
    # heartbeat carries none of them and therefore cannot sustain an episode.
    pressure_seen: bool = False
    pair_eligible_for_analysis: bool = False
    allowed_quorum_reached: bool = False
    microboost_detected: bool = False
    pressure_event_count: int = 0

    # --- material-change signals ----------------------------------------
    #: Emitted by the Microboost pulse engine in a later increment.
    microboost_transition: str | None = None
    #: Material context fingerprint; a change means the context moved.
    context_hash: str | None = None
    #: Set by later increments (structural invalidation / context reset).
    hard_context_reset: bool = False

    @property
    def direction(self) -> str | None:
        resolved = (self.raw_direction or "").upper()
        return resolved if resolved in {"BUY", "SELL"} else None

    @property
    def is_continuity_evidence(self) -> bool:
        """Does this event prove the episode is still alive?"""
        return any(
            (
                self.pressure_seen,
                self.pair_eligible_for_analysis,
                self.allowed_quorum_reached,
                self.microboost_detected,
                self.pressure_event_count > 0,
            )
        )


@dataclass(frozen=True, slots=True)
class GroupingDecision:
    action: GroupingAction
    reason: str
    next_direction_state: str
    #: Advances last_continuity_event_at.
    continuity: bool
    #: Advances last_material_event_at.
    material: bool


def _directions_compatible(current: str, incoming: str | None) -> bool:
    if incoming is None:
        return True
    if current in {"INCOMPLETE", "CONFLICT"}:
        return True
    return current == incoming


def decide_grouping(
    event: EpisodeEvent,
    active: StrategyLifecycleV2 | None,
    policy: MarketEpisodePolicyV1,
    *,
    context_changed: bool = False,
    lineage_newly_attached: bool = False,
) -> GroupingDecision:
    """Resolve one event against the active episode for its symbol."""

    continuity = event.is_continuity_evidence

    if active is None:
        return GroupingDecision(
            action=OPEN_EPISODE,
            reason=SPLIT_NO_ACTIVE_EPISODE,
            next_direction_state=event.direction or "INCOMPLETE",
            continuity=True,
            material=True,
        )

    if active.is_terminal:
        # A terminal episode is never reopened.
        return GroupingDecision(
            action=OPEN_EPISODE,
            reason=SPLIT_TERMINAL_LIFECYCLE,
            next_direction_state=event.direction or "INCOMPLETE",
            continuity=True,
            material=True,
        )

    if active.symbol != event.symbol:  # pragma: no cover - caller partitions by symbol
        return GroupingDecision(
            action=OPEN_EPISODE,
            reason=SPLIT_NO_ACTIVE_EPISODE,
            next_direction_state=event.direction or "INCOMPLETE",
            continuity=True,
            material=True,
        )

    # The episode gap is measured against continuity, not material change:
    # steady pressure keeps a story alive even when nothing about it moves.
    gap = (event.event_time_utc - active.last_continuity_event_at_utc).total_seconds()
    if gap > policy.max_continuity_gap_seconds:
        return GroupingDecision(
            action=OPEN_EPISODE,
            reason=SPLIT_CONTINUITY_GAP,
            next_direction_state=event.direction or "INCOMPLETE",
            continuity=True,
            material=True,
        )

    if event.hard_context_reset:
        return GroupingDecision(
            action=OPEN_EPISODE,
            reason=SPLIT_HARD_CONTEXT_RESET,
            next_direction_state=event.direction or "INCOMPLETE",
            continuity=True,
            material=True,
        )

    incoming = event.direction
    current = active.direction_state
    other_material = (
        event.microboost_transition in MATERIAL_MICROBOOST_TRANSITIONS
        or context_changed
        or lineage_newly_attached
    )

    if current == "CONFLICT":
        # Sitting in TRANSITION_PENDING.  Formal transition proof lands in a
        # later increment; for now only a return to a definite direction
        # resolves it, and it resolves to that direction.
        if incoming is None:
            return GroupingDecision(
                action=CONTINUE_EPISODE,
                reason="TRANSITION_PENDING_UNCHANGED",
                next_direction_state="CONFLICT",
                continuity=continuity,
                material=other_material,
            )
        return GroupingDecision(
            action=RESOLVE_TRANSITION,
            reason="DIRECTION_RESTATED",
            next_direction_state=incoming,
            continuity=continuity,
            material=True,
        )

    if not _directions_compatible(current, incoming):
        # One opposite snapshot is evidence, not a reversal.
        return GroupingDecision(
            action=MARK_TRANSITION_PENDING,
            reason="OPPOSITE_DIRECTION_OBSERVED",
            next_direction_state="CONFLICT",
            continuity=continuity,
            material=True,
        )

    if current == "INCOMPLETE" and incoming is not None:
        return GroupingDecision(
            action=CONTINUE_EPISODE,
            reason="DIRECTION_RESOLVED",
            next_direction_state=incoming,
            continuity=continuity,
            material=True,
        )

    # Same direction, or an unknown-direction refresh.  Continuity may advance;
    # the material clock only moves if something else genuinely changed.
    return GroupingDecision(
        action=CONTINUE_EPISODE,
        reason="EPISODE_CONTINUED",
        next_direction_state=current,
        continuity=continuity,
        material=other_material,
    )


__all__ = [
    "CONTINUE_EPISODE",
    "MARK_TRANSITION_PENDING",
    "MATERIAL_MICROBOOST_TRANSITIONS",
    "OPEN_EPISODE",
    "RESOLVE_TRANSITION",
    "SPLIT_CONTINUITY_GAP",
    "SPLIT_HARD_CONTEXT_RESET",
    "SPLIT_NO_ACTIVE_EPISODE",
    "SPLIT_TERMINAL_LIFECYCLE",
    "EpisodeEvent",
    "GroupingDecision",
    "decide_grouping",
]
