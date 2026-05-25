"""Finalize pending microboost watches when a symbol pressure block goes idle.

Microboost emits the first decision point.  This module owns the next pass:
when the source pressure block stops, it re-checks the latest M15 context and
either promotes the watch into a final SignalJSON payload or emits a
SignalDecisionUpdateJSON payload explaining why the plan is still pending.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from analysis.market_context_validator import MarketContext
from analysis.microboost_counter_entry import MicroboostCounterEntryEngine

_TZ_WITA = ZoneInfo("Asia/Makassar")

PENDING_WATCH_STATUSES = {
    "SELL_ABSORPTION_WATCH",
    "BUY_ABSORPTION_WATCH",
    "SELL_TIMING_WATCH",
    "BUY_TIMING_WATCH",
    "SELL_TIMING_VALID_BY_ABSORPTION",
    "BUY_TIMING_VALID_BY_ABSORPTION",
}

FINAL_EXECUTION_STATUSES = {
    "BUY_TIMING_VALID",
    "SELL_TIMING_VALID",
    "BUY_TIMING_VALID_BY_DIRECT_ABSORPTION",
    "SELL_TIMING_VALID_BY_DIRECT_ABSORPTION",
    "BUY_TIMING_VALID_BY_ABSORPTION",
    "SELL_TIMING_VALID_BY_ABSORPTION",
    "BUY_BREAKOUT_CONTINUATION_VALID",
    "SELL_BREAKDOWN_CONTINUATION_VALID",
    "BUY_BREAKOUT_RETEST_VALID",
    "SELL_BREAKDOWN_RETEST_VALID",
}

MIN_EXECUTABLE_TP1_RR = 2.0


@dataclass
class PendingDecisionState:
    symbol: str
    cluster_id: str | None
    watch_type: str
    status: str
    payload: dict[str, Any]
    created_utc: datetime
    signal_valid_price: float | None
    entry_zone: list[float]
    expires_after_m15_bars: int = 3
    last_decision_key: str | None = None

    @property
    def pending_decision_id(self) -> str:
        raw = self.payload.get("pending_decision_id")
        if raw:
            return str(raw)
        return f"{self.symbol}_{self.cluster_id or 'ACTIVE'}_M15_DECISION"


@dataclass(frozen=True)
class M15CloseDecision:
    confirmation: str
    final_direction: str
    reason: str

    @property
    def is_confirmed(self) -> bool:
        return self.final_direction in {"BUY", "SELL"}


class M15CloseConfirmationGate:
    """Evaluate latest M15 candle against a pending absorption watch."""

    def evaluate(self, watch: PendingDecisionState, market: Any | None) -> M15CloseDecision:
        candidate = _candidate_direction(watch.payload)
        if candidate == "SELL":
            return self._evaluate_resistance_watch(watch, market)
        if candidate == "BUY":
            return self._evaluate_support_watch(watch, market)
        return M15CloseDecision(
            confirmation="PENDING_M15_CLOSE",
            final_direction="WAIT",
            reason="pending_watch_candidate_direction_missing",
        )

    def _evaluate_resistance_watch(self, watch: PendingDecisionState, market: Any | None) -> M15CloseDecision:
        signal_price = watch.signal_valid_price
        resistance_high = _first_float(
            watch.payload.get("key_resistance"),
            watch.payload.get("breakout_reclaim_level"),
            _zone_high(watch.entry_zone),
            _field(market, "resistance_high"),
            _field(market, "main_resistance"),
        )
        m15_open = _optional_float(_field(market, "m15_open"))
        m15_high = _optional_float(_field(market, "m15_high"))
        m15_close = _optional_float(_field(market, "m15_close"))

        exact_rejection = (
            m15_high is not None
            and resistance_high is not None
            and m15_close is not None
            and m15_open is not None
            and signal_price is not None
            and m15_high >= resistance_high
            and m15_close < signal_price
            and m15_close < m15_open
        )
        fallback_rejection = (
            m15_close is not None
            and signal_price is not None
            and m15_close < signal_price
            and _optional_bool(_field(market, "m15_rejection_from_resistance")) is True
        )
        exact_breakout = (
            m15_close is not None
            and m15_open is not None
            and resistance_high is not None
            and m15_close > resistance_high
            and m15_close > m15_open
        )
        fallback_breakout = _optional_bool(_field(market, "m15_close_above_resistance")) is True

        if exact_rejection or fallback_rejection:
            return M15CloseDecision(
                confirmation="M15_CLOSE_REJECTION_CONFIRMED",
                final_direction="SELL",
                reason="M15 closed as bearish rejection from the resistance watch zone.",
            )
        if exact_breakout or fallback_breakout:
            return M15CloseDecision(
                confirmation="M15_CLOSE_ABOVE_RESISTANCE",
                final_direction="BUY",
                reason="M15 closed above resistance, invalidating the sell absorption watch.",
            )
        return M15CloseDecision(
            confirmation="PENDING_M15_CLOSE",
            final_direction="WAIT",
            reason="M15 has not confirmed rejection or breakout from the resistance watch zone.",
        )

    def _evaluate_support_watch(self, watch: PendingDecisionState, market: Any | None) -> M15CloseDecision:
        signal_price = watch.signal_valid_price
        support_low = _first_float(
            watch.payload.get("key_support"),
            watch.payload.get("support_reclaim_level"),
            _zone_low(watch.entry_zone),
            _field(market, "support_low"),
            _field(market, "main_support"),
        )
        m15_open = _optional_float(_field(market, "m15_open"))
        m15_low = _optional_float(_field(market, "m15_low"))
        m15_close = _optional_float(_field(market, "m15_close"))

        exact_rejection = (
            m15_low is not None
            and support_low is not None
            and m15_close is not None
            and m15_open is not None
            and signal_price is not None
            and m15_low <= support_low
            and m15_close > signal_price
            and m15_close > m15_open
        )
        fallback_rejection = (
            m15_close is not None
            and signal_price is not None
            and m15_close > signal_price
            and _optional_bool(_field(market, "m15_rejection_from_support")) is True
        )
        exact_breakdown = (
            m15_close is not None
            and m15_open is not None
            and support_low is not None
            and m15_close < support_low
            and m15_close < m15_open
        )
        fallback_breakdown = _optional_bool(_field(market, "m15_close_below_support")) is True

        if exact_rejection or fallback_rejection:
            return M15CloseDecision(
                confirmation="M15_CLOSE_REJECTION_CONFIRMED",
                final_direction="BUY",
                reason="M15 closed as bullish rejection from the support watch zone.",
            )
        if exact_breakdown or fallback_breakdown:
            return M15CloseDecision(
                confirmation="M15_CLOSE_BELOW_SUPPORT",
                final_direction="SELL",
                reason="M15 closed below support, invalidating the buy absorption watch.",
            )
        return M15CloseDecision(
            confirmation="PENDING_M15_CLOSE",
            final_direction="WAIT",
            reason="M15 has not confirmed rejection or breakdown from the support watch zone.",
        )


class SignalBlockFinalizer:
    """Track pending watches and finalize them after source pressure goes idle."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        idle_finalize_seconds: float = 75.0,
        hard_finalize_seconds: float = 300.0,
        expires_after_m15_bars: int = 3,
        min_rr_valid: float = 2.5,
        tp1_rr_required: float = 2.0,
        counter_entry_risk_multiplier: float = 0.5,
        counter_entry_expiry_minutes: int = 30,
        allow_rr_fallback: bool = True,
    ) -> None:
        self.enabled = enabled
        self.idle_finalize_seconds = max(1.0, float(idle_finalize_seconds))
        self.hard_finalize_seconds = max(self.idle_finalize_seconds, float(hard_finalize_seconds))
        self.expires_after_m15_bars = max(1, int(expires_after_m15_bars))
        self._pending: dict[str, PendingDecisionState] = {}
        self._gate = M15CloseConfirmationGate()
        self._engine = MicroboostCounterEntryEngine(
            min_rr_valid=min_rr_valid,
            tp1_rr_required=tp1_rr_required,
            counter_entry_risk_multiplier=counter_entry_risk_multiplier,
            counter_entry_expiry_minutes=counter_entry_expiry_minutes,
            allow_rr_fallback=allow_rr_fallback,
        )

    def track(self, payload: dict[str, Any]) -> None:
        if not self.enabled or not isinstance(payload, dict):
            return
        symbol = str(payload.get("symbol") or "").upper()
        if not symbol:
            return
        if _is_final_execution(payload):
            self._pending.pop(symbol, None)
            return
        if not _is_pending_watch(payload):
            return

        pending = _pending_from_payload(
            payload,
            expires_after_m15_bars=self.expires_after_m15_bars,
        )
        if pending is None:
            return
        current = self._pending.get(symbol)
        if current is None or pending.created_utc >= current.created_utc:
            self._pending[symbol] = pending

    def pending_symbols(self) -> list[str]:
        return sorted(self._pending)

    def pending_state(self, symbol: str) -> dict[str, Any] | None:
        state = self._pending.get(symbol.upper())
        if state is None:
            return None
        return {
            "symbol": state.symbol,
            "cluster_id": state.cluster_id,
            "watch_type": state.watch_type,
            "status": state.status,
            "created_utc": state.created_utc.isoformat(),
            "signal_valid_price": state.signal_valid_price,
            "entry_zone": state.entry_zone,
            "pending_decision_id": state.pending_decision_id,
            "raw_direction": state.payload.get("raw_direction"),
            "candidate_direction": state.payload.get("candidate_direction"),
        }

    def finalize(
        self,
        *,
        report: dict[str, Any],
        market_contexts: dict[str, Any],
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if not self.enabled or not self._pending:
            return []
        now_utc = _coerce_datetime(now) or datetime.now(UTC)
        outputs: list[dict[str, Any]] = []
        for symbol, watch in list(self._pending.items()):
            activity = _activity_for_symbol(report, symbol)
            block_end = _coerce_datetime((activity or {}).get("latest_event_utc"))
            block_end = block_end or _coerce_datetime((activity or {}).get("latest_block_end_utc"))
            block_end = block_end or _coerce_datetime(watch.payload.get("signal_valid_time_utc"))
            idle_seconds = _elapsed_seconds(now_utc, block_end)
            age_seconds = _elapsed_seconds(now_utc, watch.created_utc)
            if idle_seconds < self.idle_finalize_seconds and age_seconds < self.hard_finalize_seconds:
                continue

            market = _context_for_symbol(market_contexts, symbol)
            if market is None:
                update = self._decision_update(
                    watch=watch,
                    decision=M15CloseDecision(
                        confirmation="PENDING_MARKET_CONTEXT",
                        final_direction="WAIT",
                        reason="Pressure block ended, but fresh M15/H1 market context is unavailable.",
                    ),
                    block_end=block_end,
                    idle_seconds=idle_seconds,
                    promoted=None,
                )
                outputs.extend(self._append_once(watch, update, block_end, "PENDING_MARKET_CONTEXT"))
                continue

            decision = self._gate.evaluate(watch, market)
            if self._is_expired(watch, age_seconds) and not decision.is_confirmed:
                update = self._expired_update(
                    watch=watch,
                    decision=decision,
                    block_end=block_end,
                    idle_seconds=idle_seconds,
                )
                outputs.append(update)
                self._pending.pop(symbol, None)
                continue
            promoted = self._promote(watch, market, decision) if decision.is_confirmed else None
            if promoted is not None and _is_final_execution(promoted):
                outputs.append(_with_block_fields(promoted, watch, block_end, idle_seconds, decision))
                self._pending.pop(symbol, None)
                continue
            if self._is_expired(watch, age_seconds) and decision.is_confirmed:
                update = self._expired_update(
                    watch=watch,
                    decision=decision,
                    block_end=block_end,
                    idle_seconds=idle_seconds,
                )
                update["reason"] = (
                    f"Pending watch expired after {watch.expires_after_m15_bars} M15 bars; "
                    "direction confirmation existed but structure-aware tradeplan remained incomplete."
                )
                outputs.append(update)
                self._pending.pop(symbol, None)
                continue

            update = self._decision_update(
                watch=watch,
                decision=decision,
                block_end=block_end,
                idle_seconds=idle_seconds,
                promoted=promoted,
            )
            outputs.extend(self._append_once(watch, update, block_end, decision.confirmation))
        return outputs

    def _promote(
        self,
        watch: PendingDecisionState,
        market: Any,
        decision: M15CloseDecision,
    ) -> dict[str, Any] | None:
        cluster = _cluster_from_pending(watch)
        decision_market = _market_with_decision(market, decision)
        result = self._engine.evaluate(cluster, decision_market).to_dict()
        if result.get("status") == "NONE":
            return None
        for key, value in (
            (
                "key_resistance",
                _first_float(
                    watch.payload.get("key_resistance"),
                    watch.payload.get("breakout_reclaim_level"),
                    _field(market, "key_resistance"),
                    _field(market, "main_resistance"),
                    _field(market, "resistance_high"),
                ),
            ),
            (
                "key_support",
                _first_float(
                    watch.payload.get("key_support"),
                    watch.payload.get("support_reclaim_level"),
                    _field(market, "key_support"),
                    _field(market, "main_support"),
                    _field(market, "support_low"),
                ),
            ),
        ):
            if result.get(key) is None and value is not None:
                result[key] = value
        for key in ("breakout_buy_zone", "pullback_buy_zone", "sell_rejection_zone"):
            if result.get(key) is None and watch.payload.get(key) is not None:
                result[key] = watch.payload.get(key)
        result["previous_status"] = watch.status
        result["new_status"] = result.get("status")
        result["pending_decision_id"] = watch.pending_decision_id
        result["parent_event_type"] = "signal_watch_json"
        result["parent_event_exists"] = True
        result["parent_watch_id"] = watch.pending_decision_id
        result["parent_watch_required"] = True
        result["promotion_path"] = "WATCH_TO_FINAL"
        result["promotion_trigger"] = decision.confirmation
        result["m15_confirmation_status"] = decision.confirmation
        result["reason"] = f"{decision.reason} {result.get('reason') or ''}".strip()
        return result

    def _decision_update(
        self,
        *,
        watch: PendingDecisionState,
        decision: M15CloseDecision,
        block_end: datetime | None,
        idle_seconds: float,
        promoted: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = deepcopy(watch.payload)
        status = "WAIT_STRUCTURE_OR_NEXT_M15"
        action = "FETCH_M15_CLOSE_AND_SUPPORT_LADDER"
        if decision.confirmation == "PENDING_M15_CLOSE":
            action = "WAIT_NEXT_M15_CLOSE"
        elif promoted is not None and not _is_structure_ready_for_execution(promoted):
            action = "WAIT_STRUCTURE_TARGET_OR_SUPPORT_LADDER"

        payload.update(
            {
                "event": "signal_decision_update_json",
                "status": status,
                "previous_status": watch.status,
                "new_status": status,
                "final_direction": "WAIT",
                "validated_direction": _candidate_direction(watch.payload),
                "action": action,
                "next_action": action,
                "valid_for_execution": False,
                "is_final_signal": False,
                "confirmation_policy": decision.confirmation,
                "requires_m15_close": decision.confirmation == "PENDING_M15_CLOSE",
                "m15_confirmation_status": decision.confirmation,
                "pending_decision_id": watch.pending_decision_id,
                "parent_event_type": "signal_watch_json",
                "parent_event_exists": True,
                "parent_watch_id": watch.pending_decision_id,
                "parent_watch_required": True,
                "promotion_path": "WATCH_TO_DECISION_UPDATE",
                "promotion_trigger": decision.confirmation,
                "reason": _decision_update_reason(decision, promoted),
                "market_context_applied": decision.confirmation != "PENDING_MARKET_CONTEXT",
                "block_end_utc": None if block_end is None else block_end.isoformat(),
                "block_end_wita": None
                if block_end is None
                else block_end.astimezone(_TZ_WITA).strftime("%Y-%m-%d %H:%M:%S"),
                "block_idle_seconds": round(idle_seconds, 3),
            }
        )
        if promoted is not None:
            payload["source_status"] = promoted.get("status")
            payload["source_final_direction"] = promoted.get("final_direction")
            for key in (
                "target_mode",
                "tp_status",
                "tp_missing_reason",
                "support_ladder_ready",
                "resistance_ladder_ready",
                "structure_targets_available",
                "tradeplan_context_ready",
                "rr_status",
                "tp1",
                "tp2",
                "tp3",
                "tp4",
                "tp1_rr",
                "tp2_rr",
                "tp3_rr",
                "tp4_rr",
                "structure_ready",
                "rr_to_valid_target",
                "analysis_valid",
                "tradeplan_valid",
                "execution_valid_now",
                "execution_status",
                "execution_reason",
                "selected_sl_mode",
                "selected_sl",
                "risk_pips",
                "risk_pips_tight",
                "risk_pips_safe",
                "selected_risk_pips",
                "target_policy",
                "targets",
                "structure_zones",
                "risk_reward",
                "invalidation_rules",
                "execution_quality",
                "phase_coherence",
                "signal_expiry",
            ):
                if key in promoted:
                    payload[key] = promoted.get(key)
        return payload

    def _expired_update(
        self,
        *,
        watch: PendingDecisionState,
        decision: M15CloseDecision,
        block_end: datetime | None,
        idle_seconds: float,
    ) -> dict[str, Any]:
        payload = self._decision_update(
            watch=watch,
            decision=decision,
            block_end=block_end,
            idle_seconds=idle_seconds,
            promoted=None,
        )
        payload.update(
            {
                "status": "PENDING_WATCH_EXPIRED",
                "new_status": "PENDING_WATCH_EXPIRED",
                "action": "EXPIRE_PENDING_WATCH",
                "next_action": "REMOVE_PENDING_DECISION_STATE",
                "requires_m15_close": False,
                "reason": (
                    f"Pending watch expired after {watch.expires_after_m15_bars} M15 bars without confirmation."
                ),
            }
        )
        return payload

    @staticmethod
    def _is_expired(watch: PendingDecisionState, age_seconds: float) -> bool:
        return age_seconds >= watch.expires_after_m15_bars * 15.0 * 60.0

    def _append_once(
        self,
        watch: PendingDecisionState,
        payload: dict[str, Any],
        block_end: datetime | None,
        confirmation: str,
    ) -> list[dict[str, Any]]:
        decision_key = "|".join(
            [
                watch.pending_decision_id,
                confirmation,
                "" if block_end is None else block_end.isoformat(),
                str(payload.get("target_mode") or ""),
                str(payload.get("tp_missing_reason") or ""),
            ]
        )
        if watch.last_decision_key == decision_key:
            return []
        watch.last_decision_key = decision_key
        return [payload]


def _pending_from_payload(
    payload: dict[str, Any],
    *,
    expires_after_m15_bars: int,
) -> PendingDecisionState | None:
    symbol = str(payload.get("symbol") or "").upper()
    created = _coerce_datetime(payload.get("signal_valid_time_utc") or payload.get("signal_valid_time"))
    if not symbol or created is None:
        return None
    entry_zone = _float_list(payload.get("entry_zone"))
    return PendingDecisionState(
        symbol=symbol,
        cluster_id=_optional_str(payload.get("cluster_id")),
        watch_type=str(payload.get("decision_watch_type") or payload.get("status") or "PENDING_WATCH"),
        status=str(payload.get("status") or "PENDING_WATCH"),
        payload=deepcopy(payload),
        created_utc=created,
        signal_valid_price=_optional_float(payload.get("signal_valid_price") or payload.get("entry_reference_price")),
        entry_zone=entry_zone,
        expires_after_m15_bars=expires_after_m15_bars,
    )


def _cluster_from_pending(watch: PendingDecisionState) -> dict[str, Any]:
    payload = deepcopy(watch.payload)
    entry_start = (
        _zone_high(watch.entry_zone) if _candidate_direction(payload) == "SELL" else _zone_low(watch.entry_zone)
    )
    payload.update(
        {
            "symbol": watch.symbol,
            "cluster_id": watch.cluster_id,
            "direction": payload.get("raw_direction"),
            "end_utc": payload.get("signal_valid_time_utc"),
            "price_at_signal_start": entry_start or watch.signal_valid_price,
            "price_at_signal_end": watch.signal_valid_price,
            "market_context_applied": True,
        }
    )
    if payload.get("duration_seconds") is None and payload.get("duration_minutes") is not None:
        duration_minutes = _optional_float(payload.get("duration_minutes"))
        if duration_minutes is not None:
            payload["duration_seconds"] = duration_minutes * 60.0
    return payload


def _market_with_decision(market: Any, decision: M15CloseDecision) -> Any:
    updates: dict[str, Any] = {}
    if decision.confirmation == "M15_CLOSE_REJECTION_CONFIRMED" and decision.final_direction == "SELL":
        updates["m15_rejection_from_resistance"] = True
        updates["m15_close_above_resistance"] = False
    elif decision.confirmation == "M15_CLOSE_REJECTION_CONFIRMED" and decision.final_direction == "BUY":
        updates["m15_rejection_from_support"] = True
        updates["m15_close_below_support"] = False
    elif decision.confirmation == "M15_CLOSE_ABOVE_RESISTANCE":
        updates["m15_close_above_resistance"] = True
    elif decision.confirmation == "M15_CLOSE_BELOW_SUPPORT":
        updates["m15_close_below_support"] = True

    if not updates:
        return market
    if isinstance(market, MarketContext):
        return replace(market, **updates)
    if isinstance(market, dict):
        merged = dict(market)
        merged.update(updates)
        return merged
    return market


def _with_block_fields(
    payload: dict[str, Any],
    watch: PendingDecisionState,
    block_end: datetime | None,
    idle_seconds: float,
    decision: M15CloseDecision,
) -> dict[str, Any]:
    payload = dict(payload)
    for key in (
        "key_resistance",
        "key_support",
        "breakout_reclaim_level",
        "support_reclaim_level",
        "breakout_buy_zone",
        "pullback_buy_zone",
        "sell_rejection_zone",
        "decision_watch_type",
        "buy_condition",
        "sell_condition",
    ):
        if payload.get(key) is None and watch.payload.get(key) is not None:
            payload[key] = watch.payload.get(key)
    payload.update(
        {
            "event": "signal_json",
            "previous_status": watch.status,
            "new_status": payload.get("status"),
            "block_end_utc": None if block_end is None else block_end.isoformat(),
            "block_end_wita": None
            if block_end is None
            else block_end.astimezone(_TZ_WITA).strftime("%Y-%m-%d %H:%M:%S"),
            "block_idle_seconds": round(idle_seconds, 3),
            "pending_decision_id": watch.pending_decision_id,
            "parent_event_type": "signal_watch_json",
            "parent_event_exists": True,
            "parent_watch_id": watch.pending_decision_id,
            "parent_watch_required": True,
            "promotion_path": "WATCH_TO_FINAL",
            "promotion_trigger": decision.confirmation,
            "m15_confirmation_status": decision.confirmation,
        }
    )
    return payload


def _activity_for_symbol(report: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    normalized = symbol.upper()
    activity = report.get("symbol_activity")
    if isinstance(activity, dict):
        direct = activity.get(normalized) or activity.get(symbol)
        if isinstance(direct, dict):
            return direct

    candidates: list[dict[str, Any]] = []
    for section in ("top_microboost", "top_clean_blocks"):
        rows = report.get(section)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and str(row.get("symbol") or "").upper() == normalized:
                candidates.append(row)
    if not candidates:
        return None
    latest = max(candidates, key=lambda item: str(item.get("end_utc") or item.get("end") or ""))
    return {
        "latest_block_end_utc": latest.get("end_utc") or latest.get("end"),
        "latest_event_utc": latest.get("end_utc") or latest.get("end"),
    }


def _context_for_symbol(market_contexts: dict[str, Any], symbol: str) -> Any | None:
    normalized = symbol.upper()
    return market_contexts.get(normalized) or market_contexts.get(symbol) or market_contexts.get(symbol.lower())


def _decision_update_reason(decision: M15CloseDecision, promoted: dict[str, Any] | None) -> str:
    if promoted is None:
        return decision.reason
    missing = promoted.get("tp_missing_reason") or "structure_target_incomplete"
    return f"{decision.reason} Final execution is still blocked because {missing}."


def _is_pending_watch(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "")
    return (
        status in PENDING_WATCH_STATUSES
        and str(payload.get("final_direction") or "WAIT").upper() == "WAIT"
        and not bool(payload.get("valid_for_execution", False))
    ) or (bool(payload.get("pending_decision_id")) and _optional_bool(payload.get("requires_m15_close")) is True)


def _is_final_execution(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "")
    return (
        str(payload.get("final_direction") or "").upper() in {"BUY", "SELL"}
        and bool(payload.get("valid_for_execution", False))
        and (status in FINAL_EXECUTION_STATUSES or status.endswith("_VALID"))
        and _tp1_rr_meets_minimum(payload)
        and _counter_entry_execution_contract_complete(payload)
    )


def _is_structure_ready_for_execution(payload: dict[str, Any]) -> bool:
    return bool(payload.get("structure_ready") or payload.get("tradeplan_context_ready")) and (
        _counter_entry_execution_contract_complete(payload)
    )


def _counter_entry_execution_contract_complete(payload: dict[str, Any]) -> bool:
    family = str(payload.get("signal_family") or "").upper()
    if family != "MICROBOOST_COUNTER_ENTRY":
        return True
    if str(payload.get("target_mode") or "").upper() != "FINAL_MARKET_STRUCTURE":
        return False
    zones = payload.get("structure_zones")
    invalidation = payload.get("invalidation_rules")
    targets = payload.get("targets")
    execution_quality = payload.get("execution_quality")
    phase_coherence = payload.get("phase_coherence")
    signal_expiry = payload.get("signal_expiry")
    return bool(
        payload.get("tradeplan_valid") is True
        and payload.get("execution_valid_now") is True
        and _optional_float(payload.get("selected_sl")) is not None
        and _optional_float(payload.get("selected_risk_pips") or payload.get("risk_pips")) is not None
        and _optional_float(payload.get("tp_min_rr")) is not None
        and isinstance(zones, dict)
        and _optional_float(zones.get("key_resistance")) is not None
        and _optional_float(zones.get("key_support")) is not None
        and isinstance(invalidation, dict)
        and _optional_float(invalidation.get("hard_invalid_level")) is not None
        and isinstance(targets, list)
        and bool(targets)
        and isinstance(execution_quality, dict)
        and execution_quality.get("spread_normal") is True
        and isinstance(phase_coherence, dict)
        and phase_coherence.get("status") == "EXECUTION_COMPATIBLE"
        and isinstance(signal_expiry, dict)
        and _optional_str(signal_expiry.get("expires_at_utc")) is not None
    )


def _tp1_rr_meets_minimum(payload: dict[str, Any]) -> bool:
    tp1_rr = _optional_float(payload.get("tp1_rr"))
    return tp1_rr is not None and tp1_rr >= MIN_EXECUTABLE_TP1_RR


def _candidate_direction(payload: dict[str, Any]) -> str | None:
    for key in ("candidate_direction", "validated_direction", "final_direction"):
        value = str(payload.get(key) or "").upper()
        if value in {"BUY", "SELL"}:
            return value
    status = str(payload.get("status") or "").upper()
    if "SELL" in status:
        return "SELL"
    if "BUY" in status:
        return "BUY"
    return None


def _field(source: Any, name: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, MarketContext):
        return getattr(source, name, default)
    if isinstance(source, dict):
        snapshot = source.get("market_context_snapshot")
        if name in source:
            return source.get(name, default)
        if isinstance(snapshot, dict) and name in snapshot:
            return snapshot.get(name, default)
        return default
    return getattr(source, name, default)


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _elapsed_seconds(now: datetime, then: datetime | None) -> float:
    if then is None:
        return 0.0
    return max(0.0, (now - then).total_seconds())


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    values: list[float] = []
    for item in value:
        number = _optional_float(item)
        if number is not None:
            values.append(number)
    return values


def _first_float(*values: Any) -> float | None:
    for value in values:
        number = _optional_float(value)
        if number is not None:
            return number
    return None


def _zone_high(values: list[float]) -> float | None:
    return max(values) if values else None


def _zone_low(values: list[float]) -> float | None:
    return min(values) if values else None
