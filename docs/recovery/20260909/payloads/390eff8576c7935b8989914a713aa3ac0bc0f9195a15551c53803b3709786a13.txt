"""Deterministic StrategyAnalysisAdmissionV1 policy.

The policy deliberately does not count emitted log rows.  Maturity comes from
the analyzer's deduplicated effective-event block, material duration and
direction persistence.  Quote or context quality changes the next analysis
state; it never upgrades advisory pressure into execution authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from contracts.strategy_5scr_analysis_admission import (
    AnalysisContextAlignment,
    AnalysisDirection,
    DirectionLineageAlignment,
    StrategyAnalysisAdmissionV1,
)
from contracts.strategy_5scr_pair_admission import PairAdmissionGrant


class StrategyAnalysisAdmissionPolicyV1(BaseModel):
    """Versioned universal thresholds for mature advisory admission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mature_duration_seconds: float = Field(default=300.0, ge=60.0, le=86_400.0)
    mature_effective_events: int = Field(default=3, ge=3, le=10_000)
    extreme_duration_seconds: float = Field(default=1_800.0, ge=300.0, le=172_800.0)
    extreme_effective_events: int = Field(default=100, ge=3, le=1_000_000)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    resolved = str(value).strip()
    return resolved or None


def _upper(value: Any) -> str | None:
    resolved = _text(value)
    return None if resolved is None else resolved.upper()


def _number(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _integer(value: Any) -> int:
    return int(_number(value))


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode()).hexdigest()


def _directions(payload: Mapping[str, Any]) -> tuple[AnalysisDirection, DirectionLineageAlignment]:
    advertised = _upper(payload.get("pressure_direction_consensus_status"))
    if advertised == "CONFLICT":
        return "CONFLICT", "CONFLICT"
    values = {
        value
        for value in (
            _upper(payload.get("raw_direction")),
            _upper(payload.get("candidate_direction")),
            _upper(payload.get("watch_direction")),
            _upper(payload.get("block_direction")),
        )
        if value in {"BUY", "SELL"}
    }
    if len(values) > 1:
        return "CONFLICT", "CONFLICT"
    if not values:
        return "INCOMPLETE", "UNAVAILABLE"
    return cast(AnalysisDirection, next(iter(values))), "ALIGNED"


def _context_alignment(payload: Mapping[str, Any], direction: AnalysisDirection) -> AnalysisContextAlignment:
    raw_htf = payload.get("htf_structure_context")
    htf = raw_htf if isinstance(raw_htf, Mapping) else {}
    if not htf and _text(payload.get("material_context_hash")) is None:
        return "UNAVAILABLE"
    playbook = _upper(htf.get("allowed_playbook")) or ""
    blocked_raw = htf.get("blocked_playbook")
    blocked = {str(item).upper() for item in (blocked_raw if isinstance(blocked_raw, (list, tuple, set)) else ())}
    daily = _upper(htf.get("daily_bias"))
    if direction == "SELL" and (
        ("BUY" in playbook and "SELL" not in playbook)
        or any(item.startswith("SELL") for item in blocked)
        or daily == "BULLISH"
    ):
        return "CONTEXT_CONFLICT"
    if direction == "BUY" and (
        ("SELL" in playbook and "BUY" not in playbook)
        or any(item.startswith("BUY") for item in blocked)
        or daily == "BEARISH"
    ):
        return "CONTEXT_CONFLICT"
    if playbook in {"", "NONE"}:
        return "DEFERRED"
    return "ALIGNED"


def _event_time(payload: Mapping[str, Any], observed_at_utc: datetime | None) -> datetime:
    return (
        observed_at_utc
        or _datetime(payload.get("signal_valid_time_utc"))
        or _datetime(payload.get("generated_at_utc"))
        or datetime.now(UTC)
    ).astimezone(UTC)


def _logical_anchor(payload: Mapping[str, Any], *, observed_at: datetime) -> str:
    return (
        _text(payload.get("source_clean_block_id"))
        or _text(payload.get("block_start_utc"))
        or _text(payload.get("current_block_start_utc"))
        or _text(payload.get("cluster_id"))
        or observed_at.isoformat()
    )


