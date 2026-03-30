"""Event Bus — Redis pub/sub untuk komunikasi antar agent."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Callable, Coroutine

from loguru import logger

from infrastructure.redis_client import get_async_redis

CHANNEL_PREFIX = os.getenv("REDIS_PREFIX", "tuyul")
SWARM_CHANNEL = f"{CHANNEL_PREFIX}:swarm:events"
AGENT_CHANNEL_TPL = f"{CHANNEL_PREFIX}:agent:{{agent_name}}:events"
DECISION_CHANNEL = f"{CHANNEL_PREFIX}:decisions"
HALT_CHANNEL = f"{CHANNEL_PREFIX}:halt:broadcast"
HANDOFF_CHANNEL = f"{CHANNEL_PREFIX}:handoff:events"


class EventBus:
    """Redis-based event bus untuk koordinasi antar agent dalam swarm."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = {}
        self._running = False

    async def publish(self, channel: str, event_type: str, payload: dict[str, Any]) -> None:
        """Publish event ke channel Redis."""
        redis = await get_async_redis()
        message = json.dumps({
            "event_type": event_type,
            "payload": payload,
            "timestamp": datetime.utcnow().isoformat(),
            "channel": channel,
        })
        await redis.publish(channel, message)
        logger.debug(f"[EventBus] Published {event_type} -> {channel}")

    async def publish_decision(self, decision_data: dict[str, Any]) -> None:
        """Publish decision packet ke semua subscriber."""
        await self.publish(DECISION_CHANNEL, "decision.emitted", decision_data)

    async def publish_halt(self, reason: str, agent_name: str) -> None:
        """Broadcast HALT signal — override semua agent aktif."""
        await self.publish(HALT_CHANNEL, "system.halt", {
            "reason": reason,
            "triggered_by": agent_name,
        })
        logger.critical(f"[EventBus] HALT BROADCAST dari {agent_name}: {reason}")

    async def publish_handoff(self, handoff_summary: dict[str, Any]) -> None:
        """Publish shift handoff summary."""
        await self.publish(HANDOFF_CHANNEL, "shift.handoff", handoff_summary)

    async def publish_agent_event(self, agent_name: str, event_type: str, data: dict[str, Any]) -> None:
        """Publish event spesifik untuk satu agent."""
        channel = AGENT_CHANNEL_TPL.format(agent_name=agent_name)
        await self.publish(channel, event_type, data)

    async def subscribe_and_listen(
        self,
        channel: str,
        handler: Callable[[dict[str, Any]], Coroutine],
    ) -> None:
        """Subscribe ke channel dan listen secara async."""
        redis = await get_async_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        self._running = True
        logger.info(f"[EventBus] Subscribed to {channel}")

        async for message in pubsub.listen():
            if not self._running:
                break
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    await handler(data)
                except Exception as e:
                    logger.error(f"[EventBus] Handler error on {channel}: {e}")

    def stop(self) -> None:
        self._running = False


# Global singleton
_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
