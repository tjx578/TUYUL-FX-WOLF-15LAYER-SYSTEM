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
