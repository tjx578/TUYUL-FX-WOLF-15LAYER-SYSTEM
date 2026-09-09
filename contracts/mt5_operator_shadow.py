"""Credential-free contracts for one operator-controlled C3 SHADOW command."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

C3_OPERATOR_SHADOW_MANIFEST_VERSION: Final = "wolf15.mt5.operator-shadow-manifest.v1"
C3_OPERATOR_AUTHORITY: Final = "WOLF15_C3_OPERATOR_SHADOW_V1"
C3_MAX_REQUEST_TTL_SECONDS: Final = 300


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


class OperatorShadowRequest(_FrozenContract):
    """Explicit, stale-state-protected authority for one C3 invocation."""

    operator_run_id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
    operator_authority: Literal["WOLF15_C3_OPERATOR_SHADOW_V1"] = C3_OPERATOR_AUTHORITY
    actor: str = Field(..., min_length=2, max_length=200)
    reason: str = Field(..., min_length=3, max_length=500)
    tradeplan_id: str = Field(..., pattern=r"^5scr-plan:[0-9a-f]{32}$")
    executor_id: UUID
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    expected_governance_version: int = Field(..., ge=1)
    requested_at_utc: datetime
    expires_at_utc: datetime
    confirm_run_id: str

    @field_validator("requested_at_utc", "expires_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, info.field_name)

    @model_validator(mode="after")
    def _validate_intent(self) -> OperatorShadowRequest:
        if self.confirm_run_id != self.operator_run_id:
            raise ValueError("confirm_run_id must exactly match operator_run_id")
        if self.expires_at_utc <= self.requested_at_utc:
            raise ValueError("expires_at_utc must follow requested_at_utc")
        if self.expires_at_utc > self.requested_at_utc + timedelta(seconds=C3_MAX_REQUEST_TTL_SECONDS):
            raise ValueError(f"operator request TTL cannot exceed {C3_MAX_REQUEST_TTL_SECONDS} seconds")
        return self


class OperatorShadowManifest(_FrozenContract):
    """Identity-only lineage handed from the issuing operator to the auditor."""

    schema_version: Literal["wolf15.mt5.operator-shadow-manifest.v1"] = C3_OPERATOR_SHADOW_MANIFEST_VERSION
    operator_run_id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
    operator_authority: Literal["WOLF15_C3_OPERATOR_SHADOW_V1"] = C3_OPERATOR_AUTHORITY
    tradeplan_id: str = Field(..., pattern=r"^5scr-plan:[0-9a-f]{32}$")
    executor_id: UUID
    canonical_symbol: str = Field(..., min_length=3, max_length=32)
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    risk_reservation_id: UUID
    risk_snapshot_id: str = Field(..., min_length=3, max_length=200)
    final_signal_id: str = Field(..., pattern=r"^5scr-signal:[0-9a-f]{32}$")
    final_signal_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    outbox_id: UUID
    command_id: UUID
    execution_mode: Literal["SHADOW"] = "SHADOW"
    broker_execution: Literal["FORBIDDEN"] = "FORBIDDEN"
    requested_at_utc: datetime
    command_expires_at_utc: datetime

    @field_validator("requested_at_utc", "command_expires_at_utc")
    @classmethod
    def _manifest_times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, info.field_name)

    @model_validator(mode="after")
    def _positive_command_window(self) -> OperatorShadowManifest:
        if self.command_expires_at_utc <= self.requested_at_utc:
            raise ValueError("command expiry must follow the operator request")
        return self


__all__ = [
    "C3_MAX_REQUEST_TTL_SECONDS",
    "C3_OPERATOR_AUTHORITY",
    "C3_OPERATOR_SHADOW_MANIFEST_VERSION",
    "OperatorShadowManifest",
    "OperatorShadowRequest",
]