def _identity(
    payload: Mapping[str, Any],
    *,
    admission_class: str,
    direction: AnalysisDirection,
    observed_at: datetime,
) -> str:
    basis = {
        "deployment_id": _text(payload.get("deployment_id")) or "unknown",
        "symbol": _upper(payload.get("symbol")) or "UNKNOWN",
        "admission_class": admission_class,
        "direction": direction,
        "episode_anchor": _logical_anchor(payload, observed_at=observed_at),
    }
    return "5scr-analysis-admission:" + hashlib.sha256(_canonical(basis).encode()).hexdigest()[:32]


def _canonical_admission(
    payload: Mapping[str, Any],
    *,
    source_pressure_event_id: str | None,
    observed_at: datetime,
) -> StrategyAnalysisAdmissionV1 | None:
    raw_grant = payload.get("pair_admission_grant")
    if not isinstance(raw_grant, Mapping):
        return None
    try:
        grant = PairAdmissionGrant.model_validate(dict(raw_grant))
    except ValidationError:
        return None
    pair_id = _text(payload.get("pair_admission_id"))
    if (
        _upper(payload.get("pair_admission_status")) != "GRANTED"
        or pair_id != grant.pair_admission_id
        or _text(payload.get("pair_admission_rule_version")) != grant.rule_version
        or _text(payload.get("pair_admission_source_ledger_hash")) != grant.source_ledger_hash
    ):
        return None
    direction, alignment = _directions(payload)
    expires = grant.expires_at_utc
    admitted = grant.granted_at_utc
    reasons: list[str] = []
    status = "GRANTED"
    if direction not in {"BUY", "SELL"} or alignment != "ALIGNED":
        status = "SUSPENDED"
        admitted = None
        reasons.append("CANONICAL_DIRECTION_NOT_ALIGNED")
    elif direction != grant.direction:
        status = "SUSPENDED"
        admitted = None
        reasons.append("CANONICAL_GRANT_DIRECTION_MISMATCH")
    if expires is not None and expires <= observed_at:
        status = "SUSPENDED"
        admitted = None
        expires = None
        reasons.append("CANONICAL_PAIR_ADMISSION_EXPIRED")
    evidence = {
        "pair_admission_id": pair_id,
        "source_ledger_hash": grant.source_ledger_hash,
        "direction": direction,
        "observed_at": observed_at,
    }
    analysis_state = "CANONICAL_ANALYSIS_READY" if status == "GRANTED" else "ADVISORY_WAITING_PRESSURE_RESOLUTION"
    context_alignment = _context_alignment(payload, direction)
    return StrategyAnalysisAdmissionV1(
        analysis_admission_id=_identity(
            payload,
            admission_class="CANONICAL_RAW",
            direction=direction,
            observed_at=observed_at,
        ),
        symbol=_upper(payload.get("symbol")) or "UNKNOWN",
        admission_class="CANONICAL_RAW",
        admission_status=status,
        analysis_authority="FULL_CANONICAL_ANALYSIS",
        source_authority="RAW_SIGNAL_THROTTLE_LEDGER",
        pressure_direction=direction,
        direction_lineage_alignment=alignment,
        advisory_maturity="MATURE",
        context_alignment=context_alignment,
        analysis_state=analysis_state,
        context_resolution_allowed=status == "GRANTED",
        structural_evidence_prefetch_required=status == "GRANTED",
        shadow_tradeplan_allowed=status == "GRANTED",
        strategy_next_required_stage=(
            f"H1_M15_{direction}_CONFIRMATION" if status == "GRANTED" else "PRESSURE_DIRECTION_RESOLUTION"
        ),
        source_pressure_event_id=source_pressure_event_id,
        pair_admission_id=pair_id,
        observed_at_utc=observed_at,
        admitted_at_utc=admitted,
        expires_at_utc=expires,
        reason_codes=tuple(reasons),
        analysis_material_hash=_sha256(
            {
                "pair_admission_id": pair_id,
                "analysis_state": analysis_state,
                "direction": direction,
                "context_alignment": context_alignment,
                "material_context_hash": payload.get("material_context_hash"),
            }
        ),
        evidence_hash=_sha256(evidence),
    )


