from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class L3Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class WarmupState(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class FallbackClass(str, Enum):
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"
    NO_FALLBACK = "NO_FALLBACK"


class CoherenceBand(str, Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class BlockerCode(str, Enum):
    UPSTREAM_L2_NOT_CONTINUABLE = "UPSTREAM_L2_NOT_CONTINUABLE"
    REQUIRED_TREND_SOURCE_MISSING = "REQUIRED_TREND_SOURCE_MISSING"
    TREND_CONFIRMATION_UNAVAILABLE = "TREND_CONFIRMATION_UNAVAILABLE"
    TREND_STRUCTURE_CONFLICT = "TREND_STRUCTURE_CONFLICT"
    TREND_SOURCE_INVALID = "TREND_SOURCE_INVALID"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"
    LOW_CONFIRMATION_SCORE = "LOW_CONFIRMATION_SCORE"


@dataclass(frozen=True)
class L3Input:
    input_ref: str
    timestamp: str
    trend_sources_used: list[str]
    required_trend_sources: list[str]
    available_trend_sources: list[str]
    confirmation_score: float
    trend_confirmed: bool
    structure_conflict: bool
    upstream_l2_continuation_allowed: bool
    freshness_state: FreshnessState
    warmup_state: WarmupState
    fallback_class: FallbackClass = FallbackClass.NO_FALLBACK
    fallback_used: bool = False
    required_trend_source_missing: bool = False
    trend_confirmation_unavailable: bool = False
    freshness_governance_hard_fail: bool = False
    trend_source_invalid: bool = False
    contract_payload_malformed: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class L3EvaluationResult:
    layer: str
    layer_version: str
    timestamp: str
    input_ref: str
    status: L3Status
    continuation_allowed: bool
    blocker_codes: list[str]
    warning_codes: list[str]
    fallback_class: str
    freshness_state: str
    warmup_state: str
    coherence_band: str
    coherence_score: float
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
            "coherence_score": self.coherence_score,
            "features": self.features,
            "routing": self.routing,
            "audit": self.audit,
        }


class L3RouterEvaluator:
    """Strict constitutional L3 evaluator."""

    VERSION = "1.0.0"
    # Calibrated for sigmoid edge model (bias=-3.5). See L3_constitutional.py.
    HIGH_THRESHOLD = 0.55
    MID_THRESHOLD = 0.25
    # Hard floor: below this → blocker. Between HARD_FLOOR and MID → WARN band.
    HARD_FLOOR = 0.15

    def coherence_band(self, score: float) -> CoherenceBand:
        if score >= self.HIGH_THRESHOLD:
            return CoherenceBand.HIGH
        if score >= self.MID_THRESHOLD:
            return CoherenceBand.MID
        return CoherenceBand.LOW

    def _critical_blockers(self, payload: L3Input) -> list[BlockerCode]:
        blockers: list[BlockerCode] = []

        if not payload.upstream_l2_continuation_allowed:
            blockers.append(BlockerCode.UPSTREAM_L2_NOT_CONTINUABLE)

        missing_required = [s for s in payload.required_trend_sources if s not in payload.available_trend_sources]
        if payload.required_trend_source_missing or missing_required:
            blockers.append(BlockerCode.REQUIRED_TREND_SOURCE_MISSING)

        if payload.trend_confirmation_unavailable or not payload.trend_confirmed:
            blockers.append(BlockerCode.TREND_CONFIRMATION_UNAVAILABLE)

        if payload.structure_conflict:
            blockers.append(BlockerCode.TREND_STRUCTURE_CONFLICT)

        if payload.trend_source_invalid:
            blockers.append(BlockerCode.TREND_SOURCE_INVALID)

        if payload.freshness_governance_hard_fail or payload.freshness_state == FreshnessState.NO_PRODUCER:
            blockers.append(BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL)

        if payload.warmup_state == WarmupState.INSUFFICIENT:
            blockers.append(BlockerCode.WARMUP_INSUFFICIENT)

        if payload.fallback_class == FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED)

        if payload.contract_payload_malformed:
            blockers.append(BlockerCode.CONTRACT_PAYLOAD_MALFORMED)

        # v1.2: diagnostic blocker only when score < hard floor (not MID threshold)
        # Scores between HARD_FLOOR and MID_THRESHOLD get WARN band, not blocker
        if payload.confirmation_score < self.HARD_FLOOR:
            blockers.append(BlockerCode.LOW_CONFIRMATION_SCORE)

        deduped: list[BlockerCode] = []
        seen = set()
        for item in blockers:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        return deduped

    def evaluate(self, payload: L3Input) -> L3EvaluationResult:
        blockers = self._critical_blockers(payload)
        band = self.coherence_band(payload.confirmation_score)
        warning_codes: list[str] = []
        rule_hits = [
            f"freshness_state={payload.freshness_state.value}",
            f"warmup_state={payload.warmup_state.value}",
            f"fallback_class={payload.fallback_class.value}",
            f"trend_confirmed={payload.trend_confirmed}",
            f"structure_conflict={payload.structure_conflict}",
            f"required_sources={len(payload.required_trend_sources)}",
            f"available_sources={len(payload.available_trend_sources)}",
        ]

        if blockers:
            status = L3Status.FAIL
            continuation_allowed = False
        else:
            if band == CoherenceBand.LOW:
                # LOW band without blocker = score in WARN range (HARD_FLOOR..MID)
                # Allow as WARN with degradation warning
                low_warn_legal = (
                    payload.trend_confirmed
                    and not payload.structure_conflict
                    and payload.freshness_state in (
                        FreshnessState.FRESH,
                        FreshnessState.STALE_PRESERVED,
                        FreshnessState.DEGRADED,
                    )
                    and payload.warmup_state in (WarmupState.READY, WarmupState.PARTIAL)
                )
                if low_warn_legal:
                    status = L3Status.WARN
                    continuation_allowed = True
                    warning_codes.append("LOW_CONFIRMATION_SCORE_DEGRADED")
                else:
                    status = L3Status.FAIL
                    continuation_allowed = False
                    warning_codes.append("LOW_CONFIRMATION")
            elif (
                payload.freshness_state == FreshnessState.FRESH
                and payload.warmup_state == WarmupState.READY
                and band in (CoherenceBand.HIGH, CoherenceBand.MID)
                and payload.trend_confirmed
                and not payload.structure_conflict
                and payload.fallback_class in (
                    FallbackClass.NO_FALLBACK,
                    FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
                )
            ):
                status = L3Status.PASS
                continuation_allowed = True
                if payload.fallback_class == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
                    warning_codes.append("PRIMARY_SUBSTITUTE_USED")
            else:
                legal_warn = (
                    payload.upstream_l2_continuation_allowed
                    and payload.freshness_state in (
                        FreshnessState.FRESH,
                        FreshnessState.STALE_PRESERVED,
                        FreshnessState.DEGRADED,
                    )
                    and payload.warmup_state in (WarmupState.READY, WarmupState.PARTIAL)
                    and band in (CoherenceBand.HIGH, CoherenceBand.MID)
                    and payload.trend_confirmed
                    and not payload.structure_conflict
                    and payload.fallback_class in (
                        FallbackClass.NO_FALLBACK,
                        FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
                        FallbackClass.LEGAL_EMERGENCY_PRESERVE,
                    )
                )
                if legal_warn:
                    status = L3Status.WARN
                    continuation_allowed = True
                    if payload.freshness_state == FreshnessState.STALE_PRESERVED:
                        warning_codes.append("STALE_PRESERVED_TREND_CONTEXT")
                    if payload.freshness_state == FreshnessState.DEGRADED:
                        warning_codes.append("DEGRADED_TREND_CONTEXT")
                    if payload.warmup_state == WarmupState.PARTIAL:
                        warning_codes.append("PARTIAL_WARMUP")
                    if payload.fallback_class == FallbackClass.LEGAL_EMERGENCY_PRESERVE:
                        warning_codes.append("EMERGENCY_PRESERVE_FALLBACK")
                    if payload.fallback_class == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
                        warning_codes.append("PRIMARY_SUBSTITUTE_USED")
                else:
                    status = L3Status.FAIL
                    continuation_allowed = False

        missing_required = [s for s in payload.required_trend_sources if s not in payload.available_trend_sources]
        next_targets = ["L4"] if continuation_allowed else []

        features = {
            "confirmation_score": round(payload.confirmation_score, 4),
            "trend_confirmed": payload.trend_confirmed,
            "structure_conflict": payload.structure_conflict,
            "required_trend_sources": payload.required_trend_sources,
            "available_trend_sources": payload.available_trend_sources,
            "missing_required_trend_sources": missing_required,
        }

        routing = {
            "source_used": payload.trend_sources_used,
            "fallback_used": payload.fallback_used,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": list(payload.notes),
        }

        return L3EvaluationResult(
            layer="L3",
            layer_version=self.VERSION,
            timestamp=payload.timestamp,
            input_ref=payload.input_ref,
            status=status,
            continuation_allowed=continuation_allowed,
            blocker_codes=[b.value for b in blockers],
            warning_codes=warning_codes,
            fallback_class=payload.fallback_class.value,
            freshness_state=payload.freshness_state.value,
            warmup_state=payload.warmup_state.value,
            coherence_band=band.value,
            coherence_score=round(payload.confirmation_score, 4),
            features=features,
            routing=routing,
            audit=audit,
        )


