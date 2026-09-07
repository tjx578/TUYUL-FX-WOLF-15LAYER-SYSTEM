"""Shadow worker for mature advisory StrategyAnalysisAdmissionV1.

The worker consumes durable ``pressure_radar_events`` that canonical
PairAdmission intentionally ignores.  A qualifying advisory opens or attaches
to StrategyLifecycleV2 and queues historical closed-candle evidence.  It never
writes pressure_outbox, risk reservations, final signals or commands.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from loguru import logger

from analysis.strategy_5scr_analysis_admission import evaluate_strategy_analysis_admission
from analysis.strategy_5scr_closed_candle_provider import Strategy5SCRClosedCandleEvidenceProvider
from analysis.strategy_5scr_v3.episode_hash import build_material_state_hash
from analysis.strategy_5scr_v3.episode_policy import MarketEpisodePolicyV1
from analysis.strategy_5scr_v3.episode_reducer import MarketEpisodeReducer, episode_event_from_payload
from contracts.strategy_5scr_analysis_admission import (
    StrategyAnalysisAdmissionV1,
    StrategyAnalysisEvidenceSnapshotV1,
)
from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleEventLink
from contracts.strategy_5scr_pressure import Strategy5SCRMarketEvidence
from execution.execution_plane_flags import ExecutionPlaneFlags, parse_execution_flag
from storage.observer_export_outbox import ObserverExportOutboxRepository
from storage.postgres_client import PostgresClient, pg_client
from storage.strategy_5scr_analysis_admission_v1_repository import (
    AnalysisEvidenceWorkItemV1,
    StrategyAnalysisAdmissionV1Repository,
)
from storage.strategy_5scr_candle_store import PostgresClosedCandleStore

ANALYSIS_ADMISSION_LOG_PREFIX = "[StrategyAnalysisAdmissionV1]"


def _enabled(value: str | None) -> bool:
    return str(value or "false").strip().lower() == "true"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class StrategyAnalysisAdmissionRuntimeConfig:
    enabled: bool = False
    activation_requested: bool = False
    shadow_only: bool = True
    poll_seconds: float = 5.0
    batch_size: int = 100
    evidence_batch_size: int = 25
    evidence_max_attempts: int = 8
    max_continuity_gap_seconds: int = 900
    execution_plane_active: bool = False

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> StrategyAnalysisAdmissionRuntimeConfig:
        source = os.environ if environ is None else environ
        requested = _enabled(source.get("STRATEGY_5SCR_ANALYSIS_ADMISSION_V1_ENABLED"))
        execution_plane_active = (
            ExecutionPlaneFlags.from_env(source, strict=True).any_execution_reachable
            or parse_execution_flag(
                "STRATEGY_5SCR_EXECUTION_ENABLED",
                source.get("STRATEGY_5SCR_EXECUTION_ENABLED"),
                strict=True,
            )
        )
        config = cls(
            enabled=requested,
            activation_requested=requested,
            shadow_only=str(source.get("STRATEGY_5SCR_ANALYSIS_ADMISSION_V1_SHADOW_ONLY") or "true").lower() == "true",
            poll_seconds=max(
                0.1,
                float(source.get("STRATEGY_5SCR_ANALYSIS_ADMISSION_V1_POLL_SECONDS") or "5"),
            ),
            batch_size=max(
                1,
                int(source.get("STRATEGY_5SCR_ANALYSIS_ADMISSION_V1_BATCH_SIZE") or "100"),
            ),
            evidence_batch_size=max(
                1,
                int(source.get("STRATEGY_5SCR_ANALYSIS_ADMISSION_V1_EVIDENCE_BATCH_SIZE") or "25"),
            ),
            evidence_max_attempts=max(
                1,
                int(source.get("STRATEGY_5SCR_ANALYSIS_ADMISSION_V1_EVIDENCE_MAX_ATTEMPTS") or "8"),
            ),
            max_continuity_gap_seconds=max(
                60,
                int(source.get("STRATEGY_5SCR_LIFECYCLE_V2_MAX_CONTINUITY_GAP_SECONDS") or "900"),
            ),
            execution_plane_active=execution_plane_active,
        )
        return config

    def validate(self) -> None:
        if self.enabled and not self.shadow_only:
            raise RuntimeError("STRATEGY_5SCR_ANALYSIS_ADMISSION_V1_SHADOW_ONLY_REQUIRED")
        if self.enabled and self.execution_plane_active:
            raise RuntimeError("STRATEGY_5SCR_ANALYSIS_ADMISSION_V1_REQUIRES_EXECUTION_OFF")


class AnalysisAdmissionEvidenceProvider(Protocol):
    async def provide(
        self,
        *,
        symbol: str,
        decision_at_utc: datetime,
        lifecycle_anchor_utc: datetime,
    ) -> Strategy5SCRMarketEvidence | None: ...


def build_analysis_evidence_snapshot_v1(
    item: AnalysisEvidenceWorkItemV1,
    evidence: Strategy5SCRMarketEvidence,
    *,
    decision_time: datetime,
) -> StrategyAnalysisEvidenceSnapshotV1:
    admission = StrategyAnalysisAdmissionV1.model_validate(item.admission_payload)
    timeframes = tuple(
        dict.fromkeys(
            cast(str, candle.timeframe)
            for candle in sorted(
                evidence.source_candles,
                key=lambda value: (value.close_time, value.timeframe),
            )
        )
    )
    h1_ready = evidence.h1 is not None and evidence.h1.structure_confirmed
    m15_ready = evidence.m15 is not None and (
        evidence.m15.acceptance_confirmed or evidence.m15.failed_reclaim_or_retest_confirmed
    )
    geometry_ready = evidence.m1 is not None and evidence.structural_sl is not None
    if admission.analysis_state == "ADVISORY_WAITING_PRICE_QUALITY":
        result_state = "WAIT"
        reason = "PRICE_QUALITY_PENDING_HISTORICAL_EVIDENCE_PREFETCHED"
    elif not h1_ready:
        result_state = "WAIT"
        reason = "H1_CLOSED_CONFIRMATION_PENDING"
    elif not m15_ready:
        result_state = "WAIT"
        reason = "M15_CLOSED_CONFIRMATION_PENDING"
    elif not geometry_ready:
        result_state = "WAIT"
        reason = "M1_SHADOW_GEOMETRY_PENDING"
    else:
        result_state = "SHADOW_CANDIDATE"
        reason = "SHADOW_GEOMETRY_AVAILABLE_NO_EXECUTION_AUTHORITY"
    basis = {
        "evidence_job_id": item.evidence_job_id,
        "analysis_admission_id": item.analysis_admission_id,
        "strategy_lifecycle_id": item.strategy_lifecycle_id,
        "decision_time": decision_time,
        "source_timeframes": timeframes,
        "market_evidence": evidence.model_dump(mode="json"),
        "result_state": result_state,
        "terminal_reason": reason,
    }
    evidence_hash = _sha256(basis)
    return StrategyAnalysisEvidenceSnapshotV1(
        snapshot_id=f"5scr-analysis-evidence:{evidence_hash.removeprefix('sha256:')[:32]}",
        evidence_job_id=item.evidence_job_id,
        analysis_admission_id=item.analysis_admission_id,
        strategy_lifecycle_id=item.strategy_lifecycle_id,
        symbol=item.symbol,
        decision_time_utc=decision_time,
        source_timeframes=cast(tuple[Any, ...], timeframes),
        coverage_status="COMPLETE",
        result_state=result_state,
        terminal_reason=reason,
        evidence_hash=evidence_hash,
        shadow_tradeplan_candidate=result_state == "SHADOW_CANDIDATE",
    )


class StrategyAnalysisAdmissionV1Worker:
    """Drain advisory admission and evidence queues without execution effects."""

    def __init__(
        self,
        *,
        repository: StrategyAnalysisAdmissionV1Repository,
        provider: AnalysisAdmissionEvidenceProvider,
        config: StrategyAnalysisAdmissionRuntimeConfig,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._config = config
        self._policy = MarketEpisodePolicyV1(max_continuity_gap_seconds=config.max_continuity_gap_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._running = False

    async def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        if not self._config.enabled:
            return
        self._running = True
        while self._running:
            try:
                await self.process_admissions_once()
                await self.process_evidence_once()
            except Exception as exc:  # pragma: no cover - defensive worker loop
                logger.warning("{} poll failed: {}", ANALYSIS_ADMISSION_LOG_PREFIX, exc)
            if self._running:
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.sleep(self._config.poll_seconds)

    async def process_admissions_once(self) -> int:
        if not self._config.enabled:
            return 0
        events = await self._repository.fetch_pending_radar_events(limit=self._config.batch_size)
        processed = 0
        for event in events:
            admission = evaluate_strategy_analysis_admission(
                event.payload,
                source_pressure_event_id=event.pressure_event_id,
                observed_at_utc=event.observed_at_utc,
            )
            if admission.admission_status == "REJECTED":
                lifecycle = await self._repository.lifecycle_for_analysis_admission(admission.analysis_admission_id)
                if lifecycle is None or admission.analysis_state not in {
                    "ADVISORY_EXPIRED",
                    "ADVISORY_INVALIDATED",
                    "ADVISORY_TERMINAL_NO_TRADE",
                }:
                    await self._repository.persist_evaluation(event, admission)
                else:
                    terminal_state = (
                        "INVALIDATED" if admission.analysis_state == "ADVISORY_INVALIDATED" else "TERMINAL_NO_TRADE"
                    )
                    terminal_at = max(lifecycle.last_event_at_utc, event.observed_at_utc)
                    lifecycle = lifecycle.model_copy(
                        update={
                            "state": terminal_state,
                            "last_event_at_utc": terminal_at,
                            "last_continuity_event_at_utc": terminal_at,
                            "last_material_event_at_utc": terminal_at,
                            "material_state_hash": build_material_state_hash(
                                symbol=lifecycle.symbol,
                                state=terminal_state,
                                direction_state=lifecycle.direction_state,
                                opened_at_utc=lifecycle.opened_at_utc,
                                last_material_event_at_utc=terminal_at,
                                rule_version=lifecycle.rule_version,
                            ),
                            "event_count": lifecycle.event_count + 1,
                        }
                    )
                    event_link = StrategyLifecycleEventLink(
                        strategy_lifecycle_id=lifecycle.strategy_lifecycle_id,
                        pressure_event_id=event.pressure_event_id,
                        transport_lifecycle_id=str(
                            event.payload.get("lifecycle_id")
                            or event.payload.get("cluster_id")
                            or admission.analysis_admission_id
                        ),
                        source_clean_block_id=(
                            str(event.payload["source_clean_block_id"])
                            if event.payload.get("source_clean_block_id")
                            else None
                        ),
                        source_watch_id=(
                            str(event.payload["source_watch_id"]) if event.payload.get("source_watch_id") else None
                        ),
                        linked_at_utc=event.observed_at_utc,
                        link_reason="EPISODE_CONTINUED",
                    )
                    await self._repository.persist_evaluation(
                        event,
                        admission,
                        lifecycle=lifecycle,
                        event_link=event_link,
                    )
                processed += 1
                continue

            recovered = await self._repository.active_recovery_state(event.symbol)
            reducer = MarketEpisodeReducer(policy=self._policy)
            if recovered is not None:
                reducer.seed_active(
                    recovered.lifecycle,
                    known_lineage=recovered.known_lineage,
                    context_hash=recovered.context_hash,
                    transport_lifecycle_id=recovered.transport_lifecycle_id,
                )
            episode_event = episode_event_from_payload(
                event.payload,
                pressure_event_id=event.pressure_event_id,
                transport_lifecycle_id=str(
                    event.payload.get("lifecycle_id")
                    or event.payload.get("cluster_id")
                    or admission.analysis_admission_id
                ),
                event_time_utc=event.observed_at_utc,
            )
            lifecycle = reducer.ingest(episode_event)
            if admission.direction_lineage_alignment == "CONFLICT":
                lifecycle = lifecycle.model_copy(
                    update={
                        "state": "TRANSITION_PENDING",
                        "direction_state": "CONFLICT",
                        "material_state_hash": build_material_state_hash(
                            symbol=lifecycle.symbol,
                            state="TRANSITION_PENDING",
                            direction_state="CONFLICT",
                            opened_at_utc=lifecycle.opened_at_utc,
                            last_material_event_at_utc=lifecycle.last_material_event_at_utc,
                            rule_version=lifecycle.rule_version,
                        ),
                    }
                )
            await self._repository.persist_evaluation(
                event,
                admission,
                lifecycle=lifecycle,
                event_link=reducer.result.links[-1],
            )
            processed += 1
        return processed

    async def process_evidence_once(self) -> int:
        if not self._config.enabled:
            return 0
        items = await self._repository.load_pending_evidence(limit=self._config.evidence_batch_size)
        processed = 0
        for item in items:
            try:
                requested_at = self._clock().astimezone(UTC)
                decision_time = await self._repository.freeze_decision_time(
                    item.evidence_job_id,
                    requested_at,
                )
                evidence = await self._provider.provide(
                    symbol=item.symbol,
                    decision_at_utc=decision_time,
                    lifecycle_anchor_utc=item.opened_at_utc,
                )
                if evidence is None:
                    await self._repository.record_evidence_failure(
                        item.evidence_job_id,
                        error="STRATEGY_ANALYSIS_CLOSED_CANDLE_EVIDENCE_INCOMPLETE",
                        max_attempts=self._config.evidence_max_attempts,
                    )
                else:
                    snapshot = build_analysis_evidence_snapshot_v1(
                        item,
                        evidence,
                        decision_time=decision_time,
                    )
                    await self._repository.persist_snapshot(snapshot)
                processed += 1
            except Exception as exc:
                await self._repository.record_evidence_failure(
                    item.evidence_job_id,
                    error=str(getattr(exc, "reason_code", exc)),
                    max_attempts=self._config.evidence_max_attempts,
                )
                logger.warning(
                    "{} evidence job={} lifecycle={} failed={}",
                    ANALYSIS_ADMISSION_LOG_PREFIX,
                    item.evidence_job_id,
                    item.strategy_lifecycle_id,
                    type(exc).__name__,
                )
                processed += 1
        return processed


def build_strategy_analysis_admission_v1_worker(
    *,
    pg: PostgresClient = pg_client,
    config: StrategyAnalysisAdmissionRuntimeConfig,
) -> StrategyAnalysisAdmissionV1Worker:
    provider = Strategy5SCRClosedCandleEvidenceProvider(
        PostgresClosedCandleStore(pg=pg),
        mode="SHADOW",
    )
    observer_export = ObserverExportOutboxRepository(pg=pg)
    return StrategyAnalysisAdmissionV1Worker(
        repository=StrategyAnalysisAdmissionV1Repository(
            pg=pg,
            observer_export_repository=observer_export,
        ),
        provider=provider,
        config=config,
    )


__all__ = [
    "ANALYSIS_ADMISSION_LOG_PREFIX",
    "AnalysisAdmissionEvidenceProvider",
    "StrategyAnalysisAdmissionRuntimeConfig",
    "StrategyAnalysisAdmissionV1Worker",
    "build_analysis_evidence_snapshot_v1",
    "build_strategy_analysis_admission_v1_worker",
]
