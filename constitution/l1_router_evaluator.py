from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class L1Status(str, Enum):
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
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class CoherenceBand(str, Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class BlockerCode(str, Enum):
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"
    REQUIRED_PRODUCER_MISSING = "REQUIRED_PRODUCER_MISSING"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    SNAPSHOT_INVALID_OR_CORRUPT = "SNAPSHOT_INVALID_OR_CORRUPT"
    SESSION_STATE_INVALID = "SESSION_STATE_INVALID"
    REGIME_SERVICE_UNAVAILABLE_NO_LEGAL_FALLBACK = "REGIME_SERVICE_UNAVAILABLE_NO_LEGAL_FALLBACK"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"


@dataclass(frozen=True)
class L1Thresholds:
    high_gte: float = 0.85
    mid_gte: float = 0.65

    def band_for(self, coherence_score: float) -> CoherenceBand:
        if coherence_score >= self.high_gte:
            return CoherenceBand.HIGH
        if coherence_score >= self.mid_gte:
            return CoherenceBand.MID
        return CoherenceBand.LOW


@dataclass(frozen=True)
class L1Input:
    input_ref: str
    timestamp: str
    context_sources_used: tuple[str, ...]
    market_regime: str
    dominant_force: str
    coherence_score: float
    freshness_state: FreshnessState
    warmup_state: WarmupState
    fallback_class: FallbackClass = FallbackClass.NO_FALLBACK
    fallback_used: bool = False

    # Governance / dependency flags
    required_producer_missing: bool = False
    freshness_governance_hard_fail: bool = False
    snapshot_invalid_or_corrupt: bool = False
    session_state_invalid: bool = False
    regime_service_unavailable: bool = False
    contract_payload_malformed: bool = False

    # Optional audit/context notes
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class L1EvaluationResult:
    layer: str = "L1"
    layer_version: str = "1.0.0"
    timestamp: str = ""
    input_ref: str = ""
    status: L1Status = L1Status.FAIL
    continuation_allowed: bool = False
    blocker_codes: tuple[str, ...] = ()
    warning_codes: tuple[str, ...] = ()
    fallback_class: FallbackClass = FallbackClass.NO_FALLBACK
    freshness_state: FreshnessState = FreshnessState.NO_PRODUCER
    warmup_state: WarmupState = WarmupState.INSUFFICIENT
    coherence_band: CoherenceBand = CoherenceBand.LOW
    coherence_score: float = 0.0
    features: dict[str, Any] = field(default_factory=dict)
    routing: dict[str, Any] = field(default_factory=dict)
    audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class L1RouterEvaluator:
    """Strict constitutional evaluator for L1."""

    def __init__(self, thresholds: L1Thresholds | None = None) -> None:
        self.thresholds = thresholds or L1Thresholds()

    def evaluate(self, payload: L1Input) -> L1EvaluationResult:
        blocker_codes = list(self._collect_blockers(payload))
        warning_codes = list(self._collect_warnings(payload))
        rule_hits: list[str] = []

        coherence_band = self.thresholds.band_for(payload.coherence_score)
        rule_hits.append(f"coherence_band={coherence_band.value}")
        rule_hits.append(f"freshness_state={payload.freshness_state.value}")
        rule_hits.append(f"warmup_state={payload.warmup_state.value}")
        rule_hits.append(f"fallback_class={payload.fallback_class.value}")

        status = self._compress_status(payload, coherence_band, blocker_codes, rule_hits)

        continuation_allowed = status in (L1Status.PASS, L1Status.WARN)
        next_legal_targets = ["L2"] if continuation_allowed else []

        # Warn caps based on degraded-but-legal conditions
        if status == L1Status.WARN:
            if payload.freshness_state == FreshnessState.STALE_PRESERVED:
                warning_codes.append("STALE_PRESERVED_CONTEXT")
            elif payload.freshness_state == FreshnessState.DEGRADED:
                warning_codes.append("DEGRADED_CONTEXT")
            if payload.warmup_state == WarmupState.PARTIAL:
                warning_codes.append("PARTIAL_WARMUP")
            if payload.fallback_class == FallbackClass.LEGAL_EMERGENCY_PRESERVE:
                warning_codes.append("EMERGENCY_PRESERVE_FALLBACK")
            if coherence_band == CoherenceBand.LOW:
                warning_codes.append("LOW_COHERENCE_NON_TREND")

        warning_codes = sorted(set(warning_codes))

        return L1EvaluationResult(
            timestamp=payload.timestamp,
            input_ref=payload.input_ref,
            status=status,
            continuation_allowed=continuation_allowed,
            blocker_codes=tuple(blocker_codes),
            warning_codes=tuple(warning_codes),
            fallback_class=payload.fallback_class,
            freshness_state=payload.freshness_state,
            warmup_state=payload.warmup_state,
            coherence_band=coherence_band,
            coherence_score=round(payload.coherence_score, 6),
            features={
                "market_regime": payload.market_regime,
                "dominant_force": payload.dominant_force,
                "context_sources_used": list(payload.context_sources_used),
            },
            routing={
                "source_used": list(payload.context_sources_used),
                "fallback_used": payload.fallback_used,
                "next_legal_targets": next_legal_targets,
            },
            audit={
                "rule_hits": rule_hits,
                "blocker_triggered": bool(blocker_codes),
                "notes": list(payload.notes),
            },
        )

    def _collect_blockers(self, payload: L1Input) -> tuple[str, ...]:
        blockers: list[str] = []

        if payload.contract_payload_malformed:
            blockers.append(BlockerCode.CONTRACT_PAYLOAD_MALFORMED.value)

        if payload.required_producer_missing:
            blockers.append(BlockerCode.REQUIRED_PRODUCER_MISSING.value)

        if payload.freshness_governance_hard_fail:
            blockers.append(BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL.value)

        if payload.warmup_state == WarmupState.INSUFFICIENT:
            blockers.append(BlockerCode.WARMUP_INSUFFICIENT.value)

        if payload.snapshot_invalid_or_corrupt:
            blockers.append(BlockerCode.SNAPSHOT_INVALID_OR_CORRUPT.value)

        if payload.session_state_invalid:
            blockers.append(BlockerCode.SESSION_STATE_INVALID.value)

        if (
            payload.regime_service_unavailable
            and payload.fallback_class in (FallbackClass.NO_FALLBACK, FallbackClass.ILLEGAL_FALLBACK)
        ):
            blockers.append(BlockerCode.REGIME_SERVICE_UNAVAILABLE_NO_LEGAL_FALLBACK.value)

        if payload.fallback_class == FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED.value)

        if payload.freshness_state == FreshnessState.NO_PRODUCER:  # noqa: SIM102
            # This is also a hard fail by spec even if producer flags were not populated.
            if BlockerCode.REQUIRED_PRODUCER_MISSING.value not in blockers:
                blockers.append(BlockerCode.REQUIRED_PRODUCER_MISSING.value)

        return tuple(sorted(set(blockers)))

    def _collect_warnings(self, payload: L1Input) -> tuple[str, ...]:
        warnings: list[str] = []
        if payload.fallback_used and payload.fallback_class == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
            warnings.append("PRIMARY_SUBSTITUTE_USED")
        return tuple(warnings)

    def _compress_status(
        self,
        payload: L1Input,
        coherence_band: CoherenceBand,
        blocker_codes: list[str],
        rule_hits: list[str],
    ) -> L1Status:
        if blocker_codes:
            rule_hits.append("status=FAIL:blocker")
            return L1Status.FAIL

        if payload.freshness_state == FreshnessState.NO_PRODUCER:
            rule_hits.append("status=FAIL:no_producer")
            return L1Status.FAIL

        if payload.warmup_state == WarmupState.INSUFFICIENT:
            rule_hits.append("status=FAIL:warmup_insufficient")
            return L1Status.FAIL

        if coherence_band == CoherenceBand.LOW:
            # Regime-adaptive: LOW coherence is hard FAIL only for TREND regimes.
            # RANGE/TRANSITION tolerate lower coherence → WARN, not FAIL.
            if payload.market_regime in ("TREND_UP", "TREND_DOWN"):
                rule_hits.append("status=FAIL:low_coherence_trend")
                return L1Status.FAIL
            rule_hits.append("low_coherence_downgraded_to_warn")

        if payload.fallback_class == FallbackClass.ILLEGAL_FALLBACK:
            rule_hits.append("status=FAIL:illegal_fallback")
            return L1Status.FAIL

        clean_pass = (
            payload.freshness_state == FreshnessState.FRESH
            and payload.warmup_state == WarmupState.READY
            and coherence_band in (CoherenceBand.HIGH, CoherenceBand.MID)
            and payload.fallback_class in (FallbackClass.NO_FALLBACK, FallbackClass.LEGAL_PRIMARY_SUBSTITUTE)
        )
        if clean_pass:
            rule_hits.append("status=PASS:clean_envelope")
            return L1Status.PASS

        legal_warn = (
            payload.freshness_state in (
                FreshnessState.STALE_PRESERVED,
                FreshnessState.DEGRADED,
                FreshnessState.FRESH,
            )
            and payload.warmup_state in (WarmupState.READY, WarmupState.PARTIAL)
            and coherence_band in (CoherenceBand.HIGH, CoherenceBand.MID, CoherenceBand.LOW)
            and payload.fallback_class in (
                FallbackClass.NO_FALLBACK,
                FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
                FallbackClass.LEGAL_EMERGENCY_PRESERVE,
            )
        )
        if legal_warn:
            rule_hits.append("status=WARN:degraded_legal_envelope")
            return L1Status.WARN

        rule_hits.append("status=FAIL:outside_legal_envelope")
        return L1Status.FAIL


