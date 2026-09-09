"""Lifecycle V2-owned closed-candle evidence and durable shadow comparison."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from analysis.strategy_5scr_closed_candle_provider import Strategy5SCRClosedCandleEvidenceProvider
from contracts.canonical_candle import CanonicalCandle, as_utc
from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleEventLink
from contracts.strategy_5scr_pressure import Strategy5SCRMarketEvidence
from contracts.strategy_5scr_shadow_evidence_v2 import (
    SHADOW_EVIDENCE_V2_CALENDAR_VERSION,
    ShadowCandleReferenceV2,
    StrategyEvidenceComparisonV2,
    StrategyLifecycleAdmissionLinkV2,
    StrategyShadowEvidenceSnapshotV2,
)
from storage.postgres_client import PostgresClient, pg_client
from storage.strategy_5scr_candle_store import PostgresClosedCandleStore
from storage.strategy_5scr_shadow_evidence_v2_repository import (
    ShadowEvidenceWorkItemV2,
    StrategyShadowEvidenceV2Repository,
)

SHADOW_EVIDENCE_V2_LOG_PREFIX = "[Strategy5SCRShadowEvidenceOwnerV2]"
_TERMINAL_LIFECYCLE_STATES = frozenset({"TERMINAL_NO_TRADE", "INVALIDATED", "SUPERSEDED"})


def _enabled(value: str | None) -> bool:
    return str(value or "false").strip().lower() == "true"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode()).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class ShadowEvidenceV2RuntimeConfig:
    enabled: bool = False
    activation_requested: bool = False
    shadow_only: bool = True
    poll_seconds: float = 5.0
    batch_size: int = 25
    max_attempts: int = 3
    execution_enabled: bool = False
    strategy_execution_enabled: bool = False
    signed_command_bridge_enabled: bool = False
    command_producer_enabled: bool = False
    risk_reservation_enabled: bool = False
    trade_outbox_write_enabled: bool = False
    ea_command_delivery_enabled: bool = False
    legacy_push_execution_enabled: bool = False
    mt5_order_send_enabled: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ShadowEvidenceV2RuntimeConfig:
        source = os.environ if environ is None else environ
        requested = _enabled(source.get("STRATEGY_5SCR_SHADOW_EVIDENCE_V2_ENABLED"))
        config = cls(
            enabled=requested,
            activation_requested=requested,
            shadow_only=str(source.get("STRATEGY_5SCR_SHADOW_EVIDENCE_V2_SHADOW_ONLY") or "true").lower() == "true",
            poll_seconds=max(0.1, float(source.get("STRATEGY_5SCR_SHADOW_EVIDENCE_V2_POLL_SECONDS") or "5")),
            batch_size=max(1, int(source.get("STRATEGY_5SCR_SHADOW_EVIDENCE_V2_BATCH_SIZE") or "25")),
            max_attempts=max(1, int(source.get("STRATEGY_5SCR_SHADOW_EVIDENCE_V2_MAX_ATTEMPTS") or "3")),
            execution_enabled=_enabled(source.get("EXECUTION_ENABLED")),
            strategy_execution_enabled=_enabled(source.get("STRATEGY_5SCR_EXECUTION_ENABLED")),
            signed_command_bridge_enabled=_enabled(source.get("SIGNED_COMMAND_BRIDGE_ENABLED")),
            command_producer_enabled=_enabled(source.get("EXECUTION_COMMAND_PRODUCER_ENABLED")),
            risk_reservation_enabled=_enabled(source.get("RISK_RESERVATION_ENABLED")),
            trade_outbox_write_enabled=_enabled(source.get("TRADE_OUTBOX_WRITE_ENABLED")),
            ea_command_delivery_enabled=_enabled(source.get("EA_COMMAND_DELIVERY_ENABLED")),
            legacy_push_execution_enabled=_enabled(source.get("LEGACY_PUSH_EXECUTION_ENABLED")),
            mt5_order_send_enabled=_enabled(source.get("MT5_ORDER_SEND_ENABLED")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.enabled and not self.shadow_only:
            raise RuntimeError("STRATEGY_5SCR_SHADOW_EVIDENCE_V2_SHADOW_ONLY_REQUIRED")
        if self.activation_requested and self.execution_plane_active:
            raise RuntimeError("STRATEGY_5SCR_SHADOW_EVIDENCE_V2_REQUIRES_EXECUTION_OFF")

    @property
    def execution_plane_active(self) -> bool:
        return any(
            (
                self.execution_enabled,
                self.strategy_execution_enabled,
                self.signed_command_bridge_enabled,
                self.command_producer_enabled,
                self.risk_reservation_enabled,
                self.trade_outbox_write_enabled,
                self.ea_command_delivery_enabled,
                self.legacy_push_execution_enabled,
                self.mt5_order_send_enabled,
            )
        )


def admission_link_from_outbox_row(
    row: Mapping[str, Any],
    event_link: StrategyLifecycleEventLink,
) -> StrategyLifecycleAdmissionLinkV2:
    """Require raw Pair Admission lineage before an episode can own evidence."""

    raw_payload = row.get("payload")
    payload = _mapping(raw_payload)
    admitted_raw = payload.get("pair_admission_granted_at_utc")
    if not isinstance(admitted_raw, str):
        raise ValueError("PAIR_ADMISSION_GRANTED_AT_MISSING")
    try:
        admitted_at = as_utc(
            datetime.fromisoformat(admitted_raw.replace("Z", "+00:00")),
            "pair_admission_granted_at_utc",
        )
    except ValueError as exc:
        raise ValueError("PAIR_ADMISSION_GRANTED_AT_INVALID") from exc
    return StrategyLifecycleAdmissionLinkV2(
        admission_event_id=str(payload.get("pair_admission_id") or ""),
        strategy_lifecycle_id=event_link.strategy_lifecycle_id,
        pressure_event_id=event_link.pressure_event_id,
        raw_lineage_hash=str(payload.get("pair_admission_source_ledger_hash") or ""),
        admission_rule_version=str(payload.get("pair_admission_rule_version") or ""),
        admitted_at_utc=admitted_at,
        linked_at_utc=event_link.linked_at_utc,
    )


def _candle_identity(candle: CanonicalCandle) -> str:
    return _sha256(
        {
            "symbol": candle.symbol,
            "timeframe": candle.timeframe,
            "period_open": candle.open_time,
            "period_close": candle.close_time,
            "ohlc": [candle.open, candle.high, candle.low, candle.close],
            "provider": candle.provider,
            "provider_timestamp": candle.provider_timestamp,
        }
    )


def _candle_reference(candle: CanonicalCandle, decision_time: datetime) -> ShadowCandleReferenceV2:
    if not candle.is_authoritative_closed_as_of(decision_time):
        raise ValueError("STRATEGY_5SCR_V2_FORMING_OR_FUTURE_CANDLE")
    return ShadowCandleReferenceV2(
        candle_id=_candle_identity(candle),
        timeframe=candle.timeframe,  # type: ignore[arg-type]
        period_open_utc=candle.open_time,
        period_close_utc=candle.close_time,
        provider=candle.provider,
    )


def _result(evidence: Strategy5SCRMarketEvidence | None, lifecycle_state: str) -> tuple[str, str]:
    if lifecycle_state in _TERMINAL_LIFECYCLE_STATES:
        return "NO_TRADE", f"LIFECYCLE_{lifecycle_state}"
    if evidence is None:
        return "WAIT", "CLOSED_CANDLE_COVERAGE_INCOMPLETE"
    if evidence.h1 is None or not evidence.h1.structure_confirmed:
        return "WAIT", "H1_CLOSED_CONFIRMATION_PENDING"
    if evidence.m15 is None or not (
        evidence.m15.acceptance_confirmed or evidence.m15.failed_reclaim_or_retest_confirmed
    ):
        return "WAIT", "M15_CLOSED_CONFIRMATION_PENDING"
    if evidence.m1 is None:
        return "CONDITIONAL", "M1_EXECUTION_BOX_PENDING"
    return "CONDITIONAL", "SHADOW_GEOMETRY_AVAILABLE"


def _geometry_payload(evidence: Strategy5SCRMarketEvidence | None) -> dict[str, Any] | None:
    if evidence is None:
        return None
    payload = {
        "h4": None if evidence.h4 is None else evidence.h4.model_dump(mode="json"),
        "m1": None if evidence.m1 is None else evidence.m1.model_dump(mode="json"),
        "structural_sl": evidence.structural_sl,
        "pip_size": evidence.pip_size,
        "spread_price": evidence.spread_price,
    }
    return payload if any(value is not None for value in payload.values()) else None


def build_shadow_snapshot_v2(
    item: ShadowEvidenceWorkItemV2,
    evidence: Strategy5SCRMarketEvidence | None,
    *,
    decision_time: datetime,
) -> StrategyShadowEvidenceSnapshotV2:
    refs = tuple(
        sorted(
            (
                _candle_reference(candle, decision_time)
                for candle in (() if evidence is None else evidence.source_candles)
            ),
            key=lambda candle: (candle.period_close_utc, candle.timeframe, candle.candle_id),
        )
    )
    context = (
        None
        if evidence is None or evidence.context_resolution is None
        else evidence.context_resolution.model_dump(mode="json")
    )
    geometry = _geometry_payload(evidence)
    result_state, terminal_reason = _result(evidence, item.lifecycle_state)
    basis = {
        "evidence_job_id": item.evidence_job_id,
        "strategy_lifecycle_id": item.strategy_lifecycle_id,
        "admission_event_id": item.admission_event_id,
        "symbol": item.symbol,
        "decision_time_utc": decision_time,
        "provider_calendar_version": SHADOW_EVIDENCE_V2_CALENDAR_VERSION,
        "source_candle_ids": [ref.candle_id for ref in refs],
        "context": context,
        "geometry": geometry,
        "result_state": result_state,
        "terminal_reason": terminal_reason,
    }
    evidence_hash = _sha256(basis)
    return StrategyShadowEvidenceSnapshotV2(
        snapshot_id=f"5scr-evidence-v2:{evidence_hash.removeprefix('sha256:')[:32]}",
        evidence_job_id=item.evidence_job_id,
        strategy_lifecycle_id=item.strategy_lifecycle_id,
        admission_event_id=item.admission_event_id,
        symbol=item.symbol,
        decision_time_utc=decision_time,
        provider_calendar_version=SHADOW_EVIDENCE_V2_CALENDAR_VERSION,
        source_candles=refs,
        coverage_status="COMPLETE" if evidence is not None else "INCOMPLETE",
        context_hash=_sha256(context),
        evidence_hash=evidence_hash,
        result_state=result_state,  # type: ignore[arg-type]
        terminal_reason=terminal_reason,
        trade_geometry_hash=None if geometry is None else _sha256(geometry),
    )


def _legacy_candle_ids(legacy_payload: Mapping[str, Any]) -> set[str]:
    resolved: set[str] = set()
    candles = legacy_payload.get("source_candles")
    if not isinstance(candles, list):
        return resolved
    for candle in candles:
        if not isinstance(candle, Mapping):
            continue
        identity = {
            "symbol": candle.get("symbol"),
            "timeframe": candle.get("timeframe"),
            "period_open": candle.get("open_time"),
            "period_close": candle.get("close_time"),
            "ohlc": [candle.get("open"), candle.get("high"), candle.get("low"), candle.get("close")],
            "provider": candle.get("provider"),
            "provider_timestamp": candle.get("provider_timestamp"),
        }
        resolved.add(_sha256(identity))
    return resolved


def build_comparison_v2(
    item: ShadowEvidenceWorkItemV2,
    snapshot: StrategyShadowEvidenceSnapshotV2,
    *,
    grouping: Mapping[str, int],
    legacy: Mapping[str, Any] | None,
) -> StrategyEvidenceComparisonV2:
    same_grouping = int(grouping.get("transport_lifecycles", 0)) == 1
    reason_codes: list[str] = []
    if not same_grouping:
        reason_codes.append("V2_COMPRESSED_MULTIPLE_TRANSPORT_LIFECYCLES")
    same_candles: bool | None = None
    same_context: bool | None = None
    same_terminal: bool | None = None
    same_geometry: bool | None = None
    legacy_snapshot_id: str | None = None
    legacy_lifecycle_id: str | None = item.legacy_lifecycle_id
    if legacy is None:
        reason_codes.append("LEGACY_EVIDENCE_NOT_AVAILABLE")
    else:
        legacy_snapshot_id = str(legacy.get("snapshot_id") or "") or None
        legacy_lifecycle_id = str(legacy.get("lifecycle_id") or "") or legacy_lifecycle_id
        legacy_payload = _mapping(legacy.get("payload"))
        same_candles = _legacy_candle_ids(legacy_payload) == {ref.candle_id for ref in snapshot.source_candles}
        legacy_context = legacy_payload.get("context_resolution")
        same_context = _sha256(legacy_context) == snapshot.context_hash
        legacy_reason = str(legacy.get("last_error") or legacy.get("inbox_status") or "")
        same_terminal = legacy_reason == snapshot.terminal_reason
        legacy_geometry = {
            "h4": legacy_payload.get("h4"),
            "m1": legacy_payload.get("m1"),
            "structural_sl": legacy_payload.get("structural_sl"),
            "pip_size": legacy_payload.get("pip_size"),
            "spread_price": legacy_payload.get("spread_price"),
        }
        same_geometry = _sha256(legacy_geometry) == snapshot.trade_geometry_hash
        for value, code in (
            (same_candles, "CANDLE_SET_DIFFERS"),
            (same_context, "CONTEXT_HASH_DIFFERS"),
            (same_terminal, "TERMINAL_REASON_DIFFERS"),
            (same_geometry, "TRADE_GEOMETRY_DIFFERS"),
        ):
            if not value:
                reason_codes.append(code)
    digest = hashlib.sha256(f"comparison|{item.strategy_lifecycle_id}".encode()).hexdigest()[:32]
    return StrategyEvidenceComparisonV2(
        comparison_id=f"5scr-evidence-comparison-v2:{digest}",
        strategy_lifecycle_id=item.strategy_lifecycle_id,
        v2_snapshot_id=snapshot.snapshot_id,
        legacy_lifecycle_id=legacy_lifecycle_id,
        legacy_snapshot_id=legacy_snapshot_id,
        same_lifecycle_grouping=same_grouping,
        same_candle_set=same_candles,
        same_context_hash=same_context,
        same_terminal_reason=same_terminal,
        same_trade_geometry=same_geometry,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )


class StrategyShadowEvidenceV2Worker:
    """Resolve one immutable V2 snapshot per lifecycle and compare it durably."""

    def __init__(
        self,
        *,
        repository: StrategyShadowEvidenceV2Repository,
        provider: Any,
        config: ShadowEvidenceV2RuntimeConfig,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._config = config
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
                await self.process_once()
            except Exception as exc:  # pragma: no cover - defensive loop
                logger.warning("{} poll failed: {}", SHADOW_EVIDENCE_V2_LOG_PREFIX, exc)
            if self._running:
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.sleep(self._config.poll_seconds)

    async def process_once(self) -> int:
        if not self._config.enabled:
            return 0
        items = await self._repository.load_pending(limit=self._config.batch_size)
        processed = 0
        for item in items:
            try:
                requested_decision = as_utc(self._clock(), "shadow evidence V2 clock")
                decision_time = await self._repository.freeze_decision_time(
                    item.evidence_job_id,
                    requested_decision,
                )
                evidence = await self._provider.provide(
                    symbol=item.symbol,
                    decision_at_utc=decision_time,
                    lifecycle_anchor_utc=item.opened_at_utc,
                )
                snapshot = build_shadow_snapshot_v2(item, evidence, decision_time=decision_time)
                grouping = await self._repository.grouping_snapshot(item.strategy_lifecycle_id)
                legacy = await self._repository.legacy_evidence(item.pressure_event_id)
                comparison = build_comparison_v2(item, snapshot, grouping=grouping, legacy=legacy)
                await self._repository.persist_result(snapshot, comparison)
                processed += 1
            except Exception as exc:
                await self._repository.record_failure(
                    item.evidence_job_id,
                    error=str(getattr(exc, "reason_code", exc)),
                    max_attempts=self._config.max_attempts,
                )
                logger.warning(
                    "{} job={} lifecycle={} failed={}",
                    SHADOW_EVIDENCE_V2_LOG_PREFIX,
                    item.evidence_job_id,
                    item.strategy_lifecycle_id,
                    type(exc).__name__,
                )
        if processed:
            logger.info("{} {}", SHADOW_EVIDENCE_V2_LOG_PREFIX, asdict(self._config) | {"processed": processed})
        return processed


def build_shadow_evidence_v2_worker(
    *,
    pg: PostgresClient = pg_client,
    config: ShadowEvidenceV2RuntimeConfig,
) -> StrategyShadowEvidenceV2Worker:
    repository = StrategyShadowEvidenceV2Repository(pg=pg)
    provider = Strategy5SCRClosedCandleEvidenceProvider(
        PostgresClosedCandleStore(pg=pg),
        mode="SHADOW",
    )
    return StrategyShadowEvidenceV2Worker(repository=repository, provider=provider, config=config)


__all__ = [
    "SHADOW_EVIDENCE_V2_LOG_PREFIX",
    "ShadowEvidenceV2RuntimeConfig",
    "StrategyShadowEvidenceV2Worker",
    "admission_link_from_outbox_row",
    "build_comparison_v2",
    "build_shadow_evidence_v2_worker",
    "build_shadow_snapshot_v2",
]
