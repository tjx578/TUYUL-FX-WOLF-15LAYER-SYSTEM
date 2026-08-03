"""Typed contracts for the non-executable Strategy 5S-CR pressure radar."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PressureRadarDirection = Literal["BUY", "SELL"]
PressureRadarQualifyingStage = Literal["PRESSURE_BLOCK", "CANDIDATE_LIFECYCLE", "ALLOWED_QUORUM"]
PressureRadarStatus = Literal[
    "WAITING_CANONICAL_LINEAGE",
    "ANALYSIS_READY",
    "EXPIRED",
    "INVALIDATED_DIRECTION_REVERSAL",
    "CANCELLED",
]
PressureRadarState = Literal[
    "RADAR_OBSERVED",
    "RADAR_QUALIFIED_PROVISIONAL",
    "WAITING_CANONICAL_LINEAGE",
    "PAIR_ADMISSION_GRANTED",
    "ANALYSIS_READY",
    "EXPIRED",
    "INVALIDATED_DIRECTION_REVERSAL",
    "CANCELLED",
]


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PressureRadarEvaluation(FrozenContract):
    """Result of evaluating one pressure payload against gate v1."""

    gate_rule_version: Literal["pressure_radar_gate_v1"] = "pressure_radar_gate_v1"
    event_id: str = Field(
        ...,
        pattern=r"^(?:sha256:[0-9a-f]{64}|[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$",
    )
    deployment_id: str = Field(..., min_length=1, max_length=200)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    raw_direction: PressureRadarDirection | None = None
    observed_at_utc: datetime
    raw_direction_expires_at_utc: datetime | None = None
    source_stage: str = Field(..., min_length=1, max_length=100)
    signal_family: str = Field(..., min_length=1, max_length=100)
    qualifying_stage: PressureRadarQualifyingStage | None = None
    current_block_effective_ticks: int = Field(default=0, ge=0)
    source_clean_block_id: str | None = Field(default=None, max_length=500)
    context_version: str = Field(..., min_length=1, max_length=200)
    context_signature: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    provisional_candidate: bool
    reserve_near_qualified: bool
    failed_predicates: tuple[str, ...] = ()

    @field_validator("observed_at_utc", "raw_direction_expires_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime | None, info: Any) -> datetime | None:
        return None if value is None else _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _decision_is_consistent(self) -> PressureRadarEvaluation:
        if self.provisional_candidate:
            if self.qualifying_stage is None or self.failed_predicates or self.reserve_near_qualified:
                raise ValueError("provisional candidate requires a qualifying stage without failures")
        elif self.qualifying_stage is not None:
            raise ValueError("non-candidate evaluation cannot expose a qualifying stage")
        if self.reserve_near_qualified and self.failed_predicates != ("SOURCE_STAGE_NOT_ALLOWED",):
            raise ValueError("reserve near-qualified is limited to a stage-only failure")
        return self


class PressureRadarManifest(FrozenContract):
    """Latched pressure qualification awaiting canonical pair admission.

    ``WAITING_CANONICAL_LINEAGE`` remains the persisted v1 status label for
    database compatibility.  Its v2 meaning is made explicit by
    ``next_required_stage=PAIR_ADMISSION``; lineage alone cannot promote it.
    """

    manifest_id: str = Field(..., pattern=r"^5scr-radar:[0-9a-f]{32}$")
    deployment_id: str = Field(..., min_length=1, max_length=200)
    gate_rule_version: Literal["pressure_radar_gate_v1"] = "pressure_radar_gate_v1"
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    raw_direction: PressureRadarDirection
    qualifying_event_id: str = Field(
        ...,
        pattern=r"^(?:sha256:[0-9a-f]{64}|[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$",
    )
    qualifying_time_utc: datetime
    qualifying_stage: PressureRadarQualifyingStage
    max_effective_ticks: int = Field(..., ge=3)
    source_clean_block_id: str | None = Field(default=None, max_length=500)
    lineage_finalized_at_utc: datetime | None = None
    pair_admission_id: str | None = Field(default=None, pattern=r"^5scr-admission:[0-9a-f]{32}$")
    pair_admission_status: Literal["NOT_GRANTED", "GRANTED"] = "NOT_GRANTED"
    pair_admission_rule_version: str | None = Field(default=None, max_length=100)
    pair_admission_granted_at_utc: datetime | None = None
    pair_admission_expires_at_utc: datetime | None = None
    pair_admission_source_ledger_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    context_version: str = Field(..., min_length=1, max_length=200)
    lineage_context_version: str | None = Field(default=None, max_length=200)
    context_signature: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    raw_direction_expires_at_utc: datetime
    status: PressureRadarStatus
    state_history: tuple[PressureRadarState, ...] = Field(..., min_length=3)
    observed_event_ids: tuple[str, ...] = Field(..., min_length=1)
    final_direction: Literal["WAIT"] = "WAIT"
    valid_for_execution: Literal[False] = False
    is_final_signal: Literal[False] = False
    next_required_stage: Literal["PAIR_ADMISSION", "CLOSED_CANDLE_EVIDENCE", "NONE"]

    @field_validator(
        "qualifying_time_utc",
        "lineage_finalized_at_utc",
        "pair_admission_granted_at_utc",
        "pair_admission_expires_at_utc",
        "raw_direction_expires_at_utc",
    )
    @classmethod
    def _manifest_times_are_utc(cls, value: datetime | None, info: Any) -> datetime | None:
        return None if value is None else _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _manifest_is_consistent(self) -> PressureRadarManifest:
        if self.raw_direction_expires_at_utc <= self.qualifying_time_utc:
            raise ValueError("raw direction expiry must follow qualification")
        if len(set(self.observed_event_ids)) != len(self.observed_event_ids):
            raise ValueError("observed event IDs must be unique")
        if self.state_history[:3] != (
            "RADAR_OBSERVED",
            "RADAR_QUALIFIED_PROVISIONAL",
            "WAITING_CANONICAL_LINEAGE",
        ):
            raise ValueError("manifest must preserve the provisional lineage-wait states")
        if self.state_history[-1] != self.status:
            raise ValueError("last state must equal manifest status")
        if self.status == "ANALYSIS_READY":
            if (
                self.pair_admission_status != "GRANTED"
                or not self.pair_admission_id
                or self.pair_admission_granted_at_utc is None
                or self.pair_admission_expires_at_utc is None
                or not self.pair_admission_source_ledger_hash
            ):
                raise ValueError("analysis-ready manifest requires canonical pair admission")
            if self.pair_admission_expires_at_utc <= self.pair_admission_granted_at_utc:
                raise ValueError("pair admission expiry must follow grant time")
            if self.next_required_stage != "CLOSED_CANDLE_EVIDENCE":
                raise ValueError("analysis-ready manifest must request closed-candle evidence")
        elif self.status == "WAITING_CANONICAL_LINEAGE":
            if self.pair_admission_id is not None or self.pair_admission_status != "NOT_GRANTED":
                raise ValueError("waiting manifest cannot carry pair-admission authority")
            if self.next_required_stage != "PAIR_ADMISSION":
                raise ValueError("waiting manifest must request pair admission")
        elif self.next_required_stage != "NONE":
            raise ValueError("terminal manifest cannot request another stage")
        return self


__all__ = [
    "PressureRadarDirection",
    "PressureRadarEvaluation",
    "PressureRadarManifest",
    "PressureRadarQualifyingStage",
    "PressureRadarState",
    "PressureRadarStatus",
]
