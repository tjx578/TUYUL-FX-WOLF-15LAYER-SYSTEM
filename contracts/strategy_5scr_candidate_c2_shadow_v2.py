"""Typed CandidateV2 -> C2 SHADOW risk-authority contracts.

These contracts authorize strategy and risk in the backend authority plane.
They deliberately do not authorize command creation, delivery, or broker
execution.  C3 manual SHADOW promotion is a separate boundary.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.mt5_execution_protocol import AccountSnapshotV1
from contracts.strategy_5scr_tradeplan_candidate_v2 import (
    TradePlanCandidateV2,
    canonical_hash_v1,
    canonical_tradeplan_numeric_v2,
)

C2_SHADOW_RULE_VERSION = "5scr.candidate-c2-shadow.v2"
C2_SHADOW_RISK_POLICY_ID = "5scr.c2-shadow.parent-only.v2"
C2_SHADOW_RISK_PERCENT_PER_ENTRY = Decimal("0.05")
C2_SHADOW_MAX_ENTRIES = 2
C2_SHADOW_MAX_TOTAL_OPEN_RISK_PERCENT = Decimal("0.10")
C2_SHADOW_FINAL_SIGNAL_SCHEMA = "wolf15.strategy-5scr.final-signal.shadow.v2"
C2_SHADOW_MAX_TTL_SECONDS = 300
C2_SHADOW_SNAPSHOT_MAX_AGE_SECONDS = 30
C2_SHADOW_CANDIDATE_MAX_AGE_SECONDS = 120
C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS = 30
_C2_NUMERIC_28_12_ABS_LIMIT = Decimal("1e16")

C2Decision = Literal["APPROVED", "WAIT", "REJECTED", "DUPLICATE", "QUARANTINED"]
PersistedC2Decision = Literal["APPROVED", "WAIT", "REJECTED"]
Direction = Literal["BUY", "SELL"]


class FrozenC2Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


def _identity(prefix: str, material: object) -> str:
    digest = hashlib.sha256(canonical_hash_v1(material).encode()).hexdigest()[:32]
    return f"{prefix}:{digest}"


def _durable_numeric_v2(value: Decimal, field_name: str) -> Decimal:
    """Normalize authority numerics without silently losing material value."""

    try:
        canonical = canonical_tradeplan_numeric_v2(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} is not exactly representable on the durable NUMERIC(28,12) grid") from exc
    if not value.is_finite() or abs(value) >= _C2_NUMERIC_28_12_ABS_LIMIT or canonical != value:
        raise ValueError(f"{field_name} is not exactly representable on the durable NUMERIC(28,12) grid")
    return canonical


def account_snapshot_authority_hash_v2(snapshot: AccountSnapshotV1) -> str:
    return canonical_hash_v1(snapshot.model_dump(mode="json"))


def symbol_capability_authority_hash_v2(capability: object) -> str:
    if not isinstance(capability, BaseModel):
        raise TypeError("symbol capability authority requires a typed model")
    return canonical_hash_v1(capability.model_dump(mode="json"))


def candidate_c2_shadow_handoff_identity_material_v2(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return occurrence-stable candidate/account material bound by the handoff ID."""

    return {
        "tradeplan_id": payload["tradeplan_id"],
        "candidate_sequence": payload["candidate_sequence"],
        "candidate_revision": payload["candidate_revision"],
        "strategy_lifecycle_id": payload["strategy_lifecycle_id"],
        "context_epoch_id": payload["context_epoch_id"],
        "strategy_thesis_id": payload["strategy_thesis_id"],
        "execution_box_id": payload["execution_box_id"],
        "material_context_hash": payload["material_context_hash"],
        "thesis_semantic_identity_hash": payload["thesis_semantic_identity_hash"],
        "execution_box_material_hash": payload["execution_box_material_hash"],
        "execution_box_freeze_authority_hash": payload["execution_box_freeze_authority_hash"],
        "material_candidate_hash": payload["material_candidate_hash"],
        "candidate_evidence_hash": payload["candidate_evidence_hash"],
        "symbol": payload["symbol"],
        "direction": payload["direction"],
        "candidate_price": payload["candidate_price"],
        "stop_loss": payload["stop_loss"],
        "take_profit": payload["take_profit"],
        "target_authority_hash": payload["target_authority_hash"],
        "stop_authority_hash": payload["stop_authority_hash"],
        "broker_geometry_material_hash": payload["broker_geometry_material_hash"],
        "account_id": payload["account_id"],
        "executor_id": str(payload["executor_id"]),
        "broker_server": payload["broker_server"],
        "risk_policy_id": payload["risk_policy_id"],
        "rule_version": payload["rule_version"],
    }


