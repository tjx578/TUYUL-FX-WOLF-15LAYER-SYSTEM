"""Counter-entry timing for priced microboost pressure.

Raw SignalThrottle pressure is telemetry.  This module promotes a priced
microboost warning into a counter-entry watch/valid state only when price
location and reaction agree.  It never fetches market data and it never turns
an unpriced cluster into a trade signal.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from analysis.market_context_validator import MarketContext


class CounterEntryStatus(StrEnum):
    NONE = "NONE"
    NANO_ABSORPTION_SELL_WATCH = "NANO_ABSORPTION_SELL_WATCH"
    EARLY_SELL_WATCH = "EARLY_SELL_WATCH"
    SELL_TIMING_WATCH = "SELL_TIMING_WATCH"
    SELL_TIMING_VALID = "SELL_TIMING_VALID"
    NANO_ABSORPTION_BUY_WATCH = "NANO_ABSORPTION_BUY_WATCH"
    EARLY_BUY_WATCH = "EARLY_BUY_WATCH"
    BUY_TIMING_WATCH = "BUY_TIMING_WATCH"
    BUY_TIMING_VALID = "BUY_TIMING_VALID"
    BREAKOUT_CONTINUATION_BUY = "BREAKOUT_CONTINUATION_BUY"
    BREAKDOWN_CONTINUATION_SELL = "BREAKDOWN_CONTINUATION_SELL"


@dataclass(frozen=True)
class MicroboostCounterEntryResult:
    enabled: bool
    status: CounterEntryStatus
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
    aggressive_trigger: float | None = None
    conservative_trigger: float | None = None
    suggested_sl: float | None = None
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
    requires_rejection_or_breakdown: bool = False
    price_position: str | None = None
    m15_phase: str | None = None
    h1_phase: str | None = None
    effective_density: float | None = None
    effective_ticks: int | None = None
    duration_seconds: float | None = None
    duration_minutes: float | None = None
    price_delta_pips: float | None = None
    confidence_bucket: str | None = None
    invalidation: str | None = None
    trade_plan: dict[str, Any] | None = None
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

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


class MicroboostCounterEntryEngine:
    """Promote priced microboost warnings into counter-entry timing states."""

    def __init__(
        self,
        *,
        min_density_per_minute: float = 12.0,
        max_stall_pips: float = 8.0,
        nano_duration_seconds: float = 30.0,
        nano_density_per_minute: float = 30.0,
        nano_max_stall_pips: float = 1.0,
        timing_watch_min_seconds: float = 60.0,
        timing_valid_min_seconds: float = 180.0,
        min_rr_valid: float = 2.5,
        allow_rr_fallback: bool = True,
    ) -> None:
        self.min_density_per_minute = min_density_per_minute
        self.max_stall_pips = max_stall_pips
        self.nano_duration_seconds = nano_duration_seconds
        self.nano_density_per_minute = nano_density_per_minute
        self.nano_max_stall_pips = nano_max_stall_pips
        self.timing_watch_min_seconds = timing_watch_min_seconds
        self.timing_valid_min_seconds = timing_valid_min_seconds
        self.min_rr_valid = min_rr_valid
        self.allow_rr_fallback = allow_rr_fallback

    def evaluate(self, cluster: Any, market: Any | None = None) -> MicroboostCounterEntryResult:
        symbol = str(_field(cluster, "symbol", _field(market, "symbol", ""))).upper()
        raw_direction = _normalize_direction(_field(cluster, "raw_direction", _field(cluster, "direction", None)))
        phase_priced = _optional_str(_field(cluster, "phase_priced", None))
        phase_unpriced = str(_field(cluster, "phase_unpriced", "") or "").upper()
        cluster_id = _optional_str(_field(cluster, "cluster_id", None))
        density = _optional_float(
            _field(cluster, "effective_density", _field(cluster, "effective_density_per_minute", None))
        )
        effective_ticks = _optional_int(
            _field(cluster, "effective_ticks", _field(cluster, "effective_tick_count", None))
        )
        duration_seconds = _optional_float(_field(cluster, "duration_seconds", _field(cluster, "cluster_age_seconds", None)))
        signal_time = _optional_str(_field(cluster, "end_utc", _field(cluster, "signal_valid_time", None)))
        signal_time_utc = _normalize_utc_time(signal_time)
        market_context_applied = _market_context_applied(cluster, market)
        price_position = _normalize_position(_field(market, "price_position", _field(cluster, "price_position", None)))
        m15_phase = _optional_str(_field(market, "m15_phase", _field(cluster, "m15_phase", None)))
        h1_phase = _optional_str(_field(market, "h1_phase", _field(cluster, "h1_phase", None)))
        pip_value = _pip_value(symbol, _field(market, "pip_value", None))
        price_start = _price_start(cluster, market)
        price_end = _price_end(cluster, market)
        entry_reference = price_end if price_end is not None else price_start
        price_delta_pips = _price_delta_pips(price_start, price_end, pip_value)

        base = {
            "symbol": symbol,
            "cluster_id": cluster_id,
            "raw_direction": raw_direction,
            "phase_unpriced": phase_unpriced or None,
            "phase_priced": phase_priced,
            "signal_valid_time": signal_time,
            "signal_valid_time_utc": signal_time_utc,
            "signal_valid_time_wita": _wita_time(signal_time_utc),
            "signal_valid_price": entry_reference,
            "entry_reference_price": entry_reference,
            "entry_zone": _entry_zone(price_start, price_end),
            "market_context_applied": market_context_applied,
            "price_position": price_position,
            "m15_phase": m15_phase,
            "h1_phase": h1_phase,
            "effective_density": density,
            "effective_ticks": effective_ticks,
            "duration_seconds": duration_seconds,
            "duration_minutes": round(duration_seconds / 60.0, 2) if duration_seconds is not None else None,
            "price_delta_pips": price_delta_pips,
        }

        if not market_context_applied:
            return self._result(
                enabled=False,
                status=CounterEntryStatus.NONE,
                candidate_direction=None,
                final_direction="WAIT",
                direction_status="MARKET_CONTEXT_REQUIRED",
                action="NO_COUNTER_ENTRY",
                reason="counter_entry_requires_priced_microboost_market_context",
                **base,
            )

        if raw_direction == "BUY" and self._is_resistance_warning(phase_priced, price_position):
            return self._evaluate_resistance_sell(
                cluster=cluster,
                market=market,
                observed_phase_unpriced=phase_unpriced,
                pip_value=pip_value,
                observed_price_delta_pips=price_delta_pips,
                density=density,
                observed_duration_seconds=duration_seconds,
                entry_reference=entry_reference,
                **base,
            )

        if raw_direction == "SELL" and self._is_support_warning(phase_priced, price_position):
            return self._evaluate_support_buy(
                cluster=cluster,
                market=market,
                observed_phase_unpriced=phase_unpriced,
                pip_value=pip_value,
                observed_price_delta_pips=price_delta_pips,
                density=density,
                observed_duration_seconds=duration_seconds,
                entry_reference=entry_reference,
                **base,
            )

        return self._result(
            enabled=False,
            status=CounterEntryStatus.NONE,
            candidate_direction=None,
            final_direction="WAIT",
            direction_status="NO_COUNTER_ENTRY_CONDITION",
            action="NO_COUNTER_ENTRY",
            reason="no_resistance_or_support_counter_entry_condition",
            **base,
        )

    def evaluate_report(self, report: dict[str, Any]) -> MicroboostCounterEntryResult | None:
        summary = report.get("microboost_summary")
        if not isinstance(summary, dict):
            return None
        latest = summary.get("latest")
        if not isinstance(latest, dict):
            return None
        return self.evaluate(latest)

    def _evaluate_resistance_sell(
        self,
        *,
        cluster: Any,
        market: Any | None,
        observed_phase_unpriced: str,
        pip_value: float,
        observed_price_delta_pips: float | None,
        density: float | None,
        observed_duration_seconds: float | None,
        entry_reference: float | None,
        **base: Any,
    ) -> MicroboostCounterEntryResult:
        m15_close_above_resistance = _optional_bool(_field(market, "m15_close_above_resistance", None))
        if m15_close_above_resistance is True:
            return self._result(
                enabled=False,
                status=CounterEntryStatus.BREAKOUT_CONTINUATION_BUY,
                candidate_direction="BUY",
                final_direction="WAIT",
                direction_status="BREAKOUT_BLOCKS_COUNTER_SELL",
                action="WAIT_RETEST_BUY",
                reason="m15_close_above_resistance_blocks_counter_sell",
                **base,
            )

        stalled = (
            density is not None
            and density >= self.min_density_per_minute
            and observed_price_delta_pips is not None
            and observed_price_delta_pips <= self.max_stall_pips
        )
        if not stalled:
            return self._result(
                enabled=False,
                status=CounterEntryStatus.NONE,
                candidate_direction=None,
                final_direction="WAIT",
                direction_status="NO_STALL_AT_RESISTANCE",
                action="NO_COUNTER_ENTRY",
                reason="buy_microboost_at_resistance_has_not_stalled_enough",
                **base,
            )

        rejection = bool(_optional_bool(_field(market, "m15_rejection_from_resistance", None)))
        minor_break = bool(_optional_bool(_field(market, "m15_close_below_minor_support", None)))
        status = self._sell_watch_status(
            phase_unpriced=observed_phase_unpriced,
            density=density,
            duration_seconds=observed_duration_seconds,
            price_delta_pips=observed_price_delta_pips,
        )
        final_direction = "WAIT"
        direction_status = "MICROBOOST_COUNTER_ENTRY_WATCH"
        action = "WAIT_REJECTION_OR_MINOR_SUPPORT_BREAK"
        levels = _sell_levels(market, entry_reference, pip_value)
        target_result = _build_target_result(
            direction="SELL",
            symbol=str(base.get("symbol") or ""),
            levels=levels,
            entry=entry_reference,
            sl=levels["sl_tight"],
            min_rr=self.min_rr_valid,
            missing_reason=_support_ladder_missing_reason(market),
            allow_rr_fallback=self.allow_rr_fallback,
        )
        rr_to_tp1 = target_result["tp1_rr"]
        rr_to_tp2 = target_result["tp2_rr"]
        rr_to_tp3 = target_result["tp3_rr"]
        mature_valid = self._mature_timing_valid(
            phase_unpriced=observed_phase_unpriced,
            duration_seconds=observed_duration_seconds,
            rr_to_tp2=target_result["selected_rr"],
        )
        can_promote = bool(target_result["structure_rr_valid"]) and (rejection or minor_break or mature_valid)
        if can_promote:
            status = CounterEntryStatus.SELL_TIMING_VALID
            final_direction = "SELL"
            direction_status = "MICROBOOST_COUNTER_ENTRY_VALIDATED"
            action = "SELL_AT_SIGNAL_VALID_PRICE_OR_RETEST"
        elif target_result["target_mode"] == "PROVISIONAL_RR_FALLBACK":
            action = "WAIT_STRUCTURE_TARGET_OR_REJECTION"
        elif target_result["rr_status"] == "FAIL_MIN_RR":
            action = "WAIT_BETTER_PRICE_OR_DEEPER_TARGET"

        trade_plan = _sell_trade_plan(target_result, action)
        return self._result(
            enabled=True,
            status=status,
            candidate_direction="SELL",
            validated_direction="SELL",
            final_direction=final_direction,
            direction_status=direction_status,
            action=action,
            reason=_sell_reason(status, density, observed_price_delta_pips),
            aggressive_trigger=target_result["aggressive_trigger"],
            conservative_trigger=target_result["conservative_trigger"],
            suggested_sl=levels["sl_tight"],
            sl_tight=levels["sl_tight"],
            sl_safe=levels["sl_safe"],
            tp1=target_result["tp1"],
            tp2=target_result["tp2"],
            tp3=target_result["tp3"],
            tp4=target_result["tp4"],
            rr_to_tp1_tight=rr_to_tp1,
            rr_to_tp2_tight=rr_to_tp2,
            rr_to_tp3_tight=rr_to_tp3,
            rr_status=_rr_status(status, target_result["rr_status"], target_result["selected_rr"], self.min_rr_valid),
            requires_rejection_or_breakdown=status != CounterEntryStatus.SELL_TIMING_VALID,
            confidence_bucket=_confidence_bucket(status, target_result["selected_rr"], self.min_rr_valid),
            invalidation="M15 close above resistance high or strong reclaim above resistance",
            trade_plan=trade_plan,
            target_mode=target_result["target_mode"],
            tp_status=target_result["tp_status"],
            tp_missing_reason=target_result["tp_missing_reason"],
            support_ladder_ready=target_result["support_ladder_ready"],
            resistance_ladder_ready=_optional_bool(_field(market, "resistance_ladder_ready", None)),
            structure_targets_available=target_result["structure_targets_available"],
            tradeplan_context_ready=can_promote,
            valid_for_execution=can_promote,
            min_rr_required=self.min_rr_valid,
            tp_min_rr=target_result["tp_min_rr"],
            tp_min_rr_value=target_result["tp_min_rr_value"],
            tp1_rr=target_result["tp1_rr"],
            tp2_rr=target_result["tp2_rr"],
            tp3_rr=target_result["tp3_rr"],
            tp4_rr=target_result["tp4_rr"],
            **base,
        )

    def _evaluate_support_buy(
        self,
        *,
        cluster: Any,
        market: Any | None,
        observed_phase_unpriced: str,
        pip_value: float,
        observed_price_delta_pips: float | None,
        density: float | None,
        observed_duration_seconds: float | None,
        entry_reference: float | None,
        **base: Any,
    ) -> MicroboostCounterEntryResult:
        m15_close_below_support = _optional_bool(_field(market, "m15_close_below_support", None))
        if m15_close_below_support is True:
            return self._result(
                enabled=False,
                status=CounterEntryStatus.BREAKDOWN_CONTINUATION_SELL,
                candidate_direction="SELL",
                final_direction="WAIT",
                direction_status="BREAKDOWN_BLOCKS_COUNTER_BUY",
                action="WAIT_RETEST_SELL",
                reason="m15_close_below_support_blocks_counter_buy",
                **base,
            )

        stalled = (
            density is not None
            and density >= self.min_density_per_minute
            and observed_price_delta_pips is not None
            and observed_price_delta_pips <= self.max_stall_pips
        )
        if not stalled:
            return self._result(
                enabled=False,
                status=CounterEntryStatus.NONE,
                candidate_direction=None,
                final_direction="WAIT",
                direction_status="NO_STALL_AT_SUPPORT",
                action="NO_COUNTER_ENTRY",
                reason="sell_microboost_at_support_has_not_stalled_enough",
                **base,
            )

        rejection = bool(_optional_bool(_field(market, "m15_rejection_from_support", None)))
        minor_break = bool(_optional_bool(_field(market, "m15_close_above_minor_resistance", None)))
        status = self._buy_watch_status(
            phase_unpriced=observed_phase_unpriced,
            density=density,
            duration_seconds=observed_duration_seconds,
            price_delta_pips=observed_price_delta_pips,
        )
        final_direction = "WAIT"
        direction_status = "MICROBOOST_COUNTER_ENTRY_WATCH"
        action = "WAIT_REJECTION_OR_MINOR_RESISTANCE_BREAK"
        levels = _buy_levels(market, entry_reference, pip_value)
        target_result = _build_target_result(
            direction="BUY",
            symbol=str(base.get("symbol") or ""),
            levels=levels,
            entry=entry_reference,
            sl=levels["sl_tight"],
            min_rr=self.min_rr_valid,
            missing_reason=_resistance_ladder_missing_reason(market),
            allow_rr_fallback=self.allow_rr_fallback,
        )
        rr_to_tp1 = target_result["tp1_rr"]
        rr_to_tp2 = target_result["tp2_rr"]
        rr_to_tp3 = target_result["tp3_rr"]
        mature_valid = self._mature_timing_valid(
            phase_unpriced=observed_phase_unpriced,
            duration_seconds=observed_duration_seconds,
            rr_to_tp2=target_result["selected_rr"],
        )
        can_promote = bool(target_result["structure_rr_valid"]) and (rejection or minor_break or mature_valid)
        if can_promote:
            status = CounterEntryStatus.BUY_TIMING_VALID
            final_direction = "BUY"
            direction_status = "MICROBOOST_COUNTER_ENTRY_VALIDATED"
            action = "BUY_AT_SIGNAL_VALID_PRICE_OR_RETEST"
        elif target_result["target_mode"] == "PROVISIONAL_RR_FALLBACK":
            action = "WAIT_STRUCTURE_TARGET_OR_REJECTION"
        elif target_result["rr_status"] == "FAIL_MIN_RR":
            action = "WAIT_BETTER_PRICE_OR_DEEPER_TARGET"

        return self._result(
            enabled=True,
            status=status,
            candidate_direction="BUY",
            validated_direction="BUY",
            final_direction=final_direction,
            direction_status=direction_status,
            action=action,
            reason=_buy_reason(status, density, observed_price_delta_pips),
            aggressive_trigger=target_result["aggressive_trigger"],
            conservative_trigger=target_result["conservative_trigger"],
            suggested_sl=levels["sl_tight"],
            sl_tight=levels["sl_tight"],
            sl_safe=levels["sl_safe"],
            tp1=target_result["tp1"],
            tp2=target_result["tp2"],
            tp3=target_result["tp3"],
            tp4=target_result["tp4"],
            rr_to_tp1_tight=rr_to_tp1,
            rr_to_tp2_tight=rr_to_tp2,
            rr_to_tp3_tight=rr_to_tp3,
            rr_status=_rr_status(status, target_result["rr_status"], target_result["selected_rr"], self.min_rr_valid),
            requires_rejection_or_breakdown=status != CounterEntryStatus.BUY_TIMING_VALID,
            confidence_bucket=_confidence_bucket(status, target_result["selected_rr"], self.min_rr_valid),
            invalidation="M15 close below support low or strong breakdown below support",
            trade_plan=_buy_trade_plan(target_result, action),
            target_mode=target_result["target_mode"],
            tp_status=target_result["tp_status"],
            tp_missing_reason=target_result["tp_missing_reason"],
            support_ladder_ready=_optional_bool(_field(market, "support_ladder_ready", None)),
            resistance_ladder_ready=target_result["resistance_ladder_ready"],
            structure_targets_available=target_result["structure_targets_available"],
            tradeplan_context_ready=can_promote,
            valid_for_execution=can_promote,
            min_rr_required=self.min_rr_valid,
            tp_min_rr=target_result["tp_min_rr"],
            tp_min_rr_value=target_result["tp_min_rr_value"],
            tp1_rr=target_result["tp1_rr"],
            tp2_rr=target_result["tp2_rr"],
            tp3_rr=target_result["tp3_rr"],
            tp4_rr=target_result["tp4_rr"],
            **base,
        )

    def _sell_watch_status(
        self,
        *,
        phase_unpriced: str,
        density: float | None,
        duration_seconds: float | None,
        price_delta_pips: float | None,
    ) -> CounterEntryStatus:
        if (
            duration_seconds is not None
            and duration_seconds < self.nano_duration_seconds
            and density is not None
            and density >= self.nano_density_per_minute
            and price_delta_pips is not None
            and price_delta_pips <= self.nano_max_stall_pips
        ):
            return CounterEntryStatus.NANO_ABSORPTION_SELL_WATCH
        if (duration_seconds or 0.0) >= self.timing_watch_min_seconds or phase_unpriced == "NEAR_TIMING_GATE_MICROBOOST":
            return CounterEntryStatus.SELL_TIMING_WATCH
        return CounterEntryStatus.EARLY_SELL_WATCH

    def _buy_watch_status(
        self,
        *,
        phase_unpriced: str,
        density: float | None,
        duration_seconds: float | None,
        price_delta_pips: float | None,
    ) -> CounterEntryStatus:
        if (
            duration_seconds is not None
            and duration_seconds < self.nano_duration_seconds
            and density is not None
            and density >= self.nano_density_per_minute
            and price_delta_pips is not None
            and price_delta_pips <= self.nano_max_stall_pips
        ):
            return CounterEntryStatus.NANO_ABSORPTION_BUY_WATCH
        if (duration_seconds or 0.0) >= self.timing_watch_min_seconds or phase_unpriced == "NEAR_TIMING_GATE_MICROBOOST":
            return CounterEntryStatus.BUY_TIMING_WATCH
        return CounterEntryStatus.EARLY_BUY_WATCH

    @staticmethod
    def _is_resistance_warning(phase_priced: str | None, price_position: str | None) -> bool:
        return phase_priced in {"RESISTANCE_PRESSURE_WARNING", "EXHAUSTION_AT_RESISTANCE"} and price_position in {
            "MAIN_RESISTANCE",
            "UPPER_RANGE",
        }

    @staticmethod
    def _is_support_warning(phase_priced: str | None, price_position: str | None) -> bool:
        return phase_priced in {"SUPPORT_PRESSURE_WARNING", "EXHAUSTION_AT_SUPPORT"} and price_position in {
            "MAIN_SUPPORT",
            "LOWER_RANGE",
        }

    @staticmethod
    def _result(**kwargs: Any) -> MicroboostCounterEntryResult:
        kwargs.setdefault("signal_family", "MICROBOOST_COUNTER_ENTRY")
        kwargs.setdefault("cluster_id", None)
        kwargs.setdefault("validated_direction", kwargs.get("candidate_direction"))
        return MicroboostCounterEntryResult(signal_type="MICROBOOST_COUNTER_ENTRY", **kwargs)

    def _mature_timing_valid(
        self,
        *,
        phase_unpriced: str,
        duration_seconds: float | None,
        rr_to_tp2: float | None,
    ) -> bool:
        if duration_seconds is None or duration_seconds < self.timing_valid_min_seconds:
            return False
        if phase_unpriced not in {"NEAR_TIMING_GATE_MICROBOOST", "DENSE_MICROBOOST", "REPEATED_MICROBOOST"}:
            return False
        return rr_to_tp2 is not None and rr_to_tp2 >= self.min_rr_valid


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


def _market_context_applied(cluster: Any, market: Any | None) -> bool:
    if _optional_bool(_field(cluster, "market_context_applied", None)) is True:
        return True
    snapshot = _field(cluster, "market_context_snapshot", None)
    if isinstance(snapshot, dict):
        return (
            _optional_float(snapshot.get("price_at_signal_start")) is not None
            and _optional_float(snapshot.get("price_at_signal_end")) is not None
            and _normalize_position(snapshot.get("price_position")) is not None
        )
    return market is not None and _optional_float(_field(market, "price_at_signal_end", None)) is not None


def _price_start(cluster: Any, market: Any | None) -> float | None:
    return _optional_float(
        _field(
            cluster,
            "price_at_signal_start",
            _field(market, "price_at_signal_start", None),
        )
    )


def _price_end(cluster: Any, market: Any | None) -> float | None:
    return _optional_float(
        _field(
            cluster,
            "price_at_signal_end",
            _field(market, "price_at_signal_end", _field(market, "bid", None)),
        )
    )


def _price_delta_pips(start: float | None, end: float | None, pip_value: float) -> float | None:
    if start is None or end is None or pip_value <= 0:
        return None
    return round(abs(end - start) / pip_value, 2)


def _entry_zone(start: float | None, end: float | None) -> list[float] | None:
    values: list[float] = []
    for value in (start, end):
        if value is not None:
            values.append(_round_price_required(value))
    if not values:
        return None
    low = values[0]
    high = values[0]
    for value in values[1:]:
        if value < low:
            low = value
        if value > high:
            high = value
    return [low, high]


def _sell_levels(market: Any | None, entry_reference: float | None, pip_value: float) -> dict[str, float | None]:
    resistance_high = _optional_float(_field(market, "resistance_high", _field(market, "main_resistance", None)))
    resistance_low = _optional_float(_field(market, "resistance_low", resistance_high))
    sl_buffer = _optional_float(_field(market, "sl_buffer", None)) or pip_value * 8.0
    sl_tight = _optional_float(_field(market, "sl_tight", None))
    sl_safe = _optional_float(_field(market, "sl_safe", None))
    if sl_tight is None and resistance_high is not None:
        sl_tight = resistance_high + sl_buffer
    if sl_safe is None and resistance_high is not None:
        sl_safe = resistance_high + max(sl_buffer * 2.0, pip_value * 16.0)
    if sl_tight is None and entry_reference is not None:
        sl_tight = entry_reference + pip_value * 12.0
    if sl_safe is None and entry_reference is not None:
        sl_safe = entry_reference + pip_value * 20.0

    return {
        "aggressive_trigger": _round_price(_optional_float(_field(market, "minor_support", None))),
        "conservative_trigger": _round_price(
            _optional_float(_field(market, "major_support", _field(market, "main_support", None)))
        ),
        "sl_tight": _round_price(sl_tight),
        "sl_safe": _round_price(sl_safe),
        "tp1": _round_price(_optional_float(_field(market, "tp1_support", _field(market, "minor_support", None)))),
        "tp2": _round_price(
            _optional_float(_field(market, "tp2_support", _field(market, "major_support", _field(market, "main_support", None))))
        ),
        "tp3": _round_price(_optional_float(_field(market, "tp3_support", None))),
        "tp4": _round_price(_optional_float(_field(market, "tp4_support", None))),
        "resistance_low": _round_price(resistance_low),
        "resistance_high": _round_price(resistance_high),
    }


def _buy_levels(market: Any | None, entry_reference: float | None, pip_value: float) -> dict[str, float | None]:
    support_low = _optional_float(_field(market, "support_low", _field(market, "main_support", None)))
    support_high = _optional_float(_field(market, "support_high", support_low))
    sl_buffer = _optional_float(_field(market, "sl_buffer", None)) or pip_value * 8.0
    sl_tight = _optional_float(_field(market, "sl_tight", None))
    sl_safe = _optional_float(_field(market, "sl_safe", None))
    if sl_tight is None and support_low is not None:
        sl_tight = support_low - sl_buffer
    if sl_safe is None and support_low is not None:
        sl_safe = support_low - max(sl_buffer * 2.0, pip_value * 16.0)
    if sl_tight is None and entry_reference is not None:
        sl_tight = entry_reference - pip_value * 12.0
    if sl_safe is None and entry_reference is not None:
        sl_safe = entry_reference - pip_value * 20.0

    return {
        "aggressive_trigger": _round_price(_optional_float(_field(market, "minor_resistance", None))),
        "conservative_trigger": _round_price(
            _optional_float(_field(market, "resistance_high", _field(market, "main_resistance", None)))
        ),
        "sl_tight": _round_price(sl_tight),
        "sl_safe": _round_price(sl_safe),
        "tp1": _round_price(_optional_float(_field(market, "tp1_resistance", _field(market, "minor_resistance", None)))),
        "tp2": _round_price(
            _optional_float(_field(market, "tp2_resistance", _field(market, "resistance_high", _field(market, "main_resistance", None))))
        ),
        "tp3": _round_price(_optional_float(_field(market, "tp3_resistance", None))),
        "tp4": _round_price(_optional_float(_field(market, "tp4_resistance", None))),
        "support_low": _round_price(support_low),
        "support_high": _round_price(support_high),
    }


def _build_target_result(
    *,
    direction: str,
    symbol: str,
    levels: dict[str, float | None],
    entry: float | None,
    sl: float | None,
    min_rr: float,
    missing_reason: str | None,
    allow_rr_fallback: bool,
) -> dict[str, Any]:
    structure_targets = _structure_targets(direction, entry, levels)
    if structure_targets:
        return _structure_target_result(
            direction=direction,
            levels=levels,
            entry=entry,
            sl=sl,
            targets=structure_targets,
            min_rr=min_rr,
        )
    if allow_rr_fallback:
        return _rr_fallback_target_result(
            direction=direction,
            symbol=symbol,
            levels=levels,
            entry=entry,
            sl=sl,
            min_rr=min_rr,
            missing_reason=missing_reason,
        )
    return _missing_target_result(
        direction=direction,
        symbol=symbol,
        levels=levels,
        entry=entry,
        sl=sl,
        min_rr=min_rr,
        missing_reason=missing_reason,
    )


def _structure_targets(direction: str, entry: float | None, levels: dict[str, float | None]) -> list[float]:
    if entry is None:
        return []
    targets: list[float] = []
    for key in ("tp1", "tp2", "tp3", "tp4"):
        target = levels.get(key)
        if target is None:
            continue
        if (direction == "SELL" and target < entry) or (direction == "BUY" and target > entry):
            targets.append(target)
    return targets


def _structure_target_result(
    *,
    direction: str,
    levels: dict[str, float | None],
    entry: float | None,
    sl: float | None,
    targets: list[float],
    min_rr: float,
) -> dict[str, Any]:
    padded = [*targets[:4], None, None, None, None]
    tp1, tp2, tp3, tp4 = padded[:4]
    rr_values = [_rr(direction, entry, sl, target) for target in (tp1, tp2, tp3, tp4)]
    valid_rrs = [rr for rr in rr_values if rr is not None and rr >= min_rr]
    selected_rr = valid_rrs[0] if valid_rrs else next((rr for rr in rr_values if rr is not None), None)
    rr_status = "VALID" if valid_rrs else "FAIL_MIN_RR"
    return {
        **_target_common(levels, direction),
        "target_mode": "FINAL_MARKET_STRUCTURE",
        "tp_status": "VALID" if valid_rrs else "FAIL_MIN_RR",
        "tp_missing_reason": None if valid_rrs else f"no_structure_target_reaches_rr_{min_rr:g}",
        "structure_targets_available": True,
        "structure_rr_valid": bool(valid_rrs),
        "support_ladder_ready": direction == "SELL",
        "resistance_ladder_ready": direction == "BUY",
        "rr_status": rr_status,
        "selected_rr": selected_rr,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "tp4": tp4,
        "tp_min_rr": next((target for target, rr in zip((tp1, tp2, tp3, tp4), rr_values, strict=True) if rr is not None and rr >= min_rr), None),
        "tp_min_rr_value": min_rr if valid_rrs else None,
        "tp1_rr": rr_values[0],
        "tp2_rr": rr_values[1],
        "tp3_rr": rr_values[2],
        "tp4_rr": rr_values[3],
    }


def _rr_fallback_target_result(
    *,
    direction: str,
    symbol: str,
    levels: dict[str, float | None],
    entry: float | None,
    sl: float | None,
    min_rr: float,
    missing_reason: str | None,
) -> dict[str, Any]:
    common = _target_common(levels, direction)
    if entry is None or sl is None:
        return {
            **common,
            "target_mode": "NONE",
            "tp_status": "INVALID_RISK",
            "tp_missing_reason": missing_reason or "entry_or_sl_missing",
            "structure_targets_available": False,
            "structure_rr_valid": False,
            "support_ladder_ready": False if direction == "SELL" else None,
            "resistance_ladder_ready": False if direction == "BUY" else None,
            "rr_status": "INVALID_RISK",
            "selected_rr": None,
            "tp1": None,
            "tp2": None,
            "tp3": None,
            "tp4": None,
            "tp_min_rr": None,
            "tp_min_rr_value": min_rr,
            "tp1_rr": None,
            "tp2_rr": None,
            "tp3_rr": None,
            "tp4_rr": None,
        }

    risk = abs(sl - entry)
    if risk <= 0:
        return {
            **common,
            "target_mode": "NONE",
            "tp_status": "INVALID_RISK",
            "tp_missing_reason": "invalid_zero_or_negative_risk",
            "structure_targets_available": False,
            "structure_rr_valid": False,
            "support_ladder_ready": False if direction == "SELL" else None,
            "resistance_ladder_ready": False if direction == "BUY" else None,
            "rr_status": "INVALID_RISK",
            "selected_rr": None,
            "tp1": None,
            "tp2": None,
            "tp3": None,
            "tp4": None,
            "tp_min_rr": None,
            "tp_min_rr_value": min_rr,
            "tp1_rr": None,
            "tp2_rr": None,
            "tp3_rr": None,
            "tp4_rr": None,
        }

    sign = -1.0 if direction == "SELL" else 1.0
    tp1 = _round_price(entry + sign * risk)
    tp2 = _round_price(entry + sign * risk * 2.0)
    tp_min = _round_price(entry + sign * risk * min_rr)
    tp4 = _round_price(entry + sign * risk * 3.0)
    return {
        **common,
        "target_mode": "PROVISIONAL_RR_FALLBACK",
        "tp_status": "WATCH_PROVISIONAL",
        "tp_missing_reason": missing_reason or (
            "support_ladder_missing" if direction == "SELL" else "resistance_ladder_missing"
        ),
        "structure_targets_available": False,
        "structure_rr_valid": False,
        "support_ladder_ready": False if direction == "SELL" else None,
        "resistance_ladder_ready": False if direction == "BUY" else None,
        "rr_status": "WATCH_PROVISIONAL",
        "selected_rr": None,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp_min,
        "tp4": tp4,
        "tp_min_rr": tp_min,
        "tp_min_rr_value": min_rr,
        "tp1_rr": 1.0,
        "tp2_rr": 2.0,
        "tp3_rr": min_rr,
        "tp4_rr": 3.0,
    }


def _missing_target_result(
    *,
    direction: str,
    symbol: str,
    levels: dict[str, float | None],
    entry: float | None,
    sl: float | None,
    min_rr: float,
    missing_reason: str | None,
) -> dict[str, Any]:
    _ = (symbol, entry, sl)
    return {
        **_target_common(levels, direction),
        "target_mode": "NONE",
        "tp_status": "MISSING_STRUCTURE_TARGETS",
        "tp_missing_reason": missing_reason or (
            "support_ladder_missing" if direction == "SELL" else "resistance_ladder_missing"
        ),
        "structure_targets_available": False,
        "structure_rr_valid": False,
        "support_ladder_ready": False if direction == "SELL" else None,
        "resistance_ladder_ready": False if direction == "BUY" else None,
        "rr_status": "WAIT_TARGET_STRUCTURE",
        "selected_rr": None,
        "tp1": None,
        "tp2": None,
        "tp3": None,
        "tp4": None,
        "tp_min_rr": None,
        "tp_min_rr_value": min_rr,
        "tp1_rr": None,
        "tp2_rr": None,
        "tp3_rr": None,
        "tp4_rr": None,
    }


def _target_common(levels: dict[str, float | None], direction: str) -> dict[str, float | None]:
    if direction == "SELL":
        return {
            "aggressive_trigger": levels.get("aggressive_trigger"),
            "conservative_trigger": levels.get("conservative_trigger"),
            "resistance_low": levels.get("resistance_low"),
        }
    return {
        "aggressive_trigger": levels.get("aggressive_trigger"),
        "conservative_trigger": levels.get("conservative_trigger"),
        "support_high": levels.get("support_high"),
    }


def _support_ladder_missing_reason(market: Any | None) -> str:
    return _optional_str(_field(market, "support_ladder_missing_reason", None)) or "support_ladder_missing"


def _resistance_ladder_missing_reason(market: Any | None) -> str:
    return _optional_str(_field(market, "resistance_ladder_missing_reason", None)) or "resistance_ladder_missing"


def _sell_trade_plan(levels: dict[str, Any], action: str) -> dict[str, Any]:
    return {
        "direction": "SELL",
        "entry_mode": (
            "SELL_AT_SIGNAL_VALID_PRICE_OR_RETEST"
            if action == "SELL_AT_SIGNAL_VALID_PRICE_OR_RETEST"
            else "WAIT_REJECTION_OR_MINOR_BREAK"
        ),
        "entry_zone": _compact_price_zone(levels.get("aggressive_trigger"), levels.get("resistance_low")),
        "stop_loss": levels.get("sl_tight"),
        "tp1": levels.get("tp1"),
        "tp2": levels.get("tp2"),
        "tp3": levels.get("tp3"),
        "tp4": levels.get("tp4"),
        "invalidation": "M15 close back above resistance high",
    }


def _buy_trade_plan(levels: dict[str, Any], action: str) -> dict[str, Any]:
    return {
        "direction": "BUY",
        "entry_mode": (
            "BUY_AT_SIGNAL_VALID_PRICE_OR_RETEST"
            if action == "BUY_AT_SIGNAL_VALID_PRICE_OR_RETEST"
            else "WAIT_REJECTION_OR_MINOR_BREAK"
        ),
        "entry_zone": _compact_price_zone(levels.get("support_high"), levels.get("aggressive_trigger")),
        "stop_loss": levels.get("sl_tight"),
        "tp1": levels.get("tp1"),
        "tp2": levels.get("tp2"),
        "tp3": levels.get("tp3"),
        "tp4": levels.get("tp4"),
        "invalidation": "M15 close back below support low",
    }


def _sell_reason(status: CounterEntryStatus, density: float | None, price_delta_pips: float | None) -> str:
    if status == CounterEntryStatus.SELL_TIMING_VALID:
        return "BUY microboost at main resistance failed to expand; counter-sell timing validated."
    if status == CounterEntryStatus.NANO_ABSORPTION_SELL_WATCH:
        return (
            f"BUY microboost density {density:.2f}/m at main resistance with "
            f"{price_delta_pips:.2f} pip expansion."
            if density is not None and price_delta_pips is not None
            else "Nano BUY microboost stalled at main resistance."
        )
    return "High-density BUY microboost is stalled at main resistance; sell timing watch active."


def _buy_reason(status: CounterEntryStatus, density: float | None, price_delta_pips: float | None) -> str:
    if status == CounterEntryStatus.BUY_TIMING_VALID:
        return "SELL microboost at main support failed to expand; counter-buy timing validated."
    if status == CounterEntryStatus.NANO_ABSORPTION_BUY_WATCH:
        return (
            f"SELL microboost density {density:.2f}/m at main support with "
            f"{price_delta_pips:.2f} pip expansion."
            if density is not None and price_delta_pips is not None
            else "Nano SELL microboost stalled at main support."
        )
    return "High-density SELL microboost is stalled at main support; buy timing watch active."


def _rr(direction: str, entry: float | None, stop: float | None, target: float | None) -> float | None:
    if entry is None or stop is None or target is None:
        return None
    risk = abs(stop - entry)
    if risk <= 0:
        return None
    reward = entry - target if direction == "SELL" else target - entry
    if reward <= 0:
        return None
    return round(reward / risk, 2)


def _rr_status(
    status: CounterEntryStatus,
    target_rr_status: str,
    selected_rr: float | None,
    min_rr_valid: float,
) -> str:
    if target_rr_status in {"WATCH_PROVISIONAL", "FAIL_MIN_RR", "INVALID_RISK", "WAIT_TARGET_STRUCTURE"}:
        return target_rr_status
    if status in {CounterEntryStatus.SELL_TIMING_VALID, CounterEntryStatus.BUY_TIMING_VALID}:
        if selected_rr is not None and selected_rr >= min_rr_valid:
            return "VALID"
        if selected_rr is not None and selected_rr > 0:
            return "ACCEPTABLE"
        return "UNVALIDATED"
    return "WATCH"


def _confidence_bucket(status: CounterEntryStatus, rr_to_tp2: float | None, min_rr_valid: float) -> str:
    if status in {CounterEntryStatus.SELL_TIMING_VALID, CounterEntryStatus.BUY_TIMING_VALID}:
        if rr_to_tp2 is not None and rr_to_tp2 >= min_rr_valid * 2:
            return "A_COUNTER_ENTRY_VALID"
        return "B_COUNTER_ENTRY_VALID"
    if status in {
        CounterEntryStatus.SELL_TIMING_WATCH,
        CounterEntryStatus.BUY_TIMING_WATCH,
        CounterEntryStatus.NANO_ABSORPTION_SELL_WATCH,
        CounterEntryStatus.NANO_ABSORPTION_BUY_WATCH,
        CounterEntryStatus.EARLY_SELL_WATCH,
        CounterEntryStatus.EARLY_BUY_WATCH,
    }:
        return "B_COUNTER_ENTRY_WATCH"
    return "X_BLOCKED"


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


def _pip_value(symbol: str, raw: Any) -> float:
    explicit = _optional_float(raw)
    if explicit is not None and explicit > 0:
        return explicit
    return 0.01 if "JPY" in symbol.upper() else 0.0001


def _normalize_direction(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"BUY", "SELL"}:
        return text
    if text in {"LONG", "BULL", "BULLISH"}:
        return "BUY"
    if text in {"SHORT", "BEAR", "BEARISH"}:
        return "SELL"
    return None


def _normalize_position(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"MAIN_RESISTANCE", "RESISTANCE", "NEAR_RESISTANCE", "UPPER_RANGE"}:
        return "MAIN_RESISTANCE"
    if text in {"MAIN_SUPPORT", "SUPPORT", "NEAR_SUPPORT", "LOWER_RANGE"}:
        return "MAIN_SUPPORT"
    if text:
        return text
    return None


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


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


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _round_price(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 5)


def _round_price_required(value: float) -> float:
    return round(float(value), 5)


def _compact_price_zone(*values: float | None) -> list[float]:
    return [_round_price_required(value) for value in values if value is not None]
