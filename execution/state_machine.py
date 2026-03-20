"""
Execution Bridge — strict, replay-safe state machine for EA/broker order intent.

TUYUL FX v2 Architecture:
------------------------------------------------------------
• This module is the execution bridge: connects pipeline verdicts (L12) to EA/broker, not consumer observability.
• Separate from output/observability (dashboard, journal, metrics, alerts).
• Handles order intent, compliance, kill switch, and authority gating.
• No analytical or decision logic — only state transitions for execution.
• Each symbol gets its own independent StateMachine (multi-pair safe).
• Authority boundaries: only pipeline verdict (L12) can trigger execution; EventBus is orchestration/trigger only.

Backward compatibility:
    ``ExecutionStateMachine`` is now an alias for ``StateMachineRegistry``
    (a thread-safe singleton).  Code that previously called
    ``ExecutionStateMachine().set_pending(...)`` should migrate to
    ``ExecutionStateMachine().get(symbol).set_pending(...)``.
"""

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
    """Single-symbol FSM.  Not a singleton — one instance per symbol."""

    def __init__(self) -> None:
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
                raise ValueError(f"Invalid transition: {current.value} + {event.value}")

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


class StateMachineRegistry:
    """Thread-safe registry of per-symbol ``StateMachine`` instances.

    Usage::

        registry = StateMachineRegistry()   # singleton
        sm = registry.get("EURUSD")
        sm.set_pending({"order_id": "T-1", "symbol": "EURUSD"})
    """

    _instance: StateMachineRegistry | None = None
    _instance_lock = Lock()
    _machines: dict[str, StateMachine]
    _reg_lock: Lock

    def __new__(cls) -> StateMachineRegistry:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._machines = {}
                    inst._reg_lock = Lock()
                    cls._instance = inst
        return cls._instance

    # -- per-symbol access -------------------------------------------------

    def get(self, symbol: str) -> StateMachine:
        """Return the FSM for *symbol*, creating one on first access."""
        sym = symbol.upper()
        if sym not in self._machines:
            with self._reg_lock:
                if sym not in self._machines:
                    self._machines[sym] = StateMachine()
        return self._machines[sym]

    def symbols(self) -> list[str]:
        """Return list of tracked symbols."""
        return list(self._machines.keys())

    def snapshot_all(self) -> dict[str, dict[str, Any]]:
        """Return ``{symbol: snapshot}`` for every tracked symbol."""
        return {sym: sm.snapshot() for sym, sm in self._machines.items()}

    def reset(self, symbol: str) -> None:
        """Reset FSM for *symbol* back to IDLE.  Useful after trade lifecycle."""
        sym = symbol.upper()
        with self._reg_lock:
            self._machines[sym] = StateMachine()

    def reset_all(self) -> None:
        """Clear all tracked symbols.  **Test-only.**"""
        with self._reg_lock:
            self._machines.clear()

    # -- backward-compat shims (delegate to unnamed / first symbol) -------
    # These let old callers that did ``ExecutionStateMachine().is_pending()``
    # continue to work during the migration period.  They operate on a
    # reserved ``__default__`` symbol.

    _DEFAULT = "__default__"

    def _default(self) -> StateMachine:
        return self.get(self._DEFAULT)

    def set_pending(self, order: dict[str, Any]) -> TransitionResult:
        return self._default().set_pending(order)

    def set_cancelled(self, reason: str) -> TransitionResult:
        return self._default().set_cancelled(reason)

    def set_filled(self, fill_info: dict[str, Any]) -> TransitionResult:
        return self._default().set_filled(fill_info)

    def is_pending(self) -> bool:
        return self._default().is_pending()

    def snapshot(self) -> dict[str, Any]:
        return self._default().snapshot()

    # -- singleton-compat for old code that called ``_init()`` on tests ---

    def _init(self) -> None:
        """Reset default symbol FSM — backward compat for tests."""
        self.reset(self._DEFAULT)


ExecutionStateMachine = StateMachineRegistry
