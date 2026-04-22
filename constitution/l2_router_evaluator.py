from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class L2Status(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class FreshnessState(StrEnum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class WarmupState(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class FallbackClass(StrEnum):
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"
    NO_FALLBACK = "NO_FALLBACK"


class CoherenceBand(StrEnum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class BlockerCode(StrEnum):
    UPSTREAM_L1_NOT_CONTINUABLE = "UPSTREAM_L1_NOT_CONTINUABLE"
    REQUIRED_TIMEFRAME_MISSING = "REQUIRED_TIMEFRAME_MISSING"
    TIMEFRAME_SET_INSUFFICIENT = "TIMEFRAME_SET_INSUFFICIENT"
    MTA_HIERARCHY_VIOLATED = "MTA_HIERARCHY_VIOLATED"
    STRUCTURE_SOURCE_INVALID = "STRUCTURE_SOURCE_INVALID"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


@dataclass(frozen=True)
class L2Input:
    input_ref: str
    timestamp: str
    structure_sources_used: list[str]
    required_timeframes: list[str]
    coverage_target_timeframes: list[str]
    available_timeframes: list[str]
    alignment_score: float
    hierarchy_followed: bool
    aligned: bool
    upstream_l1_continuation_allowed: bool
    freshness_state: FreshnessState
    warmup_state: WarmupState
    hierarchy_band: str = "PASS"
    fallback_class: FallbackClass = FallbackClass.NO_FALLBACK
    fallback_used: bool = False
    required_timeframe_missing: bool = False
    freshness_governance_hard_fail: bool = False
    structure_source_invalid: bool = False
    timeframe_set_insufficient: bool = False
    contract_payload_malformed: bool = False
    adaptive_pass_threshold: float | None = None
    adaptive_warn_threshold: float | None = None
    adaptive_regime: str = "UNKNOWN"
    adaptive_mode: str = "shadow"
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class L2EvaluationResult:
    layer: str
    layer_version: str
    timestamp: str
    input_ref: str
    status: L2Status
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


class L2RouterEvaluator:
    """Strict constitutional L2 evaluator."""

    VERSION = "1.0.0"
    HIGH_THRESHOLD = 0.85
    MID_THRESHOLD = 0.65

    def coherence_band(self, score: float) -> CoherenceBand:
        if score >= self.HIGH_THRESHOLD:
            return CoherenceBand.HIGH
        if score >= self.MID_THRESHOLD:
            return CoherenceBand.MID
        return CoherenceBand.LOW

    @staticmethod
    def _adaptive_band(score: float, pass_threshold: float | None, warn_threshold: float | None) -> str | None:
        if pass_threshold is None or warn_threshold is None:
            return None
        if score >= pass_threshold:
            return "PASS"
        if score >= warn_threshold:
            return "WARN"
        return "FAIL"

    def _critical_blockers(self, payload: L2Input) -> list[BlockerCode]:
        blockers: list[BlockerCode] = []

        if not payload.upstream_l1_continuation_allowed:
            blockers.append(BlockerCode.UPSTREAM_L1_NOT_CONTINUABLE)

        missing_required = [tf for tf in payload.required_timeframes if tf not in payload.available_timeframes]
        if payload.required_timeframe_missing or missing_required:
            blockers.append(BlockerCode.REQUIRED_TIMEFRAME_MISSING)

        if payload.timeframe_set_insufficient or len(payload.available_timeframes) < 3:
            blockers.append(BlockerCode.TIMEFRAME_SET_INSUFFICIENT)

        if payload.structure_source_invalid:
            blockers.append(BlockerCode.STRUCTURE_SOURCE_INVALID)

        if payload.freshness_governance_hard_fail or payload.freshness_state == FreshnessState.NO_PRODUCER:
            blockers.append(BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL)

        if payload.warmup_state == WarmupState.INSUFFICIENT:
            blockers.append(BlockerCode.WARMUP_INSUFFICIENT)

        if payload.fallback_class == FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED)

        if payload.contract_payload_malformed:
            blockers.append(BlockerCode.CONTRACT_PAYLOAD_MALFORMED)

        deduped: list[BlockerCode] = []
        seen = set()
        for blocker in blockers:
            if blocker.value not in seen:
                seen.add(blocker.value)
                deduped.append(blocker)
        return deduped

    @staticmethod
    def _confidence_penalty(payload: L2Input, band: CoherenceBand, partial_coverage: bool, blockers: list[BlockerCode]) -> float:
        if blockers:
            return 1.0

        penalty = 0.0
        if band == CoherenceBand.LOW:
            penalty += 0.35
        if not payload.hierarchy_followed:
            penalty += 0.25
        if not payload.aligned:
            penalty += 0.15
        if partial_coverage:
            penalty += 0.10
        if payload.freshness_state == FreshnessState.STALE_PRESERVED:
            penalty += 0.10
        elif payload.freshness_state == FreshnessState.DEGRADED:
            penalty += 0.20
        if payload.warmup_state == WarmupState.PARTIAL:
            penalty += 0.10
        if payload.fallback_class == FallbackClass.LEGAL_EMERGENCY_PRESERVE:
            penalty += 0.10
        elif payload.fallback_class == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
            penalty += 0.05
        return round(max(0.0, min(1.0, penalty)), 4)

    def evaluate(self, payload: L2Input) -> L2EvaluationResult:
        blockers = self._critical_blockers(payload)
        warning_codes: list[str] = []
        rule_hits: list[str] = []

        band = self.coherence_band(payload.alignment_score)
        rule_hits.append(f"coherence_band={band.value}")
        rule_hits.append(f"freshness_state={payload.freshness_state.value}")
        rule_hits.append(f"warmup_state={payload.warmup_state.value}")
        rule_hits.append(f"fallback_class={payload.fallback_class.value}")
        rule_hits.append(f"available_timeframes={len(payload.available_timeframes)}")
        rule_hits.append(f"hierarchy_followed={payload.hierarchy_followed}")
        rule_hits.append(f"hierarchy_band={payload.hierarchy_band}")
        rule_hits.append(f"aligned={payload.aligned}")
        adaptive_band = self._adaptive_band(
            payload.alignment_score,
            payload.adaptive_pass_threshold,
            payload.adaptive_warn_threshold,
        )
        adaptive_shadow_status = f"{adaptive_band}_SHADOW" if adaptive_band else None
        if adaptive_band:
            rule_hits.append(f"adaptive_band={adaptive_band}")

        target_timeframes = payload.coverage_target_timeframes or payload.required_timeframes
        partial_coverage = any(tf not in payload.available_timeframes for tf in target_timeframes)
        confidence_penalty = self._confidence_penalty(payload, band, partial_coverage, blockers)
        evidence_score = round(max(0.0, min(1.0, payload.alignment_score * (1.0 - confidence_penalty))), 4)

        if blockers:
            status = L2Status.FAIL
            continuation_allowed = False
        else:
            if (
                payload.freshness_state == FreshnessState.FRESH
                and payload.warmup_state == WarmupState.READY
                and band in (CoherenceBand.HIGH, CoherenceBand.MID)
                and payload.hierarchy_followed
                and payload.aligned
                and not partial_coverage
                and payload.fallback_class in (
                    FallbackClass.NO_FALLBACK,
                    FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
                )
            ):
                status = L2Status.PASS
                continuation_allowed = True
                if payload.fallback_class == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
                    warning_codes.append("PRIMARY_SUBSTITUTE_USED")
            else:
                status = L2Status.WARN
                continuation_allowed = True
                if not payload.hierarchy_followed:
                    warning_codes.append(BlockerCode.MTA_HIERARCHY_VIOLATED.value)
                elif payload.hierarchy_band == "WARN":
                    warning_codes.append("MTA_HIERARCHY_DEGRADED")
                if band == CoherenceBand.LOW:
                    warning_codes.append("LOW_ALIGNMENT_BAND")
                if not payload.aligned:
                    warning_codes.append("STRUCTURE_NOT_FULLY_ALIGNED")
                if partial_coverage:
                    warning_codes.append("PARTIAL_TIMEFRAME_COVERAGE")
                if payload.freshness_state == FreshnessState.STALE_PRESERVED:
                    warning_codes.append("STALE_PRESERVED_STRUCTURE")
                if payload.freshness_state == FreshnessState.DEGRADED:
                    warning_codes.append("DEGRADED_STRUCTURE")
                if payload.warmup_state == WarmupState.PARTIAL:
                    warning_codes.append("PARTIAL_WARMUP")
                if payload.fallback_class == FallbackClass.LEGAL_EMERGENCY_PRESERVE:
                    warning_codes.append("EMERGENCY_PRESERVE_FALLBACK")
                if payload.fallback_class == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
                    warning_codes.append("PRIMARY_SUBSTITUTE_USED")

        next_targets = ["L3"] if continuation_allowed else []
        missing_required = [tf for tf in payload.required_timeframes if tf not in payload.available_timeframes]

        features = {
            "alignment_score": round(payload.alignment_score, 4),
            "evidence_score": evidence_score,
            "confidence_penalty": confidence_penalty,
            "required_alignment": self.MID_THRESHOLD,
            "frozen_required_alignment": self.MID_THRESHOLD,
            "adaptive_warn_threshold": payload.adaptive_warn_threshold,
            "adaptive_pass_threshold": payload.adaptive_pass_threshold,
            "frozen_band": band.value,
            "adaptive_band": adaptive_band,
            "adaptive_shadow_status": adaptive_shadow_status,
            "adaptive_mode": payload.adaptive_mode,
            "adaptive_regime": payload.adaptive_regime,
            "hierarchy_followed": payload.hierarchy_followed,
            "hierarchy_band": payload.hierarchy_band,
            "aligned": payload.aligned,
            "required_timeframes": payload.required_timeframes,
            "coverage_target_timeframes": payload.coverage_target_timeframes,
            "available_timeframes": payload.available_timeframes,
            "missing_required_timeframes": missing_required,
            "hard_blockers": [b.value for b in blockers],
            "soft_blockers": warning_codes,
        }

        routing = {
            "source_used": payload.structure_sources_used,
            "fallback_used": payload.fallback_used,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": list(payload.notes),
        }

        return L2EvaluationResult(
            layer="L2",
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
            coherence_score=round(payload.alignment_score, 4),
            features=features,
            routing=routing,
            audit=audit,
        )


def build_l2_input_from_dict(payload: dict[str, Any]) -> L2Input:
    """Adapter from generic JSON/runtime payload to typed L2Input."""
    required = [
        "input_ref",
        "timestamp",
        "structure_sources_used",
        "required_timeframes",
        "available_timeframes",
        "alignment_score",
        "hierarchy_followed",
        "aligned",
        "upstream_l1_continuation_allowed",
        "freshness_state",
        "warmup_state",
    ]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Missing required L2 payload fields: {', '.join(missing)}")

    return L2Input(
        input_ref=str(payload["input_ref"]),
        timestamp=str(payload["timestamp"]),
        structure_sources_used=[str(x) for x in payload["structure_sources_used"]],
        required_timeframes=[str(x) for x in payload["required_timeframes"]],
        coverage_target_timeframes=[str(x) for x in payload.get("coverage_target_timeframes", payload["required_timeframes"])],
        available_timeframes=[str(x) for x in payload["available_timeframes"]],
        alignment_score=float(payload["alignment_score"]),
        hierarchy_followed=bool(payload["hierarchy_followed"]),
        aligned=bool(payload["aligned"]),
        upstream_l1_continuation_allowed=bool(payload["upstream_l1_continuation_allowed"]),
        freshness_state=FreshnessState(str(payload["freshness_state"])),
        warmup_state=WarmupState(str(payload["warmup_state"])),
        fallback_class=FallbackClass(str(payload.get("fallback_class", FallbackClass.NO_FALLBACK.value))),
        fallback_used=bool(payload.get("fallback_used", False)),
        required_timeframe_missing=bool(payload.get("required_timeframe_missing", False)),
        freshness_governance_hard_fail=bool(payload.get("freshness_governance_hard_fail", False)),
        structure_source_invalid=bool(payload.get("structure_source_invalid", False)),
        timeframe_set_insufficient=bool(payload.get("timeframe_set_insufficient", False)),
        contract_payload_malformed=bool(payload.get("contract_payload_malformed", False)),
        notes=[str(x) for x in payload.get("notes", [])],
        adaptive_pass_threshold=(
            float(payload["alignment_thresholds"].get("pass"))
            if isinstance(payload.get("alignment_thresholds"), dict)
            and payload["alignment_thresholds"].get("pass") is not None
            else None
        ),
        adaptive_warn_threshold=(
            float(payload["alignment_thresholds"].get("warn"))
            if isinstance(payload.get("alignment_thresholds"), dict)
            and payload["alignment_thresholds"].get("warn") is not None
            else None
        ),
        adaptive_regime=(
            str(payload["alignment_thresholds"].get("regime", "UNKNOWN"))
            if isinstance(payload.get("alignment_thresholds"), dict)
            else "UNKNOWN"
        ),
        adaptive_mode=(
            str(payload["alignment_thresholds"].get("mode", "shadow"))
            if isinstance(payload.get("alignment_thresholds"), dict)
            else "shadow"
        ),
    )
