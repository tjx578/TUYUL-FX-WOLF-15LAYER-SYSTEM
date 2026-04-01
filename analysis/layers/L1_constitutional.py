"""
L1 Constitutional Governor — Strict Mode v1.0.0
================================================

Constitutional sub-gate evaluator for L1 context layer.

Implements the frozen L1 spec:
  - Evaluation order: contract → data → freshness → fallback → coherence → compress → emit
  - Critical blockers spec (frozen v1)
  - Fallback legality matrix (frozen v1)
  - Freshness / warmup states
  - Coherence thresholds (frozen baseline v1)
  - Final compression logic (strict mode)

Authority boundary:
  L1 is a context governor only.
  L1 must never emit execution authority.
  Hard legality checks run before coherence scoring.
  status == FAIL implies continuation_allowed == false.

Zone: analysis/ — pure read-only analysis, no execution side-effects.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# §1  FROZEN ENUMS
# ═══════════════════════════════════════════════════════════════════════════


class L1Status(str, Enum):
    """Final compressed status for L1 output."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class FreshnessState(str, Enum):
    """Data freshness classification."""

    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class WarmupState(str, Enum):
    """Warmup completeness classification."""

    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class FallbackClass(str, Enum):
    """Fallback legality classification."""

    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class CoherenceBand(str, Enum):
    """Context coherence band."""

    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


# ═══════════════════════════════════════════════════════════════════════════
# §2  FROZEN CRITICAL BLOCKER CODES
# ═══════════════════════════════════════════════════════════════════════════


class BlockerCode(str, Enum):
    """Critical blocker codes (frozen v1)."""

    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"
    REQUIRED_PRODUCER_MISSING = "REQUIRED_PRODUCER_MISSING"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    SNAPSHOT_INVALID_OR_CORRUPT = "SNAPSHOT_INVALID_OR_CORRUPT"
    SESSION_STATE_INVALID = "SESSION_STATE_INVALID"
    REGIME_SERVICE_UNAVAILABLE_NO_LEGAL_FALLBACK = (
        "REGIME_SERVICE_UNAVAILABLE_NO_LEGAL_FALLBACK"
    )
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    LOW_CONTEXT_COHERENCE = "LOW_CONTEXT_COHERENCE"


# ═══════════════════════════════════════════════════════════════════════════
# §3  FROZEN THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════════


# Coherence thresholds (frozen baseline v1)
COHERENCE_HIGH_GTE = 0.85
COHERENCE_MID_GTE = 0.65
# LOW < 0.65

# Warmup minimum bars per timeframe
WARMUP_MIN_BARS: dict[str, int] = {
    "H1": 20,
    "H4": 10,
    "D1": 5,
    "W1": 5,
    "MN": 2,
}

# Freshness — maximum age in seconds before state transitions
FRESHNESS_STALE_THRESHOLD_SEC = 3600  # 1 hour → STALE_PRESERVED
FRESHNESS_DEGRADED_THRESHOLD_SEC = 7200  # 2 hours → DEGRADED


# ═══════════════════════════════════════════════════════════════════════════
# §4  SUB-GATE INPUT CONTRACT
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class L1GateInput:
    """Input contract for L1 constitutional evaluation.

    Collected from LiveContextBus, governance gate, and analysis result.
    """

    # From analyze_context() output
    analysis_result: dict[str, Any]

    # From LiveContextBus / governance
    symbol: str = ""
    feed_timestamp: float | None = None
    candle_counts: dict[str, int] = field(default_factory=dict)
    producer_available: bool = True
    snapshot_valid: bool = True
    session_state_valid: bool = True
    regime_service_available: bool = True
    fallback_used: bool = False
    fallback_source: str = ""  # e.g., "preserved_snapshot", "substitute_provider"
    fallback_approved: bool = False
    context_sources_used: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# §5  SUB-GATE EVALUATORS (frozen evaluation order)
# ═══════════════════════════════════════════════════════════════════════════


