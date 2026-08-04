"""Fold pressure events into durable market-episode lifecycles.

Pure reducer: no I/O, no execution impact.  Feeding the same events in any
order yields the same lifecycles, because the reducer sorts deterministically
before folding rather than trusting arrival order.

Deliberate properties, each asserted by test:

* A duplicate ``pressure_event_id`` changes nothing.
* A new ``cluster_id`` or ``deployment_id`` does not start an episode.
* A new clean block attaches to the episode instead of forking it.
* A telemetry refresh does not advance the material clock, so it can never
  extend an episode past its gap.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from analysis.strategy_5scr_v3.episode_grouping import (
    MARK_TRANSITION_PENDING,
    OPEN_EPISODE,
    RESOLVE_TRANSITION,
    EpisodeEvent,
    GroupingDecision,
    decide_grouping,
)
from analysis.strategy_5scr_v3.episode_hash import (
    build_material_state_hash,
    build_strategy_lifecycle_id,
)
from analysis.strategy_5scr_v3.episode_policy import MarketEpisodePolicyV1
from contracts.strategy_5scr_lifecycle_v2 import (
    DirectionState,
    StrategyLifecycleEventLink,
    StrategyLifecycleV2,
)


class EpisodeReduction:
    """Result of folding a batch of events."""

    __slots__ = (
        "lifecycles",
        "links",
        "split_reasons",
        "duplicate_event_count",
        "material_context_transition_count",
        "transport_identity_churn_ignored_count",
    )

    def __init__(self) -> None:
        self.lifecycles: dict[str, StrategyLifecycleV2] = {}
        self.links: list[StrategyLifecycleEventLink] = []
        self.split_reasons: dict[str, int] = {}
        self.duplicate_event_count: int = 0
        self.material_context_transition_count: int = 0
        self.transport_identity_churn_ignored_count: int = 0

    @property
    def compression_ratio(self) -> float | None:
        if not self.lifecycles:
            return None
        return len(self.links) / len(self.lifecycles)

    def lifecycle_for_event(self, pressure_event_id: str) -> str | None:
        for link in self.links:
            if link.pressure_event_id == pressure_event_id:
                return link.strategy_lifecycle_id
        return None


class MarketEpisodeReducer:
    """Reduce an ordered pressure stream into durable episodes."""

    def __init__(self, *, policy: MarketEpisodePolicyV1 | None = None) -> None:
        self.policy = policy or MarketEpisodePolicyV1()
        self._result = EpisodeReduction()
        self._active_by_symbol: dict[str, str] = {}
        self._seen_events: set[str] = set()
        # Per-episode memory used to tell a material change from a restatement.
        self._context_fingerprint: dict[str, str] = {}
        self._known_lineage: dict[str, set[str]] = {}
        self._transport_identity: dict[str, str] = {}

    @property
    def result(self) -> EpisodeReduction:
        return self._result

    def seed_active(
        self,
        lifecycle: StrategyLifecycleV2,
        *,
        known_lineage: Iterable[str] = (),
        context_hash: str | None = None,
        transport_lifecycle_id: str | None = None,
    ) -> None:
        """Resume a persisted episode so a restart continues it, not forks it.

        Used by the shadow worker after recovering the active episode from the
        database; the reducer otherwise only knows what it folded in-process.
        """
        if lifecycle.is_terminal:
            return
        self._result.lifecycles[lifecycle.strategy_lifecycle_id] = lifecycle
        self._active_by_symbol[lifecycle.symbol] = lifecycle.strategy_lifecycle_id
        restored_lineage = {str(value) for value in known_lineage if str(value)}
        if restored_lineage:
            self._known_lineage[lifecycle.strategy_lifecycle_id] = restored_lineage
        if context_hash:
            self._context_fingerprint[lifecycle.strategy_lifecycle_id] = context_hash
        if transport_lifecycle_id:
            self._transport_identity[lifecycle.strategy_lifecycle_id] = transport_lifecycle_id

    def ingest_many(self, events: Iterable[EpisodeEvent]) -> EpisodeReduction:
        # Deterministic order regardless of arrival order, so replay of an
        # out-of-order export matches live.
        ordered = sorted(
            events,
            key=lambda item: (item.symbol, item.event_time_utc, item.pressure_event_id),
        )
        for event in ordered:
            self.ingest(event)
        return self._result

    def ingest(self, event: EpisodeEvent) -> StrategyLifecycleV2:
        if event.pressure_event_id in self._seen_events:
            self._result.duplicate_event_count += 1
            active_id = self._active_by_symbol.get(event.symbol)
            existing = self._result.lifecycle_for_event(event.pressure_event_id)
            target = existing or active_id
            assert target is not None  # a seen event always has a lifecycle
            return self._result.lifecycles[target]
        self._seen_events.add(event.pressure_event_id)

        active_id = self._active_by_symbol.get(event.symbol)
        active = self._result.lifecycles.get(active_id) if active_id else None
        context_changed = self._context_changed(active_id, event)
        transport_changed = (
            active_id is not None
            and active_id in self._transport_identity
            and self._transport_identity[active_id] != event.transport_lifecycle_id
        )
        decision = decide_grouping(
            event,
            active,
            self.policy,
            context_changed=context_changed,
            lineage_newly_attached=self._lineage_is_new(active_id, event),
        )
        if context_changed:
            self._result.material_context_transition_count += 1
        if transport_changed and decision.action != OPEN_EPISODE:
            self._result.transport_identity_churn_ignored_count += 1

        if decision.action == OPEN_EPISODE or active is None:
            lifecycle = self._open(event, decision.next_direction_state)
            self._note_split(decision.reason)
            link_reason = "EPISODE_OPENED"
        else:
            lifecycle = self._advance(active, event, decision)
            link_reason = (
                "DIRECTION_TRANSITION_PENDING"
                if decision.action == MARK_TRANSITION_PENDING
                else "CANONICAL_ANCHOR_ATTACHED"
                if event.source_clean_block_id and not active.clean_block_count
                else "EPISODE_CONTINUED"
            )

        self._result.lifecycles[lifecycle.strategy_lifecycle_id] = lifecycle
        self._active_by_symbol[event.symbol] = lifecycle.strategy_lifecycle_id
        self._remember(lifecycle.strategy_lifecycle_id, event)
        self._result.links.append(
            StrategyLifecycleEventLink(
                strategy_lifecycle_id=lifecycle.strategy_lifecycle_id,
                pressure_event_id=event.pressure_event_id,
                transport_lifecycle_id=event.transport_lifecycle_id,
                source_clean_block_id=event.source_clean_block_id,
                source_watch_id=event.source_watch_id,
                linked_at_utc=event.event_time_utc,
                link_reason=link_reason,
            )
        )
        return lifecycle

    # ------------------------------------------------------------------

    def _open(self, event: EpisodeEvent, direction_state: DirectionState) -> StrategyLifecycleV2:
        lifecycle_id = build_strategy_lifecycle_id(
            symbol=event.symbol,
            opened_at_utc=event.event_time_utc,
            opening_direction_state=direction_state,
            rule_version=self.policy.rule_version,
        )
        return StrategyLifecycleV2(
            strategy_lifecycle_id=lifecycle_id,
            symbol=event.symbol,
            state="ANALYSIS_OPEN",
            direction_state=direction_state,
            opened_at_utc=event.event_time_utc,
            # An opening event sets all three clocks: it is by definition both
            # continuity evidence and a material change.
            last_event_at_utc=event.event_time_utc,
            last_continuity_event_at_utc=event.event_time_utc,
            last_material_event_at_utc=event.event_time_utc,
            rule_version=self.policy.rule_version,
            material_state_hash=build_material_state_hash(
                symbol=event.symbol,
                state="ANALYSIS_OPEN",
                direction_state=direction_state,
                opened_at_utc=event.event_time_utc,
                last_material_event_at_utc=event.event_time_utc,
                rule_version=self.policy.rule_version,
            ),
            event_count=1,
            clean_block_count=1 if event.source_clean_block_id else 0,
            watch_count=1 if event.source_watch_id else 0,
        )

    def _advance(
        self,
        active: StrategyLifecycleV2,
        event: EpisodeEvent,
        decision: GroupingDecision,
    ) -> StrategyLifecycleV2:
        state = active.state
        if decision.action == MARK_TRANSITION_PENDING:
            state = "TRANSITION_PENDING"
        elif decision.action == RESOLVE_TRANSITION:
            state = "ANALYSIS_OPEN"

        # Three clocks advance independently.  A material change is always also
        # continuity evidence, so the material clock can never outrun it.
        continuity_at = (
            event.event_time_utc if (decision.continuity or decision.material) else active.last_continuity_event_at_utc
        )
        material_at = event.event_time_utc if decision.material else active.last_material_event_at_utc
        direction_state = decision.next_direction_state

        return active.model_copy(
            update={
                "state": state,
                "direction_state": direction_state,
                "last_event_at_utc": max(active.last_event_at_utc, event.event_time_utc),
                "last_continuity_event_at_utc": continuity_at,
                "last_material_event_at_utc": material_at,
                "material_state_hash": build_material_state_hash(
                    symbol=active.symbol,
                    state=state,
                    direction_state=direction_state,
                    opened_at_utc=active.opened_at_utc,
                    last_material_event_at_utc=material_at,
                    rule_version=self.policy.rule_version,
                ),
                "event_count": active.event_count + 1,
                "clean_block_count": active.clean_block_count + (1 if event.source_clean_block_id else 0),
                "watch_count": active.watch_count + (1 if event.source_watch_id else 0),
            }
        )

    def _context_changed(self, active_id: str | None, event: EpisodeEvent) -> bool:
        """A context fingerprint that moved is material; a restatement is not."""
        if active_id is None or event.context_hash is None:
            return False
        previous = self._context_fingerprint.get(active_id)
        return previous is not None and previous != event.context_hash

    def _lineage_is_new(self, active_id: str | None, event: EpisodeEvent) -> bool:
        """Canonical lineage attaching for the first time is material.

        The same clean block restated on every emission is not.
        """
        if active_id is None:
            return False
        lineage = {value for value in (event.source_clean_block_id, event.source_watch_id) if value is not None}
        if not lineage:
            return False
        known = self._known_lineage.get(active_id, set())
        return bool(lineage - known)

    def _remember(self, lifecycle_id: str, event: EpisodeEvent) -> None:
        if event.context_hash is not None:
            self._context_fingerprint[lifecycle_id] = event.context_hash
        lineage = {value for value in (event.source_clean_block_id, event.source_watch_id) if value is not None}
        if lineage:
            self._known_lineage.setdefault(lifecycle_id, set()).update(lineage)
        self._transport_identity[lifecycle_id] = event.transport_lifecycle_id

    def _note_split(self, reason: str) -> None:
        self._result.split_reasons[reason] = self._result.split_reasons.get(reason, 0) + 1


def episode_event_from_payload(
    payload: Mapping[str, object],
    *,
    pressure_event_id: str,
    transport_lifecycle_id: str,
    event_time_utc,
) -> EpisodeEvent:
    """Adapt a pressure payload without coupling the reducer to its schema."""

    def _text(key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        resolved = str(value).strip()
        return resolved or None

    def _int(key: str) -> int:
        value = payload.get(key)
        if value is None or isinstance(value, bool):
            return 0
        try:
            return max(0, int(float(value)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0

    return EpisodeEvent(
        pressure_event_id=pressure_event_id,
        symbol=str(payload.get("symbol", "")).upper(),
        event_time_utc=event_time_utc,
        transport_lifecycle_id=transport_lifecycle_id,
        raw_direction=_text("raw_direction") or _text("block_direction"),
        source_clean_block_id=_text("source_clean_block_id"),
        source_watch_id=_text("source_watch_id"),
        pressure_seen=bool(payload.get("pressure_seen")),
        pair_eligible_for_analysis=bool(payload.get("pair_eligible_for_analysis")),
        allowed_quorum_reached=bool(payload.get("allowed_quorum_reached")),
        microboost_detected=bool(payload.get("microboost_detected")),
        pressure_event_count=_int("pressure_event_count"),
        context_hash=_text("material_context_hash") or _text("context_version"),
    )


__all__ = [
    "EpisodeReduction",
    "MarketEpisodeReducer",
    "episode_event_from_payload",
]
