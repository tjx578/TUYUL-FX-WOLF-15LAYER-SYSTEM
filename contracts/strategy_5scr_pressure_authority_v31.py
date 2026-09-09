"""SSOT 10.5 direction gate; this never grants hypothesis or execution authority.

Policy approval is caller-supplied evidence, not authenticated by this module.
The selected source does not resolve the independent-route/conflict table, so
that route stays denied. Legacy pressure authorities are not converted here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RULE_VERSION = "5scr.pressure-direction-gate.v3.1"
Direction = Literal["BUY", "SELL"]
HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"


class FrozenPressureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def normalize_values(cls, value: object) -> object:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("pressure timestamps must include a UTC offset")
            return value.astimezone(UTC)
        if isinstance(value, str) and not value.strip():
            raise ValueError("blank identifiers are not evidence")
        return value


class PressurePolicyBindingV31(FrozenPressureModel):
    """Explicit binding; UNBOUND is useful evidence, never an active policy."""

    approval_state: Literal["UNBOUND", "APPROVED", "REVOKED"]
    policy_id: str | None = Field(default=None, min_length=1)
    policy_digest: str | None = Field(default=None, pattern=HASH_PATTERN)
    approved_at_utc: datetime | None = None
    valid_until_utc: datetime | None = None

    @model_validator(mode="after")
    def approved_shape(self) -> Self:
        if self.approval_state == "APPROVED" and any(
            value is None for value in (self.policy_id, self.policy_digest, self.approved_at_utc, self.valid_until_utc)
        ):
            raise ValueError("approved policy requires explicit identity, digest and validity")
        if self.approved_at_utc and self.valid_until_utc and self.valid_until_utc <= self.approved_at_utc:
            raise ValueError("policy validity must follow approval")
        return self


class PressureAuthorityV31(FrozenPressureModel):
    """A versioned producer snapshot, not an inferred legacy LOCKED contract."""

    schema_version: Literal["5scr.pressure-authority.v3.1"] = "5scr.pressure-authority.v3.1"
    symbol: str = Field(..., pattern=r"^[A-Z0-9._-]{3,32}$")
    source_event_ids: tuple[str, ...] = Field(..., min_length=1)
    pressure_authority_mode: Literal["RADAR_ONLY", "CONSOLIDATED_DIRECTION_CONTRACT"]
    pressure_contract_status: Literal["OPEN", "LOCKED", "TRANSITION_PENDING", "INVALIDATED", "EXPIRED"]
    pressure_contract_version: str = Field(..., min_length=1)
    pressure_contract_invalidated_at: datetime | None
    observed_at_utc: datetime
    valid_until_utc: datetime
    raw_direction: Direction | None
    candidate_direction: Direction | None
    watch_direction: Direction | None
    block_direction: Direction | None
    direction_lineage_alignment: Literal["ALIGNED", "CONFLICT", "UNAVAILABLE"]
    pressure_consensus_status: Literal["BUY", "SELL", "CONFLICT", "INCOMPLETE", "STALE"]
    contract_direction: Direction | None = None
    formal_transition_event_id: str | None = None
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def snapshot_shape(self) -> Self:
        if self.source_event_ids != tuple(sorted(set(self.source_event_ids))) or any(
            not value.strip() for value in self.source_event_ids
        ):
            raise ValueError("source IDs must be nonblank, unique and sorted")
        directions = (self.raw_direction, self.candidate_direction, self.watch_direction, self.block_direction)
        known = {direction for direction in directions if direction is not None}
        expected = "CONFLICT" if len(known) > 1 else "UNAVAILABLE" if None in directions else "ALIGNED"
        if self.direction_lineage_alignment != expected:
            raise ValueError("declared alignment disagrees with source directions")
        if (
            expected == "ALIGNED"
            and self.pressure_consensus_status in {"BUY", "SELL"}
            and self.pressure_consensus_status != self.raw_direction
        ):
            raise ValueError("pressure consensus disagrees with aligned lineage")
        if self.valid_until_utc <= self.observed_at_utc:
            raise ValueError("source validity must follow observation")
        if self.pressure_contract_status == "INVALIDATED" and self.pressure_contract_invalidated_at is None:
            raise ValueError("invalidated contract requires invalidation timestamp")
        if self.pressure_authority_mode == "RADAR_ONLY":
            if self.contract_direction is not None or self.formal_transition_event_id is not None:
                raise ValueError("radar evidence cannot claim a consolidated direction transition")
            if self.pressure_contract_status == "LOCKED":
                raise ValueError("radar evidence cannot claim LOCKED")
        elif self.pressure_contract_status == "LOCKED":
            if self.contract_direction is None or self.formal_transition_event_id not in self.source_event_ids:
                raise ValueError("LOCKED requires explicit direction and source-bound formal transition")
        return self


class PressureDirectionDecisionV31(FrozenPressureModel):
    rule_version: Literal["5scr.pressure-direction-gate.v3.1"] = RULE_VERSION
    evidence_hash: str = Field(..., pattern=HASH_PATTERN)
    evaluated_at_utc: datetime
    requested_direction: Direction
    pressure_direction_gate_passed: bool
    reason_code: str
    separate_route_gate_passed: Literal[False] = False
    separate_route_reason: Literal["SEPARATE_ROUTE_POLICY_UNRESOLVED"] = "SEPARATE_ROUTE_POLICY_UNRESOLVED"
    hypothesis_authority: Literal[False] = False
    risk_authority: Literal[False] = False
    execution_authority: Literal[False] = False


def evaluate_pressure_direction(
    authority: PressureAuthorityV31,
    *,
    policy: PressurePolicyBindingV31 | None,
    requested_direction: Direction,
    decision_at_utc: datetime,
) -> PressureDirectionDecisionV31:
    """Evaluate one prerequisite; callers still owe every SSOT 10.2 condition."""
    # Revalidate instances to reject model_construct/model_copy bypasses.
    source = PressureAuthorityV31.model_validate(authority.model_dump(mode="json"))
    bound = PressurePolicyBindingV31.model_validate(policy.model_dump(mode="json")) if policy else None
    if decision_at_utc.tzinfo is None or decision_at_utc.utcoffset() is None:
        raise ValueError("decision time must include a UTC offset")
    now = decision_at_utc.astimezone(UTC)
    if requested_direction not in {"BUY", "SELL"}:
        raise ValueError("requested direction must be BUY or SELL")
    reason = "PRESSURE_DIRECTION_GATE_PASSED"
    if bound is None or bound.approval_state != "APPROVED":
        reason = "PRESSURE_POLICY_UNBOUND_OR_REVOKED"
    elif not bound.approved_at_utc <= now < bound.valid_until_utc:
        reason = "PRESSURE_POLICY_NOT_CURRENT"
    elif source.observed_at_utc > now:
        reason = "FUTURE_PRESSURE_EVIDENCE"
    elif source.pressure_contract_invalidated_at is not None:
        reason = (
            "FUTURE_INVALIDATION_EVIDENCE" if source.pressure_contract_invalidated_at > now else "CONTRACT_INVALIDATED"
        )
    elif now >= source.valid_until_utc or source.pressure_contract_status == "EXPIRED":
        reason = "PRESSURE_EVIDENCE_EXPIRED"
    elif source.direction_lineage_alignment != "ALIGNED":
        reason = "PRESSURE_DIRECTION_LINEAGE_" + source.direction_lineage_alignment
    elif source.pressure_consensus_status not in {"BUY", "SELL"}:
        reason = "PRESSURE_CONSENSUS_UNAVAILABLE"
    elif source.pressure_contract_status in {"TRANSITION_PENDING", "INVALIDATED"}:
        reason = "PRESSURE_CONTRACT_NOT_OPEN"
    elif source.pressure_authority_mode == "CONSOLIDATED_DIRECTION_CONTRACT" and (
        source.pressure_contract_status != "LOCKED" or source.contract_direction != requested_direction
    ):
        reason = "CONSOLIDATED_DIRECTION_NOT_AUTHORIZED"
    elif requested_direction != source.pressure_consensus_status:
        reason = "OPPOSITE_PRESSURE_DIRECTION_NOT_AUTHORIZED"
    payload = {
        "rule_version": RULE_VERSION,
        "authority": source.model_dump(mode="json"),
        "policy": bound.model_dump(mode="json") if bound else None,
        "requested_direction": requested_direction,
        "decision_at_utc": now.isoformat(),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return PressureDirectionDecisionV31(
        evidence_hash="sha256:" + digest,
        evaluated_at_utc=now,
        requested_direction=requested_direction,
        pressure_direction_gate_passed=reason == "PRESSURE_DIRECTION_GATE_PASSED",
        reason_code=reason,
    )
