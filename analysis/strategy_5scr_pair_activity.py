"""Pure v3.1 symbol-activity evaluator with explicit coverage and policy binding.

No runtime defaults, directional grant conversion, database writer or execution
sink is provided. Legacy raw-ledger.v2 remains unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from analysis.strategy_5scr_raw_admission_blocks import (
    is_raw_signal_throttle_authority,
    raw_signal_throttle_direction,
    raw_signal_throttle_event_id,
)
from contracts.strategy_5scr_pair_activity import (
    PAIR_ACTIVITY_RULE_VERSION,
    LogicalRawActivityObservationV1,
    PairActivityAuditV31,
    PairActivityEvaluationV31,
    PairActivityObservationNormalizationV1,
    PairActivityPolicyV31,
    RawActivityCoverageV31,
    RawActivityObservationV31,
    activity_hash,
    direction_quality,
    observation_hash,
)


def _value(event: Any, key: str, default: Any = None) -> Any:
    return event.get(key, default) if isinstance(event, dict) else getattr(event, key, default)


def pair_activity_raw_event_id(event: Any) -> str:
    """Version new source-bound facts; retain exact historical IDs when unbound."""
    source_id = _value(event, "source_observation_id")
    schema = _value(event, "source_observation_schema")
    legacy_id = raw_signal_throttle_event_id(event)
    if source_id is None and schema is None:
        return legacy_id
    if (
        not isinstance(source_id, str)
        or not source_id.strip()
        or len(source_id) > 200
        or schema != "signal-throttle-observation.v1"
    ):
        raise ValueError("source observation identity requires a supported schema and nonempty identifier")
    return activity_hash(["5scr.raw-observation-fact.v1", legacy_id, schema, source_id])


def normalize_pair_activity_observations(raw_events: Iterable[Any]) -> PairActivityObservationNormalizationV1:
    """Deduplicate delivery and explicit source twins while retaining all raw facts.

    Timestamp and scanner cycle never imply shared observation identity. Source
    identifiers must survive delivery/restart; this function never fabricates one.
    Logical observations are not Microboost pulses or execution authority.
    """
    observations: dict[str, RawActivityObservationV31] = {}
    bindings: dict[str, tuple[str | None, str | None]] = {}
    groups: dict[str, list[RawActivityObservationV31]] = {}
    group_bindings: dict[str, tuple[str | None, str | None]] = {}
    duplicates = skipped = 0
    for event in raw_events:
        if not is_raw_signal_throttle_authority(event):
            if _value(event, "pressure_source") == "SignalThrottle" and _value(event, "source_stream") in {
                "RAW_THROTTLED",
                "ALLOWED",
                "DOWNGRADED",
            }:
                raise ValueError("invalid raw-authority event cannot be silently dropped")
            skipped += 1
            continue
        source_id = _value(event, "source_observation_id")
        schema = _value(event, "source_observation_schema")
        normalized = RawActivityObservationV31.model_validate(
            {
                "raw_event_id": pair_activity_raw_event_id(event),
                "symbol": str(_value(event, "symbol") or "").strip().upper(),
                "deployment_id": _value(event, "deployment_id"),
                "scanner_cycle_id": _value(event, "scanner_cycle_id"),
                "occurred_at_utc": _value(event, "timestamp"),
                "direction_quality": raw_signal_throttle_direction(event) or "UNKNOWN",
            }
        )
        binding = (source_id, schema)
        if normalized.raw_event_id in observations:
            if observations[normalized.raw_event_id] != normalized or bindings[normalized.raw_event_id] != binding:
                raise ValueError("conflicting raw-event identity or source observation binding")
            duplicates += 1
            continue
        observations[normalized.raw_event_id] = normalized
        bindings[normalized.raw_event_id] = binding
        observation_id = activity_hash(
            [schema, normalized.deployment_id, source_id]
            if source_id is not None
            else ["raw-event-identity.v1", normalized.raw_event_id]
        )
        groups.setdefault(observation_id, []).append(normalized)
        group_bindings[observation_id] = binding
    ordered = tuple(sorted(observations.values(), key=lambda event: (event.occurred_at_utc, event.raw_event_id)))
    logical = []
    for observation_id, members in groups.items():
        source_id, schema = group_bindings[observation_id]
        quality = direction_quality(tuple(members))
        if quality == "CONFLICT":
            raise ValueError("source observation identity conflicts with direction quality")
        logical.append(
            LogicalRawActivityObservationV1(
                observation_id=observation_id,
                identity_basis="SOURCE_OBSERVATION_ID" if source_id is not None else "RAW_EVENT_ID",
                source_observation_id=source_id,
                source_observation_schema=schema,
                symbol=members[0].symbol,
                deployment_id=members[0].deployment_id,
                occurred_at_utc=members[0].occurred_at_utc,
                source_raw_event_ids=tuple(sorted(item.raw_event_id for item in members)),
                direction_quality=quality,
            )
        )
    return PairActivityObservationNormalizationV1(
        raw_observations=ordered,
        logical_observations=tuple(sorted(logical, key=lambda item: (item.occurred_at_utc, item.observation_id))),
        raw_event_count=len(ordered),
        logical_observation_count=len(logical),
        duplicate_delivery_count=duplicates,
        skipped_non_authority_event_count=skipped,
        raw_population_hash=observation_hash(ordered),
    )


def _normalize(raw_events: Iterable[Any]) -> tuple[tuple[RawActivityObservationV31, ...], int, int]:
    normalized = normalize_pair_activity_observations(raw_events)
    return (
        normalized.raw_observations,
        normalized.duplicate_delivery_count,
        normalized.skipped_non_authority_event_count,
    )


def pair_activity_ledger_hash(raw_events: Iterable[Any]) -> str:
    """Compute population identity only; this does not attest raw completeness."""
    observations, _, _ = _normalize(raw_events)
    return observation_hash(observations)


def _validated_previous(items: Iterable[PairActivityEvaluationV31]) -> tuple[PairActivityEvaluationV31, ...]:
    # model_copy/model_construct must not bypass persistence receipt validation.
    previous = tuple(PairActivityEvaluationV31.model_validate(item.model_dump(mode="json")) for item in items)
    if len({item.activity_id for item in previous}) != len(previous):
        raise ValueError("previous evaluations must contain one latest receipt per activity")
    return previous


def _evaluation(
    events: tuple[RawActivityObservationV31, ...],
    *,
    coverage: RawActivityCoverageV31,
    coverage_status: str,
    policy: PairActivityPolicyV31 | None,
    decision_at: datetime,
    global_observed_through: datetime,
    finalizer: RawActivityObservationV31 | None,
    previous: tuple[PairActivityEvaluationV31, ...],
) -> PairActivityEvaluationV31:
    first, last = events[0], events[-1]
    identity = [PAIR_ACTIVITY_RULE_VERSION, coverage.ledger_id, first.deployment_id, first.symbol, first.raw_event_id]
    activity_id = "5scr-activity-v31:" + activity_hash(identity)[7:39]
    duration = (last.occurred_at_utc - first.occurred_at_utc).total_seconds()
    gaps = [(b.occurred_at_utc - a.occurred_at_utc).total_seconds() for a, b in zip(events, events[1:], strict=False)]
    maximum_gap = max(gaps, default=0.0)
    related = [
        old
        for old in previous
        if old.ledger_id == coverage.ledger_id
        and old.deployment_id == first.deployment_id
        and old.symbol == first.symbol
        and old.block_started_at_utc <= last.occurred_at_utc
        and old.block_observed_through_utc >= first.occurred_at_utc
        and (old.admission_id or old.previous_admission_id)
    ]
    previous_id = (related[0].admission_id or related[0].previous_admission_id) if related else None
    decision, reason = "PENDING", "PENDING_THRESHOLD"
    admission_id = admission_lineage = admitted_at = valid_until = None
    crossing = next(
        (
            event.occurred_at_utc
            for event in events
            if (event.occurred_at_utc - first.occurred_at_utc).total_seconds() >= 300
        ),
        None,
    )
    candidate_prefix = tuple(event for event in events if crossing is not None and event.occurred_at_utc <= crossing)
    candidate_lineage = observation_hash(candidate_prefix) if candidate_prefix else None
    conflict = any(
        old.activity_id != activity_id
        or old.admission_lineage_hash != candidate_lineage
        or old.policy != policy
        or old.previous_admission_id is not None
        and old.admission_id is None
        for old in related
    )
    if conflict:
        decision, reason = "RECONCILIATION_REQUIRED", "IMMUTABLE_ADMISSION_LINEAGE_CHANGED"
    elif last.occurred_at_utc > decision_at or coverage.window_end_utc > decision_at:
        decision, reason = "SUSPENDED", "FUTURE_RAW_EVIDENCE"
    elif coverage_status != "COMPLETE":
        decision, reason = "SUSPENDED", "INDETERMINATE_RAW_AUTHORITY_COVERAGE"
    elif first.occurred_at_utc < coverage.window_start_utc or last.occurred_at_utc > coverage.window_end_utc:
        decision, reason = "SUSPENDED", "RAW_COVERAGE_WINDOW_MISMATCH"
    elif policy is None:
        decision, reason = "SUSPENDED", "PAIR_ACTIVITY_POLICY_UNBOUND"
    elif (
        max(
            maximum_gap,
            ((finalizer.occurred_at_utc if finalizer else decision_at) - last.occurred_at_utc).total_seconds(),
            (decision_at - global_observed_through).total_seconds(),
        )
        > policy.maximum_source_gap_seconds
    ):
        decision, reason = "SUSPENDED", "SUSPENDED_SOURCE_GAP"
    elif crossing is not None:
        expires = crossing + timedelta(seconds=policy.grant_ttl_seconds)
        if decision_at >= expires:
            decision, reason = "SUSPENDED", "EXPIRED_GRANT"
        else:
            decision, reason = "GRANTED", "PAIR_ACTIVITY_THRESHOLD_REACHED"
            admitted_at, valid_until, admission_lineage = crossing, expires, candidate_lineage
            admission_id = (
                "5scr-activity-admission-v31:"
                + activity_hash([activity_id, policy.model_dump(mode="json"), admission_lineage])[7:39]
            )
    elif finalizer is not None:
        reason = "FINALIZED_BELOW_THRESHOLD"
    payload = {
        "activity_id": activity_id,
        "ledger_id": coverage.ledger_id,
        "symbol": first.symbol,
        "deployment_id": first.deployment_id,
        "decision": decision,
        "reason_code": reason,
        "policy": policy.model_dump(mode="json") if policy else None,
        "coverage": coverage.model_dump(mode="json"),
        "evaluated_at_utc": decision_at.isoformat().replace("+00:00", "Z"),
        "observations": [event.model_dump(mode="json") for event in events],
        "source_lineage_hash": observation_hash(events),
        "direction_quality": direction_quality(events),
        "block_started_at_utc": first.occurred_at_utc.isoformat().replace("+00:00", "Z"),
        "block_observed_through_utc": last.occurred_at_utc.isoformat().replace("+00:00", "Z"),
        "global_observed_through_utc": global_observed_through.isoformat().replace("+00:00", "Z"),
        "finalized_at_utc": finalizer.occurred_at_utc.isoformat().replace("+00:00", "Z") if finalizer else None,
        "duration_seconds": duration,
        "maximum_observed_gap_seconds": maximum_gap,
        "finalized_by_raw_event_id": finalizer.raw_event_id if finalizer else None,
        "admission_id": admission_id,
        "admission_lineage_hash": admission_lineage,
        "admitted_at_utc": admitted_at.isoformat().replace("+00:00", "Z") if admitted_at else None,
        "valid_until_utc": valid_until.isoformat().replace("+00:00", "Z") if valid_until else None,
        "previous_admission_id": previous_id if decision != "GRANTED" else None,
        "event": "pair_activity_evaluated",
        "rule_version": PAIR_ACTIVITY_RULE_VERSION,
        "hypothesis_authority": False,
        "risk_authority": False,
        "execution_authority": False,
        "valid_for_execution": False,
    }
    payload["evaluation_id"] = "5scr-activity-eval-v31:" + activity_hash(payload)[7:39]
    return PairActivityEvaluationV31.model_validate(payload)


def build_pair_activity_audit(
    raw_events: Iterable[Any],
    *,
    coverage: RawActivityCoverageV31,
    policy: PairActivityPolicyV31 | None,
    decision_at_utc: datetime,
    previous_evaluations: Iterable[PairActivityEvaluationV31] = (),
) -> PairActivityAuditV31:
    """Evaluate complete global raw input without inventing coverage or policy.

    Replaying persisted evaluation JSON alongside retained raw ledger preserves
    admission IDs. A changed pre-admission lineage requires reconciliation.
    Receipt counts remain raw facts. The shared normalizer validates explicit
    logical observation identities without altering legacy receipt hashes;
    scanner IDs and derived telemetry never imply a shared observation.
    """
    if decision_at_utc.tzinfo is None or decision_at_utc.utcoffset() is None:
        raise ValueError("decision time requires an explicit UTC offset")
    decision_at = decision_at_utc.astimezone(UTC)
    coverage = RawActivityCoverageV31.model_validate(coverage.model_dump(mode="json"))
    if policy is not None:
        policy = PairActivityPolicyV31.model_validate(policy.model_dump(mode="json"))
    previous = _validated_previous(previous_evaluations)
    observations, duplicates, skipped = _normalize(raw_events)
    if any(event.deployment_id != coverage.deployment_id for event in observations):
        raise ValueError("raw deployment differs from bound coverage")
    ledger_hash = observation_hash(observations)
    coverage_status = coverage.status if coverage.source_ledger_hash in (None, ledger_hash) else "INCOMPLETE"
    if coverage_status == "COMPLETE" and (
        coverage.window_end_utc > decision_at
        or any(
            event.occurred_at_utc < coverage.window_start_utc
            or event.occurred_at_utc > coverage.window_end_utc
            or event.occurred_at_utc > decision_at
            for event in observations
        )
    ):
        coverage_status = "INCOMPLETE"
    for old in previous:
        if old.ledger_id != coverage.ledger_id or old.deployment_id != coverage.deployment_id:
            raise ValueError("previous receipt belongs to another raw ledger scope")
        if old.evaluated_at_utc > decision_at:
            raise ValueError("previous receipt lies after replay decision time")
        if (old.admission_id or old.previous_admission_id) and not any(
            event.symbol == old.symbol
            and old.block_started_at_utc <= event.occurred_at_utc <= old.block_observed_through_utc
            for event in observations
        ):
            raise ValueError("previous admitted activity is missing from raw replay; reconciliation required")
    blocks: list[tuple[tuple[RawActivityObservationV31, ...], RawActivityObservationV31 | None]] = []
    current: list[RawActivityObservationV31] = []
    for event in observations:
        if current and current[-1].symbol != event.symbol:
            blocks.append((tuple(current), event))
            current = []
        current.append(event)
    if current:
        blocks.append((tuple(current), None))
    evaluations = tuple(
        _evaluation(
            events,
            coverage=coverage,
            coverage_status=coverage_status,
            policy=policy,
            decision_at=decision_at,
            global_observed_through=observations[-1].occurred_at_utc,
            finalizer=finalizer,
            previous=previous,
        )
        for events, finalizer in blocks
    )
    empty_reason = (
        None
        if observations
        else ("NO_RAW_ACTIVITY" if coverage_status == "COMPLETE" else "INDETERMINATE_RAW_AUTHORITY_COVERAGE")
    )
    return PairActivityAuditV31(
        coverage=coverage,
        policy=policy,
        evaluated_at_utc=decision_at,
        evaluations=evaluations,
        raw_event_count=len(observations),
        duplicate_event_count=duplicates,
        skipped_non_authority_event_count=skipped,
        source_ledger_hash=ledger_hash,
        coverage_status=coverage_status,
        empty_reason=empty_reason,
    )
