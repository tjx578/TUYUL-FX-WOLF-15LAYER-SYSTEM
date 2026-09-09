"""Selected-SSOT candidate boundary for TEST_ONLY strategy-to-risk handoff."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from contracts.strategy_5scr_net_geometry_v31 import EntryIntervalV31, GeometryContract, Price
from contracts.strategy_5scr_target_selection_v31 import TargetUniverseV31


class TradePlanCandidateV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    tradeplan_id: UUID
    tradeplan_revision: int = Field(ge=1, strict=True)
    strategy_lifecycle_id: UUID
    strategy_analysis_admission_id: UUID
    analysis_admission_class: Literal["CANONICAL_RAW", "MATURE_ADVISORY"]
    pressure_hypothesis_id: UUID | None
    strategy_thesis_id: UUID
    context_epoch_id: UUID
    execution_box_id: UUID
    box_version: int = Field(ge=1, strict=True)
    symbol: str = Field(min_length=3, max_length=32)
    direction: Literal["BUY", "SELL"]
    state: Literal["TRADEPLAN_CANDIDATE"]
    final_direction: Literal["WAIT"]
    valid_for_execution: Literal[False]
    promotion_eligibility: Literal["CANONICAL_RISK_PATH", "SHADOW_ONLY"]
    risk_handoff_allowed: bool = Field(strict=True)
    final_signal_allowed: Literal[False]
    execution_command_allowed: Literal[False]
    strategy_next_required_stage: Literal["RISK_RESERVATION", "SHADOW_TERMINAL_REVIEW"]
    target_id: UUID
    entry_interval: EntryIntervalV31
    candidate_entry: Price
    structural_sl: Price
    tp1: Price
    gross_rr: Decimal = Field(gt=0, allow_inf_nan=False)
    net_rr: Decimal = Field(ge=Decimal("1.5"), allow_inf_nan=False)
    execution_policy_id: str = Field(min_length=3, max_length=100)
    evidence_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    decision_at: datetime

    @model_validator(mode="after")
    def scope(self):
        expected = (
            ("SHADOW_ONLY", False, "SHADOW_TERMINAL_REVIEW")
            if self.analysis_admission_class == "MATURE_ADVISORY"
            else ("CANONICAL_RISK_PATH", True, "RISK_RESERVATION")
        )
        if (self.promotion_eligibility, self.risk_handoff_allowed, self.strategy_next_required_stage) != expected:
            raise ValueError("candidate admission and promotion scope conflict")
        if self.decision_at.tzinfo is None or self.decision_at.utcoffset() is None:
            raise ValueError("candidate decision clock must be aware")
        if not self.entry_interval.low <= self.candidate_entry <= self.entry_interval.high:
            raise ValueError("candidate entry is outside its interval")
        if not (
            self.structural_sl < self.candidate_entry < self.tp1
            if self.direction == "BUY"
            else self.tp1 < self.candidate_entry < self.structural_sl
        ):
            raise ValueError("candidate geometry contradicts direction")
        return self


class CandidateHandoffV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    selected_ssot_hash: Literal["sha256:6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902"]
    proof_policy_id: Literal["S3_S5_HANDOFF_TEST_V1"]
    candidate: TradePlanCandidateV31
    target_universe: TargetUniverseV31
    admission_receipt_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    thesis_structural_proof_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    context_route_receipt_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    price_quality_receipt_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    handoff_receipt_valid_until: datetime

    @model_validator(mode="after")
    def expiry(self):
        deadline = self.handoff_receipt_valid_until
        if deadline.tzinfo is None or deadline.utcoffset() is None or deadline <= self.candidate.decision_at:
            raise ValueError("handoff receipt must have an aware positive validity window")
        return self
