"""Standalone final signal JSON emitter.

Raw throttle and microboost logs are telemetry. ``[SignalJSON]`` is the
final signal product; ``[SignalWatchJSON]`` is a rate-limited lifecycle update
for watch states.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any

EMITTABLE_SIGNAL_STATUSES = {
    "PAIR_SIGNAL_CANDIDATE",
    "MICROBOOST_COUNTER_ENTRY_WATCH",
    "MICROBOOST_COUNTER_ENTRY_VALID",
    "NANO_ABSORPTION_SELL_WATCH",
    "EARLY_SELL_WATCH",
    "SELL_ABSORPTION_WATCH",
    "SELL_TIMING_WATCH",
    "SELL_TIMING_VALID_BY_DIRECT_ABSORPTION",
    "SELL_TIMING_VALID_BY_ABSORPTION",
    "SELL_TIMING_VALID",
    "NANO_ABSORPTION_BUY_WATCH",
    "EARLY_BUY_WATCH",
    "BUY_ABSORPTION_WATCH",
    "BUY_TIMING_WATCH",
    "BUY_TIMING_VALID_BY_DIRECT_ABSORPTION",
    "BUY_TIMING_VALID_BY_ABSORPTION",
    "BUY_TIMING_VALID",
    "BUY_TIMING_VALID_BY_QUORUM_CONTINUATION",
    "SELL_TIMING_VALID_BY_QUORUM_CONTINUATION",
    "BUY_REVERSAL_VALID",
    "SELL_REVERSAL_VALID",
    "BUY_BREAKOUT_CONTINUATION_VALID",
    "BUY_BREAKOUT_RETEST_VALID",
    "SELL_BREAKDOWN_CONTINUATION_VALID",
    "SELL_BREAKDOWN_RETEST_VALID",
    "LATE_MICROBOOST_EXIT_ALERT",
    "PROTECT_PROFIT_ALERT",
    "THEME_SIGNAL_CANDIDATE",
    "WAIT_STRUCTURE_OR_NEXT_M15",
    "WAIT_M15_CLOSE_OR_STRUCTURE_TARGET",
    "WAIT_M15_CLOSE_CONFIRMATION",
    "PENDING_WATCH_EXPIRED",
}

VALID_SIGNAL_STATUSES = {
    "SELL_TIMING_VALID",
    "BUY_TIMING_VALID",
    "COUNTER_ENTRY_VALID",
    "MICROBOOST_COUNTER_ENTRY_VALID",
    "PAIR_SIGNAL_VALID",
    "BREAKOUT_RETEST_VALID",
    "PULLBACK_RECLAIM_VALID",
    "LATE_DENSE_EXIT_ALERT",
    "PROTECT_PROFIT_ALERT",
    "SELL_TIMING_VALID_BY_DIRECT_ABSORPTION",
    "BUY_TIMING_VALID_BY_DIRECT_ABSORPTION",
    "BUY_TIMING_VALID_BY_QUORUM_CONTINUATION",
    "SELL_TIMING_VALID_BY_QUORUM_CONTINUATION",
    "BUY_REVERSAL_VALID",
    "SELL_REVERSAL_VALID",
    "BUY_BREAKOUT_CONTINUATION_VALID",
    "BUY_BREAKOUT_RETEST_VALID",
    "SELL_BREAKDOWN_CONTINUATION_VALID",
    "SELL_BREAKDOWN_RETEST_VALID",
}

CONTINUATION_SIGNAL_STATUSES = {
    "BUY_TIMING_VALID_BY_QUORUM_CONTINUATION",
    "SELL_TIMING_VALID_BY_QUORUM_CONTINUATION",
}

CONDITIONAL_SIGNAL_STATUSES = {
    "SELL_ABSORPTION_WATCH",
    "SELL_TIMING_VALID_BY_ABSORPTION",
    "BUY_ABSORPTION_WATCH",
    "BUY_TIMING_VALID_BY_ABSORPTION",
}

WATCH_SIGNAL_STATUSES = {
    "NANO_ABSORPTION_SELL_WATCH",
    "EARLY_SELL_WATCH",
    "SELL_TIMING_WATCH",
    "NANO_ABSORPTION_BUY_WATCH",
    "EARLY_BUY_WATCH",
    "BUY_TIMING_WATCH",
    "MICROBOOST_COUNTER_ENTRY_WATCH",
} | CONDITIONAL_SIGNAL_STATUSES

DECISION_UPDATE_STATUSES = {
    "WAIT_STRUCTURE_OR_NEXT_M15",
    "WAIT_M15_CLOSE_OR_STRUCTURE_TARGET",
    "WAIT_M15_CLOSE_CONFIRMATION",
    "PENDING_WATCH_EXPIRED",
}

PROVISIONAL_TARGET_ALLOWED_FINAL_STATUSES = CONTINUATION_SIGNAL_STATUSES | {
    "BUY_BREAKOUT_CONTINUATION_VALID",
    "SELL_BREAKDOWN_CONTINUATION_VALID",
    "BUY_BREAKOUT_RETEST_VALID",
    "SELL_BREAKDOWN_RETEST_VALID",
}


@dataclass(frozen=True)
class SignalJsonEvent:
    event: str
    schema_version: str
    symbol: str
    signal_family: str
    status: str
    raw_direction: str | None
    candidate_direction: str | None
    validated_direction: str | None
    final_direction: str
    action: str
    signal_valid_time_utc: str
    signal_valid_time_wita: str | None
    signal_valid_price: float
    entry_reference_price: float
    entry_zone: list[float]
    price_position: str | None
    m15_phase: str | None
    h1_phase: str | None
    phase_unpriced: str | None
    phase_priced: str | None
    effective_ticks: int | None
    effective_density: float | None
    duration_minutes: float | None
    sl_tight: float | None
    sl_safe: float | None
    tp1: float | None
    tp2: float | None
    tp3: float | None
    tp4: float | None
    rr_to_tp1_tight: float | None
    rr_to_tp2_tight: float | None
    rr_to_tp3_tight: float | None
    rr_status: str
    market_context_applied: bool
    confidence_bucket: str | None
    reason: str
    invalidation: str | None
    cluster_id: str | None = None
    is_final_signal: bool = False
    emit_reason: str | None = None
    signal_quality: str | None = None
    lifecycle_version: int = 2
    target_mode: str | None = None
    tp_status: str | None = None
    tp_missing_reason: str | None = None
    support_ladder_ready: bool | None = None
    resistance_ladder_ready: bool | None = None
    structure_targets_available: bool | None = None
    tradeplan_context_ready: bool | None = None
    valid_for_execution: bool = False
    min_rr_required: float | None = None
    tp_min_rr: float | None = None
    tp_min_rr_value: float | None = None
    tp1_rr: float | None = None
    tp2_rr: float | None = None
    tp3_rr: float | None = None
    tp4_rr: float | None = None
    allowed_quorum: bool | None = None
    allowed_quorum_streak: int | None = None
    reclaim_trigger: float | None = None
    risk_pips: float | None = None
    signal_id: str | None = None
    linked_previous_signal: str | None = None
    previous_signal_status: str | None = None
    lifecycle_status: str | None = None
    active_signal: dict[str, Any] | None = None
    previous_status: str | None = None
    new_status: str | None = None
    block_end_utc: str | None = None
    block_end_wita: str | None = None
    block_idle_seconds: float | None = None
    next_action: str | None = None
    confirmation_policy: str | None = None
    requires_m15_close: bool | None = None
    direct_valid_reason: str | None = None
    pending_decision_id: str | None = None
    price_delta_pips: float | None = None
    theme_alignment: str | None = None
    structure_ready: bool | None = None
    rr_to_valid_target: float | None = None
    m15_confirmation_status: str | None = None
    breakout_reclaim_level: float | None = None
    support_reclaim_level: float | None = None
    decision_watch_type: str | None = None
    buy_condition: str | None = None
    sell_condition: str | None = None
    pullback_buy_zone: list[float] | None = None
    breakout_buy_zone: list[float] | None = None
    sell_rejection_zone: list[float] | None = None
    key_resistance: float | None = None
    key_support: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SignalJsonEmitter:
    def __init__(
        self,
        *,
        enabled: bool = True,
        prefix: str = "[SignalJSON]",
        watch_prefix: str = "[SignalWatchJSON]",
        decision_update_prefix: str = "[SignalDecisionUpdateJSON]",
        dedup_ttl_seconds: int = 300,
        emit_watch: bool = False,
        emit_conditional: bool = True,
        emit_valid: bool = True,
        require_market_context: bool = True,
        watch_transition_only: bool = True,
    ) -> None:
        self.enabled = enabled
        self.prefix = prefix
        self.watch_prefix = watch_prefix
        self.decision_update_prefix = decision_update_prefix
        self.dedup_ttl_seconds = max(1, int(dedup_ttl_seconds))
        self.emit_watch = emit_watch
        self.emit_conditional = emit_conditional
        self.emit_valid = emit_valid
        self.require_market_context = require_market_context
        self.watch_transition_only = watch_transition_only
        self._emitted: dict[str, float] = {}
        self._cluster_state: dict[str, str] = {}
        self.logger = logging.getLogger("signal_json")

    def emit(self, event: SignalJsonEvent) -> bool:
        if not self.enabled:
            return False
        is_decision_update = _is_decision_update_event(event)
        is_watch = _is_watch_status(event.status) and not is_decision_update
        if is_watch and self.watch_transition_only and not self._mark_watch_transition(event):
            return False
        if not should_emit_signal_json(
            event,
            emit_watch=self.emit_watch,
            emit_conditional=self.emit_conditional,
            emit_valid=self.emit_valid,
            require_market_context=self.require_market_context,
        ):
            return False

        key = self._event_key(event)
        if self._is_duplicate(key):
            return False

        payload = event.to_dict()
        payload["event"] = (
            "signal_decision_update_json"
            if is_decision_update
            else ("signal_watch_json" if is_watch else "signal_json")
        )
        payload["is_final_signal"] = bool(payload.get("is_final_signal") or _is_final_payload(payload))
        payload["emit_reason"] = payload.get("emit_reason") or _emit_reason(event.status)
        payload["signal_quality"] = payload.get("signal_quality") or _signal_quality(payload)
        prefix = self.decision_update_prefix if is_decision_update else (self.watch_prefix if is_watch else self.prefix)
        self.logger.warning("%s %s", prefix, json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
        return True

    @staticmethod
    def _event_key(event: SignalJsonEvent) -> str:
        cluster_key = event.cluster_id or event.signal_valid_time_utc
        if _is_decision_update_event(event):
            return (
                f"{event.symbol}|{cluster_key}|{event.signal_family}|decision|{event.status}|"
                f"{event.m15_confirmation_status or ''}|{event.target_mode or ''}"
            )
        if _is_watch_status(event.status):
            return f"{event.symbol}|{cluster_key}|{event.signal_family}|{event.status}|{event.target_mode or ''}"
        return (
            f"{event.symbol}|{cluster_key}|{event.signal_family}|{event.final_direction}|"
            f"{event.entry_reference_price}"
        )

    def _mark_watch_transition(self, event: SignalJsonEvent) -> bool:
        cluster_key = event.cluster_id or f"{event.symbol}|{event.signal_family}|{event.entry_reference_price}"
        state = f"{event.status}|{event.target_mode or ''}|{event.tp_status or ''}"
        previous = self._cluster_state.get(cluster_key)
        if previous == state:
            return False
        self._cluster_state[cluster_key] = state
        return True

    def _is_duplicate(self, key: str) -> bool:
        now = time.time()
        expired_keys = [old_key for old_key, ts in self._emitted.items() if now - ts > self.dedup_ttl_seconds]
        for old_key in expired_keys:
            self._emitted.pop(old_key, None)

        if key in self._emitted:
            return True
        self._emitted[key] = now
        return False


def build_signal_json_event(counter_entry: dict[str, Any] | None) -> SignalJsonEvent | None:
    if not isinstance(counter_entry, dict):
        return None
    signal_valid_time = _optional_str(
        counter_entry.get("signal_valid_time_utc") or counter_entry.get("signal_valid_time")
    )
    signal_valid_price = _optional_float(counter_entry.get("signal_valid_price"))
    entry_reference_price = _optional_float(counter_entry.get("entry_reference_price"))
    entry_zone = _float_list(counter_entry.get("entry_zone"))
    symbol = str(counter_entry.get("symbol") or "").upper()
    status = str(counter_entry.get("status") or "")
    if not signal_valid_time or signal_valid_price is None or entry_reference_price is None or not entry_zone or not symbol:
        return None
    is_decision_update = _is_decision_update_payload(counter_entry)
    is_watch = _is_watch_status(status) and not is_decision_update
    return SignalJsonEvent(
        event="signal_decision_update_json" if is_decision_update else ("signal_watch_json" if is_watch else "signal_json"),
        schema_version="1.0",
        symbol=symbol,
        signal_family=str(
            counter_entry.get("signal_family")
            or counter_entry.get("signal_type")
            or "MICROBOOST_COUNTER_ENTRY"
        ),
        status=status,
        cluster_id=_optional_str(counter_entry.get("cluster_id")),
        is_final_signal=_is_final_payload(counter_entry),
        emit_reason=_emit_reason(status),
        signal_quality=_signal_quality(counter_entry),
        raw_direction=_optional_str(counter_entry.get("raw_direction")),
        candidate_direction=_optional_str(counter_entry.get("candidate_direction")),
        validated_direction=_optional_str(
            counter_entry.get("validated_direction") or counter_entry.get("candidate_direction")
        ),
        final_direction=str(counter_entry.get("final_direction") or "WAIT"),
        action=str(counter_entry.get("action") or "WAIT"),
        signal_valid_time_utc=signal_valid_time,
        signal_valid_time_wita=_optional_str(counter_entry.get("signal_valid_time_wita")),
        signal_valid_price=signal_valid_price,
        entry_reference_price=entry_reference_price,
        entry_zone=entry_zone,
        price_position=_optional_str(counter_entry.get("price_position")),
        m15_phase=_optional_str(counter_entry.get("m15_phase")),
        h1_phase=_optional_str(counter_entry.get("h1_phase")),
        phase_unpriced=_optional_str(counter_entry.get("phase_unpriced")),
        phase_priced=_optional_str(counter_entry.get("phase_priced")),
        effective_ticks=_optional_int(counter_entry.get("effective_ticks")),
        effective_density=_optional_float(counter_entry.get("effective_density")),
        duration_minutes=_optional_float(counter_entry.get("duration_minutes")),
        sl_tight=_optional_float(counter_entry.get("sl_tight")),
        sl_safe=_optional_float(counter_entry.get("sl_safe")),
        tp1=_optional_float(counter_entry.get("tp1")),
        tp2=_optional_float(counter_entry.get("tp2")),
        tp3=_optional_float(counter_entry.get("tp3")),
        tp4=_optional_float(counter_entry.get("tp4")),
        rr_to_tp1_tight=_optional_float(counter_entry.get("rr_to_tp1_tight")),
        rr_to_tp2_tight=_optional_float(counter_entry.get("rr_to_tp2_tight")),
        rr_to_tp3_tight=_optional_float(counter_entry.get("rr_to_tp3_tight")),
        rr_status=str(counter_entry.get("rr_status") or "UNVALIDATED"),
        market_context_applied=bool(counter_entry.get("market_context_applied", False)),
        confidence_bucket=_optional_str(counter_entry.get("confidence_bucket")),
        reason=str(counter_entry.get("reason") or "signal_json_candidate"),
        invalidation=_optional_str(counter_entry.get("invalidation")),
        target_mode=_optional_str(counter_entry.get("target_mode")),
        tp_status=_optional_str(counter_entry.get("tp_status")),
        tp_missing_reason=_optional_str(counter_entry.get("tp_missing_reason")),
        support_ladder_ready=_optional_bool(counter_entry.get("support_ladder_ready")),
        resistance_ladder_ready=_optional_bool(counter_entry.get("resistance_ladder_ready")),
        structure_targets_available=_optional_bool(counter_entry.get("structure_targets_available")),
        tradeplan_context_ready=_optional_bool(counter_entry.get("tradeplan_context_ready")),
        valid_for_execution=bool(counter_entry.get("valid_for_execution", False)),
        min_rr_required=_optional_float(counter_entry.get("min_rr_required")),
        tp_min_rr=_optional_float(counter_entry.get("tp_min_rr")),
        tp_min_rr_value=_optional_float(counter_entry.get("tp_min_rr_value")),
        tp1_rr=_optional_float(counter_entry.get("tp1_rr")),
        tp2_rr=_optional_float(counter_entry.get("tp2_rr")),
        tp3_rr=_optional_float(counter_entry.get("tp3_rr")),
        tp4_rr=_optional_float(counter_entry.get("tp4_rr")),
        allowed_quorum=_optional_bool(counter_entry.get("allowed_quorum")),
        allowed_quorum_streak=_optional_int(counter_entry.get("allowed_quorum_streak")),
        reclaim_trigger=_optional_float(counter_entry.get("reclaim_trigger")),
        risk_pips=_optional_float(counter_entry.get("risk_pips")),
        signal_id=_optional_str(counter_entry.get("signal_id")),
        linked_previous_signal=_optional_str(counter_entry.get("linked_previous_signal")),
        previous_signal_status=_optional_str(counter_entry.get("previous_signal_status")),
        lifecycle_status=_optional_str(counter_entry.get("lifecycle_status")),
        active_signal=counter_entry.get("active_signal") if isinstance(counter_entry.get("active_signal"), dict) else None,
        previous_status=_optional_str(counter_entry.get("previous_status")),
        new_status=_optional_str(counter_entry.get("new_status")),
        block_end_utc=_optional_str(counter_entry.get("block_end_utc")),
        block_end_wita=_optional_str(counter_entry.get("block_end_wita")),
        block_idle_seconds=_optional_float(counter_entry.get("block_idle_seconds")),
        next_action=_optional_str(counter_entry.get("next_action")),
        confirmation_policy=_optional_str(counter_entry.get("confirmation_policy")),
        requires_m15_close=_optional_bool(counter_entry.get("requires_m15_close")),
        direct_valid_reason=_optional_str(counter_entry.get("direct_valid_reason")),
        pending_decision_id=_optional_str(counter_entry.get("pending_decision_id")),
        price_delta_pips=_optional_float(counter_entry.get("price_delta_pips")),
        theme_alignment=_optional_str(counter_entry.get("theme_alignment")),
        structure_ready=_optional_bool(counter_entry.get("structure_ready")),
        rr_to_valid_target=_optional_float(counter_entry.get("rr_to_valid_target")),
        m15_confirmation_status=_optional_str(counter_entry.get("m15_confirmation_status")),
        breakout_reclaim_level=_optional_float(counter_entry.get("breakout_reclaim_level")),
        support_reclaim_level=_optional_float(counter_entry.get("support_reclaim_level")),
        decision_watch_type=_optional_str(counter_entry.get("decision_watch_type")),
        buy_condition=_optional_str(counter_entry.get("buy_condition")),
        sell_condition=_optional_str(counter_entry.get("sell_condition")),
        pullback_buy_zone=_float_list(counter_entry.get("pullback_buy_zone")) or None,
        breakout_buy_zone=_float_list(counter_entry.get("breakout_buy_zone")) or None,
        sell_rejection_zone=_float_list(counter_entry.get("sell_rejection_zone")) or None,
        key_resistance=_optional_float(counter_entry.get("key_resistance")),
        key_support=_optional_float(counter_entry.get("key_support")),
    )


def should_emit_signal_json(
    event_or_payload: SignalJsonEvent | dict[str, Any],
    *,
    emit_watch: bool = True,
    emit_conditional: bool = True,
    emit_valid: bool = True,
    require_market_context: bool = True,
) -> bool:
    payload = event_or_payload.to_dict() if isinstance(event_or_payload, SignalJsonEvent) else event_or_payload
    status = str(payload.get("status") or "")
    if status not in EMITTABLE_SIGNAL_STATUSES:
        return False
    if _is_decision_update_payload(payload):
        return (
            _optional_float(payload.get("signal_valid_price")) is not None
            and _optional_float(payload.get("entry_reference_price")) is not None
        )
    is_conditional = status in CONDITIONAL_SIGNAL_STATUSES
    if is_conditional and not emit_conditional:
        return False
    if status in WATCH_SIGNAL_STATUSES and not is_conditional and not emit_watch:
        return False
    if status in VALID_SIGNAL_STATUSES and not emit_valid:
        return False
    if require_market_context and not bool(payload.get("market_context_applied", False)):
        return False
    if _optional_float(payload.get("signal_valid_price")) is None:
        return False
    if _optional_float(payload.get("entry_reference_price")) is None:
        return False
    if status in VALID_SIGNAL_STATUSES or str(status).endswith("_VALID"):
        rr_status = str(payload.get("rr_status") or "").upper()
        if rr_status not in {"VALID", "ACCEPTABLE", "PROTECT_ONLY"}:
            return False
        if str(payload.get("final_direction") or "").upper() not in {"BUY", "SELL"}:
            return False
        target_mode = str(payload.get("target_mode") or "").upper()
        if status in PROVISIONAL_TARGET_ALLOWED_FINAL_STATUSES:
            if target_mode not in {"FINAL_MARKET_STRUCTURE", "PROVISIONAL_RR_FALLBACK"}:
                return False
        elif target_mode != "FINAL_MARKET_STRUCTURE":
            return False
        if not bool(payload.get("valid_for_execution", False)):
            return False
    return True


def _is_watch_status(status: str) -> bool:
    return status in WATCH_SIGNAL_STATUSES or status.endswith("_WATCH")


def _is_decision_update_status(status: str) -> bool:
    return status in DECISION_UPDATE_STATUSES


def _is_decision_update_event(event: SignalJsonEvent) -> bool:
    return event.event == "signal_decision_update_json" or _is_decision_update_status(event.status)


def _is_decision_update_payload(payload: dict[str, Any]) -> bool:
    return str(payload.get("event") or "") == "signal_decision_update_json" or _is_decision_update_status(
        str(payload.get("status") or "")
    )


def _emit_reason(status: str) -> str:
    if _is_decision_update_status(status):
        return "BLOCK_FINALIZER_DECISION_UPDATE"
    if status in CONTINUATION_SIGNAL_STATUSES:
        return "QUORUM_CONTINUATION_VALID"
    if status.endswith("_BY_DIRECT_ABSORPTION"):
        return "DIRECT_ABSORPTION_VALID"
    if status in {"SELL_ABSORPTION_WATCH", "BUY_ABSORPTION_WATCH"}:
        return "ABSORPTION_WATCH"
    if status in CONDITIONAL_SIGNAL_STATUSES:
        return "TIMING_VALID_CONDITIONAL"
    if status in WATCH_SIGNAL_STATUSES:
        return "STATE_TRANSITION"
    return "FINAL_SIGNAL_VALID"


def _is_final_payload(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "")
    target_mode = str(payload.get("target_mode") or "").upper()
    target_ok = (
        target_mode in {"FINAL_MARKET_STRUCTURE", "PROVISIONAL_RR_FALLBACK"}
        if status in PROVISIONAL_TARGET_ALLOWED_FINAL_STATUSES
        else target_mode == "FINAL_MARKET_STRUCTURE"
    )
    return (
        (status in VALID_SIGNAL_STATUSES or status.endswith("_VALID"))
        and str(payload.get("final_direction") or "").upper() in {"BUY", "SELL"}
        and str(payload.get("rr_status") or "").upper() in {"VALID", "ACCEPTABLE", "PROTECT_ONLY"}
        and target_ok
        and bool(payload.get("valid_for_execution", False))
    )


def _signal_quality(payload: dict[str, Any]) -> str:
    if _is_decision_update_payload(payload):
        return "DECISION_UPDATE"
    if _is_final_payload(payload):
        if str(payload.get("status") or "").endswith("_BY_DIRECT_ABSORPTION"):
            return "DIRECT_ABSORPTION_VALID"
        if str(payload.get("status") or "") in CONTINUATION_SIGNAL_STATUSES:
            return "TREND_CONTINUATION_VALID"
        return "TRADEPLAN_VALID"
    status = str(payload.get("status") or "")
    if status in {"SELL_ABSORPTION_WATCH", "BUY_ABSORPTION_WATCH"}:
        return "ABSORPTION_WATCH"
    if status.endswith("_BY_ABSORPTION"):
        return "TIMING_VALID_CONDITIONAL"
    if _is_watch_status(status):
        return "WATCH_ONLY"
    return "CANDIDATE"


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    values: list[float] = []
    for item in value:
        number = _optional_float(item)
        if number is not None:
            values.append(number)
    return values


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
