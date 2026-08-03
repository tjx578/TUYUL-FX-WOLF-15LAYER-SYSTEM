"""Strict Wolf15 <-> MT5 dumb-executor protocol.

This contract is intentionally broker-facing and contains no market analysis.
Only a fully authorized final signal may be promoted into an execution command.
The EA may reject a command mechanically, but it must never reinterpret it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROTOCOL_VERSION: Final = "wolf15.mt5.exec.v1"
SIGNED_WIRE_VERSION: Final = "wolf15.mt5.exec.signed-bytes.v2"
SHADOW_ACCEPTANCE_SCHEMA_VERSION: Final = "wolf15.mt5.shadow-acceptance.v1"
SHADOW_ACCEPTANCE_OPERATOR_AUTHORITY: Final = "WOLF15_SHADOW_ACCEPTANCE_OPERATOR_V1"
SHADOW_ACCEPTANCE_PURPOSE: Final = "BROKER_CONNECTED_SHADOW_VALIDATION"
SHADOW_ACCEPTANCE_EA_VERSION: Final = "0.22-shadow-acceptance-v1"
SIGNED_WIRE_PAYLOAD_ENCODING: Final = "base64url"
SIGNED_WIRE_ALGORITHM: Final = "HMAC-SHA256"
_SIGNED_WIRE_DOMAIN: Final = "WOLF15-MT5-COMMAND-V2"
_EXECUTOR_KEY_CONTEXT: Final = "wolf15-command-verify-v2"


class ExecutionAction(StrEnum):
    PLACE_MARKET = "PLACE_MARKET"
    PLACE_PENDING = "PLACE_PENDING"
    CANCEL_PENDING = "CANCEL_PENDING"
    MODIFY_PROTECTION = "MODIFY_PROTECTION"
    CLOSE_FULL = "CLOSE_FULL"
    RECONCILE_ONLY = "RECONCILE_ONLY"


class ExecutionReportState(StrEnum):
    RECEIVED = "RECEIVED"
    CLAIMED = "CLAIMED"
    VALIDATION_REJECTED = "VALIDATION_REJECTED"
    PREFLIGHT_REJECTED = "PREFLIGHT_REJECTED"
    SUBMITTING = "SUBMITTING"
    BROKER_ACCEPTED = "BROKER_ACCEPTED"
    PENDING_ACTIVE = "PENDING_ACTIVE"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    MODIFIED = "MODIFIED"
    CLOSED_TP = "CLOSED_TP"
    CLOSED_SL = "CLOSED_SL"
    CLOSED_COMMAND = "CLOSED_COMMAND"
    EXPIRED = "EXPIRED"
    BROKER_REJECTED = "BROKER_REJECTED"
    AMBIGUOUS_REQUIRES_RECONCILIATION = "AMBIGUOUS_REQUIRES_RECONCILIATION"
    WOULD_EXECUTE = "WOULD_EXECUTE"
    WOULD_REJECT = "WOULD_REJECT"


class MarginMode(StrEnum):
    HEDGING = "HEDGING"
    NETTING = "NETTING"


class ExecutorMode(StrEnum):
    SHADOW = "SHADOW"
    DEMO = "DEMO"
    LIVE = "LIVE"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _require_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


class ExecutorBinding(StrictModel):
    executor_id: UUID
    account_id: str = Field(..., min_length=1, max_length=100)
    login_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    broker_server: str = Field(..., min_length=1, max_length=200)
    execution_mode: ExecutorMode = ExecutorMode.SHADOW


class CommandSource(StrictModel):
    source_event: Literal["signal_json"]
    source_schema_version: str = Field(..., min_length=1, max_length=100)
    source_signal_id: str = Field(..., min_length=3, max_length=200)
    source_signal_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    campaign_id: str = Field(..., min_length=3, max_length=200)
    block_id: str = Field(..., min_length=3, max_length=200)
    block_role: Literal["PARENT", "CHILD", "REVERSAL"]
    lifecycle_anchor: str = Field(..., min_length=3, max_length=200)
    valid_for_execution: Literal[True]
    execution_gate_passed: Literal[True]
    tradeplan_valid: Literal[True]
    strategy_model: Literal["STRATEGY_5S_CR_FINAL"]
    strategy_rule_version: Literal["5scr.final.2026-07-19"]
    strategy_rule_status: Literal["FROZEN"]
    strategy_proof_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    context_resolution_status: Literal["RESOLVED"]
    confirmation_policy: Literal["H1_CLOSED_PLUS_M15_BREAK_ACCEPTANCE_OR_FAILED_RECLAIM_RETEST"]


class ShadowAcceptanceSource(StrictModel):
    """Non-production lineage for broker-connected SHADOW acceptance only."""

    source_event: Literal["SHADOW_ACCEPTANCE"] = "SHADOW_ACCEPTANCE"
    source_schema_version: Literal["wolf15.mt5.shadow-acceptance.v1"] = SHADOW_ACCEPTANCE_SCHEMA_VERSION
    acceptance_run_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]+$")
    operator_authority: Literal["WOLF15_SHADOW_ACCEPTANCE_OPERATOR_V1"] = SHADOW_ACCEPTANCE_OPERATOR_AUTHORITY
    purpose: Literal["BROKER_CONNECTED_SHADOW_VALIDATION"] = SHADOW_ACCEPTANCE_PURPOSE
    phase: Literal["A1", "A2"]
    canonical_symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    execution_authority: Literal[False] = False
    broker_execution: Literal["FORBIDDEN"] = "FORBIDDEN"


class OrderInstruction(StrictModel):
    canonical_symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    side: Literal["BUY", "SELL"]
    order_type: Literal["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"]
    volume: float = Field(..., gt=0, le=1000)
    entry_price: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profit: float = Field(..., gt=0)
    magic: int = Field(..., ge=1, le=2_147_483_647)
    comment_tag: str = Field(..., min_length=3, max_length=31)
    time_in_force: Literal["GTC", "SPECIFIED"]
    broker_expiration_utc: datetime | None = None
    broker_order_ticket: int | None = Field(default=None, ge=1)
    broker_position_id: int | None = Field(default=None, ge=1)

    @field_validator("broker_expiration_utc")
    @classmethod
    def _expiration_is_utc(cls, value: datetime | None) -> datetime | None:
        return _require_utc(value, "broker_expiration_utc") if value is not None else None

    @model_validator(mode="after")
    def _validate_prices_and_type(self) -> OrderInstruction:
        if self.side == "BUY":
            if not self.stop_loss < self.entry_price < self.take_profit:
                raise ValueError("BUY requires stop_loss < entry_price < take_profit")
            if not self.order_type.startswith("BUY"):
                raise ValueError("BUY side requires a BUY order_type")
        else:
            if not self.take_profit < self.entry_price < self.stop_loss:
                raise ValueError("SELL requires take_profit < entry_price < stop_loss")
            if not self.order_type.startswith("SELL"):
                raise ValueError("SELL side requires a SELL order_type")
        if self.time_in_force == "SPECIFIED" and self.broker_expiration_utc is None:
            raise ValueError("SPECIFIED time_in_force requires broker_expiration_utc")
        return self


class CommandGuards(StrictModel):
    require_attached_sl: Literal[True] = True
    require_attached_tp: Literal[True] = True
    max_spread_points: int = Field(..., ge=0, le=100_000)
    max_price_drift_points: int = Field(..., ge=0, le=100_000)
    expected_margin_mode: MarginMode
    max_submit_attempts: Literal[1] = 1
    allow_volume_round_down: Literal[False] = False
    allow_price_normalization: Literal[False] = False
    risk_snapshot_id: str = Field(..., min_length=3, max_length=200)
    risk_reservation_id: str = Field(..., min_length=3, max_length=200)
    balance_snapshot: float = Field(..., gt=0)
    equity_snapshot: float = Field(..., gt=0)
    max_balance_drift_pct: float = Field(default=0.1, ge=0, le=5)
    max_equity_drift_pct: float = Field(default=1.0, ge=0, le=10)


class ShadowAcceptanceGuards(StrictModel):
    """Mechanical SHADOW guards with deliberately no risk reservation."""

    guard_type: Literal["SHADOW_ACCEPTANCE"] = "SHADOW_ACCEPTANCE"
    kill_switch_required: Literal[True] = True
    expected_margin_mode: MarginMode
    account_snapshot_id: str = Field(..., min_length=3, max_length=200)
    balance_snapshot: float = Field(..., gt=0)
    equity_snapshot: float = Field(..., gt=0)
    broker_execution: Literal["FORBIDDEN"] = "FORBIDDEN"


class CommandSignature(StrictModel):
    algorithm: Literal["HMAC-SHA256"] = "HMAC-SHA256"
    key_id: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., pattern=r"^base64:[A-Za-z0-9_-]{43}=$")


class ExecutionCommandV1(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["execution_command"] = "execution_command"
    protocol_version: Literal["wolf15.mt5.exec.v1"] = PROTOCOL_VERSION
    command_id: UUID
    idempotency_key: str = Field(..., min_length=8, max_length=250)
    revision: int = Field(default=1, ge=1)
    issued_at_utc: datetime
    not_before_utc: datetime
    expires_at_utc: datetime
    executor_binding: ExecutorBinding
    source: CommandSource | ShadowAcceptanceSource
    action: ExecutionAction
    order: OrderInstruction | None
    guards: CommandGuards | ShadowAcceptanceGuards
    signature: CommandSignature

    @field_validator("issued_at_utc", "not_before_utc", "expires_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _require_utc(value, info.field_name)

    @model_validator(mode="after")
    def _validate_command_shape(self) -> ExecutionCommandV1:
        if self.expires_at_utc <= self.issued_at_utc:
            raise ValueError("expires_at_utc must be after issued_at_utc")
        if self.not_before_utc < self.issued_at_utc or self.not_before_utc >= self.expires_at_utc:
            raise ValueError("not_before_utc must be within the command validity window")
        if self.action == ExecutionAction.RECONCILE_ONLY:
            if self.order is not None:
                raise ValueError("RECONCILE_ONLY must not carry an order")
        elif self.order is None:
            raise ValueError(f"{self.action} requires an order")
        if (
            self.action == ExecutionAction.PLACE_MARKET
            and self.order is not None
            and self.order.order_type not in {"BUY", "SELL"}
        ):
            raise ValueError("PLACE_MARKET requires BUY or SELL order_type")
        if (
            self.action == ExecutionAction.PLACE_PENDING
            and self.order is not None
            and self.order.order_type not in {"BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}
        ):
            raise ValueError("PLACE_PENDING requires a pending order_type")
        if isinstance(self.source, ShadowAcceptanceSource):
            if self.executor_binding.execution_mode is not ExecutorMode.SHADOW:
                raise ValueError("SHADOW_ACCEPTANCE requires SHADOW execution mode")
            if self.action is not ExecutionAction.RECONCILE_ONLY or self.order is not None:
                raise ValueError("SHADOW_ACCEPTANCE requires RECONCILE_ONLY without an order")
            if not isinstance(self.guards, ShadowAcceptanceGuards):
                raise ValueError("SHADOW_ACCEPTANCE requires dedicated acceptance guards")
        elif not isinstance(self.guards, CommandGuards):
            raise ValueError("signal_json requires production command guards")
        return self

    def is_active(self, *, now: datetime | None = None) -> bool:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        return self.not_before_utc <= current < self.expires_at_utc


class SignedExecutionEnvelopeV2(StrictModel):
    """Immutable wire bytes signed without reserializing JSON in the EA."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    wire_version: Literal["wolf15.mt5.exec.signed-bytes.v2"] = SIGNED_WIRE_VERSION
    payload_encoding: Literal["base64url"] = SIGNED_WIRE_PAYLOAD_ENCODING
    payload_b64: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    payload_sha256: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    algorithm: Literal["HMAC-SHA256"] = SIGNED_WIRE_ALGORITHM
    key_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._:-]+$")
    executor_id: UUID
    signature: str = Field(..., pattern=r"^base64url:[A-Za-z0-9_-]{43}$")