def candidate_c2_shadow_handoff_authority_material_v2(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the full admitted handoff payload bound by its authority hash."""

    return {
        "handoff_id": payload["handoff_id"],
        **candidate_c2_shadow_handoff_identity_material_v2(payload),
        "account_snapshot_id": payload["account_snapshot_id"],
        "account_snapshot_hash": payload["account_snapshot_hash"],
        "symbol_capability_hash": payload["symbol_capability_hash"],
        "governance_evidence_hash": payload["governance_evidence_hash"],
        "existing_risk_evidence_hash": payload["existing_risk_evidence_hash"],
        "accepted_at_utc": payload["accepted_at_utc"],
        "execution_mode": payload["execution_mode"],
    }


class C2ShadowGovernanceEvidenceV2(FrozenC2Contract):
    executor_id: UUID
    account_id: str = Field(..., min_length=1, max_length=100)
    broker_server: str = Field(..., min_length=1, max_length=200)
    executor_registered: bool = True
    executor_revoked: bool = False
    execution_mode: Literal["SHADOW", "DEMO", "LIVE"] = "SHADOW"
    kill_switch_state: Literal["ENGAGED", "DISENGAGED"] = "DISENGAGED"
    verified_at_utc: datetime
    evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    execution_authority: Literal[False] = False

    @field_validator("verified_at_utc")
    @classmethod
    def _verified_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "verified_at_utc")

    @model_validator(mode="after")
    def _hash_is_coherent(self) -> C2ShadowGovernanceEvidenceV2:
        expected = canonical_hash_v1(
            {
                "executor_id": str(self.executor_id),
                "account_id": self.account_id,
                "broker_server": self.broker_server,
                "executor_registered": self.executor_registered,
                "executor_revoked": self.executor_revoked,
                "execution_mode": self.execution_mode,
                "kill_switch_state": self.kill_switch_state,
                "verified_at_utc": self.verified_at_utc,
            }
        )
        if self.evidence_hash != expected:
            raise ValueError("C2 governance evidence hash mismatch")
        return self


def c2_shadow_governance_evidence_v2(
    *,
    executor_id: UUID,
    account_id: str,
    broker_server: str,
    verified_at_utc: datetime,
) -> C2ShadowGovernanceEvidenceV2:
    payload = {
        "executor_id": str(executor_id),
        "account_id": account_id,
        "broker_server": broker_server,
        "executor_registered": True,
        "executor_revoked": False,
        "execution_mode": "SHADOW",
        "kill_switch_state": "DISENGAGED",
        "verified_at_utc": _utc(verified_at_utc, "verified_at_utc"),
    }
    return C2ShadowGovernanceEvidenceV2(**payload, evidence_hash=canonical_hash_v1(payload))


class C2ShadowExistingRiskEvidenceV2(FrozenC2Contract):
    account_id: str = Field(..., min_length=1, max_length=100)
    tradeplan_id: str = Field(..., pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    active_campaign_count: int = Field(default=0, ge=0)
    active_reservation_count: int = Field(default=0, ge=0)
    pending_order_count: int = Field(default=0, ge=0)
    broker_ledger_reconciled: bool = True
    committed_or_reserved_campaign_risk_usd: Decimal = Field(default=Decimal("0"), ge=0)
    account_total_open_risk_usd: Decimal = Field(default=Decimal("0"), ge=0)
    captured_at_utc: datetime
    evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    execution_authority: Literal[False] = False

    @field_validator("captured_at_utc")
    @classmethod
    def _captured_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "captured_at_utc")

    @model_validator(mode="after")
    def _hash_is_coherent(self) -> C2ShadowExistingRiskEvidenceV2:
        expected = canonical_hash_v1(
            {
                "account_id": self.account_id,
                "tradeplan_id": self.tradeplan_id,
                "active_campaign_count": self.active_campaign_count,
                "active_reservation_count": self.active_reservation_count,
                "pending_order_count": self.pending_order_count,
                "broker_ledger_reconciled": self.broker_ledger_reconciled,
                "committed_or_reserved_campaign_risk_usd": self.committed_or_reserved_campaign_risk_usd,
                "account_total_open_risk_usd": self.account_total_open_risk_usd,
                "captured_at_utc": self.captured_at_utc,
            }
        )
        if self.evidence_hash != expected:
            raise ValueError("C2 existing-risk evidence hash mismatch")
        return self


def c2_shadow_existing_risk_evidence_v2(
    *, account_id: str, tradeplan_id: str, captured_at_utc: datetime
) -> C2ShadowExistingRiskEvidenceV2:
    payload = {
        "account_id": account_id,
        "tradeplan_id": tradeplan_id,
        "active_campaign_count": 0,
        "active_reservation_count": 0,
        "pending_order_count": 0,
        "broker_ledger_reconciled": True,
        "committed_or_reserved_campaign_risk_usd": Decimal("0"),
        "account_total_open_risk_usd": Decimal("0"),
        "captured_at_utc": _utc(captured_at_utc, "captured_at_utc"),
    }
    return C2ShadowExistingRiskEvidenceV2(**payload, evidence_hash=canonical_hash_v1(payload))


class CandidateC2ShadowBuildEvidenceV2(FrozenC2Contract):
    source_request_id: str = Field(..., min_length=1, max_length=240)
    decision_at_utc: datetime
    expires_at_utc: datetime
    candidate: TradePlanCandidateV2
    governance: C2ShadowGovernanceEvidenceV2
    account_snapshot: AccountSnapshotV1
    account_snapshot_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    existing_risk: C2ShadowExistingRiskEvidenceV2
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    source_deployment_id: str | None = Field(default=None, max_length=200)
    source_replica_id: str | None = Field(default=None, max_length=200)
    execution_authority: Literal[False] = False

    @field_validator("decision_at_utc", "expires_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _scope_and_window_are_coherent(self) -> CandidateC2ShadowBuildEvidenceV2:
        if self.expires_at_utc <= self.decision_at_utc:
            raise ValueError("C2 authority expiry must follow decision")
        if self.expires_at_utc > self.decision_at_utc + timedelta(seconds=C2_SHADOW_MAX_TTL_SECONDS):
            raise ValueError("C2 authority TTL exceeds 300 seconds")
        if self.account_snapshot_hash != account_snapshot_authority_hash_v2(self.account_snapshot):
            raise ValueError("account snapshot authority hash mismatch")
        if (
            self.governance.executor_id != self.account_snapshot.executor_id
            or self.governance.account_id != self.account_snapshot.account_id
            or self.existing_risk.account_id != self.account_snapshot.account_id
            or self.existing_risk.tradeplan_id != self.candidate.tradeplan_id
        ):
            raise ValueError("C2 candidate/governance/account/risk scope mismatch")
        return self

    def authority_hash(self) -> str:
        return canonical_hash_v1(
            {
                "source_request_id": self.source_request_id,
                "decision_at_utc": self.decision_at_utc,
                "expires_at_utc": self.expires_at_utc,
                "tradeplan_id": self.candidate.tradeplan_id,
                "candidate_material_hash": self.candidate.material_candidate_hash,
                "candidate_evidence_hash": self.candidate.evidence_hash,
                "governance_hash": self.governance.evidence_hash,
                "account_snapshot_hash": self.account_snapshot_hash,
                "existing_risk_hash": self.existing_risk.evidence_hash,
                "broker_symbol": self.broker_symbol,
                "source_deployment_id": self.source_deployment_id,
                "source_replica_id": self.source_replica_id,
            }
        )


def snapshot_candidate_c2_build_evidence_v2(
    evidence: CandidateC2ShadowBuildEvidenceV2,
) -> CandidateC2ShadowBuildEvidenceV2:
    """Deep-snapshot mutable protocol children and revalidate hashed authority."""

    snapshot = evidence.model_copy(deep=True)
    if snapshot.account_snapshot_hash != account_snapshot_authority_hash_v2(snapshot.account_snapshot):
        raise ValueError("C2_ACCOUNT_SNAPSHOT_HASH_DRIFT")
    candidate_payload = snapshot.candidate.model_dump(mode="python", warnings=False)
    try:
        candidate = TradePlanCandidateV2.model_validate(candidate_payload)
    except ValueError as candidate_error:
        # The reducer owns the durable NUMERIC(28,12) rejection reason. A
        # ``model_copy``-forged, unrepresentable entry price therefore still
        # reaches that typed gate, but only after restoring the price implied
        # by independently hashed target/distance material proves that every
        # other nested candidate authority remains canonical.
        raw_price = snapshot.candidate.candidate_price
        if not isinstance(raw_price, Decimal):
            raise candidate_error from None
        try:
            _durable_numeric_v2(raw_price, "candidate_price")
        except ValueError:
            target = snapshot.candidate.target_authority.target_price
            distance = snapshot.candidate.target_distance_pips * snapshot.candidate.broker_pip_size
            canonical_price = target - distance if snapshot.candidate.direction == "BUY" else target + distance
            candidate_payload["candidate_price"] = canonical_price
            try:
                TradePlanCandidateV2.model_validate(candidate_payload)
            except ValueError:
                raise candidate_error from None
            candidate = snapshot.candidate.model_copy(deep=True)
        else:
            raise
    governance = C2ShadowGovernanceEvidenceV2.model_validate(snapshot.governance.model_dump(mode="python"))
    existing_risk = C2ShadowExistingRiskEvidenceV2.model_validate(snapshot.existing_risk.model_dump(mode="python"))
    snapshot = snapshot.model_copy(
        update={"candidate": candidate, "governance": governance, "existing_risk": existing_risk}
    )
    # Re-run the aggregate hash, scope and TTL checks without recursively
    # validating reducer-owned numeric material (which must receive a typed,
    # fail-closed reduction reason rather than a generic integrity verdict).
    if snapshot.expires_at_utc <= snapshot.decision_at_utc:
        raise ValueError("C2 authority expiry must follow decision")
    if snapshot.expires_at_utc > snapshot.decision_at_utc + timedelta(seconds=C2_SHADOW_MAX_TTL_SECONDS):
        raise ValueError("C2 authority TTL exceeds 300 seconds")
    if (
        snapshot.governance.executor_id != snapshot.account_snapshot.executor_id
        or snapshot.governance.account_id != snapshot.account_snapshot.account_id
        or snapshot.existing_risk.account_id != snapshot.account_snapshot.account_id
        or snapshot.existing_risk.tradeplan_id != snapshot.candidate.tradeplan_id
    ):
        raise ValueError("C2 candidate/governance/account/risk scope mismatch")
    return snapshot


class CandidateC2ShadowHandoffV2(FrozenC2Contract):
    handoff_id: str = Field(..., pattern=r"^5scr-c2-handoff-v2:[0-9a-f]{32}$")
    tradeplan_id: str = Field(..., pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    candidate_sequence: int = Field(..., ge=1)
    candidate_revision: int = Field(..., ge=1)
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    strategy_thesis_id: str = Field(..., pattern=r"^5scr-thesis:[0-9a-f]{32}$")
    execution_box_id: str = Field(..., pattern=r"^5scr-execution-box:[0-9a-f]{32}$")
    account_id: str = Field(..., min_length=1, max_length=100)
    executor_id: UUID
    broker_server: str = Field(..., min_length=1, max_length=200)
    account_snapshot_id: str = Field(..., min_length=3, max_length=200)
    account_snapshot_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    symbol_capability_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    governance_evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    existing_risk_evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    material_context_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    thesis_semantic_identity_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    execution_box_material_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    execution_box_freeze_authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    material_candidate_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    candidate_evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    symbol: str = Field(..., min_length=3, max_length=32)
    direction: Direction
    candidate_price: Decimal = Field(..., gt=0)
    stop_loss: Decimal = Field(..., gt=0)
    take_profit: Decimal = Field(..., gt=0)
    target_authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    stop_authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    broker_geometry_material_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    accepted_at_utc: datetime
    risk_policy_id: Literal["5scr.c2-shadow.parent-only.v2"] = C2_SHADOW_RISK_POLICY_ID
    rule_version: Literal["5scr.candidate-c2-shadow.v2"] = C2_SHADOW_RULE_VERSION
    authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    execution_mode: Literal["SHADOW"] = "SHADOW"
    execution_authority: Literal[False] = False

    @field_validator("candidate_price", "stop_loss", "take_profit")
    @classmethod
    def _prices_are_durable(cls, value: Decimal, info: Any) -> Decimal:
        return _durable_numeric_v2(value, str(info.field_name))

    @field_validator("accepted_at_utc")
    @classmethod
    def _accepted_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "accepted_at_utc")

    @model_validator(mode="after")
    def _authority_is_coherent(self) -> CandidateC2ShadowHandoffV2:
        geometry = (
            self.stop_loss < self.candidate_price < self.take_profit
            if self.direction == "BUY"
            else self.take_profit < self.candidate_price < self.stop_loss
        )
        if self.candidate_revision != 1 or not geometry:
            raise ValueError("C2 handoff candidate revision/geometry is invalid")
        payload = self.model_dump(mode="python")
        identity_material = candidate_c2_shadow_handoff_identity_material_v2(payload)
        authority_material = candidate_c2_shadow_handoff_authority_material_v2(payload)
        if self.authority_hash != canonical_hash_v1(authority_material) or self.handoff_id != _identity(
            "5scr-c2-handoff-v2", identity_material
        ):
            raise ValueError("C2 handoff authority integrity mismatch")
        return self


class C2ShadowCampaignRiskLockV2(FrozenC2Contract):
    risk_lock_id: str = Field(..., pattern=r"^5scr-c2-risk-lock-v2:[0-9a-f]{32}$")
    execution_campaign_id: str = Field(..., pattern=r"^5scr-execution-campaign-v2:[0-9a-f]{32}$")
    tradeplan_id: str = Field(..., pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    account_id: str = Field(..., min_length=1, max_length=100)
    account_snapshot_id: str = Field(..., min_length=3, max_length=200)
    policy_id: Literal["5scr.c2-shadow.parent-only.v2"] = C2_SHADOW_RISK_POLICY_ID
    balance_base: Decimal = Field(..., gt=0)
    risk_percent_per_entry: Decimal = Field(..., gt=0, le=1)
    risk_unit_usd: Decimal = Field(..., gt=0)
    max_campaign_risk_usd: Decimal = Field(..., gt=0)
    locked_at_utc: datetime
    authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    risk_authority: Literal[True] = True
    broker_execution_authority: Literal[False] = False

    @field_validator("balance_base", "risk_percent_per_entry", "risk_unit_usd", "max_campaign_risk_usd")
    @classmethod
    def _risk_amounts_are_durable(cls, value: Decimal, info: Any) -> Decimal:
        return _durable_numeric_v2(value, str(info.field_name))

    @field_validator("locked_at_utc")
    @classmethod
    def _locked_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "locked_at_utc")

    @model_validator(mode="after")
    def _authority_is_coherent(self) -> C2ShadowCampaignRiskLockV2:
        material = {
            "execution_campaign_id": self.execution_campaign_id,
            "tradeplan_id": self.tradeplan_id,
            "account_id": self.account_id,
            "account_snapshot_id": self.account_snapshot_id,
            "balance_base": self.balance_base,
            "risk_percent_per_entry": self.risk_percent_per_entry,
            "risk_unit_usd": self.risk_unit_usd,
            "max_campaign_risk_usd": self.max_campaign_risk_usd,
            "locked_at_utc": self.locked_at_utc,
            "policy_id": self.policy_id,
        }
        if self.authority_hash != canonical_hash_v1(material) or self.risk_lock_id != _identity(
            "5scr-c2-risk-lock-v2", material
        ):
            raise ValueError("C2 risk-lock authority integrity mismatch")
        if self.risk_percent_per_entry != C2_SHADOW_RISK_PERCENT_PER_ENTRY:
            raise ValueError("C2 risk lock must use the canonical 5% fractional per-entry policy")
        expected_risk_unit = self.balance_base * self.risk_percent_per_entry
        expected_risk_unit = _durable_numeric_v2(expected_risk_unit, "risk_unit_usd")
        if self.risk_unit_usd != expected_risk_unit:
            raise ValueError("C2 risk unit must equal closed balance times the fractional per-entry policy")
        expected_campaign_risk = self.risk_unit_usd * C2_SHADOW_MAX_ENTRIES
        expected_campaign_risk = _durable_numeric_v2(expected_campaign_risk, "max_campaign_risk_usd")
        if self.max_campaign_risk_usd != expected_campaign_risk:
            raise ValueError("C2 parent campaign risk lock must retain two-R campaign cap")
        return self


class C2ShadowDecimalSizingV2(FrozenC2Contract):
    allowed: bool
    reason_code: str = Field(..., pattern=r"^[A-Z0-9_]{3,120}$")
    risk_unit_usd: Decimal = Field(..., gt=0)
    effective_loss_per_lot: Decimal = Field(..., ge=0)
    raw_volume: Decimal = Field(..., ge=0)
    final_volume: Decimal = Field(..., ge=0)
    actual_planned_risk_usd: Decimal = Field(..., ge=0)

    @model_validator(mode="after")
    def _approved_risk_is_bounded(self) -> C2ShadowDecimalSizingV2:
        if self.allowed and (
            self.final_volume <= 0
            or self.effective_loss_per_lot <= 0
            or self.actual_planned_risk_usd != self.final_volume * self.effective_loss_per_lot
            or self.actual_planned_risk_usd > self.risk_unit_usd
        ):
            raise ValueError("approved C2 Decimal sizing is not an exact volume-derived one-R loss")
        return self


class C2ShadowRiskReservationV2(FrozenC2Contract):
    reservation_id: str = Field(..., pattern=r"^5scr-c2-reservation-v2:[0-9a-f]{32}$")
    execution_campaign_id: str = Field(..., pattern=r"^5scr-execution-campaign-v2:[0-9a-f]{32}$")
    risk_lock_id: str = Field(..., pattern=r"^5scr-c2-risk-lock-v2:[0-9a-f]{32}$")
    handoff_id: str = Field(..., pattern=r"^5scr-c2-handoff-v2:[0-9a-f]{32}$")
    tradeplan_id: str = Field(..., pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    executor_id: UUID
    account_id: str = Field(..., min_length=1, max_length=100)
    account_snapshot_id: str = Field(..., min_length=3, max_length=200)
    account_snapshot_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    symbol_capability_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    governance_evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    existing_risk_evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    broker_server: str = Field(..., min_length=1, max_length=200)
    canonical_symbol: str = Field(..., min_length=3, max_length=32)
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    direction: Direction
    entry_role: Literal["PARENT"] = "PARENT"
    state: Literal["RESERVED"] = "RESERVED"
    volume: Decimal = Field(..., gt=0)
    entry_price: Decimal = Field(..., gt=0)
    stop_loss: Decimal = Field(..., gt=0)
    take_profit: Decimal = Field(..., gt=0)
    risk_unit_usd: Decimal = Field(..., gt=0)
    reserved_risk_usd: Decimal = Field(..., gt=0)
    reserved_at_utc: datetime
    expires_at_utc: datetime
    authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    risk_authority: Literal[True] = True
    valid_for_execution: Literal[True] = True
    execution_mode: Literal["SHADOW"] = "SHADOW"
    broker_execution_authority: Literal[False] = False
    command_authority: Literal[False] = False

    @field_validator(
        "volume",
        "entry_price",
        "stop_loss",
        "take_profit",
        "risk_unit_usd",
        "reserved_risk_usd",
    )
    @classmethod
    def _risk_geometry_is_durable(cls, value: Decimal, info: Any) -> Decimal:
        return _durable_numeric_v2(value, str(info.field_name))

    @field_validator("reserved_at_utc", "expires_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _geometry_and_ttl_are_coherent(self) -> C2ShadowRiskReservationV2:
        if (
            not self.reserved_at_utc
            < self.expires_at_utc
            <= self.reserved_at_utc + timedelta(seconds=C2_SHADOW_MAX_TTL_SECONDS)
        ):
            raise ValueError("C2 reservation TTL is invalid")
        geometry = (
            self.stop_loss < self.entry_price < self.take_profit
            if self.direction == "BUY"
            else self.take_profit < self.entry_price < self.stop_loss
        )
        if not geometry or self.reserved_risk_usd > self.risk_unit_usd:
            raise ValueError("C2 reservation geometry/risk is invalid")
        material = {
            "execution_campaign_id": self.execution_campaign_id,
            "risk_lock_id": self.risk_lock_id,
            "handoff_id": self.handoff_id,
            "tradeplan_id": self.tradeplan_id,
            "executor_id": str(self.executor_id),
            "account_id": self.account_id,
            "account_snapshot_id": self.account_snapshot_id,
            "account_snapshot_hash": self.account_snapshot_hash,
            "symbol_capability_hash": self.symbol_capability_hash,
            "governance_evidence_hash": self.governance_evidence_hash,
            "existing_risk_evidence_hash": self.existing_risk_evidence_hash,
            "broker_server": self.broker_server,
            "symbol": self.canonical_symbol,
            "broker_symbol": self.broker_symbol,
            "direction": self.direction,
            "volume": self.volume,
            "entry": self.entry_price,
            "stop": self.stop_loss,
            "target": self.take_profit,
            "risk_unit_usd": self.risk_unit_usd,
            "reserved_risk_usd": self.reserved_risk_usd,
            "reserved_at_utc": self.reserved_at_utc,
            "expires_at_utc": self.expires_at_utc,
        }
        if self.authority_hash != canonical_hash_v1(material) or self.reservation_id != _identity(
            "5scr-c2-reservation-v2", material
        ):
            raise ValueError("C2 reservation authority integrity mismatch")
        return self


class C2ShadowExecutionCampaignV2(FrozenC2Contract):
    execution_campaign_id: str = Field(..., pattern=r"^5scr-execution-campaign-v2:[0-9a-f]{32}$")
    tradeplan_id: str = Field(..., pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    reservation_id: str = Field(..., pattern=r"^5scr-c2-reservation-v2:[0-9a-f]{32}$")
    account_id: str = Field(..., min_length=1, max_length=100)
    canonical_symbol: str = Field(..., min_length=3, max_length=32)
    direction: Direction
    state: Literal["PARENT_PENDING"] = "PARENT_PENDING"
    execution_mode: Literal["SHADOW"] = "SHADOW"
    opened_at_utc: datetime
    authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    risk_authority: Literal[True] = True
    broker_execution_authority: Literal[False] = False
    command_authority: Literal[False] = False

    @field_validator("opened_at_utc")
    @classmethod
    def _opened_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "opened_at_utc")

    @model_validator(mode="after")
    def _authority_is_coherent(self) -> C2ShadowExecutionCampaignV2:
        material = {
            "execution_campaign_id": self.execution_campaign_id,
            "tradeplan_id": self.tradeplan_id,
            "reservation_id": self.reservation_id,
            "account_id": self.account_id,
            "symbol": self.canonical_symbol,
            "direction": self.direction,
            "state": self.state,
            "opened_at_utc": self.opened_at_utc,
        }
        if self.authority_hash != canonical_hash_v1(material):
            raise ValueError("C2 execution-campaign authority integrity mismatch")
        return self


class C2ShadowFinalSignalV2(FrozenC2Contract):
    event: Literal["signal_json"] = "signal_json"
    schema_version: Literal["wolf15.strategy-5scr.final-signal.shadow.v2"] = C2_SHADOW_FINAL_SIGNAL_SCHEMA
    signal_id: str = Field(..., pattern=r"^5scr-signal-shadow-v2:[0-9a-f]{32}$")
    execution_campaign_id: str = Field(..., pattern=r"^5scr-execution-campaign-v2:[0-9a-f]{32}$")
    tradeplan_id: str = Field(..., pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    reservation_id: str = Field(..., pattern=r"^5scr-c2-reservation-v2:[0-9a-f]{32}$")
    handoff_id: str = Field(..., pattern=r"^5scr-c2-handoff-v2:[0-9a-f]{32}$")
    risk_lock_id: str = Field(..., pattern=r"^5scr-c2-risk-lock-v2:[0-9a-f]{32}$")
    account_id: str = Field(..., min_length=1, max_length=100)
    executor_id: UUID
    broker_server: str = Field(..., min_length=1, max_length=200)
    risk_snapshot_id: str = Field(..., min_length=3, max_length=200)
    account_snapshot_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    symbol_capability_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    governance_evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    existing_risk_evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    material_candidate_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    candidate_evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    canonical_symbol: str = Field(..., min_length=3, max_length=32)
    broker_symbol: str = Field(..., min_length=1, max_length=64)
    final_direction: Direction
    entry_role: Literal["PARENT"] = "PARENT"
    entry_price: Decimal = Field(..., gt=0)
    stop_loss: Decimal = Field(..., gt=0)
    take_profit: Decimal = Field(..., gt=0)
    reserved_volume: Decimal = Field(..., gt=0)
    issued_at_utc: datetime
    expires_at_utc: datetime
    signal_valid: Literal[True] = True
    is_final_signal: Literal[True] = True
    execution_valid_now: Literal[True] = True
    valid_for_execution: Literal[True] = True
    risk_authority: Literal[True] = True
    execution_mode: Literal["SHADOW"] = "SHADOW"
    broker_execution_authority: Literal[False] = False
    command_authority: Literal[False] = False
    delivery_authority: Literal[False] = False
    next_required_stage: Literal["C3_MANUAL_SHADOW_PROMOTION"] = "C3_MANUAL_SHADOW_PROMOTION"
    authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("entry_price", "stop_loss", "take_profit", "reserved_volume")
    @classmethod
    def _risk_geometry_is_durable(cls, value: Decimal, info: Any) -> Decimal:
        return _durable_numeric_v2(value, str(info.field_name))

    @field_validator("issued_at_utc", "expires_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _authority_is_coherent(self) -> C2ShadowFinalSignalV2:
        if (
            not self.issued_at_utc
            < self.expires_at_utc
            <= self.issued_at_utc + timedelta(seconds=C2_SHADOW_MAX_TTL_SECONDS)
        ):
            raise ValueError("C2 final-signal TTL is invalid")
        geometry = (
            self.stop_loss < self.entry_price < self.take_profit
            if self.final_direction == "BUY"
            else self.take_profit < self.entry_price < self.stop_loss
        )
        if not geometry:
            raise ValueError("C2 final-signal geometry is invalid")
        material = {
            "execution_campaign_id": self.execution_campaign_id,
            "tradeplan_id": self.tradeplan_id,
            "reservation_id": self.reservation_id,
            "handoff_id": self.handoff_id,
            "risk_lock_id": self.risk_lock_id,
            "account_id": self.account_id,
            "executor_id": str(self.executor_id),
            "broker_server": self.broker_server,
            "risk_snapshot_id": self.risk_snapshot_id,
            "account_snapshot_hash": self.account_snapshot_hash,
            "symbol_capability_hash": self.symbol_capability_hash,
            "governance_evidence_hash": self.governance_evidence_hash,
            "existing_risk_evidence_hash": self.existing_risk_evidence_hash,
            "material_candidate_hash": self.material_candidate_hash,
            "candidate_evidence_hash": self.candidate_evidence_hash,
            "symbol": self.canonical_symbol,
            "broker_symbol": self.broker_symbol,
            "direction": self.final_direction,
            "entry_role": self.entry_role,
            "entry": self.entry_price,
            "stop": self.stop_loss,
            "target": self.take_profit,
            "volume": self.reserved_volume,
            "issued_at_utc": self.issued_at_utc,
            "expires_at_utc": self.expires_at_utc,
        }
        if self.authority_hash != canonical_hash_v1(material) or self.signal_id != _identity(
            "5scr-signal-shadow-v2", material
        ):
            raise ValueError("C2 final-signal authority integrity mismatch")
        return self


class C2ShadowEvaluationV2(FrozenC2Contract):
    evaluation_id: str = Field(..., pattern=r"^5scr-c2-eval-v2:[0-9a-f]{32}$")
    evaluation_sequence: int = Field(..., ge=1)
    source_request_id: str = Field(..., min_length=1, max_length=240)
    tradeplan_id: str = Field(..., pattern=r"^5scr-tradeplan-v2:[0-9a-f]{32}$")
    material_candidate_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    account_id: str = Field(..., min_length=1, max_length=100)
    executor_id: UUID
    decision_at_utc: datetime
    decision: PersistedC2Decision
    reason_code: str = Field(..., pattern=r"^[A-Z0-9_]{3,120}$")
    evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    material_evaluation_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    result_execution_campaign_id: str | None = Field(default=None, pattern=r"^5scr-execution-campaign-v2:[0-9a-f]{32}$")
    result_reservation_id: str | None = Field(default=None, pattern=r"^5scr-c2-reservation-v2:[0-9a-f]{32}$")
    rule_version: Literal["5scr.candidate-c2-shadow.v2"] = C2_SHADOW_RULE_VERSION
    execution_authority: Literal[False] = False

    @field_validator("decision_at_utc")
    @classmethod
    def _decision_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "decision_at_utc")

    @model_validator(mode="after")
    def _result_shape_is_coherent(self) -> C2ShadowEvaluationV2:
        linked = self.result_execution_campaign_id is not None and self.result_reservation_id is not None
        if (self.decision == "APPROVED") != linked:
            raise ValueError("only APPROVED C2 evaluation may link campaign and reservation")
        material = canonical_hash_v1(
            {
                "tradeplan_id": self.tradeplan_id,
                "candidate_material_hash": self.material_candidate_hash,
                "account_id": self.account_id,
                "executor_id": str(self.executor_id),
                "decision": self.decision,
                "reason": self.reason_code,
                "campaign_id": self.result_execution_campaign_id,
                "reservation_id": self.result_reservation_id,
                "rule_version": self.rule_version,
            }
        )
        identity = {
            "source_request_id": self.source_request_id,
            "sequence": self.evaluation_sequence,
            "decision_at_utc": self.decision_at_utc,
            "evidence_hash": self.evidence_hash,
            "material_hash": material,
        }
        if self.material_evaluation_hash != material or self.evaluation_id != _identity("5scr-c2-eval-v2", identity):
            raise ValueError("C2 evaluation identity/material integrity mismatch")
        return self


class C2ShadowAuthorityBundleV2(FrozenC2Contract):
    handoff: CandidateC2ShadowHandoffV2
    risk_lock: C2ShadowCampaignRiskLockV2
    reservation: C2ShadowRiskReservationV2
    execution_campaign: C2ShadowExecutionCampaignV2
    final_signal: C2ShadowFinalSignalV2

    @model_validator(mode="after")
    def _atomic_scope_is_coherent(self) -> C2ShadowAuthorityBundleV2:
        campaign = self.execution_campaign.execution_campaign_id
        reservation = self.reservation.reservation_id
        if not (
            self.handoff.tradeplan_id
            == self.risk_lock.tradeplan_id
            == self.reservation.tradeplan_id
            == self.execution_campaign.tradeplan_id
            == self.final_signal.tradeplan_id
        ):
            raise ValueError("C2 authority bundle tradeplan scope mismatch")
        if not (
            campaign
            == self.risk_lock.execution_campaign_id
            == self.reservation.execution_campaign_id
            == self.final_signal.execution_campaign_id
        ):
            raise ValueError("C2 authority bundle campaign scope mismatch")
        if not (reservation == self.execution_campaign.reservation_id == self.final_signal.reservation_id):
            raise ValueError("C2 authority bundle reservation scope mismatch")
        if self.reservation.handoff_id != self.handoff.handoff_id:
            raise ValueError("C2 authority bundle handoff scope mismatch")
        if self.reservation.risk_lock_id != self.risk_lock.risk_lock_id:
            raise ValueError("C2 authority bundle risk-lock scope mismatch")
        if not (
            self.handoff.symbol
            == self.reservation.canonical_symbol
            == self.execution_campaign.canonical_symbol
            == self.final_signal.canonical_symbol
        ) or not (
            self.handoff.direction
            == self.reservation.direction
            == self.execution_campaign.direction
            == self.final_signal.final_direction
        ):
            raise ValueError("C2 authority bundle symbol/direction scope mismatch")
        if not (
            self.risk_lock.account_id
            == self.reservation.account_id
            == self.execution_campaign.account_id
            == self.handoff.account_id
            == self.final_signal.account_id
        ) or not (
            self.handoff.account_snapshot_id
            == self.risk_lock.account_snapshot_id
            == self.reservation.account_snapshot_id
            == self.final_signal.risk_snapshot_id
        ):
            raise ValueError("C2 authority bundle account/snapshot scope mismatch")
        if not (self.handoff.executor_id == self.reservation.executor_id == self.final_signal.executor_id) or not (
            self.handoff.broker_server == self.reservation.broker_server == self.final_signal.broker_server
        ):
            raise ValueError("C2 authority bundle executor/broker scope mismatch")
        if not (
            self.handoff.handoff_id == self.final_signal.handoff_id
            and self.risk_lock.risk_lock_id == self.final_signal.risk_lock_id
            and self.handoff.material_candidate_hash == self.final_signal.material_candidate_hash
            and self.handoff.candidate_evidence_hash == self.final_signal.candidate_evidence_hash
            and self.handoff.account_snapshot_hash
            == self.reservation.account_snapshot_hash
            == self.final_signal.account_snapshot_hash
            and self.handoff.symbol_capability_hash
            == self.reservation.symbol_capability_hash
            == self.final_signal.symbol_capability_hash
            and self.handoff.governance_evidence_hash
            == self.reservation.governance_evidence_hash
            == self.final_signal.governance_evidence_hash
            and self.handoff.existing_risk_evidence_hash
            == self.reservation.existing_risk_evidence_hash
            == self.final_signal.existing_risk_evidence_hash
            and self.handoff.risk_policy_id == self.risk_lock.policy_id
        ):
            raise ValueError("C2 authority bundle lineage scope mismatch")
        if not (
            self.handoff.accepted_at_utc
            == self.risk_lock.locked_at_utc
            == self.reservation.reserved_at_utc
            == self.execution_campaign.opened_at_utc
            == self.final_signal.issued_at_utc
        ):
            raise ValueError("C2 authority bundle formation clock mismatch")
        if not (
            self.handoff.candidate_price == self.reservation.entry_price == self.final_signal.entry_price
            and self.handoff.stop_loss == self.reservation.stop_loss == self.final_signal.stop_loss
            and self.handoff.take_profit == self.reservation.take_profit == self.final_signal.take_profit
            and self.reservation.volume == self.final_signal.reserved_volume
        ):
            raise ValueError("C2 authority bundle risk geometry mismatch")
        if (
            self.reservation.risk_unit_usd != self.risk_lock.risk_unit_usd
            or self.reservation.reserved_risk_usd > self.risk_lock.risk_unit_usd
        ):
            raise ValueError("C2 authority bundle reservation/risk-lock budget mismatch")
        expected_campaign = _identity(
            "5scr-execution-campaign-v2",
            {
                "tradeplan_id": self.handoff.tradeplan_id,
                "candidate_sequence": self.handoff.candidate_sequence,
                "candidate_revision": self.handoff.candidate_revision,
                "account_id": self.reservation.account_id,
                "policy_id": self.risk_lock.policy_id,
            },
        )
        if self.execution_campaign.execution_campaign_id != expected_campaign:
            raise ValueError("C2 execution-campaign occurrence identity mismatch")
        return self


class CandidateC2ShadowReductionResultV2(FrozenC2Contract):
    decision: C2Decision
    reason_code: str = Field(..., pattern=r"^[A-Z0-9_]{3,120}$")
    evaluation: C2ShadowEvaluationV2 | None = None
    authority_bundle: C2ShadowAuthorityBundleV2 | None = None

    @model_validator(mode="after")
    def _shape_is_coherent(self) -> CandidateC2ShadowReductionResultV2:
        if self.decision == "APPROVED":
            if self.evaluation is None or self.evaluation.decision != "APPROVED" or self.authority_bundle is None:
                raise ValueError("APPROVED C2 result requires evaluation and atomic authority bundle")
        elif self.decision in {"WAIT", "REJECTED"}:
            if (
                self.evaluation is None
                or self.evaluation.decision != self.decision
                or self.authority_bundle is not None
            ):
                raise ValueError("WAIT/REJECTED C2 result requires only its persisted evaluation")
        elif self.authority_bundle is not None and self.decision != "DUPLICATE":
            raise ValueError("only DUPLICATE may return existing C2 authority")
        return self


__all__ = [
    "C2Decision",
    "C2_SHADOW_FINAL_SIGNAL_SCHEMA",
    "C2_SHADOW_GOVERNANCE_MAX_AGE_SECONDS",
    "C2_SHADOW_MAX_ENTRIES",
    "C2_SHADOW_MAX_TOTAL_OPEN_RISK_PERCENT",
    "C2_SHADOW_MAX_TTL_SECONDS",
    "C2_SHADOW_RISK_PERCENT_PER_ENTRY",
    "C2_SHADOW_RISK_POLICY_ID",
    "C2_SHADOW_RULE_VERSION",
    "C2_SHADOW_SNAPSHOT_MAX_AGE_SECONDS",
    "C2ShadowAuthorityBundleV2",
    "C2ShadowCampaignRiskLockV2",
    "C2ShadowDecimalSizingV2",
    "C2ShadowEvaluationV2",
    "C2ShadowExecutionCampaignV2",
    "C2ShadowExistingRiskEvidenceV2",
    "C2ShadowFinalSignalV2",
    "C2ShadowGovernanceEvidenceV2",
    "C2ShadowRiskReservationV2",
    "CandidateC2ShadowBuildEvidenceV2",
    "CandidateC2ShadowHandoffV2",
    "CandidateC2ShadowReductionResultV2",
    "account_snapshot_authority_hash_v2",
    "candidate_c2_shadow_handoff_authority_material_v2",
    "candidate_c2_shadow_handoff_identity_material_v2",
    "c2_shadow_existing_risk_evidence_v2",
    "c2_shadow_governance_evidence_v2",
    "canonical_tradeplan_numeric_v2",
    "symbol_capability_authority_hash_v2",
    "snapshot_candidate_c2_build_evidence_v2",
]
