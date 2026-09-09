"""Shadow worker that folds LIVE pressure events into market episodes.

Hosted inside ``wolf15-pressure-outbox`` because that service is already the
active pressure consumer; a dedicated analysis service can come later, once the
episode semantics have proven themselves.

Strictly observational.  The worker reads pressure events, writes the two new
V2 tables and reports metrics.  It never routes pressure, never changes
``WAITING_EVIDENCE``, never touches a tradeplan, risk reservation, final
direction or command.  With the feature flag off -- the default -- it does
nothing at all.

Restart safety comes from the repository: the active episode is recovered from
the database, so restarting mid-episode continues it instead of forking it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from loguru import logger

from analysis.strategy_5scr_v3.episode_grouping import (
    MARK_TRANSITION_PENDING,
    OPEN_EPISODE,
    RESOLVE_TRANSITION,
    EpisodeEvent,
    decide_grouping,
)
from analysis.strategy_5scr_v3.episode_policy import (
    MarketEpisodePolicyV1,
    episode_dual_write_enabled,
    episode_lifecycle_v2_enabled,
    episode_metrics_enabled,
    episode_shadow_only,
    resolve_episode_policy,
)
from analysis.strategy_5scr_v3.episode_reducer import MarketEpisodeReducer
from contracts.strategy_5scr_lifecycle_v2 import (
    StrategyLifecycleEventLink,
    StrategyLifecycleV2,
)
from services.pressure_outbox.shadow_evidence_v2_worker import admission_link_from_outbox_row
from storage.observer_export_outbox import ObserverExportOutboxRepository
from storage.strategy_5scr_lifecycle_v2_repository import StrategyLifecycleV2Repository
from storage.strategy_5scr_shadow_evidence_v2_repository import StrategyShadowEvidenceV2Repository

SHADOW_LOG_PREFIX = "[Strategy5SCRLifecycleV2Shadow]"


@dataclass(frozen=True)
class _RecoveredEpisode:
    lifecycle: StrategyLifecycleV2
    known_lineage: tuple[str, ...] = ()
    context_hash: str | None = None
    transport_lifecycle_id: str | None = None


async def _recover_episode(repository: Any, symbol: str) -> _RecoveredEpisode | None:
    recover = cast(
        Callable[[str], Awaitable[Any]] | None,
        getattr(repository, "active_recovery_state", None),
    )
    if callable(recover):
        state = await recover(symbol)
        if state is not None:
            return _RecoveredEpisode(
                lifecycle=state.lifecycle,
                known_lineage=tuple(state.known_lineage),
                context_hash=state.context_hash,
                transport_lifecycle_id=state.transport_lifecycle_id,
            )
    active = await repository.active_lifecycle(symbol)
    return None if active is None else _RecoveredEpisode(lifecycle=active)


def _flag(value: str | None) -> bool:
    return str(value or "false").strip().lower() == "true"


@dataclass(frozen=True)
class LifecycleV2RuntimeConfig:
    """Rollout configuration for the episode-lifecycle shadow worker."""

    enabled: bool = False
    shadow_only: bool = True
    dual_write_enabled: bool = False
    evidence_owner_writer_enabled: bool = False
    metrics_enabled: bool = True
    max_continuity_gap_seconds: int = 900
    poll_seconds: float = 5.0
    batch_size: int = 100

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> LifecycleV2RuntimeConfig:
        source = os.environ if environ is None else environ
        raw_gap = str(source.get("STRATEGY_5SCR_LIFECYCLE_V2_MAX_CONTINUITY_GAP_SECONDS") or "900")
        try:
            gap = int(raw_gap)
        except (TypeError, ValueError) as exc:
            raise ValueError("STRATEGY_5SCR_LIFECYCLE_V2_MAX_CONTINUITY_GAP_SECONDS must be an integer") from exc
        return cls(
            enabled=_flag(source.get("STRATEGY_5SCR_LIFECYCLE_V2_ENABLED")),
            # Shadow-only is the safe default, so it defaults ON.
            shadow_only=str(source.get("STRATEGY_5SCR_LIFECYCLE_V2_SHADOW_ONLY") or "true").strip().lower() == "true",
            dual_write_enabled=_flag(source.get("STRATEGY_5SCR_LIFECYCLE_V2_DUAL_WRITE_ENABLED")),
            evidence_owner_writer_enabled=_flag(source.get("STRATEGY_5SCR_LIFECYCLE_V2_EVIDENCE_OWNER_WRITER_ENABLED")),
            metrics_enabled=str(source.get("STRATEGY_5SCR_LIFECYCLE_V2_METRICS_ENABLED") or "true").strip().lower()
            == "true",
            max_continuity_gap_seconds=gap,
            poll_seconds=float(source.get("STRATEGY_5SCR_LIFECYCLE_V2_POLL_SECONDS") or "5"),
            batch_size=int(source.get("STRATEGY_5SCR_LIFECYCLE_V2_BATCH_SIZE") or "100"),
        )


class LifecycleShadowWorker:
    """Fold pressure events into durable episodes, without side effects."""

    def __init__(
        self,
        *,
        repository: StrategyLifecycleV2Repository | None = None,
        policy: MarketEpisodePolicyV1 | None = None,
    ) -> None:
        self._repository = repository or StrategyLifecycleV2Repository()
        self._policy = policy or resolve_episode_policy()

    @property
    def enabled(self) -> bool:
        return episode_lifecycle_v2_enabled()

    async def process_event(self, event: EpisodeEvent) -> StrategyLifecycleV2 | None:
        """Fold one event.  Returns ``None`` when the worker is disabled."""
        if not self.enabled:
            return None
        if not episode_shadow_only():
            # Phase one has no non-shadow mode; refuse rather than guess.
            logger.warning(
                "{} refusing to run: shadow_only is false in phase one",
                SHADOW_LOG_PREFIX,
            )
            return None

        recovered = await _recover_episode(self._repository, event.symbol)
        active = None if recovered is None else recovered.lifecycle
        decision = decide_grouping(event, active, self._policy)

        reducer = MarketEpisodeReducer(policy=self._policy)
        if active is not None and decision.action != OPEN_EPISODE:
            # Resume the recovered episode so a restart continues it rather
            # than opening a duplicate.
            reducer.seed_active(
                active,
                known_lineage=() if recovered is None else recovered.known_lineage,
                context_hash=None if recovered is None else recovered.context_hash,
                transport_lifecycle_id=(None if recovered is None else recovered.transport_lifecycle_id),
            )
        lifecycle = reducer.ingest(event)
        link = reducer.result.links[-1]

        if episode_dual_write_enabled():
            await self._repository.persist(lifecycle, link)

        if episode_metrics_enabled():
            self._emit(lifecycle, link, decision.action)
        return lifecycle

    async def process_batch(self, events: Iterable[EpisodeEvent]) -> dict[str, Any]:
        """Fold a batch and return a shadow-metrics summary."""
        if not self.enabled:
            return {"enabled": False}

        reducer = MarketEpisodeReducer(policy=self._policy)
        reduction = reducer.ingest_many(events)

        if episode_dual_write_enabled():
            for link in reduction.links:
                lifecycle = reduction.lifecycles[link.strategy_lifecycle_id]
                await self._repository.persist(lifecycle, link)

        summary = {
            "enabled": True,
            "shadow_only": episode_shadow_only(),
            "rule_version": self._policy.rule_version,
            "max_continuity_gap_seconds": self._policy.max_continuity_gap_seconds,
            "pressure_events_total": len(reduction.links),
            "strategy_lifecycles_v2_total": len(reduction.lifecycles),
            "lifecycle_v2_compression_ratio": (
                round(reduction.compression_ratio, 4) if reduction.compression_ratio else None
            ),
            "duplicate_event_total": reduction.duplicate_event_count,
            "continuity_gap_split_total": reduction.split_reasons.get("CONTINUITY_GAP_EXCEEDED", 0),
            "hard_reset_split_total": reduction.split_reasons.get("HARD_CONTEXT_RESET", 0),
            "terminal_split_total": reduction.split_reasons.get("TERMINAL_LIFECYCLE", 0),
            "direction_conflict_total": sum(
                1 for item in reduction.lifecycles.values() if item.direction_state == "CONFLICT"
            ),
            "execution_impact": False,
        }
        if episode_metrics_enabled():
            logger.warning("{} {}", SHADOW_LOG_PREFIX, summary)
        return summary

    def _emit(
        self,
        lifecycle: StrategyLifecycleV2,
        link: StrategyLifecycleEventLink,
        action: str,
    ) -> None:
        logger.warning(
            "{} {}",
            SHADOW_LOG_PREFIX,
            {
                "event": "strategy_5scr_lifecycle_v2_shadow",
                "action": action,
                "strategy_lifecycle_id": lifecycle.strategy_lifecycle_id,
                "transport_lifecycle_id": link.transport_lifecycle_id,
                "symbol": lifecycle.symbol,
                "state": lifecycle.state,
                "direction_state": lifecycle.direction_state,
                "event_count": lifecycle.event_count,
                "clean_block_count": lifecycle.clean_block_count,
                "transition_pending": action == MARK_TRANSITION_PENDING,
                "transition_resolved": action == RESOLVE_TRANSITION,
                "rule_version": lifecycle.rule_version,
                "execution_authority": False,
                "execution_impact": False,
                "advisory_only": True,
            },
        )


class LifecycleV2ShadowRunner:
    """Poll delivered pressure events and fold them into episodes.

    A peer worker alongside the dispatcher, evidence and outcome workers.  It
    takes no lease on ``pressure_outbox`` and mutates no existing status, so it
    cannot steal delivery from the primary consumer.

    Restart ordering matters: the active episode for a symbol is recovered
    *before* that symbol's first post-restart event is folded.  Polling first
    would let the first event open a duplicate episode while the previous one
    was still being loaded.
    """

    def __init__(
        self,
        *,
        repository: StrategyLifecycleV2Repository,
        config: LifecycleV2RuntimeConfig,
        owner_repository: StrategyShadowEvidenceV2Repository | None = None,
    ) -> None:
        self._repository = repository
        self._config = config
        self._owner_repository = owner_repository
        self._policy = MarketEpisodePolicyV1(max_continuity_gap_seconds=config.max_continuity_gap_seconds)
        self._running = False
        #: Episodes already recovered from the database this run.
        self._recovered_symbols: set[str] = set()
        self._reducer = MarketEpisodeReducer(policy=self._policy)

    async def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        if not self._config.enabled:
            return
        if not self._config.shadow_only:
            raise RuntimeError("STRATEGY_5SCR_LIFECYCLE_V2_SHADOW_ONLY_REQUIRED")

        self._running = True
        logger.info(
            "{} started dual_write={} gap={}s",
            SHADOW_LOG_PREFIX,
            self._config.dual_write_enabled,
            self._config.max_continuity_gap_seconds,
        )
        while self._running:
            try:
                await self.poll_once()
            except Exception as exc:  # pragma: no cover - defensive worker loop
                logger.warning("{} poll failed: {}", SHADOW_LOG_PREFIX, exc)
            if not self._running:
                break
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(self._config.poll_seconds)

    async def poll_once(self) -> int:
        """Fold one batch of not-yet-linked events.  Returns the count."""
        rows = await self._repository.fetch_unlinked_events(limit=self._config.batch_size)
        if not rows:
            return 0

        for row in rows:
            event = episode_event_from_outbox_row(row)
            await self._recover_symbol(event.symbol)
            lifecycle = self._reducer.ingest(event)
            link = self._reducer.result.links[-1]
            if self._config.dual_write_enabled:
                if self._config.evidence_owner_writer_enabled:
                    if self._owner_repository is None:
                        raise RuntimeError("STRATEGY_5SCR_EVIDENCE_OWNER_REPOSITORY_REQUIRED")
                    admission_link = admission_link_from_outbox_row(row, link)
                    await self._owner_repository.persist_owner_bundle(
                        lifecycle,
                        link,
                        admission_link,
                    )
                else:
                    await self._repository.persist(lifecycle, link)

        if self._config.metrics_enabled:
            logger.warning(
                "{} {}",
                SHADOW_LOG_PREFIX,
                {
                    "event": "strategy_5scr_lifecycle_v2_batch",
                    "processed": len(rows),
                    "strategy_lifecycles_v2_total": len(self._reducer.result.lifecycles),
                    "lifecycle_split_reasons": dict(sorted(self._reducer.result.split_reasons.items())),
                    "material_context_transition_count": (self._reducer.result.material_context_transition_count),
                    "transport_identity_churn_ignored_count": (
                        self._reducer.result.transport_identity_churn_ignored_count
                    ),
                    "duplicate_event_count": self._reducer.result.duplicate_event_count,
                    "event_to_lifecycle_compression_ratio": self._reducer.result.compression_ratio,
                    "dual_write": self._config.dual_write_enabled,
                    "execution_impact": False,
                    "advisory_only": True,
                },
            )
        return len(rows)

    async def _recover_symbol(self, symbol: str) -> None:
        """Seed the reducer from durable state the first time we see a symbol."""
        if symbol in self._recovered_symbols:
            return
        self._recovered_symbols.add(symbol)
        recovered = await _recover_episode(self._repository, symbol)
        if recovered is not None:
            self._reducer.seed_active(
                recovered.lifecycle,
                known_lineage=recovered.known_lineage,
                context_hash=recovered.context_hash,
                transport_lifecycle_id=recovered.transport_lifecycle_id,
            )


def build_lifecycle_v2_shadow_runner(
    *,
    pg: Any,
    config: LifecycleV2RuntimeConfig,
) -> LifecycleV2ShadowRunner:
    observer_export = ObserverExportOutboxRepository(pg=pg)
    return LifecycleV2ShadowRunner(
        repository=StrategyLifecycleV2Repository(
            pg=pg,
            observer_export_repository=observer_export,
        ),
        config=config,
        owner_repository=(
            StrategyShadowEvidenceV2Repository(
                pg=pg,
                observer_export_repository=observer_export,
            )
            if config.evidence_owner_writer_enabled
            else None
        ),
    )


def episode_event_from_outbox_row(
    row: Mapping[str, Any],
    *,
    payload: Mapping[str, Any] | str | bytes | bytearray | memoryview | None = None,
) -> EpisodeEvent:
    """Adapt one ``pressure_outbox`` row into an episode event.

    Transport identity is carried through untouched; it is lineage, not
    identity, for the episode layer.
    """
    raw_body = payload if payload is not None else row.get("payload")
    if raw_body is None:
        body: Mapping[str, Any] = {}
    elif isinstance(raw_body, Mapping):
        body = raw_body
    else:
        serialized = raw_body.tobytes() if isinstance(raw_body, memoryview) else raw_body
        if not isinstance(serialized, (str, bytes, bytearray)):
            raise ValueError("pressure outbox row payload must be a JSON object")
        try:
            decoded = json.loads(serialized)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("pressure outbox row payload must be valid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise ValueError("pressure outbox row payload must decode to a JSON object")
        body = decoded

    def _text(key: str) -> str | None:
        value = body.get(key) if key in body else row.get(key)
        if value is None:
            return None
        resolved = str(value).strip()
        return resolved or None

    signal_valid_at = row.get("signal_valid_at")
    if not isinstance(signal_valid_at, datetime):
        raise ValueError("pressure outbox row requires a signal_valid_at timestamp")

    def _int(key: str) -> int:
        value = body.get(key)
        if value is None or isinstance(value, bool):
            return 0
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return 0

    return EpisodeEvent(
        pressure_event_id=str(row.get("event_id")),
        symbol=str(row.get("symbol", "")).upper(),
        event_time_utc=signal_valid_at,
        transport_lifecycle_id=str(row.get("lifecycle_id")),
        raw_direction=_text("raw_direction") or _text("block_direction"),
        source_clean_block_id=_text("source_clean_block_id"),
        source_watch_id=_text("source_watch_id"),
        # Continuity evidence: without these the event reads as a heartbeat and
        # could not sustain an episode.
        pressure_seen=bool(body.get("pressure_seen")),
        pair_eligible_for_analysis=bool(body.get("pair_eligible_for_analysis")),
        allowed_quorum_reached=bool(body.get("allowed_quorum_reached")),
        microboost_detected=bool(body.get("microboost_detected")),
        pressure_event_count=_int("pressure_event_count"),
        context_hash=_text("material_context_hash") or _text("context_version"),
    )


__all__ = [
    "SHADOW_LOG_PREFIX",
    "LifecycleShadowWorker",
    "LifecycleV2RuntimeConfig",
    "LifecycleV2ShadowRunner",
    "build_lifecycle_v2_shadow_runner",
    "episode_event_from_outbox_row",
]
