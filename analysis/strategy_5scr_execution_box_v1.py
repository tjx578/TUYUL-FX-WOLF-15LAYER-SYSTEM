"""Pure reducer for versioned, shadow-only Strategy 5S-CR execution boxes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from contracts.strategy_5scr_directional_thesis_v1 import DirectionalThesisV1
from contracts.strategy_5scr_execution_box_v1 import (
    EXECUTION_BOX_RULE_VERSION,
    ExecutionBoxEvidenceV1,
    ExecutionBoxV1,
    execution_box_identity_v1,
)

ExecutionBoxReductionStatus = Literal[
    "OPENED",
    "FROZEN",
    "DUPLICATE",
    "SUPERSEDED",
    "NO_CHANGE",
    "REJECTED",
    "QUARANTINED",
]


def _sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def execution_box_evidence_hash(evidence: ExecutionBoxEvidenceV1) -> str:
    """Hash complete evidence, including non-material operational lineage."""

    return _sha256(evidence.model_dump(mode="json"))


def material_box_hash(evidence: ExecutionBoxEvidenceV1) -> str:
    """Fingerprint only immutable thesis scope, route, and M1 geometry.

    Deployment, replica, publisher, request IDs, reference-price refreshes,
    telemetry count, and evidence ordering provenance do not version a box.
    """

    box_low, box_high = route_geometry_bounds(evidence)
    return _sha256(
        {
            "strategy_lifecycle_id": evidence.strategy_lifecycle_id,
            "context_epoch_id": evidence.context_epoch_id,
            "strategy_thesis_id": evidence.strategy_thesis_id,
            "thesis_semantic_identity_hash": evidence.thesis_semantic_identity_hash,
            "symbol": evidence.symbol,
            "strategy_direction": evidence.strategy_direction,
            "route_type": evidence.route_type,
            "route_geometry_authority_hash": evidence.route_geometry_authority.authority_hash,
            "box_low": box_low,
            "box_high": box_high,
            "source_m1_material_hashes": sorted(item.material_candle_hash for item in evidence.material_m1_candles),
            "rule_version": EXECUTION_BOX_RULE_VERSION,
        }
    )


def execution_box_id(
    strategy_thesis_id: str,
    box_sequence: int,
    box_version: int,
    material_hash: str,
) -> str:
    return execution_box_identity_v1(strategy_thesis_id, box_sequence, box_version, material_hash)


def route_geometry_bounds(evidence: ExecutionBoxEvidenceV1) -> tuple[float, float]:
    """Return bounds proven by the typed route authority, never a universal origin range."""

    authority = evidence.route_geometry_authority
    return authority.route_low, authority.route_high


def _terminal_clock_update(
    box: ExecutionBoxV1,
    *,
    state: Literal["SUPERSEDED", "INVALIDATED", "CONSUMED", "EXPIRED"],
    occurred_at_utc: datetime,
) -> ExecutionBoxV1:
    if box.state not in {"BUILDING", "FROZEN"}:
        return box
    clock_field = {
        "SUPERSEDED": "superseded_at_utc",
        "INVALIDATED": "invalidated_at_utc",
        "CONSUMED": "consumed_at_utc",
        "EXPIRED": "expired_at_utc",
    }[state]
    payload = box.model_dump(mode="python")
    payload.update(
        state=state,
        state_version=box.state_version + 1,
        last_observed_at_utc=max(box.last_observed_at_utc, occurred_at_utc),
        **{clock_field: occurred_at_utc},
    )
    return ExecutionBoxV1.model_validate(payload)


def close_execution_box(
    box: ExecutionBoxV1,
    *,
    state: Literal["INVALIDATED", "CONSUMED", "EXPIRED"],
    occurred_at_utc: datetime,
) -> ExecutionBoxV1:
    """Apply an explicit parent/consumer terminal transition idempotently."""

    return _terminal_clock_update(box, state=state, occurred_at_utc=occurred_at_utc)


@dataclass(frozen=True)
class ExecutionBoxReductionResult:
    status: ExecutionBoxReductionStatus
    reason_code: str | None = None
    box: ExecutionBoxV1 | None = None
    previous_box: ExecutionBoxV1 | None = None


def reduce_execution_box(
    *,
    thesis: DirectionalThesisV1,
    evidence: ExecutionBoxEvidenceV1,
    current: ExecutionBoxV1 | None,
    next_sequence: int,
) -> ExecutionBoxReductionResult:
    """Fold one M1 geometry observation without granting execution authority."""

    if thesis.state != "ACTIVE":
        return ExecutionBoxReductionResult("REJECTED", "DIRECTIONAL_THESIS_NOT_ACTIVE")
    if thesis.valid_for_execution or thesis.execution_authority:
        return ExecutionBoxReductionResult("QUARANTINED", "DIRECTIONAL_THESIS_AUTHORITY_DRIFT")
    scope = (
        thesis.strategy_lifecycle_id,
        thesis.context_epoch_id,
        thesis.strategy_thesis_id,
        thesis.semantic_identity_hash,
        thesis.symbol,
        thesis.strategy_direction,
        thesis.selected_route,
    )
    evidence_scope = (
        evidence.strategy_lifecycle_id,
        evidence.context_epoch_id,
        evidence.strategy_thesis_id,
        evidence.thesis_semantic_identity_hash,
        evidence.symbol,
        evidence.strategy_direction,
        evidence.route_type,
    )
    if evidence_scope != scope:
        return ExecutionBoxReductionResult("REJECTED", "EXECUTION_BOX_PARENT_SCOPE_MISMATCH")
    material_hash = material_box_hash(evidence)
    evidence_hash = execution_box_evidence_hash(evidence)
    box_low, box_high = route_geometry_bounds(evidence)

    if current is not None:
        current_scope = (
            current.strategy_lifecycle_id,
            current.context_epoch_id,
            current.strategy_thesis_id,
            current.thesis_semantic_identity_hash,
            current.symbol,
            current.strategy_direction,
            current.route_type,
        )
        current_expected_id = execution_box_id(
            current.strategy_thesis_id,
            current.box_sequence,
            current.box_version,
            current.material_box_hash,
        )
        if current_scope != scope or current.execution_box_id != current_expected_id:
            return ExecutionBoxReductionResult("QUARANTINED", "ACTIVE_EXECUTION_BOX_PARENT_DRIFT")
        if current.valid_for_execution or current.execution_authority:
            return ExecutionBoxReductionResult("QUARANTINED", "ACTIVE_EXECUTION_BOX_AUTHORITY_DRIFT")
        if current.state not in {"BUILDING", "FROZEN"}:
            return ExecutionBoxReductionResult("REJECTED", "EXECUTION_BOX_TERMINAL_NO_RESURRECTION")
        if (
            evidence.source_request_id is not None
            and evidence.source_request_id == current.last_source_request_id
            and current.evidence_hash != evidence_hash
        ):
            return ExecutionBoxReductionResult("QUARANTINED", "EXECUTION_BOX_REQUEST_EVIDENCE_DRIFT", current)
        if evidence_hash == current.evidence_hash:
            return ExecutionBoxReductionResult(
                "DUPLICATE",
                "EXECUTION_BOX_FREEZE_ALREADY_PERSISTED"
                if current.state == "FROZEN" and evidence.freeze_requested
                else "EXECUTION_BOX_ALREADY_PERSISTED",
                current,
            )
        if evidence.observed_at_utc < max(thesis.created_at_utc, thesis.liveness_checked_through_utc):
            return ExecutionBoxReductionResult("REJECTED", "EXECUTION_BOX_PARENT_CLOCK_PRECEDES_THESIS", current)
        if any(item.open_time_utc < thesis.created_at_utc for item in evidence.material_m1_candles):
            return ExecutionBoxReductionResult("REJECTED", "EXECUTION_BOX_M1_PRECEDES_THESIS", current)
        if evidence.observed_at_utc < current.last_observed_at_utc:
            return ExecutionBoxReductionResult("REJECTED", "STALE_EXECUTION_BOX_EVIDENCE", current)
        if evidence.observed_at_utc == current.last_observed_at_utc:
            return ExecutionBoxReductionResult(
                "QUARANTINED",
                "AMBIGUOUS_EXECUTION_BOX_EVIDENCE_CLOCK",
                current,
            )
        if current.material_box_hash == material_hash:
            if current.state == "BUILDING" and evidence.freeze_requested:
                frozen = ExecutionBoxV1.model_validate(
                    {
                        **current.model_dump(mode="python"),
                        "state": "FROZEN",
                        "frozen_at_utc": evidence.observed_at_utc,
                        "freeze_authority_hash": evidence.freeze_authority_hash,
                        "evidence_hash": evidence_hash,
                        "source_m1_ids": tuple(
                            sorted(item.material_candle_hash for item in evidence.material_m1_candles)
                        ),
                        "source_m1_evidence_ids": tuple(
                            sorted(item.candle_evidence_id for item in evidence.material_m1_candles)
                        ),
                        "last_observed_at_utc": evidence.observed_at_utc,
                        "last_source_request_id": evidence.source_request_id,
                        "state_version": current.state_version + 1,
                    }
                )
                return ExecutionBoxReductionResult(
                    "FROZEN",
                    "EXECUTION_BOX_GEOMETRY_FROZEN",
                    frozen,
                    current,
                )
            if current.evidence_hash == evidence_hash:
                return ExecutionBoxReductionResult(
                    "DUPLICATE",
                    "EXECUTION_BOX_ALREADY_PERSISTED",
                    current,
                )
            if current.state == "FROZEN" and evidence.freeze_requested:
                return ExecutionBoxReductionResult(
                    "REJECTED",
                    "FROZEN_EXECUTION_BOX_IMMUTABLE",
                    current,
                )
            refreshed = ExecutionBoxV1.model_validate(
                {
                    **current.model_dump(mode="python"),
                    "evidence_hash": evidence_hash,
                    "source_m1_ids": tuple(sorted(item.material_candle_hash for item in evidence.material_m1_candles)),
                    "source_m1_evidence_ids": tuple(
                        sorted(item.candle_evidence_id for item in evidence.material_m1_candles)
                    ),
                    "last_observed_at_utc": evidence.observed_at_utc,
                    "last_source_request_id": evidence.source_request_id,
                    "state_version": current.state_version + 1,
                }
            )
            return ExecutionBoxReductionResult(
                "NO_CHANGE",
                "NON_MATERIAL_EXECUTION_BOX_REFRESH",
                refreshed,
                current,
            )
    else:
        if evidence.observed_at_utc < max(thesis.created_at_utc, thesis.liveness_checked_through_utc):
            return ExecutionBoxReductionResult("REJECTED", "EXECUTION_BOX_PARENT_CLOCK_PRECEDES_THESIS")
        if any(item.open_time_utc < thesis.created_at_utc for item in evidence.material_m1_candles):
            return ExecutionBoxReductionResult("REJECTED", "EXECUTION_BOX_M1_PRECEDES_THESIS")

    if current is not None:
        if current.state == "FROZEN":
            return ExecutionBoxReductionResult(
                "REJECTED",
                "FROZEN_EXECUTION_BOX_IMMUTABLE",
                current,
            )
        previous = _terminal_clock_update(
            current,
            state="SUPERSEDED",
            occurred_at_utc=evidence.observed_at_utc,
        )
        box_version = current.box_version + 1
        if next_sequence != current.box_sequence + 1:
            return ExecutionBoxReductionResult("QUARANTINED", "EXECUTION_BOX_SEQUENCE_DRIFT", current)
        previous_id = current.execution_box_id
        status: ExecutionBoxReductionStatus = "SUPERSEDED"
    else:
        previous = None
        box_version = 1
        previous_id = None
        status = "OPENED"

    box_state = "FROZEN" if evidence.freeze_requested else "BUILDING"
    box = ExecutionBoxV1(
        execution_box_id=execution_box_id(thesis.strategy_thesis_id, next_sequence, box_version, material_hash),
        strategy_lifecycle_id=thesis.strategy_lifecycle_id,
        context_epoch_id=thesis.context_epoch_id,
        strategy_thesis_id=thesis.strategy_thesis_id,
        box_sequence=next_sequence,
        box_version=box_version,
        previous_execution_box_id=previous_id,
        symbol=thesis.symbol,
        strategy_direction=thesis.strategy_direction,
        route_type=thesis.selected_route,
        state=box_state,
        box_low=box_low,
        box_high=box_high,
        opened_at_utc=evidence.observed_at_utc,
        frozen_at_utc=evidence.observed_at_utc if box_state == "FROZEN" else None,
        freeze_authority_hash=evidence.freeze_authority_hash if box_state == "FROZEN" else None,
        material_box_hash=material_hash,
        evidence_hash=evidence_hash,
        thesis_semantic_identity_hash=thesis.semantic_identity_hash,
        source_m1_ids=tuple(sorted(item.material_candle_hash for item in evidence.material_m1_candles)),
        source_m1_evidence_ids=tuple(sorted(item.candle_evidence_id for item in evidence.material_m1_candles)),
        last_observed_at_utc=evidence.observed_at_utc,
        last_source_request_id=evidence.source_request_id,
    )
    if evidence.freeze_requested:
        status = "FROZEN" if previous is None else status
    return ExecutionBoxReductionResult(status, box=box, previous_box=previous)


__all__ = [
    "ExecutionBoxReductionResult",
    "ExecutionBoxReductionStatus",
    "close_execution_box",
    "execution_box_evidence_hash",
    "execution_box_id",
    "material_box_hash",
    "reduce_execution_box",
    "route_geometry_bounds",
]
