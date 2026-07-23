"""Typed, non-executable contracts for Strategy 5S-CR outcome replay."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.canonical_candle import CanonicalCandle

Strategy5SCROutcomeStatus = Literal[
    "TP1_FIRST",
    "SL_FIRST",
    "AMBIGUOUS_SAME_CANDLE",
    "TIMEOUT",
    "NO_DATA",
]


class Strategy5SCRM1Outcome(BaseModel):
    """Deterministic hypothetical result for one frozen tradeplan candidate.

    This is research output, not an execution report.  The candidate is treated
    as active at ``decision_at_utc`` because its entry was already selected by
    the pre-decision M1 proof.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome_id: str = Field(..., pattern=r"^5scr-outcome:[0-9a-f]{32}$")
    classifier_version: Literal["5scr.m1-outcome.v1"] = "5scr.m1-outcome.v1"
    tradeplan_id: str = Field(..., pattern=r"^5scr-plan:[0-9a-f]{32}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    direction: Literal["BUY", "SELL"]
    decision_at_utc: datetime
    evaluated_until_utc: datetime | None = None
    entry_assumption: Literal["ACTIVE_AT_DECISION"] = "ACTIVE_AT_DECISION"
    entry: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    tp1: float = Field(..., gt=0)
    status: Strategy5SCROutcomeStatus
    realized_r: float | None = None
    bars_evaluated: int = Field(..., ge=0)
    first_bar_open_utc: datetime | None = None
    last_bar_close_utc: datetime | None = None
    terminal_candle: CanonicalCandle | None = None
    valid_for_execution: Literal[False] = False

    @field_validator(
        "decision_at_utc",
        "evaluated_until_utc",
        "first_bar_open_utc",
        "last_bar_close_utc",
    )
    @classmethod
    def _timestamps_are_utc(cls, value: datetime | None, info: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            field_name = getattr(info, "field_name", "timestamp")
            raise ValueError(f"{field_name} must include a UTC offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _result_is_consistent(self) -> Strategy5SCRM1Outcome:
        if self.direction == "BUY" and not self.stop_loss < self.entry < self.tp1:
            raise ValueError("BUY replay requires stop_loss < entry < tp1")
        if self.direction == "SELL" and not self.tp1 < self.entry < self.stop_loss:
            raise ValueError("SELL replay requires tp1 < entry < stop_loss")
        if self.evaluated_until_utc is not None and self.evaluated_until_utc <= self.decision_at_utc:
            raise ValueError("evaluated_until_utc must follow decision_at_utc")
        if self.status == "NO_DATA":
            if self.bars_evaluated or self.terminal_candle is not None:
                raise ValueError("NO_DATA cannot carry evaluated bars or a terminal candle")
        elif self.bars_evaluated == 0:
            raise ValueError("non-NO_DATA outcome requires at least one evaluated bar")
        terminal = self.status in {"TP1_FIRST", "SL_FIRST", "AMBIGUOUS_SAME_CANDLE"}
        if terminal != (self.terminal_candle is not None):
            raise ValueError("terminal status and terminal_candle must agree")
        expected_r = {
            "TP1_FIRST": abs(self.tp1 - self.entry) / abs(self.entry - self.stop_loss),
            "SL_FIRST": -1.0,
        }.get(self.status)
        if expected_r is None:
            if self.realized_r is not None:
                raise ValueError("ambiguous, timeout, and no-data outcomes have no realized_r")
        elif self.realized_r is None or abs(self.realized_r - expected_r) > 1e-9:
            raise ValueError("realized_r does not match the classified price path")
        return self


__all__ = [
    "Strategy5SCRM1Outcome",
    "Strategy5SCROutcomeStatus",
]
