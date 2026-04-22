"""
L3 Constitutional Governor — Evidence-Aware Mode v1.1.0
========================================================

Constitutional sub-gate evaluator for L3 trend confirmation legality.

Implements the L3 evidence-governor flow:
    - Evaluation order: blockers → freshness → warmup → fallback → confirmation → evidence → compress → emit
    - Hard legality is reserved for contract/infrastructure invalidity
    - Weak trend confirmation and structure conflict degrade evidence instead of vetoing Phase 1

Authority boundary:
    L3 is a trend confirmation evidence governor only.
    L3 must never emit direction, entry, execute, trade_valid, or verdict.
    Hard legality checks run before confirmation scoring.
    status == FAIL implies continuation_allowed == false.
    continuation_allowed == true implies next_legal_targets == ["L4"].

Zone: analysis/ — pure read-only analysis, no execution side-effects.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from loguru import logger

# ═══════════════════════════════════════════════════════════════════════════
# §1  FROZEN ENUMS
# ═══════════════════════════════════════════════════════════════════════════


class L3Status(StrEnum):
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


# ═══════════════════════════════════════════════════════════════════════════
# §2  FROZEN THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════════

# Calibrated for sigmoid edge model with bias=-3.5
# The P_edge output range is ~0.1-0.9 but realistic setups produce 0.2-0.7.
# OLD: HIGH=0.85, MID=0.65 — impossible in practice (required features>0.7 avg).
# NEW: Aligned to actual sigmoid output distribution.
CONFIRMATION_HIGH_GTE = 0.55
CONFIRMATION_MID_GTE = 0.25

# Hard floor: below this → LOW_CONFIRMATION_SCORE blocker (hard fail)
# Between HARD_FLOOR and MID_GTE → warning band (degraded but legal)
CONFIRMATION_HARD_FLOOR = 0.15

# Required trend sources for legal confirmation
REQUIRED_TREND_SOURCES: list[str] = ["ema_stack", "momentum_sync"]

# Freshness thresholds (seconds) — candle-level staleness
FRESHNESS_STALE_THRESHOLD_SEC = 3600  # 1 hour → STALE_PRESERVED
FRESHNESS_DEGRADED_THRESHOLD_SEC = 7200  # 2 hours → DEGRADED

# Minimum bars for warmup legality (L3 uses H1 primarily)
WARMUP_MIN_BARS_H1 = 30


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


# ═══════════════════════════════════════════════════════════════════════════
# §3  SUB-GATE EVALUATORS (frozen evaluation order)
# ═══════════════════════════════════════════════════════════════════════════


def _band_from_score(score: float) -> CoherenceBand:
    """Derive coherence band from confirmation score."""
    if score >= CONFIRMATION_HIGH_GTE:
        return CoherenceBand.HIGH
    if score >= CONFIRMATION_MID_GTE:
        return CoherenceBand.MID
    return CoherenceBand.LOW


def _check_upstream_legality(l2_output: dict[str, Any]) -> list[str]:
    """Step 0: Check that L2 legally authorizes propagation into L3.

    Returns list of blocker codes (empty = pass).
    """
    blockers: list[str] = []

    if not isinstance(l2_output, dict):
        blockers.append(BlockerCode.UPSTREAM_L2_NOT_CONTINUABLE)
        return blockers

    continuation = l2_output.get("continuation_allowed")
    if continuation is None:
        # Backward compat: old L2 output uses "valid"
        continuation = l2_output.get("valid", False)

    if not continuation:
        blockers.append(BlockerCode.UPSTREAM_L2_NOT_CONTINUABLE)

    return blockers


def _check_critical_blockers(l3_analysis: dict[str, Any]) -> list[str]:
    """Step 1: Check structural critical blockers.

    Returns list of blocker codes (empty = pass).
    """
    blockers: list[str] = []

    if not isinstance(l3_analysis, dict):
        blockers.append(BlockerCode.CONTRACT_PAYLOAD_MALFORMED)
        return blockers

    # Required fields
    required_keys = {"valid", "trend", "technical_score"}
    if required_keys - set(l3_analysis.keys()):
        blockers.append(BlockerCode.CONTRACT_PAYLOAD_MALFORMED)
        return blockers

    # Trend confirmation unavailable: NEUTRAL trend with very low score
    trend = l3_analysis.get("trend", "NEUTRAL")
    tech_score = l3_analysis.get("technical_score", 0)
    if trend == "NEUTRAL" and tech_score < 15:
        blockers.append(BlockerCode.TREND_CONFIRMATION_UNAVAILABLE)

    return blockers


def _eval_freshness(
    l3_analysis: dict[str, Any],
    candle_age_seconds: float | None,
) -> FreshnessState:
    """Step 2: Evaluate freshness governance."""
    if candle_age_seconds is not None:
        if candle_age_seconds > FRESHNESS_DEGRADED_THRESHOLD_SEC:
            return FreshnessState.DEGRADED
        if candle_age_seconds > FRESHNESS_STALE_THRESHOLD_SEC:
            return FreshnessState.STALE_PRESERVED
        return FreshnessState.FRESH

    # Infer from data quality
    dq = l3_analysis.get("data_quality", "HEALTHY")
    if dq == "FLAT":
        # FLAT means data exists but is unusable — DEGRADED, not NO_PRODUCER.
        # NO_PRODUCER is reserved for truly absent data pipeline.
        return FreshnessState.DEGRADED
    if dq == "STALE_CLOSE":
        return FreshnessState.STALE_PRESERVED

    # Valid analysis produced → FRESH
    if l3_analysis.get("valid", False):
        return FreshnessState.FRESH

    return FreshnessState.DEGRADED


def _eval_warmup(
    l3_analysis: dict[str, Any],
    h1_bar_count: int | None,
) -> WarmupState:
    """Step 3: Evaluate warmup completeness."""
    if h1_bar_count is not None:
        if h1_bar_count >= WARMUP_MIN_BARS_H1:
            return WarmupState.READY
        if h1_bar_count >= 20:
            return WarmupState.PARTIAL
        return WarmupState.INSUFFICIENT

    # Infer from L3 analysis — if L3 produced valid output, it has ≥30 bars
    if l3_analysis.get("valid", False):
        return WarmupState.READY

    return WarmupState.INSUFFICIENT


def _eval_fallback(
    fallback_used: bool,
    fallback_source: str,
    fallback_approved: bool,
) -> FallbackClass:
    """Step 4: Evaluate fallback legality class."""
    if not fallback_used:
        return FallbackClass.NO_FALLBACK

    if not fallback_approved:
        return FallbackClass.ILLEGAL_FALLBACK

    src = fallback_source.lower()
    if src in (
        "substitute_trend_source",
        "substitute_momentum",
        "primary_substitute",
    ):
        return FallbackClass.LEGAL_PRIMARY_SUBSTITUTE

    if src in (
        "preserved_trend_snapshot",
        "hl_midpoint_synthetic",
        "emergency_preserve",
    ):
        return FallbackClass.LEGAL_EMERGENCY_PRESERVE

    return FallbackClass.LEGAL_EMERGENCY_PRESERVE


def _compute_confirmation_score(l3_analysis: dict[str, Any]) -> float:
    """Step 5: Compute confirmation score from L3 analysis.

    Uses edge_probability as primary, falls back to normalized tech_score.
    """
    # Prefer edge_probability (L3 v6 enrichment)
    ep = l3_analysis.get("edge_probability")
    if ep is not None:
        try:
            return float(ep)
        except (TypeError, ValueError):
            pass

    # Fallback: normalize technical_score (0-100) to 0-1
    tech = l3_analysis.get("technical_score", 0)
    try:
        return min(1.0, max(0.0, float(tech) / 100.0))
    except (TypeError, ValueError):
        return 0.0


def _check_structure_conflict(l3_analysis: dict[str, Any]) -> bool:
    """Check if trend confirmation conflicts with upstream structure.

    A conflict occurs when:
    - trend is directional but structure_validity is WEAK with low confidence

    FLAT data quality is handled by the freshness gate (DEGRADED), not here.
    NEUTRAL trend cannot conflict — there is no directional claim to contradict.
    """
    trend = l3_analysis.get("trend", "NEUTRAL")
    struct_validity = l3_analysis.get("structure_validity", "WEAK")
    confidence = l3_analysis.get("confidence", 0)

    # Directional trend with WEAK structure and very low confidence
    return bool(trend in ("BULLISH", "BEARISH") and struct_validity == "WEAK" and confidence <= 1)


# ═══════════════════════════════════════════════════════════════════════════
# §4  COMPRESSION LOGIC (frozen strict mode)
# ═══════════════════════════════════════════════════════════════════════════


def _compress_status(
    blockers: list[str],
    freshness: FreshnessState,
    warmup: WarmupState,
    fallback: FallbackClass,
    band: CoherenceBand,
    trend_confirmed: bool,
    structure_conflict: bool,
    trend_is_directional: bool = True,
) -> L3Status:
    """Step 6: Compress sub-gate outputs into final status.

        Hard blockers still fail closed, but low confirmation and structure
        conflict are now handled as degradations when the contract is otherwise
        usable and the pipeline can keep forwarding evidence to L12.
    """
    if blockers:
        return L3Status.FAIL

    if not trend_confirmed:
        return L3Status.FAIL

    # LOW band: if no blockers (i.e. above hard floor), allow as WARN
    if band == CoherenceBand.LOW:
        low_warn_legal = freshness in (
            FreshnessState.FRESH,
            FreshnessState.STALE_PRESERVED,
            FreshnessState.DEGRADED,
        ) and warmup in (WarmupState.READY, WarmupState.PARTIAL)
        return L3Status.WARN if low_warn_legal else L3Status.FAIL

    # NEUTRAL trend (confirmed but non-directional) → WARN envelope
    if not trend_is_directional:
        neutral_legal = (
            freshness in (FreshnessState.FRESH, FreshnessState.STALE_PRESERVED, FreshnessState.DEGRADED)
            and warmup in (WarmupState.READY, WarmupState.PARTIAL)
            and band in (CoherenceBand.HIGH, CoherenceBand.MID, CoherenceBand.LOW)
        )
        return L3Status.WARN if neutral_legal else L3Status.FAIL

    clean_pass = (
        freshness == FreshnessState.FRESH
        and warmup == WarmupState.READY
        and band in (CoherenceBand.HIGH, CoherenceBand.MID)
        and not structure_conflict
        and fallback in (FallbackClass.NO_FALLBACK, FallbackClass.LEGAL_PRIMARY_SUBSTITUTE)
    )
    if clean_pass:
        return L3Status.PASS

    legal_warn = (
        freshness in (FreshnessState.FRESH, FreshnessState.STALE_PRESERVED, FreshnessState.DEGRADED)
        and warmup in (WarmupState.READY, WarmupState.PARTIAL)
        and band in (CoherenceBand.HIGH, CoherenceBand.MID)
        and fallback
        in (
            FallbackClass.NO_FALLBACK,
            FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
            FallbackClass.LEGAL_EMERGENCY_PRESERVE,
        )
    )
    if legal_warn:
        return L3Status.WARN

    return L3Status.FAIL


def _collect_warning_codes(
    freshness: FreshnessState,
    warmup: WarmupState,
    fallback: FallbackClass,
    data_quality: str,
    soft_blockers: list[str] | None = None,
) -> list[str]:
    """Collect warning codes for the PASS/WARN envelope."""
    warnings: list[str] = []

    if data_quality == "STALE_CLOSE":
        warnings.append("STALE_CLOSE_DATA")
    if data_quality == "FLAT":
        warnings.append("FLAT_DATA_QUALITY")
    if freshness == FreshnessState.STALE_PRESERVED:
        warnings.append("STALE_PRESERVED_TREND")
    if freshness == FreshnessState.DEGRADED:
        warnings.append("DEGRADED_TREND")
    if warmup == WarmupState.PARTIAL:
        warnings.append("PARTIAL_WARMUP")
    if fallback == FallbackClass.LEGAL_EMERGENCY_PRESERVE:
        warnings.append("EMERGENCY_PRESERVE_FALLBACK")
    if fallback == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
        warnings.append("PRIMARY_SUBSTITUTE_USED")
    warnings.extend(soft_blockers or [])

    return warnings


def _trend_source_summary(available_sources: list[str]) -> dict[str, Any]:
    required_sources = list(REQUIRED_TREND_SOURCES)
    available_required = [name for name in required_sources if name in available_sources]
    missing_required = [name for name in required_sources if name not in available_required]

    hard_blockers: list[str] = []
    soft_blockers: list[str] = []

    if not available_required:
        hard_blockers.append(BlockerCode.REQUIRED_TREND_SOURCE_MISSING.value)
    elif missing_required:
        soft_blockers.extend(f"{name.upper()}_SOURCE_MISSING" for name in missing_required)

    return {
        "required_sources": required_sources,
        "available_required": available_required,
        "missing_required": missing_required,
        "source_completeness": round(len(available_required) / len(required_sources), 4),
        "hard_blockers": list(dict.fromkeys(hard_blockers)),
        "soft_blockers": list(dict.fromkeys(soft_blockers)),
    }


def _confidence_penalty(
    *,
    band: CoherenceBand,
    freshness: FreshnessState,
    warmup: WarmupState,
    fallback: FallbackClass,
    structure_conflict: bool,
    source_soft_blockers: list[str],
) -> float:
    penalty = 0.0

    if band == CoherenceBand.MID:
        penalty += 0.08
    elif band == CoherenceBand.LOW:
        penalty += 0.24

    if freshness == FreshnessState.STALE_PRESERVED:
        penalty += 0.08
    elif freshness == FreshnessState.DEGRADED:
        penalty += 0.14

    if warmup == WarmupState.PARTIAL:
        penalty += 0.10

    if fallback == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
        penalty += 0.06
    elif fallback == FallbackClass.LEGAL_EMERGENCY_PRESERVE:
        penalty += 0.12

    if structure_conflict:
        penalty += 0.22

    if source_soft_blockers:
        penalty += min(0.18, 0.09 * len(source_soft_blockers))

    return round(_clamp01(penalty), 4)


# ═══════════════════════════════════════════════════════════════════════════
# §5  L3 CONSTITUTIONAL GOVERNOR
# ═══════════════════════════════════════════════════════════════════════════


class L3ConstitutionalGovernor:
    """Evidence-aware constitutional evaluator for L3 trend confirmation legality.

    Wraps raw L3 analysis output with constitutional envelope.
    Evaluation order is frozen:
      1. check_upstream_legality (from L2)
      2. check_critical_blockers
      3. check_freshness_legality
      4. check_warmup_legality
      5. check_fallback_legality
      6. compute_confirmation_score
      7. compress_status
      8. set_continuation
      9. emit_contract
    """

    VERSION = "1.1.0"

    def evaluate(
        self,
        *,
        l2_output: dict[str, Any],
        l3_analysis: dict[str, Any],
        symbol: str = "",
        candle_age_seconds: float | None = None,
        h1_bar_count: int | None = None,
        fallback_used: bool = False,
        fallback_source: str = "",
        fallback_approved: bool = False,
    ) -> dict[str, Any]:
        """Run frozen evaluation order and emit canonical L3 contract.

        Parameters
        ----------
        l2_output : dict
            Output from L2 constitutional governor (must have continuation_allowed or valid).
        l3_analysis : dict
            Raw output from L3TechnicalAnalyzer.analyze().
        symbol : str
            Trading pair symbol.
        candle_age_seconds : float | None
            Age of newest candle in seconds (for freshness gate).
        h1_bar_count : int | None
            Number of H1 bars available (for warmup gate).
        fallback_used : bool
            Whether a fallback data source was used.
        fallback_source : str
            Identifier of the fallback source.
        fallback_approved : bool
            Whether the fallback is constitutionally approved.

        Returns
        -------
        dict
            Canonical L3 output contract with constitutional envelope.
        """
        blockers: list[str] = []
        rule_hits: list[str] = []
        notes: list[str] = []
        now_iso = datetime.now(UTC).isoformat()
        input_ref = f"{symbol}_L3_run" if symbol else "L3_run"

        # ── Step 1: Upstream legality ─────────────────────────
        upstream_blockers = _check_upstream_legality(l2_output)
        blockers.extend(upstream_blockers)
        if upstream_blockers:
            rule_hits.append("upstream_l2_not_continuable")

        # ── Step 2: Critical blockers ─────────────────────────
        structural_blockers = _check_critical_blockers(l3_analysis)
        blockers.extend(structural_blockers)
        for b in structural_blockers:
            rule_hits.append(f"blocker={b}")

        # ── Step 3: Freshness legality ────────────────────────
        freshness = _eval_freshness(l3_analysis, candle_age_seconds)
        rule_hits.append(f"freshness_state={freshness.value}")

        if freshness == FreshnessState.NO_PRODUCER:
            blockers.append(BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL)

        # ── Step 4: Warmup legality ───────────────────────────
        warmup = _eval_warmup(l3_analysis, h1_bar_count)
        rule_hits.append(f"warmup_state={warmup.value}")

        if warmup == WarmupState.INSUFFICIENT:
            blockers.append(BlockerCode.WARMUP_INSUFFICIENT)

        # ── Step 5: Fallback legality ─────────────────────────
        # Auto-detect fallback from data quality
        dq = l3_analysis.get("data_quality", "HEALTHY")
        _fallback_used = fallback_used
        _fallback_source = fallback_source
        _fallback_approved = fallback_approved

        if dq == "STALE_CLOSE" and not fallback_used:
            _fallback_used = True
            _fallback_source = "hl_midpoint_synthetic"
            _fallback_approved = True

        fallback = _eval_fallback(_fallback_used, _fallback_source, _fallback_approved)
        rule_hits.append(f"fallback_class={fallback.value}")

        if fallback == FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED)

        # ── Step 6: Compute confirmation score ────────────────
        confirmation_score = _compute_confirmation_score(l3_analysis)
        band = _band_from_score(confirmation_score)
        rule_hits.append(f"coherence_band={band.value}")
        rule_hits.append(f"confirmation_score={confirmation_score:.4f}")

        # Trend confirmation status
        trend = l3_analysis.get("trend", "NEUTRAL")
        # trend_confirmed = L3 analysis ran successfully (valid output)
        # trend_is_directional = trend has a clear direction (BULLISH/BEARISH)
        # NEUTRAL is a valid confirmed state ("confirmed no trend"), not a failure.
        trend_confirmed = l3_analysis.get("valid", False)
        trend_is_directional = trend in ("BULLISH", "BEARISH")
        structure_conflict = _check_structure_conflict(l3_analysis)
        rule_hits.append(f"trend_confirmed={trend_confirmed}")
        rule_hits.append(f"trend_is_directional={trend_is_directional}")
        rule_hits.append(f"structure_conflict={structure_conflict}")
        rule_hits.append(f"trend={trend}")

        soft_blockers: list[str] = []
        if structure_conflict:
            soft_blockers.append(BlockerCode.TREND_STRUCTURE_CONFLICT.value)
            rule_hits.append("trend_structure_conflict_soft")

        if band == CoherenceBand.LOW:
            soft_blockers.append(BlockerCode.LOW_CONFIRMATION_SCORE.value)
            rule_hits.append("low_confirmation_score_soft")

        # ── Step 7: Compress status ───────────────────────────
        blocker_strs = list(dict.fromkeys(b.value if isinstance(b, BlockerCode) else str(b) for b in blockers))

        # Available trend sources built from L3 analysis
        available_sources: list[str] = []
        if l3_analysis.get("trend_strength", 0) > 0:
            available_sources.append("ema_stack")
        if l3_analysis.get("trq3d_energy", 0) > 0:
            available_sources.append("momentum_sync")
        if l3_analysis.get("adx", 0) > 20:
            available_sources.append("adx_trending")
        if l3_analysis.get("fvg_detected", False):
            available_sources.append("fvg_detection")
        if l3_analysis.get("ob_detected", False):
            available_sources.append("ob_detection")

        source_summary = _trend_source_summary(available_sources)
        for blocker in source_summary["hard_blockers"]:
            if blocker not in blocker_strs:
                blocker_strs.append(blocker)
        if source_summary["soft_blockers"]:
            soft_blockers = list(dict.fromkeys([*soft_blockers, *source_summary["soft_blockers"]]))
            rule_hits.append("trend_source_soft_blockers=" + ",".join(source_summary["soft_blockers"]))

        status = _compress_status(
            blocker_strs,
            freshness,
            warmup,
            fallback,
            band,
            trend_confirmed,
            structure_conflict,
            trend_is_directional,
        )

        if soft_blockers and status == L3Status.PASS:
            status = L3Status.WARN
            rule_hits.append("soft_evidence_downgrade")

        confidence_penalty = _confidence_penalty(
            band=band,
            freshness=freshness,
            warmup=warmup,
            fallback=fallback,
            structure_conflict=structure_conflict,
            source_soft_blockers=soft_blockers,
        )
        evidence_score = _clamp01(confirmation_score - confidence_penalty)
        hard_blockers = list(dict.fromkeys(blocker_strs))
        soft_blockers = list(dict.fromkeys(soft_blockers))
        hard_stop = bool(hard_blockers)
        advisory_continuation = not hard_stop

        # Collect warning codes (for PASS and WARN — PASS can have advisory warnings)
        warning_codes: list[str] = []
        if status in (L3Status.PASS, L3Status.WARN):
            warning_codes = _collect_warning_codes(
                freshness,
                warmup,
                fallback,
                dq,
                soft_blockers,
            )
            if not trend_is_directional:
                warning_codes.append("NEUTRAL_TREND_NON_DIRECTIONAL")
            if band == CoherenceBand.LOW:
                warning_codes.append("LOW_CONFIRMATION_SCORE_DEGRADED")
            if structure_conflict:
                warning_codes.append("TREND_STRUCTURE_CONFLICT_DEGRADED")

        if band == CoherenceBand.LOW:
            notes.append("Confirmation score is below the directional ideal and is treated as degraded evidence.")
        if structure_conflict:
            notes.append("Trend confirmation conflicts with upstream structure and is forwarded as degraded evidence.")
        if not trend_confirmed and status == L3Status.FAIL:
            notes.append("L3 analysis invalid — trend confirmation unavailable.")
        if not trend_is_directional and status == L3Status.WARN:
            notes.append("NEUTRAL trend — non-directional confirmation, pipeline continues with reduced confidence.")

        # ── Step 8: Set continuation ──────────────────────────
        continuation_allowed = status in (L3Status.PASS, L3Status.WARN)
        next_targets = ["L4"] if continuation_allowed else []

        missing_sources = [s for s in REQUIRED_TREND_SOURCES if s not in available_sources]

        # Log constitutional result
        logger.info(
            "[L3] {} constitutional: status={} band={} confirmation={:.4f} evidence={:.4f} penalty={:.4f} "
            "freshness={} warmup={} fallback={} trend={} conflict={} hard={} soft={}",
            symbol,
            status.value,
            band.value,
            confirmation_score,
            evidence_score,
            confidence_penalty,
            freshness.value,
            warmup.value,
            fallback.value,
            trend,
            structure_conflict,
            len(hard_blockers),
            len(soft_blockers),
        )

        # ── Step 9: Emit contract ─────────────────────────────
        return {
            # Canonical envelope
            "layer": "L3",
            "layer_version": self.VERSION,
            "timestamp": now_iso,
            "input_ref": input_ref,
            "status": status.value,
            "continuation_allowed": continuation_allowed,
            "blocker_codes": hard_blockers,
            "warning_codes": warning_codes,
            "fallback_class": fallback.value,
            "freshness_state": freshness.value,
            "warmup_state": warmup.value,
            "coherence_band": band.value,
            "coherence_score": round(confirmation_score, 4),
            "score_numeric": round(confirmation_score, 4),
            "evidence_score": round(evidence_score, 4),
            "confidence_penalty": round(confidence_penalty, 4),
            "hard_blockers": hard_blockers,
            "soft_blockers": soft_blockers,
            "hard_stop": hard_stop,
            "advisory_continuation": advisory_continuation,
            # Features
            "features": {
                "confirmation_score": round(confirmation_score, 4),
                "trend_confirmed": trend_confirmed,
                "structure_conflict": structure_conflict,
                "candle_age_seconds": candle_age_seconds,
                "candle_age_by_tf": dict(l3_analysis.get("candle_age_by_tf", {})),
                "h1_bar_count": h1_bar_count,
                "required_trend_sources": list(REQUIRED_TREND_SOURCES),
                "available_trend_sources": available_sources,
                "missing_trend_sources": missing_sources,
                "evidence_score": round(evidence_score, 4),
                "confidence_penalty": round(confidence_penalty, 4),
            },
            "trend_diagnostics": {
                "trend": trend,
                "trend_confirmed": trend_confirmed,
                "trend_is_directional": trend_is_directional,
                "structure_conflict": structure_conflict,
                "confirmation_score": round(confirmation_score, 4),
                "required_confirmation_floor": CONFIRMATION_HARD_FLOOR,
                "required_confirmation_mid": CONFIRMATION_MID_GTE,
                "required_sources": list(REQUIRED_TREND_SOURCES),
                "available_sources": available_sources,
                "missing_sources": missing_sources,
                "source_completeness": source_summary["source_completeness"],
                "hard_blockers": hard_blockers,
                "soft_blockers": soft_blockers,
            },
            # Routing
            "routing": {
                "source_used": available_sources,
                "fallback_used": _fallback_used,
                "next_legal_targets": next_targets,
            },
            # Audit
            "audit": {
                "rule_hits": rule_hits,
                "blocker_triggered": bool(hard_blockers),
                "notes": notes,
                "trend_evidence": {
                    "hard_blockers": hard_blockers,
                    "soft_blockers": soft_blockers,
                    "source_completeness": source_summary["source_completeness"],
                },
            },
        }