class BrokerReport(StrictModel):
    order_ticket: int | None = Field(default=None, ge=1)
    deal_ticket: int | None = Field(default=None, ge=1)
    position_id: int | None = Field(default=None, ge=1)
    retcode: int | None = None
    retcode_external: int | None = None
    comment: str | None = Field(default=None, max_length=250)


class ExecutionReportDetail(StrictModel):
    requested_volume: float | None = Field(default=None, gt=0)
    filled_volume: float | None = Field(default=None, ge=0)
    requested_price: float | None = Field(default=None, gt=0)
    filled_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    observed_spread_points: int | None = Field(default=None, ge=0)


class ExecutionReportV1(StrictModel):
    event: Literal["execution_report"] = "execution_report"
    protocol_version: Literal["wolf15.mt5.exec.v1"] = PROTOCOL_VERSION
    report_id: UUID
    command_id: UUID
    idempotency_key: str = Field(..., min_length=8, max_length=250)
    sequence: int = Field(..., ge=1)
    state: ExecutionReportState
    event_time_utc: datetime
    executor_id: UUID
    account_id: str = Field(..., min_length=1, max_length=100)
    request_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    broker: BrokerReport = Field(default_factory=BrokerReport)
    execution: ExecutionReportDetail = Field(default_factory=ExecutionReportDetail)
    reason_code: str = Field(..., min_length=3, max_length=120, pattern=r"^[A-Z0-9_]+$")
    reason_detail: str | None = Field(default=None, max_length=500)

    @field_validator("event_time_utc")
    @classmethod
    def _event_time_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "event_time_utc")


