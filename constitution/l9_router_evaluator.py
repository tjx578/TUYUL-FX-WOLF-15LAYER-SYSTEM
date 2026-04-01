from __future__ import annotations

"""
L9 Router Evaluator — strict constitutional prototype

Analysis-only module for structure / entry-timing legality.
This module does NOT emit direction, execute, trade_valid, sizing,
or final verdict.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class L9Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L9FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class L9WarmupState(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class L9FallbackClass(str, Enum):
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class L9CoherenceBand(str, Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class L9BlockerCode(str, Enum):
    UPSTREAM_L8_NOT_CONTINUABLE = "UPSTREAM_L8_NOT_CONTINUABLE"
    REQUIRED_STRUCTURE_SOURCE_MISSING = "REQUIRED_STRUCTURE_SOURCE_MISSING"
    STRUCTURE_ALIGNMENT_INVALID = "STRUCTURE_ALIGNMENT_INVALID"
    ENTRY_TIMING_UNAVAILABLE = "ENTRY_TIMING_UNAVAILABLE"
    LIQUIDITY_STATE_INVALID = "LIQUIDITY_STATE_INVALID"
    STRUCTURE_SCORE_BELOW_MINIMUM = "STRUCTURE_SCORE_BELOW_MINIMUM"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


@dataclass(frozen=True)
class L9Input:
    input_ref: str
    timestamp: str
    upstream_l8_continuation_allowed: bool = True

    structure_sources_used: list[str] = field(default_factory=list)
    required_structure_sources: list[str] = field(default_factory=list)
    available_structure_sources: list[str] = field(default_factory=list)

    structure_score: float = 0.0
    structure_alignment_valid: bool = True
    entry_timing_available: bool = True
    liquidity_state: str = "VALID"   # VALID | DEGRADED | INVALID
    entry_timing_degraded: bool = False
    liquidity_partial: bool = False
    structure_non_ideal: bool = False

    fallback_class: L9FallbackClass = L9FallbackClass.NO_FALLBACK
    freshness_state: L9FreshnessState = L9FreshnessState.FRESH
    warmup_state: L9WarmupState = L9WarmupState.READY


@dataclass(frozen=True)
class L9EvaluationResult:
    layer: str
    layer_version: str
    timestamp: str
    input_ref: str
    status: L9Status
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


class L9RouterEvaluator:
    VERSION = "1.0.0"
    HIGH_THRESHOLD = 0.80
    MID_THRESHOLD = 0.65

    def _score_band(self, structure_score: float) -> L9CoherenceBand:
        if structure_score >= self.HIGH_THRESHOLD:
            return L9CoherenceBand.HIGH
        if structure_score >= self.MID_THRESHOLD:
            return L9CoherenceBand.MID
        return L9CoherenceBand.LOW

    def evaluate(self, payload: L9Input) -> L9EvaluationResult:
        blockers: list[str] = []
        warnings: list[str] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        if not payload.input_ref or not payload.timestamp:
            blockers.append(L9BlockerCode.CONTRACT_PAYLOAD_MALFORMED.value)

        if not payload.upstream_l8_continuation_allowed:
            blockers.append(L9BlockerCode.UPSTREAM_L8_NOT_CONTINUABLE.value)

        missing_required = sorted(set(payload.required_structure_sources) - set(payload.available_structure_sources))
        if missing_required:
            blockers.append(L9BlockerCode.REQUIRED_STRUCTURE_SOURCE_MISSING.value)
            notes.append(f"Missing required structure sources: {', '.join(missing_required)}")

        if payload.freshness_state == L9FreshnessState.NO_PRODUCER:
            blockers.append(L9BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL.value)
        elif payload.freshness_state == L9FreshnessState.STALE_PRESERVED:
            warnings.append("STALE_PRESERVED_CONTEXT")
        elif payload.freshness_state == L9FreshnessState.DEGRADED:
            warnings.append("DEGRADED_CONTEXT")

        if payload.warmup_state == L9WarmupState.INSUFFICIENT:
            blockers.append(L9BlockerCode.WARMUP_INSUFFICIENT.value)
        elif payload.warmup_state == L9WarmupState.PARTIAL:
            warnings.append("PARTIAL_WARMUP")

        if payload.fallback_class == L9FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(L9BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED.value)
        elif payload.fallback_class == L9FallbackClass.LEGAL_EMERGENCY_PRESERVE:
            warnings.append("LEGAL_EMERGENCY_PRESERVE_USED")
        elif payload.fallback_class == L9FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
            rule_hits.append("LEGAL_PRIMARY_SUBSTITUTE")

        if not payload.structure_alignment_valid:
            blockers.append(L9BlockerCode.STRUCTURE_ALIGNMENT_INVALID.value)
        if not payload.entry_timing_available:
            blockers.append(L9BlockerCode.ENTRY_TIMING_UNAVAILABLE.value)

        liquidity_state = str(payload.liquidity_state).upper().strip()
        if liquidity_state == "INVALID":
            blockers.append(L9BlockerCode.LIQUIDITY_STATE_INVALID.value)
        elif liquidity_state == "DEGRADED":
            warnings.append("LIQUIDITY_STATE_DEGRADED")

        if payload.entry_timing_degraded:
            warnings.append("ENTRY_TIMING_DEGRADED")
        if payload.liquidity_partial:
            warnings.append("LIQUIDITY_PARTIAL")
        if payload.structure_non_ideal:
            warnings.append("STRUCTURE_NON_IDEAL")

        score_band = self._score_band(payload.structure_score)
        rule_hits.append(f"score_band={score_band.value}")

        status = L9Status.PASS
        continuation_allowed = True
        next_targets = ["PHASE_4"]

        if blockers:
            status = L9Status.FAIL
            continuation_allowed = False
            next_targets = []
        elif score_band == L9CoherenceBand.LOW:
            status = L9Status.FAIL
            continuation_allowed = False
            next_targets = []
            blockers.append(L9BlockerCode.STRUCTURE_SCORE_BELOW_MINIMUM.value)
        else:
            if (
                payload.freshness_state != L9FreshnessState.FRESH
                or payload.warmup_state != L9WarmupState.READY
                or payload.fallback_class == L9FallbackClass.LEGAL_EMERGENCY_PRESERVE
                or score_band == L9CoherenceBand.MID
                or liquidity_state == "DEGRADED"
                or payload.entry_timing_degraded
                or payload.liquidity_partial
                or payload.structure_non_ideal
            ):
                status = L9Status.WARN

        features = {
            "feature_vector": {
                "structure_score": round(payload.structure_score, 4),
                "structure_alignment_valid": payload.structure_alignment_valid,
                "entry_timing_available": payload.entry_timing_available,
                "liquidity_state": liquidity_state,
                "entry_timing_degraded": payload.entry_timing_degraded,
                "liquidity_partial": payload.liquidity_partial,
                "structure_non_ideal": payload.structure_non_ideal,
            },
            "feature_hash": f"L9_{score_band.value}_{status.value}_{int(round(payload.structure_score * 100))}",
        }

        routing = {
            "source_used": list(payload.structure_sources_used),
            "fallback_used": payload.fallback_class != L9FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
        }

        return L9EvaluationResult(
            layer="L9",
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
            score_numeric=round(payload.structure_score, 4),
            features=features,
            routing=routing,
            audit=audit,
        )


def build_l9_input_from_dict(payload: dict[str, Any]) -> L9Input:
    return L9Input(
        input_ref=str(payload.get("input_ref", "")).strip(),
        timestamp=str(payload.get("timestamp", "")).strip(),
        upstream_l8_continuation_allowed=bool(payload.get("upstream_l8_continuation_allowed", True)),
        structure_sources_used=[str(x) for x in payload.get("structure_sources_used", [])],
        required_structure_sources=[str(x) for x in payload.get("required_structure_sources", [])],
        available_structure_sources=[str(x) for x in payload.get("available_structure_sources", payload.get("structure_sources_used", []))],
        structure_score=float(payload.get("structure_score", 0.0)),
        structure_alignment_valid=bool(payload.get("structure_alignment_valid", True)),
        entry_timing_available=bool(payload.get("entry_timing_available", True)),
        liquidity_state=str(payload.get("liquidity_state", "VALID")),
        entry_timing_degraded=bool(payload.get("entry_timing_degraded", False)),
        liquidity_partial=bool(payload.get("liquidity_partial", False)),
        structure_non_ideal=bool(payload.get("structure_non_ideal", False)),
        fallback_class=L9FallbackClass(str(payload.get("fallback_class", "NO_FALLBACK"))),
        freshness_state=L9FreshnessState(str(payload.get("freshness_state", "FRESH"))),
        warmup_state=L9WarmupState(str(payload.get("warmup_state", "READY"))),
    )


if __name__ == "__main__":
    evaluator = L9RouterEvaluator()
    examples = [
        {
            "input_ref": "EURUSD_H1_run_500",
            "timestamp": "2026-03-28T15:00:00+07:00",
            "upstream_l8_continuation_allowed": True,
            "structure_sources_used": ["smc_engine", "timing_engine"],
            "required_structure_sources": ["smc_engine"],
            "available_structure_sources": ["smc_engine", "timing_engine"],
            "structure_score": 0.84,
            "structure_alignment_valid": True,
            "entry_timing_available": True,
            "liquidity_state": "VALID",
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        },
        {
            "input_ref": "EURUSD_H1_run_501",
            "timestamp": "2026-03-28T15:05:00+07:00",
            "upstream_l8_continuation_allowed": True,
            "structure_sources_used": ["smc_engine", "preserved_timing"],
            "required_structure_sources": ["smc_engine"],
            "available_structure_sources": ["smc_engine", "preserved_timing"],
            "structure_score": 0.70,
            "structure_alignment_valid": True,
            "entry_timing_available": True,
            "liquidity_state": "DEGRADED",
            "entry_timing_degraded": True,
            "liquidity_partial": True,
            "structure_non_ideal": True,
            "fallback_class": "LEGAL_EMERGENCY_PRESERVE",
            "freshness_state": "STALE_PRESERVED",
            "warmup_state": "PARTIAL",
        },
        {
            "input_ref": "EURUSD_H1_run_502",
            "timestamp": "2026-03-28T15:10:00+07:00",
            "upstream_l8_continuation_allowed": False,
            "structure_sources_used": ["smc_engine"],
            "required_structure_sources": ["smc_engine"],
            "available_structure_sources": ["smc_engine"],
            "structure_score": 0.50,
            "structure_alignment_valid": False,
            "entry_timing_available": False,
            "liquidity_state": "INVALID",
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        },
    ]
    for ex in examples:
        print(evaluator.evaluate(build_l9_input_from_dict(ex)).to_dict())
