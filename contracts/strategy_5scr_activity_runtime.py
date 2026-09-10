"""Explicit non-executable bindings for a durable raw activity source."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from contracts.strategy_5scr_pair_activity import (
    HASH_PATTERN,
    FrozenActivityModel,
    PairActivityPolicyV31,
    activity_hash,
)

SELECTED_SSOT_SHA256 = "6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902"


class ActivityRuntimeBindingV1(FrozenActivityModel):
    schema_version: Literal["5scr.activity-runtime-binding.v1"] = "5scr.activity-runtime-binding.v1"
    ledger_id: str = Field(..., min_length=1, max_length=200)
    deployment_id: str = Field(..., min_length=1, max_length=200)
    producer_id: str = Field(..., min_length=1, max_length=200)
    source_scope_id: str = Field(..., min_length=1, max_length=200)
    coverage_attestor_id: str = Field(..., min_length=1, max_length=200)
    environment_class: Literal["DISPOSABLE_TEST", "SHADOW"]
    ssot_sha256: Literal[SELECTED_SSOT_SHA256] = SELECTED_SSOT_SHA256
    policy: PairActivityPolicyV31 | None = None
    window_start_utc: datetime
    maximum_ledger_events: int = Field(..., ge=3, le=100_000)
    recovery_overlap_seconds: int = Field(..., ge=0)
    execution_authority: Literal[False] = False

    @property
    def binding_hash(self) -> str:
        return activity_hash(self.model_dump(mode="json"))


class ActivityCoverageCheckpointV1(FrozenActivityModel):
    """Producer/attestor statement of expected population, never inferred from RAM.

    Authenticity belongs to the configured source/attestor boundary. The consumer
    verifies binding, expected hash/count and time against durable facts. This is
    not an assertion that an arbitrary attestor is approved for production.
    """

    schema_version: Literal["5scr.activity-coverage-checkpoint.v1"] = "5scr.activity-coverage-checkpoint.v1"
    binding_hash: str = Field(..., pattern=HASH_PATTERN)
    attestor_id: str = Field(..., min_length=1, max_length=200)
    window_start_utc: datetime
    window_end_utc: datetime
    expected_raw_count: int = Field(..., ge=0)
    expected_raw_hash: str = Field(..., pattern=HASH_PATTERN)
    status: Literal["COMPLETE", "INCOMPLETE", "UNKNOWN"]

    @model_validator(mode="after")
    def ordered_window(self) -> Self:
        if self.window_end_utc < self.window_start_utc:
            raise ValueError("checkpoint window is reversed")
        return self

    @property
    def checkpoint_id(self) -> str:
        return activity_hash(self.model_dump(mode="json"))
