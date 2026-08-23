"""Command-inert C2 SHADOW risk projection contracts.

A projection records what the canonical Candidate V2 risk calculation would
have authorized.  It is not a capital reservation and cannot authorize a
broker side effect.  C3 may consume an AVAILABLE projection only to issue one
separately governed SHADOW command.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.strategy_5scr_tradeplan_candidate_v2 import (
    canonical_hash_v1,
    canonical_tradeplan_numeric_v2,
)

C2_SHADOW_RISK_PROJECTION_RULE_VERSION = "5scr.c2-shadow-risk-projection.v1"
C2_SHADOW_SOURCE_ADMISSION_CLASS = "CANONICAL_CANDIDATE_V2"
C2_SHADOW_MARGIN_STATUS = "NOT_MEASURED"
C2_SHADOW_RISK_PROJECTION_MAX_TTL_SECONDS = 300


class C2ShadowRiskProjectionDecision(StrEnum):
    WOULD_RESERVE = "WOULD_RESERVE"
    WOULD_REJECT = "WOULD_REJECT"


class C2ShadowRiskProjectionState(StrEnum):
    AVAILABLE = "AVAILABLE"
    COMMAND_ISSUED = "COMMAND_ISSUED"
    REJECTED = "REJECTED"


class _FrozenProjectionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


def c2_shadow_risk_projection_authority_material_v1(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the immutable authority material; mutable issuance state is excluded."""

    def durable_numeric(value: Any) -> Decimal | None:
        if value is None:
            return None
        return canonical_tradeplan_numeric_v2(Decimal(value))

    return {
        "source_admission_class": payload["source_admission_class"],
        "tradeplan_id": payload["tradeplan_id"],
        "strategy_lifecycle_id": payload["strategy_lifecycle_id"],
        "context_epoch_id": payload["context_epoch_id"],
        "strategy_thesis_id": payload["strategy_thesis_id"],
        "execution_box_id": payload["execution_box_id"],
        "candidate_sequence": payload["candidate_sequence"],
        "candidate_revision": payload["candidate_revision"],
        "material_context_hash": payload["material_context_hash"],
        "thesis_semantic_identity_hash": payload["thesis_semantic_identity_hash"],
        "material_candidate_hash": payload["material_candidate_hash"],
        "candidate_evidence_hash": payload["candidate_evidence_hash"],
        "executor_id": str(payload["executor_id"]),
        "account_id": payload["account_id"],
        "account_snapshot_id": payload["account_snapshot_id"],
        "account_snapshot_hash": payload["account_snapshot_hash"],
        "broker_server": payload["broker_server"],
        "symbol": payload["symbol"],
        "broker_symbol": payload["broker_symbol"],
        "direction": payload["direction"],
        "entry_price": durable_numeric(payload["entry_price"]),
        "stop_loss": durable_numeric(payload["stop_loss"]),
        "target_price": durable_numeric(payload["target_price"]),
        "would_volume": durable_numeric(payload["would_volume"]),
        "would_risk_usd": durable_numeric(payload["would_risk_usd"]),
        "would_margin_usd": durable_numeric(payload["would_margin_usd"]),
        "would_margin_status": payload["would_margin_status"],
        "would_open_risk_after_usd": durable_numeric(payload["would_open_risk_after_usd"]),
        "decision": str(payload["decision"]),
        "reason_code": payload["reason_code"],
        "kill_switch_observed": payload["kill_switch_observed"],
        "projected_at_utc": payload["projected_at_utc"],
        "expires_at_utc": payload["expires_at_utc"],
        "evidence_hash": payload["evidence_hash"],
        "rule_version": payload["rule_version"],
        "execution_authority": False,
        "capital_reserved": False,
        "broker_side_effect_allowed": False,
        "order_send_eligible": False,
    }


def c2_shadow_risk_projection_id_v1(payload: Mapping[str, Any], authority_hash: str) -> str:
    identity = canonical_hash_v1(
        {
            "tradeplan_id": payload["tradeplan_id"],
            "candidate_sequence": payload["candidate_sequence"],
            "candidate_revision": payload["candidate_revision"],
            "executor_id": str(payload["executor_id"]),
            "account_id": payload["account_id"],
            "account_snapshot_id": payload["account_snapshot_id"],
            "authority_hash": authority_hash,
        }
    )
    return "5scr-shadow-authority-v1:" + hashlib.sha256(identity.encode()).hexdigest()[:32]


