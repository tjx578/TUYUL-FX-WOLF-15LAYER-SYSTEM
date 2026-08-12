"""Pure P4 builder for ordered H1/M15 proofs and immutable thesis identity."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from contracts.strategy_5scr_context_epoch_v1 import StrategyContextEpochV1
from contracts.strategy_5scr_directional_thesis_v1 import (
    DIRECTIONAL_THESIS_RULE_VERSION,
    ClosedCandleAuthorityRefV1,
    DirectionalThesisEvidenceV1,
    DirectionalThesisV1,
    H1StructureProofV1,
    M15StructuralProofV1,
    pressure_authority_material_hash,
    route_authorization_material_hash,
)

ThesisBuildStatus = Literal["READY", "WAIT", "REJECTED", "QUARANTINED"]


def _sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def candle_material_hash(candle: ClosedCandleAuthorityRefV1) -> str:
    return _sha256(
        {
            "symbol": candle.symbol,
            "timeframe": candle.timeframe,
            "open_time_utc": candle.open_time_utc,
            "close_time_utc": candle.close_time_utc,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
        }
    )


def candle_evidence_hash(candle: ClosedCandleAuthorityRefV1) -> str:
    payload = candle.model_dump(mode="json")
    payload.pop("candle_evidence_id", None)
    return _sha256(payload)


def _validate_candle_identity(candle: ClosedCandleAuthorityRefV1) -> str | None:
    if candle.material_candle_hash != candle_material_hash(candle):
        return "CANDLE_MATERIAL_HASH_DRIFT"
    if candle.candle_evidence_id != candle_evidence_hash(candle):
        return "CANDLE_EVIDENCE_ID_DRIFT"
    return None


@dataclass(frozen=True)
class DirectionalThesisBuildArtifact:
    h1_proof: H1StructureProofV1
    m15_proof: M15StructuralProofV1
    structural_proof_hash: str
    counter_pressure_proof_hash: str | None
    semantic_identity_hash: str


@dataclass(frozen=True)
class DirectionalThesisBuildResult:
    status: ThesisBuildStatus
    reason_code: str | None = None
    artifact: DirectionalThesisBuildArtifact | None = None


def _h1_proof(
    context: StrategyContextEpochV1,
    evidence: DirectionalThesisEvidenceV1,
) -> H1StructureProofV1 | None:
    direction = evidence.strategy_direction
    candles = evidence.h1_candles
    for index in range(1, len(candles)):
        anchor, confirmation = candles[index - 1 : index + 1]
        if anchor.close_time_utc != confirmation.open_time_utc:
            continue
        if confirmation.close_time_utc < context.opened_at_utc:
            continue
        broke = confirmation.close > anchor.high if direction == "BUY" else confirmation.close < anchor.low
        if not broke:
            continue
        reference_level = anchor.high if direction == "BUY" else anchor.low
        material_payload = {
            "context_epoch_id": context.context_epoch_id,
            "strategy_direction": direction,
            "anchor_material_hash": anchor.material_candle_hash,
            "confirmation_material_hash": confirmation.material_candle_hash,
            "reference_level": reference_level,
            "structure_event": "BOS",
            "rule_version": DIRECTIONAL_THESIS_RULE_VERSION,
        }
        material_hash = _sha256(material_payload)
        evidence_payload = {
            **material_payload,
            "anchor": anchor.model_dump(mode="json"),
            "confirmation": confirmation.model_dump(mode="json"),
            "decision_at_utc": evidence.decision_at_utc,
        }
        evidence_hash = _sha256(evidence_payload)
        return H1StructureProofV1(
            h1_proof_id="5scr-h1-proof:" + material_hash.removeprefix("sha256:")[:32],
            strategy_lifecycle_id=evidence.strategy_lifecycle_id,
            context_epoch_id=evidence.context_epoch_id,
            symbol=evidence.symbol,
            strategy_direction=direction,
            structure_event="BOS",
            anchor_candle=anchor,
            confirmation_candle=confirmation,
            reference_level=reference_level,
            confirmation_close=confirmation.close,
            confirmed_at_utc=confirmation.close_time_utc,
            decision_at_utc=evidence.decision_at_utc,
            coverage_start_at_utc=anchor.open_time_utc,
            coverage_end_at_utc=confirmation.close_time_utc,
            source_candle_ids=(anchor.candle_evidence_id, confirmation.candle_evidence_id),
            source_content_hashes=(anchor.source_content_hash, confirmation.source_content_hash),
            material_proof_hash=material_hash,
            evidence_hash=evidence_hash,
            semantic_dedupe_key=f"{context.context_epoch_id}|{direction}|H1|{material_hash}",
        )
    return None


def _m15_proof(
    context: StrategyContextEpochV1,
    evidence: DirectionalThesisEvidenceV1,
    h1: H1StructureProofV1,
) -> M15StructuralProofV1 | None:
    direction = evidence.strategy_direction
    candles = evidence.m15_candles
    for index in range(1, len(candles) - 1):
        reference, breakout = candles[index - 1 : index + 1]
        if reference.close_time_utc != breakout.open_time_utc:
            continue
        if breakout.close_time_utc < h1.confirmed_at_utc:
            continue
        level = reference.high if direction == "BUY" else reference.low
        broke = breakout.close > level if direction == "BUY" else breakout.close < level
        if not broke:
            continue
        completion = candles[index + 1]
        if breakout.close_time_utc != completion.open_time_utc:
            continue
        if direction == "BUY":
            closes_beyond = completion.close > level
            retest = completion.low <= level and closes_beyond
        else:
            closes_beyond = completion.close < level
            retest = completion.high >= level and closes_beyond
        if not closes_beyond:
            continue
        failed_reclaim = (
            completion.open <= level < completion.close
            if direction == "BUY"
            else completion.open >= level > completion.close
        )
        completion_kind = "FAILED_RECLAIM" if failed_reclaim else ("RETEST" if retest else "ACCEPTANCE")
        material_payload = {
            "context_epoch_id": context.context_epoch_id,
            "h1_proof_id": h1.h1_proof_id,
            "strategy_direction": direction,
            "reference_material_hash": reference.material_candle_hash,
            "break_material_hash": breakout.material_candle_hash,
            "completion_material_hash": completion.material_candle_hash,
            "break_level": level,
            "completion_kind": completion_kind,
            "rule_version": DIRECTIONAL_THESIS_RULE_VERSION,
        }
        material_hash = _sha256(material_payload)
        evidence_payload = {
            **material_payload,
            "reference": reference.model_dump(mode="json"),
            "break": breakout.model_dump(mode="json"),
            "completion": completion.model_dump(mode="json"),
            "decision_at_utc": evidence.decision_at_utc,
        }
        evidence_hash = _sha256(evidence_payload)
        return M15StructuralProofV1(
            m15_proof_id="5scr-m15-proof:" + material_hash.removeprefix("sha256:")[:32],
            h1_proof_id=h1.h1_proof_id,
            strategy_lifecycle_id=evidence.strategy_lifecycle_id,
            context_epoch_id=evidence.context_epoch_id,
            symbol=evidence.symbol,
            strategy_direction=direction,
            reference_candle=reference,
            break_candle=breakout,
            completion_candle=completion,
            break_level=level,
            h1_confirmed_at_utc=h1.confirmed_at_utc,
            break_close_at_utc=breakout.close_time_utc,
            completed_at_utc=completion.close_time_utc,
            completion_kind=completion_kind,
            decision_at_utc=evidence.decision_at_utc,
            coverage_start_at_utc=reference.open_time_utc,
            coverage_end_at_utc=completion.close_time_utc,
            source_candle_ids=(
                reference.candle_evidence_id,
                breakout.candle_evidence_id,
                completion.candle_evidence_id,
            ),
            source_content_hashes=(
                reference.source_content_hash,
                breakout.source_content_hash,
                completion.source_content_hash,
            ),
            material_proof_hash=material_hash,
            evidence_hash=evidence_hash,
            semantic_dedupe_key=f"{context.context_epoch_id}|{direction}|M15|{material_hash}",
        )
    return None


def build_directional_thesis_proofs(
    *,
    context: StrategyContextEpochV1,
    evidence: DirectionalThesisEvidenceV1,
) -> DirectionalThesisBuildResult:
    """Recompute and validate one legal, ordered structural proof chain."""

    if context.strategy_lifecycle_id != evidence.strategy_lifecycle_id:
        return DirectionalThesisBuildResult("REJECTED", "THESIS_LIFECYCLE_MISMATCH")
    if context.context_epoch_id != evidence.context_epoch_id:
        return DirectionalThesisBuildResult("REJECTED", "THESIS_CONTEXT_EPOCH_MISMATCH")
    if context.symbol != evidence.symbol:
        return DirectionalThesisBuildResult("REJECTED", "THESIS_SYMBOL_MISMATCH")
    if context.state != "ACTIVE":
        return DirectionalThesisBuildResult("REJECTED", "CONTEXT_EPOCH_NOT_ACTIVE")
    if pressure_authority_material_hash(evidence.pressure_authority) != evidence.pressure_authority.authority_hash:
        return DirectionalThesisBuildResult("QUARANTINED", "PRESSURE_AUTHORITY_HASH_MISMATCH")
    if (
        evidence.route_authorization is not None
        and route_authorization_material_hash(evidence.route_authorization)
        != evidence.route_authorization.authorization_hash
    ):
        return DirectionalThesisBuildResult("QUARANTINED", "ROUTE_AUTHORIZATION_HASH_MISMATCH")
    if evidence.decision_at_utc < context.opened_at_utc:
        return DirectionalThesisBuildResult("REJECTED", "DECISION_PRECEDES_CONTEXT_EPOCH")
    if evidence.pressure_authority.observed_at_utc > evidence.decision_at_utc:
        return DirectionalThesisBuildResult("QUARANTINED", "FUTURE_PRESSURE_AUTHORITY")
    if (
        evidence.pressure_authority.valid_until_utc is not None
        and evidence.pressure_authority.valid_until_utc < evidence.decision_at_utc
    ):
        return DirectionalThesisBuildResult("REJECTED", "PRESSURE_AUTHORITY_EXPIRED")

    direction = evidence.strategy_direction
    domain = context.direction_domain
    if domain in {"UNRESOLVED", "EMPTY"}:
        return DirectionalThesisBuildResult("WAIT", "CONTEXT_DIRECTION_DOMAIN_UNRESOLVED")
    if domain == "BUY_ONLY" and direction != "BUY":
        return DirectionalThesisBuildResult("REJECTED", "CONTEXT_DIRECTION_DOMAIN_MISMATCH")
    if domain == "SELL_ONLY" and direction != "SELL":
        return DirectionalThesisBuildResult("REJECTED", "CONTEXT_DIRECTION_DOMAIN_MISMATCH")
    if evidence.selected_route not in context.allowed_routes or evidence.selected_route in context.blocked_routes:
        return DirectionalThesisBuildResult("REJECTED", "CONTEXT_ROUTE_NOT_AUTHORIZED")
    route = evidence.route_authorization
    if domain == "BOTH_CONDITIONAL" and route is None:
        return DirectionalThesisBuildResult("REJECTED", "TYPED_ROUTE_AUTHORITY_REQUIRED")
    if route is not None and (
        route.context_epoch_id != context.context_epoch_id
        or route.material_context_hash != context.material_context_hash
        or route.selected_route != evidence.selected_route
        or route.strategy_direction != direction
    ):
        return DirectionalThesisBuildResult("REJECTED", "TYPED_ROUTE_AUTHORITY_MISMATCH")

    pressure = evidence.pressure_authority
    if pressure.mode == "CONSOLIDATED_DIRECTION_CONTRACT":
        if pressure.contract_status != "LOCKED":
            return DirectionalThesisBuildResult("WAIT", "PRESSURE_DIRECTION_CONTRACT_NOT_LOCKED")
        if pressure.contract_direction != direction:
            return DirectionalThesisBuildResult("REJECTED", "LOCKED_PRESSURE_DIRECTION_MISMATCH")
    for candle in (*evidence.h1_candles, *evidence.m15_candles):
        failure = _validate_candle_identity(candle)
        if failure is not None:
            return DirectionalThesisBuildResult("QUARANTINED", failure)

    h1 = _h1_proof(context, evidence)
    if h1 is None:
        return DirectionalThesisBuildResult("WAIT", "H1_CLOSED_STRUCTURE_PROOF_MISSING")
    m15 = _m15_proof(context, evidence, h1)
    if m15 is None:
        return DirectionalThesisBuildResult("WAIT", "M15_ORDERED_BREAK_COMPLETION_MISSING")

    structural_hash = _sha256(
        {
            "context_epoch_id": context.context_epoch_id,
            "direction": direction,
            "h1_material_proof_hash": h1.material_proof_hash,
            "m15_material_proof_hash": m15.material_proof_hash,
            "rule_version": DIRECTIONAL_THESIS_RULE_VERSION,
        }
    )
    # A route-direction authorization is material only for BOTH_CONDITIONAL.
    # Including an otherwise irrelevant authorization in a single-direction
    # epoch would let lineage churn manufacture a second thesis identity.
    route_hash = route.authorization_hash if domain == "BOTH_CONDITIONAL" and route is not None else None
    counter_pressure_hash = (
        _sha256(
            {
                "context_epoch_id": context.context_epoch_id,
                "from_raw_pressure_direction": pressure.raw_pressure_direction,
                "to_strategy_direction": direction,
                "h1_material_proof_hash": h1.material_proof_hash,
                "m15_material_proof_hash": m15.material_proof_hash,
                "rule_version": DIRECTIONAL_THESIS_RULE_VERSION,
            }
        )
        if pressure.mode == "RADAR_ONLY"
        and pressure.raw_pressure_direction is not None
        and pressure.raw_pressure_direction != direction
        else None
    )
    semantic_hash = _sha256(
        {
            "context_epoch_id": context.context_epoch_id,
            "direction": direction,
            "h1_proof_hash": h1.material_proof_hash,
            "m15_proof_hash": m15.material_proof_hash,
            "selected_route": evidence.selected_route,
            "route_authorization_hash": route_hash,
            "pressure_authority_hash": pressure.authority_hash,
            "counter_pressure_proof_hash": counter_pressure_hash,
            "rule_version": DIRECTIONAL_THESIS_RULE_VERSION,
        }
    )
    return DirectionalThesisBuildResult(
        "READY",
        artifact=DirectionalThesisBuildArtifact(
            h1_proof=h1,
            m15_proof=m15,
            structural_proof_hash=structural_hash,
            counter_pressure_proof_hash=counter_pressure_hash,
            semantic_identity_hash=semantic_hash,
        ),
    )


def close_directional_thesis(
    thesis: DirectionalThesisV1,
    *,
    state: Literal["INVALIDATED", "TERMINAL"],
    closed_at_utc: datetime,
    reason: str,
) -> DirectionalThesisV1:
    """Close without mutating immutable direction, parent, or proof identity."""

    if thesis.state != "ACTIVE":
        return thesis
    return DirectionalThesisV1.model_validate(
        {
            **thesis.model_dump(),
            "state": state,
            "closed_at_utc": closed_at_utc,
            "closure_reason": reason,
            "state_version": thesis.state_version + 1,
        }
    )


__all__ = [
    "DirectionalThesisBuildArtifact",
    "DirectionalThesisBuildResult",
    "ThesisBuildStatus",
    "build_directional_thesis_proofs",
    "candle_evidence_hash",
    "candle_material_hash",
    "close_directional_thesis",
]