def build_l1_input_from_dict(payload: dict[str, Any]) -> L1Input:
    """Adapter from generic JSON/runtime payload to typed L1Input."""
    required = [
        "input_ref",
        "timestamp",
        "context_sources_used",
        "market_regime",
        "dominant_force",
        "coherence_score",
        "freshness_state",
        "warmup_state",
    ]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Missing required L1 payload fields: {', '.join(missing)}")

    ctx_sources = payload["context_sources_used"]
    if isinstance(ctx_sources, list):
        ctx_sources = tuple(ctx_sources)

    notes = payload.get("notes", ())
    if isinstance(notes, list):
        notes = tuple(notes)

    return L1Input(
        input_ref=str(payload["input_ref"]),
        timestamp=str(payload["timestamp"]),
        context_sources_used=ctx_sources,
        market_regime=str(payload["market_regime"]),
        dominant_force=str(payload["dominant_force"]),
        coherence_score=float(payload["coherence_score"]),
        freshness_state=FreshnessState(str(payload["freshness_state"])),
        warmup_state=WarmupState(str(payload["warmup_state"])),
        fallback_class=FallbackClass(str(payload.get("fallback_class", FallbackClass.NO_FALLBACK.value))),
        fallback_used=bool(payload.get("fallback_used", False)),
        required_producer_missing=bool(payload.get("required_producer_missing", False)),
        freshness_governance_hard_fail=bool(payload.get("freshness_governance_hard_fail", False)),
        snapshot_invalid_or_corrupt=bool(payload.get("snapshot_invalid_or_corrupt", False)),
        session_state_invalid=bool(payload.get("session_state_invalid", False)),
        regime_service_unavailable=bool(payload.get("regime_service_unavailable", False)),
        contract_payload_malformed=bool(payload.get("contract_payload_malformed", False)),
        notes=notes,
    )


