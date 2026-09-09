"""Typed boundary for durable Strategy 5S-CR parent risk reservations.

This contract deliberately stops at a PostgreSQL final-signal outbox.  It does
not sign an MT5 command, mutate executor governance, or authorize broker
execution.  The first rollout is parent-only until broker reconciliation can
prove an open parent before a child reservation is considered.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RISK_RESERVATION_SCHEMA_VERSION: Final = "wolf15.strategy-5scr.risk-reservation.v1"
FINAL_SIGNAL_SCHEMA_VERSION: Final = "wolf15.strategy-5scr.final-signal.v1"
RISK_POLICY_ID: Final = "5scr.production-adjusted.parent-only.v1"
MAX_RESERVATION_TTL_SECONDS: Final = 300


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


class RiskReservationRequest(FrozenContract):
    """Identity-only request consumed by the internal risk authority."""

    tradeplan_id: str = Field(..., pattern=r"^5scr-plan:[0-9a-f]{32}$")
    executor_id: UUID
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    entry_role: Literal["PARENT"] = "PARENT"
    requested_at_utc: datetime
    expires_at_utc: datetime

    @field_validator("requested_at_utc", "expires_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, info.field_name)

    @model_validator(mode="after")
    def _bounded_window(self) -> RiskReservationRequest:
        if self.expires_at_utc <= self.requested_at_utc:
            raise ValueError("expires_at_utc must follow requested_at_utc")
        if self.expires_at_utc > self.requested_at_utc + timedelta(seconds=MAX_RESERVATION_TTL_SECONDS):
            raise ValueError(f"reservation TTL cannot exceed {MAX_RESERVATION_TTL_SECONDS} seconds")
        return self


class FinalSignalRiskReservation(FrozenContract):
    """Credential-free reservation proof embedded in final SignalJSON."""

    schema_version: Literal["wolf15.strategy-5scr.risk-reservation.v1"] = RISK_RESERVATION_SCHEMA_VERSION
    reservation_id: UUID
    campaign_id: str = Field(..., min_length=3, max_length=240)
    tradeplan_id: str = Field(..., pattern=r"^5scr-plan:[0-9a-f]{32}$")
    canonical_symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    direction: Literal["BUY", "SELL"]
    policy_id: Literal["5scr.production-adjusted.parent-only.v1"] = RISK_POLICY_ID
    state: Literal["HELD"] = "HELD"
    risk_snapshot_id: str = Field(..., min_length=3, max_length=200)
    entry_role: Literal["PARENT"] = "PARENT"
    risk_unit_usd: float = Field(..., gt=0)
    reserved_risk_usd: float = Field(..., gt=0)
    reserved_volume: float = Field(..., gt=0)
    reserved_at_utc: datetime
    expires_at_utc: datetime

    @field_validator("reserved_at_utc", "expires_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, info.field_name)

    @model_validator(mode="after")
    def _risk_is_bounded(self) -> FinalSignalRiskReservation:
        if self.expires_at_utc <= self.reserved_at_utc:
            raise ValueError("reservation proof must have a positive validity window")
        if self.expires_at_utc > self.reserved_at_utc + timedelta(seconds=MAX_RESERVATION_TTL_SECONDS):
            raise ValueError(f"reservation proof TTL cannot exceed {MAX_RESERVATION_TTL_SECONDS} seconds")
        if self.reserved_risk_usd > self.risk_unit_usd + 1e-8:
            raise ValueError("reserved risk cannot exceed the locked campaign risk unit")
        return self


class DurableRiskReservation(FrozenContract):
    reservation_id: UUID
    campaign_id: str = Field(..., min_length=3, max_length=240)
    tradeplan_id: str = Field(..., pattern=r"^5scr-plan:[0-9a-f]{32}$")
    executor_id: UUID
    account_id: str = Field(..., min_length=1, max_length=100)
    account_snapshot_id: str = Field(..., min_length=3, max_length=200)
    policy_id: Literal["5scr.production-adjusted.parent-only.v1"] = RISK_POLICY_ID
    state: Literal["HELD"] = "HELD"
    canonical_symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    entry_role: Literal["PARENT"] = "PARENT"
    direction: Literal["BUY", "SELL"]
    volume: float = Field(..., gt=0)
    entry_price: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profit: float = Field(..., gt=0)
    risk_unit_usd: float = Field(..., gt=0)
    reserved_risk_usd: float = Field(..., gt=0)
    balance_snapshot: float = Field(..., gt=0)
    equity_snapshot: float = Field(..., gt=0)
    reserved_at_utc: datetime
    expires_at_utc: datetime

    @field_validator("reserved_at_utc", "expires_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, info.field_name)

    @model_validator(mode="after")
    def _geometry_and_risk_are_valid(self) -> DurableRiskReservation:
        if self.expires_at_utc <= self.reserved_at_utc:
            raise ValueError("reservation must have a positive validity window")
        if self.expires_at_utc > self.reserved_at_utc + timedelta(seconds=MAX_RESERVATION_TTL_SECONDS):
            raise ValueError(f"reservation TTL cannot exceed {MAX_RESERVATION_TTL_SECONDS} seconds")
        if self.reserved_risk_usd > self.risk_unit_usd + 1e-8:
            raise ValueError("reserved risk cannot exceed the locked campaign risk unit")
        valid_geometry = (
            self.stop_loss < self.entry_price < self.take_profit
            if self.direction == "BUY"
            else self.take_profit < self.entry_price < self.stop_loss
        )
        if not valid_geometry:
            raise ValueError("reservation price geometry does not match direction")
        return self

    def signal_proof(self) -> FinalSignalRiskReservation:
        return FinalSignalRiskReservation(
            reservation_id=self.reservation_id,
            campaign_id=self.campaign_id,
            tradeplan_id=self.tradeplan_id,
            canonical_symbol=self.canonical_symbol,
            broker_symbol=self.broker_symbol,
            direction=self.direction,
            risk_snapshot_id=self.account_snapshot_id,
            risk_unit_usd=self.risk_unit_usd,
            reserved_risk_usd=self.reserved_risk_usd,
            reserved_volume=self.volume,
            reserved_at_utc=self.reserved_at_utc,
            expires_at_utc=self.expires_at_utc,
        )


class RiskReservationResult(FrozenContract):
    reservation: DurableRiskReservation
    outbox_id: UUID
    signal_id: str = Field(..., pattern=r"^5scr-signal:[0-9a-f]{32}$")
    signal_payload: dict[str, Any]
    signal_payload_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")


def validate_final_signal_reservation(signal: dict[str, Any]) -> FinalSignalRiskReservation:
    """Validate the embedded proof and its top-level immutable bindings."""

    if signal.get("event") != "signal_json" or signal.get("schema_version") != FINAL_SIGNAL_SCHEMA_VERSION:
        raise ValueError("risk-authorized final signal has the wrong event or schema version")
    for field in ("signal_valid", "is_final_signal", "execution_valid_now", "valid_for_execution"):
        if signal.get(field) is not True:
            raise ValueError(f"risk-authorized final signal requires {field}=true")
    raw = signal.get("risk_reservation")
    if not isinstance(raw, dict):
        raise ValueError("final SignalJSON is missing risk_reservation proof")
    proof = FinalSignalRiskReservation.model_validate(raw)
    if signal.get("risk_reservation_id") != str(proof.reservation_id):
        raise ValueError("top-level risk_reservation_id does not match proof")
    if signal.get("risk_snapshot_id") != proof.risk_snapshot_id:
        raise ValueError("top-level risk_snapshot_id does not match proof")
    bindings = {
        "tradeplan_id": proof.tradeplan_id,
        "lifecycle_id": proof.campaign_id,
        "symbol": proof.canonical_symbol,
        "broker_symbol": proof.broker_symbol,
        "final_direction": proof.direction,
    }
    for field, expected in bindings.items():
        if signal.get(field) != expected:
            raise ValueError(f"top-level {field} does not match reservation proof")
    reserved_volume = signal.get("reserved_volume")
    if not isinstance(reserved_volume, (int, float)) or not math.isclose(
        float(reserved_volume), proof.reserved_volume, rel_tol=1e-9, abs_tol=1e-9
    ):
        raise ValueError("top-level reserved_volume does not match proof")
    forbidden = {
        "account_id",
        "account_number",
        "executor_id",
        "login_hash",
        "token",
        "verification_key",
        "balance",
        "equity",
    }
    if forbidden.intersection(signal) or forbidden.intersection(raw):
        raise ValueError("final SignalJSON reservation proof leaks account or credential data")
    return proof


__all__ = [
    "DurableRiskReservation",
    "FINAL_SIGNAL_SCHEMA_VERSION",
    "FinalSignalRiskReservation",
    "MAX_RESERVATION_TTL_SECONDS",
    "RISK_POLICY_ID",
    "RISK_RESERVATION_SCHEMA_VERSION",
    "RiskReservationRequest",
    "RiskReservationResult",
    "validate_final_signal_reservation",
]
