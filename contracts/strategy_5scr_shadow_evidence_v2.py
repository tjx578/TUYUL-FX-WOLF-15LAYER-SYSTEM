"""Shadow-only evidence ownership contracts for Strategy Lifecycle V2."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHADOW_EVIDENCE_V2_SCHEMA_VERSION = "5scr.shadow-evidence-owner.v1"
SHADOW_EVIDENCE_V2_CALENDAR_VERSION = "FOREX_17NY_EXPECTED_CLOSED_BAR_V2_PROVIDER_CALENDAR"


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


class StrategyLifecycleAdmissionLinkV2(_FrozenContract):
    """Authoritative Pair Admission lineage attached to one strategy episode."""

    admission_event_id: str = Field(..., pattern=r"^5scr-admission:[0-9a-f]{32}$")
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    pressure_event_id: str = Field(..., min_length=1, max_length=240)
    raw_lineage_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    admission_rule_version: str = Field(..., min_length=3, max_length=100)
    admitted_at_utc: datetime
    linked_at_utc: datetime
    execution_authority: Literal[False] = False

    @field_validator("admitted_at_utc", "linked_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: object) -> datetime:
        return _utc(value, str(getattr(info, "field_name", "admission timestamp")))

    @model_validator(mode="after")
    def _admission_precedes_link(self) -> StrategyLifecycleAdmissionLinkV2:
        if self.linked_at_utc < self.admitted_at_utc:
            raise ValueError("linked_at_utc cannot precede admitted_at_utc")
        return self


class ShadowCandleReferenceV2(_FrozenContract):
    """Identity and closed-period boundary for one authoritative candle."""

    candle_id: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    timeframe: Literal["D1", "H4", "H1", "M15", "M1"]
    period_open_utc: datetime
    period_close_utc: datetime
    provider: str = Field(..., min_length=2, max_length=100)
    is_closed: Literal[True] = True

    @field_validator("period_open_utc", "period_close_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: object) -> datetime:
        return _utc(value, str(getattr(info, "field_name", "candle timestamp")))

    @model_validator(mode="after")
    def _window_is_positive(self) -> ShadowCandleReferenceV2:
        if self.period_close_utc <= self.period_open_utc:
            raise ValueError("candle period_close_utc must follow period_open_utc")
        return self


class StrategyShadowEvidenceSnapshotV2(_FrozenContract):
    """Immutable as-of evidence owned by ``strategy_lifecycle_id``."""

    schema_version: Literal["5scr.shadow-evidence-owner.v1"] = SHADOW_EVIDENCE_V2_SCHEMA_VERSION
    snapshot_id: str = Field(..., pattern=r"^5scr-evidence-v2:[0-9a-f]{32}$")
    evidence_job_id: str = Field(..., pattern=r"^5scr-evidence-job-v2:[0-9a-f]{32}$")
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    admission_event_id: str = Field(..., pattern=r"^5scr-admission:[0-9a-f]{32}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    decision_time_utc: datetime
    provider_calendar_version: str = Field(..., min_length=3, max_length=120)
    source_candles: tuple[ShadowCandleReferenceV2, ...] = ()
    coverage_status: Literal["COMPLETE", "INCOMPLETE"]
    context_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    result_state: Literal["WAIT", "NO_TRADE", "CONDITIONAL"]
    terminal_reason: str = Field(..., min_length=3, max_length=160)
    trade_geometry_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    valid_for_execution: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("decision_time_utc")
    @classmethod
    def _decision_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "decision_time_utc")

    @model_validator(mode="after")
    def _snapshot_is_as_of_and_closed(self) -> StrategyShadowEvidenceSnapshotV2:
        candle_ids = [item.candle_id for item in self.source_candles]
        if len(set(candle_ids)) != len(candle_ids):
            raise ValueError("source candle IDs must be unique")
        if any(item.period_close_utc > self.decision_time_utc for item in self.source_candles):
            raise ValueError("future candle leakage is forbidden")
        if self.coverage_status == "COMPLETE" and not self.source_candles:
            raise ValueError("COMPLETE evidence requires source candles")
        return self


class StrategyEvidenceComparisonV2(_FrozenContract):
    """Durable legacy-vs-V2 comparison; never an execution decision."""

    comparison_id: str = Field(..., pattern=r"^5scr-evidence-comparison-v2:[0-9a-f]{32}$")
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    v2_snapshot_id: str = Field(..., pattern=r"^5scr-evidence-v2:[0-9a-f]{32}$")
    legacy_lifecycle_id: str | None = Field(default=None, max_length=500)
    legacy_snapshot_id: str | None = Field(default=None, max_length=80)
    same_lifecycle_grouping: bool | None = None
    same_candle_set: bool | None = None
    same_context_hash: bool | None = None
    same_terminal_reason: bool | None = None
    same_trade_geometry: bool | None = None
    reason_codes: tuple[str, ...] = ()
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _differences_are_explained(self) -> StrategyEvidenceComparisonV2:
        comparisons = (
            self.same_lifecycle_grouping,
            self.same_candle_set,
            self.same_context_hash,
            self.same_terminal_reason,
            self.same_trade_geometry,
        )
        if any(value is not True for value in comparisons) and not self.reason_codes:
            raise ValueError("missing or different comparison dimensions require reason_codes")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes must be unique")
        return self


__all__ = [
    "SHADOW_EVIDENCE_V2_CALENDAR_VERSION",
    "SHADOW_EVIDENCE_V2_SCHEMA_VERSION",
    "ShadowCandleReferenceV2",
    "StrategyEvidenceComparisonV2",
    "StrategyLifecycleAdmissionLinkV2",
    "StrategyShadowEvidenceSnapshotV2",
]