def _check_contract_integrity(inp: L1GateInput) -> list[str]:
    """Step 1: Check contract payload integrity.

    Returns list of blocker codes (empty = pass).
    """
    blockers: list[str] = []
    ar = inp.analysis_result

    if not isinstance(ar, dict):
        blockers.append(BlockerCode.CONTRACT_PAYLOAD_MALFORMED)
        return blockers

    # Required fields in analysis result
    required_keys = {"regime", "context_coherence", "valid"}
    missing = required_keys - set(ar.keys())
    if missing:
        blockers.append(BlockerCode.CONTRACT_PAYLOAD_MALFORMED)

    return blockers


def _check_data_availability(inp: L1GateInput) -> list[str]:
    """Step 2: L1-A Data Availability Gate.

    Ensures required producers/snapshots exist.
    """
    blockers: list[str] = []

    if not inp.producer_available:
        blockers.append(BlockerCode.REQUIRED_PRODUCER_MISSING)

    if not inp.snapshot_valid:
        blockers.append(BlockerCode.SNAPSHOT_INVALID_OR_CORRUPT)

    if not inp.session_state_valid:
        blockers.append(BlockerCode.SESSION_STATE_INVALID)

    return blockers


def _eval_freshness(inp: L1GateInput) -> FreshnessState:
    """Step 3a: Evaluate feed freshness state."""
    if not inp.producer_available:
        return FreshnessState.NO_PRODUCER

    if inp.feed_timestamp is None:
        # No feed timestamp available — treat as degraded
        return FreshnessState.DEGRADED

    age_sec = datetime.now(UTC).timestamp() - inp.feed_timestamp

    if age_sec <= FRESHNESS_STALE_THRESHOLD_SEC:
        return FreshnessState.FRESH

    if age_sec <= FRESHNESS_DEGRADED_THRESHOLD_SEC:
        return FreshnessState.STALE_PRESERVED

    return FreshnessState.DEGRADED


def _eval_warmup(inp: L1GateInput) -> WarmupState:
    """Step 3b: Evaluate warmup completeness."""
    if not inp.candle_counts:
        # No candle count info — check analysis result bar count
        ar = inp.analysis_result
        if not ar.get("valid", False) and "need" in str(ar.get("reason", "")):
            return WarmupState.INSUFFICIENT
        return WarmupState.READY

    total_required = 0
    total_available = 0
    critical_missing = False

    for tf, min_bars in WARMUP_MIN_BARS.items():
        available = inp.candle_counts.get(tf, 0)
        total_required += min_bars
        total_available += min(available, min_bars)

        # H1 is critical — must meet minimum
        if tf == "H1" and available < min_bars:
            critical_missing = True

    if critical_missing:
        return WarmupState.INSUFFICIENT

    completeness = total_available / total_required if total_required > 0 else 0.0

    if completeness >= 0.90:
        return WarmupState.READY

    if completeness >= 0.60:
        return WarmupState.PARTIAL

    return WarmupState.INSUFFICIENT


def _check_freshness_warmup(
    freshness: FreshnessState,
    warmup: WarmupState,
) -> list[str]:
    """Step 3: L1-B Freshness/Warmup Gate.

    Checks freshness and warmup states for hard failures.
    """
    blockers: list[str] = []

    if freshness == FreshnessState.NO_PRODUCER:
        blockers.append(BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL)

    if warmup == WarmupState.INSUFFICIENT:
        blockers.append(BlockerCode.WARMUP_INSUFFICIENT)

    return blockers


def _eval_fallback(inp: L1GateInput) -> FallbackClass:
    """Step 4: Evaluate fallback legality class."""
    if not inp.fallback_used:
        return FallbackClass.NO_FALLBACK

    if not inp.fallback_approved:
        return FallbackClass.ILLEGAL_FALLBACK

    # Determine fallback class from source
    src = inp.fallback_source.lower()

    if src in ("substitute_provider", "legal_primary_substitute"):
        return FallbackClass.LEGAL_PRIMARY_SUBSTITUTE

    if src in ("preserved_snapshot", "emergency_preserve", "legal_emergency_preserve"):
        return FallbackClass.LEGAL_EMERGENCY_PRESERVE

    # Unknown fallback source — treat as illegal
    return FallbackClass.ILLEGAL_FALLBACK


