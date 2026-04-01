"""
L2 Constitutional Governor — Strict Mode v1.0.0
================================================

Constitutional sub-gate evaluator for L2 MTA structure legality.

Implements the frozen L2 spec:
  - Evaluation order: upstream → blockers → freshness → warmup → fallback → alignment → compress → emit
  - Critical blockers spec (frozen v1)
  - Fallback legality matrix (frozen v1)
  - Freshness / warmup states
  - Alignment thresholds (frozen baseline v1)
  - Final compression logic (strict mode)

Authority boundary:
  L2 is an MTA structure legality governor only.
  L2 must never emit direction, entry, execute, trade_valid, or verdict.
  Hard legality checks run before alignment scoring.
  status == FAIL implies continuation_allowed == false.
  continuation_allowed == true implies next_legal_targets == ["L3"].

Zone: analysis/ — pure read-only analysis, no execution side-effects.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from loguru import logger

# ═══════════════════════════════════════════════════════════════════════════
# §1  FROZEN ENUMS
# ═══════════════════════════════════════════════════════════════════════════


class L2Status(str, Enum):
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
    UPSTREAM_L1_NOT_CONTINUABLE = "UPSTREAM_L1_NOT_CONTINUABLE"
    REQUIRED_TIMEFRAME_MISSING = "REQUIRED_TIMEFRAME_MISSING"
    TIMEFRAME_SET_INSUFFICIENT = "TIMEFRAME_SET_INSUFFICIENT"
    MTA_HIERARCHY_VIOLATED = "MTA_HIERARCHY_VIOLATED"
    STRUCTURE_SOURCE_INVALID = "STRUCTURE_SOURCE_INVALID"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


# ═══════════════════════════════════════════════════════════════════════════
# §2  FROZEN THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════════

ALIGNMENT_HIGH_GTE = 0.85
ALIGNMENT_MID_GTE = 0.65

# Required timeframes that must be present for legal MTA evaluation
REQUIRED_TIMEFRAMES: list[str] = ["D1", "H4"]

# Coverage target — ideal set, partial coverage triggers WARN not FAIL
COVERAGE_TARGET_TIMEFRAMES: list[str] = ["MN", "W1", "D1", "H4", "H1", "M15"]

# Minimum timeframes for MTA legality
MIN_TIMEFRAMES_LEGAL = 3

# Freshness thresholds (seconds) — candle-level staleness
FRESHNESS_STALE_THRESHOLD_SEC = 3600  # 1 hour → STALE_PRESERVED
FRESHNESS_DEGRADED_THRESHOLD_SEC = 7200  # 2 hours → DEGRADED

# Minimum bars per timeframe for warmup legality
WARMUP_MIN_BARS: dict[str, int] = {
    "H1": 20,
    "H4": 10,
    "D1": 5,
    "W1": 3,
    "MN": 1,
}


# ═══════════════════════════════════════════════════════════════════════════
# §3  SUB-GATE EVALUATORS (frozen evaluation order)
# ═══════════════════════════════════════════════════════════════════════════


def _band_from_score(score: float) -> CoherenceBand:
    """Derive coherence band from alignment score."""
    if score >= ALIGNMENT_HIGH_GTE:
        return CoherenceBand.HIGH
    if score >= ALIGNMENT_MID_GTE:
        return CoherenceBand.MID
    return CoherenceBand.LOW


def _check_upstream_legality(l1_output: dict[str, Any]) -> list[str]:
    """Step 1: Check that L1 legally authorizes propagation into L2.

    Returns list of blocker codes (empty = pass).
    """
    blockers: list[str] = []

    if not isinstance(l1_output, dict):
        blockers.append(BlockerCode.UPSTREAM_L1_NOT_CONTINUABLE)
        return blockers

    continuation = l1_output.get("continuation_allowed")
    if continuation is None:
        # Backward compat: old L1 output uses "valid"
        continuation = l1_output.get("valid", False)

    if not continuation:
        blockers.append(BlockerCode.UPSTREAM_L1_NOT_CONTINUABLE)

    return blockers


def _check_critical_blockers(
    l2_analysis: dict[str, Any],
    available_tfs: list[str],
) -> list[str]:
    """Step 2: Check structural critical blockers.

    Returns list of blocker codes (empty = pass).
    """
    blockers: list[str] = []

    # Required payload fields
    required_keys = {"valid", "available_timeframes"}
    if not isinstance(l2_analysis, dict) or (required_keys - set(l2_analysis.keys())):
        blockers.append(BlockerCode.CONTRACT_PAYLOAD_MALFORMED)
        return blockers

    # Required timeframes must be present
    missing_required = [tf for tf in REQUIRED_TIMEFRAMES if tf not in available_tfs]
    if missing_required:
        blockers.append(BlockerCode.REQUIRED_TIMEFRAME_MISSING)

    # Minimum timeframe set
    if len(available_tfs) < MIN_TIMEFRAMES_LEGAL:
        blockers.append(BlockerCode.TIMEFRAME_SET_INSUFFICIENT)

    # Hierarchy check
    if not l2_analysis.get("hierarchy_followed", False):
        blockers.append(BlockerCode.MTA_HIERARCHY_VIOLATED)

    return blockers


def _eval_freshness(
    l2_analysis: dict[str, Any],
    candle_age_seconds: float | None,
) -> FreshnessState:
    """Step 3: Evaluate freshness governance.

    Uses candle age if available, otherwise infers from L2 analysis.
    """
    if candle_age_seconds is not None:
        if candle_age_seconds > FRESHNESS_DEGRADED_THRESHOLD_SEC:
            return FreshnessState.DEGRADED
        if candle_age_seconds > FRESHNESS_STALE_THRESHOLD_SEC:
            return FreshnessState.STALE_PRESERVED
        return FreshnessState.FRESH

    # If no candle age is available, check if L2 produced valid data
    if not l2_analysis.get("valid", False):
        return FreshnessState.NO_PRODUCER

    return FreshnessState.FRESH


def _eval_warmup(
    available_tfs: list[str],
    candle_counts: dict[str, int] | None,
) -> WarmupState:
    """Step 4: Evaluate warmup completeness.

    Checks that available timeframes have sufficient bars.
    """
    if candle_counts is None:
        # No bar count data — infer from tf count
        if len(available_tfs) >= MIN_TIMEFRAMES_LEGAL:
            return WarmupState.READY
        if available_tfs:
            return WarmupState.PARTIAL
        return WarmupState.INSUFFICIENT

    insufficient_count = 0
    partial_count = 0

    for tf, min_bars in WARMUP_MIN_BARS.items():
        count = candle_counts.get(tf, 0)
        if tf in REQUIRED_TIMEFRAMES and count < min_bars:
            insufficient_count += 1
        elif count < min_bars:
            partial_count += 1

    if insufficient_count > 0:
        return WarmupState.INSUFFICIENT
    if partial_count > 0:
        return WarmupState.PARTIAL
    return WarmupState.READY


def _eval_fallback(
    fallback_used: bool,
    fallback_source: str,
    fallback_approved: bool,
) -> FallbackClass:
    """Step 5: Evaluate fallback legality.

    Classifies the fallback path used (if any).
    """
    if not fallback_used:
        return FallbackClass.NO_FALLBACK

    if not fallback_approved:
        return FallbackClass.ILLEGAL_FALLBACK

    # Classify approved fallbacks
    if fallback_source in (
        "substitute_timeframe",
        "substitute_provider",
        "primary_substitute",
    ):
        return FallbackClass.LEGAL_PRIMARY_SUBSTITUTE

    if fallback_source in (
        "preserved_structure_snapshot",
        "cached_mtf",
        "emergency_preserve",
    ):
        return FallbackClass.LEGAL_EMERGENCY_PRESERVE

    # Unknown approved fallback → treat as emergency preserve
    return FallbackClass.LEGAL_EMERGENCY_PRESERVE


def _compute_alignment_score(l2_analysis: dict[str, Any]) -> float:
    """Step 6: Extract alignment score from L2 analysis.

    Uses alignment_strength from L2 Bayesian analysis.
    """
    raw = l2_analysis.get("alignment_strength", 0.0)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


# ═══════════════════════════════════════════════════════════════════════════
# §4  COMPRESSION LOGIC (frozen strict mode)
# ═══════════════════════════════════════════════════════════════════════════


def _compress_status(
    blockers: list[str],
    freshness: FreshnessState,
    warmup: WarmupState,
    fallback: FallbackClass,
    band: CoherenceBand,
    hierarchy_followed: bool,
    aligned: bool,
    partial_coverage: bool,
) -> L2Status:
    """Step 7: Compress all sub-gate outputs into final status.

    Truth table (frozen v1):
      FAIL: any critical blocker, LOW band, hierarchy violated, no-producer,
            insufficient warmup, illegal fallback
      PASS: fresh + ready + hierarchy ok + aligned + no partial coverage +
            band in {HIGH, MID} + fallback in {NO, PRIMARY_SUBSTITUTE}
      WARN: legal degraded envelope (all other legal-but-degraded states)
      else: FAIL
    """
    # Any critical blocker → FAIL
    if blockers:
        return L2Status.FAIL

    # Band LOW → FAIL
    if band == CoherenceBand.LOW:
        return L2Status.FAIL

    # Clean PASS envelope
    clean_pass = (
        freshness == FreshnessState.FRESH
        and warmup == WarmupState.READY
        and hierarchy_followed
        and aligned
        and not partial_coverage
        and band in (CoherenceBand.HIGH, CoherenceBand.MID)
        and fallback in (FallbackClass.NO_FALLBACK, FallbackClass.LEGAL_PRIMARY_SUBSTITUTE)
    )
    if clean_pass:
        return L2Status.PASS

    # WARN envelope — legal but degraded
    legal_warn = (
        freshness in (FreshnessState.FRESH, FreshnessState.STALE_PRESERVED, FreshnessState.DEGRADED)
        and warmup in (WarmupState.READY, WarmupState.PARTIAL)
        and hierarchy_followed
        and band in (CoherenceBand.HIGH, CoherenceBand.MID)
        and fallback in (
            FallbackClass.NO_FALLBACK,
            FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
            FallbackClass.LEGAL_EMERGENCY_PRESERVE,
        )
    )
    if legal_warn:
        return L2Status.WARN

    return L2Status.FAIL


def _collect_warning_codes(
    freshness: FreshnessState,
    warmup: WarmupState,
    fallback: FallbackClass,
    aligned: bool,
    partial_coverage: bool,
) -> list[str]:
    """Collect warning codes for the WARN envelope."""
    warnings: list[str] = []

    if not aligned:
        warnings.append("STRUCTURE_NOT_FULLY_ALIGNED")
    if partial_coverage:
        warnings.append("PARTIAL_TIMEFRAME_COVERAGE")
    if freshness == FreshnessState.STALE_PRESERVED:
        warnings.append("STALE_PRESERVED_STRUCTURE")
    if freshness == FreshnessState.DEGRADED:
        warnings.append("DEGRADED_STRUCTURE")
    if warmup == WarmupState.PARTIAL:
        warnings.append("PARTIAL_WARMUP")
    if fallback == FallbackClass.LEGAL_EMERGENCY_PRESERVE:
        warnings.append("EMERGENCY_PRESERVE_FALLBACK")
    if fallback == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
        warnings.append("PRIMARY_SUBSTITUTE_USED")

    return warnings


# ═══════════════════════════════════════════════════════════════════════════
# §5  L2 CONSTITUTIONAL GOVERNOR
# ═══════════════════════════════════════════════════════════════════════════


class L2ConstitutionalGovernor:
    """Strict constitutional evaluator for L2 MTA structure legality.

    Wraps raw L2 analysis output with constitutional envelope.
    Evaluation order is frozen:
      1. check_upstream_legality
      2. check_critical_blockers
      3. check_freshness_legality
      4. check_warmup_legality
      5. check_fallback_legality
      6. compute_alignment_score
      7. compress_status
      8. set_continuation
      9. emit_contract
    """

    VERSION = "1.0.0"

    def evaluate(
        self,
        *,
        l1_output: dict[str, Any],
        l2_analysis: dict[str, Any],
        symbol: str = "",
        candle_age_seconds: float | None = None,
        candle_counts: dict[str, int] | None = None,
        fallback_used: bool = False,
        fallback_source: str = "",
        fallback_approved: bool = False,
    ) -> dict[str, Any]:
        """Run frozen evaluation order and emit canonical L2 contract.

        Parameters
        ----------
        l1_output : dict
            Output from L1 constitutional governor (must have continuation_allowed or valid).
        l2_analysis : dict
            Raw output from L2MTAAnalyzer.analyze().
        symbol : str
            Trading pair symbol.
        candle_age_seconds : float | None
            Age of newest candle in seconds (for freshness gate).
        candle_counts : dict | None
            {timeframe: bar_count} for warmup gate.
        fallback_used : bool
            Whether a fallback data source was used.
        fallback_source : str
            Identifier of the fallback source.
        fallback_approved : bool
            Whether the fallback is constitutionally approved.

        Returns
        -------
        dict
            Canonical L2 output contract with constitutional envelope.
        """
        blockers: list[str] = []
        rule_hits: list[str] = []
        notes: list[str] = []
        now_iso = datetime.now(UTC).isoformat()
        input_ref = f"{symbol}_L2_run" if symbol else "L2_run"

        # ── Step 1: Upstream legality ─────────────────────────
        upstream_blockers = _check_upstream_legality(l1_output)
        blockers.extend(upstream_blockers)
        if upstream_blockers:
            rule_hits.append("upstream_l1_not_continuable")

        # ── Step 2: Critical blockers ─────────────────────────
        available_tfs = self._extract_available_tfs(l2_analysis)
        structural_blockers = _check_critical_blockers(l2_analysis, available_tfs)
        blockers.extend(structural_blockers)
        for b in structural_blockers:
            rule_hits.append(f"blocker={b}")

        # ── Step 3: Freshness legality ────────────────────────
        freshness = _eval_freshness(l2_analysis, candle_age_seconds)
        rule_hits.append(f"freshness_state={freshness.value}")

        if freshness == FreshnessState.NO_PRODUCER:
            blockers.append(BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL)

        # ── Step 4: Warmup legality ───────────────────────────
        warmup = _eval_warmup(available_tfs, candle_counts)
        rule_hits.append(f"warmup_state={warmup.value}")

        if warmup == WarmupState.INSUFFICIENT:
            blockers.append(BlockerCode.WARMUP_INSUFFICIENT)

        # ── Step 5: Fallback legality ─────────────────────────
        fallback = _eval_fallback(fallback_used, fallback_source, fallback_approved)
        rule_hits.append(f"fallback_class={fallback.value}")

        if fallback == FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED)

        # ── Step 6: Compute alignment score ───────────────────
        alignment_score = _compute_alignment_score(l2_analysis)
        band = _band_from_score(alignment_score)
        rule_hits.append(f"coherence_band={band.value}")
        rule_hits.append(f"alignment_score={alignment_score:.4f}")
        rule_hits.append(f"available_timeframes={len(available_tfs)}")

        hierarchy_followed = bool(l2_analysis.get("hierarchy_followed", False))
        hierarchy_band = str(l2_analysis.get("hierarchy_band", "PASS" if hierarchy_followed else "FAIL"))
        aligned = bool(l2_analysis.get("aligned", False))
        rule_hits.append(f"hierarchy_followed={hierarchy_followed}")
        rule_hits.append(f"hierarchy_band={hierarchy_band}")
        rule_hits.append(f"aligned={aligned}")

        # Partial coverage check
        partial_coverage = any(
            tf not in available_tfs for tf in COVERAGE_TARGET_TIMEFRAMES
        )

        # ── Step 7: Compress status ───────────────────────────
        # Deduplicate blockers
        blocker_strs = list(dict.fromkeys(
            b.value if isinstance(b, BlockerCode) else str(b)
            for b in blockers
        ))

        status = _compress_status(
            blocker_strs,
            freshness,
            warmup,
            fallback,
            band,
            hierarchy_followed,
            aligned,
            partial_coverage,
        )

        # Collect warning codes (for PASS and WARN — PASS can have advisory warnings)
        warning_codes: list[str] = []
        if status in (L2Status.PASS, L2Status.WARN):
            warning_codes = _collect_warning_codes(
                freshness, warmup, fallback, aligned, partial_coverage,
            )
            if hierarchy_band == "WARN":
                warning_codes.append("MTA_HIERARCHY_DEGRADED")

        if hierarchy_band == "WARN" and status != L2Status.FAIL:
            notes.append("Alignment in WARN band — regime-adaptive threshold applied.")
        if band == CoherenceBand.LOW and status == L2Status.FAIL:
            notes.append("Alignment below legal threshold.")
        if partial_coverage and status != L2Status.FAIL:
            notes.append("Coverage target incomplete but required TFs are present.")

        # ── Step 8: Set continuation ──────────────────────────
        continuation_allowed = status in (L2Status.PASS, L2Status.WARN)
        next_targets = ["L3"] if continuation_allowed else []

        # ── Step 9: Emit contract ─────────────────────────────
        missing_required = [tf for tf in REQUIRED_TIMEFRAMES if tf not in available_tfs]

        # Log constitutional result
        logger.info(
            "[L2] {} constitutional: status={} band={} alignment={:.4f} "
            "freshness={} warmup={} fallback={} blockers={}",
            symbol,
            status.value,
            band.value,
            alignment_score,
            freshness.value,
            warmup.value,
            fallback.value,
            len(blocker_strs),
        )

        return {
            # Canonical envelope
            "layer": "L2",
            "layer_version": self.VERSION,
            "timestamp": now_iso,
            "input_ref": input_ref,
            "status": status.value,
            "continuation_allowed": continuation_allowed,
            "blocker_codes": blocker_strs,
            "warning_codes": warning_codes,
            "fallback_class": fallback.value,
            "freshness_state": freshness.value,
            "warmup_state": warmup.value,
            "coherence_band": band.value,
            "coherence_score": round(alignment_score, 4),
            # Features
            "features": {
                "alignment_score": round(alignment_score, 4),
                "hierarchy_followed": hierarchy_followed,
                "aligned": aligned,
                "required_timeframes": list(REQUIRED_TIMEFRAMES),
                "coverage_target_timeframes": list(COVERAGE_TARGET_TIMEFRAMES),
                "available_timeframes": available_tfs,
                "missing_required_timeframes": missing_required,
            },
            # Routing
            "routing": {
                "source_used": list(l2_analysis.get("per_tf_bias", {}).keys()),
                "fallback_used": fallback_used,
                "next_legal_targets": next_targets,
            },
            # Audit
            "audit": {
                "rule_hits": rule_hits,
                "blocker_triggered": bool(blocker_strs),
                "notes": notes,
            },
        }

    @staticmethod
    def _extract_available_tfs(l2_analysis: dict[str, Any]) -> list[str]:
        """Extract list of available timeframe strings from L2 analysis."""
        per_tf = l2_analysis.get("per_tf_bias", {})
        if isinstance(per_tf, dict) and per_tf:
            return list(per_tf.keys())

        # Fallback: count-based (old format)
        count = l2_analysis.get("available_timeframes", 0)
        if isinstance(count, int) and count > 0:
            # Infer from standard order
            return ["D1", "H4", "H1", "M15", "W1", "MN"][:count]

        return []
