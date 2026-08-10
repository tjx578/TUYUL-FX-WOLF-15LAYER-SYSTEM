"""Build pair-admission grants exclusively from the global raw ledger."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isclose
from typing import Any

from analysis.strategy_5scr_raw_admission_blocks import (
    is_raw_signal_throttle_authority,
    raw_signal_throttle_direction,
    raw_signal_throttle_event_id,
)
from contracts.strategy_5scr_pair_admission import (
    PAIR_ADMISSION_MAX_TTL_SECONDS,
    PAIR_ADMISSION_RULE_VERSION,
    PairAdmissionGrant,
)

DEFAULT_PAIR_ADMISSION_MIN_DURATION_SECONDS = 300.0
DEFAULT_PAIR_ADMISSION_MIN_EFFECTIVE_TICKS = 3
DEFAULT_PAIR_ADMISSION_TTL_SECONDS = PAIR_ADMISSION_MAX_TTL_SECONDS
DEFAULT_PAIR_ADMISSION_MAX_GAP_SECONDS = 300.0


@dataclass(frozen=True)
class PairAdmissionAudit:
    """Shadow-safe grant/rejection accounting for rollout comparison."""

    grants: tuple[PairAdmissionGrant, ...]
    evaluated_blocks: int
    rejection_counts: dict[str, int]
    evaluations: tuple[dict[str, Any], ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "rule_version": PAIR_ADMISSION_RULE_VERSION,
            "evaluated_blocks": self.evaluated_blocks,
            "granted_blocks": len(self.grants),
            "rejected_blocks": self.evaluated_blocks - len(self.grants),
            "grant_rate": round(len(self.grants) / self.evaluated_blocks, 6) if self.evaluated_blocks else 0.0,
            "rejection_counts": dict(sorted(self.rejection_counts.items())),
            "evaluations": list(self.evaluations),
            "execution_authority": False,
        }


@dataclass(frozen=True)
class _ValidatedRawEvidence:
    events: tuple[Any, ...]
    deployment_id: str
    started_at_utc: datetime
    observed_through_utc: datetime
    duration_seconds: float
    effective_ticks: int
    max_gap_seconds: float
    maximum_allowed_gap_seconds: float
    source_event_ids: tuple[str, ...]
    scanner_cycle_ids: tuple[str, ...]
    ledger_hash: str


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        resolved = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            resolved = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        return None
    return resolved.astimezone(UTC)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _event_effective_ticks(event: Any) -> int:
    """Recompute effective ticks from raw fields; never trust a summary value."""

    try:
        suppressed = int(_value(event, "suppressed", 0) or 0)
    except (TypeError, ValueError):
        suppressed = 0
    return 1 + max(0, suppressed)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _candidate_block_id(block: Any, source_clean_block_id: str | None) -> str:
    """Return a stable audit identity without promoting clean-block lineage."""

    raw_block_id = str(_value(block, "raw_block_id") or "").strip()
    if raw_block_id:
        return raw_block_id
    if source_clean_block_id:
        return source_clean_block_id
    identity = {
        "symbol": str(_value(block, "symbol") or "").strip().upper(),
        "direction": str(_value(block, "direction") or "").strip().upper(),
        "start": _utc(_value(block, "start")),
        "end": _utc(_value(block, "end")),
    }
    digest = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:32]
    return f"5scr-admission-candidate:{digest}"


def _raw_audit_snapshot(block: Any, raw_events: tuple[Any, ...]) -> dict[str, Any]:
    """Compute deterministic diagnostics retained for grants and rejections."""

    symbol = str(_value(block, "symbol") or "").strip().upper()
    start = _utc(_value(block, "start"))
    end = _utc(_value(block, "end"))
    ordered: list[tuple[datetime, Any, str]] = []
    cross_symbol_events = 0
    for event in raw_events:
        timestamp = _utc(_value(event, "timestamp"))
        if timestamp is None:
            continue
        if start is not None and timestamp < start:
            continue
        if end is not None and timestamp > end:
            continue
        if not is_raw_signal_throttle_authority(event):
            continue
        event_symbol = str(_value(event, "symbol") or "").strip().upper()
        if event_symbol != symbol:
            cross_symbol_events += 1
            continue
        ordered.append((timestamp, event, raw_signal_throttle_event_id(event)))
    ordered.sort(key=lambda item: (item[0], item[2]))
    timestamps = tuple(item[0] for item in ordered)
    events = tuple(item[1] for item in ordered)
    event_ids = tuple(item[2] for item in ordered)
    gaps = tuple((timestamps[index] - timestamps[index - 1]).total_seconds() for index in range(1, len(timestamps)))
    decision_at = timestamps[-1] if timestamps else end or start
    return {
        "raw_event_range_start_utc": None if not timestamps else timestamps[0].isoformat(),
        "raw_event_range_end_utc": None if not timestamps else timestamps[-1].isoformat(),
        "calculated_duration_seconds": (
            None if len(timestamps) < 2 else (timestamps[-1] - timestamps[0]).total_seconds()
        ),
        "calculated_max_gap_seconds": None if not gaps else max(gaps),
        "calculated_effective_ticks": sum(_event_effective_ticks(event) for event in events),
        "source_event_count": len(events),
        "source_ledger_event_ids": list(event_ids),
        "raw_lineage_hash": (
            None if not event_ids else "sha256:" + hashlib.sha256("|".join(event_ids).encode("utf-8")).hexdigest()
        ),
        "source_scanner_cycle_ids": list(
            dict.fromkeys(
                str(_value(event, "scanner_cycle_id") or "").strip()
                for event in events
                if str(_value(event, "scanner_cycle_id") or "").strip()
            )
        ),
        "source_deployment_ids": sorted(
            {
                str(_value(event, "deployment_id") or "").strip()
                for event in events
                if str(_value(event, "deployment_id") or "").strip()
            }
        ),
        "cross_symbol_events_in_range": cross_symbol_events,
        "decision_at_utc": None if decision_at is None else decision_at.isoformat(),
    }


def _audit_evaluation(
    block: Any,
    *,
    raw_events: tuple[Any, ...],
    source_clean_block_id: str | None,
    grant: PairAdmissionGrant | None,
    rejection_reason: str | None,
) -> dict[str, Any]:
    snapshot = _raw_audit_snapshot(block, raw_events)
    candidate_id = _candidate_block_id(block, source_clean_block_id)
    decision = "GRANTED" if grant is not None else "REJECTED"
    identity = {
        "rule_version": PAIR_ADMISSION_RULE_VERSION,
        "candidate_block_id": candidate_id,
        "raw_block_id": candidate_id if candidate_id.startswith("5scr-raw-block:") else None,
        "decision": decision,
        "rejection_reason": rejection_reason,
        "source_ledger_event_ids": snapshot["source_ledger_event_ids"],
    }
    evaluation_id = (
        "5scr-admission-evaluation:" + hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:32]
    )
    return {
        "event": "pair_admission_evaluated",
        "evaluation_id": evaluation_id,
        "rule_version": PAIR_ADMISSION_RULE_VERSION,
        "candidate_block_id": candidate_id,
        "symbol": str(_value(block, "symbol") or "").strip().upper() or None,
        "direction": str(_value(block, "direction") or "").strip().upper() or None,
        "episode_started_at_utc": (None if (started := _utc(_value(block, "start"))) is None else started.isoformat()),
        "episode_observed_through_utc": (None if (ended := _utc(_value(block, "end"))) is None else ended.isoformat()),
        "decision": decision,
        "pair_admission_id": None if grant is None else grant.pair_admission_id,
        "pair_admission_source_ledger_hash": None if grant is None else grant.source_ledger_hash,
        "rejection_reason": rejection_reason,
        "reason_codes": [] if rejection_reason is None else [rejection_reason],
        "rejected_at_utc": snapshot["decision_at_utc"] if grant is None else None,
        "source_event_authority": "RAW_SIGNAL_THROTTLE_LOG_EVENT",
        "source_ledger_ordering": "EVENT_TIME_ASC_RAW_ID_TIEBREAK",
        "cross_symbol_interruption_policy": "CROSS_SYMBOL_EVENT_FINALIZES_BLOCK",
        "cross_symbol_interruption_count": int(_value(block, "cross_symbol_interruption_count", 0) or 0),
        "duplicate_event_policy": "REJECT_DUPLICATE_STABLE_RAW_ID",
        "deployment_boundary_policy": "SINGLE_DEPLOYMENT_REQUIRED",
        "execution_authority": False,
        **snapshot,
    }


def _validate_raw_evidence(
    block: Any,
    *,
    raw_events: tuple[Any, ...],
    min_duration_seconds: float,
    min_effective_ticks: int,
    max_gap_seconds: float,
) -> tuple[_ValidatedRawEvidence | None, str | None]:
    """Validate a block by recomputing every authority field from raw rows."""

    symbol = str(_value(block, "symbol") or "").strip().upper()
    direction = str(_value(block, "direction") or "").strip().upper()
    start = _utc(_value(block, "start"))
    end = _utc(_value(block, "end"))
    declared_duration = _number(_value(block, "duration_seconds"))
    declared_ticks = _integer(_value(block, "effective_ticks"))
    declared_events = _integer(_value(block, "events"))

    if not symbol:
        return None, "SYMBOL_MISSING"
    if direction not in {"BUY", "SELL"}:
        return None, "DIRECTION_UNRESOLVED"
    if start is None or end is None or end < start:
        return None, "EPISODE_INTERVAL_INVALID"
    if declared_duration is None or declared_duration < 0:
        return None, "BLOCK_DURATION_INVALID"
    if declared_ticks is None or declared_ticks < 0:
        return None, "BLOCK_EFFECTIVE_TICKS_INVALID"
    if declared_events is None or declared_events < 2:
        return None, "BLOCK_EVENT_COUNT_INVALID"
    if max_gap_seconds <= 0 or max_gap_seconds > DEFAULT_PAIR_ADMISSION_MAX_GAP_SECONDS:
        return None, "PAIR_ADMISSION_MAX_GAP_INVALID"

    if any(
        is_raw_signal_throttle_authority(event)
        and str(_value(event, "symbol") or "").strip().upper() != symbol
        and (timestamp := _utc(_value(event, "timestamp"))) is not None
        and start <= timestamp <= end
        for event in raw_events
    ):
        return None, "CROSS_SYMBOL_INTERRUPTION"

    evidence_with_time = [
        (timestamp, event, raw_signal_throttle_event_id(event))
        for event in raw_events
        if str(_value(event, "symbol") or "").strip().upper() == symbol
        and is_raw_signal_throttle_authority(event)
        and (timestamp := _utc(_value(event, "timestamp"))) is not None
        and start <= timestamp <= end
    ]
    evidence_with_time.sort(key=lambda item: (item[0], item[2]))
    if not evidence_with_time:
        return None, "RAW_SIGNAL_THROTTLE_AUTHORITY_MISSING"

    evidence = tuple(item[1] for item in evidence_with_time)
    timestamps = tuple(item[0] for item in evidence_with_time)
    source_event_ids = tuple(item[2] for item in evidence_with_time)
    if len(set(source_event_ids)) != len(source_event_ids):
        return None, "RAW_LEDGER_EVENT_ID_DUPLICATE"
    if timestamps[0] != start or timestamps[-1] != end:
        return None, "BLOCK_INTERVAL_EVIDENCE_MISMATCH"
    if declared_events is not None and declared_events != len(evidence):
        return None, "BLOCK_EVENT_COUNT_EVIDENCE_MISMATCH"
    if any(raw_signal_throttle_direction(event) is None for event in evidence):
        return None, "RAW_LEDGER_DIRECTION_UNRESOLVED"
    if any(raw_signal_throttle_direction(event) != direction for event in evidence):
        return None, "RAW_LEDGER_DIRECTION_CONFLICT"

    observed_duration = (timestamps[-1] - timestamps[0]).total_seconds()
    if not isclose(declared_duration, observed_duration, rel_tol=0.0, abs_tol=1e-6):
        return None, "BLOCK_DURATION_EVIDENCE_MISMATCH"
    if observed_duration < min_duration_seconds:
        return None, "DURATION_BELOW_MINIMUM"

    gaps = tuple((timestamps[index] - timestamps[index - 1]).total_seconds() for index in range(1, len(timestamps)))
    observed_max_gap = max(gaps, default=0.0)
    if observed_max_gap > max_gap_seconds:
        return None, "RAW_LEDGER_GAP_EXCEEDED"

    effective_ticks = sum(_event_effective_ticks(event) for event in evidence)
    if declared_ticks != effective_ticks:
        return None, "BLOCK_TICK_EVIDENCE_MISMATCH"
    if effective_ticks < min_effective_ticks:
        return None, "EFFECTIVE_TICKS_BELOW_MINIMUM"

    deployment_values = tuple(str(_value(event, "deployment_id") or "").strip() for event in evidence)
    if any(not value for value in deployment_values):
        return None, "DEPLOYMENT_ID_MISSING"
    deployments = set(deployment_values)
    if len(deployments) != 1:
        return None, "MIXED_DEPLOYMENTS"

    scanner_values = tuple(str(_value(event, "scanner_cycle_id") or "").strip() for event in evidence)
    if any(not value for value in scanner_values):
        return None, "SCANNER_CYCLE_ID_MISSING"

    # Freeze the immutable grant evidence at the first observation point that
    # crosses every admission gate.  The enclosing raw block may keep growing,
    # but its logical grant and evidence-at-admission must not change.
    admission_end_index: int | None = None
    admission_effective_ticks = 0
    for index, event in enumerate(evidence):
        admission_effective_ticks += _event_effective_ticks(event)
        prefix_duration = (timestamps[index] - timestamps[0]).total_seconds()
        if index >= 1 and prefix_duration >= min_duration_seconds and admission_effective_ticks >= min_effective_ticks:
            admission_end_index = index
            break
    if admission_end_index is None:
        return None, "PAIR_ADMISSION_THRESHOLD_NOT_REACHED"

    admission_events = evidence[: admission_end_index + 1]
    admission_timestamps = timestamps[: admission_end_index + 1]
    admission_event_ids = source_event_ids[: admission_end_index + 1]
    admission_scanner_values = scanner_values[: admission_end_index + 1]
    admission_gaps = tuple(
        (admission_timestamps[index] - admission_timestamps[index - 1]).total_seconds()
        for index in range(1, len(admission_timestamps))
    )
    scanner_cycle_ids = tuple(dict.fromkeys(admission_scanner_values))
    ledger_hash = "sha256:" + hashlib.sha256("|".join(admission_event_ids).encode("utf-8")).hexdigest()
    return (
        _ValidatedRawEvidence(
            events=admission_events,
            deployment_id=next(iter(deployments)),
            started_at_utc=admission_timestamps[0],
            observed_through_utc=admission_timestamps[-1],
            duration_seconds=(admission_timestamps[-1] - admission_timestamps[0]).total_seconds(),
            effective_ticks=sum(_event_effective_ticks(event) for event in admission_events),
            max_gap_seconds=max(admission_gaps, default=0.0),
            maximum_allowed_gap_seconds=max_gap_seconds,
            source_event_ids=admission_event_ids,
            scanner_cycle_ids=scanner_cycle_ids,
            ledger_hash=ledger_hash,
        ),
        None,
    )


def build_pair_admission_grant(
    block: Any,
    *,
    raw_events: Iterable[Any],
    source_clean_block_id: str | None = None,
    min_duration_seconds: float = DEFAULT_PAIR_ADMISSION_MIN_DURATION_SECONDS,
    min_effective_ticks: int = DEFAULT_PAIR_ADMISSION_MIN_EFFECTIVE_TICKS,
    ttl_seconds: int = DEFAULT_PAIR_ADMISSION_TTL_SECONDS,
    max_gap_seconds: float = DEFAULT_PAIR_ADMISSION_MAX_GAP_SECONDS,
) -> PairAdmissionGrant | None:
    """Return a grant only when raw-ledger evidence meets every authority rule."""

    symbol = str(_value(block, "symbol") or "").strip().upper()
    direction = str(_value(block, "direction") or "").strip().upper()
    validated, _ = _validate_raw_evidence(
        block,
        raw_events=tuple(raw_events),
        min_duration_seconds=min_duration_seconds,
        min_effective_ticks=min_effective_ticks,
        max_gap_seconds=max_gap_seconds,
    )
    if validated is None:
        return None
    identity = {
        "deployment_id": validated.deployment_id,
        "raw_block_id": _candidate_block_id(block, source_clean_block_id),
        "rule_version": PAIR_ADMISSION_RULE_VERSION,
    }
    admission_id = "5scr-admission:" + hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:32]
    clean_ids = (source_clean_block_id,) if source_clean_block_id else ()
    return PairAdmissionGrant(
        pair_admission_id=admission_id,
        deployment_id=validated.deployment_id,
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        episode_started_at_utc=validated.started_at_utc,
        episode_observed_through_utc=validated.observed_through_utc,
        granted_at_utc=validated.observed_through_utc,
        expires_at_utc=validated.observed_through_utc
        + timedelta(seconds=min(PAIR_ADMISSION_MAX_TTL_SECONDS, max(1, ttl_seconds))),
        duration_seconds=validated.duration_seconds,
        effective_ticks=validated.effective_ticks,
        source_event_count=len(validated.events),
        max_observed_gap_seconds=validated.max_gap_seconds,
        maximum_allowed_gap_seconds=validated.maximum_allowed_gap_seconds,
        source_ledger_event_ids=validated.source_event_ids,
        source_scanner_cycle_ids=validated.scanner_cycle_ids,
        source_ledger_hash=validated.ledger_hash,
        source_clean_block_ids=clean_ids,
    )


def _rejection_reason(
    block: Any,
    *,
    raw_events: tuple[Any, ...],
    min_duration_seconds: float,
    min_effective_ticks: int,
    max_gap_seconds: float,
) -> str:
    _, reason = _validate_raw_evidence(
        block,
        raw_events=raw_events,
        min_duration_seconds=min_duration_seconds,
        min_effective_ticks=min_effective_ticks,
        max_gap_seconds=max_gap_seconds,
    )
    return reason or "PAIR_ADMISSION_CONTRACT_REJECTED"


def build_pair_admission_audit(
    blocks: Iterable[Any],
    *,
    raw_events: Iterable[Any],
    clean_block_ids: dict[tuple[str, str, str], str] | None = None,
    min_duration_seconds: float = DEFAULT_PAIR_ADMISSION_MIN_DURATION_SECONDS,
    min_effective_ticks: int = DEFAULT_PAIR_ADMISSION_MIN_EFFECTIVE_TICKS,
    max_gap_seconds: float = DEFAULT_PAIR_ADMISSION_MAX_GAP_SECONDS,
) -> PairAdmissionAudit:
    """Evaluate all blocks and retain explicit rejection reasons for shadow rollout."""

    events = tuple(raw_events)
    ids = clean_block_ids or {}
    grants: list[PairAdmissionGrant] = []
    evaluations: list[dict[str, Any]] = []
    rejection_counts: dict[str, int] = {}
    block_list = tuple(blocks)
    for block in block_list:
        start = _utc(_value(block, "start"))
        end = _utc(_value(block, "end"))
        symbol = str(_value(block, "symbol") or "").upper()
        key = (
            symbol,
            "" if start is None else start.isoformat(),
            "" if end is None else end.isoformat(),
        )
        grant = build_pair_admission_grant(
            block,
            raw_events=events,
            source_clean_block_id=ids.get(key),
            min_duration_seconds=min_duration_seconds,
            min_effective_ticks=min_effective_ticks,
            max_gap_seconds=max_gap_seconds,
        )
        if grant is not None:
            grants.append(grant)
            evaluations.append(
                _audit_evaluation(
                    block,
                    raw_events=events,
                    source_clean_block_id=ids.get(key),
                    grant=grant,
                    rejection_reason=None,
                )
            )
            continue
        reason = _rejection_reason(
            block,
            raw_events=events,
            min_duration_seconds=min_duration_seconds,
            min_effective_ticks=min_effective_ticks,
            max_gap_seconds=max_gap_seconds,
        )
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        evaluations.append(
            _audit_evaluation(
                block,
                raw_events=events,
                source_clean_block_id=ids.get(key),
                grant=None,
                rejection_reason=reason,
            )
        )
    ordered_grants = tuple(sorted(grants, key=lambda item: (item.granted_at_utc, item.symbol, item.pair_admission_id)))
    return PairAdmissionAudit(
        grants=ordered_grants,
        evaluated_blocks=len(block_list),
        rejection_counts=rejection_counts,
        evaluations=tuple(evaluations),
    )


def build_pair_admission_grants(
    blocks: Iterable[Any],
    *,
    raw_events: Iterable[Any],
    clean_block_ids: dict[tuple[str, str, str], str] | None = None,
    min_duration_seconds: float = DEFAULT_PAIR_ADMISSION_MIN_DURATION_SECONDS,
    max_gap_seconds: float = DEFAULT_PAIR_ADMISSION_MAX_GAP_SECONDS,
) -> tuple[PairAdmissionGrant, ...]:
    """Build deterministic grants for all eligible blocks in one global ledger."""

    return build_pair_admission_audit(
        blocks,
        raw_events=raw_events,
        clean_block_ids=clean_block_ids,
        min_duration_seconds=min_duration_seconds,
        max_gap_seconds=max_gap_seconds,
    ).grants


__all__ = [
    "DEFAULT_PAIR_ADMISSION_MIN_DURATION_SECONDS",
    "DEFAULT_PAIR_ADMISSION_MIN_EFFECTIVE_TICKS",
    "DEFAULT_PAIR_ADMISSION_TTL_SECONDS",
    "DEFAULT_PAIR_ADMISSION_MAX_GAP_SECONDS",
    "PairAdmissionAudit",
    "build_pair_admission_audit",
    "build_pair_admission_grant",
    "build_pair_admission_grants",
]
