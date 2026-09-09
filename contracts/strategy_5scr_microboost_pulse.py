"""Microboost pulse-transition and reduced-state contracts.

``microboost_detected`` in ``SignalPressureStateJSON`` is a *state snapshot*: it
stays true for as long as the Microboost remains attached to the lifecycle, even
when the emission itself was published by another stage.  Measured on the repo's
own archive cohort, the state flag is carried far more often than a Microboost
is actually born, so counting snapshots badly overstates how often pressure
pulses.

These contracts separate the two ideas the snapshot conflates:

``MicroboostPulseEvent``
    An immutable record that something *materially changed* -- a pulse formed,
    was reinforced, weakened, was invalidated, or expired.

``MicroboostState``
    The reduced current state of the pulse within one analysis lifecycle.

Neither object resolves direction or authorizes execution.  Microboost stays
timing/pressure evidence exactly as the pure-stage contract requires.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MICROBOOST_PULSE_CONTRACT_VERSION = "microboost-pulse-state.v1"

MicroboostPulseTransition = Literal[
    "FORMED",
    "REINFORCED",
    "WEAKENED",
    "INVALIDATED",
    "EXPIRED",
]
MicroboostStateName = Literal[
    "NONE",
    "ACTIVE",
    "WEAKENING",
    "INVALIDATED",
    "EXPIRED",
]
PulseDirection = Literal["BUY", "SELL"]

#: Transitions that mean "a new independent pulse was born".
INDEPENDENT_PULSE_TRANSITIONS: frozenset[str] = frozenset({"FORMED"})
#: Transitions that terminate an active pulse.
TERMINAL_PULSE_TRANSITIONS: frozenset[str] = frozenset({"INVALIDATED", "EXPIRED"})


class _FrozenPulseContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


class MicroboostPulseEvent(_FrozenPulseContract):
    """One immutable material change in Microboost pressure."""

    pulse_event_id: str = Field(..., pattern=r"^5scr-pulse:[0-9a-f]{32}$")
    contract_version: Literal["microboost-pulse-state.v1"] = MICROBOOST_PULSE_CONTRACT_VERSION
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    transition: MicroboostPulseTransition
    direction: PulseDirection | None = None
    occurred_at_utc: datetime
    source_event_ids: tuple[str, ...] = Field(..., min_length=1)
    evidence_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    source_deployment_id: str | None = Field(default=None, max_length=240)
    source_commit_sha: str | None = Field(default=None, max_length=240)
    source_stage: str | None = Field(default=None, max_length=100)
    source_family: str | None = Field(default=None, max_length=100)
    active_block_id: str | None = Field(default=None, max_length=240)
    effective_ticks_before: int | None = Field(default=None, ge=0)
    effective_ticks_after: int | None = Field(default=None, ge=0)
    strength_before: str | None = Field(default=None, max_length=100)
    strength_after: str | None = Field(default=None, max_length=100)
    dedupe_key: str = Field(..., min_length=8, max_length=400)
    # Microboost never resolves direction or authorizes execution.
    valid_for_execution: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator("occurred_at_utc")
    @classmethod
    def _occurred_at_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "occurred_at_utc")

    @model_validator(mode="after")
    def _transition_is_coherent(self) -> MicroboostPulseEvent:
        if len(set(self.source_event_ids)) != len(self.source_event_ids):
            raise ValueError("source_event_ids must be unique")
        if self.transition == "FORMED" and self.effective_ticks_before is not None:
            raise ValueError("FORMED cannot carry a prior effective-tick reading")
        return self


class MicroboostState(_FrozenPulseContract):
    """Reduced Microboost state for one analysis lifecycle."""

    contract_version: Literal["microboost-pulse-state.v1"] = MICROBOOST_PULSE_CONTRACT_VERSION
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    state: MicroboostStateName = "NONE"
    direction: PulseDirection | None = None
    first_formed_at_utc: datetime | None = None
    last_pulse_at_utc: datetime | None = None
    last_confirmed_at_utc: datetime | None = None
    expires_at_utc: datetime | None = None
    #: Number of *independent* pulses (FORMED), not sticky snapshots.
    independent_pulse_count: int = Field(default=0, ge=0)
    reinforcement_count: int = Field(default=0, ge=0)
    #: Snapshots that carried the state without producing a pulse.
    carried_snapshot_count: int = Field(default=0, ge=0)
    observed_snapshot_count: int = Field(default=0, ge=0)
    current_effective_ticks: int = Field(default=0, ge=0)
    peak_effective_ticks: int = Field(default=0, ge=0)
    current_strength: str | None = Field(default=None, max_length=100)
    peak_strength: str | None = Field(default=None, max_length=100)
    active_block_id: str | None = Field(default=None, max_length=240)
    last_source_stage: str | None = Field(default=None, max_length=100)
    #: Durable replay cursor. Canonically ordered emissions at or before this
    #: pair have already been folded and must not mutate counters on retry.
    last_observed_at_utc: datetime | None = None
    last_source_event_id: str | None = Field(default=None, max_length=240)
    evidence_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    state_version: int = Field(default=0, ge=0)
    valid_for_execution: Literal[False] = False
    execution_authority: Literal[False] = False

    @field_validator(
        "first_formed_at_utc",
        "last_pulse_at_utc",
        "last_confirmed_at_utc",
        "expires_at_utc",
        "last_observed_at_utc",
    )
    @classmethod
    def _state_times_are_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value, "microboost state timestamp")

    @model_validator(mode="after")
    def _counts_are_coherent(self) -> MicroboostState:
        if self.peak_effective_ticks < self.current_effective_ticks:
            raise ValueError("peak_effective_ticks cannot fall below current_effective_ticks")
        if self.state != "NONE" and self.first_formed_at_utc is None:
            raise ValueError("a non-NONE Microboost state requires first_formed_at_utc")
        if self.independent_pulse_count == 0 and self.reinforcement_count:
            raise ValueError("reinforcement requires at least one formed pulse")
        if (self.last_observed_at_utc is None) != (self.last_source_event_id is None):
            raise ValueError("durable replay cursor requires both timestamp and source event ID")
        return self

    @property
    def sticky_ratio(self) -> float | None:
        """Share of Microboost snapshots that were carried, not pulses.

        This is the number the raw ``microboost_detected`` percentage hides.  A
        high ratio means the state is persisting, not that pressure is repeating.
        """
        if not self.observed_snapshot_count:
            return None
        return self.carried_snapshot_count / self.observed_snapshot_count

    @property
    def is_active(self) -> bool:
        return self.state in {"ACTIVE", "WEAKENING"}


__all__ = [
    "INDEPENDENT_PULSE_TRANSITIONS",
    "MICROBOOST_PULSE_CONTRACT_VERSION",
    "TERMINAL_PULSE_TRANSITIONS",
    "MicroboostPulseEvent",
    "MicroboostPulseTransition",
    "MicroboostState",
    "MicroboostStateName",
    "PulseDirection",
]
