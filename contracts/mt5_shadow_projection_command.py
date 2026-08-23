"""Credential-free contracts for one manual C2-projection C3 issuance.

The request chooses one immutable ``C2ShadowRiskProjectionV1`` occurrence.
It never creates or names a real risk reservation and can only yield a signed
SHADOW command whose broker-authority flags remain false.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

C3_SHADOW_PROJECTION_OPERATOR_AUTHORITY: Final = "WOLF15_C3_SHADOW_PROJECTION_OPERATOR_V1"
C3_SHADOW_PROJECTION_MANIFEST_VERSION: Final = "wolf15.mt5.shadow-projection-manifest.v1"
C3_SHADOW_PROJECTION_MAX_TTL_SECONDS: Final = 300
C3_SHADOW_PROJECTION_COMMAND_NAMESPACE: Final = UUID("5cd81cc7-55c5-5aa1-99e0-a8c72da60fd1")


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


def c3_shadow_projection_command_id(shadow_authority_id: str) -> UUID:
    """Return the stable UUIDv5 identity of one projection revision."""

    return uuid5(C3_SHADOW_PROJECTION_COMMAND_NAMESPACE, f"c3-shadow-projection:{shadow_authority_id}")


class C3ShadowProjectionCommandRequest(_FrozenContract):
    """Explicit, confirmed authority to issue one selected SHADOW projection."""

    operator_run_id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
    confirm_run_id: str
    operator_authority: Literal["WOLF15_C3_SHADOW_PROJECTION_OPERATOR_V1"] = C3_SHADOW_PROJECTION_OPERATOR_AUTHORITY
    actor: str = Field(..., min_length=2, max_length=200)
    reason: str = Field(..., min_length=3, max_length=500)
    shadow_authority_id: str = Field(..., pattern=r"^5scr-shadow-authority-v1:[0-9a-f]{32}$")
    source_candidate_id: str = Field(..., pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    source_candidate_revision: int = Field(..., ge=1)
    executor_id: UUID
    account_id: str = Field(..., min_length=1, max_length=100)
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    expected_governance_version: int = Field(..., ge=1)
    requested_execution_mode: Literal["SHADOW"] = "SHADOW"
    max_spread_points: int = Field(..., ge=0, le=100_000)
    max_price_drift_points: int = Field(..., ge=0, le=100_000)
    magic: int = Field(..., ge=1, le=2_147_483_647)
    comment_tag: str = Field(default="W15-C3-SHADOW", min_length=3, max_length=31)
    requested_at_utc: datetime
    expires_at_utc: datetime

    @field_validator("requested_at_utc", "expires_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _intent_is_confirmed(self) -> C3ShadowProjectionCommandRequest:
        if self.confirm_run_id != self.operator_run_id:
            raise ValueError("confirm_run_id must exactly match operator_run_id")
        if self.expires_at_utc <= self.requested_at_utc:
            raise ValueError("expires_at_utc must follow requested_at_utc")
        if self.expires_at_utc > self.requested_at_utc + timedelta(seconds=C3_SHADOW_PROJECTION_MAX_TTL_SECONDS):
            raise ValueError(f"operator request TTL cannot exceed {C3_SHADOW_PROJECTION_MAX_TTL_SECONDS} seconds")
        return self

    @property
    def command_id(self) -> UUID:
        return c3_shadow_projection_command_id(self.shadow_authority_id)


class C3ShadowProjectionCommandManifest(_FrozenContract):
    """Durable identity returned for a newly issued or recovered command."""

    schema_version: Literal["wolf15.mt5.shadow-projection-manifest.v1"] = C3_SHADOW_PROJECTION_MANIFEST_VERSION
    operator_run_id: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
    operator_authority: Literal["WOLF15_C3_SHADOW_PROJECTION_OPERATOR_V1"] = C3_SHADOW_PROJECTION_OPERATOR_AUTHORITY
    source_shadow_authority_id: str = Field(..., pattern=r"^5scr-shadow-authority-v1:[0-9a-f]{32}$")
    source_candidate_id: str = Field(..., pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    source_candidate_sequence: int = Field(..., ge=1)
    source_candidate_revision: int = Field(..., ge=1)
    executor_id: UUID
    account_id: str = Field(..., min_length=1, max_length=100)
    canonical_symbol: str = Field(..., min_length=3, max_length=32)
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    account_snapshot_id: str = Field(..., min_length=3, max_length=200)
    governance_version: int = Field(..., ge=1)
    command_id: UUID
    issued_at_utc: datetime
    command_expires_at_utc: datetime
    execution_mode: Literal["SHADOW"] = "SHADOW"
    projection_state: Literal["COMMAND_ISSUED"] = "COMMAND_ISSUED"
    execution_authority: Literal[False] = False
    capital_reserved: Literal[False] = False
    broker_side_effect_allowed: Literal[False] = False
    order_send_eligible: Literal[False] = False

    @field_validator("issued_at_utc", "command_expires_at_utc")
    @classmethod
    def _manifest_times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _identity_and_window_are_coherent(self) -> C3ShadowProjectionCommandManifest:
        if self.command_id != c3_shadow_projection_command_id(self.source_shadow_authority_id):
            raise ValueError("manifest command_id is not the deterministic projection UUIDv5")
        if self.command_expires_at_utc <= self.issued_at_utc:
            raise ValueError("command expiry must follow issuance")
        return self


__all__ = [
    "C3_SHADOW_PROJECTION_COMMAND_NAMESPACE",
    "C3_SHADOW_PROJECTION_MANIFEST_VERSION",
    "C3_SHADOW_PROJECTION_MAX_TTL_SECONDS",
    "C3_SHADOW_PROJECTION_OPERATOR_AUTHORITY",
    "C3ShadowProjectionCommandManifest",
    "C3ShadowProjectionCommandRequest",
    "c3_shadow_projection_command_id",
]
