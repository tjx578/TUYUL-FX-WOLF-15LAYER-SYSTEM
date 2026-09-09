"""Immutable normalized pressure-emission contract for Strategy 5S-CR V3.

This is a read model, not a strategy decision.  It preserves source facts
across legacy replay and the durable LIVE pressure outbox while pinning every
execution capability off.  In particular, none of the lineage fields below is
an analysis-lifecycle, context-epoch, risk, campaign, or command authority.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PRESSURE_EMISSION_V3_CONTRACT_VERSION = "pressure-emission.v3"
PRESSURE_EMISSION_V3_ADAPTER_VERSION = "pressure-emission-v3.adapter.v1"

NormalizationProfile = Literal["LEGACY_580", "LIVE_PRESSURE_OUTBOX"]
NormalizationStatus = Literal["COMPLETE", "PARTIAL", "QUARANTINED"]
PressureDirection = Literal["BUY", "SELL"]


class FrozenEmissionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


class PressureEmissionIdentityV3(FrozenEmissionModel):
    transport_event_id: str = Field(..., min_length=1, max_length=240)
    source_payload_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    semantic_projection_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    source_schema_version: str = Field(..., min_length=1, max_length=100)
    adapter_version: Literal["pressure-emission-v3.adapter.v1"] = PRESSURE_EMISSION_V3_ADAPTER_VERSION
    normalization_profile: NormalizationProfile


class PressureEmissionTimeV3(FrozenEmissionModel):
    event_time_utc: datetime
    received_at_utc: datetime | None = None

    @field_validator("event_time_utc", "received_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value, "pressure-emission timestamp")


class PressureEmissionDeploymentV3(FrozenEmissionModel):
    deployment_id: str | None = Field(default=None, max_length=200)
    commit_sha: str | None = Field(default=None, max_length=100)
    replica_id: str | None = Field(default=None, max_length=200)


class PressureEmissionLineageV3(FrozenEmissionModel):
    cluster_id: str | None = Field(default=None, max_length=240)
    pressure_lifecycle_key: str | None = Field(default=None, max_length=500)
    source_clean_block_id: str | None = Field(default=None, max_length=500)
    source_watch_id: str | None = Field(default=None, max_length=500)
    active_block_id: str | None = Field(default=None, max_length=240)
    admission_event_id: str | None = Field(default=None, pattern=r"^5scr-admission:[0-9a-f]{32}$")


class PressureEmissionFactsV3(FrozenEmissionModel):
    raw_direction: PressureDirection | None = None
    candidate_direction: PressureDirection | None = None
    watch_direction: PressureDirection | None = None
    block_direction: PressureDirection | None = None
    pressure_seen: bool | None = None
    pair_eligible_for_analysis: bool | None = None
    allowed_quorum_reached: bool | None = None
    source_stage: str | None = Field(default=None, max_length=100)
    source_family: str | None = Field(default=None, max_length=100)
    effective_ticks: int | None = Field(default=None, ge=0)
    event_count: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    density: float | None = Field(default=None, ge=0)


class MicroboostSnapshotV3(FrozenEmissionModel):
    detected: bool | None = None
    level: str | None = Field(default=None, max_length=100)
    strength: str | None = Field(default=None, max_length=100)


class PressurePriceFactsV3(FrozenEmissionModel):
    reference_price: float | None = Field(default=None, gt=0)
    reference_price_source: str | None = Field(default=None, max_length=100)
    observed_price: float | None = Field(default=None, gt=0)
    observed_price_source: str | None = Field(default=None, max_length=100)
    observed_price_time_utc: datetime | None = None
    observed_price_status: str | None = Field(default=None, max_length=100)
    price_lineage_version: int | None = Field(default=None, ge=1)

    @field_validator("observed_price_time_utc")
    @classmethod
    def _observed_time_is_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value, "observed-price timestamp")


class PressureContextSeedV3(FrozenEmissionModel):
    daily_bias: str | None = Field(default=None, max_length=100)
    h4_structure: str | None = Field(default=None, max_length=100)
    price_location: str | None = Field(default=None, max_length=100)
    liquidity_context: str | None = Field(default=None, max_length=100)
    allowed_playbook: str | None = Field(default=None, max_length=200)
    pressure_resolution: str | None = Field(default=None, max_length=100)
    material_context_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    context_epoch_reference: str | None = Field(
        default=None,
        pattern=r"^5scr-context:[0-9a-f]{32}$",
    )


class PressureSourceSafetyV3(FrozenEmissionModel):
    final_direction: Literal["WAIT"] = "WAIT"
    valid_for_execution: Literal[False] = False
    tradeplan_valid: Literal[False] = False
    execution_valid_now: Literal[False] = False


class PressureNormalizationV3(FrozenEmissionModel):
    status: NormalizationStatus
    missing_fields: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _diagnostics_are_canonical(self) -> PressureNormalizationV3:
        if self.missing_fields != tuple(sorted(set(self.missing_fields))):
            raise ValueError("missing_fields must be sorted and unique")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("reason_codes must be sorted and unique")
        if self.status == "COMPLETE" and self.missing_fields:
            raise ValueError("COMPLETE normalization cannot carry missing fields")
        if self.status == "QUARANTINED" and not self.reason_codes:
            raise ValueError("QUARANTINED normalization requires a reason code")
        return self


class CanonicalPressureEmissionV3(FrozenEmissionModel):
    """One source pressure emission normalized without downstream authority."""

    contract_version: Literal["pressure-emission.v3"] = PRESSURE_EMISSION_V3_CONTRACT_VERSION
    identity: PressureEmissionIdentityV3
    time: PressureEmissionTimeV3
    deployment: PressureEmissionDeploymentV3
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    source_lineage: PressureEmissionLineageV3
    pressure: PressureEmissionFactsV3
    microboost_snapshot: MicroboostSnapshotV3
    price: PressurePriceFactsV3
    context_seed: PressureContextSeedV3
    source_safety: PressureSourceSafetyV3 = Field(default_factory=PressureSourceSafetyV3)
    normalization: PressureNormalizationV3
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _lineage_is_not_domain_authority(self) -> CanonicalPressureEmissionV3:
        values = {
            self.identity.transport_event_id,
            self.source_lineage.cluster_id,
            self.source_lineage.pressure_lifecycle_key,
            self.source_lineage.source_clean_block_id,
            self.source_lineage.source_watch_id,
        }
        forbidden_prefixes = ("5scr-lifecycle:", "5scr-context:", "5scr-campaign:")
        if any(value and value.startswith(forbidden_prefixes) for value in values):
            raise ValueError("transport/source lineage cannot impersonate downstream domain authority")
        return self

    def canonical_bytes(self) -> bytes:
        """Stable serialization for deterministic replay comparisons."""

        payload: dict[str, Any] = self.model_dump(mode="json")
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


__all__ = [
    "PRESSURE_EMISSION_V3_ADAPTER_VERSION",
    "PRESSURE_EMISSION_V3_CONTRACT_VERSION",
    "CanonicalPressureEmissionV3",
    "MicroboostSnapshotV3",
    "NormalizationProfile",
    "NormalizationStatus",
    "PressureContextSeedV3",
    "PressureDirection",
    "PressureEmissionDeploymentV3",
    "PressureEmissionFactsV3",
    "PressureEmissionIdentityV3",
    "PressureEmissionLineageV3",
    "PressureEmissionTimeV3",
    "PressureNormalizationV3",
    "PressurePriceFactsV3",
    "PressureSourceSafetyV3",
]
