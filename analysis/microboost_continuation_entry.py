"""Trend-continuation signal promotion for priced microboost clusters.

Counter-entry logic treats dense pressure at main extremes as absorption.  This
module handles the opposite case: pressure that appears away from the main
extreme while SignalThrottle allowed quorum and timeframe context agree.
"""

from __future__ import annotations

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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MicroboostContinuationEngine:
    """Promote aligned MID_RANGE microboost + allowed quorum into continuation."""

    def __init__(
        self,
        *,
        min_density_per_minute: float = 25.0,
        min_duration_seconds: float = 15.0,
        min_rr_valid: float = 2.5,
        allow_rr_fallback: bool = True,
    ) -> None:
        self.min_density_per_minute = min_density_per_minute
        self.min_duration_seconds = min_duration_seconds
        self.min_rr_valid = min_rr_valid
        self.allow_rr_fallback = allow_rr_fallback

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
        price_position = _normalize_position(_field(cluster, "price_position", _field(snapshot, "price_position", None)))
        h1_phase = _optional_str(_field(cluster, "h1_phase", _field(snapshot, "h1_phase", None)))
        m15_phase = _optional_str(_field(cluster, "m15_phase", _field(snapshot, "m15_phase", None)))
        density = _optional_float(
            _field(cluster, "effective_density", _field(cluster, "effective_density_per_minute", None))
        )
        duration_seconds = _optional_float(_field(cluster, "duration_seconds", _field(cluster, "cluster_age_seconds", None)))
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
            "entry_zone": _entry_zone(price_start, price_end),
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
            allow_rr_fallback=self.allow_rr_fallback,
        )
        status = f"{raw_direction}_TIMING_VALID_BY_QUORUM_CONTINUATION"
        action = "BUY_SIGNAL_ZONE_OR_RETEST" if raw_direction == "BUY" else "SELL_SIGNAL_ZONE_OR_RETEST"
        return self._result(
            enabled=True,
            status=status,
            candidate_direction=raw_direction,
            validated_direction=raw_direction,
            final_direction=raw_direction or "WAIT",
            direction_status="MICROBOOST_QUORUM_CONTINUATION_VALIDATED",
            action=action,
            reason=(
                f"{symbol} {raw_direction} continuation: allowed quorum, high-density microboost, "
                f"{price_position} price position, H1 {h1_phase}, and M15 {m15_phase} are aligned."
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
            rr_status=levels["rr_status"],
            confidence_bucket="A_CONTINUATION_VALID" if levels["structure_rr_valid"] else "B_CONTINUATION_VALID",
            invalidation=levels["invalidation"],
            trade_plan=levels["trade_plan"],
            target_mode=levels["target_mode"],
            tp_status=levels["tp_status"],
            tp_missing_reason=levels["tp_missing_reason"],
            structure_targets_available=levels["structure_targets_available"],
            tradeplan_context_ready=levels["structure_rr_valid"],
            valid_for_execution=levels["valid_for_execution"],
            min_rr_required=self.min_rr_valid,
            tp_min_rr=levels["tp_min_rr"],
            tp_min_rr_value=levels["tp_min_rr_value"],
            tp1_rr=levels["tp1_rr"],
            tp2_rr=levels["tp2_rr"],
            tp3_rr=levels["tp3_rr"],
            tp4_rr=levels["tp4_rr"],
            risk_pips=levels["risk_pips"],
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
    ) -> bool:
        if raw_direction not in {"BUY", "SELL"}:
            return False
        if not quorum_ok or not market_context_applied:
            return False
        if phase_priced not in {"TREND_CONTINUATION_MICROBOOST", "CONTINUATION_MICROBOOST", "CONFIRMATION_MICROBOOST"}:
            return False
        if price_position not in {"MID_RANGE", "PULLBACK_ZONE"}:
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
        return MicroboostContinuationResult(signal_type="MICROBOOST_TREND_CONTINUATION", **kwargs)


def _continuation_levels(
    *,
    direction: str,
    entry: float | None,
    entry_zone: list[float] | None,
    snapshot: dict[str, Any] | None,
    pip_value: float,
    min_rr: float,
    allow_rr_fallback: bool,
) -> dict[str, Any]:
    digits = _digits(pip_value)
    zone = entry_zone or ([] if entry is None else [entry, entry])
    zone_low = min(zone) if zone else entry
    zone_high = max(zone) if zone else entry
    if direction == "BUY":
        structure_sl = _optional_float(_field(snapshot, "support_low", _field(snapshot, "main_support", None)))
        fallback_sl = None if zone_low is None else zone_low - (12.0 * pip_value)
        sl = structure_sl if structure_sl is not None and entry is not None and structure_sl < entry else fallback_sl
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
        invalidation = f"M15 failure below {_round_price(sl, digits)}" if sl is not None else "M15 failure below signal zone"
    else:
        structure_sl = _optional_float(_field(snapshot, "resistance_high", _field(snapshot, "main_resistance", None)))
        fallback_sl = None if zone_high is None else zone_high + (12.0 * pip_value)
        sl = structure_sl if structure_sl is not None and entry is not None and structure_sl > entry else fallback_sl
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
        invalidation = f"M15 failure above {_round_price(sl, digits)}" if sl is not None else "M15 failure above signal zone"

    selected_rr = _first_rr_at_least(direction, entry, sl, targets, min_rr)
    if selected_rr is not None:
        ladder = _pad_targets(targets)
        return _level_payload(
            direction=direction,
            entry=entry,
            sl=sl,
            targets=ladder,
            target_mode="FINAL_MARKET_STRUCTURE",
            tp_status="VALID",
            tp_missing_reason=None,
            structure_targets_available=True,
            structure_rr_valid=True,
            valid_for_execution=True,
            min_rr=min_rr,
            reclaim_trigger=reclaim_trigger,
            invalidation=invalidation,
            digits=digits,
            pip_value=pip_value,
        )

    if allow_rr_fallback and entry is not None and sl is not None:
        fallback_targets = _rr_fallback_targets(direction, entry, sl, min_rr)
        return _level_payload(
            direction=direction,
            entry=entry,
            sl=sl,
            targets=fallback_targets,
            target_mode="PROVISIONAL_RR_FALLBACK",
            tp_status="VALID_FROM_TP3",
            tp_missing_reason="STRUCTURE_TARGET_MISSING_OR_BELOW_MIN_RR",
            structure_targets_available=bool(targets),
            structure_rr_valid=False,
            valid_for_execution=True,
            min_rr=min_rr,
            reclaim_trigger=reclaim_trigger,
            invalidation=invalidation,
            digits=digits,
            pip_value=pip_value,
        )

    return _level_payload(
        direction=direction,
        entry=entry,
        sl=sl,
        targets=[None, None, None, None],
        target_mode="NONE",
        tp_status="WAIT_TARGET_STRUCTURE",
        tp_missing_reason="NO_CONTINUATION_TARGETS",
        structure_targets_available=False,
        structure_rr_valid=False,
        valid_for_execution=False,
        min_rr=min_rr,
        reclaim_trigger=reclaim_trigger,
        invalidation=invalidation,
        digits=digits,
        pip_value=pip_value,
    )


def _level_payload(
    *,
    direction: str,
    entry: float | None,
    sl: float | None,
    targets: list[float | None],
    target_mode: str,
    tp_status: str,
    tp_missing_reason: str | None,
    structure_targets_available: bool,
    structure_rr_valid: bool,
    valid_for_execution: bool,
    min_rr: float,
    reclaim_trigger: float | None,
    invalidation: str,
    digits: int,
    pip_value: float,
) -> dict[str, Any]:
    tp1, tp2, tp3, tp4 = targets[:4]
    risk = abs(sl - entry) if sl is not None and entry is not None else None
    return {
        "sl_tight": _round_price(sl, digits),
        "sl_safe": _round_price(_safe_stop(direction, sl, pip_value), digits),
        "tp1": _round_price(tp1, digits),
        "tp2": _round_price(tp2, digits),
        "tp3": _round_price(tp3, digits),
        "tp4": _round_price(tp4, digits),
        "tp1_rr": _rr(direction, entry, sl, tp1),
        "tp2_rr": _rr(direction, entry, sl, tp2),
        "tp3_rr": _rr(direction, entry, sl, tp3),
        "tp4_rr": _rr(direction, entry, sl, tp4),
        "rr_status": "VALID" if valid_for_execution else "WAIT_TARGET_STRUCTURE",
        "target_mode": target_mode,
        "tp_status": tp_status,
        "tp_missing_reason": tp_missing_reason,
        "structure_targets_available": structure_targets_available,
        "structure_rr_valid": structure_rr_valid,
        "valid_for_execution": valid_for_execution,
        "tp_min_rr": _round_price(_rr_target(direction, entry, sl, min_rr), digits),
        "tp_min_rr_value": min_rr,
        "reclaim_trigger": _round_price(reclaim_trigger, digits),
        "invalidation": invalidation,
        "risk_pips": round(risk / pip_value, 1) if risk is not None and pip_value > 0 else None,
        "trade_plan": {
            "direction": direction,
            "entry_mode": f"{direction}_SIGNAL_ZONE_OR_RETEST",
            "stop_loss": _round_price(sl, digits),
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
    values = [value for value in (start, end) if value is not None]
    if not values:
        return None
    return [_round_price(min(values), 5), _round_price(max(values), 5)]


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


def _first_rr_at_least(direction: str, entry: float | None, sl: float | None, targets: list[float], min_rr: float) -> float | None:
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


def _rr_fallback_targets(direction: str, entry: float, sl: float, min_rr: float) -> list[float]:
    multipliers = [1.0, 2.0, min_rr, 3.0]
    risk = abs(entry - sl)
    if direction == "BUY":
        return [entry + risk * multiplier for multiplier in multipliers]
    return [entry - risk * multiplier for multiplier in multipliers]


def _safe_stop(direction: str, sl: float | None, pip_value: float) -> float | None:
    if sl is None:
        return None
    return sl - (8.0 * pip_value) if direction == "BUY" else sl + (8.0 * pip_value)


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
