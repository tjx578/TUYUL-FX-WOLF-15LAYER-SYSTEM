"""
Central event bus for TUYUL FX system.
Decouples components while maintaining authority boundaries.
Events are typed and validated -- not a free-for-all.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
import time

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("tuyul.event_bus")


class EventType(Enum):
    # Analysis events (read-only, informational)
    TICK_RECEIVED = "TICK_RECEIVED"
    CANDLE_CLOSED = "CANDLE_CLOSED"
    ANALYSIS_COMPLETE = "ANALYSIS_COMPLETE"

    # Constitution events (decision authority)
    VERDICT_ISSUED = "VERDICT_ISSUED"
    SIGNAL_EXPIRED = "SIGNAL_EXPIRED"
    SIGNAL_REJECTED = "SIGNAL_REJECTED"

    # Dashboard events (risk/account authority)
    RISK_CHECK_PASSED = "RISK_CHECK_PASSED"
    RISK_CHECK_FAILED = "RISK_CHECK_FAILED"
    ACCOUNT_UPDATED = "ACCOUNT_UPDATED"

    # Execution events (reporting only -- no authority)
    ORDER_PLACED = "ORDER_PLACED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_FAILED = "ORDER_FAILED"
    POSITION_CLOSED = "POSITION_CLOSED"

    # System events
    FEED_CONNECTED = "FEED_CONNECTED"
    FEED_DISCONNECTED = "FEED_DISCONNECTED"
    FEED_STALE = "FEED_STALE"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    HEARTBEAT = "HEARTBEAT"


@dataclass
class Event:
    type: EventType
    source: str  # Which module emitted this
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_id: str = ""

    def __post_init__(self):
        if not self.event_id:
            import uuid  # noqa: PLC0415
            self.event_id = uuid.uuid4().hex[:12]


# Authority boundary enforcement
_ALLOWED_SOURCES: dict[EventType, list[str]] = {
    EventType.VERDICT_ISSUED: ["constitution"],
    EventType.SIGNAL_EXPIRED: ["constitution"],
    EventType.SIGNAL_REJECTED: ["constitution"],
    EventType.RISK_CHECK_PASSED: ["dashboard", "risk"],
    EventType.RISK_CHECK_FAILED: ["dashboard", "risk"],
    EventType.ACCOUNT_UPDATED: ["dashboard"],
    EventType.ORDER_PLACED: ["execution"],
    EventType.ORDER_FILLED: ["execution"],
    EventType.ORDER_CANCELLED: ["execution"],
    EventType.ORDER_FAILED: ["execution"],
    EventType.ANALYSIS_COMPLETE: ["analysis"],
    EventType.CANDLE_CLOSED: ["ingest"],
    EventType.TICK_RECEIVED: ["ingest"],
}


class EventBus:
    """
    Async event bus with authority enforcement.
    Modules can only emit events they're authorized to emit.
    """

    def __init__(self):
        self._subscribers: dict[EventType, list[Callable]] = {}
        self._event_log: deque[Event] = deque(maxlen=10_000)

    def subscribe(self, event_type: EventType, handler: Callable[[Event], Any]) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
        logger.debug(f"Subscribed to {event_type.value}: {handler.__qualname__}")

    async def emit(self, event: Event) -> None:
        """
        Emit an event. Validates source authority before dispatching.
        """
        # Authority check
        allowed = _ALLOWED_SOURCES.get(event.type)
        if allowed is not None and event.source not in allowed:
            logger.error(
                f"AUTHORITY VIOLATION: {event.source} tried to emit {event.type.value} "
                f"(allowed: {allowed})"
            )
            raise PermissionError(
                f"Module '{event.source}' is not authorized to emit '{event.type.value}'"
            )

        # Log event
        self._event_log.append(event)

        # Dispatch to subscribers
        handlers = self._subscribers.get(event.type, [])
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Handler error for {event.type.value}: {e}", exc_info=True)

    def emit_sync(self, event: Event) -> None:
        """Synchronous emit for non-async contexts."""
        allowed = _ALLOWED_SOURCES.get(event.type)
        if allowed is not None and event.source not in allowed:
            raise PermissionError(
                f"Module '{event.source}' is not authorized to emit '{event.type.value}'"
            )

        self._event_log.append(event)
        handlers = self._subscribers.get(event.type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Handler error for {event.type.value}: {e}", exc_info=True)

    def get_recent_events(self, event_type: EventType | None = None, limit: int = 100) -> list[Event]:
        events = list(self._event_log)
        if event_type:
            events = [e for e in events if e.type == event_type]
        return events[-limit:]


# ── Module-level singleton ──────────────────────────────────────
_event_bus_instance: EventBus | None = None


def get_event_bus() -> EventBus:
    """Return the process-wide EventBus singleton."""
    global _event_bus_instance
    if _event_bus_instance is None:
        _event_bus_instance = EventBus()
    return _event_bus_instance
