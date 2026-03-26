"""
Take-Signal Service — P1-1/P1-2
=================================
Service layer for the take-signal operational binding flow.

Orchestrates: validation → idempotency check → signal lookup →
              record creation → event emission.

Zone: API / control plane — reads signal truth from engine,
      does NOT compute market direction or mutate verdicts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from core.redis_keys import TAKE_SIGNAL_EVENTS
from execution.take_signal_models import (
    TakeSignalCreateRequest,
    TakeSignalRecord,
    TakeSignalResponse,
    TakeSignalStatus,
)
from execution.take_signal_repository import TakeSignalRepository


class TakeSignalService:
    """Manages the take-signal operational binding lifecycle."""

    def __init__(
        self,
        repository: TakeSignalRepository | None = None,
    ) -> None:
        self._repo = repository or TakeSignalRepository()

    async def create(
        self,
        request: TakeSignalCreateRequest,
    ) -> tuple[TakeSignalResponse, bool]:
        """Create a take-signal binding record.

        Returns (response, created) where created=True if new, False if replay.
        Raises ValueError on idempotency conflict.
        """
        # Check idempotency: same request_id already exists?
        existing = await self._repo.get_by_request_id(request.request_id)
        if existing is not None:
            # Validate payload match
            if (
                existing.signal_id != request.signal_id
                or existing.account_id != request.account_id
                or existing.ea_instance_id != request.ea_instance_id
            ):
                raise ValueError(
                    f"Idempotency conflict: request_id={request.request_id} already bound with different payload"
                )
            return self._to_response(existing), False

        # Validate signal exists and is not expired
        signal = await self._lookup_signal(request.signal_id)
        if signal is None:
            raise SignalNotFoundError(request.signal_id)

        if self._is_signal_expired(signal):
            raise SignalExpiredError(request.signal_id)

        # Create the record
        take_id = f"take_{uuid.uuid4().hex[:16]}"
        now = datetime.now(UTC).isoformat()

        record = TakeSignalRecord(
            take_id=take_id,
            request_id=request.request_id,
            signal_id=request.signal_id,
            account_id=request.account_id,
            ea_instance_id=request.ea_instance_id,
            operator=request.operator,
            reason=request.reason,
            status=TakeSignalStatus.PENDING,
            strategy_profile_id=request.strategy_profile_id,
            metadata=request.metadata,
            created_at=now,
            updated_at=now,
        )

        record = await self._repo.create(record)

        # Emit event (best-effort, non-blocking)
        await self._emit_event("TAKE_SIGNAL_CREATED", record)

        logger.info(
            "[TakeSignalService] Created take_id=%s for signal=%s account=%s",
            take_id,
            request.signal_id,
            request.account_id,
        )
        return self._to_response(record), True

    async def get(self, take_id: str) -> TakeSignalResponse | None:
        """Get a take-signal record by take_id."""
        record = await self._repo.get(take_id)
        if record is None:
            return None
        return self._to_response(record)

    async def get_by_request_id(self, request_id: str) -> TakeSignalResponse | None:
        """Get a take-signal record by idempotency request_id."""
        record = await self._repo.get_by_request_id(request_id)
        if record is None:
            return None
        return self._to_response(record)

    async def transition(
        self,
        take_id: str,
        new_status: TakeSignalStatus,
        *,
        reason: str | None = None,
        firewall_result_id: str | None = None,
        execution_intent_id: str | None = None,
    ) -> TakeSignalResponse:
        """Transition a take-signal to a new lifecycle state.

        Validates transition rules. Raises on invalid transitions.
        """
        record = await self._repo.transition(
            take_id,
            new_status,
            reason=reason,
            firewall_result_id=firewall_result_id,
            execution_intent_id=execution_intent_id,
        )

        event_type = f"TAKE_SIGNAL_{new_status.value}"
        await self._emit_event(event_type, record)

        return self._to_response(record)

    async def cancel(self, take_id: str, reason: str = "OPERATOR_CANCEL") -> TakeSignalResponse:
        """Cancel a take-signal binding."""
        return await self.transition(
            take_id,
            TakeSignalStatus.CANCELLED,
            reason=reason,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _lookup_signal(self, signal_id: str) -> dict[str, Any] | None:
        """Look up a frozen signal by ID from the signal registry."""
        try:
            from allocation.signal_service import SignalService  # noqa: PLC0415

            svc = SignalService()
            return svc.get(signal_id)
        except Exception:
            logger.debug("[TakeSignalService] Signal lookup failed for {}", signal_id)
            return None

    @staticmethod
    def _is_signal_expired(signal: dict[str, Any]) -> bool:
        """Check if a signal has expired."""
        expires_at = signal.get("expires_at")
        if expires_at is None:
            return False
        try:
            exp = float(expires_at)
            return datetime.now(UTC).timestamp() > exp
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _to_response(record: TakeSignalRecord) -> TakeSignalResponse:
        return TakeSignalResponse(
            take_id=record.take_id,
            request_id=record.request_id,
            signal_id=record.signal_id,
            account_id=record.account_id,
            ea_instance_id=record.ea_instance_id,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
            status_reason=record.status_reason,
            firewall_result_id=record.firewall_result_id,
            execution_intent_id=record.execution_intent_id,
        )

    @staticmethod
    async def _emit_event(event_type: str, record: TakeSignalRecord) -> None:
        """Best-effort event emission for take-signal lifecycle changes."""
        try:
            from infrastructure.stream_publisher import StreamPublisher  # noqa: PLC0415

            publisher = StreamPublisher()
            await publisher.publish(
                stream=TAKE_SIGNAL_EVENTS,
                fields={
                    "event_type": event_type,
                    "take_id": record.take_id,
                    "signal_id": record.signal_id,
                    "account_id": record.account_id,
                    "status": record.status.value,
                    "timestamp": record.updated_at,
                },
            )
        except Exception:
            logger.debug("[TakeSignalService] Event emission failed for {}", event_type)


# ── Exceptions ────────────────────────────────────────────────────────────────


class SignalNotFoundError(Exception):
    """Raised when the referenced signal does not exist."""

    def __init__(self, signal_id: str) -> None:
        self.signal_id = signal_id
        super().__init__(f"Signal not found: {signal_id}")


class SignalExpiredError(Exception):
    """Raised when the referenced signal has expired."""

    def __init__(self, signal_id: str) -> None:
        self.signal_id = signal_id
        super().__init__(f"Signal expired: {signal_id}")