def _check_fallback_legality(
    fallback_class: FallbackClass,
    producer_missing: bool,
) -> list[str]:
    """Step 4 blocker check."""
    blockers: list[str] = []

    if fallback_class == FallbackClass.ILLEGAL_FALLBACK:
        blockers.append(BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED)

    if (
        fallback_class == FallbackClass.NO_FALLBACK
        and producer_missing
    ):
        blockers.append(BlockerCode.REQUIRED_PRODUCER_MISSING)

    if (
        not producer_missing
        and fallback_class == FallbackClass.NO_FALLBACK
    ):
        # Check if regime service is down with no legal fallback
        pass  # handled by data availability gate

    return blockers


def _derive_coherence_band(coherence_score: float) -> CoherenceBand:
    """Step 6: Derive coherence band from score."""
    if coherence_score >= COHERENCE_HIGH_GTE:
        return CoherenceBand.HIGH

    if coherence_score >= COHERENCE_MID_GTE:
        return CoherenceBand.MID

    return CoherenceBand.LOW


# ═══════════════════════════════════════════════════════════════════════════
# §6  FINAL COMPRESSION LOGIC (frozen strict mode)
# ═══════════════════════════════════════════════════════════════════════════


def _compress_status(
    blocker_codes: list[str],
    freshness: FreshnessState,
    warmup: WarmupState,
    coherence_band: CoherenceBand,
    fallback_class: FallbackClass,
) -> L1Status:
    """Step 7: Final compression logic (strict mode, frozen v1).

    PASS only for cleanest envelope.
    WARN for legal but degraded.
    FAIL for everything outside legal envelope.
    """
    # Any critical blocker → FAIL
    if blocker_codes:
        return L1Status.FAIL

    # Freshness hard fail
    if freshness == FreshnessState.NO_PRODUCER:
        return L1Status.FAIL

    # Warmup hard fail
    if warmup == WarmupState.INSUFFICIENT:
        return L1Status.FAIL

    # Coherence hard fail
    if coherence_band == CoherenceBand.LOW:
        return L1Status.FAIL

    # Illegal fallback hard fail
    if fallback_class == FallbackClass.ILLEGAL_FALLBACK:
        return L1Status.FAIL

    # Clean PASS check
    clean_pass = (
        freshness == FreshnessState.FRESH
        and warmup == WarmupState.READY
        and coherence_band in (CoherenceBand.HIGH, CoherenceBand.MID)
        and fallback_class
        in (FallbackClass.NO_FALLBACK, FallbackClass.LEGAL_PRIMARY_SUBSTITUTE)
    )

    if clean_pass:
        return L1Status.PASS

    # Legal but degraded → WARN
    degraded_ok = (
        freshness
        in (
            FreshnessState.STALE_PRESERVED,
            FreshnessState.DEGRADED,
            FreshnessState.FRESH,
        )
        and warmup in (WarmupState.READY, WarmupState.PARTIAL)
        and coherence_band in (CoherenceBand.HIGH, CoherenceBand.MID)
        and fallback_class
        in (
            FallbackClass.NO_FALLBACK,
            FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
            FallbackClass.LEGAL_EMERGENCY_PRESERVE,
        )
    )

    if degraded_ok:
        return L1Status.WARN

    # Catch-all → FAIL
    return L1Status.FAIL


# ═══════════════════════════════════════════════════════════════════════════
# §7  CONTINUATION LEGALITY
# ═══════════════════════════════════════════════════════════════════════════


def _set_continuation(status: L1Status) -> tuple[bool, list[str]]:
    """Step 8: Set continuation legality.

    FAIL → continuation_allowed=false, next_legal_targets=[]
    PASS/WARN → continuation_allowed=true, next_legal_targets=["L2"]
    """
    if status == L1Status.FAIL:
        return False, []
    return True, ["L2"]


# ═══════════════════════════════════════════════════════════════════════════
# §8  FEATURE HASH
# ═══════════════════════════════════════════════════════════════════════════


