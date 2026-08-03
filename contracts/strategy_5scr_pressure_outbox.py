"""Durable transport contracts for Strategy 5S-CR pressure events.

The transport is deliberately separate from ``trade_outbox``.  A pressure
event is input to analysis and can never authorize execution.  The durable
record therefore freezes the safety flags that keep the downstream result at
``WAIT`` until a later risk-reservation transaction exists.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.strategy_5scr_pair_admission import (
    PAIR_ADMISSION_MAX_TTL_SECONDS,
    PAIR_ADMISSION_RULE_VERSION,
)

PressureOutboxStatus = Literal["PENDING", "IN_FLIGHT", "PUBLISHED", "DEAD"]
PressureInboxStatus = Literal[
    "RECEIVED",
    "PROCESSING",
    "WAITING_EVIDENCE",
    "PROCESSED",
    "INTEGRITY_VIOLATION",
    "FAILED",
]
PressureProcessingDecision = Literal["DEFER", "READY", "BLOCK"]


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _as_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


def _payload_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


class PressureOutboxEnvelope(FrozenContract):
    """One immutable pressure event as stored and delivered by PostgreSQL."""

    outbox_id: UUID
    event_id: UUID
    event_type: Literal["signal_pressure_state_json"] = "signal_pressure_state_json"
    schema_version: str = Field(..., min_length=1, max_length=100)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    lifecycle_id: str = Field(..., min_length=3, max_length=500)
    lifecycle_sequence: int = Field(..., ge=1)
    source_clean_block_id: str | None = Field(default=None, max_length=500)
    source_watch_id: str | None = Field(default=None, max_length=500)
    signal_valid_at: datetime
    payload: dict[str, Any]
    payload_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    status: PressureOutboxStatus = "PENDING"
    attempt_count: int = Field(default=0, ge=0)
    available_at: datetime | None = None
    locked_at: datetime | None = None
    lease_expires_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime | None = None

    @field_validator(
        "signal_valid_at",
        "available_at",
        "locked_at",
        "lease_expires_at",
        "published_at",
        "created_at",
    )
    @classmethod
    def _times_are_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _as_utc(value, "pressure outbox timestamp")

    @model_validator(mode="after")
    def _live_lineage_and_safety_are_frozen(self) -> PressureOutboxEnvelope:
        if not (self.source_clean_block_id or self.source_watch_id):
            raise ValueError("durable LIVE pressure requires canonical lineage")
        pair_granted_at = _payload_datetime(self.payload.get("pair_admission_granted_at_utc"))
        pair_expires_at = _payload_datetime(self.payload.get("pair_admission_expires_at_utc"))
        if (
            str(self.payload.get("pair_admission_status") or "").upper() != "GRANTED"
            or str(self.payload.get("pair_admission_id") or "") != self.lifecycle_id
            or str(self.payload.get("pair_admission_rule_version") or "") != PAIR_ADMISSION_RULE_VERSION
            or re.fullmatch(r"5scr-admission:[0-9a-f]{32}", self.lifecycle_id) is None
            or re.fullmatch(
                r"sha256:[0-9a-f]{64}",
                str(self.payload.get("pair_admission_source_ledger_hash") or ""),
            )
            is None
            or pair_granted_at is None
            or pair_expires_at is None
            or not (pair_granted_at <= self.signal_valid_at < pair_expires_at)
            or (pair_expires_at - pair_granted_at).total_seconds() > PAIR_ADMISSION_MAX_TTL_SECONDS
        ):
            raise ValueError("durable LIVE pressure requires canonical pair admission")
        if (
            self.payload.get("pressure_selection_confirmed") is not True
            or str(self.payload.get("radar_status") or "").upper() != "ANALYSIS_READY"
            or re.fullmatch(
                r"5scr-radar:[0-9a-f]{32}",
                str(self.payload.get("radar_manifest_id") or ""),
            )
            is None
        ):
            raise ValueError("durable LIVE pressure requires radar selection proof")
        if str(self.payload.get("event") or "").lower() != self.event_type:
            raise ValueError("payload event does not match the outbox event type")
        if str(self.payload.get("event_id") or "") != str(self.event_id):
            raise ValueError("payload event_id does not match the outbox envelope")
        if str(self.payload.get("lifecycle_id") or "") != self.lifecycle_id:
            raise ValueError("payload lifecycle_id does not match the outbox envelope")
        if int(self.payload.get("lifecycle_sequence") or 0) != self.lifecycle_sequence:
            raise ValueError("payload lifecycle_sequence does not match the outbox envelope")
        if any(
            self.payload.get(field) is not False
            for field in ("valid_for_execution", "execution_valid_now", "is_final_signal")
        ):
            raise ValueError("pressure payload execution flags must remain false")
        if str(self.payload.get("final_direction") or "").upper() != "WAIT":
            raise ValueError("pressure payload final_direction must remain WAIT")
        if str(self.payload.get("promotion_stage") or "").upper() != "PRESSURE_ONLY":
            raise ValueError("pressure payload promotion_stage must remain PRESSURE_ONLY")
        return self


class PressureInboxOutcome(FrozenContract):
    """Result of one idempotent delivery into the Strategy 5S-CR inbox."""

    event_id: UUID
    lifecycle_id: str
    status: PressureInboxStatus
    duplicate: bool = False
    decision: PressureProcessingDecision | None = None
    result_id: str | None = None
    reasons: tuple[str, ...] = ()
    candidate_payload: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _candidate_stays_non_executable(self) -> PressureInboxOutcome:
        if self.candidate_payload is not None:
            if self.candidate_payload.get("valid_for_execution") is not False:
                raise ValueError("candidate payload must remain non-executable")
            if self.candidate_payload.get("final_direction") != "WAIT":
                raise ValueError("candidate payload final_direction must remain WAIT")
        return self


__all__ = [
    "PressureInboxOutcome",
    "PressureInboxStatus",
    "PressureOutboxEnvelope",
    "PressureOutboxStatus",
    "PressureProcessingDecision",
]