class C2ShadowRiskProjectionV1(_FrozenProjectionContract):
    """Durable observation of risk feasibility with every execution flag hard-off."""

    shadow_authority_id: str = Field(..., pattern=r"^5scr-shadow-authority-v1:[0-9a-f]{32}$")
    source_admission_class: Literal["CANONICAL_CANDIDATE_V2"] = C2_SHADOW_SOURCE_ADMISSION_CLASS
    tradeplan_id: str = Field(..., pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    strategy_thesis_id: str = Field(..., pattern=r"^5scr-thesis:[0-9a-f]{32}$")
    execution_box_id: str = Field(..., pattern=r"^5scr-execution-box:[0-9a-f]{32}$")
    candidate_sequence: int = Field(..., ge=1)
    candidate_revision: Literal[1] = 1
    material_context_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    thesis_semantic_identity_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    material_candidate_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    candidate_evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    executor_id: UUID
    account_id: str = Field(..., min_length=1, max_length=100)
    account_snapshot_id: str = Field(..., min_length=3, max_length=200)
    account_snapshot_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    broker_server: str = Field(..., min_length=1, max_length=200)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    direction: Literal["BUY", "SELL"]
    entry_price: Decimal = Field(..., gt=0)
    stop_loss: Decimal = Field(..., gt=0)
    target_price: Decimal = Field(..., gt=0)
    would_volume: Decimal | None = Field(default=None, gt=0)
    would_risk_usd: Decimal | None = Field(default=None, gt=0)
    would_margin_usd: Decimal | None = Field(default=None, ge=0)
    would_margin_status: Literal["NOT_MEASURED"] = C2_SHADOW_MARGIN_STATUS
    would_open_risk_after_usd: Decimal | None = Field(default=None, gt=0)
    decision: C2ShadowRiskProjectionDecision
    reason_code: str = Field(..., min_length=3, max_length=120, pattern=r"^[A-Z0-9_]+$")
    state: C2ShadowRiskProjectionState
    state_version: int = Field(default=1, ge=1)
    kill_switch_observed: Literal["ENGAGED"] = "ENGAGED"
    projected_at_utc: datetime
    expires_at_utc: datetime
    evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    rule_version: Literal["5scr.c2-shadow-risk-projection.v1"] = C2_SHADOW_RISK_PROJECTION_RULE_VERSION
    execution_authority: Literal[False] = False
    capital_reserved: Literal[False] = False
    broker_side_effect_allowed: Literal[False] = False
    order_send_eligible: Literal[False] = False

    @field_validator("projected_at_utc", "expires_at_utc")
    @classmethod
    def _projected_at_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "projected_at_utc")

    @model_validator(mode="after")
    def _projection_is_coherent(self) -> C2ShadowRiskProjectionV1:
        if (
            not self.projected_at_utc
            < self.expires_at_utc
            <= self.projected_at_utc + timedelta(seconds=C2_SHADOW_RISK_PROJECTION_MAX_TTL_SECONDS)
        ):
            raise ValueError("shadow risk projection expiry is outside its 300-second authority window")
        if self.direction == "BUY" and not self.stop_loss < self.entry_price < self.target_price:
            raise ValueError("BUY projection geometry is invalid")
        if self.direction == "SELL" and not self.target_price < self.entry_price < self.stop_loss:
            raise ValueError("SELL projection geometry is invalid")
        sizing = (self.would_volume, self.would_risk_usd, self.would_open_risk_after_usd)
        if self.would_margin_usd is not None or self.would_margin_status != C2_SHADOW_MARGIN_STATUS:
            raise ValueError("prospective margin must remain explicitly NOT_MEASURED")
        if self.decision is C2ShadowRiskProjectionDecision.WOULD_RESERVE:
            if self.state not in {
                C2ShadowRiskProjectionState.AVAILABLE,
                C2ShadowRiskProjectionState.COMMAND_ISSUED,
            }:
                raise ValueError("WOULD_RESERVE projection state is invalid")
            if any(item is None for item in sizing):
                raise ValueError("WOULD_RESERVE requires complete projected sizing")
            assert self.would_risk_usd is not None and self.would_open_risk_after_usd is not None
            if self.would_open_risk_after_usd < self.would_risk_usd:
                raise ValueError("projected account risk cannot be below projected order risk")
        else:
            if self.state is not C2ShadowRiskProjectionState.REJECTED or any(item is not None for item in sizing):
                raise ValueError("WOULD_REJECT must be terminal and carry no projected sizing")
        expected_state_version = 2 if self.state is C2ShadowRiskProjectionState.COMMAND_ISSUED else 1
        if self.state_version != expected_state_version:
            raise ValueError("shadow risk projection state version is invalid")
        material = c2_shadow_risk_projection_authority_material_v1(self.model_dump(mode="python"))
        expected_authority_hash = canonical_hash_v1(material)
        expected_id = c2_shadow_risk_projection_id_v1(material, expected_authority_hash)
        if self.authority_hash != expected_authority_hash or self.shadow_authority_id != expected_id:
            raise ValueError("shadow risk projection authority integrity mismatch")
        return self


class C2ShadowRiskProjectionEvaluationV1(_FrozenProjectionContract):
    """Typed evaluation result; noncanonical input is rejected without persistence."""

    source_admission_class: str = Field(..., min_length=3, max_length=80)
    decision: C2ShadowRiskProjectionDecision
    reason_code: str = Field(..., min_length=3, max_length=120, pattern=r"^[A-Z0-9_]+$")
    projection: C2ShadowRiskProjectionV1 | None = None

    @model_validator(mode="after")
    def _result_is_coherent(self) -> C2ShadowRiskProjectionEvaluationV1:
        if self.source_admission_class != C2_SHADOW_SOURCE_ADMISSION_CLASS:
            if (
                self.decision is not C2ShadowRiskProjectionDecision.WOULD_REJECT
                or self.reason_code != "C2_SHADOW_SOURCE_NOT_CANONICAL"
                or self.projection is not None
            ):
                raise ValueError("noncanonical sources must fail closed without a projection")
        elif self.projection is None or self.projection.decision is not self.decision:
            raise ValueError("canonical evaluation must contain its durable projection")
        return self


__all__ = [
    "C2_SHADOW_MARGIN_STATUS",
    "C2_SHADOW_RISK_PROJECTION_RULE_VERSION",
    "C2_SHADOW_RISK_PROJECTION_MAX_TTL_SECONDS",
    "C2_SHADOW_SOURCE_ADMISSION_CLASS",
    "C2ShadowRiskProjectionDecision",
    "C2ShadowRiskProjectionEvaluationV1",
    "C2ShadowRiskProjectionState",
    "C2ShadowRiskProjectionV1",
    "c2_shadow_risk_projection_authority_material_v1",
    "c2_shadow_risk_projection_id_v1",
]
