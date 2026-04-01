from __future__ import annotations

"""
L11 Router Evaluator — strict constitutional prototype

Analysis-only module for risk-reward / battle-strategy legality.
This module does NOT emit execute, trade_valid, sizing, or final verdict.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class L11Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L11FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class L11WarmupState(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class L11FallbackClass(str, Enum):
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class L11CoherenceBand(str, Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class L11BlockerCode(str, Enum):
    UPSTREAM_NOT_CONTINUABLE = "UPSTREAM_NOT_CONTINUABLE"
    REQUIRED_RR_SOURCE_MISSING = "REQUIRED_RR_SOURCE_MISSING"
    ENTRY_UNAVAILABLE = "ENTRY_UNAVAILABLE"
    STOP_LOSS_UNAVAILABLE = "STOP_LOSS_UNAVAILABLE"
    TAKE_PROFIT_UNAVAILABLE = "TAKE_PROFIT_UNAVAILABLE"
    RR_INVALID = "RR_INVALID"
    BATTLE_PLAN_UNAVAILABLE = "BATTLE_PLAN_UNAVAILABLE"
    ATR_CONTEXT_UNAVAILABLE = "ATR_CONTEXT_UNAVAILABLE"
    RR_SCORE_BELOW_MINIMUM = "RR_SCORE_BELOW_MINIMUM"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


@dataclass(frozen=True)
class L11Input:
    input_ref: str
    timestamp: str
    upstream_continuation_allowed: bool = True

    rr_sources_used: list[str] = field(default_factory=list)
    required_rr_sources: list[str] = field(default_factory=list)
    available_rr_sources: list[str] = field(default_factory=list)

    entry_available: bool = True
    stop_loss_available: bool = True
    take_profit_available: bool = True

    rr_score: float = 0.0
    rr_ratio: float = 0.0
    rr_valid: bool = True
    battle_plan_available: bool = True
    battle_plan_degraded: bool = False
    atr_context_available: bool = True
    atr_context_partial: bool = False
    target_geometry_non_ideal: bool = False
    multi_target_incomplete: bool = False

    fallback_class: L11FallbackClass = L11FallbackClass.NO_FALLBACK
    freshness_state: L11FreshnessState = L11FreshnessState.FRESH
    warmup_state: L11WarmupState = L11WarmupState.READY


@dataclass(frozen=True)
class L11EvaluationResult:
    layer: str
    layer_version: str
    timestamp: str
    input_ref: str
    status: L11Status
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


class L11RouterEvaluator:
    VERSION = "1.0.0"
    HIGH_THRESHOLD = 0.80
    MID_THRESHOLD = 0.65

    def _score_band(self, rr_score: float) -> L11CoherenceBand:
        if rr_score >= self.HIGH_THRESHOLD:
            return L11CoherenceBand.HIGH
        if rr_score >= self.MID_THRESHOLD:
            return L11CoherenceBand.MID
        return L11CoherenceBand.LOW

    def evaluate(self, payload: L11Input) -> L11EvaluationResult:
        blockers: list[str] = []
        warnings: list[str] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        if not payload.input_ref or not payload.timestamp:
            blockers.append(L11BlockerCode.CONTRACT_PAYLOAD_MALFORMED.value)

        if not payload.upstream_continuation_allowed:
            blockers.append(L11BlockerCode.UPSTREAM_NOT_CONTINUABLE.value)

        missing_required = sorted(set(payload.required_rr_sources) - set(payload.available_rr_sources))
        if missing_required:
            blockers.append(L11BlockerCode.REQUIRED_RR_SOURCE_MISSING.value)
            notes.append(f"Missing required RR sources: {', '.join(missing_required)}")

        if payload.freshness_state == L11FreshnessState.NO_PRODUCER:
            blockers.append(L11BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL.value)
        elif payload.freshness_state == L11FreshnessState.STALE_PRESERVED:
            warnings.append("STALE_PRESERVED_CONTEXT")
        elif payload.freshness_state == L11FreshnessState.DEGRADED:
            warnings.append("DEGRADED_CONTEXT")

        if payload.warmup_state == L11WarmupState.INSUFFICIENT:
            blockers.append(L11BlockerCode.WARMUP_INSUFFICIENT.value)
        elif payload.warmup_state == L11WarmupState.PARTIAL:
            warnings.append("PARTIAL_WARMUP")

        if payload.fallback_class == L11FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(L11BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED.value)
        elif payload.fallback_class == L11FallbackClass.LEGAL_EMERGENCY_PRESERVE:
            warnings.append("LEGAL_EMERGENCY_PRESERVE_USED")
        elif payload.fallback_class == L11FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
            rule_hits.append("LEGAL_PRIMARY_SUBSTITUTE")

        if not payload.entry_available:
            blockers.append(L11BlockerCode.ENTRY_UNAVAILABLE.value)
        if not payload.stop_loss_available:
            blockers.append(L11BlockerCode.STOP_LOSS_UNAVAILABLE.value)
        if not payload.take_profit_available:
            blockers.append(L11BlockerCode.TAKE_PROFIT_UNAVAILABLE.value)

        if not payload.rr_valid or payload.rr_ratio <= 0:
            blockers.append(L11BlockerCode.RR_INVALID.value)

        if not payload.battle_plan_available:
            blockers.append(L11BlockerCode.BATTLE_PLAN_UNAVAILABLE.value)
        elif payload.battle_plan_degraded:
            warnings.append("BATTLE_PLAN_DEGRADED")

        if not payload.atr_context_available:
            blockers.append(L11BlockerCode.ATR_CONTEXT_UNAVAILABLE.value)
        elif payload.atr_context_partial:
            warnings.append("ATR_CONTEXT_PARTIAL")

        if payload.target_geometry_non_ideal:
            warnings.append("TARGET_GEOMETRY_NON_IDEAL")
        if payload.multi_target_incomplete:
            warnings.append("MULTI_TARGET_INCOMPLETE")

        score_band = self._score_band(payload.rr_score)
        rule_hits.append(f"score_band={score_band.value}")

        status = L11Status.PASS
        continuation_allowed = True
        next_targets = ["L6"]

        if blockers:
            status = L11Status.FAIL
            continuation_allowed = False
            next_targets = []
        elif score_band == L11CoherenceBand.LOW:
            status = L11Status.FAIL
            continuation_allowed = False
            next_targets = []
            blockers.append(L11BlockerCode.RR_SCORE_BELOW_MINIMUM.value)
        else:
            if (
                payload.freshness_state != L11FreshnessState.FRESH
                or payload.warmup_state != L11WarmupState.READY
                or payload.fallback_class == L11FallbackClass.LEGAL_EMERGENCY_PRESERVE
                or score_band == L11CoherenceBand.MID
                or payload.battle_plan_degraded
                or payload.atr_context_partial
                or payload.target_geometry_non_ideal
                or payload.multi_target_incomplete
            ):
                status = L11Status.WARN

        features = {
            "feature_vector": {
                "rr_score": round(payload.rr_score, 4),
                "rr_ratio": round(payload.rr_ratio, 4),
                "entry_available": payload.entry_available,
                "stop_loss_available": payload.stop_loss_available,
                "take_profit_available": payload.take_profit_available,
                "rr_valid": payload.rr_valid,
                "battle_plan_available": payload.battle_plan_available,
                "battle_plan_degraded": payload.battle_plan_degraded,
                "atr_context_available": payload.atr_context_available,
                "atr_context_partial": payload.atr_context_partial,
                "target_geometry_non_ideal": payload.target_geometry_non_ideal,
                "multi_target_incomplete": payload.multi_target_incomplete,
            },
            "feature_hash": f"L11_{score_band.value}_{status.value}_{int(round(payload.rr_score * 100))}",
        }

        routing = {
            "source_used": list(payload.rr_sources_used),
            "fallback_used": payload.fallback_class != L11FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
        }

        return L11EvaluationResult(
            layer="L11",
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
            score_numeric=round(payload.rr_score, 4),
            features=features,
            routing=routing,
            audit=audit,
        )


def build_l11_input_from_dict(payload: dict[str, Any]) -> L11Input:
    return L11Input(
        input_ref=str(payload.get("input_ref", "")).strip(),
        timestamp=str(payload.get("timestamp", "")).strip(),
        upstream_continuation_allowed=bool(payload.get("upstream_continuation_allowed", True)),
        rr_sources_used=[str(x) for x in payload.get("rr_sources_used", [])],
        required_rr_sources=[str(x) for x in payload.get("required_rr_sources", [])],
        available_rr_sources=[str(x) for x in payload.get("available_rr_sources", payload.get("rr_sources_used", []))],
        entry_available=bool(payload.get("entry_available", True)),
        stop_loss_available=bool(payload.get("stop_loss_available", True)),
        take_profit_available=bool(payload.get("take_profit_available", True)),
        rr_score=float(payload.get("rr_score", 0.0)),
        rr_ratio=float(payload.get("rr_ratio", 0.0)),
        rr_valid=bool(payload.get("rr_valid", True)),
        battle_plan_available=bool(payload.get("battle_plan_available", True)),
        battle_plan_degraded=bool(payload.get("battle_plan_degraded", False)),
        atr_context_available=bool(payload.get("atr_context_available", True)),
        atr_context_partial=bool(payload.get("atr_context_partial", False)),
        target_geometry_non_ideal=bool(payload.get("target_geometry_non_ideal", False)),
        multi_target_incomplete=bool(payload.get("multi_target_incomplete", False)),
        fallback_class=L11FallbackClass(str(payload.get("fallback_class", "NO_FALLBACK"))),
        freshness_state=L11FreshnessState(str(payload.get("freshness_state", "FRESH"))),
        warmup_state=L11WarmupState(str(payload.get("warmup_state", "READY"))),
    )


if __name__ == "__main__":
    evaluator = L11RouterEvaluator()
    examples = [
        {
            "input_ref": "EURUSD_H1_run_900",
            "timestamp": "2026-03-28T17:00:00+07:00",
            "upstream_continuation_allowed": True,
            "rr_sources_used": ["rr_engine", "atr_context"],
            "required_rr_sources": ["rr_engine"],
            "available_rr_sources": ["rr_engine", "atr_context"],
            "entry_available": True,
            "stop_loss_available": True,
            "take_profit_available": True,
            "rr_score": 0.84,
            "rr_ratio": 2.1,
            "rr_valid": True,
            "battle_plan_available": True,
            "atr_context_available": True,
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        },
        {
            "input_ref": "EURUSD_H1_run_901",
            "timestamp": "2026-03-28T17:05:00+07:00",
            "upstream_continuation_allowed": True,
            "rr_sources_used": ["rr_engine", "preserved_atr"],
            "required_rr_sources": ["rr_engine"],
            "available_rr_sources": ["rr_engine", "preserved_atr"],
            "entry_available": True,
            "stop_loss_available": True,
            "take_profit_available": True,
            "rr_score": 0.70,
            "rr_ratio": 1.4,
            "rr_valid": True,
            "battle_plan_available": True,
            "battle_plan_degraded": True,
            "atr_context_available": True,
            "atr_context_partial": True,
            "target_geometry_non_ideal": True,
            "multi_target_incomplete": True,
            "fallback_class": "LEGAL_EMERGENCY_PRESERVE",
            "freshness_state": "STALE_PRESERVED",
            "warmup_state": "PARTIAL",
        },
        {
            "input_ref": "EURUSD_H1_run_902",
            "timestamp": "2026-03-28T17:10:00+07:00",
            "upstream_continuation_allowed": False,
            "rr_sources_used": ["rr_engine"],
            "required_rr_sources": ["rr_engine"],
            "available_rr_sources": ["rr_engine"],
            "entry_available": False,
            "stop_loss_available": False,
            "take_profit_available": False,
            "rr_score": 0.50,
            "rr_ratio": 0.0,
            "rr_valid": False,
            "battle_plan_available": False,
            "atr_context_available": False,
            "freshness_state": "FRESH",
            "warmup_state": "READY",
        },
    ]
    for ex in examples:
        print(evaluator.evaluate(build_l11_input_from_dict(ex)).to_dict())
