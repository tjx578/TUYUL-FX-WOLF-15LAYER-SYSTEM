from __future__ import annotations

"""
L7 Router Evaluator — strict constitutional prototype

Analysis-only module for probability / survivability legality.
This module does NOT emit direction, execute, trade_valid, sizing,
or final verdict.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class L7Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L7FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class L7WarmupState(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class L7FallbackClass(str, Enum):
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class L7CoherenceBand(str, Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class L7BlockerCode(str, Enum):
    UPSTREAM_NOT_CONTINUABLE = "UPSTREAM_NOT_CONTINUABLE"
    REQUIRED_PROBABILITY_SOURCE_MISSING = "REQUIRED_PROBABILITY_SOURCE_MISSING"
    EDGE_VALIDATION_UNAVAILABLE = "EDGE_VALIDATION_UNAVAILABLE"
    EDGE_STATUS_INVALID = "EDGE_STATUS_INVALID"
    WIN_PROBABILITY_BELOW_MINIMUM = "WIN_PROBABILITY_BELOW_MINIMUM"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


@dataclass(frozen=True)
class L7Input:
    input_ref: str
    timestamp: str
    upstream_continuation_allowed: bool = True

    probability_sources_used: list[str] = field(default_factory=list)
    required_probability_sources: list[str] = field(default_factory=list)
    available_probability_sources: list[str] = field(default_factory=list)

    win_probability: float = 0.0
    profit_factor: float = 0.0
    sample_count: int = 0
    edge_validation_available: bool = True
    edge_status: str = "VALID"  # VALID | DEGRADED | INVALID
    validation_partial: bool = False

    fallback_class: L7FallbackClass = L7FallbackClass.NO_FALLBACK
    freshness_state: L7FreshnessState = L7FreshnessState.FRESH
    warmup_state: L7WarmupState = L7WarmupState.READY


@dataclass(frozen=True)
class L7EvaluationResult:
    layer: str
    layer_version: str
    timestamp: str
    input_ref: str
    status: L7Status
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


class L7RouterEvaluator:
    VERSION = "1.0.0"
    HIGH_THRESHOLD = 0.67
    MID_THRESHOLD = 0.55
    MIN_SAMPLE_WARN = 30

    def _score_band(self, win_probability: float) -> L7CoherenceBand:
        if win_probability >= self.HIGH_THRESHOLD:
            return L7CoherenceBand.HIGH
        if win_probability >= self.MID_THRESHOLD:
            return L7CoherenceBand.MID
        return L7CoherenceBand.LOW

    def evaluate(self, payload: L7Input) -> L7EvaluationResult:
        blockers: list[str] = []
        warnings: list[str] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        if not payload.input_ref or not payload.timestamp:
            blockers.append(L7BlockerCode.CONTRACT_PAYLOAD_MALFORMED.value)

        if not payload.upstream_continuation_allowed:
            blockers.append(L7BlockerCode.UPSTREAM_NOT_CONTINUABLE.value)

        missing_required = sorted(set(payload.required_probability_sources) - set(payload.available_probability_sources))
        if missing_required:
            blockers.append(L7BlockerCode.REQUIRED_PROBABILITY_SOURCE_MISSING.value)
            notes.append(f"Missing required probability sources: {', '.join(missing_required)}")

        if payload.freshness_state == L7FreshnessState.NO_PRODUCER:
            blockers.append(L7BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL.value)
        elif payload.freshness_state == L7FreshnessState.STALE_PRESERVED:
            warnings.append("STALE_PRESERVED_CONTEXT")
        elif payload.freshness_state == L7FreshnessState.DEGRADED:
            warnings.append("DEGRADED_CONTEXT")

        if payload.warmup_state == L7WarmupState.INSUFFICIENT:
            blockers.append(L7BlockerCode.WARMUP_INSUFFICIENT.value)
        elif payload.warmup_state == L7WarmupState.PARTIAL:
            warnings.append("PARTIAL_WARMUP")

        if payload.fallback_class == L7FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(L7BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED.value)
        elif payload.fallback_class == L7FallbackClass.LEGAL_EMERGENCY_PRESERVE:
            warnings.append("LEGAL_EMERGENCY_PRESERVE_USED")
        elif payload.fallback_class == L7FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
            rule_hits.append("LEGAL_PRIMARY_SUBSTITUTE")

        if not payload.edge_validation_available:
            blockers.append(L7BlockerCode.EDGE_VALIDATION_UNAVAILABLE.value)

        edge_status = str(payload.edge_status).upper().strip()
        if edge_status == "INVALID":
            blockers.append(L7BlockerCode.EDGE_STATUS_INVALID.value)
        elif edge_status == "DEGRADED":
            warnings.append("EDGE_STATUS_DEGRADED")

        if payload.validation_partial:
            warnings.append("VALIDATION_PARTIAL")

        if payload.sample_count and payload.sample_count < self.MIN_SAMPLE_WARN:
            warnings.append("LOW_SAMPLE_COUNT")

        score_band = self._score_band(payload.win_probability)
        rule_hits.append(f"score_band={score_band.value}")

        status = L7Status.PASS
        continuation_allowed = True
        next_targets = ["L8"]

        if blockers:
            status = L7Status.FAIL
            continuation_allowed = False
            next_targets = []
        elif score_band == L7CoherenceBand.LOW:
            status = L7Status.FAIL
            continuation_allowed = False
            next_targets = []
            blockers.append(L7BlockerCode.WIN_PROBABILITY_BELOW_MINIMUM.value)
        else:
            if (
                payload.freshness_state != L7FreshnessState.FRESH
                or payload.warmup_state != L7WarmupState.READY
                or payload.fallback_class == L7FallbackClass.LEGAL_EMERGENCY_PRESERVE
                or score_band == L7CoherenceBand.MID
                or edge_status == "DEGRADED"
                or payload.validation_partial
                or (payload.sample_count and payload.sample_count < self.MIN_SAMPLE_WARN)
            ):
                status = L7Status.WARN

        features = {
            "feature_vector": {
                "win_probability": round(payload.win_probability, 4),
                "profit_factor": round(payload.profit_factor, 4),
                "sample_count": payload.sample_count,
                "edge_validation_available": payload.edge_validation_available,
                "edge_status": edge_status,
                "validation_partial": payload.validation_partial,
            },
            "feature_hash": f"L7_{score_band.value}_{status.value}_{int(round(payload.win_probability * 100))}",
        }

        routing = {
            "source_used": list(payload.probability_sources_used),
            "fallback_used": payload.fallback_class != L7FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
        }

        return L7EvaluationResult(
            layer="L7",
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
            score_numeric=round(payload.win_probability, 4),
            features=features,
            routing=routing,
            audit=audit,
        )


def build_l7_input_from_dict(payload: dict[str, Any]) -> L7Input:
    return L7Input(
        input_ref=str(payload.get("input_ref", "")).strip(),
        timestamp=str(payload.get("timestamp", "")).strip(),
        upstream_continuation_allowed=bool(payload.get("upstream_continuation_allowed", True)),
        probability_sources_used=[str(x) for x in payload.get("probability_sources_used", [])],
        required_probability_sources=[str(x) for x in payload.get("required_probability_sources", [])],
        available_probability_sources=[str(x) for x in payload.get("available_probability_sources", payload.get("probability_sources_used", []))],
        win_probability=float(payload.get("win_probability", 0.0)),
        profit_factor=float(payload.get("profit_factor", 0.0)),
        sample_count=int(payload.get("sample_count", 0)),
        edge_validation_available=bool(payload.get("edge_validation_available", True)),
        edge_status=str(payload.get("edge_status", "VALID")),
        validation_partial=bool(payload.get("validation_partial", False)),
        fallback_class=L7FallbackClass(str(payload.get("fallback_class", "NO_FALLBACK"))),
        freshness_state=L7FreshnessState(str(payload.get("freshness_state", "FRESH"))),
        warmup_state=L7WarmupState(str(payload.get("warmup_state", "READY"))),
    )


if __name__ == "__main__":
    evaluator = L7RouterEvaluator()
    examples = [
        {
            "input_ref": "EURUSD_H1_run_300",
            "timestamp": "2026-03-28T14:00:00+07:00",
            "upstream_continuation_allowed": True,
            "probability_sources_used": ["monte_carlo", "edge_validator"],
            "required_probability_sources": ["monte_carlo"],
            "available_probability_sources": ["monte_carlo", "edge_validator"],
            "win_probability": 0.71,
            "profit_factor": 1.8,
            "sample_count": 80,
            "edge_validation_available": True,
            "edge_status": "VALID",
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        },
        {
            "input_ref": "EURUSD_H1_run_301",
            "timestamp": "2026-03-28T14:05:00+07:00",
            "upstream_continuation_allowed": True,
            "probability_sources_used": ["monte_carlo", "preserved_edge"],
            "required_probability_sources": ["monte_carlo"],
            "available_probability_sources": ["monte_carlo", "preserved_edge"],
            "win_probability": 0.60,
            "profit_factor": 1.3,
            "sample_count": 20,
            "edge_validation_available": True,
            "edge_status": "DEGRADED",
            "validation_partial": True,
            "fallback_class": "LEGAL_EMERGENCY_PRESERVE",
            "freshness_state": "STALE_PRESERVED",
            "warmup_state": "PARTIAL",
        },
        {
            "input_ref": "EURUSD_H1_run_302",
            "timestamp": "2026-03-28T14:10:00+07:00",
            "upstream_continuation_allowed": False,
            "probability_sources_used": ["monte_carlo"],
            "required_probability_sources": ["monte_carlo"],
            "available_probability_sources": ["monte_carlo"],
            "win_probability": 0.40,
            "profit_factor": 0.9,
            "sample_count": 10,
            "edge_validation_available": False,
            "edge_status": "INVALID",
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        },
    ]
    for ex in examples:
        print(evaluator.evaluate(build_l7_input_from_dict(ex)).to_dict())
