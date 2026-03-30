"""
Compliance Auto-Mode — P1-9
==============================
Auto-trading mode state machine with event publishing and enforcement.

Two states:
  - AUTO_TRADING_ENABLED: Normal operation, take-signal flow proceeds.
  - AUTO_TRADING_PAUSED: Compliance violation detected, new trade flow is blocked.

Transitions:
  - ENABLED → PAUSED: triggered by compliance guard violation
  - PAUSED → ENABLED: manual operator reset (requires reason + audit)

The auto-mode is enforced at the orchestrator level before the risk firewall.
This module NEVER computes market direction — it is a compliance gate only.

Zone: risk/compliance — veto authority, NOT verdict authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from loguru import logger

from core.redis_keys import COMPLIANCE_AUTO_MODE, COMPLIANCE_AUTO_MODE_STATE
from services.orchestrator.protocols import StreamPublisherLike


class AutoTradingState(StrEnum):
    """Auto-trading mode states."""

    ENABLED = "ENABLED"
    PAUSED = "PAUSED"


@dataclass(frozen=True, slots=True)
class AutoModeTransition:
    """Immutable record of an auto-mode state change."""

    previous_state: AutoTradingState
    new_state: AutoTradingState
    trigger_code: str
    reason: str
    actor: str  # "system:compliance" or operator identity
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_state": self.previous_state.value,
            "new_state": self.new_state.value,
            "trigger_code": self.trigger_code,
            "reason": self.reason,
            "actor": self.actor,
            "timestamp": self.timestamp,
        }


class _AutoModeRedisProtocol(Protocol):
    """Minimal Redis protocol for auto-mode state persistence."""

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ex: int | None = None) -> None: ...


class ComplianceAutoMode:
    """Auto-trading mode state machine with event publishing.

    State is persisted to Redis so that restarts do not silently
    resume auto-trading when it was paused by a compliance violation.
    """

    def __init__(
        self,
        redis_client: _AutoModeRedisProtocol | None = None,
        stream_publisher: StreamPublisherLike | None = None,
    ) -> None:
        self._redis = redis_client
        self._publisher = stream_publisher
        self._transitions: list[AutoModeTransition] = []
        self._state: AutoTradingState = self._restore_state()

    def _get_publisher(self) -> StreamPublisherLike:
        if self._publisher is None:
            from infrastructure.stream_publisher import StreamPublisher  # noqa: PLC0415

            self._publisher = StreamPublisher()
        return self._publisher

    @property
    def state(self) -> AutoTradingState:
        return self._state

    @property
    def is_enabled(self) -> bool:
        return self._state == AutoTradingState.ENABLED

    @property
    def is_paused(self) -> bool:
        return self._state == AutoTradingState.PAUSED

    @property
    def transition_history(self) -> list[AutoModeTransition]:
        return list(self._transitions)

    def _restore_state(self) -> AutoTradingState:
        """Restore persisted state from Redis. Default PAUSED if previously paused."""
        if self._redis is None:
            return AutoTradingState.ENABLED
        try:
            raw = self._redis.get(COMPLIANCE_AUTO_MODE_STATE)
        except Exception:
            logger.warning("[ComplianceAutoMode] Redis read failed on init — defaulting to PAUSED for safety")
            return AutoTradingState.PAUSED
        if raw == AutoTradingState.PAUSED.value:
            logger.warning("[ComplianceAutoMode] Restored PAUSED state from Redis — operator resume required")
            return AutoTradingState.PAUSED
        return AutoTradingState.ENABLED

    def _persist_state(self) -> None:
        """Best-effort write of current state to Redis."""
        if self._redis is None:
            return
        try:
            self._redis.set(COMPLIANCE_AUTO_MODE_STATE, self._state.value)
        except Exception:
            logger.warning("[ComplianceAutoMode] Redis write failed — state may be lost on restart")

    async def pause(self, trigger_code: str, reason: str, actor: str = "system:compliance") -> AutoModeTransition:
        """Pause auto-trading. Idempotent: pausing when already paused is a no-op."""
        if self._state == AutoTradingState.PAUSED:
            return AutoModeTransition(
                previous_state=AutoTradingState.PAUSED,
                new_state=AutoTradingState.PAUSED,
                trigger_code=trigger_code,
                reason=f"Already paused (duplicate): {reason}",
                actor=actor,
            )

        transition = AutoModeTransition(
            previous_state=AutoTradingState.ENABLED,
            new_state=AutoTradingState.PAUSED,
            trigger_code=trigger_code,
            reason=reason,
            actor=actor,
        )
        self._state = AutoTradingState.PAUSED
        self._transitions.append(transition)
        self._persist_state()

        logger.warning(
            "[ComplianceAutoMode] PAUSED auto-trading: code=%s reason=%s actor=%s",
            trigger_code,
            reason,
            actor,
        )
        await self._emit_transition_event(transition)
        return transition

    async def resume(self, reason: str, actor: str) -> AutoModeTransition:
        """Resume auto-trading (requires explicit operator action).

        Raises ValueError if already enabled (prevents accidental resume).
        """
        if self._state == AutoTradingState.ENABLED:
            raise ValueError("Auto-trading is already enabled — nothing to resume")

        transition = AutoModeTransition(
            previous_state=AutoTradingState.PAUSED,
            new_state=AutoTradingState.ENABLED,
            trigger_code="OPERATOR_RESUME",
            reason=reason,
            actor=actor,
        )
        self._state = AutoTradingState.ENABLED
        self._transitions.append(transition)
        self._persist_state()

        logger.info(
            "[ComplianceAutoMode] RESUMED auto-trading: reason=%s actor=%s",
            reason,
            actor,
        )
        await self._emit_transition_event(transition)
        return transition

    def enforce(self) -> None:
        """Check auto-mode and raise if paused.

        Called by the orchestrator before the risk firewall.
        Raises ComplianceAutoModePaused if auto-trading is paused.
        """
        if self._state == AutoTradingState.PAUSED:
            raise ComplianceAutoModePaused("Auto-trading is paused by compliance — no new trades allowed")

    async def _emit_transition_event(self, transition: AutoModeTransition) -> None:
        """Emit state change event to Redis stream (best-effort, internal)."""
        try:
            publisher = self._get_publisher()
            await publisher.publish(
                stream=COMPLIANCE_AUTO_MODE,
                fields={
                    "event_type": f"AUTO_MODE_{transition.new_state.value}",
                    **transition.to_dict(),
                },
            )
        except Exception:
            logger.debug("[ComplianceAutoMode] Event emission failed")


class ComplianceAutoModePaused(Exception):  # noqa: N818
    """Raised when auto-trading is paused and a new trade is attempted."""
