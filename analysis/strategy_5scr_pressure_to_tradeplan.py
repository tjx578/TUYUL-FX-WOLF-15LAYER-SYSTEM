"""Pressure-log normalization, lifecycle aggregation, and 5S-CR tradeplan assembly.

This module is a pure analysis boundary.  It consumes
``SignalPressureStateJSON`` plus already-resolved closed-candle evidence and
returns a non-executable tradeplan candidate.  It never reserves risk, emits a
final ``signal_json``, enqueues an MT5 command, or performs a broker side effect.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from contracts.strategy_5scr import (
    CONFIRMATION_POLICY,
    STRATEGY_MODEL,
    STRATEGY_OOS_STATUS,
    STRATEGY_RULE_STATUS,
    STRATEGY_RULE_VERSION,
    STRATEGY_VALIDATION_STATUS,
    PressureAuthority,
    RiskAuthority,
    Strategy5SCRProof,
    evaluate_strategy_5scr_proof,
)
from contracts.strategy_5scr_execution_policy import (
    EXECUTION_POLICY_MISSING_REASON,
    ExecutionPolicy,
    resolve_execution_policy,
)
from contracts.strategy_5scr_pressure import (
    CampaignAnchorSource,
    LegacyEpisodePolicy,
    PressureEvent,
    PressureInputMode,
    PressureLifecycle,
    PressureTradePlanBuildResult,
    Strategy5SCRMarketEvidence,
    Strategy5SCRTradePlan,
    TradeDirection,
)
from contracts.strategy_5scr_pressure_outbox import PressureOutboxEnvelope

PRESSURE_LOG_PREFIX = "[SignalPressureStateJSON]"
MIN_RR = 1.5

_RUNTIME_IDENTITY_FIELDS = frozenset(
    {
        "deployment_id",
        "commit_sha",
        "replica_id",
        "generated_at_utc",
    }
)
_TRANSPORT_IDENTITY_FIELDS = frozenset(
    {
        "event_id",
        "lifecycle_id",
        "lifecycle_sequence",
        "pressure_outbox_id",
    }
)


class PressureInputError(ValueError):
    """Raised when a pressure record violates the non-executable input contract."""


class PressureLifecycleOrderError(ValueError):
    """Raised when an event would rewrite an already-observed lifecycle past."""


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256_tag(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        parsed = datetime.fromtimestamp(timestamp, tz=UTC)
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    resolved = str(value).strip()
    return resolved or None


def _positive_float(*values: Any) -> float | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            return number
    return None


def _non_negative_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _extract_payload(record: Mapping[str, Any] | str) -> tuple[dict[str, Any], Any]:
    outer_timestamp: Any = None
    if isinstance(record, Mapping):
        outer_timestamp = record.get("timestamp")
        if str(record.get("event") or "").lower() == "signal_pressure_state_json":
            return dict(record), outer_timestamp
        raw = record.get("message")
        if not isinstance(raw, str):
            raise PressureInputError("PRESSURE_RECORD_MESSAGE_MISSING")
    elif isinstance(record, str):
        raw = record
    else:
        raise PressureInputError("PRESSURE_RECORD_TYPE_UNSUPPORTED")

    if PRESSURE_LOG_PREFIX in raw:
        raw = raw.split(PRESSURE_LOG_PREFIX, 1)[1].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PressureInputError("PRESSURE_RECORD_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise PressureInputError("PRESSURE_RECORD_PAYLOAD_NOT_OBJECT")
    return payload, outer_timestamp


class PressureEventNormalizer:
    """Normalize current or legacy pressure payloads into one immutable event."""

    def __init__(self, *, input_mode: PressureInputMode) -> None:
        self.input_mode: PressureInputMode = input_mode

    def normalize(self, record: Mapping[str, Any] | str) -> PressureEvent:
        payload, outer_timestamp = _extract_payload(record)
        event_name = str(payload.get("event") or "").lower()
        if event_name != "signal_pressure_state_json":
            raise PressureInputError("PRESSURE_EVENT_NAME_INVALID")
        self._validate_non_executable(payload)

        symbol = str(payload.get("symbol") or "").strip().upper()
        if not symbol:
            raise PressureInputError("PRESSURE_SYMBOL_MISSING")
        event_time, event_time_source = self._resolve_event_time(payload, outer_timestamp)
        cluster_id = _text(payload.get("cluster_id")) or _text(payload.get("pending_decision_id"))
        if cluster_id is None:
            cluster_id = f"legacy:{symbol}:{event_time.isoformat()}"

        clean_block_id = _text(payload.get("source_clean_block_id"))
        source_watch_id = _text(payload.get("source_watch_id"))
        canonical_lifecycle_id = _text(payload.get("lifecycle_id"))
        if clean_block_id:
            campaign_anchor = canonical_lifecycle_id or clean_block_id
            anchor_source: CampaignAnchorSource = "SOURCE_CLEAN_BLOCK_ID"
            anchor_execution_grade = True
        elif source_watch_id:
            campaign_anchor = canonical_lifecycle_id or source_watch_id
            anchor_source = "SOURCE_WATCH_ID"
            anchor_execution_grade = True
        else:
            campaign_anchor = None
            anchor_source = "UNRESOLVED"
            anchor_execution_grade = False
        anchor_at = _parse_datetime(payload.get("lifecycle_anchor_at_utc"))
        selection_confirmed = payload.get("pressure_selection_confirmed") is True
        if selection_confirmed and not (
            str(payload.get("radar_status") or "").upper() == "ANALYSIS_READY"
            and _text(payload.get("radar_manifest_id")) is not None
            and clean_block_id is not None
        ):
            raise PressureInputError("PRESSURE_SELECTION_PROOF_INVALID")

        raw_direction_text = str(payload.get("raw_direction") or "").upper()
        raw_direction: TradeDirection | None = (
            cast(TradeDirection, raw_direction_text) if raw_direction_text in {"BUY", "SELL"} else None
        )
        allowed_quorum = payload.get("allowed_quorum")
        allowed_quorum_reached = bool(
            isinstance(allowed_quorum, Mapping) and allowed_quorum.get("quorum_reached") is True
        )
        htf = payload.get("htf_structure_context")
        semantic_payload = {
            key: value
            for key, value in payload.items()
            if key not in (_RUNTIME_IDENTITY_FIELDS | _TRANSPORT_IDENTITY_FIELDS)
        }
        canonical_event_id = _text(payload.get("event_id"))
        if canonical_event_id is not None:
            try:
                canonical_event_id = str(UUID(canonical_event_id))
            except ValueError as exc:
                raise PressureInputError("PRESSURE_EVENT_ID_INVALID") from exc

        return PressureEvent(
            event_id=canonical_event_id or _sha256_tag(semantic_payload),
            source_hash=_sha256_tag(payload),
            input_mode=self.input_mode,
            schema_version=str(payload.get("schema_version") or "legacy-unversioned"),
            symbol=symbol,
            event_time_utc=event_time,
            event_time_source=event_time_source,
            cluster_id=cluster_id,
            campaign_anchor=campaign_anchor,
            campaign_anchor_at_utc=anchor_at,
            campaign_anchor_source=anchor_source,
            campaign_anchor_execution_grade=anchor_execution_grade,
            raw_direction=raw_direction,
            pressure_seen=payload.get("pressure_seen") is not False,
            pair_eligible_for_analysis=payload.get("pair_eligible_for_analysis") is True,
            allowed_quorum_reached=allowed_quorum_reached,
            pressure_selection_confirmed=selection_confirmed,
            pressure_event_count=_non_negative_int(payload.get("pressure_event_count")),
            pressure_level=_text(payload.get("pressure_level")),
            pressure_strength=_text(payload.get("pressure_strength")),
            reference_price=_positive_float(
                payload.get("observed_price"),
                payload.get("reference_price"),
                payload.get("entry_reference_price"),
                payload.get("signal_valid_price"),
            ),
            reference_price_source=_text(
                payload.get("observed_price_source")
                or payload.get("reference_price_source")
                or payload.get("price_source")
            ),
            htf_structure_context=dict(htf) if isinstance(htf, Mapping) else {},
        )

    def normalize_many(self, records: Iterable[Mapping[str, Any] | str]) -> list[PressureEvent]:
        events = [self.normalize(record) for record in records]
        events.sort(key=lambda event: (event.event_time_utc, event.event_id))
        return events

    @staticmethod
    def _validate_non_executable(payload: Mapping[str, Any]) -> None:
        if any(
            payload.get(field) is True for field in ("valid_for_execution", "execution_valid_now", "is_final_signal")
        ):
            raise PressureInputError("PRESSURE_EVENT_EXECUTION_FLAG_TRUE")
        final_direction = str(payload.get("final_direction") or "WAIT").upper()
        if final_direction != "WAIT":
            raise PressureInputError("PRESSURE_EVENT_FINAL_DIRECTION_NOT_WAIT")
        promotion_stage = str(payload.get("promotion_stage") or "PRESSURE_ONLY").upper()
        if promotion_stage != "PRESSURE_ONLY":
            raise PressureInputError("PRESSURE_EVENT_PROMOTION_STAGE_INVALID")

    @staticmethod
    def _resolve_event_time(payload: Mapping[str, Any], outer_timestamp: Any) -> tuple[datetime, str]:
        candidates = (
            ("signal_valid_time_utc", payload.get("signal_valid_time_utc")),
            ("observed_price_time", payload.get("observed_price_time")),
            ("price_snapshot_time_utc", payload.get("price_snapshot_time_utc")),
            ("outer_railway_timestamp", outer_timestamp),
            ("generated_at_utc", payload.get("generated_at_utc")),
        )
        for source, value in candidates:
            parsed = _parse_datetime(value)
            if parsed is not None:
                return parsed, source
        raise PressureInputError("PRESSURE_EVENT_TIME_MISSING_OR_INVALID")


class PressureLifecycleAccumulator:
    """Deduplicate pressure events and build stable campaign lifecycles."""

    def __init__(self, *, legacy_policy: LegacyEpisodePolicy | None = None) -> None:
        self.legacy_policy = legacy_policy or LegacyEpisodePolicy()
        self._seen_event_ids: set[str] = set()
        self._lifecycles: dict[str, PressureLifecycle] = {}
        self._active_legacy: dict[tuple[str, str], str] = {}

    def ingest(self, event: PressureEvent) -> tuple[PressureLifecycle, bool]:
        if event.event_id in self._seen_event_ids:
            lifecycle = self._find_lifecycle_for_event(event.event_id)
            if lifecycle is None:  # pragma: no cover - defensive corruption guard
                raise PressureInputError("PRESSURE_DEDUP_INDEX_CORRUPT")
            return lifecycle, True

        campaign_id, anchor_source, execution_grade, grouping_rule = self._resolve_campaign(event)
        current = self._lifecycles.get(campaign_id)
        if current is not None and event.event_time_utc < current.updated_at_utc:
            raise PressureLifecycleOrderError("PRESSURE_EVENT_OUT_OF_ORDER")

        if current is None:
            started_at = event.campaign_anchor_at_utc or event.event_time_utc
            lifecycle = PressureLifecycle(
                campaign_id=campaign_id,
                campaign_anchor_source=anchor_source,
                campaign_anchor_execution_grade=execution_grade,
                input_mode=event.input_mode,
                symbol=event.symbol,
                raw_direction=event.raw_direction,
                started_at_utc=started_at,
                updated_at_utc=event.event_time_utc,
                event_ids=(event.event_id,),
                latest_cluster_id=event.cluster_id,
                selected_by_pressure=(
                    event.pair_eligible_for_analysis
                    or event.allowed_quorum_reached
                    or event.pressure_selection_confirmed
                ),
                max_reported_pressure_count=event.pressure_event_count,
                latest_pressure_level=event.pressure_level,
                latest_pressure_strength=event.pressure_strength,
                latest_reference_price=event.reference_price,
                latest_htf_structure_context=event.htf_structure_context,
                legacy_grouping_rule_version=grouping_rule,
            )
        else:
            if current.symbol != event.symbol or current.input_mode != event.input_mode:
                raise PressureInputError("PRESSURE_CAMPAIGN_ID_COLLISION")
            raw_direction = current.raw_direction if current.raw_direction == event.raw_direction else None
            lifecycle = current.model_copy(
                update={
                    "raw_direction": raw_direction,
                    "updated_at_utc": event.event_time_utc,
                    "event_ids": (*current.event_ids, event.event_id),
                    "latest_cluster_id": event.cluster_id,
                    "selected_by_pressure": (
                        current.selected_by_pressure
                        or event.pair_eligible_for_analysis
                        or event.allowed_quorum_reached
                        or event.pressure_selection_confirmed
                    ),
                    "max_reported_pressure_count": max(
                        current.max_reported_pressure_count,
                        event.pressure_event_count,
                    ),
                    "latest_pressure_level": event.pressure_level or current.latest_pressure_level,
                    "latest_pressure_strength": event.pressure_strength or current.latest_pressure_strength,
                    "latest_reference_price": event.reference_price or current.latest_reference_price,
                    "latest_htf_structure_context": (
                        event.htf_structure_context or current.latest_htf_structure_context
                    ),
                }
            )
        self._lifecycles[campaign_id] = lifecycle
        self._seen_event_ids.add(event.event_id)
        return lifecycle, False

    def ingest_many(self, events: Iterable[PressureEvent]) -> list[PressureLifecycle]:
        for event in sorted(events, key=lambda item: (item.event_time_utc, item.event_id)):
            self.ingest(event)
        return self.snapshots()

    def snapshots(self) -> list[PressureLifecycle]:
        return sorted(self._lifecycles.values(), key=lambda item: (item.started_at_utc, item.campaign_id))

    def _resolve_campaign(
        self,
        event: PressureEvent,
    ) -> tuple[str, CampaignAnchorSource, bool, str | None]:
        if event.campaign_anchor is not None:
            return (
                event.campaign_anchor,
                event.campaign_anchor_source,
                event.campaign_anchor_execution_grade,
                None,
            )
        if event.input_mode == "LIVE":
            return f"unresolved:{event.symbol}:{event.cluster_id}", "UNRESOLVED", False, None

        direction_key = event.raw_direction or "WAIT"
        active_key = (event.symbol, direction_key)
        active_campaign = self._active_legacy.get(active_key)
        if active_campaign is not None:
            active = self._lifecycles[active_campaign]
            gap = (event.event_time_utc - active.updated_at_utc).total_seconds()
            if 0 <= gap <= self.legacy_policy.max_gap_seconds:
                return active.campaign_id, "LEGACY_EPISODE", False, self.legacy_policy.rule_version

        start_token = event.event_time_utc.strftime("%Y%m%dT%H%M%S.%fZ")
        digest = hashlib.sha256(
            f"{event.symbol}|{direction_key}|{start_token}|{self.legacy_policy.rule_version}".encode()
        ).hexdigest()[:16]
        campaign_id = f"legacy:{event.symbol}:{start_token}:{digest}"
        self._active_legacy[active_key] = campaign_id
        return campaign_id, "LEGACY_EPISODE", False, self.legacy_policy.rule_version

    def _find_lifecycle_for_event(self, event_id: str) -> PressureLifecycle | None:
        for lifecycle in self._lifecycles.values():
            if event_id in lifecycle.event_ids:
                return lifecycle
        return None


class PressureToTradePlanBuilder:
    """Assemble a frozen 5S-CR proof and non-executable tradeplan candidate."""

    def __init__(self, *, execution_policy: ExecutionPolicy | None = None) -> None:
        # Explicit policy wins, then env.  Never a silent default: an unresolved
        # policy fails closed in build() rather than inheriting a hidden floor.
        self.execution_policy = execution_policy or resolve_execution_policy()

    def build(
        self,
        lifecycle: PressureLifecycle,
        evidence: Strategy5SCRMarketEvidence,
        *,
        selection_confirmed: bool | None = None,
    ) -> PressureTradePlanBuildResult:
        selected = lifecycle.selected_by_pressure if selection_confirmed is None else selection_confirmed
        defer: list[str] = []
        block: list[str] = []

        if self.execution_policy is None:
            # A target floor is a strategy rule.  Refuse to invent one.
            return self._not_ready("BLOCK", lifecycle, [EXECUTION_POLICY_MISSING_REASON])

        if not selected:
            defer.append("STRATEGY_5SCR_PRESSURE_SELECTION_REQUIRED")
        if lifecycle.input_mode == "LIVE" and not lifecycle.campaign_anchor_execution_grade:
            defer.append("STRATEGY_5SCR_CANONICAL_LIFECYCLE_REQUIRED")
        if any(close_time > evidence.decision_at_utc for close_time in evidence.source_candle_close_times):
            block.append("STRATEGY_5SCR_FUTURE_CANDLE_LEAKAGE")

        context = evidence.context_resolution
        h4 = evidence.h4
        h1 = evidence.h1
        m15 = evidence.m15
        m1 = evidence.m1
        if context is None or context.status == "WAIT_FOR_CONFIRMATION":
            defer.append("NO_TRADE_CONTEXT_UNRESOLVED")
        elif context.status == "BLOCKED":
            block.append("STRATEGY_5SCR_CONTEXT_BLOCKED")
        else:
            if not context.scenario_allowed:
                block.append("STRATEGY_5SCR_SCENARIO_NOT_ALLOWED")
            if context.selected_playbook in context.blocked_playbook:
                block.append("STRATEGY_5SCR_PLAYBOOK_BLOCKED")

        if h4 is None:
            defer.append("STRATEGY_5SCR_H4_STRUCTURAL_TP1_REQUIRED")
        elif not h4.target_room_valid:
            block.append("STRATEGY_5SCR_TARGET_ROOM_INVALID")
        if h1 is None or not h1.candle_closed or not h1.structure_confirmed:
            defer.append("STRATEGY_5SCR_H1_CLOSED_STRUCTURE_CONFIRMATION_REQUIRED")
        elif h1.confirmed_at_utc > evidence.decision_at_utc:
            block.append("STRATEGY_5SCR_H1_FUTURE_CONFIRMATION")
        if m15 is None:
            defer.append("STRATEGY_5SCR_M15_CLOSED_STRUCTURAL_BREAK_REQUIRED")
        else:
            if not m15.candle_closed or not m15.structural_break:
                defer.append("STRATEGY_5SCR_M15_CLOSED_STRUCTURAL_BREAK_REQUIRED")
            if not (m15.acceptance_confirmed or m15.failed_reclaim_or_retest_confirmed):
                defer.append("STRATEGY_5SCR_M15_ACCEPTANCE_OR_FAILED_RECLAIM_RETEST_REQUIRED")
            if m15.rejection_candle_only:
                defer.append("NO_TRADE_REJECTION_CANDLE_ONLY")
            if m15.confirmed_at_utc > evidence.decision_at_utc:
                block.append("STRATEGY_5SCR_M15_FUTURE_CONFIRMATION")
            if h1 is not None and m15.confirmed_at_utc < h1.confirmed_at_utc:
                block.append("STRATEGY_5SCR_CONFIRMATION_SEQUENCE_INVALID")
        if m1 is None:
            defer.append("STRATEGY_5SCR_M1_BOX_FILL_REQUIRED")
        elif m1.return_to_box_invalidated:
            block.append("STRATEGY_5SCR_M1_RETURN_TO_BOX_INVALIDATED")
        if evidence.structural_sl is None:
            defer.append("STRATEGY_5SCR_STRUCTURAL_SL_REQUIRED")
        if evidence.pip_size is None or evidence.spread_price is None:
            defer.append("STRATEGY_5SCR_EXECUTION_COST_CONTEXT_REQUIRED")

        if block:
            return self._not_ready("BLOCK", lifecycle, block + defer)
        if defer:
            return self._not_ready("DEFER", lifecycle, defer)
        assert context is not None and h4 is not None and h1 is not None and m15 is not None and m1 is not None
        assert (
            evidence.structural_sl is not None and evidence.pip_size is not None and evidence.spread_price is not None
        )

        direction = h1.direction
        if m15.direction != direction:
            block.append("STRATEGY_5SCR_DIRECTION_AUTHORITY_MISMATCH")
        entry = m1.fill_price
        stop = evidence.structural_sl
        target = h4.structural_tp1
        if not self._geometry_valid(direction, entry, stop, target):
            block.append("STRATEGY_5SCR_PRICE_GEOMETRY_INVALID")
        target_distance = abs(target - entry)
        risk_distance = abs(entry - stop)
        rr = target_distance / risk_distance if risk_distance > 0 else 0.0
        policy = self.execution_policy
        execution_floor = policy.execution_floor(lifecycle.symbol, evidence.pip_size, evidence.spread_price)
        floor_assessment = policy.assess_target(
            lifecycle.symbol,
            target_distance_price=target_distance,
            pip_size=evidence.pip_size,
            spread_price=evidence.spread_price,
        )
        if target_distance + self._price_tolerance(entry) < execution_floor:
            block.append("STRATEGY_5SCR_TARGET_BELOW_EXECUTION_FLOOR")
        if rr + 1e-12 < policy.minimum_rr:
            block.append("STRATEGY_5SCR_RR_BELOW_1_5")
        if block:
            return self._not_ready("BLOCK", lifecycle, block)

        proof = Strategy5SCRProof(
            strategy_model=STRATEGY_MODEL,
            rule_version=STRATEGY_RULE_VERSION,
            rule_status=STRATEGY_RULE_STATUS,
            validation_status=STRATEGY_VALIDATION_STATUS,
            out_of_sample_status=STRATEGY_OOS_STATUS,
            production_proven=False,
            confirmation_policy=CONFIRMATION_POLICY,
            authority_chain=("PRESSURE", "CONTEXT_RESOLUTION", "H4", "H1", "M15", "M1", "RISK"),
            pressure=PressureAuthority(
                selected_pair=lifecycle.symbol,
                lifecycle_id=lifecycle.campaign_id,
                selection_confirmed=True,
            ),
            context_resolution=context,
            h4=h4,
            h1=h1,
            m15=m15,
            m1=m1,
            risk=RiskAuthority(structural_sl=stop, sizing_basis="STRUCTURAL_SL"),
        )
        proof_evaluation = evaluate_strategy_5scr_proof(
            {
                "symbol": lifecycle.symbol,
                "lifecycle_id": lifecycle.campaign_id,
                "final_direction": direction,
                "entry_reference_price": entry,
                "selected_sl": stop,
                "tp1": target,
                "strategy_5scr": proof.model_dump(mode="json"),
            }
        )
        if not proof_evaluation.ready:
            return self._not_ready(proof_evaluation.decision, lifecycle, list(proof_evaluation.reasons))

        tradeplan_id = self._tradeplan_id(lifecycle, direction, entry, stop, target, evidence.decision_at_utc)
        tradeplan = Strategy5SCRTradePlan(
            tradeplan_id=tradeplan_id,
            campaign_id=lifecycle.campaign_id,
            symbol=lifecycle.symbol,
            direction=direction,
            decision_at_utc=evidence.decision_at_utc,
            entry=entry,
            stop_loss=stop,
            tp1=target,
            target_mode=h4.target_mode,
            rr=rr,
            target_distance_price=target_distance,
            execution_floor_price=execution_floor,
            execution_policy_id=floor_assessment.execution_policy_id,
            execution_policy_version=floor_assessment.execution_policy_version,
            target_distance_pips=floor_assessment.target_distance_pips,
            minimum_target_pips=floor_assessment.minimum_target_pips,
            broker_cost_floor_pips=floor_assessment.broker_cost_floor_pips,
            required_target_pips=floor_assessment.required_target_pips,
            target_floor_status=floor_assessment.target_floor_status,
            pip_size=evidence.pip_size,
            spread_price=evidence.spread_price,
            source_pressure_event_ids=lifecycle.event_ids,
            proof=proof,
        )
        candidate_payload = {
            "event": "strategy_5scr_tradeplan_candidate",
            "schema_version": "1.0",
            "strategy_model": STRATEGY_MODEL,
            "strategy_rule_version": STRATEGY_RULE_VERSION,
            "tradeplan_id": tradeplan.tradeplan_id,
            "lifecycle_id": lifecycle.campaign_id,
            "symbol": lifecycle.symbol,
            "candidate_direction": direction,
            "validated_direction": direction,
            "final_direction": "WAIT",
            "source_pressure_event_ids": list(lifecycle.event_ids),
            "evidence_snapshot_id": evidence.evidence_snapshot_id,
            "evidence_mode": evidence.evidence_mode,
            "market_data_provider": evidence.market_data_provider,
            "execution_cost_authority": evidence.execution_cost_authority,
            "source_candle_count": evidence.source_candle_count,
            "entry_reference_price": entry,
            "selected_sl": stop,
            "tp1": target,
            "rr_status": "VALID",
            "tradeplan_valid": True,
            "analysis_valid": True,
            "direction_valid": True,
            "signal_valid": False,
            "is_final_signal": False,
            "execution_valid_now": False,
            "valid_for_execution": False,
            "next_required_stage": "RISK_RESERVATION",
            "strategy_5scr": proof.model_dump(mode="json"),
            "tradeplan_preview": tradeplan.model_dump(mode="json", exclude={"proof"}),
        }
        return PressureTradePlanBuildResult(
            decision="READY",
            lifecycle=lifecycle,
            tradeplan=tradeplan,
            candidate_payload=candidate_payload,
        )

    @staticmethod
    def _not_ready(
        decision: str,
        lifecycle: PressureLifecycle,
        reasons: list[str],
    ) -> PressureTradePlanBuildResult:
        resolved_decision = "BLOCK" if decision == "BLOCK" else "DEFER"
        return PressureTradePlanBuildResult(
            decision=resolved_decision,
            reasons=tuple(dict.fromkeys(reasons)),
            lifecycle=lifecycle,
        )

    @staticmethod
    def _geometry_valid(direction: str, entry: float, stop: float, target: float) -> bool:
        return stop < entry < target if direction == "BUY" else target < entry < stop

    @staticmethod
    def _price_tolerance(reference: float) -> float:
        return max(abs(reference), 1.0) * 1e-12

    @staticmethod
    def _tradeplan_id(
        lifecycle: PressureLifecycle,
        direction: str,
        entry: float,
        stop: float,
        target: float,
        decision_at: datetime,
    ) -> str:
        basis = "|".join(
            (
                lifecycle.campaign_id,
                lifecycle.symbol,
                direction,
                format(entry, ".12g"),
                format(stop, ".12g"),
                format(target, ".12g"),
                decision_at.astimezone(UTC).isoformat(),
                STRATEGY_RULE_VERSION,
            )
        )
        return "5scr-plan:" + hashlib.sha256(basis.encode()).hexdigest()[:32]


def replay_pressure_records(
    records: Iterable[Mapping[str, Any] | str],
    *,
    legacy_policy: LegacyEpisodePolicy | None = None,
) -> list[PressureLifecycle]:
    """Normalize and aggregate an exported Railway pressure-log collection."""

    normalizer = PressureEventNormalizer(input_mode="REPLAY")
    events = normalizer.normalize_many(records)
    accumulator = PressureLifecycleAccumulator(legacy_policy=legacy_policy)
    return accumulator.ingest_many(events)


def replay_pressure_outbox_events(
    records: Iterable[PressureOutboxEnvelope | Mapping[str, Any]],
) -> list[PressureLifecycle]:
    """Rebuild LIVE pressure lifecycles from canonical PostgreSQL outbox rows."""

    envelopes = [
        record if isinstance(record, PressureOutboxEnvelope) else PressureOutboxEnvelope.model_validate(record)
        for record in records
    ]
    envelopes.sort(key=lambda item: (item.lifecycle_id, item.lifecycle_sequence))
    expected_by_lifecycle: dict[str, int] = {}
    normalizer = PressureEventNormalizer(input_mode="LIVE")
    accumulator = PressureLifecycleAccumulator()
    for envelope in envelopes:
        expected = expected_by_lifecycle.get(envelope.lifecycle_id, 0) + 1
        if envelope.lifecycle_sequence != expected:
            raise PressureLifecycleOrderError("PRESSURE_OUTBOX_LIFECYCLE_SEQUENCE_GAP")
        expected_by_lifecycle[envelope.lifecycle_id] = expected
        event = normalizer.normalize(envelope.payload)
        lifecycle, _duplicate = accumulator.ingest(event)
        if lifecycle.campaign_id != envelope.lifecycle_id:
            raise PressureInputError("PRESSURE_OUTBOX_LIFECYCLE_MISMATCH")
    return accumulator.snapshots()


__all__ = [
    "MIN_RR",
    "PRESSURE_LOG_PREFIX",
    "PressureEventNormalizer",
    "PressureInputError",
    "PressureLifecycleAccumulator",
    "PressureLifecycleOrderError",
    "PressureToTradePlanBuilder",
    "replay_pressure_outbox_events",
    "replay_pressure_records",
]
