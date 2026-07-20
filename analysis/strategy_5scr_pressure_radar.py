"""Deployment-scoped pressure radar gate and deferred lineage association.

The radar preserves the highest pressure stage already observed instead of
reading only the latest row.  Its output is analysis input only: raw BUY/SELL
remains advisory, final direction stays WAIT, and no execution command exists.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from analysis.strategy_5scr_pressure_to_tradeplan import (
    PRESSURE_LOG_PREFIX,
    PressureEventNormalizer,
    PressureInputError,
)
from contracts.strategy_5scr_pressure_radar import (
    PressureRadarDirection,
    PressureRadarEvaluation,
    PressureRadarManifest,
    PressureRadarQualifyingStage,
)

GATE_RULE_VERSION = "pressure_radar_gate_v1"
_ALLOWED_SOURCE_STAGES = frozenset({"PRESSURE_BLOCK", "CANDIDATE_LIFECYCLE"})
_STAGE_RANK = {"ALLOWED_QUORUM": 1, "PRESSURE_BLOCK": 2, "CANDIDATE_LIFECYCLE": 3}
_RUNTIME_FIELDS = frozenset({"deployment_id", "commit_sha", "replica_id", "generated_at_utc"})
_TRANSPORT_FIELDS = frozenset({"event_id", "lifecycle_id", "lifecycle_sequence", "pressure_outbox_id"})
_CLEAN_BLOCK_INTERVAL = re.compile(r"_(?P<start>\d{8}T\d{6}(?:\.\d{1,6})?Z)_(?P<end>\d{8}T\d{6}(?:\.\d{1,6})?Z)(?:_|$)")


class PressureRadarError(ValueError):
    """Raised when a radar record or replay scope is unsafe or ambiguous."""


@dataclass(frozen=True)
class PressureRadarIngestResult:
    evaluation: PressureRadarEvaluation
    manifest: PressureRadarManifest | None
    transition: str
    duplicate: bool = False


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    resolved = str(value).strip()
    return resolved or None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _non_negative_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _extract_payload(record: Mapping[str, Any] | str) -> dict[str, Any]:
    if isinstance(record, Mapping):
        if str(record.get("event") or "").lower() == "signal_pressure_state_json":
            return dict(record)
        raw = record.get("message")
        if not isinstance(raw, str):
            raise PressureRadarError("PRESSURE_RADAR_RECORD_MESSAGE_MISSING")
    elif isinstance(record, str):
        raw = record
    else:
        raise PressureRadarError("PRESSURE_RADAR_RECORD_TYPE_UNSUPPORTED")
    if PRESSURE_LOG_PREFIX in raw:
        raw = raw.split(PRESSURE_LOG_PREFIX, 1)[1].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PressureRadarError("PRESSURE_RADAR_RECORD_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise PressureRadarError("PRESSURE_RADAR_PAYLOAD_NOT_OBJECT")
    return payload


def pressure_radar_context(payload: Mapping[str, Any]) -> dict[str, str | None]:
    """Return the stable semantic context used for deferred association.

    ``context_version`` is deliberately excluded.  The live emitter hashes
    volatile age/snapshot fields into that value, and the supplied production
    window shows it changes while the structural context remains identical.
    """

    raw_htf = payload.get("htf_structure_context")
    htf = raw_htf if isinstance(raw_htf, Mapping) else {}
    return {
        "raw_direction": _text(payload.get("raw_direction")),
        "daily_bias": _text(htf.get("daily_bias")),
        "h4_structure": _text(htf.get("h4_structure")),
        "price_location": _text(
            payload.get("structural_price_location") or payload.get("price_location") or htf.get("price_location")
        ),
        "liquidity_resolution": _text(payload.get("liquidity_resolution") or htf.get("liquidity_resolution")),
        "allowed_playbook": _text(htf.get("allowed_playbook")),
    }


def pressure_radar_context_signature(payload: Mapping[str, Any]) -> str:
    return _sha256(pressure_radar_context(payload))


def parse_clean_block_interval(source_clean_block_id: str, *, symbol: str) -> tuple[datetime, datetime] | None:
    """Parse the canonical clean-block interval carried by current LIVE IDs."""

    if not source_clean_block_id.startswith(f"{symbol}_"):
        return None
    match = _CLEAN_BLOCK_INTERVAL.search(source_clean_block_id)
    if match is None:
        return None

    def parse_token(token: str) -> datetime:
        pattern = "%Y%m%dT%H%M%S.%fZ" if "." in token else "%Y%m%dT%H%M%SZ"
        return datetime.strptime(token, pattern).replace(tzinfo=UTC)

    start = parse_token(match.group("start"))
    end = parse_token(match.group("end"))
    return (start, end) if end >= start else None


def _stage(payload: Mapping[str, Any]) -> PressureRadarQualifyingStage | None:
    source_stage = str(payload.get("source_stage") or "").upper()
    if source_stage in _ALLOWED_SOURCE_STAGES:
        return cast(PressureRadarQualifyingStage, source_stage)
    if (
        str(payload.get("signal_family") or "").upper() == "SIGNAL_THROTTLE_ALLOWED_QUORUM"
        and payload.get("pair_eligible_for_analysis") is True
    ):
        return "ALLOWED_QUORUM"
    return None


def evaluate_pressure_radar(record: Mapping[str, Any] | str) -> PressureRadarEvaluation:
    payload = _extract_payload(record)
    try:
        normalized = PressureEventNormalizer(input_mode="REPLAY").normalize(payload)
    except PressureInputError as exc:
        raise PressureRadarError(str(exc)) from exc

    deployment_id = _text(payload.get("deployment_id")) or "unknown"
    htf_raw = payload.get("htf_structure_context")
    htf = htf_raw if isinstance(htf_raw, Mapping) else {}
    ticks = _non_negative_int(payload.get("current_block_effective_ticks"))
    stage = _stage(payload)
    expires_at = _parse_datetime(payload.get("raw_direction_expires_at_utc"))
    failures: list[str] = []
    if deployment_id == "unknown":
        failures.append("DEPLOYMENT_ID_MISSING")
    if normalized.raw_direction is None:
        failures.append("RAW_DIRECTION_MISSING")
    if payload.get("raw_direction_eligible_for_context_resolution") is not True:
        failures.append("RAW_DIRECTION_NOT_CONTEXT_ELIGIBLE")
    if ticks < 3:
        failures.append("EFFECTIVE_TICKS_BELOW_3")
    if stage is None:
        failures.append("SOURCE_STAGE_NOT_ALLOWED")
    if htf.get("daily_bias_freshness_status") != "FRESH":
        failures.append("DAILY_BIAS_NOT_FRESH")
    if _text(htf.get("allowed_playbook")) in {None, "NONE"}:
        failures.append("PLAYBOOK_NOT_ALLOWED")
    if payload.get("direction_next_required_stage") != "LIQUIDITY_ACCEPTANCE_OR_REJECTION":
        failures.append("DIRECTION_NEXT_STAGE_INVALID")
    if expires_at is None or expires_at <= normalized.event_time_utc:
        failures.append("RAW_DIRECTION_EXPIRY_INVALID")
    context_version = _text(payload.get("context_version"))
    if context_version is None:
        failures.append("CONTEXT_VERSION_MISSING")

    provisional = not failures
    failed = tuple(failures)
    return PressureRadarEvaluation(
        event_id=normalized.event_id,
        deployment_id=deployment_id,
        symbol=normalized.symbol,
        raw_direction=cast(PressureRadarDirection | None, normalized.raw_direction),
        observed_at_utc=normalized.event_time_utc,
        raw_direction_expires_at_utc=expires_at,
        source_stage=str(payload.get("source_stage") or "UNKNOWN").upper(),
        signal_family=str(payload.get("signal_family") or "UNKNOWN").upper(),
        qualifying_stage=stage if provisional else None,
        current_block_effective_ticks=ticks,
        source_clean_block_id=_text(payload.get("source_clean_block_id")),
        context_version=context_version or "missing",
        context_signature=pressure_radar_context_signature(payload),
        provisional_candidate=provisional,
        reserve_near_qualified=failed == ("SOURCE_STAGE_NOT_ALLOWED",),
        failed_predicates=failed,
    )


def _manifest_id(evaluation: PressureRadarEvaluation) -> str:
    identity = {
        "deployment_id": evaluation.deployment_id,
        "symbol": evaluation.symbol,
        "raw_direction": evaluation.raw_direction,
        "qualifying_event_id": evaluation.event_id,
        "gate_rule_version": evaluation.gate_rule_version,
    }
    digest = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:32]
    return f"5scr-radar:{digest}"


def _new_manifest(evaluation: PressureRadarEvaluation) -> PressureRadarManifest:
    assert evaluation.provisional_candidate
    assert evaluation.raw_direction is not None
    assert evaluation.qualifying_stage is not None
    assert evaluation.raw_direction_expires_at_utc is not None
    return PressureRadarManifest(
        manifest_id=_manifest_id(evaluation),
        deployment_id=evaluation.deployment_id,
        symbol=evaluation.symbol,
        raw_direction=evaluation.raw_direction,
        qualifying_event_id=evaluation.event_id,
        qualifying_time_utc=evaluation.observed_at_utc,
        qualifying_stage=evaluation.qualifying_stage,
        max_effective_ticks=evaluation.current_block_effective_ticks,
        context_version=evaluation.context_version,
        context_signature=evaluation.context_signature,
        raw_direction_expires_at_utc=evaluation.raw_direction_expires_at_utc,
        status="WAITING_CANONICAL_LINEAGE",
        state_history=(
            "RADAR_OBSERVED",
            "RADAR_QUALIFIED_PROVISIONAL",
            "WAITING_CANONICAL_LINEAGE",
        ),
        observed_event_ids=(evaluation.event_id,),
        next_required_stage="CANONICAL_LINEAGE",
    )


def associate_canonical_lineage(
    manifest: PressureRadarManifest,
    record: Mapping[str, Any] | str,
) -> PressureRadarManifest | None:
    payload = _extract_payload(record)
    evaluation = evaluate_pressure_radar(payload)
    if manifest.status != "WAITING_CANONICAL_LINEAGE":
        return None
    if (
        evaluation.deployment_id != manifest.deployment_id
        or evaluation.symbol != manifest.symbol
        or evaluation.raw_direction != manifest.raw_direction
        or evaluation.context_signature != manifest.context_signature
    ):
        return None
    source_id = evaluation.source_clean_block_id
    if source_id is None:
        return None
    interval = parse_clean_block_interval(source_id, symbol=manifest.symbol)
    if interval is None or not (interval[0] <= manifest.qualifying_time_utc <= interval[1]):
        return None
    finalized_at = _parse_datetime(payload.get("generated_at_utc")) or evaluation.observed_at_utc
    if finalized_at > manifest.raw_direction_expires_at_utc:
        return None
    event_ids = manifest.observed_event_ids
    if evaluation.event_id not in event_ids:
        event_ids = (*event_ids, evaluation.event_id)
    return manifest.model_copy(
        update={
            "source_clean_block_id": source_id,
            "lineage_finalized_at_utc": finalized_at,
            "lineage_context_version": evaluation.context_version,
            "status": "ANALYSIS_READY",
            "state_history": (*manifest.state_history, "ANALYSIS_READY"),
            "observed_event_ids": event_ids,
            "next_required_stage": "CLOSED_CANDLE_EVIDENCE",
        }
    )


class PressureRadarAssembler:
    """Latch provisional qualifications and join later canonical lineage."""

    def __init__(self, manifests: Iterable[PressureRadarManifest] | None = None) -> None:
        seeded = tuple(manifests or ())
        self._manifests: dict[str, PressureRadarManifest] = {manifest.manifest_id: manifest for manifest in seeded}
        if len(self._manifests) != len(seeded):
            raise PressureRadarError("PRESSURE_RADAR_DUPLICATE_MANIFEST_ID")
        self._seen_event_ids: set[tuple[str, str]] = set()

    def ingest(self, record: Mapping[str, Any] | str) -> PressureRadarIngestResult:
        payload = _extract_payload(record)
        evaluation = evaluate_pressure_radar(payload)
        dedup_key = (evaluation.deployment_id, evaluation.event_id)
        if dedup_key in self._seen_event_ids:
            manifest = self._manifest_for_event(evaluation.deployment_id, evaluation.event_id)
            return PressureRadarIngestResult(evaluation, manifest, "DUPLICATE", duplicate=True)

        self.advance_time(evaluation.observed_at_utc)
        transition = "RADAR_OBSERVED"
        manifest: PressureRadarManifest | None = None

        active = self._active_for(evaluation.deployment_id, evaluation.symbol)
        if (
            evaluation.raw_direction is not None
            and "RAW_DIRECTION_NOT_CONTEXT_ELIGIBLE" not in evaluation.failed_predicates
        ):
            for current in active:
                if current.raw_direction != evaluation.raw_direction:
                    invalidated = current.model_copy(
                        update={
                            "status": "INVALIDATED_DIRECTION_REVERSAL",
                            "state_history": (*current.state_history, "INVALIDATED_DIRECTION_REVERSAL"),
                            "next_required_stage": "NONE",
                        }
                    )
                    self._manifests[current.manifest_id] = invalidated

        if evaluation.provisional_candidate:
            candidates = [
                item
                for item in self._active_for(evaluation.deployment_id, evaluation.symbol)
                if item.raw_direction == evaluation.raw_direction
                and item.context_signature == evaluation.context_signature
                and item.status == "WAITING_CANONICAL_LINEAGE"
            ]
            if candidates:
                manifest = max(candidates, key=lambda item: item.qualifying_time_utc)
                event_ids = manifest.observed_event_ids
                if evaluation.event_id not in event_ids:
                    event_ids = (*event_ids, evaluation.event_id)
                stage = manifest.qualifying_stage
                assert evaluation.qualifying_stage is not None
                if _STAGE_RANK[evaluation.qualifying_stage] > _STAGE_RANK[stage]:
                    stage = evaluation.qualifying_stage
                manifest = manifest.model_copy(
                    update={
                        "qualifying_stage": stage,
                        "max_effective_ticks": max(
                            manifest.max_effective_ticks,
                            evaluation.current_block_effective_ticks,
                        ),
                        "observed_event_ids": event_ids,
                    }
                )
            else:
                manifest = _new_manifest(evaluation)
            self._manifests[manifest.manifest_id] = manifest
            transition = "WAITING_CANONICAL_LINEAGE"
        elif evaluation.reserve_near_qualified:
            transition = "RESERVE_NEAR_QUALIFIED"

        if evaluation.source_clean_block_id is not None:
            for current in self._active_for(evaluation.deployment_id, evaluation.symbol):
                associated = associate_canonical_lineage(current, payload)
                if associated is not None:
                    self._manifests[current.manifest_id] = associated
                    manifest = associated
                    transition = "ANALYSIS_READY"

        self._seen_event_ids.add(dedup_key)
        return PressureRadarIngestResult(evaluation, manifest, transition)

    def ingest_many(self, records: Iterable[Mapping[str, Any] | str]) -> list[PressureRadarManifest]:
        prepared: list[tuple[datetime, str, Mapping[str, Any] | str]] = []
        for record in records:
            evaluation = evaluate_pressure_radar(record)
            prepared.append((evaluation.observed_at_utc, evaluation.event_id, record))
        for _, _, record in sorted(prepared, key=lambda item: (item[0], item[1])):
            self.ingest(record)
        return self.snapshots()

    def advance_time(self, now: datetime) -> None:
        resolved_now = _parse_datetime(now)
        if resolved_now is None:
            raise PressureRadarError("PRESSURE_RADAR_ADVANCE_TIME_INVALID")
        for manifest_id, manifest in tuple(self._manifests.items()):
            if manifest.status not in {"WAITING_CANONICAL_LINEAGE", "ANALYSIS_READY"}:
                continue
            if resolved_now > manifest.raw_direction_expires_at_utc:
                self._manifests[manifest_id] = manifest.model_copy(
                    update={
                        "status": "EXPIRED",
                        "state_history": (*manifest.state_history, "EXPIRED"),
                        "next_required_stage": "NONE",
                    }
                )

    def snapshots(self, *, deployment_id: str | None = None) -> list[PressureRadarManifest]:
        manifests = self._manifests.values()
        if deployment_id is not None:
            manifests = (item for item in manifests if item.deployment_id == deployment_id)
        return sorted(manifests, key=lambda item: (item.qualifying_time_utc, item.manifest_id))

    def _active_for(self, deployment_id: str, symbol: str) -> list[PressureRadarManifest]:
        return [
            item
            for item in self._manifests.values()
            if item.deployment_id == deployment_id
            and item.symbol == symbol
            and item.status in {"WAITING_CANONICAL_LINEAGE", "ANALYSIS_READY"}
        ]

    def _manifest_for_event(self, deployment_id: str, event_id: str) -> PressureRadarManifest | None:
        return next(
            (
                item
                for item in self._manifests.values()
                if item.deployment_id == deployment_id and event_id in item.observed_event_ids
            ),
            None,
        )


def replay_pressure_radar_manifests(
    records: Iterable[Mapping[str, Any] | str],
    *,
    deployment_id: str,
) -> list[PressureRadarManifest]:
    """Replay exactly one deployment to prevent cold-start cross-contamination."""

    if not deployment_id.strip():
        raise PressureRadarError("PRESSURE_RADAR_REPLAY_DEPLOYMENT_REQUIRED")
    selected: list[Mapping[str, Any] | str] = []
    for record in records:
        payload = _extract_payload(record)
        if _text(payload.get("deployment_id")) == deployment_id:
            selected.append(record)
    assembler = PressureRadarAssembler()
    assembler.ingest_many(selected)
    return assembler.snapshots(deployment_id=deployment_id)


def canonical_radar_payload(
    manifest: PressureRadarManifest,
    qualifying_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble the canonical non-executable payload after lineage recovery."""

    if manifest.status != "ANALYSIS_READY" or manifest.source_clean_block_id is None:
        raise PressureRadarError("PRESSURE_RADAR_MANIFEST_NOT_ANALYSIS_READY")
    data = {key: value for key, value in qualifying_payload.items() if key not in (_RUNTIME_FIELDS | _TRANSPORT_FIELDS)}
    data.update(
        {
            "event": "signal_pressure_state_json",
            "deployment_id": manifest.deployment_id,
            "gate_rule_version": manifest.gate_rule_version,
            "radar_manifest_id": manifest.manifest_id,
            "radar_status": manifest.status,
            "source_clean_block_id": manifest.source_clean_block_id,
            "analysis_ready_at_utc": manifest.lineage_finalized_at_utc.isoformat()
            if manifest.lineage_finalized_at_utc
            else None,
            "lineage_finalized_at_utc": manifest.lineage_finalized_at_utc.isoformat()
            if manifest.lineage_finalized_at_utc
            else None,
            "lineage_context_version": manifest.lineage_context_version,
            "qualifying_event_id": manifest.qualifying_event_id,
            "qualifying_time_utc": manifest.qualifying_time_utc.isoformat(),
            "qualifying_stage": manifest.qualifying_stage,
            "max_effective_ticks": manifest.max_effective_ticks,
            "raw_direction": manifest.raw_direction,
            "final_direction": "WAIT",
            "valid_for_execution": False,
            "execution_valid_now": False,
            "is_final_signal": False,
            "next_required_stage": "CLOSED_CANDLE_EVIDENCE",
        }
    )
    return data


__all__ = [
    "GATE_RULE_VERSION",
    "PressureRadarAssembler",
    "PressureRadarError",
    "PressureRadarIngestResult",
    "associate_canonical_lineage",
    "canonical_radar_payload",
    "evaluate_pressure_radar",
    "parse_clean_block_interval",
    "pressure_radar_context",
    "pressure_radar_context_signature",
    "replay_pressure_radar_manifests",
]
