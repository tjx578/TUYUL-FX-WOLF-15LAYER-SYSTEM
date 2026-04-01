from __future__ import annotations

"""
L10 Router Evaluator — strict constitutional prototype

Analysis-only module for position-sizing / risk-geometry legality.
This module does NOT emit execute, trade_valid, or final verdict.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class L10Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L10FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class L10WarmupState(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class L10FallbackClass(str, Enum):
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class L10CoherenceBand(str, Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class L10BlockerCode(str, Enum):
    UPSTREAM_L6_NOT_CONTINUABLE = "UPSTREAM_L6_NOT_CONTINUABLE"
    REQUIRED_SIZING_SOURCE_MISSING = "REQUIRED_SIZING_SOURCE_MISSING"
    ENTRY_UNAVAILABLE = "ENTRY_UNAVAILABLE"
    STOP_LOSS_UNAVAILABLE = "STOP_LOSS_UNAVAILABLE"
    RISK_INPUT_UNAVAILABLE = "RISK_INPUT_UNAVAILABLE"
    GEOMETRY_INVALID = "GEOMETRY_INVALID"
    POSITION_SIZING_UNAVAILABLE = "POSITION_SIZING_UNAVAILABLE"
    COMPLIANCE_INVALID = "COMPLIANCE_INVALID"
    SIZING_SCORE_BELOW_MINIMUM = "SIZING_SCORE_BELOW_MINIMUM"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


@dataclass(frozen=True)
class L10Input:
    input_ref: str
    timestamp: str
    upstream_l6_continuation_allowed: bool = True

    sizing_sources_used: list[str] = field(default_factory=list)
    required_sizing_sources: list[str] = field(default_factory=list)
    available_sizing_sources: list[str] = field(default_factory=list)

    sizing_score: float = 0.0
    entry_available: bool = True
    stop_loss_available: bool = True
    risk_input_available: bool = True
    geometry_valid: bool = True
    position_sizing_available: bool = True
    compliance_state: str = "VALID"  # VALID | DEGRADED | INVALID

    geometry_non_ideal: bool = False
    sizing_partial: bool = False
    account_limit_proximity_elevated: bool = False

    fallback_class: L10FallbackClass = L10FallbackClass.NO_FALLBACK
    freshness_state: L10FreshnessState = L10FreshnessState.FRESH
    warmup_state: L10WarmupState = L10WarmupState.READY


@dataclass(frozen=True)
class L10EvaluationResult:
    layer: str
    layer_version: str
    timestamp: str
    input_ref: str
    status: L10Status
    continuation_allowed: bool
    blocker_codes: list[str]
    warning_codes: list[str]
    fallback_class: str
    freshness_state: str
    warmup_state: str
    coherence_band: str
    score_numeric: float
    features: dict[str, Any]
    routing: dict[str, Any]
    audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "layer_version": self.layer_version,
            "timestamp": self.timestamp,
            "input_ref": self.input_ref,
            "status": self.status.value,
            "continuation_allowed": self.continuation_allowed,
            "blocker_codes": self.blocker_codes,
            "warning_codes": self.warning_codes,
            "fallback_class": self.fallback_class,
            "freshness_state": self.freshness_state,
            "warmup_state": self.warmup_state,
            "coherence_band": self.coherence_band,
            "score_numeric": self.score_numeric,
            "features": self.features,
            "routing": self.routing,
            "audit": self.audit,
        }


class L10RouterEvaluator:
    VERSION = "1.0.0"
    HIGH_THRESHOLD = 0.85
    MID_THRESHOLD = 0.70

    def _score_band(self, sizing_score: float) -> L10CoherenceBand:
        if sizing_score >= self.HIGH_THRESHOLD:
            return L10CoherenceBand.HIGH
        if sizing_score >= self.MID_THRESHOLD:
            return L10CoherenceBand.MID
        return L10CoherenceBand.LOW

    def evaluate(self, payload: L10Input) -> L10EvaluationResult:
        blockers: list[str] = []
        warnings: list[str] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        if not payload.input_ref or not payload.timestamp:
            blockers.append(L10BlockerCode.CONTRACT_PAYLOAD_MALFORMED.value)

        if not payload.upstream_l6_continuation_allowed:
            blockers.append(L10BlockerCode.UPSTREAM_L6_NOT_CONTINUABLE.value)

        missing_required = sorted(set(payload.required_sizing_sources) - set(payload.available_sizing_sources))
        if missing_required:
            blockers.append(L10BlockerCode.REQUIRED_SIZING_SOURCE_MISSING.value)
            notes.append(f"Missing required sizing sources: {', '.join(missing_required)}")

        if payload.freshness_state == L10FreshnessState.NO_PRODUCER:
            blockers.append(L10BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL.value)
        elif payload.freshness_state == L10FreshnessState.STALE_PRESERVED:
            warnings.append("STALE_PRESERVED_CONTEXT")
        elif payload.freshness_state == L10FreshnessState.DEGRADED:
            warnings.append("DEGRADED_CONTEXT")

        if payload.warmup_state == L10WarmupState.INSUFFICIENT:
            blockers.append(L10BlockerCode.WARMUP_INSUFFICIENT.value)
        elif payload.warmup_state == L10WarmupState.PARTIAL:
            warnings.append("PARTIAL_WARMUP")

        if payload.fallback_class == L10FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(L10BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED.value)
        elif payload.fallback_class == L10FallbackClass.LEGAL_EMERGENCY_PRESERVE:
            warnings.append("LEGAL_EMERGENCY_PRESERVE_USED")
        elif payload.fallback_class == L10FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
            rule_hits.append("LEGAL_PRIMARY_SUBSTITUTE")

        if not payload.entry_available:
            blockers.append(L10BlockerCode.ENTRY_UNAVAILABLE.value)
        if not payload.stop_loss_available:
            blockers.append(L10BlockerCode.STOP_LOSS_UNAVAILABLE.value)
        if not payload.risk_input_available:
            blockers.append(L10BlockerCode.RISK_INPUT_UNAVAILABLE.value)

        if not payload.geometry_valid:
            blockers.append(L10BlockerCode.GEOMETRY_INVALID.value)
        elif payload.geometry_non_ideal:
            warnings.append("GEOMETRY_NON_IDEAL")

        if not payload.position_sizing_available:
            blockers.append(L10BlockerCode.POSITION_SIZING_UNAVAILABLE.value)
        elif payload.sizing_partial:
            warnings.append("POSITION_SIZING_PARTIAL")

        compliance_state = str(payload.compliance_state).upper().strip()
        if compliance_state == "INVALID":
            blockers.append(L10BlockerCode.COMPLIANCE_INVALID.value)
        elif compliance_state == "DEGRADED":
            warnings.append("COMPLIANCE_DEGRADED")

        if payload.account_limit_proximity_elevated:
            warnings.append("ACCOUNT_LIMIT_PROXIMITY_ELEVATED")

        score_band = self._score_band(payload.sizing_score)
        rule_hits.append(f"score_band={score_band.value}")

        status = L10Status.PASS
        continuation_allowed = True
        next_targets = ["PHASE_5"]

        if blockers:
            status = L10Status.FAIL
            continuation_allowed = False
            next_targets = []
        elif score_band == L10CoherenceBand.LOW:
            status = L10Status.FAIL
            continuation_allowed = False
            next_targets = []
            blockers.append(L10BlockerCode.SIZING_SCORE_BELOW_MINIMUM.value)
        else:
            if (
                payload.freshness_state != L10FreshnessState.FRESH
                or payload.warmup_state != L10WarmupState.READY
                or payload.fallback_class == L10FallbackClass.LEGAL_EMERGENCY_PRESERVE
                or score_band == L10CoherenceBand.MID
                or payload.geometry_non_ideal
                or payload.sizing_partial
                or compliance_state == "DEGRADED"
                or payload.account_limit_proximity_elevated
            ):
                status = L10Status.WARN

        features = {
            "feature_vector": {
                "sizing_score": round(payload.sizing_score, 4),
                "entry_available": payload.entry_available,
                "stop_loss_available": payload.stop_loss_available,
                "risk_input_available": payload.risk_input_available,
                "geometry_valid": payload.geometry_valid,
                "position_sizing_available": payload.position_sizing_available,
                "compliance_state": compliance_state,
                "geometry_non_ideal": payload.geometry_non_ideal,
                "sizing_partial": payload.sizing_partial,
                "account_limit_proximity_elevated": payload.account_limit_proximity_elevated,
            },
            "feature_hash": f"L10_{score_band.value}_{status.value}_{int(round(payload.sizing_score * 100))}",
        }

        routing = {
            "source_used": list(payload.sizing_sources_used),
            "fallback_used": payload.fallback_class != L10FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
        }

        return L10EvaluationResult(
            layer="L10",
            layer_version=self.VERSION,
            timestamp=payload.timestamp,
            input_ref=payload.input_ref,
            status=status,
            continuation_allowed=continuation_allowed,
            blocker_codes=list(dict.fromkeys(blockers)),
            warning_codes=list(dict.fromkeys(warnings)),
            fallback_class=payload.fallback_class.value,
            freshness_state=payload.freshness_state.value,
            warmup_state=payload.warmup_state.value,
            coherence_band=score_band.value,
            score_numeric=round(payload.sizing_score, 4),
            features=features,
            routing=routing,
            audit=audit,
        )


def build_l10_input_from_dict(payload: dict[str, Any]) -> L10Input:
    return L10Input(
        input_ref=str(payload.get("input_ref", "")).strip(),
        timestamp=str(payload.get("timestamp", "")).strip(),
        upstream_l6_continuation_allowed=bool(payload.get("upstream_l6_continuation_allowed", True)),
        sizing_sources_used=[str(x) for x in payload.get("sizing_sources_used", [])],
        required_sizing_sources=[str(x) for x in payload.get("required_sizing_sources", [])],
        available_sizing_sources=[str(x) for x in payload.get("available_sizing_sources", payload.get("sizing_sources_used", []))],
        sizing_score=float(payload.get("sizing_score", 0.0)),
        entry_available=bool(payload.get("entry_available", True)),
        stop_loss_available=bool(payload.get("stop_loss_available", True)),
        risk_input_available=bool(payload.get("risk_input_available", True)),
        geometry_valid=bool(payload.get("geometry_valid", True)),
        position_sizing_available=bool(payload.get("position_sizing_available", True)),
        compliance_state=str(payload.get("compliance_state", "VALID")),
        geometry_non_ideal=bool(payload.get("geometry_non_ideal", False)),
        sizing_partial=bool(payload.get("sizing_partial", False)),
        account_limit_proximity_elevated=bool(payload.get("account_limit_proximity_elevated", False)),
        fallback_class=L10FallbackClass(str(payload.get("fallback_class", "NO_FALLBACK"))),
        freshness_state=L10FreshnessState(str(payload.get("freshness_state", "FRESH"))),
        warmup_state=L10WarmupState(str(payload.get("warmup_state", "READY"))),
    )


if __name__ == "__main__":
    evaluator = L10RouterEvaluator()
    examples = [
        {
            "input_ref": "EURUSD_H1_run_920",
            "timestamp": "2026-03-28T18:00:00+07:00",
            "upstream_l6_continuation_allowed": True,
            "sizing_sources_used": ["sizing_engine", "risk_geometry"],
            "required_sizing_sources": ["sizing_engine"],
            "available_sizing_sources": ["sizing_engine", "risk_geometry"],
            "sizing_score": 0.89,
            "entry_available": True,
            "stop_loss_available": True,
            "risk_input_available": True,
            "geometry_valid": True,
            "position_sizing_available": True,
            "compliance_state": "VALID",
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        },
        {
            "input_ref": "EURUSD_H1_run_921",
            "timestamp": "2026-03-28T18:05:00+07:00",
            "upstream_l6_continuation_allowed": True,
            "sizing_sources_used": ["sizing_engine", "preserved_geometry"],
            "required_sizing_sources": ["sizing_engine"],
            "available_sizing_sources": ["sizing_engine", "preserved_geometry"],
            "sizing_score": 0.76,
            "entry_available": True,
            "stop_loss_available": True,
            "risk_input_available": True,
            "geometry_valid": True,
            "position_sizing_available": True,
            "compliance_state": "DEGRADED",
            "geometry_non_ideal": True,
            "sizing_partial": True,
            "account_limit_proximity_elevated": True,
            "fallback_class": "LEGAL_EMERGENCY_PRESERVE",
            "freshness_state": "STALE_PRESERVED",
            "warmup_state": "PARTIAL",
        },
        {
            "input_ref": "EURUSD_H1_run_922",
            "timestamp": "2026-03-28T18:10:00+07:00",
            "upstream_l6_continuation_allowed": False,
            "sizing_sources_used": ["sizing_engine"],
            "required_sizing_sources": ["sizing_engine"],
            "available_sizing_sources": ["sizing_engine"],
            "sizing_score": 0.50,
            "entry_available": False,
            "stop_loss_available": False,
            "risk_input_available": False,
            "geometry_valid": False,
            "position_sizing_available": False,
            "compliance_state": "INVALID",
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        },
    ]
    for ex in examples:
        print(evaluator.evaluate(build_l10_input_from_dict(ex)).to_dict())