class SymbolCapability(StrictModel):
    canonical_symbol: str = Field(..., min_length=3, max_length=32)
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    digits: int = Field(..., ge=0, le=12)
    point: float = Field(..., gt=0)
    tick_size: float = Field(..., gt=0)
    tick_value_profit: float = Field(..., ge=0)
    tick_value_loss: float = Field(..., gt=0)
    volume_min: float = Field(..., gt=0)
    volume_max: float = Field(..., gt=0)
    volume_step: float = Field(..., gt=0)
    stops_level_points: int = Field(..., ge=0)
    freeze_level_points: int = Field(..., ge=0)
    expiration_modes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_ranges(self) -> SymbolCapability:
        if self.volume_max < self.volume_min:
            raise ValueError("volume_max must be >= volume_min")
        return self


class OpenBrokerPosition(StrictModel):
    position_id: int = Field(..., ge=1)
    symbol: str = Field(..., min_length=1, max_length=64)
    side: Literal["BUY", "SELL"]
    volume: float = Field(..., gt=0)
    entry_price: float = Field(..., gt=0)
    current_price: float = Field(..., gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    magic: int = Field(..., ge=0)
    comment: str = Field(default="", max_length=64)
    floating_pnl: float


class AccountSnapshotV1(StrictModel):
    snapshot_id: str = Field(..., min_length=3, max_length=200)
    captured_at_utc: datetime
    executor_id: UUID
    account_id: str = Field(..., min_length=1, max_length=100)
    currency: str = Field(..., min_length=3, max_length=8)
    balance: float = Field(..., gt=0)
    equity: float = Field(..., gt=0)
    floating_pnl: float
    used_margin: float = Field(..., ge=0)
    free_margin: float = Field(..., ge=0)
    margin_level_pct: float | None = Field(default=None, ge=0)
    margin_mode: MarginMode
    trade_allowed: bool
    autotrading_enabled: bool
    open_positions: list[OpenBrokerPosition] = Field(default_factory=list)
    symbols: list[SymbolCapability] = Field(default_factory=list)

    @field_validator("captured_at_utc")
    @classmethod
    def _captured_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "captured_at_utc")


