"""Execution state machine with strict, replay-safe transitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Any

from utils.timezone_utils import now_utc


class OrderState(StrEnum):
    IDLE = "IDLE"
    PENDING_ACTIVE = "PENDING_ACTIVE"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class OrderEvent(StrEnum):
    PLACE_ORDER = "PLACE_ORDER"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_EXPIRED = "ORDER_EXPIRED"


@dataclass(frozen=True)
class TransitionResult:
    applied: bool
    replay: bool
    from_state: str
    to_state: str
    reason: str


_TRANSITIONS: dict[OrderState, dict[OrderEvent, OrderState]] = {
    OrderState.IDLE: {
        OrderEvent.PLACE_ORDER: OrderState.PENDING_ACTIVE,
    },
    OrderState.PENDING_ACTIVE: {
        OrderEvent.ORDER_FILLED: OrderState.FILLED,
        OrderEvent.ORDER_CANCELLED: OrderState.CANCELLED,
        OrderEvent.ORDER_EXPIRED: OrderState.CANCELLED,
    },
    OrderState.FILLED: {},
    OrderState.CANCELLED: {},
}

_TERMINAL = {OrderState.FILLED, OrderState.CANCELLED}
_EVENT_TO_TERMINAL = {
    OrderEvent.ORDER_FILLED: OrderState.FILLED,
    OrderEvent.ORDER_CANCELLED: OrderState.CANCELLED,
    OrderEvent.ORDER_EXPIRED: OrderState.CANCELLED,
}


class StateMachine:
    _instance = None
    _instance_lock = Lock()

    def __new__(cls):
        if not cls._instance:
            with cls._instance_lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self.state = OrderState.IDLE
        self.order: dict[str, Any] | None = None
        self.reason: str | None = None
        self.timestamp = None
        self.last_event: str | None = None
        self._sm_lock = Lock()

    def apply(self, event: OrderEvent, payload: dict[str, Any] | None = None) -> TransitionResult:
        with self._sm_lock:
            current = self.state

            # Replay-safe no-op for same terminal outcome.
            target_terminal = _EVENT_TO_TERMINAL.get(event)
            if current in _TERMINAL and target_terminal == current:
                self.last_event = event.value
                self.timestamp = now_utc()
                return TransitionResult(
                    applied=False,
                    replay=True,
                    from_state=current.value,
                    to_state=current.value,
                    reason="REPLAY_TERMINAL_NOOP",
                )

            next_state = _TRANSITIONS.get(current, {}).get(event)
            if next_state is None:
                raise ValueError(
                    f"Invalid transition: {current.value} + {event.value}"
                )

            self.state = next_state
            self.last_event = event.value
            self.timestamp = now_utc()

            if payload is not None:
                self.order = payload
            if event in {OrderEvent.ORDER_CANCELLED, OrderEvent.ORDER_EXPIRED}:
                self.reason = str((payload or {}).get("reason") or event.value)
            else:
                self.reason = None

            return TransitionResult(
                applied=True,
                replay=False,
                from_state=current.value,
                to_state=next_state.value,
                reason="APPLIED",
            )

    def set_pending(self, order: dict[str, Any]) -> TransitionResult:
        return self.apply(OrderEvent.PLACE_ORDER, payload=order)

    def set_cancelled(self, reason: str) -> TransitionResult:
        return self.apply(OrderEvent.ORDER_CANCELLED, payload={"reason": reason})

    def set_filled(self, fill_info: dict[str, Any]) -> TransitionResult:
        return self.apply(OrderEvent.ORDER_FILLED, payload=fill_info)

    def is_pending(self) -> bool:
        return self.state == OrderState.PENDING_ACTIVE

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "order": self.order,
            "reason": self.reason,
            "last_event": self.last_event,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


ExecutionStateMachine = StateMachine
