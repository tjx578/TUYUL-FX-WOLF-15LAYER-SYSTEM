"""Typed contracts for the Strategy 5S-CR pressure-to-tradeplan pipeline.

The pressure path is deliberately split from final ``signal_json`` emission.
These contracts may describe a strategy-valid tradeplan, but every object in
this module remains non-executable until the risk plane creates a durable risk
reservation and the final-signal outbox transaction commits.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.strategy_5scr import (
    ContextResolution,
    H1Confirmation,
    H4StructuralTarget,
    M1ExecutionBox,
    M15Confirmation,
    Strategy5SCRProof,
)

PressureInputMode = Literal["REPLAY", "LIVE"]
CampaignAnchorSource = Literal[
    "SOURCE_CLEAN_BLOCK_ID",
    "SOURCE_WATCH_ID",
    "LEGACY_EPISODE",
    "UNRESOLVED",
]
TradeDirection = Literal["BUY", "SELL"]
BuildDecision = Literal["READY", "DEFER", "BLOCK"]


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


class LegacyEpisodePolicy(FrozenContract):
    """Frozen grouping policy used only for pressure exports lacking lineage.

    The M15-sized gap is an explicit replay compatibility rule.  Production
    LIVE inputs must carry a canonical clean-block or SignalWatch anchor.
    """

    rule_version: Literal["5scr.legacy-m15-gap.v1"] = "5scr.legacy-m15-gap.v1"
    max_gap_seconds: int = Field(default=900, ge=60, le=86_400)


class PressureEvent(FrozenContract):
    event_id: str = Field(
        ...,
        pattern=r"^(?:sha256:[0-9a-f]{64}|[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$",
    )
    source_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    input_mode: PressureInputMode
    schema_version: str = Field(..., min_length=1, max_length=100)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    event_time_utc: datetime
    event_time_source: str = Field(..., min_length=2, max_length=100)
    cluster_id: str = Field(..., min_length=1, max_length=240)
    campaign_anchor: str | None = Field(default=None, max_length=240)
    campaign_anchor_source: CampaignAnchorSource
    campaign_anchor_execution_grade: bool
    raw_direction: TradeDirection | None = None
    pressure_seen: bool
    pair_eligible_for_analysis: bool
    allowed_quorum_reached: bool
    pressure_event_count: int = Field(default=0, ge=0)
    pressure_level: str | None = Field(default=None, max_length=100)
    pressure_strength: str | None = Field(default=None, max_length=100)
    reference_price: float | None = Field(default=None, gt=0)
    reference_price_source: str | None = Field(default=None, max_length=100)
    reference_price_role: Literal["REFERENCE_ONLY_NOT_EXECUTABLE"] = "REFERENCE_ONLY_NOT_EXECUTABLE"
    htf_structure_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_time_utc")
    @classmethod
    def _event_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "event_time_utc")

    @model_validator(mode="after")
    def _anchor_contract_is_consistent(self) -> PressureEvent:
        has_anchor = bool(self.campaign_anchor)
        if self.campaign_anchor_source in {"SOURCE_CLEAN_BLOCK_ID", "SOURCE_WATCH_ID"}:
            if not has_anchor or not self.campaign_anchor_execution_grade:
                raise ValueError("canonical campaign anchors must be present and execution-grade")
        elif has_anchor or self.campaign_anchor_execution_grade:
            raise ValueError("unresolved/legacy anchors are assigned by the lifecycle accumulator")
        return self


class PressureLifecycle(FrozenContract):
    campaign_id: str = Field(..., min_length=3, max_length=240)
    campaign_anchor_source: CampaignAnchorSource
    campaign_anchor_execution_grade: bool
    input_mode: PressureInputMode
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    raw_direction: TradeDirection | None = None
    started_at_utc: datetime
    updated_at_utc: datetime
    event_ids: tuple[str, ...] = Field(..., min_length=1)
    latest_cluster_id: str = Field(..., min_length=1, max_length=240)
    selected_by_pressure: bool
    max_reported_pressure_count: int = Field(default=0, ge=0)
    latest_pressure_level: str | None = Field(default=None, max_length=100)
    latest_pressure_strength: str | None = Field(default=None, max_length=100)
    latest_reference_price: float | None = Field(default=None, gt=0)
    latest_htf_structure_context: dict[str, Any] = Field(default_factory=dict)
    legacy_grouping_rule_version: str | None = Field(default=None, max_length=100)

    @field_validator("started_at_utc", "updated_at_utc")
    @classmethod
    def _lifecycle_times_are_utc(cls, value: datetime) -> datetime:
        return _utc(value, "lifecycle timestamp")

    @model_validator(mode="after")
    def _time_order_is_valid(self) -> PressureLifecycle:
        if self.updated_at_utc < self.started_at_utc:
            raise ValueError("updated_at_utc cannot precede started_at_utc")
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("event_ids must be unique")
        if self.input_mode == "LIVE" and self.campaign_anchor_source == "LEGACY_EPISODE":
            raise ValueError("LIVE lifecycle cannot use a legacy synthetic anchor")
        return self


class Strategy5SCRMarketEvidence(FrozenContract):
    """Already-resolved closed-candle evidence supplied by Wolf15 analysis."""

    decision_at_utc: datetime
    context_resolution: ContextResolution | None = None
    h4: H4StructuralTarget | None = None
    h1: H1Confirmation | None = None
    m15: M15Confirmation | None = None
    m1: M1ExecutionBox | None = None
    structural_sl: float | None = Field(default=None, gt=0)
    pip_size: float | None = Field(default=None, gt=0)
    spread_price: float | None = Field(default=None, ge=0)
    source_candle_close_times: tuple[datetime, ...] = ()

    @field_validator("decision_at_utc")
    @classmethod
    def _decision_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "decision_at_utc")

    @field_validator("source_candle_close_times")
    @classmethod
    def _source_close_times_are_utc(cls, values: tuple[datetime, ...]) -> tuple[datetime, ...]:
        return tuple(_utc(value, "source_candle_close_times") for value in values)


class Strategy5SCRTradePlan(FrozenContract):
    tradeplan_id: str = Field(..., pattern=r"^5scr-plan:[0-9a-f]{32}$")
    strategy_model: Literal["STRATEGY_5S_CR_FINAL"] = "STRATEGY_5S_CR_FINAL"
    rule_version: Literal["5scr.final.2026-07-19"] = "5scr.final.2026-07-19"
    campaign_id: str = Field(..., min_length=3, max_length=240)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    direction: TradeDirection
    decision_at_utc: datetime
    entry: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    tp1: float = Field(..., gt=0)
    target_mode: Literal[
        "FINAL_MARKET_STRUCTURE",
        "STRUCTURE_LADDER_TARGET",
        "KEY_LEVEL_STRUCTURE_TARGET",
    ]
    rr: float = Field(..., ge=1.5)
    min_rr: float = Field(default=1.5, ge=1.5, le=1.5)
    target_distance_price: float = Field(..., gt=0)
    execution_floor_price: float = Field(..., gt=0)
    pip_size: float = Field(..., gt=0)
    spread_price: float = Field(..., ge=0)
    source_pressure_event_ids: tuple[str, ...] = Field(..., min_length=1)
    proof: Strategy5SCRProof
    tradeplan_valid: Literal[True] = True
    valid_for_execution: Literal[False] = False
    next_required_stage: Literal["RISK_RESERVATION"] = "RISK_RESERVATION"

    @field_validator("decision_at_utc")
    @classmethod
    def _tradeplan_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "decision_at_utc")


class PressureTradePlanBuildResult(FrozenContract):
    decision: BuildDecision
    reasons: tuple[str, ...] = ()
    lifecycle: PressureLifecycle
    tradeplan: Strategy5SCRTradePlan | None = None
    candidate_payload: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _ready_result_has_non_executable_plan(self) -> PressureTradePlanBuildResult:
        if self.decision == "READY":
            if self.reasons or self.tradeplan is None or self.candidate_payload is None:
                raise ValueError("READY result requires a plan and candidate payload without reasons")
            if self.candidate_payload.get("valid_for_execution") is not False:
                raise ValueError("tradeplan candidate must remain non-executable")
            if self.candidate_payload.get("is_final_signal") is not False:
                raise ValueError("tradeplan candidate must not be a final signal")
        elif self.tradeplan is not None or self.candidate_payload is not None:
            raise ValueError("DEFER/BLOCK result cannot carry a tradeplan")
        return self


__all__ = [
    "BuildDecision",
    "CampaignAnchorSource",
    "LegacyEpisodePolicy",
    "PressureEvent",
    "PressureInputMode",
    "PressureLifecycle",
    "PressureTradePlanBuildResult",
    "Strategy5SCRMarketEvidence",
    "Strategy5SCRTradePlan",
    "TradeDirection",
]
