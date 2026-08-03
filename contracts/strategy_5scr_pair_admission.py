"""Canonical, non-executable pair-admission authority for Strategy 5S-CR."""

from __future__ import annotations

from datetime import UTC, datetime
from math import isclose
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PAIR_ADMISSION_RULE_VERSION = "5scr.pair-admission.raw-ledger.v2"
PAIR_ADMISSION_MAX_TTL_SECONDS = 900


class PairAdmissionGrant(BaseModel):
    """Durable proof that the global raw pressure ledger admitted one pair.

    A grant opens analysis only.  Clean-block/watch identifiers remain source
    lineage and cannot substitute for this authority.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event: Literal["pair_admission_granted"] = "pair_admission_granted"
    schema_version: Literal["1.0"] = "1.0"
    rule_version: Literal["5scr.pair-admission.raw-ledger.v2"] = PAIR_ADMISSION_RULE_VERSION
    pair_admission_id: str = Field(..., pattern=r"^5scr-admission:[0-9a-f]{32}$")
    status: Literal["GRANTED"] = "GRANTED"
    ledger_scope: Literal["GLOBAL_SIGNAL_THROTTLE_RAW_LEDGER"] = "GLOBAL_SIGNAL_THROTTLE_RAW_LEDGER"
    deployment_id: str = Field(..., min_length=1, max_length=200)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    direction: Literal["BUY", "SELL"]
    episode_started_at_utc: datetime
    episode_observed_through_utc: datetime
    granted_at_utc: datetime
    expires_at_utc: datetime
    duration_seconds: float = Field(..., ge=300)
    effective_ticks: int = Field(..., ge=3)
    source_event_count: int = Field(..., ge=2)
    max_observed_gap_seconds: float = Field(..., ge=0, le=300)
    source_ledger_event_ids: tuple[str, ...] = Field(..., min_length=2)
    source_scanner_cycle_ids: tuple[str, ...] = Field(..., min_length=1)
    source_ledger_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    source_ledger_ordering: Literal["EVENT_TIME_ASC_RAW_ID_TIEBREAK"] = "EVENT_TIME_ASC_RAW_ID_TIEBREAK"
    lineage_complete: Literal[True] = True
    source_clean_block_ids: tuple[str, ...] = ()
    pair_eligible_for_analysis: Literal[True] = True
    execution_authority: Literal[False] = False

    @field_validator(
        "episode_started_at_utc",
        "episode_observed_through_utc",
        "granted_at_utc",
        "expires_at_utc",
    )
    @classmethod
    def _times_are_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("pair-admission timestamps require a UTC offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _grant_is_consistent(self) -> PairAdmissionGrant:
        if self.episode_observed_through_utc < self.episode_started_at_utc:
            raise ValueError("pair-admission episode end cannot precede start")
        if self.granted_at_utc != self.episode_observed_through_utc:
            raise ValueError("pair admission must be granted at the deterministic raw-ledger boundary")
        if self.expires_at_utc <= self.granted_at_utc:
            raise ValueError("pair admission expiry must follow grant time")
        if (self.expires_at_utc - self.granted_at_utc).total_seconds() > PAIR_ADMISSION_MAX_TTL_SECONDS:
            raise ValueError("pair admission expiry exceeds the canonical maximum TTL")
        observed_duration = (self.episode_observed_through_utc - self.episode_started_at_utc).total_seconds()
        if not isclose(self.duration_seconds, observed_duration, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("pair-admission duration must be derived from raw evidence bounds")
        if self.source_event_count != len(self.source_ledger_event_ids):
            raise ValueError("source event count must match the ordered raw-ledger IDs")
        if self.effective_ticks < self.source_event_count:
            raise ValueError("effective ticks cannot be below the raw source-event count")
        if len(set(self.source_ledger_event_ids)) != len(self.source_ledger_event_ids):
            raise ValueError("source ledger event IDs must be unique")
        if len(set(self.source_scanner_cycle_ids)) != len(self.source_scanner_cycle_ids):
            raise ValueError("source scanner-cycle IDs must be unique")
        if len(set(self.source_clean_block_ids)) != len(self.source_clean_block_ids):
            raise ValueError("source clean-block IDs must be unique")
        return self

    def is_active_at(self, value: datetime) -> bool:
        """Return whether this grant is valid at one timezone-aware instant."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("pair-admission activity timestamp must include a UTC offset")
        at = value.astimezone(UTC)
        return self.granted_at_utc <= at < self.expires_at_utc

    def to_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")


__all__ = ["PAIR_ADMISSION_MAX_TTL_SECONDS", "PAIR_ADMISSION_RULE_VERSION", "PairAdmissionGrant"]
