"""Pure market-episode reducer for the V31 chain (S1B-0).

Same answer live and in replay: events are folded in (symbol, event_time, pressure_event_id) order, duplicates
change nothing, and every threshold comes from an explicit ``LifecycleMergePolicyV31`` (no default gap).

Three clocks answer three questions (as in the repository's market-episode rule):
- event clock: did anything arrive (a heartbeat too)?
- continuity clock: is the episode still alive? The episode gap is measured against THIS clock;
- material clock: did the analysis change?

An episode closes (and the triggering event opens the next one) only on a §8.3 boundary: continuity gap, hard
structural invalidation, confirmed opposite transition, or a different merge policy. A single opposite snapshot
is evidence, not a reversal: it moves the episode to TRANSITION_PENDING. Transport identity churn (cluster, clean
block, watch, deployment, transport lifecycle) never opens an episode.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from contracts.strategy_5scr_market_episode_v31 import (
    LifecycleMergePolicyV31,
    MarketEpisodeEventV31,
    MarketEpisodeLinkV31,
    MarketEpisodeStateV31,
    MarketEpisodeV31,
    market_episode_id_v31,
    strategy_lifecycle_id_from_episode_v31,
)


@dataclass(frozen=True)
class EpisodeGroupingDecisionV31:
    action: str  # OPEN | CONTINUE | MARK_TRANSITION_PENDING | RESOLVE_TRANSITION
    reason: str
    next_direction_state: str
    continuity: bool
    material: bool


def decide_episode_grouping_v31(
    event: MarketEpisodeEventV31,
    episode: MarketEpisodeV31 | None,
    state: MarketEpisodeStateV31 | None,
    policy: LifecycleMergePolicyV31,
    *,
    last_definite_direction: str | None,
    context_changed: bool,
    lineage_newly_attached: bool,
) -> EpisodeGroupingDecisionV31:
    opening = event.direction or "INCOMPLETE"
    if episode is None or state is None or state.state == "CLOSED":
        return EpisodeGroupingDecisionV31("OPEN", "NO_ACTIVE_EPISODE", opening, True, True)
    if episode.merge_policy_hash != policy.policy_hash:
        return EpisodeGroupingDecisionV31("OPEN", "MERGE_POLICY_CHANGED", opening, True, True)
    gap = (event.event_time - state.last_continuity_event_at).total_seconds()
    if gap > policy.max_continuity_gap_seconds:
        return EpisodeGroupingDecisionV31("OPEN", "CONTINUITY_GAP_EXCEEDED", opening, True, True)
    if event.hard_structural_invalidation_evidence_id is not None:
        return EpisodeGroupingDecisionV31("OPEN", "HARD_STRUCTURAL_INVALIDATION", opening, True, True)
    if (
        event.confirmed_opposite_transition_evidence_id is not None
        and last_definite_direction is not None
        and event.direction != last_definite_direction
    ):
        return EpisodeGroupingDecisionV31("OPEN", "CONFIRMED_OPPOSITE_TRANSITION", opening, True, True)

    continuity = event.is_continuity_evidence
    other_material = event.microboost_transition is not None or context_changed or lineage_newly_attached
    incoming, current = event.direction, state.direction_state
    if current == "CONFLICT":
        if incoming is None:
            return EpisodeGroupingDecisionV31(
                "CONTINUE", "TRANSITION_PENDING_UNCHANGED", "CONFLICT", continuity, other_material
            )
        return EpisodeGroupingDecisionV31("RESOLVE_TRANSITION", "DIRECTION_RESTATED", incoming, continuity, True)
    if incoming is not None and current in {"BUY", "SELL"} and incoming != current:
        return EpisodeGroupingDecisionV31(
            "MARK_TRANSITION_PENDING", "OPPOSITE_DIRECTION_OBSERVED", "CONFLICT", continuity, True
        )
    if current == "INCOMPLETE" and incoming is not None:
        return EpisodeGroupingDecisionV31("CONTINUE", "DIRECTION_RESOLVED", incoming, continuity, True)
    return EpisodeGroupingDecisionV31("CONTINUE", "EPISODE_CONTINUED", current, continuity, other_material)


@dataclass
class EpisodeReductionV31:
    episodes: dict[UUID, MarketEpisodeV31] = field(default_factory=dict)
    states: dict[UUID, MarketEpisodeStateV31] = field(default_factory=dict)
    links: list[MarketEpisodeLinkV31] = field(default_factory=list)
    split_reasons: dict[str, int] = field(default_factory=dict)
    duplicate_event_count: int = 0

    def episode_for_event(self, pressure_event_id: str) -> UUID | None:
        return next(
            (link.market_episode_id for link in self.links if link.pressure_event_id == pressure_event_id), None
        )


class MarketEpisodeReducerV31:
    def __init__(self, *, policy: LifecycleMergePolicyV31) -> None:
        self.policy = LifecycleMergePolicyV31.model_validate(policy.model_dump())
        self.result = EpisodeReductionV31()
        self._active: dict[str, UUID] = {}
        self._seen: set[str] = set()
        self._context: dict[UUID, str] = {}
        self._lineage: dict[UUID, set[str]] = {}
        self._definite: dict[UUID, str] = {}

    def seed(
        self,
        episode: MarketEpisodeV31,
        state: MarketEpisodeStateV31,
        *,
        seen_event_ids: Iterable[str] = (),
        context_hash: str | None = None,
        known_lineage: Iterable[str] = (),
        last_definite_direction: str | None = None,
    ) -> None:
        """Resume a persisted episode after a restart/redeploy so it continues instead of forking."""

        episode = MarketEpisodeV31.model_validate(episode.model_dump())
        state = MarketEpisodeStateV31.model_validate(state.model_dump())
        if state.market_episode_id != episode.market_episode_id or state.state == "CLOSED":
            raise ValueError("only an open episode with its own state can be seeded")
        self.result.episodes[episode.market_episode_id] = episode
        self.result.states[episode.market_episode_id] = state
        self._active[episode.canonical_symbol] = episode.market_episode_id
        self._seen.update(seen_event_ids)
        if context_hash is not None:
            self._context[episode.market_episode_id] = context_hash
        self._lineage[episode.market_episode_id] = set(known_lineage)
        if last_definite_direction is not None:
            self._definite[episode.market_episode_id] = last_definite_direction

    def ingest_many(self, events: Iterable[MarketEpisodeEventV31]) -> EpisodeReductionV31:
        for event in sorted(events, key=lambda e: (e.canonical_symbol, e.event_time, e.pressure_event_id)):
            self.ingest(event)
        return self.result

    def ingest(self, event: MarketEpisodeEventV31) -> MarketEpisodeV31:
        event = MarketEpisodeEventV31.model_validate(event.model_dump())
        if event.pressure_event_id in self._seen:
            self.result.duplicate_event_count += 1
            episode_id = self.result.episode_for_event(event.pressure_event_id) or self._active[event.canonical_symbol]
            return self.result.episodes[episode_id]
        self._seen.add(event.pressure_event_id)
        active_id = self._active.get(event.canonical_symbol)
        episode = self.result.episodes.get(active_id) if active_id else None
        state = self.result.states.get(active_id) if active_id else None
        decision = decide_episode_grouping_v31(
            event,
            episode,
            state,
            self.policy,
            last_definite_direction=self._definite.get(active_id) if active_id else None,
            context_changed=self._context_changed(active_id, event),
            lineage_newly_attached=self._lineage_new(active_id, event),
        )
        if decision.action == "OPEN":
            if episode is not None and state is not None and state.state != "CLOSED":
                self.result.states[episode.market_episode_id] = state.model_copy(
                    update={"state": "CLOSED", "closed_reason": decision.reason, "closed_at": event.event_time}
                )
            episode, reason = self._open(event, decision), "EPISODE_OPENED"
            self.result.split_reasons[decision.reason] = self.result.split_reasons.get(decision.reason, 0) + 1
        else:
            assert episode is not None and state is not None
            self._advance(episode, state, event, decision)
            reason = {
                "MARK_TRANSITION_PENDING": "DIRECTION_TRANSITION_PENDING",
                "RESOLVE_TRANSITION": "DIRECTION_RESTATED",
            }.get(
                decision.action,
                "DIRECTION_RESOLVED" if decision.reason == "DIRECTION_RESOLVED" else "EPISODE_CONTINUED",
            )
        self._remember(episode.market_episode_id, event, decision.next_direction_state)
        self.result.links.append(
            MarketEpisodeLinkV31(
                market_episode_id=episode.market_episode_id,
                pressure_event_id=event.pressure_event_id,
                link_reason=reason,  # type: ignore[arg-type]
                linked_at=event.event_time,
                transport_lifecycle_id=event.transport_lifecycle_id,
                source_clean_block_id=event.source_clean_block_id,
                source_watch_id=event.source_watch_id,
            )
        )
        return episode

    def _open(self, event: MarketEpisodeEventV31, decision: EpisodeGroupingDecisionV31) -> MarketEpisodeV31:
        episode_id = market_episode_id_v31(
            canonical_symbol=event.canonical_symbol,
            opened_at=event.event_time,
            merge_policy_hash=self.policy.policy_hash,
        )
        episode = MarketEpisodeV31(
            market_episode_id=episode_id,
            strategy_lifecycle_id=strategy_lifecycle_id_from_episode_v31(episode_id),
            canonical_symbol=event.canonical_symbol,
            opened_at=event.event_time,
            opening_pressure_event_id=event.pressure_event_id,
            opening_split_reason=decision.reason,  # type: ignore[arg-type]
            merge_policy_version=self.policy.policy_version,
            merge_policy_hash=self.policy.policy_hash,
        )
        self.result.episodes[episode_id] = episode
        self.result.states[episode_id] = MarketEpisodeStateV31(
            market_episode_id=episode_id,
            state="OPEN",
            direction_state=decision.next_direction_state,  # type: ignore[arg-type]
            last_event_at=event.event_time,
            last_continuity_event_at=event.event_time,
            last_material_event_at=event.event_time,
            event_count=1,
            closed_reason=None,
            closed_at=None,
        )
        self._active[event.canonical_symbol] = episode_id
        return episode

    def _advance(
        self,
        episode: MarketEpisodeV31,
        state: MarketEpisodeStateV31,
        event: MarketEpisodeEventV31,
        decision: EpisodeGroupingDecisionV31,
    ) -> None:
        at: datetime = event.event_time
        continuity_at = at if (decision.continuity or decision.material) else state.last_continuity_event_at
        self.result.states[episode.market_episode_id] = MarketEpisodeStateV31(
            market_episode_id=episode.market_episode_id,
            state="TRANSITION_PENDING" if decision.next_direction_state == "CONFLICT" else "OPEN",
            direction_state=decision.next_direction_state,  # type: ignore[arg-type]
            last_event_at=max(state.last_event_at, at),
            last_continuity_event_at=continuity_at,
            last_material_event_at=at if decision.material else state.last_material_event_at,
            event_count=state.event_count + 1,
            closed_reason=None,
            closed_at=None,
        )

    def _context_changed(self, episode_id: UUID | None, event: MarketEpisodeEventV31) -> bool:
        if episode_id is None or event.material_context_hash is None:
            return False
        previous = self._context.get(episode_id)
        return previous is not None and previous != event.material_context_hash

    def _lineage_new(self, episode_id: UUID | None, event: MarketEpisodeEventV31) -> bool:
        lineage = {v for v in (event.source_clean_block_id, event.source_watch_id) if v is not None}
        return episode_id is not None and bool(lineage - self._lineage.get(episode_id, set()))

    def _remember(self, episode_id: UUID, event: MarketEpisodeEventV31, direction_state: str) -> None:
        if event.material_context_hash is not None:
            self._context[episode_id] = event.material_context_hash
        self._lineage.setdefault(episode_id, set()).update(
            v for v in (event.source_clean_block_id, event.source_watch_id) if v is not None
        )
        if direction_state in {"BUY", "SELL"}:
            self._definite[episode_id] = direction_state


__all__ = [
    "EpisodeGroupingDecisionV31",
    "EpisodeReductionV31",
    "MarketEpisodeReducerV31",
    "decide_episode_grouping_v31",
]