def build_l3_input_from_dict(payload: dict[str, Any]) -> L3Input:
    """Adapter from generic JSON/runtime payload to typed L3Input."""
    required = [
        "input_ref",
        "timestamp",
        "trend_sources_used",
        "required_trend_sources",
        "available_trend_sources",
        "confirmation_score",
        "trend_confirmed",
        "structure_conflict",
        "upstream_l2_continuation_allowed",
        "freshness_state",
        "warmup_state",
    ]
    missing = [f for f in required if f not in payload]
    if missing:
        raise ValueError(f"Missing required L3 payload fields: {', '.join(missing)}")

    return L3Input(
        input_ref=str(payload["input_ref"]),
        timestamp=str(payload["timestamp"]),
        trend_sources_used=[str(x) for x in payload["trend_sources_used"]],
        required_trend_sources=[str(x) for x in payload["required_trend_sources"]],
        available_trend_sources=[str(x) for x in payload["available_trend_sources"]],
        confirmation_score=float(payload["confirmation_score"]),
        trend_confirmed=bool(payload["trend_confirmed"]),
        structure_conflict=bool(payload["structure_conflict"]),
        upstream_l2_continuation_allowed=bool(payload["upstream_l2_continuation_allowed"]),
        freshness_state=FreshnessState(str(payload["freshness_state"])),
        warmup_state=WarmupState(str(payload["warmup_state"])),
        fallback_class=FallbackClass(str(payload.get("fallback_class", FallbackClass.NO_FALLBACK.value))),
        fallback_used=bool(payload.get("fallback_used", False)),
        required_trend_source_missing=bool(payload.get("required_trend_source_missing", False)),
        trend_confirmation_unavailable=bool(payload.get("trend_confirmation_unavailable", False)),
        freshness_governance_hard_fail=bool(payload.get("freshness_governance_hard_fail", False)),
        trend_source_invalid=bool(payload.get("trend_source_invalid", False)),
        contract_payload_malformed=bool(payload.get("contract_payload_malformed", False)),
        notes=[str(x) for x in payload.get("notes", [])],
    )
