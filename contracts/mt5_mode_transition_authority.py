"""Immutable operator authority for one governed MT5 executor mode transition.

This module is deliberately persistence-independent.  A repository may consume
the packet exactly once, but neither an EA registration nor a heartbeat can
construct or consume this authority on the executor's behalf.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.mt5_execution_protocol import ExecutorMode

MODE_TRANSITION_AUTHORITY_SCHEMA: Final = "wolf15.mt5.mode-transition-authority.v1"
SHA256_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"


class ModeTransitionAuthorityError(ValueError):
    """Raised when a packet cannot authorize a one-use transition."""


class ModeTransitionAuthorityPacket(BaseModel):
    """Canonical, immutable authority for SHADOW<->DEMO only.

    ``authority_packet_sha256`` authenticates every other field.  The digest is
    intentionally excluded from its own canonical payload.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["wolf15.mt5.mode-transition-authority.v1"] = MODE_TRANSITION_AUTHORITY_SCHEMA
    authority_packet_id: UUID
    authority_packet_sha256: str = Field(pattern=SHA256_PATTERN)
    approval_id: str = Field(min_length=1, max_length=200)
    approved_by: str = Field(min_length=1, max_length=200)
    approved_at_utc: datetime
    expires_at_utc: datetime

    executor_id: UUID
    account_reference: str = Field(min_length=1, max_length=200)
    broker_server: str = Field(min_length=1, max_length=200)
    configuration_sha256: str = Field(pattern=SHA256_PATTERN)
    final_shadow_receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    previous_mode: ExecutorMode
    new_mode: ExecutorMode
    consumption_limit: Literal[1] = 1

    @model_validator(mode="after")
    def validate_transition_and_digest(self) -> ModeTransitionAuthorityPacket:
        approved = _utc(self.approved_at_utc, "approved_at_utc")
        expires = _utc(self.expires_at_utc, "expires_at_utc")
        if expires <= approved:
            raise ValueError("expires_at_utc must be later than approved_at_utc")
        allowed = {
            (ExecutorMode.SHADOW, ExecutorMode.DEMO),
            (ExecutorMode.DEMO, ExecutorMode.SHADOW),
        }
        if (self.previous_mode, self.new_mode) not in allowed:
            raise ValueError("only SHADOW->DEMO and DEMO->SHADOW transitions are authorized")
        expected = self.canonical_sha256()
        if self.authority_packet_sha256 != expected:
            raise ValueError("authority_packet_sha256 does not match canonical packet bytes")
        return self

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"authority_packet_sha256"})

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def canonical_sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"

    def assert_one_use_ready(self, *, now_utc: datetime, prior_consumptions: int) -> None:
        """Fail closed unless this exact authority can be consumed once now."""

        now = _utc(now_utc, "now_utc")
        if prior_consumptions < 0:
            raise ModeTransitionAuthorityError("prior_consumptions must not be negative")
        if prior_consumptions != 0:
            raise ModeTransitionAuthorityError("mode transition authority was already consumed")
        if now < _utc(self.approved_at_utc, "approved_at_utc"):
            raise ModeTransitionAuthorityError("mode transition authority is not active yet")
        if now >= _utc(self.expires_at_utc, "expires_at_utc"):
            raise ModeTransitionAuthorityError("mode transition authority is expired")


def canonical_mode_transition_authority_sha256(fields: dict[str, object]) -> str:
    """Compute the digest used when materializing a packet for validation."""

    payload = dict(fields)
    payload.pop("authority_packet_sha256", None)
    payload.setdefault("schema_version", MODE_TRANSITION_AUTHORITY_SCHEMA)
    for field_name in ("approved_at_utc", "expires_at_utc"):
        value = payload.get(field_name)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            payload[field_name] = _utc(parsed, field_name).isoformat().replace("+00:00", "Z")
        elif isinstance(value, datetime):
            payload[field_name] = _utc(value, field_name).isoformat().replace("+00:00", "Z")
    for field_name in ("authority_packet_id", "executor_id"):
        value = payload.get(field_name)
        if isinstance(value, UUID):
            payload[field_name] = str(value)
    for field_name in ("previous_mode", "new_mode"):
        value = payload.get(field_name)
        if isinstance(value, ExecutorMode):
            payload[field_name] = value.value
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


__all__ = [
    "MODE_TRANSITION_AUTHORITY_SCHEMA",
    "ModeTransitionAuthorityError",
    "ModeTransitionAuthorityPacket",
    "canonical_mode_transition_authority_sha256",
]
