"""L8 Router Evaluator — strict constitutional prototype.

Analysis-only module for integrity / TII legality.
This module does NOT emit direction, execute, trade_valid, sizing,
or final verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class L8Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L8FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class L8WarmupState(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class L8FallbackClass(str, Enum):
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class L8CoherenceBand(str, Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class L8BlockerCode(str, Enum):
    UPSTREAM_L7_NOT_CONTINUABLE = "UPSTREAM_L7_NOT_CONTINUABLE"
    REQUIRED_INTEGRITY_SOURCE_MISSING = "REQUIRED_INTEGRITY_SOURCE_MISSING"
    TII_UNAVAILABLE = "TII_UNAVAILABLE"
    TWMS_UNAVAILABLE = "TWMS_UNAVAILABLE"
    INTEGRITY_STATE_INVALID = "INTEGRITY_STATE_INVALID"
    INTEGRITY_SCORE_BELOW_MINIMUM = "INTEGRITY_SCORE_BELOW_MINIMUM"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


@dataclass(frozen=True)
class L8Input:
    input_ref: str
    timestamp: str
    upstream_l7_continuation_allowed: bool = True

    integrity_sources_used: list[str] = field(default_factory=list)
    required_integrity_sources: list[str] = field(default_factory=list)
    available_integrity_sources: list[str] = field(default_factory=list)

    integrity_score: float = 0.0
    tii_available: bool = True
    twms_available: bool = True
    integrity_state: str = "VALID"
    tii_partial: bool = False
    twms_partial: bool = False
    governance_degraded: bool = False
    stability_non_ideal: bool = False

    fallback_class: L8FallbackClass = L8FallbackClass.NO_FALLBACK
    freshness_state: L8FreshnessState = L8FreshnessState.FRESH
    warmup_state: L8WarmupState = L8WarmupState.READY


@dataclass(frozen=True)
class L8EvaluationResult:
    layer: str
    layer_version: str
    timestamp: str
    input_ref: str
    status: L8Status
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


class L8RouterEvaluator:
    VERSION = "1.0.0"
    HIGH_THRESHOLD = 0.88
    MID_THRESHOLD = 0.75

    def _score_band(self, integrity_score: float) -> L8CoherenceBand:
        if integrity_score >= self.HIGH_THRESHOLD:
            return L8CoherenceBand.HIGH
        if integrity_score >= self.MID_THRESHOLD:
            return L8CoherenceBand.MID
        return L8CoherenceBand.LOW

    def evaluate(self, payload: L8Input) -> L8EvaluationResult:
        blockers: list[str] = []
        warnings: list[str] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        # -- Contract integrity --
        if not payload.input_ref or not payload.timestamp:
            blockers.append(L8BlockerCode.CONTRACT_PAYLOAD_MALFORMED.value)

        # -- Upstream L7 check --
        if not payload.upstream_l7_continuation_allowed:
            blockers.append(L8BlockerCode.UPSTREAM_L7_NOT_CONTINUABLE.value)

        # -- Required integrity sources --
        missing_required = sorted(
            set(payload.required_integrity_sources)
            - set(payload.available_integrity_sources)
        )
        if missing_required:
            blockers.append(L8BlockerCode.REQUIRED_INTEGRITY_SOURCE_MISSING.value)
            notes.append(
                f"Missing required integrity sources: {', '.join(missing_required)}"
            )

        # -- Freshness gate --
        if payload.freshness_state == L8FreshnessState.NO_PRODUCER:
            blockers.append(L8BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL.value)
        elif payload.freshness_state == L8FreshnessState.STALE_PRESERVED:
            warnings.append("STALE_PRESERVED_CONTEXT")
        elif payload.freshness_state == L8FreshnessState.DEGRADED:
            warnings.append("DEGRADED_CONTEXT")

        # -- Warmup gate --
        if payload.warmup_state == L8WarmupState.INSUFFICIENT:
            blockers.append(L8BlockerCode.WARMUP_INSUFFICIENT.value)
        elif payload.warmup_state == L8WarmupState.PARTIAL:
            warnings.append("PARTIAL_WARMUP")

        # -- Fallback legality --
        if payload.fallback_class == L8FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(L8BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED.value)
        elif payload.fallback_class == L8FallbackClass.LEGAL_EMERGENCY_PRESERVE:
            warnings.append("LEGAL_EMERGENCY_PRESERVE_USED")
        elif payload.fallback_class == L8FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
            rule_hits.append("LEGAL_PRIMARY_SUBSTITUTE")

        # -- TII availability --
        if not payload.tii_available:
            blockers.append(L8BlockerCode.TII_UNAVAILABLE.value)
        if not payload.twms_available:
            blockers.append(L8BlockerCode.TWMS_UNAVAILABLE.value)

        # -- Integrity state --
        integrity_state = str(payload.integrity_state).upper().strip()
        if integrity_state == "INVALID":
            blockers.append(L8BlockerCode.INTEGRITY_STATE_INVALID.value)
        elif integrity_state == "DEGRADED":
            warnings.append("INTEGRITY_STATE_DEGRADED")

        # -- Partial/degraded warnings --
        if payload.tii_partial:
            warnings.append("TII_PARTIAL")
        if payload.twms_partial:
            warnings.append("TWMS_PARTIAL")
        if payload.governance_degraded:
            warnings.append("GOVERNANCE_DEGRADED")
        if payload.stability_non_ideal:
            warnings.append("STABILITY_NON_IDEAL")

        # -- Coherence scoring --
        score_band = self._score_band(payload.integrity_score)
        rule_hits.append(f"score_band={score_band.value}")

        # -- Status compression --
        status = L8Status.PASS
        continuation_allowed = True
        next_targets = ["L9"]

        if blockers:
            status = L8Status.FAIL
            continuation_allowed = False
            next_targets = []
        elif score_band == L8CoherenceBand.LOW:
            status = L8Status.FAIL
            continuation_allowed = False
            next_targets = []
            blockers.append(L8BlockerCode.INTEGRITY_SCORE_BELOW_MINIMUM.value)
        else:
            if (
                payload.freshness_state != L8FreshnessState.FRESH
                or payload.warmup_state != L8WarmupState.READY
                or payload.fallback_class == L8FallbackClass.LEGAL_EMERGENCY_PRESERVE
                or score_band == L8CoherenceBand.MID
                or integrity_state == "DEGRADED"
                or payload.tii_partial
                or payload.twms_partial
                or payload.governance_degraded
                or payload.stability_non_ideal
            ):
                status = L8Status.WARN

        features = {
            "feature_vector": {
                "integrity_score": round(payload.integrity_score, 4),
                "tii_available": payload.tii_available,
                "twms_available": payload.twms_available,
                "integrity_state": integrity_state,
                "tii_partial": payload.tii_partial,
                "twms_partial": payload.twms_partial,
                "governance_degraded": payload.governance_degraded,
                "stability_non_ideal": payload.stability_non_ideal,
            },
            "feature_hash": (
                f"L8_{score_band.value}_{status.value}"
                f"_{int(round(payload.integrity_score * 100))}"
            ),
        }

        routing = {
            "source_used": list(payload.integrity_sources_used),
            "fallback_used": payload.fallback_class != L8FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
        }

        return L8EvaluationResult(
            layer="L8",
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
            score_numeric=round(payload.integrity_score, 4),
            features=features,
            routing=routing,
            audit=audit,
        )


def build_l8_input_from_dict(payload: dict[str, Any]) -> L8Input:
    return L8Input(
        input_ref=str(payload.get("input_ref", "")).strip(),
        timestamp=str(payload.get("timestamp", "")).strip(),
        upstream_l7_continuation_allowed=bool(
            payload.get("upstream_l7_continuation_allowed", True)
        ),
        integrity_sources_used=[
            str(x) for x in payload.get("integrity_sources_used", [])
        ],
        required_integrity_sources=[
            str(x) for x in payload.get("required_integrity_sources", [])
        ],
        available_integrity_sources=[
            str(x)
            for x in payload.get(
                "available_integrity_sources",
                payload.get("integrity_sources_used", []),
            )
        ],
        integrity_score=float(payload.get("integrity_score", 0.0)),
        tii_available=bool(payload.get("tii_available", True)),
        twms_available=bool(payload.get("twms_available", True)),
        integrity_state=str(payload.get("integrity_state", "VALID")),
        tii_partial=bool(payload.get("tii_partial", False)),
        twms_partial=bool(payload.get("twms_partial", False)),
        governance_degraded=bool(payload.get("governance_degraded", False)),
        stability_non_ideal=bool(payload.get("stability_non_ideal", False)),
        fallback_class=L8FallbackClass(
            str(payload.get("fallback_class", "NO_FALLBACK"))
        ),
        freshness_state=L8FreshnessState(
            str(payload.get("freshness_state", "FRESH"))
        ),
        warmup_state=L8WarmupState(str(payload.get("warmup_state", "READY"))),
    )