def example_payloads() -> list[L1Input]:
    """Small demo set for quick replay/testing."""
    return [
        L1Input(
            input_ref="EURUSD_H1_run_001",
            timestamp="2026-03-28T10:15:00+07:00",
            context_sources_used=("regime_service", "session_state"),
            market_regime="TRENDING",
            dominant_force="MOMENTUM",
            coherence_score=0.91,
            freshness_state=FreshnessState.FRESH,
            warmup_state=WarmupState.READY,
        ),
        L1Input(
            input_ref="EURUSD_H1_run_002",
            timestamp="2026-03-28T10:16:00+07:00",
            context_sources_used=("preserved_snapshot",),
            market_regime="TRENDING",
            dominant_force="MOMENTUM",
            coherence_score=0.74,
            freshness_state=FreshnessState.STALE_PRESERVED,
            warmup_state=WarmupState.PARTIAL,
            fallback_class=FallbackClass.LEGAL_EMERGENCY_PRESERVE,
            fallback_used=True,
            notes=("Context legally degraded but still propagable.",),
        ),
        L1Input(
            input_ref="EURUSD_H1_run_003",
            timestamp="2026-03-28T10:17:00+07:00",
            context_sources_used=(),
            market_regime="UNKNOWN",
            dominant_force="MIXED",
            coherence_score=0.93,
            freshness_state=FreshnessState.NO_PRODUCER,
            warmup_state=WarmupState.INSUFFICIENT,
            required_producer_missing=True,
        ),
    ]
