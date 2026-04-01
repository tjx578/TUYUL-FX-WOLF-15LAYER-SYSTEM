"""L4 Router Evaluator — strict constitutional prototype.

Analysis-only module for session/scoring legality.
This module does NOT emit direction, execute, trade_valid, sizing,
or final verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class L4Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L4FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class L4WarmupState(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class L4FallbackClass(str, Enum):
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class L4CoherenceBand(str, Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class L4BlockerCode(str, Enum):
    UPSTREAM_L3_NOT_CONTINUABLE = "UPSTREAM_L3_NOT_CONTINUABLE"
    REQUIRED_SESSION_SOURCE_MISSING = "REQUIRED_SESSION_SOURCE_MISSING"
    SESSION_STATE_INVALID = "SESSION_STATE_INVALID"
    SESSION_EXPECTANCY_UNAVAILABLE = "SESSION_EXPECTANCY_UNAVAILABLE"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


@dataclass(frozen=True)
class L4Input:
    input_ref: str
    timestamp: str
    upstream_l3_continuation_allowed: bool = True

    session_sources_used: list[str] = field(default_factory=list)
    required_session_sources: list[str] = field(default_factory=list)
    available_session_sources: list[str] = field(default_factory=list)

    session_score: float = 0.0
    session_valid: bool = True
    expectancy_available: bool = True
    prime_session: bool = True
    degraded_scoring_mode: bool = False

    fallback_class: L4FallbackClass = L4FallbackClass.NO_FALLBACK
    freshness_state: L4FreshnessState = L4FreshnessState.FRESH
    warmup_state: L4WarmupState = L4WarmupState.READY


@dataclass(frozen=True)
class L4EvaluationResult:
    layer: str
    layer_version: str
    timestamp: str
    input_ref: str
    status: L4Status
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


class L4RouterEvaluator:
    VERSION = "1.0.0"
    HIGH_THRESHOLD = 0.85
    MID_THRESHOLD = 0.65

    def _score_band(self, session_score: float) -> L4CoherenceBand:
        if session_score >= self.HIGH_THRESHOLD:
            return L4CoherenceBand.HIGH
        if session_score >= self.MID_THRESHOLD:
            return L4CoherenceBand.MID
        return L4CoherenceBand.LOW

    def evaluate(self, payload: L4Input) -> L4EvaluationResult:
        blockers: list[str] = []
        warnings: list[str] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        if not payload.input_ref or not payload.timestamp:
            blockers.append(L4BlockerCode.CONTRACT_PAYLOAD_MALFORMED.value)

        if not payload.upstream_l3_continuation_allowed:
            blockers.append(L4BlockerCode.UPSTREAM_L3_NOT_CONTINUABLE.value)

        missing_required_sources = sorted(
            set(payload.required_session_sources)
            - set(payload.available_session_sources)
        )
        if missing_required_sources:
            blockers.append(L4BlockerCode.REQUIRED_SESSION_SOURCE_MISSING.value)
            notes.append(
                f"Missing required session sources: {', '.join(missing_required_sources)}"
            )

        if payload.freshness_state == L4FreshnessState.NO_PRODUCER:
            blockers.append(L4BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL.value)
        elif payload.freshness_state == L4FreshnessState.STALE_PRESERVED:
            warnings.append("STALE_PRESERVED_CONTEXT")
        elif payload.freshness_state == L4FreshnessState.DEGRADED:
            warnings.append("DEGRADED_CONTEXT")

        if payload.warmup_state == L4WarmupState.INSUFFICIENT:
            blockers.append(L4BlockerCode.WARMUP_INSUFFICIENT.value)
        elif payload.warmup_state == L4WarmupState.PARTIAL:
            warnings.append("PARTIAL_WARMUP")

        if payload.fallback_class == L4FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(L4BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED.value)
        elif payload.fallback_class == L4FallbackClass.LEGAL_EMERGENCY_PRESERVE:
            warnings.append("LEGAL_EMERGENCY_PRESERVE_USED")
        elif payload.fallback_class == L4FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
            rule_hits.append("LEGAL_PRIMARY_SUBSTITUTE")

        if not payload.session_valid:
            blockers.append(L4BlockerCode.SESSION_STATE_INVALID.value)

        if not payload.expectancy_available:
            blockers.append(L4BlockerCode.SESSION_EXPECTANCY_UNAVAILABLE.value)

        if not payload.prime_session:
            warnings.append("NON_PRIME_BUT_LEGAL_SESSION")

        if payload.degraded_scoring_mode:
            warnings.append("DEGRADED_SCORING_MODE")

        score_band = self._score_band(payload.session_score)
        rule_hits.append(f"score_band={score_band.value}")

        status = L4Status.PASS
        continuation_allowed = True
        next_targets = ["L5"]

        if blockers:
            status = L4Status.FAIL
            continuation_allowed = False
            next_targets = []
        elif score_band == L4CoherenceBand.LOW:
            status = L4Status.FAIL
            continuation_allowed = False
            next_targets = []
            blockers.append("SESSION_SCORE_TOO_LOW")
        else:
            if (
                payload.freshness_state != L4FreshnessState.FRESH
                or payload.warmup_state != L4WarmupState.READY
                or payload.fallback_class == L4FallbackClass.LEGAL_EMERGENCY_PRESERVE
                or score_band == L4CoherenceBand.MID
                or not payload.prime_session
                or payload.degraded_scoring_mode
            ):
                status = L4Status.WARN

        features = {
            "feature_vector": {
                "session_score": round(payload.session_score, 4),
                "session_valid": payload.session_valid,
                "expectancy_available": payload.expectancy_available,
                "prime_session": payload.prime_session,
                "degraded_scoring_mode": payload.degraded_scoring_mode,
            },
            "feature_hash": (
                f"L4_{score_band.value}_{status.value}"
                f"_{int(round(payload.session_score * 100))}"
            ),
        }

        routing = {
            "source_used": list(payload.session_sources_used),
            "fallback_used": payload.fallback_class != L4FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
        }

        return L4EvaluationResult(
            layer="L4",
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
            score_numeric=round(payload.session_score, 4),
            features=features,
            routing=routing,
            audit=audit,
        )


def build_l4_input_from_dict(payload: dict[str, Any]) -> L4Input:
    return L4Input(
        input_ref=str(payload.get("input_ref", "")).strip(),
        timestamp=str(payload.get("timestamp", "")).strip(),
        upstream_l3_continuation_allowed=bool(
            payload.get("upstream_l3_continuation_allowed", True)
        ),
        session_sources_used=[
            str(x) for x in payload.get("session_sources_used", [])
        ],
        required_session_sources=[
            str(x) for x in payload.get("required_session_sources", [])
        ],
        available_session_sources=[
            str(x)
            for x in payload.get(
                "available_session_sources",
                payload.get("session_sources_used", []),
            )
        ],
        session_score=float(payload.get("session_score", 0.0)),
        session_valid=bool(payload.get("session_valid", True)),
        expectancy_available=bool(payload.get("expectancy_available", True)),
        prime_session=bool(payload.get("prime_session", True)),
        degraded_scoring_mode=bool(payload.get("degraded_scoring_mode", False)),
        fallback_class=L4FallbackClass(
            str(payload.get("fallback_class", "NO_FALLBACK"))
        ),
        freshness_state=L4FreshnessState(
            str(payload.get("freshness_state", "FRESH"))
        ),
        warmup_state=L4WarmupState(str(payload.get("warmup_state", "READY"))),
    )
