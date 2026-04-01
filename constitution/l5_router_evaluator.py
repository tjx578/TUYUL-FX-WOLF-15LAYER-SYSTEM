"""L5 Router Evaluator — strict constitutional prototype.

Analysis-only module for psychology/discipline legality.
This module does NOT emit direction, execute, trade_valid, sizing,
or final verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class L5Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L5FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class L5WarmupState(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class L5FallbackClass(str, Enum):
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class L5CoherenceBand(str, Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class L5BlockerCode(str, Enum):
    UPSTREAM_L4_NOT_CONTINUABLE = "UPSTREAM_L4_NOT_CONTINUABLE"
    REQUIRED_PSYCHOLOGY_INPUT_MISSING = "REQUIRED_PSYCHOLOGY_INPUT_MISSING"
    DISCIPLINE_BELOW_MINIMUM = "DISCIPLINE_BELOW_MINIMUM"
    FATIGUE_CRITICAL = "FATIGUE_CRITICAL"
    FOCUS_CRITICAL = "FOCUS_CRITICAL"
    REVENGE_TRADING_ACTIVE = "REVENGE_TRADING_ACTIVE"
    RISK_EVENT_HARD_BLOCK = "RISK_EVENT_HARD_BLOCK"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


@dataclass(frozen=True)
class L5Input:
    input_ref: str
    timestamp: str
    upstream_l4_continuation_allowed: bool = True
    psychology_sources_used: list[str] = field(default_factory=list)
    required_psychology_inputs: list[str] = field(default_factory=list)
    available_psychology_inputs: list[str] = field(default_factory=list)
    psychology_score: float = 0.0
    discipline_score: float = 1.0
    fatigue_level: str = "LOW"
    focus_level: float = 1.0
    revenge_trading: bool = False
    fomo_level: float = 0.0
    emotional_bias: float = 0.0
    risk_event_active: bool = False
    caution_event: bool = False
    fallback_class: L5FallbackClass = L5FallbackClass.NO_FALLBACK
    freshness_state: L5FreshnessState = L5FreshnessState.FRESH
    warmup_state: L5WarmupState = L5WarmupState.READY


@dataclass(frozen=True)
class L5EvaluationResult:
    layer: str
    layer_version: str
    timestamp: str
    input_ref: str
    status: L5Status
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


class L5RouterEvaluator:
    VERSION = "1.0.0"
    HIGH_THRESHOLD = 0.85
    MID_THRESHOLD = 0.65
    DISCIPLINE_MIN = 0.65
    FOCUS_CRITICAL_MAX = 0.30
    FOCUS_WARN_MAX = 0.60
    FOMO_WARN_MIN = 0.60
    EMOTIONAL_BIAS_WARN_ABS = 0.60

    def _score_band(self, psychology_score: float) -> L5CoherenceBand:
        if psychology_score >= self.HIGH_THRESHOLD:
            return L5CoherenceBand.HIGH
        if psychology_score >= self.MID_THRESHOLD:
            return L5CoherenceBand.MID
        return L5CoherenceBand.LOW

    def evaluate(self, payload: L5Input) -> L5EvaluationResult:
        blockers: list[str] = []
        warnings: list[str] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        # -- Contract integrity --
        if not payload.input_ref or not payload.timestamp:
            blockers.append(L5BlockerCode.CONTRACT_PAYLOAD_MALFORMED.value)

        # -- Upstream L4 check --
        if not payload.upstream_l4_continuation_allowed:
            blockers.append(L5BlockerCode.UPSTREAM_L4_NOT_CONTINUABLE.value)

        # -- Required psychology inputs --
        missing_required = sorted(
            set(payload.required_psychology_inputs)
            - set(payload.available_psychology_inputs)
        )
        if missing_required:
            blockers.append(L5BlockerCode.REQUIRED_PSYCHOLOGY_INPUT_MISSING.value)
            notes.append(
                f"Missing required psychology inputs: {', '.join(missing_required)}"
            )

        # -- Freshness gate --
        if payload.freshness_state == L5FreshnessState.NO_PRODUCER:
            blockers.append(L5BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL.value)
        elif payload.freshness_state == L5FreshnessState.STALE_PRESERVED:
            warnings.append("STALE_PRESERVED_CONTEXT")
        elif payload.freshness_state == L5FreshnessState.DEGRADED:
            warnings.append("DEGRADED_CONTEXT")

        # -- Warmup gate --
        if payload.warmup_state == L5WarmupState.INSUFFICIENT:
            blockers.append(L5BlockerCode.WARMUP_INSUFFICIENT.value)
        elif payload.warmup_state == L5WarmupState.PARTIAL:
            warnings.append("PARTIAL_WARMUP")

        # -- Fallback legality --
        if payload.fallback_class == L5FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(L5BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED.value)
        elif payload.fallback_class == L5FallbackClass.LEGAL_EMERGENCY_PRESERVE:
            warnings.append("LEGAL_EMERGENCY_PRESERVE_USED")
        elif payload.fallback_class == L5FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
            rule_hits.append("LEGAL_PRIMARY_SUBSTITUTE")

        # -- Discipline gate --
        if payload.discipline_score < self.DISCIPLINE_MIN:
            blockers.append(L5BlockerCode.DISCIPLINE_BELOW_MINIMUM.value)

        # -- Fatigue gate --
        fatigue = payload.fatigue_level.upper()
        if fatigue == "CRITICAL":
            blockers.append(L5BlockerCode.FATIGUE_CRITICAL.value)
        elif fatigue in {"HIGH", "MEDIUM"}:
            warnings.append(f"FATIGUE_{fatigue}")

        # -- Focus gate --
        if payload.focus_level < self.FOCUS_CRITICAL_MAX:
            blockers.append(L5BlockerCode.FOCUS_CRITICAL.value)
        elif payload.focus_level < self.FOCUS_WARN_MAX:
            warnings.append("FOCUS_LOW")

        # -- Revenge trading --
        if payload.revenge_trading:
            blockers.append(L5BlockerCode.REVENGE_TRADING_ACTIVE.value)

        # -- FOMO --
        if payload.fomo_level >= self.FOMO_WARN_MIN:
            warnings.append("FOMO_ELEVATED")

        # -- Emotional bias --
        if abs(payload.emotional_bias) >= self.EMOTIONAL_BIAS_WARN_ABS:
            warnings.append("EMOTIONAL_BIAS_ELEVATED")

        # -- Risk event --
        if payload.risk_event_active:
            blockers.append(L5BlockerCode.RISK_EVENT_HARD_BLOCK.value)
        elif payload.caution_event:
            warnings.append("CAUTION_EVENT_ACTIVE")

        # -- Coherence scoring --
        score_band = self._score_band(payload.psychology_score)
        rule_hits.append(f"score_band={score_band.value}")

        # -- Status compression --
        status = L5Status.PASS
        continuation_allowed = True
        next_targets = ["PHASE_2_5"]

        if blockers:
            status = L5Status.FAIL
            continuation_allowed = False
            next_targets = []
        elif score_band == L5CoherenceBand.LOW:
            status = L5Status.FAIL
            continuation_allowed = False
            next_targets = []
            blockers.append("PSYCHOLOGY_SCORE_TOO_LOW")
        else:
            if (
                payload.freshness_state != L5FreshnessState.FRESH
                or payload.warmup_state != L5WarmupState.READY
                or payload.fallback_class == L5FallbackClass.LEGAL_EMERGENCY_PRESERVE
                or score_band == L5CoherenceBand.MID
                or fatigue in {"HIGH", "MEDIUM"}
                or payload.focus_level < self.FOCUS_WARN_MAX
                or payload.fomo_level >= self.FOMO_WARN_MIN
                or abs(payload.emotional_bias) >= self.EMOTIONAL_BIAS_WARN_ABS
                or payload.caution_event
            ):
                status = L5Status.WARN

        features = {
            "feature_vector": {
                "psychology_score": round(payload.psychology_score, 4),
                "discipline_score": round(payload.discipline_score, 4),
                "fatigue_level": fatigue,
                "focus_level": round(payload.focus_level, 4),
                "revenge_trading": payload.revenge_trading,
                "fomo_level": round(payload.fomo_level, 4),
                "emotional_bias": round(payload.emotional_bias, 4),
                "risk_event_active": payload.risk_event_active,
                "caution_event": payload.caution_event,
            },
            "feature_hash": (
                f"L5_{score_band.value}_{status.value}"
                f"_{int(round(payload.psychology_score * 100))}"
            ),
        }

        routing = {
            "source_used": list(payload.psychology_sources_used),
            "fallback_used": payload.fallback_class != L5FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
        }

        return L5EvaluationResult(
            layer="L5",
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
            score_numeric=round(payload.psychology_score, 4),
            features=features,
            routing=routing,
            audit=audit,
        )


def build_l5_input_from_dict(payload: dict[str, Any]) -> L5Input:
    return L5Input(
        input_ref=str(payload.get("input_ref", "")).strip(),
        timestamp=str(payload.get("timestamp", "")).strip(),
        upstream_l4_continuation_allowed=bool(
            payload.get("upstream_l4_continuation_allowed", True)
        ),
        psychology_sources_used=[
            str(x) for x in payload.get("psychology_sources_used", [])
        ],
        required_psychology_inputs=[
            str(x) for x in payload.get("required_psychology_inputs", [])
        ],
        available_psychology_inputs=[
            str(x)
            for x in payload.get(
                "available_psychology_inputs",
                payload.get("psychology_sources_used", []),
            )
        ],
        psychology_score=float(payload.get("psychology_score", 0.0)),
        discipline_score=float(payload.get("discipline_score", 1.0)),
        fatigue_level=str(payload.get("fatigue_level", "LOW")),
        focus_level=float(payload.get("focus_level", 1.0)),
        revenge_trading=bool(payload.get("revenge_trading", False)),
        fomo_level=float(payload.get("fomo_level", 0.0)),
        emotional_bias=float(payload.get("emotional_bias", 0.0)),
        risk_event_active=bool(payload.get("risk_event_active", False)),
        caution_event=bool(payload.get("caution_event", False)),
        fallback_class=L5FallbackClass(
            str(payload.get("fallback_class", "NO_FALLBACK"))
        ),
        freshness_state=L5FreshnessState(
            str(payload.get("freshness_state", "FRESH"))
        ),
        warmup_state=L5WarmupState(str(payload.get("warmup_state", "READY"))),
    )
