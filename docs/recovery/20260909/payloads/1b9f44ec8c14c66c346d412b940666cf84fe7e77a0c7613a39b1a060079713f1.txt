"""Frozen authority packet and process-local issuance capability for D0 DEMO.

This module deliberately has no database, environment, or broker dependency.  It
turns already-approved bytes into one narrowly scoped in-process capability.
Persistence-level exactly-once handling remains the repository's responsibility.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.mt5_execution_protocol import (
    EngineeringDemoCanaryGuards,
    EngineeringDemoCanarySource,
    ExecutionCommandV1,
)

PACKET_SCHEMA: Final = "wolf15.mt5.demo-canary-authority-packet.v1"
PACKET_AUTHORITY: Final = "WOLF15_ENGINEERING_DEMO_OPERATOR_V1"
_COMMAND_CONTENT_FIELDS: Final = (
    "canary_id",
    "command_id",
    "idempotency_key",
    "executor_id",
    "expected_account_snapshot_id",
    "account_reference",
    "broker_server",
    "canonical_symbol",
    "broker_symbol",
    "side",
    "order_type",
    "volume",
    "entry_price",
    "stop_loss",
    "take_profit",
    "issued_at_utc",
    "expires_at_utc",
    "max_spread_points",
    "max_price_drift_points",
    "max_slippage_points",
    "magic_number",
    "order_check_max",
    "order_send_max",
    "child_allowed",
    "automatic_retry",
    "max_commands",
)


def _json_scalar(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, UUID):
        return str(value)
    return value


def command_content_sha256_from_fields(values: Mapping[str, object]) -> str:
    """Hash all operator-controlled command fields, independent of packet metadata."""

    missing = [field for field in _COMMAND_CONTENT_FIELDS if field not in values]
    if missing:
        raise AuthorityPacketError(f"command content fields are missing: {','.join(missing)}")
    content = {field: _json_scalar(values[field]) for field in _COMMAND_CONTENT_FIELDS}
    raw = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def emitted_command_content_sha256(command: ExecutionCommandV1) -> str:
    """Reconstruct the operator-controlled content from the signed command."""

    source = command.source
    guards = command.guards
    order = command.order
    if (
        not isinstance(source, EngineeringDemoCanarySource)
        or not isinstance(guards, EngineeringDemoCanaryGuards)
        or order is None
    ):
        raise AuthorityPacketError("command is not an engineering DEMO canary")
    return command_content_sha256_from_fields(
        {
            "canary_id": source.canary_id,
            "command_id": command.command_id,
            "idempotency_key": command.idempotency_key,
            "executor_id": command.executor_binding.executor_id,
            "expected_account_snapshot_id": guards.account_snapshot_id,
            "account_reference": command.executor_binding.account_id,
            "broker_server": command.executor_binding.broker_server,
            "canonical_symbol": order.canonical_symbol,
            "broker_symbol": order.broker_symbol,
            "side": order.side,
            "order_type": order.order_type,
            "volume": Decimal(str(order.volume)),
            "entry_price": Decimal(str(order.entry_price)),
            "stop_loss": Decimal(str(order.stop_loss)),
            "take_profit": Decimal(str(order.take_profit)),
            "issued_at_utc": command.issued_at_utc,
            "expires_at_utc": command.expires_at_utc,
            "max_spread_points": guards.max_spread_points,
            "max_price_drift_points": guards.max_price_drift_points,
            "max_slippage_points": guards.max_price_drift_points,
            "magic_number": order.magic,
            "order_check_max": 2,
            "order_send_max": guards.max_submit_attempts,
            "child_allowed": False,
            "automatic_retry": False,
            "max_commands": 1,
        }
    )


class AuthorityPacketError(RuntimeError):
    """The supplied authority bytes are invalid, stale, or not exact."""


class ProcessLocalIssuanceError(RuntimeError):
    """The process-local one-command capability was used outside its scope."""


class DemoCanaryAuthorityPacketV1(BaseModel):
    """Complete immutable operator approval for exactly one DEMO parent order."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["wolf15.mt5.demo-canary-authority-packet.v1"] = PACKET_SCHEMA
    authority_packet_id: str = Field(min_length=3, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]+$")
    canary_id: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]+$")
    operator_authority: Literal["WOLF15_ENGINEERING_DEMO_OPERATOR_V1"] = PACKET_AUTHORITY
    approved_by: str = Field(min_length=1, max_length=160)
    approved_at_utc: datetime

    command_id: UUID
    command_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=3, max_length=240)

    executor_id: UUID
    expected_account_snapshot_id: str = Field(min_length=3, max_length=200)
    account_reference: str = Field(min_length=1, max_length=100)
    broker_server: str = Field(min_length=1, max_length=200)
    canonical_symbol: str = Field(min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    broker_symbol: str = Field(min_length=1, max_length=64)

    side: Literal["BUY", "SELL"]
    order_type: Literal["BUY", "SELL"]
    volume: Decimal = Field(gt=0)
    entry_price: Decimal = Field(gt=0)
    stop_loss: Decimal = Field(gt=0)
    take_profit: Decimal = Field(gt=0)
    issued_at_utc: datetime
    expires_at_utc: datetime
    max_spread_points: int = Field(ge=0, le=100_000)
    max_price_drift_points: int = Field(ge=0, le=100_000)
    max_slippage_points: int = Field(ge=0, le=100_000)
    magic_number: Literal[150016] = 150016

    order_check_max: Literal[2] = 2
    order_send_max: Literal[1] = 1
    child_allowed: Literal[False] = False
    automatic_retry: Literal[False] = False
    max_commands: Literal[1] = 1
    issuer_source_revision: str = Field(min_length=7, max_length=64, pattern=r"^[0-9a-f]+$")

    @field_validator("approved_at_utc", "issued_at_utc", "expires_at_utc")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("authority packet timestamps must be timezone-aware")
        offset = value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("authority packet timestamps must use UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_scope(self) -> DemoCanaryAuthorityPacketV1:
        if self.side != self.order_type:
            raise ValueError("side and order_type must match")
        if self.max_slippage_points != self.max_price_drift_points:
            raise ValueError("current DEMO wire requires max_slippage_points to equal max_price_drift_points")
        if self.approved_at_utc > self.issued_at_utc:
            raise ValueError("approval must not postdate issuance")
        if self.expires_at_utc <= self.issued_at_utc:
            raise ValueError("expiry must follow issuance")
        if self.side == "BUY" and not self.stop_loss < self.entry_price < self.take_profit:
            raise ValueError("BUY requires stop_loss < entry_price < take_profit")
        if self.side == "SELL" and not self.take_profit < self.entry_price < self.stop_loss:
            raise ValueError("SELL requires take_profit < entry_price < stop_loss")
        expected_content = command_content_sha256_from_fields(self.model_dump())
        if not secrets.compare_digest(self.command_content_sha256, expected_content):
            raise ValueError("command_content_sha256 does not bind the command fields")
        return self


def canonical_packet_bytes(packet: DemoCanaryAuthorityPacketV1) -> bytes:
    """Return the only byte representation accepted for packet hashing."""

    payload = packet.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def packet_sha256(packet: DemoCanaryAuthorityPacketV1) -> str:
    return hashlib.sha256(canonical_packet_bytes(packet)).hexdigest()


def validate_authority_packet(
    packet: DemoCanaryAuthorityPacketV1,
    *,
    expected_sha256: str,
    now: datetime,
) -> str:
    """Fail closed unless identity, digest, and time window are exact."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise AuthorityPacketError("validation clock must be timezone-aware")
    expected = expected_sha256.removeprefix("sha256:")
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise AuthorityPacketError("expected packet digest is not canonical lowercase SHA-256")
    actual = packet_sha256(packet)
    if not secrets.compare_digest(actual, expected):
        raise AuthorityPacketError("authority packet digest mismatch")
    current = now.astimezone(UTC)
    if current < packet.issued_at_utc or current >= packet.expires_at_utc:
        raise AuthorityPacketError("authority packet is not currently active")
    return actual


class IssuanceDisposition(StrEnum):
    CREATED = "CREATED"
    ALREADY_ISSUED = "ALREADY_ISSUED"


class ProcessLocalIssuanceCapability:
    """One-process, one-packet, maximum-one-command issuance authority."""

    def __init__(self, *, packet_sha256_value: str, command_id: UUID, max_commands: Literal[1] = 1) -> None:
        self._packet_sha256 = packet_sha256_value.removeprefix("sha256:")
        self._command_id = command_id
        self._max_commands = max_commands
        self._consumed = False

    @property
    def consumed(self) -> bool:
        return self._consumed

    def mark_consumed(self, packet: DemoCanaryAuthorityPacketV1, *, packet_sha256_value: str) -> None:
        """Close the capability after the durable repository transaction succeeds."""

        if packet_sha256_value.removeprefix("sha256:") != self._packet_sha256 or packet.command_id != self._command_id:
            raise ProcessLocalIssuanceError("cannot consume capability for a different packet")
        self._consumed = True

    def issue_once(
        self,
        packet: DemoCanaryAuthorityPacketV1,
        *,
        expected_sha256: str,
        now: datetime,
        issuer: Callable[[DemoCanaryAuthorityPacketV1], IssuanceDisposition],
    ) -> IssuanceDisposition:
        actual = validate_authority_packet(packet, expected_sha256=expected_sha256, now=now)
        if (
            actual != self._packet_sha256
            or packet.command_id != self._command_id
            or packet.max_commands != self._max_commands
        ):
            raise ProcessLocalIssuanceError("packet is outside the process-local issuance capability")
        if self._consumed:
            return IssuanceDisposition.ALREADY_ISSUED
        result = issuer(packet)
        if result not in (IssuanceDisposition.CREATED, IssuanceDisposition.ALREADY_ISSUED):
            raise ProcessLocalIssuanceError("issuer returned an unsupported disposition")
        self._consumed = True
        return result


def load_and_validate_authority_packet(
    raw_json: bytes,
    *,
    expected_sha256: str,
    now: datetime,
) -> DemoCanaryAuthorityPacketV1:
    """Parse strict packet JSON and verify its canonical digest and validity."""

    try:
        packet = DemoCanaryAuthorityPacketV1.model_validate_json(raw_json)
    except ValueError as exc:
        raise AuthorityPacketError("authority packet schema validation failed") from exc
    validate_authority_packet(packet, expected_sha256=expected_sha256, now=now)
    return packet


__all__ = [
    "AuthorityPacketError",
    "DemoCanaryAuthorityPacketV1",
    "IssuanceDisposition",
    "PACKET_AUTHORITY",
    "PACKET_SCHEMA",
    "ProcessLocalIssuanceCapability",
    "ProcessLocalIssuanceError",
    "canonical_packet_bytes",
    "command_content_sha256_from_fields",
    "emitted_command_content_sha256",
    "load_and_validate_authority_packet",
    "packet_sha256",
    "validate_authority_packet",
]
