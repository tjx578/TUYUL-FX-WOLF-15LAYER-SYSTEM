"""Frozen Strategy 5S-CR execution-proof contract.

This module does not discover a trade. It validates the evidence assembled by
the Wolf15 authority chain before a directional SignalJSON may be published or
promoted to MT5. Missing confirmation defers; contradictory or tampered
evidence blocks fail-closed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

STRATEGY_MODEL: Final = "STRATEGY_5S_CR_FINAL"
STRATEGY_RULE_VERSION: Final = "5scr.final.2026-07-19"
STRATEGY_RULE_STATUS: Final = "FROZEN"
STRATEGY_VALIDATION_STATUS: Final = "STRONG_PROVISIONAL"
STRATEGY_OOS_STATUS: Final = "NOT_YET_VALIDATED"
CONFIRMATION_POLICY: Final = "H1_CLOSED_PLUS_M15_BREAK_ACCEPTANCE_OR_FAILED_RECLAIM_RETEST"

Direction = Literal["BUY", "SELL"]
GateDecision = Literal["READY", "DEFER", "BLOCK"]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


class PressureAuthority(StrictFrozenModel):
    selected_pair: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    lifecycle_id: str = Field(..., min_length=3, max_length=200)
    selection_confirmed: Literal[True]


class ContextResolution(StrictFrozenModel):
    status: Literal["RESOLVED", "WAIT_FOR_CONFIRMATION", "BLOCKED"]
    origin: Literal["DIRECT_CONTEXT", "WAIT_FOR_CONFIRMATION"]
    price_location: str = Field(..., min_length=2, max_length=100)
    liquidity_context: str = Field(..., min_length=2, max_length=100)
    daily_bias: str = Field(..., min_length=2, max_length=100)
    h4_structure: str = Field(..., min_length=2, max_length=100)
    allowed_playbook: str = Field(..., min_length=2, max_length=120)
    selected_playbook: str = Field(..., min_length=2, max_length=120)
    blocked_playbook: tuple[str, ...]
    scenario_allowed: bool


class H4StructuralTarget(StrictFrozenModel):
    target_mode: Literal[
        "FINAL_MARKET_STRUCTURE",
        "STRUCTURE_LADDER_TARGET",
        "KEY_LEVEL_STRUCTURE_TARGET",
    ]
    structural_tp1: float = Field(..., gt=0)
    target_room_valid: bool


class H1Confirmation(StrictFrozenModel):
    direction: Direction
    structure_state: str = Field(..., min_length=2, max_length=120)
    structure_confirmed: bool
    candle_closed: bool
    confirmed_at_utc: datetime

    @field_validator("confirmed_at_utc")
    @classmethod
    def _confirmed_at_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "h1.confirmed_at_utc")


class M15Confirmation(StrictFrozenModel):
    direction: Direction
    structural_break: bool
    candle_closed: bool
    acceptance_confirmed: bool
    failed_reclaim_or_retest_confirmed: bool
    rejection_candle_only: bool
    confirmed_at_utc: datetime

    @field_validator("confirmed_at_utc")
    @classmethod
    def _confirmed_at_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "m15.confirmed_at_utc")


class M1ExecutionBox(StrictFrozenModel):
    box_id: str = Field(..., min_length=3, max_length=200)
    box_low: float = Field(..., gt=0)
    box_high: float = Field(..., gt=0)
    fill_price: float = Field(..., gt=0)
    return_to_box_invalidated: bool
    formed_at_utc: datetime | None = None

    @field_validator("formed_at_utc")
    @classmethod
    def _formed_at_is_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value, "m1.formed_at_utc")

    @model_validator(mode="after")
    def _fill_is_inside_box(self) -> M1ExecutionBox:
        if self.box_high <= self.box_low:
            raise ValueError("m1 box_high must be greater than box_low")
        if not self.box_low <= self.fill_price <= self.box_high:
            raise ValueError("m1 fill_price must be inside the current box")
        return self


class RiskAuthority(StrictFrozenModel):
    structural_sl: float = Field(..., gt=0)
    sizing_basis: Literal["STRUCTURAL_SL"]


class Strategy5SCRProof(StrictFrozenModel):
    strategy_model: Literal["STRATEGY_5S_CR_FINAL"]
    rule_version: Literal["5scr.final.2026-07-19"]
    rule_status: Literal["FROZEN"]
    validation_status: Literal["STRONG_PROVISIONAL"]
    out_of_sample_status: Literal["NOT_YET_VALIDATED"]
    production_proven: Literal[False]
    confirmation_policy: Literal["H1_CLOSED_PLUS_M15_BREAK_ACCEPTANCE_OR_FAILED_RECLAIM_RETEST"]
    authority_chain: tuple[
        Literal["PRESSURE"],
        Literal["CONTEXT_RESOLUTION"],
        Literal["H4"],
        Literal["H1"],
        Literal["M15"],
        Literal["M1"],
        Literal["RISK"],
    ]
    pressure: PressureAuthority
    context_resolution: ContextResolution
    h4: H4StructuralTarget
    h1: H1Confirmation
    m15: M15Confirmation
    m1: M1ExecutionBox
    risk: RiskAuthority


@dataclass(frozen=True)
class Strategy5SCREvaluation:
    decision: GateDecision
    reasons: tuple[str, ...]
    proof: Strategy5SCRProof | None = None

    @property
    def ready(self) -> bool:
        return self.decision == "READY"


def evaluate_strategy_5scr_proof(signal: Mapping[str, Any]) -> Strategy5SCREvaluation:
    """Validate a final-signal proof against the frozen 5S-CR authority chain."""

    raw_proof = signal.get("strategy_5scr")
    if not isinstance(raw_proof, Mapping):
        execution_gate = signal.get("execution_gate")
        if isinstance(execution_gate, Mapping):
            raw_proof = execution_gate.get("strategy_5scr")
    if not isinstance(raw_proof, Mapping):
        return Strategy5SCREvaluation("DEFER", ("STRATEGY_5SCR_PROOF_MISSING",))
    try:
        proof = Strategy5SCRProof.model_validate(dict(raw_proof))
    except ValidationError:
        return Strategy5SCREvaluation("BLOCK", ("STRATEGY_5SCR_PROOF_SCHEMA_INVALID",))

    defer: list[str] = []
    block: list[str] = []
    context = proof.context_resolution
    if context.status == "WAIT_FOR_CONFIRMATION":
        defer.append("NO_TRADE_CONTEXT_UNRESOLVED")
    elif context.status == "BLOCKED":
        block.append("STRATEGY_5SCR_CONTEXT_BLOCKED")
    if not context.scenario_allowed:
        block.append("STRATEGY_5SCR_SCENARIO_NOT_ALLOWED")
    if context.selected_playbook in context.blocked_playbook:
        block.append("STRATEGY_5SCR_PLAYBOOK_BLOCKED")

    if not proof.h4.target_room_valid:
        block.append("STRATEGY_5SCR_TARGET_ROOM_INVALID")
    if not proof.h1.candle_closed or not proof.h1.structure_confirmed:
        defer.append("STRATEGY_5SCR_H1_CLOSED_STRUCTURE_CONFIRMATION_REQUIRED")
    if not proof.m15.candle_closed or not proof.m15.structural_break:
        defer.append("STRATEGY_5SCR_M15_CLOSED_STRUCTURAL_BREAK_REQUIRED")
    if not (proof.m15.acceptance_confirmed or proof.m15.failed_reclaim_or_retest_confirmed):
        defer.append("STRATEGY_5SCR_M15_ACCEPTANCE_OR_FAILED_RECLAIM_RETEST_REQUIRED")
    if proof.m15.rejection_candle_only:
        defer.append("NO_TRADE_REJECTION_CANDLE_ONLY")
    if proof.m15.confirmed_at_utc < proof.h1.confirmed_at_utc:
        block.append("STRATEGY_5SCR_CONFIRMATION_SEQUENCE_INVALID")
    if proof.m1.return_to_box_invalidated:
        block.append("STRATEGY_5SCR_M1_RETURN_TO_BOX_INVALIDATED")

    direction = str(signal.get("final_direction") or "").upper()
    if direction not in {"BUY", "SELL"}:
        block.append("STRATEGY_5SCR_FINAL_DIRECTION_INVALID")
    elif direction != proof.h1.direction or direction != proof.m15.direction:
        block.append("STRATEGY_5SCR_DIRECTION_AUTHORITY_MISMATCH")

    symbol = str(signal.get("symbol") or "").upper()
    if symbol != proof.pressure.selected_pair:
        block.append("STRATEGY_5SCR_PRESSURE_PAIR_MISMATCH")
    lifecycle_id = str(
        signal.get("lifecycle_id") or signal.get("terminal_decision_id") or signal.get("source_clean_block_id") or ""
    )
    if lifecycle_id != proof.pressure.lifecycle_id:
        block.append("STRATEGY_5SCR_LIFECYCLE_MISMATCH")

    entry = _first_float(signal.get("entry_reference_price"), signal.get("signal_valid_price"))
    stop = _first_float(signal.get("selected_sl"), signal.get("sl_safe"))
    target = _first_float(signal.get("tp1"), signal.get("take_profit"))
    if entry is None or not _same_price(entry, proof.m1.fill_price):
        block.append("STRATEGY_5SCR_M1_FILL_MISMATCH")
    if stop is None or not _same_price(stop, proof.risk.structural_sl):
        block.append("STRATEGY_5SCR_STRUCTURAL_SL_MISMATCH")
    if target is None or not _same_price(target, proof.h4.structural_tp1):
        block.append("STRATEGY_5SCR_STRUCTURAL_TP1_MISMATCH")
    if entry is not None and stop is not None and target is not None:
        price_geometry_valid = stop < entry < target if direction == "BUY" else target < entry < stop
        if not price_geometry_valid:
            block.append("STRATEGY_5SCR_PRICE_GEOMETRY_INVALID")

    if block:
        return Strategy5SCREvaluation("BLOCK", tuple(dict.fromkeys(block + defer)), proof)
    if defer:
        return Strategy5SCREvaluation("DEFER", tuple(dict.fromkeys(defer)), proof)
    return Strategy5SCREvaluation("READY", (), proof)


def _first_float(*values: Any) -> float | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            return number
    return None


def _same_price(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=max(abs(left), abs(right), 1.0) * 1e-9)


__all__ = [
    "CONFIRMATION_POLICY",
    "STRATEGY_MODEL",
    "STRATEGY_OOS_STATUS",
    "STRATEGY_RULE_STATUS",
    "STRATEGY_RULE_VERSION",
    "STRATEGY_VALIDATION_STATUS",
    "Strategy5SCREvaluation",
    "Strategy5SCRProof",
    "evaluate_strategy_5scr_proof",
]
