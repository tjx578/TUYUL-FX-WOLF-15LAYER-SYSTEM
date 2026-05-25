"""Trend-continuation signal promotion for priced microboost clusters.

Counter-entry logic treats dense pressure at main extremes as absorption.  This
module handles the opposite case: pressure that appears away from the main
extreme while SignalThrottle allowed quorum and timeframe context agree.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class MicroboostContinuationResult:
    enabled: bool
    status: str
    symbol: str
    signal_type: str
    signal_family: str
    cluster_id: str | None
    raw_direction: str | None
    candidate_direction: str | None
    validated_direction: str | None
    final_direction: str
    direction_status: str
    phase_unpriced: str | None
    phase_priced: str | None
    action: str
    reason: str
    signal_valid_time: str | None = None
    signal_valid_time_utc: str | None = None
    signal_valid_time_wita: str | None = None
    signal_valid_price: float | None = None
    entry_reference_price: float | None = None
    entry_zone: list[float] | None = None
    reclaim_trigger: float | None = None
    sl_tight: float | None = None
    sl_safe: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    tp3: float | None = None
    tp4: float | None = None
    rr_to_tp1_tight: float | None = None
    rr_to_tp2_tight: float | None = None
    rr_to_tp3_tight: float | None = None
    rr_status: str = "UNVALIDATED"
    market_context_applied: bool = False
    price_position: str | None = None
    m15_phase: str | None = None
    h1_phase: str | None = None
    effective_density: float | None = None
    effective_ticks: int | None = None
    duration_seconds: float | None = None
    duration_minutes: float | None = None
    price_delta_pips: float | None = None
    allowed_quorum: bool = False
    allowed_quorum_streak: int | None = None
    confidence_bucket: str | None = None
    invalidation: str | None = None
    trade_plan: dict[str, Any] | None = None
    target_mode: str | None = None
    tp_status: str | None = None
    tp_missing_reason: str | None = None
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
    risk_pips: float | None = None
    support_ladder_ready: bool | None = None
    resistance_ladder_ready: bool | None = None
    signal_archetype: str | None = None
    trend_following: bool | None = None
    analysis_valid: bool = False
    tradeplan_valid: bool = False
    execution_valid_now: bool = False
    execution_status: str | None = None
    execution_reason: str | None = None
    selected_sl_mode: str | None = None
    selected_sl: float | None = None
    risk_pips_tight: float | None = None
    risk_pips_safe: float | None = None
    selected_risk_pips: float | None = None
    target_policy: dict[str, Any] | None = None
    targets: list[dict[str, Any]] | None = None
    structure_zones: dict[str, Any] | None = None
    risk_reward: dict[str, Any] | None = None
    invalidation_rules: dict[str, Any] | None = None
    execution_quality: dict[str, Any] | None = None
    phase_coherence: dict[str, Any] | None = None
    signal_expiry: dict[str, Any] | None = None
    confirmation_policy: str | None = None
    requires_m15_close: bool | None = None
    m15_confirmation_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MicroboostContinuationEngine:
    """Promote aligned MID_RANGE microboost + allowed quorum into continuation."""

    def __init__(
        self,
        *,
        min_density_per_minute: float = 25.0,
        min_duration_seconds: float = 60.0,
        min_rr_valid: float = 2.5,
        tp1_rr_required: float = 2.0,
        allow_rr_fallback: bool = True,
        continuation_expiry_minutes: int = 45,
    ) -> None:
        self.min_density_per_minute = min_density_per_minute
        self.min_duration_seconds = min_duration_seconds
        self.min_rr_valid = min_rr_valid
        self.tp1_rr_required = max(2.0, float(tp1_rr_required))
        self.allow_rr_fallback = allow_rr_fallback
        self.continuation_expiry_minutes = max(1, int(continuation_expiry_minutes))

    def evaluate(
        self,
        cluster: Any,
        *,
        allowed_quorum: dict[str, Any] | None = None,
    ) -> MicroboostContinuationResult:
        snapshot = _snapshot(cluster)
        symbol = str(_field(cluster, "symbol", _field(snapshot, "symbol", ""))).upper()
        raw_direction = _normalize_direction(_field(cluster, "raw_direction", _field(cluster, "direction", None)))
        phase_priced = _optional_str(_field(cluster, "phase_priced", None))
        phase_unpriced = _optional_str(_field(cluster, "phase_unpriced", None))
        price_position = _normalize_position(
            _field(cluster, "price_position", _field(snapshot, "price_position", None))
        )
        h1_phase = _optional_str(_field(cluster, "h1_phase", _field(snapshot, "h1_phase", None)))
        m15_phase = _optional_str(_field(cluster, "m15_phase", _field(snapshot, "m15_phase", None)))
        density = _optional_float(
            _field(cluster, "effective_density", _field(cluster, "effective_density_per_minute", None))
        )
        duration_seconds = _optional_float(
            _field(cluster, "duration_seconds", _field(cluster, "cluster_age_seconds", None))
        )
        effective_ticks = _optional_int(
            _field(cluster, "effective_ticks", _field(cluster, "effective_tick_count", None))
        )
        pip_value = _pip_value(symbol, _field(snapshot, "pip_value", None))
        price_start = _price_start(cluster, snapshot)
        price_end = _price_end(cluster, snapshot)
        entry_reference = price_end if price_end is not None else price_start
        signal_time = _optional_str(_field(cluster, "end_utc", _field(cluster, "signal_valid_time", None)))
        signal_time_utc = _normalize_utc_time(signal_time)
        quorum = allowed_quorum or {}
        quorum_ok = (
            bool(quorum.get("quorum_reached"))
            and str(quorum.get("symbol") or "").upper() == symbol
            and _normalize_direction(quorum.get("direction")) == raw_direction
        )
        breakout_context = _is_breakout_continuation_context(
            direction=raw_direction,
            price_position=price_position,
            phase_priced=phase_priced,
            snapshot=snapshot,
        )
        entry_zone = _continuation_entry_zone(
            price_start=price_start,
            price_end=price_end,
            direction=raw_direction,
            snapshot=snapshot,
            breakout_context=breakout_context,
        )

        base = {
            "symbol": symbol,
            "cluster_id": _optional_str(_field(cluster, "cluster_id", None)),
            "raw_direction": raw_direction,
            "phase_unpriced": phase_unpriced,
            "phase_priced": phase_priced,
            "signal_valid_time": signal_time,
            "signal_valid_time_utc": signal_time_utc,
            "signal_valid_time_wita": _wita_time(signal_time_utc),
            "signal_valid_price": entry_reference,
            "entry_reference_price": entry_reference,
            "entry_zone": entry_zone,
            "market_context_applied": snapshot is not None,
            "price_position": price_position,
            "m15_phase": m15_phase,
            "h1_phase": h1_phase,
            "effective_density": density,
            "effective_ticks": effective_ticks,
            "duration_seconds": duration_seconds,
            "duration_minutes": round(duration_seconds / 60.0, 2) if duration_seconds is not None else None,
            "price_delta_pips": _price_delta_pips(price_start, price_end, pip_value),
            "allowed_quorum": quorum_ok,
            "allowed_quorum_streak": _optional_int(quorum.get("streak")),
        }

        if not self._is_valid_continuation_context(
            raw_direction=raw_direction,
            phase_priced=phase_priced,
            price_position=price_position,
            h1_phase=h1_phase,
            m15_phase=m15_phase,
            density=density,
            duration_seconds=duration_seconds,
            quorum_ok=quorum_ok,
            market_context_applied=snapshot is not None,
            breakout_context=breakout_context,
        ):
            return self._result(
                enabled=False,
                status="NONE",
                candidate_direction=None,
                final_direction="WAIT",
                direction_status="NO_CONTINUATION_CONDITION",
                action="NO_CONTINUATION_ENTRY",
                reason="continuation_requires_allowed_quorum_trend_context_and_mid_range_microboost",
                **base,
            )

        levels = _continuation_levels(
            direction=str(raw_direction),
            entry=entry_reference,
            entry_zone=base["entry_zone"],
            snapshot=snapshot,
            pip_value=pip_value,
            min_rr=self.min_rr_valid,
            tp1_rr=self.tp1_rr_required,
            allow_rr_fallback=self.allow_rr_fallback,
        )
        model_fields = _continuation_model_fields(
            direction=str(raw_direction),
            snapshot=snapshot,
            entry=entry_reference,
            entry_zone=base["entry_zone"],
            pip_value=pip_value,
            levels=levels,
            breakout_context=breakout_context,
            signal_time_utc=signal_time_utc,
            expiry_minutes=self.continuation_expiry_minutes,
        )
        executable = bool(model_fields["execution_valid_now"])
        signal_family = "MICROBOOST_BREAKOUT_CONTINUATION" if breakout_context else "MICROBOOST_TREND_CONTINUATION"
        if breakout_context:
            status = _breakout_status(str(raw_direction), executable)
            action = (
                ("BUY_BREAKOUT_RETEST_ENTRY" if raw_direction == "BUY" else "SELL_BREAKDOWN_RETEST_ENTRY")
                if executable
                else ("WAIT_BUY_RETEST_OR_BREAKOUT_HOLD" if raw_direction == "BUY" else "WAIT_SELL_RETEST_OR_BREAKDOWN_HOLD")
            )
        elif executable:
            status = f"{raw_direction}_TIMING_VALID_BY_QUORUM_CONTINUATION"
            action = "BUY_SIGNAL_ZONE_OR_RETEST" if raw_direction == "BUY" else "SELL_SIGNAL_ZONE_OR_RETEST"
        else:
            status = f"{raw_direction}_CONTINUATION_TRADEPLAN_WATCH"
            action = "WAIT_STRUCTURE_TARGET_OR_RETEST"
        return self._result(
            enabled=True,
            signal_family=signal_family,
            status=status,
            candidate_direction=raw_direction,
            validated_direction=raw_direction,
            final_direction=raw_direction if executable else "WAIT",
            direction_status=(
                "BREAKOUT_RETEST_CONTINUATION_VALIDATED"
                if executable and breakout_context
                else (
                    "BREAKOUT_DIRECTION_VALID_TRADEPLAN_OR_RETEST_PENDING"
                    if breakout_context
                    else ("MICROBOOST_QUORUM_CONTINUATION_VALIDATED" if executable else "CONTINUATION_TRADEPLAN_PENDING")
                )
            ),
            action=action,
            reason=(
                f"{symbol} {raw_direction} {'breakout-retest ' if breakout_context else ''}continuation: "
                f"allowed quorum, high-density microboost, {price_position} price position, "
                f"H1 {h1_phase}, and M15 {m15_phase} provide direction evidence; "
                f"execution_status={model_fields['execution_status']}."
            ),
            reclaim_trigger=levels["reclaim_trigger"],
            sl_tight=levels["sl_tight"],
            sl_safe=levels["sl_safe"],
            tp1=levels["tp1"],
            tp2=levels["tp2"],
            tp3=levels["tp3"],
            tp4=levels["tp4"],
            rr_to_tp1_tight=levels["tp1_rr"],
            rr_to_tp2_tight=levels["tp2_rr"],
            rr_to_tp3_tight=levels["tp3_rr"],
            rr_status="VALID" if executable else "WATCH_PROVISIONAL",
            confidence_bucket="A_CONTINUATION_VALID" if executable else "B_CONTINUATION_WATCH",
            invalidation=levels["invalidation"],
            trade_plan=levels["trade_plan"],
            target_mode=levels["target_mode"],
            tp_status=levels["tp_status"],
            tp_missing_reason=levels["tp_missing_reason"],
            structure_targets_available=levels["structure_targets_available"],
            tradeplan_context_ready=bool(model_fields["tradeplan_valid"]),
            valid_for_execution=executable,
            min_rr_required=self.min_rr_valid,
            tp_min_rr=levels["tp_min_rr"],
            tp_min_rr_value=levels["tp_min_rr_value"],
            tp1_rr=levels["tp1_rr"],
            tp2_rr=levels["tp2_rr"],
            tp3_rr=levels["tp3_rr"],
            tp4_rr=levels["tp4_rr"],
            risk_pips=levels["selected_risk_pips"],
            support_ladder_ready=_optional_bool(_field(snapshot, "support_ladder_ready", None)),
            resistance_ladder_ready=_optional_bool(_field(snapshot, "resistance_ladder_ready", None)),
            **model_fields,
            **base,
        )

    def evaluate_report(self, report: dict[str, Any]) -> MicroboostContinuationResult | None:
        summary = report.get("microboost_summary")
        if not isinstance(summary, dict):
            return None
        latest = summary.get("latest")
        if not isinstance(latest, dict):
            return None
        return self.evaluate(latest, allowed_quorum=report.get("allowed_quorum"))

    def _is_valid_continuation_context(
        self,
        *,
        raw_direction: str | None,
        phase_priced: str | None,
        price_position: str | None,
        h1_phase: str | None,
        m15_phase: str | None,
        density: float | None,
        duration_seconds: float | None,
        quorum_ok: bool,
        market_context_applied: bool,
        breakout_context: bool,
    ) -> bool:
        if raw_direction not in {"BUY", "SELL"}:
            return False
        if not quorum_ok or not market_context_applied:
            return False
        if breakout_context:
            valid_phase = phase_priced in {
                "RESISTANCE_PRESSURE_WARNING",
                "EXHAUSTION_AT_RESISTANCE",
                "SUPPORT_PRESSURE_WARNING",
                "EXHAUSTION_AT_SUPPORT",
            }
            valid_position = price_position in {"MAIN_RESISTANCE", "UPPER_RANGE", "MAIN_SUPPORT", "LOWER_RANGE"}
        else:
            valid_phase = phase_priced in {
                "TREND_CONTINUATION_MICROBOOST",
                "CONTINUATION_MICROBOOST",
                "CONFIRMATION_MICROBOOST",
            }
            valid_position = price_position in {"MID_RANGE", "PULLBACK_ZONE"}
        if not valid_phase or not valid_position:
            return False
        if density is None or density < self.min_density_per_minute:
            return False
        if duration_seconds is None or duration_seconds < self.min_duration_seconds:
            return False
        return _phase_direction(h1_phase) == raw_direction and _phase_direction(m15_phase) == raw_direction

    @staticmethod
    def _result(**kwargs: Any) -> MicroboostContinuationResult:
        kwargs.setdefault("signal_family", "MICROBOOST_TREND_CONTINUATION")
        kwargs.setdefault("cluster_id", None)
        kwargs.setdefault("validated_direction", kwargs.get("candidate_direction"))
        return MicroboostContinuationResult(signal_type=str(kwargs.get("signal_family")), **kwargs)


def _is_breakout_continuation_context(
    *,
    direction: str | None,
    price_position: str | None,
    phase_priced: str | None,
    snapshot: dict[str, Any] | None,
) -> bool:
    if direction == "BUY":
        return bool(
            price_position in {"MAIN_RESISTANCE", "UPPER_RANGE"}
            and phase_priced in {"RESISTANCE_PRESSURE_WARNING", "EXHAUSTION_AT_RESISTANCE"}
            and _optional_bool(_field(snapshot, "m15_close_above_resistance", None)) is True
        )
    if direction == "SELL":
        return bool(
            price_position in {"MAIN_SUPPORT", "LOWER_RANGE"}
            and phase_priced in {"SUPPORT_PRESSURE_WARNING", "EXHAUSTION_AT_SUPPORT"}
            and _optional_bool(_field(snapshot, "m15_close_below_support", None)) is True
        )
    return False


def _continuation_entry_zone(
    *,
    price_start: float | None,
    price_end: float | None,
    direction: str | None,
    snapshot: dict[str, Any] | None,
    breakout_context: bool,
) -> list[float] | None:
    if breakout_context and direction == "BUY":
        low = _optional_float(_field(snapshot, "breakout_retest_low", None))
        high = _optional_float(_field(snapshot, "breakout_retest_high", None))
        if low is not None and high is not None:
                return [round(min(low, high), 5), round(max(low, high), 5)]
    return _entry_zone(price_start, price_end)


def _breakout_status(direction: str, executable: bool) -> str:
    if direction == "BUY":
        return "BUY_BREAKOUT_RETEST_VALID" if executable else "BUY_BREAKOUT_RETEST_WATCH"
    return "SELL_BREAKDOWN_RETEST_VALID" if executable else "SELL_BREAKDOWN_RETEST_WATCH"


def _continuation_levels(
    *,
    direction: str,
    entry: float | None,
    entry_zone: list[float] | None,
    snapshot: dict[str, Any] | None,
    pip_value: float,
    min_rr: float,
    tp1_rr: float,
    allow_rr_fallback: bool,
) -> dict[str, Any]:
    digits = _digits(pip_value)
    zone = entry_zone or ([] if entry is None else [entry, entry])
    zone_low = min(zone) if zone else entry
    zone_high = max(zone) if zone else entry
    if direction == "BUY":
        structure_sl = _optional_float(
            _field(
                snapshot,
                "continuation_sl_tight",
                _field(snapshot, "sl_tight", _field(snapshot, "support_low", _field(snapshot, "main_support", None))),
            )
        )
        fallback_sl = None if zone_low is None else zone_low - (12.0 * pip_value)
        sl_tight = structure_sl if _valid_stop(direction, entry, structure_sl) else fallback_sl
        explicit_safe = _optional_float(_field(snapshot, "continuation_sl_safe", _field(snapshot, "sl_safe", None)))
        sl_safe = explicit_safe if _valid_stop(direction, entry, explicit_safe) else _safe_stop(direction, sl_tight, pip_value)
        targets = _sorted_targets(
            direction,
            entry,
            [
                _field(snapshot, "tp1_resistance", None),
                _field(snapshot, "minor_resistance", None),
                _field(snapshot, "tp2_resistance", None),
                _field(snapshot, "main_resistance", None),
                _field(snapshot, "tp3_resistance", None),
                _field(snapshot, "tp4_resistance", None),
            ],
        )
        reclaim_trigger = targets[0] if targets else None
        invalidation = "M15 failure below signal zone"
    else:
        structure_sl = _optional_float(
            _field(
                snapshot,
                "continuation_sl_tight",
                _field(snapshot, "sl_tight", _field(snapshot, "resistance_high", _field(snapshot, "main_resistance", None))),
            )
        )
        fallback_sl = None if zone_high is None else zone_high + (12.0 * pip_value)
        sl_tight = structure_sl if _valid_stop(direction, entry, structure_sl) else fallback_sl
        explicit_safe = _optional_float(_field(snapshot, "continuation_sl_safe", _field(snapshot, "sl_safe", None)))
        sl_safe = explicit_safe if _valid_stop(direction, entry, explicit_safe) else _safe_stop(direction, sl_tight, pip_value)
        targets = _sorted_targets(
            direction,
            entry,
            [
                _field(snapshot, "tp1_support", None),
                _field(snapshot, "minor_support", None),
                _field(snapshot, "tp2_support", None),
                _field(snapshot, "main_support", None),
                _field(snapshot, "tp3_support", None),
                _field(snapshot, "tp4_support", None),
            ],
        )
        reclaim_trigger = targets[0] if targets else None
        invalidation = (
            f"M15 failure above {_round_price(sl_safe, digits)}"
            if sl_safe is not None
            else "M15 failure above signal zone"
        )

    selected_sl = sl_safe or sl_tight
    if direction == "BUY":
        invalidation = (
            f"M15 failure below {_round_price(selected_sl, digits)}"
            if selected_sl is not None
            else "M15 failure below signal zone"
        )
    selected_rr = _first_rr_at_least(direction, entry, selected_sl, targets, min_rr)
    if selected_rr is not None:
        ladder = _target_ladder_with_fixed_tp1(direction, entry, selected_sl, targets, tp1_rr)
        return _level_payload(
            direction=direction,
            entry=entry,
            sl_tight=sl_tight,
            sl_safe=sl_safe,
            selected_sl=selected_sl,
            targets=ladder,
            target_mode="FINAL_MARKET_STRUCTURE",
            tp_status="VALID",
            tp_missing_reason=None,
            structure_targets_available=True,
            structure_rr_valid=True,
            tp1_rr_required=tp1_rr,
            min_rr=min_rr,
            reclaim_trigger=reclaim_trigger,
            invalidation=invalidation,
            digits=digits,
            pip_value=pip_value,
        )

    if allow_rr_fallback and entry is not None and selected_sl is not None:
        fallback_targets: list[float | None] = _rr_fallback_targets(direction, entry, selected_sl, min_rr, tp1_rr)
        return _level_payload(
            direction=direction,
            entry=entry,
            sl_tight=sl_tight,
            sl_safe=sl_safe,
            selected_sl=selected_sl,
            targets=fallback_targets,
            target_mode="PROVISIONAL_RR_FALLBACK",
            tp_status="VALID_FROM_TP3",
            tp_missing_reason="STRUCTURE_TARGET_MISSING_OR_BELOW_MIN_RR",
            structure_targets_available=bool(targets),
            structure_rr_valid=False,
            tp1_rr_required=tp1_rr,
            min_rr=min_rr,
            reclaim_trigger=reclaim_trigger,
            invalidation=invalidation,
            digits=digits,
            pip_value=pip_value,
        )

    return _level_payload(
        direction=direction,
        entry=entry,
        sl_tight=sl_tight,
        sl_safe=sl_safe,
        selected_sl=selected_sl,
        targets=[None, None, None, None],
        target_mode="NONE",
        tp_status="WAIT_TARGET_STRUCTURE",
        tp_missing_reason="NO_CONTINUATION_TARGETS",
        structure_targets_available=False,
        structure_rr_valid=False,
        tp1_rr_required=tp1_rr,
        min_rr=min_rr,
        reclaim_trigger=reclaim_trigger,
        invalidation=invalidation,
        digits=digits,
        pip_value=pip_value,
    )


def _continuation_model_fields(
    *,
    direction: str,
    snapshot: dict[str, Any] | None,
    entry: float | None,
    entry_zone: list[float] | None,
    pip_value: float,
    levels: dict[str, Any],
    breakout_context: bool,
    signal_time_utc: str | None,
    expiry_minutes: int,
) -> dict[str, Any]:
    key_support = _first_float(
        _field(snapshot, "key_support", None),
        _field(snapshot, "support_low", None),
        _field(snapshot, "main_support", None),
    )
    key_resistance = _first_float(
        _field(snapshot, "key_resistance", None),
        _field(snapshot, "main_resistance", None),
        _field(snapshot, "resistance_high", None),
    )
    selected_sl = _optional_float(levels.get("selected_sl"))
    targets = levels.get("targets")
    signal_expiry = _signal_expiry(signal_time_utc, expiry_minutes)
    tradeplan_valid = bool(
        isinstance(entry_zone, list)
        and entry_zone
        and selected_sl is not None
        and key_support is not None
        and key_resistance is not None
        and levels.get("structure_rr_valid") is True
        and isinstance(targets, list)
        and len(targets) >= 2
    )
    phase_ready = (
        _phase_direction(_optional_str(_field(snapshot, "h1_phase", None))) == direction
        and _phase_direction(_optional_str(_field(snapshot, "m15_phase", None))) == direction
    )
    if breakout_context:
        retest_field = "m15_breakout_retest_held" if direction == "BUY" else "m15_breakdown_retest_held"
        confirmation_ready = _optional_bool(_field(snapshot, retest_field, None)) is True
    else:
        confirmation_ready = phase_ready
    spread_normal = _optional_bool(_field(snapshot, "spread_normal", None))
    execution_valid_now = bool(
        tradeplan_valid and phase_ready and confirmation_ready and spread_normal is True and signal_expiry is not None
    )
    if execution_valid_now:
        execution_status = "VALID_BREAKOUT_RETEST_CONTINUATION" if breakout_context else "VALID_TREND_CONTINUATION"
        execution_reason = "structure_rr_retest_phase_and_spread_gates_passed"
    elif not tradeplan_valid:
        execution_status = "WAIT_STRUCTURE_TARGET"
        execution_reason = "structure_targets_or_selected_risk_incomplete"
    elif not confirmation_ready:
        execution_status = "WAIT_RETEST_OR_BREAKOUT_HOLD" if breakout_context else "WAIT_RETEST_CONFIRMATION"
        execution_reason = "breakout_direction_confirmed_but_retest_hold_not_confirmed"
    elif spread_normal is not True:
        execution_status = "WAIT_SPREAD_NORMALIZATION"
        execution_reason = "spread_gate_not_confirmed"
    else:
        execution_status = "WAIT_EXECUTION_REVALIDATION"
        execution_reason = "continuation_execution_gate_pending"
    return {
        "signal_archetype": (
            "BULLISH_BREAKOUT_RETEST_CONTINUATION"
            if breakout_context and direction == "BUY"
            else (
                "BEARISH_BREAKDOWN_RETEST_CONTINUATION"
                if breakout_context
                else f"{direction}_TREND_CONTINUATION"
            )
        ),
        "trend_following": True,
        "analysis_valid": True,
        "tradeplan_valid": tradeplan_valid,
        "execution_valid_now": execution_valid_now,
        "execution_status": execution_status,
        "execution_reason": execution_reason,
        "selected_sl_mode": "SAFE" if levels.get("sl_safe") is not None else "TIGHT",
        "selected_sl": selected_sl,
        "risk_pips_tight": levels.get("risk_pips_tight"),
        "risk_pips_safe": levels.get("risk_pips_safe"),
        "selected_risk_pips": levels.get("selected_risk_pips"),
        "target_policy": levels.get("target_policy"),
        "targets": targets,
        "structure_zones": {
            "price_position": _optional_str(_field(snapshot, "price_position", None)),
            "key_support": _round_price(key_support),
            "key_resistance": _round_price(key_resistance),
            "entry_zone": entry_zone,
            "breakout_retest_zone": entry_zone if breakout_context else None,
            "range_low": _round_price(_optional_float(_field(snapshot, "main_support", None))),
            "range_high": _round_price(_optional_float(_field(snapshot, "main_resistance", None))),
        },
        "risk_reward": {
            "entry": entry,
            "sl_tight": levels.get("sl_tight"),
            "sl_safe": levels.get("sl_safe"),
            "selected_sl": selected_sl,
            "risk_pips_tight": levels.get("risk_pips_tight"),
            "risk_pips_safe": levels.get("risk_pips_safe"),
            "selected_risk_pips": levels.get("selected_risk_pips"),
            "tp_min_rr": levels.get("tp_min_rr"),
            "tp1_rr": levels.get("tp1_rr"),
            "min_structure_rr_required": levels.get("tp_min_rr_value"),
            "rr_status": "VALID" if tradeplan_valid else "WATCH_PROVISIONAL",
        },
        "invalidation_rules": {
            "soft_invalid_level": levels.get("sl_tight"),
            "hard_invalid_level": selected_sl,
            "m15_close_invalid_below": levels.get("sl_tight") if direction == "BUY" else None,
            "m15_close_invalid_above": levels.get("sl_tight") if direction == "SELL" else None,
            "direction": direction,
            "rule": "BREAKOUT_RETEST_FAILURE_BEYOND_SELECTED_STOP" if breakout_context else "TREND_RECLAIM_FAILURE",
        },
        "execution_quality": {
            "spread_pips": _optional_float(_field(snapshot, "spread_pips", None)),
            "max_allowed_spread_pips": _optional_float(_field(snapshot, "max_allowed_spread_pips", None)),
            "spread_normal": spread_normal,
        },
        "phase_coherence": {
            "m15": _optional_str(_field(snapshot, "m15_phase", None)),
            "h1": _optional_str(_field(snapshot, "h1_phase", None)),
            "h4": _optional_str(_field(snapshot, "h4_phase", None)),
            "status": "EXECUTION_COMPATIBLE" if phase_ready else "TIMEFRAME_DIRECTION_CONFLICT",
        },
        "signal_expiry": signal_expiry,
        "confirmation_policy": "BREAKOUT_RETEST_HOLD_REQUIRED" if breakout_context else "TREND_RETEST_OR_HOLD_REQUIRED",
        "requires_m15_close": not confirmation_ready,
        "m15_confirmation_status": (
            "M15_BREAKOUT_RETEST_HELD"
            if breakout_context and direction == "BUY" and confirmation_ready
            else (
                "M15_BREAKDOWN_RETEST_HELD"
                if breakout_context and confirmation_ready
                else ("M15_BREAKOUT_DIRECTION_CONFIRMED_RETEST_PENDING" if breakout_context else "M15_TREND_ALIGNED")
            )
        ),
    }


def _level_payload(
    *,
    direction: str,
    entry: float | None,
    sl_tight: float | None,
    sl_safe: float | None,
    selected_sl: float | None,
    targets: Sequence[float | None],
    target_mode: str,
    tp_status: str,
    tp_missing_reason: str | None,
    structure_targets_available: bool,
    structure_rr_valid: bool,
    tp1_rr_required: float,
    min_rr: float,
    reclaim_trigger: float | None,
    invalidation: str,
    digits: int,
    pip_value: float,
) -> dict[str, Any]:
    tp1, tp2, tp3, tp4 = targets[:4]
    return {
        "sl_tight": _round_price(sl_tight, digits),
        "sl_safe": _round_price(sl_safe, digits),
        "selected_sl": _round_price(selected_sl, digits),
        "tp1": _round_price(tp1, digits),
        "tp2": _round_price(tp2, digits),
        "tp3": _round_price(tp3, digits),
        "tp4": _round_price(tp4, digits),
        "tp1_rr": _rr(direction, entry, selected_sl, tp1),
        "tp2_rr": _rr(direction, entry, selected_sl, tp2),
        "tp3_rr": _rr(direction, entry, selected_sl, tp3),
        "tp4_rr": _rr(direction, entry, selected_sl, tp4),
        "rr_status": "VALID" if structure_rr_valid else "WATCH_PROVISIONAL",
        "target_mode": target_mode,
        "tp_status": tp_status,
        "tp_missing_reason": tp_missing_reason,
        "structure_targets_available": structure_targets_available,
        "structure_rr_valid": structure_rr_valid,
        "tp_min_rr": _round_price(_rr_target(direction, entry, selected_sl, min_rr), digits),
        "tp_min_rr_value": min_rr,
        "reclaim_trigger": _round_price(reclaim_trigger, digits),
        "invalidation": invalidation,
        "risk_pips_tight": _risk_pips(entry, sl_tight, pip_value),
        "risk_pips_safe": _risk_pips(entry, sl_safe, pip_value),
        "selected_risk_pips": _risk_pips(entry, selected_sl, pip_value),
        "target_policy": _continuation_target_policy(tp1_rr_required, min_rr),
        "targets": _continuation_target_objects(targets, target_mode, direction, entry, selected_sl),
        "trade_plan": {
            "direction": direction,
            "entry_mode": f"{direction}_SIGNAL_ZONE_OR_RETEST",
            "selected_sl": _round_price(selected_sl, digits),
            "tp1": _round_price(tp1, digits),
            "tp2": _round_price(tp2, digits),
            "tp3": _round_price(tp3, digits),
            "tp4": _round_price(tp4, digits),
            "target_mode": target_mode,
            "min_rr_required": min_rr,
            "invalidation": invalidation,
        },
    }


def _snapshot(cluster: Any) -> dict[str, Any] | None:
    raw = _field(cluster, "market_context_snapshot", None)
    return raw if isinstance(raw, dict) else None


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _optional_float(value)
        if parsed is not None:
            return parsed
    return None


def _normalize_direction(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"BUY", "SELL"}:
        return text
    if text.startswith("EXECUTE") and text.endswith("_BUY"):
        return "BUY"
    if text.startswith("EXECUTE") and text.endswith("_SELL"):
        return "SELL"
    return None


def _normalize_position(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text or None


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


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


def _price_start(cluster: Any, snapshot: dict[str, Any] | None) -> float | None:
    return _optional_float(
        _field(
            cluster,
            "price_at_signal_start",
            _field(snapshot, "price_at_signal_start", _field(cluster, "price_start", None)),
        )
    )


def _price_end(cluster: Any, snapshot: dict[str, Any] | None) -> float | None:
    return _optional_float(
        _field(
            cluster,
            "price_at_signal_end",
            _field(snapshot, "price_at_signal_end", _field(cluster, "price_end", None)),
        )
    )


def _entry_zone(start: float | None, end: float | None) -> list[float] | None:
    values: list[float] = []
    for value in (start, end):
        if value is not None:
            values.append(value)
    if not values:
        return None
    return [round(min(values), 5), round(max(values), 5)]


def _pip_value(symbol: str, raw: Any) -> float:
    explicit = _optional_float(raw)
    if explicit and explicit > 0:
        return explicit
    return 0.01 if symbol.endswith("JPY") else 0.0001


def _digits(pip_value: float) -> int:
    return 3 if pip_value >= 0.01 else 5


def _price_delta_pips(start: float | None, end: float | None, pip_value: float) -> float | None:
    if start is None or end is None or pip_value <= 0:
        return None
    return round(abs(end - start) / pip_value, 2)


def _phase_direction(value: str | None) -> str | None:
    phase = str(value or "").upper()
    if phase in {"BULLISH", "BULLISH_PULLBACK", "PULLBACK_COMPLETION", "SUPPORT_HOLD", "BREAKOUT_RETEST"}:
        return "BUY"
    if phase in {"BEARISH", "BEARISH_PULLBACK", "BREAKDOWN_RETEST", "RESISTANCE_REJECTION", "SUPPORT_BREAK"}:
        return "SELL"
    return None


def _sorted_targets(direction: str, entry: float | None, raw_targets: list[Any]) -> list[float]:
    if entry is None:
        return []
    values = []
    for raw in raw_targets:
        target = _optional_float(raw)
        if target is None:
            continue
        if (direction == "BUY" and target > entry) or (direction == "SELL" and target < entry):
            values.append(target)
    return sorted(set(values), reverse=direction == "SELL")


def _first_rr_at_least(
    direction: str, entry: float | None, sl: float | None, targets: list[float], min_rr: float
) -> float | None:
    for target in targets:
        rr = _rr(direction, entry, sl, target)
        if rr is not None and rr >= min_rr:
            return rr
    return None


def _rr(direction: str, entry: float | None, sl: float | None, target: float | None) -> float | None:
    if entry is None or sl is None or target is None:
        return None
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    reward = target - entry if direction == "BUY" else entry - target
    if reward <= 0:
        return None
    return round(reward / risk, 2)


def _rr_target(direction: str, entry: float | None, sl: float | None, rr: float) -> float | None:
    if entry is None or sl is None:
        return None
    risk = abs(entry - sl)
    return entry + (risk * rr) if direction == "BUY" else entry - (risk * rr)


def _valid_stop(direction: str, entry: float | None, stop: float | None) -> bool:
    if entry is None or stop is None:
        return False
    return stop < entry if direction == "BUY" else stop > entry


def _risk_pips(entry: float | None, stop: float | None, pip_value: float) -> float | None:
    if entry is None or stop is None or pip_value <= 0:
        return None
    return round(abs(entry - stop) / pip_value, 1)


def _continuation_target_policy(tp1_rr: float, min_rr: float) -> dict[str, Any]:
    return {
        "mode": "TP1_FIXED_RR_THEN_STRUCTURE_TARGETS",
        "tp1_rr": tp1_rr,
        "tp1_required": True,
        "tp2_plus_source": "OBSERVED_KEY_STRUCTURE_LEVELS_ONLY",
        "allow_variable_tp_count": True,
        "max_tp_count": 4,
        "min_structure_rr_required": min_rr,
    }


def _continuation_target_objects(
    targets: Sequence[float | None],
    target_mode: str,
    direction: str,
    entry: float | None,
    selected_sl: float | None,
) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for index, level in enumerate(targets[:4], start=1):
        if level is None:
            continue
        if index == 1:
            target_type = "FIXED_RR"
            source = "MANDATORY_TP1_RR_FLOOR"
        elif target_mode == "FINAL_MARKET_STRUCTURE":
            target_type = "STRUCTURE_TARGET"
            source = "OBSERVED_RESISTANCE_LADDER" if direction == "BUY" else "OBSERVED_SUPPORT_LADDER"
        else:
            target_type = "PROVISIONAL_RR_REFERENCE"
            source = "RR_ORIENTATION_ONLY"
        objects.append(
            {
                "id": f"TP{index}",
                "level": level,
                "type": target_type,
                "source": source,
                "rr": _rr(direction, entry, selected_sl, level),
                "required": index == 1,
            }
        )
    return objects


def _target_ladder_with_fixed_tp1(
    direction: str,
    entry: float | None,
    sl: float | None,
    structure_targets: list[float],
    tp1_rr: float,
) -> list[float | None]:
    fixed_tp1 = _rr_target(direction, entry, sl, tp1_rr)
    eligible_extensions = [
        target
        for target in structure_targets
        if (_rr(direction, entry, sl, target) or 0.0) > tp1_rr
    ]
    canonical_targets = ([] if fixed_tp1 is None else [fixed_tp1]) + eligible_extensions
    return _pad_targets(canonical_targets)


def _rr_fallback_targets(
    direction: str,
    entry: float,
    sl: float,
    min_rr: float,
    tp1_rr: float,
) -> list[float | None]:
    final_rr = max(min_rr, tp1_rr)
    multipliers = [tp1_rr, final_rr, max(3.0, final_rr + 0.5), max(4.0, final_rr + 1.0)]
    risk = abs(entry - sl)
    if direction == "BUY":
        return [entry + risk * multiplier for multiplier in multipliers]
    return [entry - risk * multiplier for multiplier in multipliers]


def _safe_stop(direction: str, sl: float | None, pip_value: float) -> float | None:
    if sl is None:
        return None
    return sl - (8.0 * pip_value) if direction == "BUY" else sl + (8.0 * pip_value)


def _signal_expiry(signal_time_utc: str | None, expiry_minutes: int) -> dict[str, Any] | None:
    if not signal_time_utc:
        return None
    try:
        from datetime import datetime, timedelta

        expires = datetime.fromisoformat(signal_time_utc.replace("Z", "+00:00")) + timedelta(minutes=expiry_minutes)
    except ValueError:
        return None
    return {
        "valid_minutes": expiry_minutes,
        "expires_at_utc": expires.isoformat(),
        "expires_at_wita": expires.astimezone(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S"),
        "requires_revalidation_after_minutes": min(15, expiry_minutes),
    }


def _pad_targets(targets: list[float]) -> list[float | None]:
    padded: list[float | None] = list(targets[:4])
    while len(padded) < 4:
        padded.append(None)
    return padded


def _round_price(value: float | None, digits: int = 5) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _normalize_utc_time(value: str | None) -> str | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        from datetime import UTC, datetime

        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    except ValueError:
        return value


def _wita_time(value: str | None) -> str | None:
    if not value:
        return None
    try:
        from datetime import datetime

        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