def evaluate_strategy_analysis_admission(
    payload: Mapping[str, Any],
    *,
    source_pressure_event_id: str | None = None,
    observed_at_utc: datetime | None = None,
    policy: StrategyAnalysisAdmissionPolicyV1 | None = None,
) -> StrategyAnalysisAdmissionV1:
    """Evaluate canonical or advisory pressure without granting execution."""

    resolved_policy = policy or StrategyAnalysisAdmissionPolicyV1()
    observed_at = _event_time(payload, observed_at_utc)
    canonical = _canonical_admission(
        payload,
        source_pressure_event_id=source_pressure_event_id,
        observed_at=observed_at,
    )
    if canonical is not None:
        return canonical

    symbol = _upper(payload.get("symbol")) or "UNKNOWN"
    direction, alignment = _directions(payload)
    duration = _number(
        payload.get("current_block_duration_seconds")
        if payload.get("current_block_duration_seconds") is not None
        else payload.get("block_duration_seconds")
    )
    ticks = _integer(
        payload.get("current_block_effective_ticks")
        if payload.get("current_block_effective_ticks") is not None
        else payload.get("block_effective_ticks")
    )
    resolution = _upper(
        payload.get("pressure_direction_resolution")
        or payload.get("pressure_resolution_status")
        or payload.get("pressure_resolution")
    )
    expires = _datetime(payload.get("raw_direction_expires_at_utc"))
    expired = resolution == "EXPIRED" or (expires is not None and expires <= observed_at)
    if expired:
        maturity = "EXPIRED"
    elif duration >= resolved_policy.extreme_duration_seconds and ticks >= resolved_policy.extreme_effective_events:
        maturity = "EXTREME"
    elif duration >= resolved_policy.mature_duration_seconds and ticks >= resolved_policy.mature_effective_events:
        maturity = "MATURE"
    else:
        maturity = "IMMATURE"

    source_is_advisory = any(
        (
            (_text(payload.get("pressure_source")) or "").lower() == "signal_throttle_check",
            _upper(payload.get("source_stream")) == "CANARY",
            _upper(payload.get("raw_direction_role")) == "SHORT_HORIZON_PRESSURE_RADAR_ONLY",
        )
    )
    context_alignment = _context_alignment(payload, direction)
    eligible = payload.get("raw_direction_eligible_for_context_resolution") is True
    quote = _upper(payload.get("quote_health_status")) or "UNKNOWN"
    reasons: list[str] = []

    if alignment == "CONFLICT":
        status = "SUSPENDED"
        state = "ADVISORY_WAITING_PRESSURE_RESOLUTION"
        next_stage = "PRESSURE_DIRECTION_RESOLUTION"
        reasons.append("DIRECTION_LINEAGE_CONFLICT")
    elif not source_is_advisory:
        status = "REJECTED"
        state = "ADVISORY_INVALIDATED"
        next_stage = "NONE"
        reasons.append("SOURCE_NOT_DERIVED_PRESSURE_ADVISORY")
    elif maturity == "EXPIRED":
        status = "REJECTED"
        state = "ADVISORY_EXPIRED"
        next_stage = "NONE"
        reasons.append("ADVISORY_PRESSURE_EXPIRED")
    elif maturity == "IMMATURE":
        status = "REJECTED"
        state = "ADVISORY_OBSERVED_IMMATURE"
        next_stage = "PRESSURE_MATURITY"
        reasons.append("ADVISORY_PRESSURE_IMMATURE")
    elif direction not in {"BUY", "SELL"}:
        status = "SUSPENDED"
        state = "ADVISORY_WAITING_PRESSURE_RESOLUTION"
        next_stage = "PRESSURE_DIRECTION_RESOLUTION"
        reasons.append("PRESSURE_DIRECTION_INCOMPLETE")
    elif not eligible:
        status = "SUSPENDED"
        state = "ADVISORY_WAITING_CONTEXT"
        next_stage = "CONTEXT_ELIGIBILITY_RESOLUTION"
        reasons.append("PRESSURE_NOT_CONTEXT_RESOLUTION_ELIGIBLE")
    else:
        status = "GRANTED"
        if quote in {"PRICE_FROZEN", "PRICE_QUALITY_WARMING_UP", "INSUFFICIENT_HISTORY", "OUT_OF_ORDER"}:
            state = "ADVISORY_WAITING_PRICE_QUALITY"
            next_stage = f"PRICE_QUALITY_THEN_H1_M15_{direction}_CONFIRMATION"
            reasons.append("LIVE_ENTRY_PRICE_QUALITY_BLOCKED")
        elif context_alignment in {"UNAVAILABLE", "DEFERRED"}:
            state = "ADVISORY_WAITING_CONTEXT"
            next_stage = "MATERIAL_CONTEXT"
            reasons.append("MATERIAL_CONTEXT_PREFETCH_REQUIRED")
        elif context_alignment == "CONTEXT_CONFLICT":
            state = "ADVISORY_WAITING_H1"
            next_stage = f"STRICT_H1_M15_{direction}_CONFIRMATION"
            reasons.append("CONTEXT_CONFLICT_REQUIRES_STRICT_PROOF")
        else:
            state = "ADVISORY_ANALYSIS_READY"
            next_stage = f"H1_M15_{direction}_CONFIRMATION"

    admitted_at = None
    if status == "GRANTED":
        block_start = _datetime(payload.get("block_start_utc") or payload.get("current_block_start_utc"))
        admitted_at = (
            block_start + timedelta(seconds=resolved_policy.mature_duration_seconds)
            if block_start is not None
            else observed_at
        )
        admitted_at = min(admitted_at, observed_at)

    evidence = {
        "symbol": symbol,
        "direction": direction,
        "alignment": alignment,
        "duration_seconds": duration,
        "deduplicated_effective_events": ticks,
        "maturity": maturity,
        "resolution": resolution,
        "context_hash": payload.get("material_context_hash"),
        "context_alignment": context_alignment,
        "quote_health": quote,
        "episode_anchor": _logical_anchor(payload, observed_at=observed_at),
    }
    return StrategyAnalysisAdmissionV1(
        analysis_admission_id=_identity(
            payload,
            admission_class="MATURE_ADVISORY",
            direction=direction,
            observed_at=observed_at,
        ),
        symbol=symbol,
        admission_class="MATURE_ADVISORY",
        admission_status=status,
        analysis_authority="FULL_SHADOW_ANALYSIS",
        source_authority="DERIVED_PRESSURE_ADVISORY",
        pressure_direction=direction,
        direction_lineage_alignment=alignment,
        advisory_maturity=maturity,
        context_alignment=context_alignment,
        analysis_state=state,
        context_resolution_allowed=status == "GRANTED",
        structural_evidence_prefetch_required=status == "GRANTED",
        shadow_tradeplan_allowed=status == "GRANTED",
        strategy_next_required_stage=next_stage,
        source_pressure_event_id=source_pressure_event_id,
        observed_at_utc=observed_at,
        admitted_at_utc=admitted_at,
        expires_at_utc=expires if expires is None or expires > observed_at else None,
        reason_codes=tuple(dict.fromkeys(reasons)),
        analysis_material_hash=_sha256(
            {
                "analysis_admission_id": _identity(
                    payload,
                    admission_class="MATURE_ADVISORY",
                    direction=direction,
                    observed_at=observed_at,
                ),
                "analysis_state": state,
                "direction": direction,
                "context_alignment": context_alignment,
                "material_context_hash": payload.get("material_context_hash"),
            }
        ),
        evidence_hash=_sha256(evidence),
    )


def strategy_analysis_admission_payload(
    payload: Mapping[str, Any],
    *,
    source_pressure_event_id: str | None = None,
    observed_at_utc: datetime | None = None,
) -> dict[str, Any]:
    admission = evaluate_strategy_analysis_admission(
        payload,
        source_pressure_event_id=source_pressure_event_id,
        observed_at_utc=observed_at_utc,
    )
    return admission.model_dump(mode="json")


__all__ = [
    "StrategyAnalysisAdmissionPolicyV1",
    "evaluate_strategy_analysis_admission",
    "strategy_analysis_admission_payload",
]