class ExecutorRegistrationV1(StrictModel):
    protocol_version: Literal["wolf15.mt5.exec.v1"] = PROTOCOL_VERSION
    executor_id: UUID
    account_id: str = Field(..., min_length=1, max_length=100)
    login_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    broker_server: str = Field(..., min_length=1, max_length=200)
    terminal_build: int = Field(..., ge=1)
    ea_version: str = Field(..., min_length=1, max_length=50)
    requested_mode: ExecutorMode = ExecutorMode.SHADOW


class ExecutorHeartbeatV1(StrictModel):
    protocol_version: Literal["wolf15.mt5.exec.v1"] = PROTOCOL_VERSION
    executor_id: UUID
    sent_at_utc: datetime
    terminal_connected: bool
    trade_allowed: bool
    autotrading_enabled: bool
    account_snapshot: AccountSnapshotV1

    @field_validator("sent_at_utc")
    @classmethod
    def _sent_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "sent_at_utc")

    @model_validator(mode="after")
    def _binding_matches(self) -> ExecutorHeartbeatV1:
        if self.account_snapshot.executor_id != self.executor_id:
            raise ValueError("account_snapshot.executor_id must match executor_id")
        return self


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def sha256_bytes_tag(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def sha256_tag(payload: dict[str, Any]) -> str:
    return sha256_bytes_tag(canonical_json_bytes(payload))


def _require_secret_bytes(secret: str | bytes, *, name: str) -> bytes:
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    if len(key) < 32:
        raise ValueError(f"{name} must be at least 32 bytes")
    return key


def _base64url_no_padding(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_base64url_no_padding(payload: str) -> bytes:
    padding = "=" * (-len(payload) % 4)
    return base64.b64decode(payload + padding, altchars=b"-_", validate=True)


def derive_executor_command_verification_key(
    executor_id: UUID | str,
    *,
    root_secret: str | bytes,
) -> bytes:
    """Derive one command-verification key scoped to a single executor."""

    key = _require_secret_bytes(root_secret, name="command signing root secret")
    canonical_executor_id = str(UUID(str(executor_id)))
    context = f"{_EXECUTOR_KEY_CONTEXT}:{canonical_executor_id}".encode("ascii")
    return hmac.new(key, context, hashlib.sha256).digest()


def signed_execution_envelope_preimage(
    *,
    key_id: str,
    executor_id: UUID | str,
    payload_sha256: str,
    payload_b64: str,
) -> bytes:
    """Return the exact ASCII preimage consumed by Python and MQL5."""

    if (
        not key_id
        or len(key_id) > 100
        or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-" for ch in key_id)
    ):
        raise ValueError("key_id contains unsupported wire characters")
    canonical_executor_id = str(UUID(str(executor_id)))
    if (
        len(payload_sha256) != 71
        or not payload_sha256.startswith("sha256:")
        or any(ch not in "0123456789abcdef" for ch in payload_sha256[7:])
    ):
        raise ValueError("payload_sha256 is malformed")
    if not payload_b64 or any(
        ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for ch in payload_b64
    ):
        raise ValueError("payload_b64 is malformed")
    return "\n".join(
        (
            _SIGNED_WIRE_DOMAIN,
            f"key_id={key_id}",
            f"executor_id={canonical_executor_id}",
            f"payload_sha256={payload_sha256}",
            f"payload_b64={payload_b64}",
        )
    ).encode("ascii")


def build_signed_execution_envelope(
    command: ExecutionCommandV1,
    *,
    root_secret: str | bytes,
    key_id: str,
) -> SignedExecutionEnvelopeV2:
    """Freeze canonical command bytes and sign their versioned wire envelope."""

    payload_bytes = canonical_json_bytes(command.model_dump(mode="json"))
    payload_b64 = _base64url_no_padding(payload_bytes)
    payload_sha256 = sha256_bytes_tag(payload_bytes)
    executor_id = command.executor_binding.executor_id
    verification_key = derive_executor_command_verification_key(executor_id, root_secret=root_secret)
    preimage = signed_execution_envelope_preimage(
        key_id=key_id,
        executor_id=executor_id,
        payload_sha256=payload_sha256,
        payload_b64=payload_b64,
    )
    signature = "base64url:" + _base64url_no_padding(hmac.new(verification_key, preimage, hashlib.sha256).digest())
    return SignedExecutionEnvelopeV2(
        payload_b64=payload_b64,
        payload_sha256=payload_sha256,
        key_id=key_id,
        executor_id=executor_id,
        signature=signature,
    )


def verify_signed_execution_envelope(
    envelope: SignedExecutionEnvelopeV2,
    *,
    verification_key: bytes,
) -> ExecutionCommandV1 | None:
    """Verify exact wire bytes and return the bound command, or fail closed."""

    if len(verification_key) != hashlib.sha256().digest_size:
        raise ValueError("executor command verification key must be exactly 32 bytes")
    try:
        preimage = signed_execution_envelope_preimage(
            key_id=envelope.key_id,
            executor_id=envelope.executor_id,
            payload_sha256=envelope.payload_sha256,
            payload_b64=envelope.payload_b64,
        )
        expected_signature = "base64url:" + _base64url_no_padding(
            hmac.new(verification_key, preimage, hashlib.sha256).digest()
        )
        if not hmac.compare_digest(expected_signature, envelope.signature):
            return None
        payload_bytes = _decode_base64url_no_padding(envelope.payload_b64)
        if not hmac.compare_digest(sha256_bytes_tag(payload_bytes), envelope.payload_sha256):
            return None
        raw_payload = json.loads(payload_bytes.decode("ascii"))
        if not isinstance(raw_payload, dict):
            return None
        if canonical_json_bytes(raw_payload) != payload_bytes:
            return None
        command = ExecutionCommandV1.model_validate(raw_payload)
        if command.executor_binding.executor_id != envelope.executor_id:
            return None
        return command
    except (ValueError, binascii.Error):
        return None


def verify_signed_execution_envelope_with_root(
    envelope: SignedExecutionEnvelopeV2,
    *,
    root_secret: str | bytes,
) -> ExecutionCommandV1 | None:
    verification_key = derive_executor_command_verification_key(
        envelope.executor_id,
        root_secret=root_secret,
    )
    return verify_signed_execution_envelope(envelope, verification_key=verification_key)


def _signature_value(payload: dict[str, Any], secret: str | bytes) -> str:
    key = _require_secret_bytes(secret, name="command signing secret")
    digest = hmac.new(key, canonical_json_bytes(payload), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"base64:{encoded}"


def sign_execution_command(
    payload: dict[str, Any],
    *,
    secret: str | bytes,
    key_id: str,
) -> ExecutionCommandV1:
    if "signature" in payload:
        raise ValueError("unsigned payload must not include signature")
    placeholder = CommandSignature(key_id=key_id, value="base64:" + ("A" * 43) + "=")
    command = ExecutionCommandV1.model_validate({**payload, "signature": placeholder.model_dump()})
    unsigned = command.model_dump(mode="json", exclude={"signature"})
    signature = CommandSignature(key_id=key_id, value=_signature_value(unsigned, secret))
    return cast(ExecutionCommandV1, command.model_copy(update={"signature": signature}))


def verify_execution_command(command: ExecutionCommandV1, *, secret: str | bytes) -> bool:
    unsigned = command.model_dump(mode="json", exclude={"signature"})
    expected = _signature_value(unsigned, secret)
    return hmac.compare_digest(expected, command.signature.value)


__all__ = [
    "PROTOCOL_VERSION",
    "SIGNED_WIRE_VERSION",
    "SHADOW_ACCEPTANCE_SCHEMA_VERSION",
    "SHADOW_ACCEPTANCE_OPERATOR_AUTHORITY",
    "SHADOW_ACCEPTANCE_PURPOSE",
    "SHADOW_ACCEPTANCE_EA_VERSION",
    "ExecutionAction",
    "ExecutionReportState",
    "MarginMode",
    "ExecutorMode",
    "ExecutorBinding",
    "CommandSource",
    "ShadowAcceptanceSource",
    "OrderInstruction",
    "CommandGuards",
    "ShadowAcceptanceGuards",
    "CommandSignature",
    "ExecutionCommandV1",
    "SignedExecutionEnvelopeV2",
    "BrokerReport",
    "ExecutionReportDetail",
    "ExecutionReportV1",
    "SymbolCapability",
    "OpenBrokerPosition",
    "AccountSnapshotV1",
    "ExecutorRegistrationV1",
    "ExecutorHeartbeatV1",
    "canonical_json_bytes",
    "sha256_bytes_tag",
    "sha256_tag",
    "derive_executor_command_verification_key",
    "signed_execution_envelope_preimage",
    "build_signed_execution_envelope",
    "verify_signed_execution_envelope",
    "verify_signed_execution_envelope_with_root",
    "sign_execution_command",
    "verify_execution_command",
]
