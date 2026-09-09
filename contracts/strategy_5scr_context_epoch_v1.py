"""Shadow-only contracts for durable Strategy 5S-CR material context epochs.

``material_context_hash`` fingerprints market context. ``context_epoch_id``
identifies one contiguous period of that context inside a canonical strategy
lifecycle.  They are deliberately different so ``A -> B -> A`` produces three
epochs even though epochs one and three share a material hash.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTEXT_EPOCH_CONTRACT_VERSION = "5scr.context-epoch.v1"
CONTEXT_EVIDENCE_CONTRACT_VERSION = "5scr.context-evidence.v1"

ContextEpochState = Literal["ACTIVE", "SUPERSEDED", "TERMINAL"]
ContextTransitionReason = Literal["OPENED", "MATERIAL_CONTEXT_CHANGED", "LIFECYCLE_TERMINAL"]
DirectionDomain = Literal["BUY_ONLY", "SELL_ONLY", "BOTH_CONDITIONAL", "UNRESOLVED", "EMPTY"]
ContextTimeframe = Literal["D1", "H4"]
ProviderTimestampSemantics = Literal["PERIOD_OPEN", "PERIOD_END", "CANONICAL_WINDOW", "UNSPECIFIED"]


class FrozenContextContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


class ContextCandleAuthorityV1(FrozenContextContract):
    """One D1/H4 source candle reference with explicit closure authority."""

    candle_id: str = Field(..., min_length=1, max_length=240)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    timeframe: ContextTimeframe
    open_time_utc: datetime
    close_time_utc: datetime
    complete: bool
    provider: str = Field(..., min_length=2, max_length=100)
    provider_timestamp_semantics: ProviderTimestampSemantics
    provider_session_lineage_valid: bool
    structural_authority: bool

    @field_validator("open_time_utc", "close_time_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        resolved = _utc(value, str(info.field_name))
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _window_is_ordered(self) -> ContextCandleAuthorityV1:
        if self.close_time_utc <= self.open_time_utc:
            raise ValueError("context candle close must follow open")
        return self


class MaterialContextEvidenceV1(FrozenContextContract):
    """Candidate material context plus full non-authoritative lineage."""

    contract_version: Literal["5scr.context-evidence.v1"] = CONTEXT_EVIDENCE_CONTRACT_VERSION
    source_pressure_event_id: str = Field(..., min_length=1, max_length=240)
    source_event_ids: tuple[str, ...]
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    observed_at_utc: datetime
    d1_candles: tuple[ContextCandleAuthorityV1, ...] = ()
    h4_candles: tuple[ContextCandleAuthorityV1, ...] = ()
    daily_bias: str | None = Field(default=None, max_length=100)
    h4_structure: str | None = Field(default=None, max_length=100)
    price_location: str | None = Field(default=None, max_length=100)
    liquidity_state: str | None = Field(default=None, max_length=100)
    direction_domain: DirectionDomain | None = None
    allowed_routes: tuple[str, ...] = ()
    blocked_routes: tuple[str, ...] = ()
    target_map_version: str | None = Field(default=None, max_length=100)
    structural_invalidation_version: str | None = Field(default=None, max_length=100)
    deterministic_context: bool = True
    future_candle_leakage_detected: bool = False
    # Lineage-only fields. None participates in ``material_context_hash``.
    source_deployment_id: str | None = Field(default=None, max_length=200)
    source_replica_id: str | None = Field(default=None, max_length=200)
    source_cluster_id: str | None = Field(default=None, max_length=240)
    source_stage: str | None = Field(default=None, max_length=100)
    source_family: str | None = Field(default=None, max_length=100)
    reference_price: float | None = Field(default=None, gt=0)
    microboost_evidence_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    execution_authority: Literal[False] = False

    @field_validator("observed_at_utc")
    @classmethod
    def _observed_at_is_utc(cls, value: datetime) -> datetime:
        resolved = _utc(value, "observed_at_utc")
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _lineage_is_canonical(self) -> MaterialContextEvidenceV1:
        if not self.source_event_ids or self.source_event_ids != tuple(sorted(set(self.source_event_ids))):
            raise ValueError("source_event_ids must be non-empty, sorted, and unique")
        if self.source_pressure_event_id not in self.source_event_ids:
            raise ValueError("source_pressure_event_id must be present in source_event_ids")
        if self.allowed_routes != tuple(sorted(set(self.allowed_routes))):
            raise ValueError("allowed_routes must be sorted and unique")
        if self.blocked_routes != tuple(sorted(set(self.blocked_routes))):
            raise ValueError("blocked_routes must be sorted and unique")
        if set(self.allowed_routes) & set(self.blocked_routes):
            raise ValueError("allowed_routes and blocked_routes must be disjoint")
        for timeframe, candles in (("D1", self.d1_candles), ("H4", self.h4_candles)):
            identity = tuple((item.close_time_utc, item.candle_id) for item in candles)
            if identity != tuple(sorted(identity)) or len({item.candle_id for item in candles}) != len(candles):
                raise ValueError(f"{timeframe} candles must be sorted and unique")
            if any(item.timeframe != timeframe or item.symbol != self.symbol for item in candles):
                raise ValueError(f"{timeframe} candle scope mismatch")
        return self


class StrategyContextEpochV1(FrozenContextContract):
    """One contiguous period of material context inside one lifecycle."""

    contract_version: Literal["5scr.context-epoch.v1"] = CONTEXT_EPOCH_CONTRACT_VERSION
    context_epoch_id: str = Field(..., pattern=r"^5scr-context:[0-9a-f]{32}$")
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    epoch_sequence: int = Field(..., ge=1)
    state: ContextEpochState = "ACTIVE"
    material_context_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    opened_at_utc: datetime
    last_confirmed_at_utc: datetime
    closed_at_utc: datetime | None = None
    daily_source_candle_ids: tuple[str, ...]
    h4_source_candle_ids: tuple[str, ...]
    daily_bias: str = Field(..., min_length=1, max_length=100)
    h4_structure: str = Field(..., min_length=1, max_length=100)
    price_location: str = Field(..., min_length=1, max_length=100)
    liquidity_state: str = Field(..., min_length=1, max_length=100)
    direction_domain: DirectionDomain
    allowed_routes: tuple[str, ...]
    blocked_routes: tuple[str, ...]
    target_map_version: str | None = Field(default=None, max_length=100)
    structural_invalidation_version: str | None = Field(default=None, max_length=100)
    transition_reason: ContextTransitionReason
    evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    last_observed_at_utc: datetime
    last_source_event_id: str = Field(..., min_length=1, max_length=240)
    state_version: int = Field(default=1, ge=1)
    execution_authority: Literal[False] = False

    @field_validator("opened_at_utc", "last_confirmed_at_utc", "closed_at_utc", "last_observed_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime | None, info: Any) -> datetime | None:
        return _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _epoch_is_coherent(self) -> StrategyContextEpochV1:
        if not self.daily_source_candle_ids or not self.h4_source_candle_ids:
            raise ValueError("context epoch requires D1 and H4 source candles")
        if self.daily_source_candle_ids != tuple(sorted(set(self.daily_source_candle_ids))):
            raise ValueError("daily source candle IDs must be sorted and unique")
        if self.h4_source_candle_ids != tuple(sorted(set(self.h4_source_candle_ids))):
            raise ValueError("H4 source candle IDs must be sorted and unique")
        if self.allowed_routes != tuple(sorted(set(self.allowed_routes))):
            raise ValueError("allowed_routes must be sorted and unique")
        if self.blocked_routes != tuple(sorted(set(self.blocked_routes))):
            raise ValueError("blocked_routes must be sorted and unique")
        if self.last_confirmed_at_utc < self.opened_at_utc:
            raise ValueError("last confirmation cannot precede epoch open")
        if self.last_observed_at_utc < self.opened_at_utc:
            raise ValueError("last observation cannot precede epoch open")
        if self.state == "ACTIVE" and self.closed_at_utc is not None:
            raise ValueError("active context epoch cannot be closed")
        if self.state != "ACTIVE" and self.closed_at_utc is None:
            raise ValueError("closed context epoch requires closed_at_utc")
        if self.closed_at_utc is not None and self.closed_at_utc < self.opened_at_utc:
            raise ValueError("epoch close cannot precede open")
        if self.closed_at_utc is not None and (
            self.closed_at_utc < self.last_confirmed_at_utc or self.closed_at_utc < self.last_observed_at_utc
        ):
            raise ValueError("epoch close cannot precede its durable context clocks")
        return self


class ContextTransitionV1(FrozenContextContract):
    """Append-only repository record for one epoch boundary."""

    transition_id: str = Field(..., pattern=r"^5scr-context-transition:[0-9a-f]{32}$")
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    from_context_epoch_id: str | None = Field(default=None, pattern=r"^5scr-context:[0-9a-f]{32}$")
    to_context_epoch_id: str | None = Field(default=None, pattern=r"^5scr-context:[0-9a-f]{32}$")
    reason: ContextTransitionReason
    source_pressure_event_id: str = Field(..., min_length=1, max_length=240)
    source_event_ids: tuple[str, ...]
    occurred_at_utc: datetime
    material_context_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    dedupe_key: str = Field(..., min_length=1, max_length=500)
    execution_authority: Literal[False] = False

    @field_validator("occurred_at_utc")
    @classmethod
    def _occurred_at_is_utc(cls, value: datetime) -> datetime:
        resolved = _utc(value, "occurred_at_utc")
        assert resolved is not None
        return resolved

    @model_validator(mode="after")
    def _transition_shape_is_valid(self) -> ContextTransitionV1:
        if not self.source_event_ids or self.source_event_ids != tuple(sorted(set(self.source_event_ids))):
            raise ValueError("transition source_event_ids must be non-empty, sorted, and unique")
        if self.source_pressure_event_id not in self.source_event_ids:
            raise ValueError("transition source event must include pressure event")
        expected = {
            "OPENED": (False, True),
            "MATERIAL_CONTEXT_CHANGED": (True, True),
            "LIFECYCLE_TERMINAL": (True, False),
        }[self.reason]
        actual = (self.from_context_epoch_id is not None, self.to_context_epoch_id is not None)
        if actual != expected:
            raise ValueError(f"{self.reason} transition endpoints are invalid")
        return self


__all__ = [
    "CONTEXT_EPOCH_CONTRACT_VERSION",
    "CONTEXT_EVIDENCE_CONTRACT_VERSION",
    "ContextCandleAuthorityV1",
    "ContextEpochState",
    "ContextTimeframe",
    "ContextTransitionReason",
    "ContextTransitionV1",
    "DirectionDomain",
    "MaterialContextEvidenceV1",
    "ProviderTimestampSemantics",
    "StrategyContextEpochV1",
]
