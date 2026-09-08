"""Versioned activity-only admission receipts; legacy directional grants are unchanged."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PAIR_ACTIVITY_RULE_VERSION = "5scr.pair-activity.v3.1"
HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"


def activity_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class FrozenActivityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def aware_times(cls, value: object) -> object:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("activity timestamps require an explicit UTC offset")
            return value.astimezone(UTC)
        return value


class PairActivityPolicyV31(FrozenActivityModel):
    policy_id: str = Field(..., min_length=1, max_length=200)
    maximum_source_gap_seconds: float = Field(..., gt=0)
    grant_ttl_seconds: int = Field(..., gt=0)


class RawActivityCoverageV31(FrozenActivityModel):
    status: Literal["COMPLETE", "INCOMPLETE", "UNKNOWN"]
    ledger_id: str = Field(..., min_length=1, max_length=200)
    deployment_id: str = Field(..., min_length=1, max_length=200)
    window_start_utc: datetime
    window_end_utc: datetime
    source_ledger_hash: str | None = Field(default=None, pattern=HASH_PATTERN)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.window_end_utc < self.window_start_utc:
            raise ValueError("coverage window is reversed")
        if self.status == "COMPLETE" and self.source_ledger_hash is None:
            raise ValueError("complete coverage requires a bound ledger hash")
        return self


class RawActivityObservationV31(FrozenActivityModel):
    raw_event_id: str = Field(..., pattern=HASH_PATTERN)
    symbol: str = Field(..., pattern=r"^[A-Z0-9._-]{3,32}$")
    deployment_id: str = Field(..., min_length=1, max_length=200)
    scanner_cycle_id: str = Field(..., min_length=1, max_length=200)
    occurred_at_utc: datetime
    direction_quality: Literal["BUY", "SELL", "UNKNOWN"]


def direction_quality(observations: tuple[RawActivityObservationV31, ...]) -> str:
    known = {event.direction_quality for event in observations} - {"UNKNOWN"}
    if len(known) > 1:
        return "CONFLICT"
    if any(event.direction_quality == "UNKNOWN" for event in observations):
        return "UNKNOWN"
    return next(iter(known), "UNKNOWN")


def observation_hash(observations: tuple[RawActivityObservationV31, ...]) -> str:
    return activity_hash([event.model_dump(mode="json") for event in observations])


class PairActivityEvaluationV31(FrozenActivityModel):
    event: Literal["pair_activity_evaluated"] = "pair_activity_evaluated"
    rule_version: Literal["5scr.pair-activity.v3.1"] = PAIR_ACTIVITY_RULE_VERSION
    activity_id: str = Field(..., pattern=r"^5scr-activity-v31:[0-9a-f]{32}$")
    evaluation_id: str = Field(..., pattern=r"^5scr-activity-eval-v31:[0-9a-f]{32}$")
    ledger_id: str
    symbol: str
    deployment_id: str
    decision: Literal["PENDING", "GRANTED", "SUSPENDED", "RECONCILIATION_REQUIRED"]
    reason_code: str
    policy: PairActivityPolicyV31 | None
    coverage: RawActivityCoverageV31
    evaluated_at_utc: datetime
    observations: tuple[RawActivityObservationV31, ...] = Field(..., min_length=1)
    source_lineage_hash: str = Field(..., pattern=HASH_PATTERN)
    direction_quality: Literal["BUY", "SELL", "CONFLICT", "UNKNOWN"]
    block_started_at_utc: datetime
    block_observed_through_utc: datetime
    global_observed_through_utc: datetime
    finalized_at_utc: datetime | None = None
    duration_seconds: float = Field(..., ge=0)
    maximum_observed_gap_seconds: float = Field(..., ge=0)
    finalized_by_raw_event_id: str | None = Field(default=None, pattern=HASH_PATTERN)
    admission_id: str | None = Field(default=None, pattern=r"^5scr-activity-admission-v31:[0-9a-f]{32}$")
    admission_lineage_hash: str | None = Field(default=None, pattern=HASH_PATTERN)
    admitted_at_utc: datetime | None = None
    valid_until_utc: datetime | None = None
    previous_admission_id: str | None = Field(default=None, pattern=r"^5scr-activity-admission-v31:[0-9a-f]{32}$")
    hypothesis_authority: Literal[False] = False
    risk_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    valid_for_execution: Literal[False] = False

    @model_validator(mode="after")
    def receipt_consistency(self) -> Self:
        events = self.observations
        ordered = tuple(sorted(events, key=lambda event: (event.occurred_at_utc, event.raw_event_id)))
        if events != ordered or len({event.raw_event_id for event in events}) != len(events):
            raise ValueError("receipt observations must be ordered and unique")
        if any(event.symbol != self.symbol or event.deployment_id != self.deployment_id for event in events):
            raise ValueError("receipt observations cross activity scope")
        if self.ledger_id != self.coverage.ledger_id or self.deployment_id != self.coverage.deployment_id:
            raise ValueError("coverage and activity scope differ")
        if (
            self.block_started_at_utc != events[0].occurred_at_utc
            or self.block_observed_through_utc != events[-1].occurred_at_utc
        ):
            raise ValueError("receipt bounds differ from observations")
        if self.duration_seconds != (events[-1].occurred_at_utc - events[0].occurred_at_utc).total_seconds():
            raise ValueError("receipt duration differs from observations")
        gaps = [
            (b.occurred_at_utc - a.occurred_at_utc).total_seconds() for a, b in zip(events, events[1:], strict=False)
        ]
        if self.maximum_observed_gap_seconds != max(gaps, default=0.0):
            raise ValueError("receipt gap differs from observations")
        if self.direction_quality != direction_quality(events) or self.source_lineage_hash != observation_hash(events):
            raise ValueError("receipt quality or lineage differs from observations")
        identity = [PAIR_ACTIVITY_RULE_VERSION, self.ledger_id, self.deployment_id, self.symbol, events[0].raw_event_id]
        if self.activity_id != "5scr-activity-v31:" + activity_hash(identity)[7:39]:
            raise ValueError("activity identity mismatch")
        if (self.finalized_at_utc is None) != (self.finalized_by_raw_event_id is None):
            raise ValueError("finalizer identity and timestamp must be paired")
        if self.global_observed_through_utc < self.block_observed_through_utc:
            raise ValueError("global watermark precedes activity observations")
        if (
            self.finalized_at_utc is not None
            and not self.block_observed_through_utc <= self.finalized_at_utc <= self.global_observed_through_utc
        ):
            raise ValueError("finalizer timestamp lies outside global raw ordering")
        admission_values = (self.admission_id, self.admission_lineage_hash, self.admitted_at_utc, self.valid_until_utc)
        if self.decision == "GRANTED":
            if (
                self.policy is None
                or self.coverage.status != "COMPLETE"
                or any(value is None for value in admission_values)
            ):
                raise ValueError("grant requires policy, complete coverage and admission lineage")
            if (
                max(
                    self.maximum_observed_gap_seconds,
                    (
                        (self.finalized_at_utc or self.evaluated_at_utc) - self.block_observed_through_utc
                    ).total_seconds(),
                    (self.evaluated_at_utc - self.global_observed_through_utc).total_seconds(),
                )
                > self.policy.maximum_source_gap_seconds
            ):
                raise ValueError("grant cannot bridge a source gap")
            if (
                self.block_started_at_utc < self.coverage.window_start_utc
                or self.block_observed_through_utc > self.coverage.window_end_utc
            ):
                raise ValueError("grant lies outside coverage")
            if (
                self.coverage.window_end_utc > self.evaluated_at_utc
                or self.global_observed_through_utc > self.coverage.window_end_utc
            ):
                raise ValueError("grant uses future coverage")
            prefix = tuple(event for event in events if event.occurred_at_utc <= self.admitted_at_utc)
            crossing = next(
                (
                    event.occurred_at_utc
                    for event in events
                    if (event.occurred_at_utc - events[0].occurred_at_utc).total_seconds() >= 300
                ),
                None,
            )
            if self.admitted_at_utc != crossing or self.admission_lineage_hash != observation_hash(prefix):
                raise ValueError("grant must freeze at the first 300-second crossing")
            expected = activity_hash(
                [self.activity_id, self.policy.model_dump(mode="json"), self.admission_lineage_hash]
            )
            if self.admission_id != "5scr-activity-admission-v31:" + expected[7:39]:
                raise ValueError("admission identity mismatch")
            if (self.valid_until_utc - self.admitted_at_utc).total_seconds() != self.policy.grant_ttl_seconds:
                raise ValueError("admission TTL differs from bound policy")
            if self.evaluated_at_utc >= self.valid_until_utc:
                raise ValueError("expired grant cannot attach new evidence")
        elif any(value is not None for value in admission_values):
            raise ValueError("non-granted evaluation cannot carry active admission")
        expected_eval = activity_hash(self.model_dump(mode="json", exclude={"evaluation_id"}))
        if self.evaluation_id != "5scr-activity-eval-v31:" + expected_eval[7:39]:
            raise ValueError("evaluation identity mismatch")
        return self


class PairActivityAuditV31(FrozenActivityModel):
    rule_version: Literal["5scr.pair-activity.v3.1"] = PAIR_ACTIVITY_RULE_VERSION
    coverage: RawActivityCoverageV31
    policy: PairActivityPolicyV31 | None
    evaluated_at_utc: datetime
    evaluations: tuple[PairActivityEvaluationV31, ...]
    raw_event_count: int = Field(..., ge=0)
    duplicate_event_count: int = Field(..., ge=0)
    skipped_non_authority_event_count: int = Field(..., ge=0)
    source_ledger_hash: str = Field(..., pattern=HASH_PATTERN)
    coverage_status: Literal["COMPLETE", "INCOMPLETE", "UNKNOWN"]
    empty_reason: str | None = None
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def audit_consistency(self) -> Self:
        events = tuple(
            sorted(
                (event for item in self.evaluations for event in item.observations),
                key=lambda event: (event.occurred_at_utc, event.raw_event_id),
            )
        )
        if len(events) != self.raw_event_count or len({event.raw_event_id for event in events}) != len(events):
            raise ValueError("audit raw population mismatch")
        if observation_hash(events) != self.source_ledger_hash:
            raise ValueError("audit ledger hash mismatch")
        if len({item.activity_id for item in self.evaluations}) != len(self.evaluations):
            raise ValueError("duplicate activity evaluation")
        if any(
            item.coverage != self.coverage
            or item.policy != self.policy
            or item.evaluated_at_utc != self.evaluated_at_utc
            for item in self.evaluations
        ):
            raise ValueError("audit bindings differ from evaluation bindings")
        expected_coverage = (
            self.coverage.status
            if self.coverage.source_ledger_hash in (None, self.source_ledger_hash)
            else "INCOMPLETE"
        )
        if expected_coverage == "COMPLETE" and (
            self.coverage.window_end_utc > self.evaluated_at_utc
            or any(
                event.occurred_at_utc < self.coverage.window_start_utc
                or event.occurred_at_utc > self.coverage.window_end_utc
                or event.occurred_at_utc > self.evaluated_at_utc
                for event in events
            )
        ):
            expected_coverage = "INCOMPLETE"
        blocks: list[list[RawActivityObservationV31]] = []
        for event in events:
            if not blocks or blocks[-1][-1].symbol != event.symbol:
                blocks.append([])
            blocks[-1].append(event)
        if len(blocks) != len(self.evaluations):
            raise ValueError("audit crosses a global symbol interruption")
        for index, (block, item) in enumerate(zip(blocks, self.evaluations, strict=True)):
            finalizer = blocks[index + 1][0].raw_event_id if index + 1 < len(blocks) else None
            finalized_at = blocks[index + 1][0].occurred_at_utc if index + 1 < len(blocks) else None
            if item.global_observed_through_utc != events[-1].occurred_at_utc or item.finalized_at_utc != finalized_at:
                raise ValueError("global or finalizer watermark mismatch")
            if tuple(block) != item.observations or item.finalized_by_raw_event_id != finalizer:
                raise ValueError("audit activity ordering or finalization mismatch")
        expected_empty_reason = (
            None
            if events
            else ("NO_RAW_ACTIVITY" if expected_coverage == "COMPLETE" else "INDETERMINATE_RAW_AUTHORITY_COVERAGE")
        )
        if self.empty_reason != expected_empty_reason:
            raise ValueError("empty coverage classification mismatch")
        if self.coverage_status != expected_coverage:
            raise ValueError("audit coverage classification mismatch")
        if self.coverage_status != "COMPLETE" and any(item.decision == "GRANTED" for item in self.evaluations):
            raise ValueError("incomplete coverage cannot grant activity")
        return self


class LogicalRawActivityObservationV1(FrozenActivityModel):
    """One source observation, never a Microboost transition or order permission."""

    observation_id: str = Field(..., pattern=HASH_PATTERN)
    identity_basis: Literal["SOURCE_OBSERVATION_ID", "RAW_EVENT_ID"]
    source_observation_id: str | None = Field(default=None, min_length=1, max_length=200)
    source_observation_schema: Literal["signal-throttle-observation.v1"] | None = None
    symbol: str
    deployment_id: str
    occurred_at_utc: datetime
    source_raw_event_ids: tuple[str, ...] = Field(..., min_length=1)
    direction_quality: Literal["BUY", "SELL", "UNKNOWN"]

    @model_validator(mode="after")
    def identity_consistency(self) -> Self:
        if tuple(sorted(set(self.source_raw_event_ids))) != self.source_raw_event_ids:
            raise ValueError("logical observation raw identities must be sorted and unique")
        if self.identity_basis == "SOURCE_OBSERVATION_ID":
            if (
                not self.source_observation_id
                or not self.source_observation_id.strip()
                or self.source_observation_schema is None
            ):
                raise ValueError("source observation identity requires its explicit schema and identifier")
            identity = [self.source_observation_schema, self.deployment_id, self.source_observation_id]
        else:
            if (
                self.source_observation_id is not None
                or self.source_observation_schema is not None
                or len(self.source_raw_event_ids) != 1
            ):
                raise ValueError("unbound raw facts cannot be conflated into a logical observation")
            identity = ["raw-event-identity.v1", self.source_raw_event_ids[0]]
        if self.observation_id != activity_hash(identity):
            raise ValueError("logical observation identity mismatch")
        return self


class PairActivityObservationNormalizationV1(FrozenActivityModel):
    schema_version: Literal["5scr.logical-observations.v1"] = "5scr.logical-observations.v1"
    raw_observations: tuple[RawActivityObservationV31, ...]
    logical_observations: tuple[LogicalRawActivityObservationV1, ...]
    raw_event_count: int = Field(..., ge=0)
    logical_observation_count: int = Field(..., ge=0)
    duplicate_delivery_count: int = Field(..., ge=0)
    skipped_non_authority_event_count: int = Field(..., ge=0)
    raw_population_hash: str = Field(..., pattern=HASH_PATTERN)
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def population_consistency(self) -> Self:
        # Revalidate nested instances: model_copy/model_construct are not trust boundaries.
        raw = tuple(
            RawActivityObservationV31.model_validate(item.model_dump(mode="json")) for item in self.raw_observations
        )
        logical = tuple(
            LogicalRawActivityObservationV1.model_validate(item.model_dump(mode="json"))
            for item in self.logical_observations
        )
        if raw != tuple(sorted(raw, key=lambda item: (item.occurred_at_utc, item.raw_event_id))):
            raise ValueError("normalized raw observations must follow canonical ordering")
        population = {item.raw_event_id: item for item in raw}
        if (
            len(population) != len(raw)
            or self.raw_event_count != len(raw)
            or self.raw_population_hash != observation_hash(raw)
        ):
            raise ValueError("normalized raw population mismatch")
        if self.logical_observation_count != len(logical) or len({item.observation_id for item in logical}) != len(
            logical
        ):
            raise ValueError("logical observation population mismatch")
        if logical != tuple(sorted(logical, key=lambda item: (item.occurred_at_utc, item.observation_id))):
            raise ValueError("logical observations must follow canonical ordering")
        by_time: dict[datetime, list[LogicalRawActivityObservationV1]] = {}
        for item in logical:
            by_time.setdefault(item.occurred_at_utc, []).append(item)
        if any(
            len({item.symbol for item in same_time}) > 1
            and any(item.identity_basis == "SOURCE_OBSERVATION_ID" for item in same_time)
            for same_time in by_time.values()
        ):
            raise ValueError("AMBIGUOUS_GLOBAL_SOURCE_ORDER")
        mapped = [raw_id for item in logical for raw_id in item.source_raw_event_ids]
        if len(mapped) != len(set(mapped)) or set(mapped) != set(population):
            raise ValueError("logical mapping must cover each raw fact exactly once")
        for item in logical:
            members = tuple(population[raw_id] for raw_id in item.source_raw_event_ids)
            if any(
                (member.symbol, member.deployment_id, member.occurred_at_utc)
                != (item.symbol, item.deployment_id, item.occurred_at_utc)
                for member in members
            ):
                raise ValueError("source observation identity conflicts with scope or timestamp")
            if len({member.scanner_cycle_id for member in members}) != 1:
                raise ValueError("source observation identity conflicts with scanner lineage")
            quality = direction_quality(members)
            if quality == "CONFLICT" or quality != item.direction_quality:
                raise ValueError("source observation identity conflicts with direction quality")
        return self
