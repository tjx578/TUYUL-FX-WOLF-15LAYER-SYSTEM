"""Pure reducer for durable, shadow-only Strategy 5S-CR ContextEpoch V1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from contracts.strategy_5scr_context_epoch_v1 import (
    ContextTransitionReason,
    ContextTransitionV1,
    MaterialContextEvidenceV1,
    StrategyContextEpochV1,
)

ContextReductionStatus = Literal[
    "OPENED",
    "CONFIRMED",
    "TRANSITIONED",
    "TERMINATED",
    "DUPLICATE",
    "REJECTED",
    "WAITING_CONTEXT_EVIDENCE",
    "QUARANTINED_CONTEXT_EVIDENCE",
]


def _sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def context_evidence_hash(evidence: MaterialContextEvidenceV1) -> str:
    """Hash complete evidence, including lineage-only audit fields."""

    return _sha256(evidence.model_dump(mode="json"))


def material_context_hash(evidence: MaterialContextEvidenceV1) -> str:
    """Fingerprint only positive-listed market context authority.

    Telemetry, deployment, publisher, timestamps, reference-price refreshes,
    and Microboost provenance are deliberately excluded.
    """

    payload = {
        "symbol": evidence.symbol,
        "d1_source_candle_ids": sorted(item.candle_id for item in evidence.d1_candles),
        "h4_source_candle_ids": sorted(item.candle_id for item in evidence.h4_candles),
        "daily_bias": evidence.daily_bias,
        "h4_structure": evidence.h4_structure,
        "price_location": evidence.price_location,
        "liquidity_state": evidence.liquidity_state,
        "direction_domain": evidence.direction_domain,
        "allowed_routes": list(evidence.allowed_routes),
        "blocked_routes": list(evidence.blocked_routes),
        "target_map_version": evidence.target_map_version,
        "structural_invalidation_version": evidence.structural_invalidation_version,
    }
    return _sha256(payload)


def context_evidence_failure(evidence: MaterialContextEvidenceV1) -> tuple[ContextReductionStatus, str] | None:
    """Return a deterministic fail-closed classification, if any."""

    if evidence.future_candle_leakage_detected or any(
        candle.close_time_utc > evidence.observed_at_utc for candle in (*evidence.d1_candles, *evidence.h4_candles)
    ):
        return "QUARANTINED_CONTEXT_EVIDENCE", "FUTURE_CANDLE_LEAKAGE"
    if not evidence.deterministic_context:
        return "QUARANTINED_CONTEXT_EVIDENCE", "MATERIAL_CONTEXT_NON_DETERMINISTIC"
    if any(
        not candle.provider_session_lineage_valid or candle.provider_timestamp_semantics == "UNSPECIFIED"
        for candle in (*evidence.d1_candles, *evidence.h4_candles)
    ):
        return "QUARANTINED_CONTEXT_EVIDENCE", "PROVIDER_SESSION_LINEAGE_INVALID"
    if not evidence.d1_candles:
        return "WAITING_CONTEXT_EVIDENCE", "D1_CLOSED_CANDLE_EVIDENCE_MISSING"
    if not evidence.h4_candles:
        return "WAITING_CONTEXT_EVIDENCE", "H4_CLOSED_CANDLE_EVIDENCE_MISSING"
    if any(not candle.complete for candle in (*evidence.d1_candles, *evidence.h4_candles)):
        return "WAITING_CONTEXT_EVIDENCE", "SOURCE_CANDLE_INCOMPLETE"
    if any(not candle.structural_authority for candle in evidence.d1_candles):
        return "WAITING_CONTEXT_EVIDENCE", "D1_STRUCTURAL_AUTHORITY_MISSING"
    if any(not candle.structural_authority for candle in evidence.h4_candles):
        return "WAITING_CONTEXT_EVIDENCE", "H4_STRUCTURAL_AUTHORITY_MISSING"
    required = {
        "DAILY_BIAS": evidence.daily_bias,
        "H4_STRUCTURE": evidence.h4_structure,
        "PRICE_LOCATION": evidence.price_location,
        "LIQUIDITY_STATE": evidence.liquidity_state,
        "DIRECTION_DOMAIN": evidence.direction_domain,
    }
    missing = tuple(sorted(name for name, value in required.items() if value is None or not str(value).strip()))
    if missing:
        return "WAITING_CONTEXT_EVIDENCE", "MATERIAL_CONTEXT_FIELDS_MISSING:" + ",".join(missing)
    return None


def _epoch_id(strategy_lifecycle_id: str, sequence: int, opened_at_utc: datetime) -> str:
    basis = f"{strategy_lifecycle_id}|{sequence}|{opened_at_utc.isoformat()}"
    return "5scr-context:" + hashlib.sha256(basis.encode()).hexdigest()[:32]


def _transition_id(dedupe_key: str, occurred_at_utc: datetime) -> str:
    basis = f"{dedupe_key}|{occurred_at_utc.isoformat()}"
    return "5scr-context-transition:" + hashlib.sha256(basis.encode()).hexdigest()[:32]


def _open_epoch(
    strategy_lifecycle_id: str,
    sequence: int,
    evidence: MaterialContextEvidenceV1,
    reason: ContextTransitionReason,
) -> StrategyContextEpochV1:
    material_hash = material_context_hash(evidence)
    evidence_hash = context_evidence_hash(evidence)
    assert evidence.daily_bias is not None
    assert evidence.h4_structure is not None
    assert evidence.price_location is not None
    assert evidence.liquidity_state is not None
    assert evidence.direction_domain is not None
    return StrategyContextEpochV1(
        context_epoch_id=_epoch_id(strategy_lifecycle_id, sequence, evidence.observed_at_utc),
        strategy_lifecycle_id=strategy_lifecycle_id,
        symbol=evidence.symbol,
        epoch_sequence=sequence,
        state="ACTIVE",
        material_context_hash=material_hash,
        opened_at_utc=evidence.observed_at_utc,
        last_confirmed_at_utc=evidence.observed_at_utc,
        daily_source_candle_ids=tuple(sorted(item.candle_id for item in evidence.d1_candles)),
        h4_source_candle_ids=tuple(sorted(item.candle_id for item in evidence.h4_candles)),
        daily_bias=evidence.daily_bias,
        h4_structure=evidence.h4_structure,
        price_location=evidence.price_location,
        liquidity_state=evidence.liquidity_state,
        direction_domain=evidence.direction_domain,
        allowed_routes=evidence.allowed_routes,
        blocked_routes=evidence.blocked_routes,
        target_map_version=evidence.target_map_version,
        structural_invalidation_version=evidence.structural_invalidation_version,
        transition_reason=reason,
        evidence_hash=evidence_hash,
        last_observed_at_utc=evidence.observed_at_utc,
        last_source_event_id=evidence.source_pressure_event_id,
    )


def _transition(
    *,
    strategy_lifecycle_id: str,
    previous_id: str | None,
    next_id: str | None,
    reason: ContextTransitionReason,
    evidence: MaterialContextEvidenceV1,
    material_hash: str | None = None,
    occurred_at_utc: datetime | None = None,
) -> ContextTransitionV1:
    dedupe_key = "|".join(
        (
            strategy_lifecycle_id,
            reason,
            previous_id or "NONE",
            next_id or "NONE",
            evidence.source_pressure_event_id,
        )
    )
    occurred_at = evidence.observed_at_utc if occurred_at_utc is None else occurred_at_utc
    return ContextTransitionV1(
        transition_id=_transition_id(dedupe_key, occurred_at),
        strategy_lifecycle_id=strategy_lifecycle_id,
        from_context_epoch_id=previous_id,
        to_context_epoch_id=next_id,
        reason=reason,
        source_pressure_event_id=evidence.source_pressure_event_id,
        source_event_ids=evidence.source_event_ids,
        occurred_at_utc=occurred_at,
        material_context_hash=material_hash or material_context_hash(evidence),
        evidence_hash=context_evidence_hash(evidence),
        dedupe_key=dedupe_key,
    )


@dataclass(frozen=True)
class ContextReductionResult:
    status: ContextReductionStatus
    reason_code: str | None = None
    previous_epoch: StrategyContextEpochV1 | None = None
    epoch: StrategyContextEpochV1 | None = None
    transition: ContextTransitionV1 | None = None


class ContextEpochReducerV1:
    """Fold ordered material context evidence for one canonical lifecycle."""

    def __init__(
        self,
        strategy_lifecycle_id: str,
        symbol: str,
        *,
        initial_epoch: StrategyContextEpochV1 | None = None,
    ) -> None:
        normalized_symbol = symbol.upper()
        if initial_epoch is not None and (
            initial_epoch.strategy_lifecycle_id != strategy_lifecycle_id or initial_epoch.symbol != normalized_symbol
        ):
            raise ValueError("CONTEXT_EPOCH_RECOVERY_IDENTITY_MISMATCH")
        self.strategy_lifecycle_id = strategy_lifecycle_id
        self.symbol = normalized_symbol
        self._epoch = initial_epoch

    @property
    def epoch(self) -> StrategyContextEpochV1 | None:
        return self._epoch

    def ingest(self, evidence: MaterialContextEvidenceV1) -> ContextReductionResult:
        if evidence.symbol != self.symbol:
            return ContextReductionResult(status="REJECTED", reason_code="CONTEXT_SYMBOL_MISMATCH")
        failure = context_evidence_failure(evidence)
        if failure is not None:
            return ContextReductionResult(status=failure[0], reason_code=failure[1], epoch=self._epoch)
        current = self._epoch
        if current is not None:
            incoming_cursor = (evidence.observed_at_utc, evidence.source_pressure_event_id)
            durable_cursor = (current.last_observed_at_utc, current.last_source_event_id)
            same_source = evidence.source_pressure_event_id == current.last_source_event_id
            if same_source:
                if material_context_hash(evidence) != current.material_context_hash:
                    return ContextReductionResult(
                        status="QUARANTINED_CONTEXT_EVIDENCE",
                        reason_code="SOURCE_EVENT_MATERIAL_CONTEXT_DRIFT",
                        epoch=current,
                    )
                if context_evidence_hash(evidence) != current.evidence_hash:
                    return ContextReductionResult(
                        status="QUARANTINED_CONTEXT_EVIDENCE",
                        reason_code="SOURCE_EVENT_CONTEXT_EVIDENCE_DRIFT",
                        epoch=current,
                    )
                return ContextReductionResult(
                    status="DUPLICATE",
                    reason_code="SOURCE_EVENT_ALREADY_OBSERVED",
                    epoch=current,
                )
            if incoming_cursor <= durable_cursor:
                return ContextReductionResult(
                    status="REJECTED",
                    reason_code="NON_MONOTONIC_CONTEXT_ORDER",
                    epoch=current,
                )
            if current.state == "TERMINAL":
                return ContextReductionResult(status="REJECTED", reason_code="TERMINAL_CONTEXT_EPOCH", epoch=current)
            if current.state != "ACTIVE":
                return ContextReductionResult(
                    status="REJECTED", reason_code="CONTEXT_EPOCH_STATE_INVALID", epoch=current
                )

        if current is None:
            epoch = _open_epoch(self.strategy_lifecycle_id, 1, evidence, "OPENED")
            transition = _transition(
                strategy_lifecycle_id=self.strategy_lifecycle_id,
                previous_id=None,
                next_id=epoch.context_epoch_id,
                reason="OPENED",
                evidence=evidence,
            )
            self._epoch = epoch
            return ContextReductionResult(status="OPENED", epoch=epoch, transition=transition)

        if material_context_hash(evidence) == current.material_context_hash:
            epoch = current.model_copy(
                update={
                    "last_confirmed_at_utc": evidence.observed_at_utc,
                    "last_observed_at_utc": evidence.observed_at_utc,
                    "last_source_event_id": evidence.source_pressure_event_id,
                    "evidence_hash": context_evidence_hash(evidence),
                    "state_version": current.state_version + 1,
                }
            )
            self._epoch = epoch
            return ContextReductionResult(status="CONFIRMED", previous_epoch=current, epoch=epoch)

        closed = current.model_copy(
            update={
                "state": "SUPERSEDED",
                "closed_at_utc": evidence.observed_at_utc,
                "state_version": current.state_version + 1,
            }
        )
        epoch = _open_epoch(
            self.strategy_lifecycle_id,
            current.epoch_sequence + 1,
            evidence,
            "MATERIAL_CONTEXT_CHANGED",
        )
        transition = _transition(
            strategy_lifecycle_id=self.strategy_lifecycle_id,
            previous_id=current.context_epoch_id,
            next_id=epoch.context_epoch_id,
            reason="MATERIAL_CONTEXT_CHANGED",
            evidence=evidence,
        )
        self._epoch = epoch
        return ContextReductionResult(status="TRANSITIONED", previous_epoch=closed, epoch=epoch, transition=transition)

    def terminalize(
        self,
        evidence: MaterialContextEvidenceV1,
        *,
        terminal_at_utc: datetime | None = None,
    ) -> ContextReductionResult:
        current = self._epoch
        if current is None:
            return ContextReductionResult(status="REJECTED", reason_code="NO_ACTIVE_CONTEXT_EPOCH")
        if current.state == "TERMINAL":
            return ContextReductionResult(status="DUPLICATE", reason_code="CONTEXT_ALREADY_TERMINAL", epoch=current)
        if current.state != "ACTIVE":
            return ContextReductionResult(status="REJECTED", reason_code="CONTEXT_EPOCH_STATE_INVALID", epoch=current)

        # Parent lifecycle terminality is authoritative.  A duplicate or late
        # observation must not leave its child ContextEpoch ACTIVE.  Preserve
        # the durable context cursor/evidence unless the terminal observation
        # itself advances them, and close on the authoritative parent clock.
        incoming_cursor = (evidence.observed_at_utc, evidence.source_pressure_event_id)
        durable_cursor = (current.last_observed_at_utc, current.last_source_event_id)
        terminal_at = max(
            terminal_at_utc or evidence.observed_at_utc,
            evidence.observed_at_utc,
            current.last_observed_at_utc,
        )
        cursor_update: dict[str, object] = {}
        if incoming_cursor > durable_cursor:
            cursor_update = {
                "last_observed_at_utc": evidence.observed_at_utc,
                "last_source_event_id": evidence.source_pressure_event_id,
                "evidence_hash": context_evidence_hash(evidence),
            }
        terminal = current.model_copy(
            update={
                "state": "TERMINAL",
                "closed_at_utc": terminal_at,
                "state_version": current.state_version + 1,
                **cursor_update,
            }
        )
        transition = _transition(
            strategy_lifecycle_id=self.strategy_lifecycle_id,
            previous_id=current.context_epoch_id,
            next_id=None,
            reason="LIFECYCLE_TERMINAL",
            evidence=evidence,
            material_hash=current.material_context_hash,
            occurred_at_utc=terminal_at,
        )
        self._epoch = terminal
        return ContextReductionResult(
            status="TERMINATED",
            previous_epoch=terminal,
            epoch=terminal,
            transition=transition,
        )


__all__ = [
    "ContextEpochReducerV1",
    "ContextReductionResult",
    "ContextReductionStatus",
    "context_evidence_failure",
    "context_evidence_hash",
    "material_context_hash",
]
