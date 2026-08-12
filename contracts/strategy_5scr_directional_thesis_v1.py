"""Shadow-only contracts for immutable 5S-CR directional theses.

P4 answers only whether one active ContextEpoch has enough ordered H1/M15
closed-candle authority to form a legal BUY or SELL thesis.  These contracts
carry no entry, target, stop, risk, command, or broker authority.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DIRECTIONAL_THESIS_RULE_VERSION = "5scr.directional-thesis.v1"
_HASH_SENTINEL = "sha256:" + ("0" * 64)
Direction = Literal["BUY", "SELL"]
DirectionDomain = Literal["BUY_ONLY", "SELL_ONLY", "BOTH_CONDITIONAL", "UNRESOLVED", "EMPTY"]
ThesisState = Literal["ACTIVE", "INVALIDATED", "TERMINAL"]
PressureAuthorityMode = Literal["RADAR_ONLY", "CONSOLIDATED_DIRECTION_CONTRACT"]
PressureContractStatus = Literal[
    "RADAR_ONLY",
    "LOCKED",
    "UNRESOLVED",
    "CONFLICT",
    "EXPIRED",
    "INVALIDATED",
    "TRANSITION_PENDING",
]
M15CompletionKind = Literal["ACCEPTANCE", "FAILED_RECLAIM", "RETEST"]


def classify_m15_completion(
    direction: Direction,
    completion: ClosedCandleAuthorityRefV1,
    break_level: float,
) -> M15CompletionKind | None:
    """Classify one closed completion candle using the canonical P4 rule."""

    if direction == "BUY":
        closes_beyond = completion.close > break_level
        retest = completion.low <= break_level and closes_beyond
        failed_reclaim = completion.open <= break_level < completion.close
    else:
        closes_beyond = completion.close < break_level
        retest = completion.high >= break_level and closes_beyond
        failed_reclaim = completion.open >= break_level > completion.close
    if not closes_beyond:
        return None
    return "FAILED_RECLAIM" if failed_reclaim else ("RETEST" if retest else "ACCEPTANCE")


class FrozenThesisContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _material_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


class ClosedCandleAuthorityRefV1(FrozenThesisContract):
    """Frozen content and provenance for one authoritative closed candle."""

    candle_evidence_id: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    material_candle_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    source_content_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    canonical_row_id: int | None = Field(default=None, ge=1)
    selected_raw_candle_id: int | None = Field(default=None, ge=1)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    timeframe: Literal["H1", "M15"]
    open_time_utc: datetime
    close_time_utc: datetime
    open: float = Field(..., gt=0)
    high: float = Field(..., gt=0)
    low: float = Field(..., gt=0)
    close: float = Field(..., gt=0)
    volume: float = Field(default=0, ge=0)
    tick_count: int = Field(default=0, ge=0)
    provider: str = Field(..., min_length=2, max_length=100)
    feed: str = Field(..., min_length=1, max_length=100)
    provider_timestamp_semantics: Literal["PERIOD_OPEN", "PERIOD_END", "CANONICAL_WINDOW"]
    selection_policy: str = Field(..., min_length=3, max_length=100)
    selection_rank: int = Field(..., ge=0)
    is_closed: Literal[True] = True
    structural_authority: Literal[True] = True

    @field_validator("open_time_utc", "close_time_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        resolved = _utc(value, str(info.field_name))
        assert resolved is not None
        return resolved

    @field_validator("open", "high", "low", "close", "volume")
    @classmethod
    def _numbers_are_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("candle numbers must be finite")
        return value

    @model_validator(mode="after")
    def _candle_is_coherent(self) -> ClosedCandleAuthorityRefV1:
        expected = timedelta(hours=1) if self.timeframe == "H1" else timedelta(minutes=15)
        if self.close_time_utc - self.open_time_utc != expected:
            raise ValueError(f"{self.timeframe} authority window must be exactly {expected}")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("candle high is inconsistent with OHLC")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("candle low is inconsistent with OHLC")
        return self


class PressureDirectionAuthorityV1(FrozenThesisContract):
    """Explicit pressure authority; Lifecycle V2 direction is never inferred as LOCKED."""

    mode: PressureAuthorityMode
    contract_status: PressureContractStatus
    raw_pressure_direction: Direction | None = None
    contract_direction: Direction | None = None
    source_event_ids: tuple[str, ...]
    formal_transition_event_id: str | None = Field(default=None, max_length=240)
    authority_hash: str = Field(default=_HASH_SENTINEL, pattern=r"^sha256:[0-9a-f]{64}$")
    rule_version: str = Field(..., min_length=3, max_length=100)
    observed_at_utc: datetime
    valid_until_utc: datetime | None = None
    execution_authority: Literal[False] = False

    @field_validator("observed_at_utc", "valid_until_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime | None, info: Any) -> datetime | None:
        return _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _authority_shape_is_valid(self) -> PressureDirectionAuthorityV1:
        if not self.source_event_ids or self.source_event_ids != tuple(sorted(set(self.source_event_ids))):
            raise ValueError("pressure source_event_ids must be non-empty, sorted, and unique")
        if self.valid_until_utc is not None and self.valid_until_utc < self.observed_at_utc:
            raise ValueError("pressure validity cannot precede observation")
        if self.mode == "RADAR_ONLY":
            if self.contract_status != "RADAR_ONLY" or self.contract_direction is not None:
                raise ValueError("RADAR_ONLY cannot claim a locked contract direction")
            if self.formal_transition_event_id is not None:
                raise ValueError("RADAR_ONLY cannot claim a formal direction transition")
        elif self.contract_status == "LOCKED":
            if self.contract_direction is None:
                raise ValueError("LOCKED consolidated authority requires contract_direction")
            if self.formal_transition_event_id is None or self.formal_transition_event_id not in self.source_event_ids:
                raise ValueError("LOCKED consolidated authority requires its formal transition event")
        elif self.contract_direction is not None:
            raise ValueError("non-LOCKED consolidated authority cannot carry contract_direction")
        material_hash = pressure_authority_material_hash(self)
        if self.authority_hash not in {_HASH_SENTINEL, material_hash}:
            raise ValueError("pressure authority_hash does not match material authority")
        object.__setattr__(self, "authority_hash", material_hash)
        return self


class RouteDirectionAuthorizationV1(FrozenThesisContract):
    """Typed route-to-direction authorization bound to one material ContextEpoch."""

    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    material_context_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    selected_route: str = Field(..., min_length=2, max_length=120)
    strategy_direction: Direction
    source_event_ids: tuple[str, ...]
    authorization_hash: str = Field(default=_HASH_SENTINEL, pattern=r"^sha256:[0-9a-f]{64}$")
    rule_version: str = Field(..., min_length=3, max_length=100)
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _source_ids_are_canonical(self) -> RouteDirectionAuthorizationV1:
        if not self.source_event_ids or self.source_event_ids != tuple(sorted(set(self.source_event_ids))):
            raise ValueError("route source_event_ids must be non-empty, sorted, and unique")
        material_hash = route_authorization_material_hash(self)
        if self.authorization_hash not in {_HASH_SENTINEL, material_hash}:
            raise ValueError("route authorization_hash does not match material authorization")
        object.__setattr__(self, "authorization_hash", material_hash)
        return self


def pressure_authority_material_hash(authority: PressureDirectionAuthorityV1) -> str:
    """Fingerprint authority semantics without delivery or observation churn."""

    payload: dict[str, Any] = {
        "mode": authority.mode,
        "contract_status": authority.contract_status,
        "rule_version": authority.rule_version,
    }
    if authority.mode == "RADAR_ONLY":
        payload["raw_pressure_direction"] = authority.raw_pressure_direction
    else:
        # Once a formal consolidated contract exists, raw radar movement is
        # lineage-only.  It must not manufacture a second authority identity.
        payload["contract_direction"] = authority.contract_direction
        payload["formal_transition_event_id"] = authority.formal_transition_event_id
    return _material_hash(payload)


def route_authorization_material_hash(authorization: RouteDirectionAuthorizationV1) -> str:
    """Fingerprint route semantics bound to one immutable ContextEpoch."""

    return _material_hash(
        {
            "context_epoch_id": authorization.context_epoch_id,
            "material_context_hash": authorization.material_context_hash,
            "selected_route": authorization.selected_route,
            "strategy_direction": authorization.strategy_direction,
            "rule_version": authorization.rule_version,
        }
    )


class DirectionalThesisEvidenceV1(FrozenThesisContract):
    """Candidate ordered structural evidence to be recomputed, not trusted as booleans."""

    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    decision_at_utc: datetime
    strategy_direction: Direction
    selected_route: str = Field(..., min_length=2, max_length=120)
    pressure_authority: PressureDirectionAuthorityV1
    route_authorization: RouteDirectionAuthorizationV1 | None = None
    h1_candles: tuple[ClosedCandleAuthorityRefV1, ...]
    m15_candles: tuple[ClosedCandleAuthorityRefV1, ...]
    source_request_id: str | None = Field(default=None, max_length=240)
    execution_authority: Literal[False] = False

    @field_validator("decision_at_utc")
    @classmethod
    def _decision_is_utc(cls, value: datetime) -> datetime:
        resolved = _utc(value, "decision_at_utc")
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _evidence_scope_and_order_are_valid(self) -> DirectionalThesisEvidenceV1:
        for timeframe, candles in (("H1", self.h1_candles), ("M15", self.m15_candles)):
            identities = tuple(item.candle_evidence_id for item in candles)
            times = tuple(item.close_time_utc for item in candles)
            if identities != tuple(dict.fromkeys(identities)):
                raise ValueError(f"{timeframe} candle identities must be unique")
            if times != tuple(sorted(times)):
                raise ValueError(f"{timeframe} candles must be ordered by close time")
            if any(item.timeframe != timeframe or item.symbol != self.symbol for item in candles):
                raise ValueError(f"{timeframe} candle scope mismatch")
            if any(item.close_time_utc > self.decision_at_utc for item in candles):
                raise ValueError("future candle leakage is forbidden")
        return self


class H1StructureProofV1(FrozenThesisContract):
    h1_proof_id: str = Field(..., pattern=r"^5scr-h1-proof:[0-9a-f]{32}$")
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    strategy_direction: Direction
    structure_event: Literal["BOS", "CHOCH", "CONTINUATION"]
    anchor_candle: ClosedCandleAuthorityRefV1
    confirmation_candle: ClosedCandleAuthorityRefV1
    reference_level: float = Field(..., gt=0)
    confirmation_close: float = Field(..., gt=0)
    confirmed_at_utc: datetime
    decision_at_utc: datetime
    coverage_start_at_utc: datetime
    coverage_end_at_utc: datetime
    source_candle_ids: tuple[str, ...]
    source_content_hashes: tuple[str, ...]
    coverage_complete: Literal[True] = True
    structural_authority: Literal[True] = True
    material_proof_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    semantic_dedupe_key: str = Field(..., min_length=10, max_length=500)
    rule_version: Literal["5scr.directional-thesis.v1"] = DIRECTIONAL_THESIS_RULE_VERSION
    execution_authority: Literal[False] = False

    @field_validator("confirmed_at_utc", "decision_at_utc", "coverage_start_at_utc", "coverage_end_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        resolved = _utc(value, str(info.field_name))
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _proof_is_ordered(self) -> H1StructureProofV1:
        if self.anchor_candle.timeframe != "H1" or self.confirmation_candle.timeframe != "H1":
            raise ValueError("H1 proof requires H1 candles")
        if self.anchor_candle.symbol != self.symbol or self.confirmation_candle.symbol != self.symbol:
            raise ValueError("H1 proof symbol mismatch")
        if not self.anchor_candle.close_time_utc < self.confirmation_candle.close_time_utc:
            raise ValueError("H1 anchor must precede confirmation")
        if self.anchor_candle.close_time_utc != self.confirmation_candle.open_time_utc:
            raise ValueError("H1 proof coverage contains a candle gap")
        if self.confirmed_at_utc != self.confirmation_candle.close_time_utc:
            raise ValueError("H1 confirmed_at must equal confirmation close")
        if self.confirmation_close != self.confirmation_candle.close:
            raise ValueError("H1 confirmation_close must equal the frozen candle close")
        expected_level = self.anchor_candle.high if self.strategy_direction == "BUY" else self.anchor_candle.low
        if self.reference_level != expected_level:
            raise ValueError("H1 reference_level does not match the directional anchor")
        directional_break = (
            self.confirmation_candle.close > self.reference_level
            if self.strategy_direction == "BUY"
            else self.confirmation_candle.close < self.reference_level
        )
        if not directional_break:
            raise ValueError("H1 confirmation does not close through the directional reference")
        if self.coverage_start_at_utc != self.anchor_candle.open_time_utc:
            raise ValueError("H1 coverage must begin at the frozen anchor")
        if self.coverage_end_at_utc != self.confirmed_at_utc:
            raise ValueError("H1 coverage must end at the frozen confirmation")
        if self.confirmed_at_utc > self.decision_at_utc:
            raise ValueError("H1 proof is not closed by decision time")
        if self.source_candle_ids != tuple(
            item.candle_evidence_id for item in (self.anchor_candle, self.confirmation_candle)
        ):
            raise ValueError("H1 source candle IDs do not match proof")
        if self.source_content_hashes != tuple(
            item.source_content_hash for item in (self.anchor_candle, self.confirmation_candle)
        ):
            raise ValueError("H1 source hashes do not match proof")
        return self


class M15StructuralProofV1(FrozenThesisContract):
    m15_proof_id: str = Field(..., pattern=r"^5scr-m15-proof:[0-9a-f]{32}$")
    h1_proof_id: str = Field(..., pattern=r"^5scr-h1-proof:[0-9a-f]{32}$")
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    strategy_direction: Direction
    reference_candle: ClosedCandleAuthorityRefV1
    break_candle: ClosedCandleAuthorityRefV1
    completion_candle: ClosedCandleAuthorityRefV1
    break_level: float = Field(..., gt=0)
    h1_confirmed_at_utc: datetime
    break_close_at_utc: datetime
    completed_at_utc: datetime
    completion_kind: M15CompletionKind
    decision_at_utc: datetime
    coverage_start_at_utc: datetime
    coverage_end_at_utc: datetime
    source_candle_ids: tuple[str, ...]
    source_content_hashes: tuple[str, ...]
    coverage_complete: Literal[True] = True
    structural_authority: Literal[True] = True
    ordering_valid: Literal[True] = True
    material_proof_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    semantic_dedupe_key: str = Field(..., min_length=10, max_length=500)
    rule_version: Literal["5scr.directional-thesis.v1"] = DIRECTIONAL_THESIS_RULE_VERSION
    execution_authority: Literal[False] = False

    @field_validator(
        "h1_confirmed_at_utc",
        "break_close_at_utc",
        "completed_at_utc",
        "decision_at_utc",
        "coverage_start_at_utc",
        "coverage_end_at_utc",
    )
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        resolved = _utc(value, str(info.field_name))
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _proof_is_ordered(self) -> M15StructuralProofV1:
        candles = (self.reference_candle, self.break_candle, self.completion_candle)
        if any(item.timeframe != "M15" or item.symbol != self.symbol for item in candles):
            raise ValueError("M15 proof candle scope mismatch")
        if not self.h1_confirmed_at_utc <= self.break_close_at_utc < self.completed_at_utc <= self.decision_at_utc:
            raise ValueError("ORDERED_PROOF_INVALID")
        if self.reference_candle.close_time_utc != self.break_candle.open_time_utc:
            raise ValueError("M15 reference-to-break coverage contains a candle gap")
        if self.break_candle.close_time_utc != self.completion_candle.open_time_utc:
            raise ValueError("M15 break-to-completion coverage contains a candle gap")
        if self.break_close_at_utc != self.break_candle.close_time_utc:
            raise ValueError("M15 break clock mismatch")
        if self.completed_at_utc != self.completion_candle.close_time_utc:
            raise ValueError("M15 completion clock mismatch")
        expected_level = self.reference_candle.high if self.strategy_direction == "BUY" else self.reference_candle.low
        if self.break_level != expected_level:
            raise ValueError("M15 break_level does not match the directional reference")
        directional_break = (
            self.break_candle.close > self.break_level
            if self.strategy_direction == "BUY"
            else self.break_candle.close < self.break_level
        )
        if not directional_break:
            raise ValueError("M15 break candle does not close through the directional reference")
        expected_kind = classify_m15_completion(
            self.strategy_direction,
            self.completion_candle,
            self.break_level,
        )
        if expected_kind is None:
            raise ValueError("M15 completion does not close beyond the break level")
        if self.completion_kind != expected_kind:
            raise ValueError("M15 completion_kind does not match frozen candle semantics")
        if self.coverage_start_at_utc != self.reference_candle.open_time_utc:
            raise ValueError("M15 coverage must begin at the frozen reference")
        if self.coverage_end_at_utc != self.completed_at_utc:
            raise ValueError("M15 coverage must end at the frozen completion")
        if self.completed_at_utc > self.decision_at_utc:
            raise ValueError("M15 coverage is not complete by decision")
        if self.source_candle_ids != tuple(item.candle_evidence_id for item in candles):
            raise ValueError("M15 source candle IDs do not match proof")
        if self.source_content_hashes != tuple(item.source_content_hash for item in candles):
            raise ValueError("M15 source hashes do not match proof")
        return self


class DirectionalThesisV1(FrozenThesisContract):
    strategy_thesis_id: str = Field(..., pattern=r"^5scr-thesis:[0-9a-f]{32}$")
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    thesis_sequence: int = Field(..., ge=1)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    strategy_direction: Direction
    direction_immutable: Literal[True] = True
    state: ThesisState = "ACTIVE"
    direction_domain_at_creation: DirectionDomain
    selected_route: str = Field(..., min_length=2, max_length=120)
    route_authorization_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    pressure_authority_mode: PressureAuthorityMode
    pressure_contract_status: PressureContractStatus
    pressure_reference_direction: Direction | None = None
    pressure_formal_transition_event_id: str | None = Field(default=None, max_length=240)
    pressure_authority_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    counter_pressure_proof_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    h1_proof_id: str = Field(..., pattern=r"^5scr-h1-proof:[0-9a-f]{32}$")
    m15_proof_id: str = Field(..., pattern=r"^5scr-m15-proof:[0-9a-f]{32}$")
    structural_proof_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    semantic_identity_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    rule_version: Literal["5scr.directional-thesis.v1"] = DIRECTIONAL_THESIS_RULE_VERSION
    created_at_utc: datetime
    closed_at_utc: datetime | None = None
    closure_reason: str | None = Field(default=None, max_length=160)
    state_version: int = Field(default=1, ge=1)
    valid_for_execution: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("created_at_utc", "closed_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime | None, info: Any) -> datetime | None:
        return _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _thesis_is_coherent(self) -> DirectionalThesisV1:
        if self.direction_domain_at_creation in {"UNRESOLVED", "EMPTY"}:
            raise ValueError("unresolved/empty context cannot form a thesis")
        if self.direction_domain_at_creation == "BUY_ONLY" and self.strategy_direction != "BUY":
            raise ValueError("BUY_ONLY context cannot form SELL thesis")
        if self.direction_domain_at_creation == "SELL_ONLY" and self.strategy_direction != "SELL":
            raise ValueError("SELL_ONLY context cannot form BUY thesis")
        if self.direction_domain_at_creation == "BOTH_CONDITIONAL" and self.route_authorization_hash is None:
            raise ValueError("BOTH_CONDITIONAL requires typed route authorization")
        if self.direction_domain_at_creation != "BOTH_CONDITIONAL" and self.route_authorization_hash is not None:
            raise ValueError("single-direction context cannot carry irrelevant route authorization")
        if self.pressure_authority_mode == "CONSOLIDATED_DIRECTION_CONTRACT":
            if self.pressure_contract_status != "LOCKED":
                raise ValueError("consolidated authority must be LOCKED to form thesis")
            if self.pressure_reference_direction != self.strategy_direction:
                raise ValueError("locked pressure direction cannot be reversed")
            if self.pressure_formal_transition_event_id is None:
                raise ValueError("locked pressure direction requires formal transition lineage")
        elif self.pressure_formal_transition_event_id is not None:
            raise ValueError("RADAR_ONLY thesis cannot claim formal transition lineage")
        if (
            self.pressure_authority_mode == "RADAR_ONLY"
            and self.pressure_reference_direction is not None
            and self.pressure_reference_direction != self.strategy_direction
            and self.counter_pressure_proof_hash is None
        ):
            raise ValueError("opposite RADAR thesis requires counter-pressure proof")
        if (
            self.pressure_authority_mode != "RADAR_ONLY"
            or self.pressure_reference_direction is None
            or self.pressure_reference_direction == self.strategy_direction
        ) and self.counter_pressure_proof_hash is not None:
            raise ValueError("counter-pressure proof is only material for opposite RADAR direction")
        if self.state == "ACTIVE" and (self.closed_at_utc is not None or self.closure_reason is not None):
            raise ValueError("active thesis cannot be closed")
        if self.state != "ACTIVE" and (self.closed_at_utc is None or not self.closure_reason):
            raise ValueError("closed thesis requires time and reason")
        if self.closed_at_utc is not None and self.closed_at_utc < self.created_at_utc:
            raise ValueError("thesis closure cannot precede creation")
        return self


__all__ = [
    "DIRECTIONAL_THESIS_RULE_VERSION",
    "ClosedCandleAuthorityRefV1",
    "Direction",
    "DirectionDomain",
    "DirectionalThesisEvidenceV1",
    "DirectionalThesisV1",
    "H1StructureProofV1",
    "M15CompletionKind",
    "M15StructuralProofV1",
    "PressureAuthorityMode",
    "PressureContractStatus",
    "PressureDirectionAuthorityV1",
    "RouteDirectionAuthorizationV1",
    "ThesisState",
    "pressure_authority_material_hash",
    "route_authorization_material_hash",
    "classify_m15_completion",
]
