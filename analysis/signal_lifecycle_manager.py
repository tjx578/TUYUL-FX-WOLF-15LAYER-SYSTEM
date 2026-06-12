"""Lifecycle management for validated SignalJSON candidates.

The classifier decides what a new microboost signal means.  The lifecycle
manager decides what that signal means relative to an already-active signal on
the same symbol.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

FINAL_ACTIVE_STATUSES = {
    "FINAL_EXECUTION_READY",
    "BUY_TIMING_VALID_BY_QUORUM_CONTINUATION",
    "SELL_TIMING_VALID_BY_QUORUM_CONTINUATION",
    "BUY_TIMING_VALID",
    "SELL_TIMING_VALID",
    "BUY_TIMING_VALID_BY_DIRECT_ABSORPTION",
    "SELL_TIMING_VALID_BY_DIRECT_ABSORPTION",
    "BUY_TIMING_VALID_BY_ABSORPTION",
    "SELL_TIMING_VALID_BY_ABSORPTION",
    "BUY_BREAKOUT_CONTINUATION_VALID",
    "BUY_BREAKOUT_RETEST_VALID",
    "SELL_BREAKDOWN_CONTINUATION_VALID",
    "SELL_BREAKDOWN_RETEST_VALID",
    "BUY_REVERSAL_VALID",
    "SELL_REVERSAL_VALID",
}

ABSORPTION_WATCH_STATUSES = {
    "SELL_ABSORPTION_WATCH",
    "BUY_ABSORPTION_WATCH",
}

# P1A active-signal lifecycle taxonomy. Direction-agnostic: every BUY status has a
# SELL mirror because the direction is a template parameter, never hardcoded.
OPPOSITE_DIRECTION = {"BUY": "SELL", "SELL": "BUY"}

_ACTIVE_LIFECYCLE_SUFFIXES = (
    "MONITOR_COUNTER_PRESSURE",
    "PROTECT_PROFIT",
    "NO_NEW_ADD",
    "EXIT_ALERT",
    "INVALIDATED",
)

# REVERSED embeds the opposite direction, so it is templated separately.
ACTIVE_LIFECYCLE_STATUSES = frozenset(
    {f"ACTIVE_{direction}_{suffix}" for direction in ("BUY", "SELL") for suffix in _ACTIVE_LIFECYCLE_SUFFIXES}
    | {f"ACTIVE_{direction}_REVERSED_TO_{OPPOSITE_DIRECTION[direction]}_WATCH" for direction in ("BUY", "SELL")}
)

_PROTECT_PROFIT_PHASES = frozenset(
    {"EXHAUSTION_AT_RESISTANCE", "EXHAUSTION_AT_SUPPORT", "LATE_DENSE_PRESSURE"}
)


@dataclass(frozen=True)
class ActiveSignal:
    signal_id: str
    symbol: str
    direction: str
    status: str
    signal_valid_time_utc: str | None
    signal_valid_price: float | None
    entry_zone: list[float] | None
    sl_safe: float | None
    tp1: float | None
    tp2: float | None
    tp3: float | None
    tp1_rr: float | None
    lifecycle_status: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "status": self.status,
            "signal_valid_time_utc": self.signal_valid_time_utc,
            "signal_valid_price": self.signal_valid_price,
            "entry_zone": self.entry_zone,
            "sl_safe": self.sl_safe,
            "tp1": self.tp1,
            "tp2": self.tp2,
            "tp3": self.tp3,
            "tp1_rr": self.tp1_rr,
            "lifecycle_status": self.lifecycle_status,
        }


class SignalLifecycleManager:
    """Keep per-symbol signal state and classify conflicting follow-up signals."""

    def __init__(self) -> None:
        self._active: dict[str, ActiveSignal] = {}

    def apply(self, signal: dict[str, Any]) -> dict[str, Any]:
        payload = deepcopy(signal)
        symbol = str(payload.get("symbol") or "").upper()
        direction = _direction(payload)
        if not symbol or direction not in {"BUY", "SELL"}:
            return payload

        active = self._active.get(symbol)
        if active is None:
            if _is_final_active(payload):
                self._active[symbol] = _active_from_payload(payload)
                payload.setdefault("lifecycle_status", f"ACTIVE_{direction}_VALID")
                payload.setdefault("signal_id", self._active[symbol].signal_id)
                payload.setdefault("active_position_policy", f"TRACK_ACTIVE_{direction}")
                payload.setdefault(
                    "active_signal_management",
                    _management_payload(self._active[symbol], policy="NEW_ACTIVE_SIGNAL_TRACKING"),
                )
            return payload

        payload["linked_previous_signal"] = active.signal_id
        payload["previous_signal_status"] = active.lifecycle_status
        payload["active_signal"] = active.to_payload()
        payload.setdefault("active_position_policy", "ACTIVE_SIGNAL_AWARE")
        payload.setdefault(
            "active_signal_management",
            _management_payload(active, policy="COMPARE_WITH_EXISTING_ACTIVE_SIGNAL"),
        )

        if active.direction == direction:
            if _is_breakout_reinforcement(active, payload):
                return self._breakout_reinforces_active_signal(active, payload)
            payload["lifecycle_status"] = "REINFORCES_ACTIVE_SIGNAL"
            payload["previous_signal_status"] = "REINFORCED"
            payload["active_position_policy"] = f"REINFORCE_ACTIVE_{direction}"
            payload["active_signal_management"] = _management_payload(
                active,
                policy="REINFORCEMENT_ONLY_WAIT_RETEST_OR_HOLD",
            )
            if _is_final_active(payload):
                self._active[symbol] = _active_from_payload(payload, lifecycle_status=f"ACTIVE_{direction}_VALID")
                payload["signal_id"] = self._active[symbol].signal_id
            return payload

        if payload.get("status") in ABSORPTION_WATCH_STATUSES:
            return self._protect_active_signal(active, payload)

        if _is_final_active(payload):
            return self._supersede_with_reversal(active, payload)

        payload["lifecycle_status"] = "CONFLICT_WAIT_M15_CLOSE"
        payload["action"] = "WAIT_M15_CLOSE"
        payload["final_direction"] = "WAIT"
        payload["validated_direction"] = None
        payload["watch_direction"] = direction
        payload["direction_validation_status"] = "CONFLICT_WATCH_ONLY_PENDING_M15_CLOSE"
        payload["active_position_policy"] = f"PROTECT_ACTIVE_{active.direction}_WAIT_OPPOSING_CONFIRMATION"
        payload["active_signal_management"] = _management_payload(
            active,
            policy="NO_REVERSAL_UNTIL_M15_CLOSE_AND_STRUCTURE_CONFIRM",
        )
        return payload

    def active_signal(self, symbol: str) -> dict[str, Any] | None:
        active = self._active.get(symbol.upper())
        return None if active is None else active.to_payload()

    def _protect_active_signal(self, active: ActiveSignal, payload: dict[str, Any]) -> dict[str, Any]:
        payload["final_direction"] = "WAIT"
        payload["lifecycle_status"] = f"CONFLICT_PROTECT_ACTIVE_{active.direction}"
        payload["previous_signal_status"] = f"ACTIVE_{active.direction}_VALID"
        payload["action"] = f"PROTECT_{active.direction}_PROFIT_WAIT_M15_CLOSE"
        payload["valid_for_execution"] = False
        payload["validated_direction"] = None
        payload["watch_direction"] = _direction(payload)
        payload["direction_validation_status"] = "ACTIVE_SIGNAL_PROTECTION_WATCH"
        payload["active_position_policy"] = f"PROTECT_ACTIVE_{active.direction}_NO_AUTO_REVERSAL"
        payload["active_signal_management"] = _management_payload(
            active,
            policy="PROTECT_PROFIT_ONLY_WAIT_M15_CLOSE",
        )
        payload["reason"] = (
            f"{active.direction} plan is active; opposing absorption pressure is a profit-protection "
            f"and M15-close decision event, not an automatic reversal. {payload.get('reason') or ''}"
        ).strip()
        return payload

    def _breakout_reinforces_active_signal(self, active: ActiveSignal, payload: dict[str, Any]) -> dict[str, Any]:
        direction = active.direction
        payload["status"] = (
            "BUY_BREAKOUT_CONTINUATION_VALID" if direction == "BUY" else "SELL_BREAKDOWN_CONTINUATION_VALID"
        )
        payload["final_direction"] = direction
        payload["validated_direction"] = direction
        payload["lifecycle_status"] = "REINFORCES_ACTIVE_SIGNAL"
        payload["previous_signal_status"] = "REINFORCED"
        payload["action"] = f"HOLD_{direction}_OR_{direction}_RETEST"
        payload["valid_for_execution"] = True
        payload["active_position_policy"] = f"REINFORCE_ACTIVE_{direction}"
        payload["active_signal_management"] = _management_payload(
            active,
            policy="HOLD_OR_ADD_ONLY_ON_RETEST",
        )
        payload.setdefault("rr_status", "VALID")
        payload.setdefault("target_mode", "FINAL_MARKET_STRUCTURE")
        payload.setdefault("sl_safe", active.sl_safe)
        payload.setdefault("tp1", active.tp1)
        payload.setdefault("tp2", active.tp2)
        payload.setdefault("tp3", active.tp3)
        payload.setdefault("tp1_rr", active.tp1_rr)
        return payload

    def _supersede_with_reversal(self, active: ActiveSignal, payload: dict[str, Any]) -> dict[str, Any]:
        direction = _direction(payload)
        if direction not in {"BUY", "SELL"}:
            return payload
        payload["status"] = f"{direction}_REVERSAL_VALID"
        payload["lifecycle_status"] = f"SUPERSEDES_ACTIVE_{active.direction}"
        payload["previous_signal_status"] = "SUPERSEDED"
        payload["action"] = f"EXIT_{active.direction}_AND_{direction}_RETEST"
        payload["active_position_policy"] = f"SUPERSEDE_ACTIVE_{active.direction}_WITH_{direction}"
        payload["active_signal_management"] = _management_payload(
            active,
            policy="EXIT_ACTIVE_ONLY_AFTER_REVERSAL_VALID",
        )
        self._active[active.symbol] = _active_from_payload(payload, lifecycle_status=f"ACTIVE_{direction}_VALID")
        payload["signal_id"] = self._active[active.symbol].signal_id
        return payload

    @staticmethod
    def _reversal_transition_ready(active: ActiveSignal, payload: dict[str, Any]) -> bool:
        confirmation = str(payload.get("m15_confirmation_status") or "")
        confirmed = bool(payload.get("reversal_confirmed")) or confirmation in {
            "M15_CLOSE_REJECTION_CONFIRMED",
            "M15_CLOSE_ABOVE_RESISTANCE",
            "M15_CLOSE_BELOW_SUPPORT",
        }
        elapsed = _optional_int(payload.get("cooldown_m15_bars_elapsed"))
        if elapsed is None:
            elapsed = _elapsed_m15_bars(active.signal_valid_time_utc, _optional_str(payload.get("signal_valid_time_utc")))
        payload["reversal_confirmed"] = confirmed
        payload["cooldown_m15_bars_elapsed"] = elapsed
        return confirmed and elapsed >= 1

    @staticmethod
    def _hold_opposing_final_for_confirmation(active: ActiveSignal, payload: dict[str, Any]) -> dict[str, Any]:
        direction = _direction(payload) or "WAIT"
        payload["source_status"] = payload.get("status")
        payload["source_final_direction"] = direction
        payload["final_direction"] = "WAIT"
        payload["valid_for_execution"] = False
        payload["lifecycle_status"] = "CONFLICT_WAIT_REVERSAL_CONFIRMATION_AND_COOLDOWN"
        payload["previous_signal_status"] = f"ACTIVE_{active.direction}_VALID"
        payload["action"] = "WAIT_REVERSAL_CONFIRMATION_AND_M15_COOLDOWN"
        payload["validated_direction"] = None
        payload["watch_direction"] = direction if direction in {"BUY", "SELL"} else None
        payload["direction_validation_status"] = "REVERSAL_WATCH_PENDING_COOLDOWN"
        payload["active_position_policy"] = f"PROTECT_ACTIVE_{active.direction}_WAIT_REVERSAL_COOLDOWN"
        payload["active_signal_management"] = _management_payload(
            active,
            policy="NO_REVERSAL_UNTIL_COOLDOWN_CONFIRMS",
        )
        return payload


def _is_final_active(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "")
    return (
        status in FINAL_ACTIVE_STATUSES
        and _direction(payload) in {"BUY", "SELL"}
        and bool(payload.get("valid_for_execution", False))
    )


def _management_payload(active: ActiveSignal, *, policy: str) -> dict[str, Any]:
    return {
        "policy": policy,
        "active_signal_id": active.signal_id,
        "active_direction": active.direction,
        "active_status": active.status,
        "active_lifecycle_status": active.lifecycle_status,
        "automatic_reversal_allowed": False,
    }


def _direction(payload: dict[str, Any]) -> str | None:
    for key in ("final_direction", "validated_direction", "candidate_direction", "raw_direction"):
        direction = str(payload.get(key) or "").upper()
        if direction in {"BUY", "SELL"}:
            return direction
    return None


def _is_breakout_reinforcement(active: ActiveSignal, payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "")
    return (
        active.direction == "BUY" and status in {"BREAKOUT_CONTINUATION_BUY", "BUY_BREAKOUT_CONTINUATION_VALID"}
    ) or (active.direction == "SELL" and status in {"BREAKDOWN_CONTINUATION_SELL", "SELL_BREAKDOWN_CONTINUATION_VALID"})


def _active_from_payload(payload: dict[str, Any], lifecycle_status: str | None = None) -> ActiveSignal:
    symbol = str(payload.get("symbol") or "").upper()
    direction = _direction(payload) or "WAIT"
    return ActiveSignal(
        signal_id=str(payload.get("signal_id") or _signal_id(payload, direction)),
        symbol=symbol,
        direction=direction,
        status=str(payload.get("status") or "UNKNOWN"),
        signal_valid_time_utc=_optional_str(payload.get("signal_valid_time_utc")),
        signal_valid_price=_optional_float(payload.get("signal_valid_price")),
        entry_zone=_entry_zone(payload.get("entry_zone")),
        sl_safe=_optional_float(payload.get("sl_safe")),
        tp1=_optional_float(payload.get("tp1")),
        tp2=_optional_float(payload.get("tp2")),
        tp3=_optional_float(payload.get("tp3")),
        tp1_rr=_optional_float(payload.get("tp1_rr")),
        lifecycle_status=lifecycle_status or str(payload.get("lifecycle_status") or f"ACTIVE_{direction}_VALID"),
    )


def _signal_id(payload: dict[str, Any], direction: str) -> str:
    symbol = str(payload.get("symbol") or "UNKNOWN").upper()
    raw_time = str(payload.get("signal_valid_time_wita") or payload.get("signal_valid_time_utc") or "")
    compact_time = _compact_time(raw_time)
    return f"{symbol}_{direction}_{compact_time}" if compact_time else f"{symbol}_{direction}_ACTIVE"


def _compact_time(value: str) -> str | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S",):
        try:
            return datetime.strptime(value, fmt).strftime("%Y%m%d_%H%M%S")
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y%m%d_%H%M%S")
    except ValueError:
        return None


def _entry_zone(value: Any) -> list[float] | None:
    if not isinstance(value, list):
        return None
    values = [_optional_float(item) for item in value]
    compact: list[float] = []
    for item in values:
        if item is not None:
            compact.append(item)
    return compact or None


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


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _elapsed_m15_bars(start: str | None, end: str | None) -> int:
    if not start or not end:
        return 0
    try:
        start_at = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_at = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, int((end_at - start_at).total_seconds() // (15 * 60)))


def _has_auditable_promotion(payload: dict[str, Any]) -> bool:
    has_parent = bool(payload.get("parent_event_exists") is True and _optional_str(payload.get("parent_watch_id")))
    has_bypass = bool(
        str(payload.get("promotion_path") or "").upper() == "DIRECT_BYPASS"
        and _optional_str(payload.get("bypass_reason"))
        and payload.get("parent_watch_required") is False
    )
    return has_parent or has_bypass


def classify_active_lifecycle_status(active_direction: str | None, counter_payload: dict[str, Any]) -> str | None:
    """Pure mapper: given an active signal's direction and a follow-up payload,
    return the finer ``ACTIVE_{DIRECTION}_…`` lifecycle status, or ``None`` when the
    follow-up does not change the active position's lifecycle.

    Direction-agnostic: BUY and SELL flow through the same template, so every BUY
    branch has an automatic SELL mirror.  This is evidence/management classification
    only — it never marks anything executable and never mints a reversal signal.
    Conditions are ordered most-severe first.
    """
    active = str(active_direction or "").upper()
    if active not in {"BUY", "SELL"}:
        return None
    opposite = OPPOSITE_DIRECTION[active]
    counter = _direction(counter_payload)

    if _is_active_invalidated(counter_payload, active):
        if _is_opposite_setup_valid_not_executable(counter_payload, opposite):
            return f"ACTIVE_{active}_REVERSED_TO_{opposite}_WATCH"
        return f"ACTIVE_{active}_INVALIDATED"

    if _is_rejection_against_active(counter_payload, active):
        return f"ACTIVE_{active}_EXIT_ALERT"

    if _is_protect_profit_pressure(counter_payload):
        return f"ACTIVE_{active}_PROTECT_PROFIT"

    if counter == opposite:
        return f"ACTIVE_{active}_MONITOR_COUNTER_PRESSURE"

    if _is_over_extended(counter_payload, active):
        return f"ACTIVE_{active}_NO_NEW_ADD"

    return None


def _is_active_invalidated(payload: dict[str, Any], active: str) -> bool:
    if _truthy(payload.get("active_signal_invalidated")) or _truthy(payload.get("structure_flip")):
        return True
    if active == "BUY":
        return _truthy(payload.get("m15_close_below_support"))
    return _truthy(payload.get("m15_close_above_resistance"))


def _is_opposite_setup_valid_not_executable(payload: dict[str, Any], opposite: str) -> bool:
    if bool(payload.get("valid_for_execution", False)):
        return False
    validated = str(payload.get("validated_direction") or payload.get("candidate_direction") or "").upper()
    if validated != opposite:
        return False
    status = str(payload.get("status") or "").upper()
    rr_status = str(payload.get("rr_status") or "").upper()
    return status.endswith("_VALID") or rr_status in {"VALID", "ACCEPTABLE", "PROTECT_ONLY"} or _truthy(
        payload.get("tradeplan_valid")
    )


def _is_rejection_against_active(payload: dict[str, Any], active: str) -> bool:
    if _truthy(payload.get("failed_reclaim")) or _truthy(payload.get("strong_rejection")):
        return True
    phase = str(payload.get("phase_priced") or "").upper()
    if active == "BUY":
        return phase == "RESISTANCE_REJECTION_MICROBOOST"
    return phase == "SUPPORT_BOUNCE_MICROBOOST"


def _is_protect_profit_pressure(payload: dict[str, Any]) -> bool:
    phase = str(payload.get("phase_priced") or "").upper()
    status = str(payload.get("status") or "").upper()
    return phase in _PROTECT_PROFIT_PHASES or status in ABSORPTION_WATCH_STATUSES


def _is_over_extended(payload: dict[str, Any], active: str) -> bool:
    if _truthy(payload.get("over_extended")):
        return True
    position = str(payload.get("price_position") or "").upper()
    if active == "BUY":
        return position == "MAIN_RESISTANCE"
    return position == "MAIN_SUPPORT"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


# ── P1B: shadow-only preview (pure; no live behavior, never executable) ──────

_LIFECYCLE_MANAGEMENT_TEMPLATES = {
    "MONITOR_COUNTER_PRESSURE": "MONITOR_{active}_COUNTER_PRESSURE",
    "PROTECT_PROFIT": "PROTECT_{active}_PROFIT",
    "NO_NEW_ADD": "HOLD_{active}_NO_NEW_ADD",
    "EXIT_ALERT": "EXIT_OR_PROTECT_{active}",
    "INVALIDATED": "EXIT_{active}_INVALIDATED",
}


def is_active_execution_grade(payload: dict[str, Any]) -> bool:
    """True when the payload is an execution-grade final that becomes the active signal."""
    return _is_final_active(payload)


def payload_signal_direction(payload: dict[str, Any]) -> str | None:
    return _direction(payload)


def build_lifecycle_preview(active_signal_direction: str | None, counter_payload: dict[str, Any]) -> dict[str, Any] | None:
    """Pure shadow preview: what the active-signal lifecycle WOULD say. ``live_applied``
    is always False — this never changes a live decision or marks anything executable."""
    active = str(active_signal_direction or "").upper()
    if active not in {"BUY", "SELL"}:
        return None
    status = classify_active_lifecycle_status(active, counter_payload)
    if status is None:
        return None
    opposite = OPPOSITE_DIRECTION[active]
    return {
        "source": "SignalLifecycleManagerShadow",
        "active_signal_direction": active,
        "counter_direction": _direction(counter_payload),
        "suggested_lifecycle_status": status,
        "suggested_management_action": _lifecycle_management_action(status, active, opposite),
        "confidence": "SHADOW_ONLY",
        "live_applied": False,
        "reason": _lifecycle_preview_reason(status, active, opposite),
    }


def shadow_preview_event(active_directions: dict[str, str], payload: dict[str, Any]) -> dict[str, Any] | None:
    """Pure: build the shadow preview event for ``payload`` given the active-direction
    map, or ``None``. Does not mutate inputs."""
    symbol = str(payload.get("symbol") or "").upper()
    if not symbol:
        return None
    active = active_directions.get(symbol)
    if not active:
        return None
    preview = build_lifecycle_preview(active, payload)
    if preview is None:
        return None
    return {"event": "signal_lifecycle_shadow_preview", "symbol": symbol, "lifecycle_preview": preview}


def record_active_if_execution_grade(active_directions: dict[str, str], payload: dict[str, Any]) -> bool:
    """Shadow-only state update: record ``symbol -> direction`` when ``payload`` is an
    execution-grade final. Returns True if recorded. Mutates ``active_directions`` only."""
    if not is_active_execution_grade(payload):
        return False
    symbol = str(payload.get("symbol") or "").upper()
    direction = payload_signal_direction(payload)
    if not symbol or direction not in {"BUY", "SELL"}:
        return False
    active_directions[symbol] = direction
    return True


def _lifecycle_management_action(status: str, active: str, opposite: str) -> str:
    if status.endswith(f"_REVERSED_TO_{opposite}_WATCH"):
        return f"EXIT_{active}_AND_WATCH_{opposite}"
    for suffix, template in _LIFECYCLE_MANAGEMENT_TEMPLATES.items():
        if status.endswith(f"_{suffix}"):
            return template.format(active=active)
    return f"MANAGE_{active}"


def _lifecycle_preview_reason(status: str, active: str, opposite: str) -> str:
    if status.endswith("_PROTECT_PROFIT"):
        return f"Counter/exhaustion pressure while active {active} is in profit; protect, no auto-reversal."
    if status.endswith("_MONITOR_COUNTER_PRESSURE"):
        return f"Small {opposite} counter pressure against active {active}; monitor only."
    if status.endswith("_NO_NEW_ADD"):
        return f"Active {active} still valid but over-extended; hold, no new add."
    if status.endswith("_EXIT_ALERT"):
        return f"Active {active} rejection / failed reclaim; exit-or-protect alert."
    if status.endswith("_INVALIDATED"):
        return f"Active {active} invalidated by structure break."
    if "_REVERSED_TO_" in status:
        return f"Active {active} invalidated and {opposite} setup forming (not execution-grade); watch only."
    return f"Active {active} lifecycle update."