def _compute_feature_hash(
    regime: str,
    dominant_force: str,
    status: str,
    coherence_score: float,
) -> str:
    """Deterministic feature hash for replay/backtest identification."""
    raw = f"L1_{regime}_{dominant_force}_{status}_{int(coherence_score * 100)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════════════
# §9  MAIN EVALUATOR — evaluate_l1_constitutional()
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class L1ConstitutionalResult:
    """Canonical L1 output contract (frozen v1)."""

    layer: str = "L1"
    layer_version: str = "1.0.0"
    timestamp: str = ""
    input_ref: str = ""

    # Compression output
    status: str = "FAIL"
    continuation_allowed: bool = False

    # Gate outputs
    blocker_codes: list[str] = field(default_factory=list)
    warning_codes: list[str] = field(default_factory=list)
    fallback_class: str = "NO_FALLBACK"
    freshness_state: str = "FRESH"
    warmup_state: str = "READY"

    # Coherence
    coherence_score: float = 0.0
    coherence_band: str = "LOW"

    # Features (from analysis result)
    features: dict[str, Any] = field(default_factory=dict)

    # Routing
    routing: dict[str, Any] = field(default_factory=dict)

    # Audit trail
    audit: dict[str, Any] = field(default_factory=dict)

    # Backward compatibility — existing fields from analyze_context()
    valid: bool = False
    regime: str = "UNKNOWN"
    dominant_force: str = "NEUTRAL"
    regime_probability: float = 0.0
    context_coherence: float = 0.0
    volatility_level: str = "UNKNOWN"
    volatility_percentile: float = 0.0
    entropy_score: float = 0.0
    regime_confidence: float = 0.0
    csi: float = 0.0
    market_alignment: str = "NEUTRAL"
    session: str = "UNKNOWN"
    session_multiplier: float = 0.0
    pair: str = ""
    asset_class: str = "FX"
    feature_spread: float = 0.0
    feature_atr_frac: float = 0.0
    feature_hurst: float = 0.5
    feature_zscore: float = 0.0
    ema20: float = 0.0
    ema50: float = 0.0
    ema9: float = 0.0
    atr: float = 0.0
    atr_pct: float = 0.0
    momentum_direction: str = "NEUTRAL"
    momentum_magnitude: float = 0.0
    reason: str = ""

    # Hurst enrichment (optional)
    hurst_regime: str | None = None
    hurst_confidence: float | None = None
    hurst_exponent: float | None = None
    hurst_volatility_state: str | None = None
    hurst_momentum: float | None = None
    regime_agreement: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None optional fields."""
        result: dict[str, Any] = {
            "layer": self.layer,
            "layer_version": self.layer_version,
            "timestamp": self.timestamp,
            "input_ref": self.input_ref,
            "status": self.status,
            "continuation_allowed": self.continuation_allowed,
            "blocker_codes": self.blocker_codes,
            "warning_codes": self.warning_codes,
            "fallback_class": self.fallback_class,
            "freshness_state": self.freshness_state,
            "warmup_state": self.warmup_state,
            "coherence_score": self.coherence_score,
            "coherence_band": self.coherence_band,
            "features": self.features,
            "routing": self.routing,
            "audit": self.audit,
            # Backward compat
            "valid": self.valid,
            "regime": self.regime,
            "dominant_force": self.dominant_force,
            "regime_probability": self.regime_probability,
            "context_coherence": self.context_coherence,
            "volatility_level": self.volatility_level,
            "volatility_percentile": self.volatility_percentile,
            "entropy_score": self.entropy_score,
            "regime_confidence": self.regime_confidence,
            "csi": self.csi,
            "market_alignment": self.market_alignment,
            "session": self.session,
            "session_multiplier": self.session_multiplier,
            "pair": self.pair,
            "asset_class": self.asset_class,
            "feature_spread": self.feature_spread,
            "feature_atr_frac": self.feature_atr_frac,
            "feature_hurst": self.feature_hurst,
            "feature_zscore": self.feature_zscore,
            "ema20": self.ema20,
            "ema50": self.ema50,
            "ema9": self.ema9,
            "atr": self.atr,
            "atr_pct": self.atr_pct,
            "momentum_direction": self.momentum_direction,
            "momentum_magnitude": self.momentum_magnitude,
            "reason": self.reason,
        }

        # Optional hurst fields
        for key in (
            "hurst_regime",
            "hurst_confidence",
            "hurst_exponent",
            "hurst_volatility_state",
            "hurst_momentum",
            "regime_agreement",
        ):
            val = getattr(self, key)
            if val is not None:
                result[key] = val

        return result


def evaluate_l1_constitutional(inp: L1GateInput) -> L1ConstitutionalResult:
    """Main L1 constitutional evaluator (frozen evaluation order v1).

    Evaluation order (frozen):
      1. check_contract_integrity
      2. check_data_availability_gate
      3. check_freshness_warmup_gate
      4. check_fallback_legality_gate
      5. compute_context_coherence (from analysis result)
      6. derive_coherence_band
      7. compress_status
      8. set_continuation_legality
      9. emit_contract
    """
    ar = inp.analysis_result
    now_iso = datetime.now(UTC).isoformat()
    input_ref = f"{inp.symbol}_H1_run_{now_iso}"
    rule_hits: list[str] = []
    warning_codes: list[str] = []

    # ── Step 1: Contract integrity ────────────────────────────────
    blocker_codes = _check_contract_integrity(inp)
    if blocker_codes:
        rule_hits.append("contract_integrity_failed")
        logger.warning(
            "[L1 Constitutional] %s contract integrity FAIL: %s",
            inp.symbol,
            blocker_codes,
        )
        return _build_fail_result(
            inp, blocker_codes, warning_codes, rule_hits, now_iso, input_ref,
        )

    # ── Step 2: Data availability ─────────────────────────────────
    data_blockers = _check_data_availability(inp)
    blocker_codes.extend(data_blockers)
    if data_blockers:
        rule_hits.append("data_availability_failed")
        logger.warning(
            "[L1 Constitutional] %s data availability FAIL: %s",
            inp.symbol,
            data_blockers,
        )
        return _build_fail_result(
            inp, blocker_codes, warning_codes, rule_hits, now_iso, input_ref,
        )

    # ── Step 3: Freshness & warmup ────────────────────────────────
    freshness = _eval_freshness(inp)
    warmup = _eval_warmup(inp)
    fw_blockers = _check_freshness_warmup(freshness, warmup)
    blocker_codes.extend(fw_blockers)

    if freshness == FreshnessState.STALE_PRESERVED:
        warning_codes.append("STALE_PRESERVED_CONTEXT")
        rule_hits.append(f"freshness_state={freshness.value}")
    elif freshness == FreshnessState.DEGRADED:
        warning_codes.append("DEGRADED_FRESHNESS")
        rule_hits.append(f"freshness_state={freshness.value}")

    if warmup == WarmupState.PARTIAL:
        warning_codes.append("PARTIAL_WARMUP")
        rule_hits.append(f"warmup_state={warmup.value}")

    if fw_blockers:
        rule_hits.append("freshness_warmup_gate_failed")
        return _build_fail_result(
            inp, blocker_codes, warning_codes, rule_hits, now_iso, input_ref,
            freshness=freshness, warmup=warmup,
        )

    # ── Step 4: Fallback legality ─────────────────────────────────
    fallback_class = _eval_fallback(inp)
    fb_blockers = _check_fallback_legality(
        fallback_class, not inp.producer_available,
    )
    blocker_codes.extend(fb_blockers)

    if fallback_class != FallbackClass.NO_FALLBACK:
        rule_hits.append(f"fallback_class={fallback_class.value}")

    if fb_blockers:
        rule_hits.append("fallback_legality_failed")
        return _build_fail_result(
            inp, blocker_codes, warning_codes, rule_hits, now_iso, input_ref,
            freshness=freshness, warmup=warmup, fallback_class=fallback_class,
        )

    # ── Step 5: Context coherence (from analysis result) ──────────
    coherence_score = float(ar.get("context_coherence", 0.0))

    # ── Step 6: Derive coherence band ─────────────────────────────
    coherence_band = _derive_coherence_band(coherence_score)
    rule_hits.append(f"coherence_band={coherence_band.value}")

    if coherence_band == CoherenceBand.LOW:
        blocker_codes.append(BlockerCode.LOW_CONTEXT_COHERENCE)

    # ── Step 7: Compress status ───────────────────────────────────
    status = _compress_status(
        blocker_codes, freshness, warmup, coherence_band, fallback_class,
    )
    rule_hits.append(f"compressed_status={status.value}")

    # ── Step 8: Continuation legality ─────────────────────────────
    continuation_allowed, next_legal_targets = _set_continuation(status)

    # ── Step 9: Emit contract ─────────────────────────────────────
    regime = str(ar.get("regime", "UNKNOWN"))
    dominant_force = str(ar.get("dominant_force", "NEUTRAL"))

    feature_hash = _compute_feature_hash(
        regime, dominant_force, status.value, coherence_score,
    )

    result = L1ConstitutionalResult(
        timestamp=now_iso,
        input_ref=input_ref,
        status=status.value,
        continuation_allowed=continuation_allowed,
        blocker_codes=[str(b) for b in blocker_codes],
        warning_codes=warning_codes,
        fallback_class=fallback_class.value,
        freshness_state=freshness.value,
        warmup_state=warmup.value,
        coherence_score=coherence_score,
        coherence_band=coherence_band.value,
        features={
            "market_regime": regime,
            "dominant_force": dominant_force,
            "context_sources_used": inp.context_sources_used,
            "feature_vector": {
                "context_coherence": coherence_score,
                "session_state": str(ar.get("session", "UNKNOWN")),
                "regime_probability": float(ar.get("regime_probability", 0.0)),
                "feature_spread": float(ar.get("feature_spread", 0.0)),
                "feature_atr_frac": float(ar.get("feature_atr_frac", 0.0)),
                "feature_hurst": float(ar.get("feature_hurst", 0.5)),
                "feature_zscore": float(ar.get("feature_zscore", 0.0)),
            },
            "feature_hash": feature_hash,
        },
        routing={
            "source_used": inp.context_sources_used,
            "fallback_used": inp.fallback_used,
            "next_legal_targets": next_legal_targets,
        },
        audit={
            "rule_hits": rule_hits,
            "blocker_triggered": len(blocker_codes) > 0,
            "notes": _build_audit_notes(
                status, freshness, warmup, coherence_band, fallback_class,
            ),
        },
        # Backward compatibility pass-through
        valid=continuation_allowed,
        regime=regime,
        dominant_force=dominant_force,
        regime_probability=float(ar.get("regime_probability", 0.0)),
        context_coherence=coherence_score,
        volatility_level=str(ar.get("volatility_level", "UNKNOWN")),
        volatility_percentile=float(ar.get("volatility_percentile", 0.0)),
        entropy_score=float(ar.get("entropy_score", 0.0)),
        regime_confidence=float(ar.get("regime_confidence", 0.0)),
        csi=float(ar.get("csi", 0.0)),
        market_alignment=str(ar.get("market_alignment", "NEUTRAL")),
        session=str(ar.get("session", "UNKNOWN")),
        session_multiplier=float(ar.get("session_multiplier", 0.0)),
        pair=inp.symbol,
        asset_class=str(ar.get("asset_class", "FX")),
        feature_spread=float(ar.get("feature_spread", 0.0)),
        feature_atr_frac=float(ar.get("feature_atr_frac", 0.0)),
        feature_hurst=float(ar.get("feature_hurst", 0.5)),
        feature_zscore=float(ar.get("feature_zscore", 0.0)),
        ema20=float(ar.get("ema20", 0.0)),
        ema50=float(ar.get("ema50", 0.0)),
        ema9=float(ar.get("ema9", 0.0)),
        atr=float(ar.get("atr", 0.0)),
        atr_pct=float(ar.get("atr_pct", 0.0)),
        momentum_direction=str(ar.get("momentum_direction", "NEUTRAL")),
        momentum_magnitude=float(ar.get("momentum_magnitude", 0.0)),
        reason=str(ar.get("reason", "")),
        hurst_regime=ar.get("hurst_regime"),
        hurst_confidence=ar.get("hurst_confidence"),
        hurst_exponent=ar.get("hurst_exponent"),
        hurst_volatility_state=ar.get("hurst_volatility_state"),
        hurst_momentum=ar.get("hurst_momentum"),
        regime_agreement=ar.get("regime_agreement"),
    )

    logger.info(
        "[L1 Constitutional] %s status=%s cont=%s coherence=%.4f band=%s "
        "freshness=%s warmup=%s fallback=%s blockers=%d warnings=%d",
        inp.symbol,
        status.value,
        continuation_allowed,
        coherence_score,
        coherence_band.value,
        freshness.value,
        warmup.value,
        fallback_class.value,
        len(blocker_codes),
        len(warning_codes),
    )

    return result


# ═══════════════════════════════════════════════════════════════════════════
# §10  HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _build_fail_result(
    inp: L1GateInput,
    blocker_codes: list[str],
    warning_codes: list[str],
    rule_hits: list[str],
    now_iso: str,
    input_ref: str,
    *,
    freshness: FreshnessState = FreshnessState.NO_PRODUCER,
    warmup: WarmupState = WarmupState.INSUFFICIENT,
    fallback_class: FallbackClass = FallbackClass.NO_FALLBACK,
) -> L1ConstitutionalResult:
    """Build a FAIL result with early exit."""
    ar = inp.analysis_result if isinstance(inp.analysis_result, dict) else {}

    return L1ConstitutionalResult(
        timestamp=now_iso,
        input_ref=input_ref,
        status=L1Status.FAIL.value,
        continuation_allowed=False,
        blocker_codes=[str(b) for b in blocker_codes],
        warning_codes=warning_codes,
        fallback_class=fallback_class.value,
        freshness_state=freshness.value,
        warmup_state=warmup.value,
        coherence_score=float(ar.get("context_coherence", 0.0)),
        coherence_band=CoherenceBand.LOW.value,
        features={
            "market_regime": str(ar.get("regime", "UNKNOWN")),
            "dominant_force": str(ar.get("dominant_force", "NEUTRAL")),
            "context_sources_used": inp.context_sources_used,
            "feature_vector": {},
            "feature_hash": "",
        },
        routing={
            "source_used": inp.context_sources_used,
            "fallback_used": inp.fallback_used,
            "next_legal_targets": [],
        },
        audit={
            "rule_hits": rule_hits,
            "blocker_triggered": True,
            "notes": [f"Hard fail: {', '.join(str(b) for b in blocker_codes)}"],
        },
        valid=False,
        regime=str(ar.get("regime", "UNKNOWN")),
        dominant_force=str(ar.get("dominant_force", "NEUTRAL")),
        pair=inp.symbol,
        reason=f"L1 constitutional FAIL: {', '.join(str(b) for b in blocker_codes)}",
    )


def _build_audit_notes(
    status: L1Status,
    freshness: FreshnessState,
    warmup: WarmupState,
    coherence_band: CoherenceBand,
    fallback_class: FallbackClass,
) -> list[str]:
    """Build human-readable audit notes."""
    notes: list[str] = []

    if status == L1Status.PASS:
        notes.append("Context legally clean and propagable.")
    elif status == L1Status.WARN:
        notes.append("Context legally degraded but still propagable.")
    else:
        notes.append("Context failed legality checks — propagation blocked.")

    if freshness in (FreshnessState.STALE_PRESERVED, FreshnessState.DEGRADED):
        notes.append(f"Feed freshness degraded: {freshness.value}.")

    if warmup == WarmupState.PARTIAL:
        notes.append("Warmup partially complete.")

    if fallback_class == FallbackClass.LEGAL_EMERGENCY_PRESERVE:
        notes.append("Running on preserved snapshot fallback.")
    elif fallback_class == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
        notes.append("Using approved substitute data source.")

    return notes
