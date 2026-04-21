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

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from loguru import logger

# ═══════════════════════════════════════════════════════════════════════════
# §1  FROZEN ENUMS
# ═══════════════════════════════════════════════════════════════════════════


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
    LOW_ALIGNMENT_BAND = "LOW_ALIGNMENT_BAND"
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


def _coerce_float(value: Any) -> float | None:
    """Best-effort float coercion for optional diagnostics fields."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tf_bias_direction(detail: Any) -> str:
    """Derive a normalized directional label for one timeframe detail."""
    if isinstance(detail, dict):
        explicit = detail.get("bias")
        if isinstance(explicit, str) and explicit:
            label = explicit.strip().upper()
            if label in {"BULLISH", "BEARISH", "NEUTRAL"}:
                return label

        p_value = _coerce_float(detail.get("p_bull"))
        if p_value is None:
            return "NEUTRAL"
        if p_value > 0.5:
            return "BULLISH"
        if p_value < 0.5:
            return "BEARISH"
    return "NEUTRAL"


def _tf_bias_strength(detail: Any) -> float:
    """Derive a normalized 0-1 directional strength for one timeframe detail."""
    if isinstance(detail, dict):
        explicit = _coerce_float(detail.get("strength"))
        if explicit is not None:
            return round(max(0.0, min(1.0, explicit)), 4)

        p_bull = _coerce_float(detail.get("p_bull"))
        if p_bull is None:
            return 0.0
        return round(max(0.0, min(1.0, abs(p_bull - 0.5) * 2.0)), 4)
    return 0.0


def _resolve_direction_consensus(per_tf_bias: dict[str, Any]) -> str:
    """Summarize directional agreement across timeframes."""
    directions = [_tf_bias_direction(detail) for detail in per_tf_bias.values()]
    non_neutral = [direction for direction in directions if direction != "NEUTRAL"]
    if not non_neutral:
        return "neutral"
    if all(direction == "BULLISH" for direction in non_neutral):
        return "bullish"
    if all(direction == "BEARISH" for direction in non_neutral):
        return "bearish"
    return "mixed"


def _build_conflict_matrix(available_tfs: list[str], per_tf_bias: dict[str, Any]) -> tuple[list[str], str | None]:
    """Build adjacent-timeframe conflicts ordered from HTF to LTF."""
    conflicts: list[str] = []
    for left_tf, right_tf in zip(available_tfs, available_tfs[1:], strict=False):
        left_dir = _tf_bias_direction(per_tf_bias.get(left_tf, {}))
        right_dir = _tf_bias_direction(per_tf_bias.get(right_tf, {}))
        if "NEUTRAL" in (left_dir, right_dir):
            continue
        if left_dir != right_dir:
            conflicts.append(f"{left_tf} {left_dir.lower()} vs {right_tf} {right_dir.lower()}")

    primary_conflict = None
    if conflicts:
        first = conflicts[0]
        first_left, _, _, first_right, _ = first.split()
        primary_conflict = f"{first_left}_{first_right}_DIRECTION_CONFLICT"
    return conflicts, primary_conflict


def _build_mta_diagnostics(
    *,
    l2_analysis: dict[str, Any],
    available_tfs: list[str],
    alignment_score: float,
    candle_counts: dict[str, int] | None,
) -> dict[str, Any]:
    """Assemble audit-friendly L2 MTA diagnostics without affecting decisions."""
    per_tf_bias = l2_analysis.get("per_tf_bias", {})
    if not isinstance(per_tf_bias, dict):
        per_tf_bias = {}

    per_tf_direction = {tf: _tf_bias_direction(per_tf_bias.get(tf, {})) for tf in available_tfs}
    per_tf_strength = {tf: _tf_bias_strength(per_tf_bias.get(tf, {})) for tf in available_tfs}
    candle_age_by_tf = l2_analysis.get("candle_age_by_tf", {})
    if not isinstance(candle_age_by_tf, dict):
        candle_age_by_tf = {}

    conflict_matrix, primary_conflict = _build_conflict_matrix(available_tfs, per_tf_bias)
    missing_timeframes = [tf for tf in COVERAGE_TARGET_TIMEFRAMES if tf not in available_tfs]

    return {
        "alignment_score": round(alignment_score, 4),
        "required_alignment": ALIGNMENT_MID_GTE,
        "direction_consensus": _resolve_direction_consensus(per_tf_bias),
        "available_timeframes": list(available_tfs),
        "missing_timeframes": missing_timeframes,
        "per_tf_bias": per_tf_direction,
        "per_tf_strength": per_tf_strength,
        "candle_age_by_tf": {tf: candle_age_by_tf.get(tf) for tf in available_tfs if tf in candle_age_by_tf},
        "candle_counts": {tf: (candle_counts or {}).get(tf, 0) for tf in available_tfs},
        "conflict_matrix": conflict_matrix,
        "primary_conflict": primary_conflict,
    }


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
        and fallback
        in (
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
# §4b  GRANULAR MTA DIAGNOSTICS EMITTER
# ═══════════════════════════════════════════════════════════════════════════

# Blocker codes that warrant full per-timeframe forensic output
_DIAGNOSTIC_TRIGGER_BLOCKERS: frozenset[str] = frozenset(
    {
        BlockerCode.MTA_HIERARCHY_VIOLATED.value,
        BlockerCode.LOW_ALIGNMENT_BAND.value,
    }
)

# Adjacent TF pairs in HTF→LTF order used for conflict analysis
_ADJACENT_TF_PAIRS: list[tuple[str, str]] = [
    ("MN", "W1"),
    ("W1", "D1"),
    ("D1", "H4"),
    ("H4", "H1"),
    ("H1", "M15"),
]


def _emit_mta_diagnostics_warning(
    *,
    symbol: str,
    l2_analysis: dict[str, Any],
    available_tfs: list[str],
    alignment_score: float,
    candle_counts: dict[str, int] | None,
    blocker_strs: list[str],
) -> None:
    """Emit granular per-timeframe MTA diagnostics at WARNING level.

    Called before a blocker is raised so forensic data is always present
    in logs alongside the blocker name.  Pure read-only — no side-effects
    on the evaluation result.

    Emits a single WARNING line with key ``L2_MTA_DIAGNOSTICS`` and a
    JSON payload that includes per-TF bias, candle counts, freshness,
    alignment score vs threshold, conflict analysis, and a human-readable
    recommendation.
    """
    # Only emit when a hierarchy or alignment blocker is present
    if not any(b in _DIAGNOSTIC_TRIGGER_BLOCKERS for b in blocker_strs):
        return

    per_tf_bias_raw: dict[str, Any] = l2_analysis.get("per_tf_bias", {})
    if not isinstance(per_tf_bias_raw, dict):
        per_tf_bias_raw = {}

    candle_age_by_tf: dict[str, Any] = l2_analysis.get("candle_age_by_tf", {})
    if not isinstance(candle_age_by_tf, dict):
        candle_age_by_tf = {}

    counts: dict[str, int] = candle_counts or {}

    # ── Per-timeframe analysis block ─────────────────────────────────────
    timeframe_analysis: dict[str, dict[str, Any]] = {}
    for tf in available_tfs:
        detail = per_tf_bias_raw.get(tf, {})
        bias_label = _tf_bias_direction(detail).lower()  # "bullish" / "bearish" / "neutral"

        age_raw = candle_age_by_tf.get(tf)
        try:
            age_sec: float | None = float(age_raw) if age_raw is not None else None
        except (TypeError, ValueError):
            age_sec = None

        is_fresh = (age_sec is not None and age_sec <= FRESHNESS_STALE_THRESHOLD_SEC)

        timeframe_analysis[tf] = {
            "bias": bias_label,
            "candle_count": counts.get(tf, 0),
            "latest_age_seconds": round(age_sec, 1) if age_sec is not None else None,
            "is_fresh": is_fresh,
        }

    # ── Conflict analysis ─────────────────────────────────────────────────
    conflict_pairs: dict[str, str] = {}
    conflict_descriptions: list[str] = []

    for htf, ltf in _ADJACENT_TF_PAIRS:
        if htf not in available_tfs or ltf not in available_tfs:
            continue
        htf_dir = _tf_bias_direction(per_tf_bias_raw.get(htf, {}))
        ltf_dir = _tf_bias_direction(per_tf_bias_raw.get(ltf, {}))
        pair_key = f"{htf}_vs_{ltf}"

        if "NEUTRAL" in (htf_dir, ltf_dir):
            conflict_pairs[pair_key] = "indeterminate"
        elif htf_dir == ltf_dir:
            conflict_pairs[pair_key] = "aligned"
        else:
            conflict_pairs[pair_key] = "conflict"
            conflict_descriptions.append(
                f"{htf} {htf_dir.lower()} but {ltf} {ltf_dir.lower()}"
            )

    # Build human-readable reason string
    if conflict_descriptions:
        reason_str = "; ".join(conflict_descriptions) + " — hierarchy broken"
    elif BlockerCode.LOW_ALIGNMENT_BAND.value in blocker_strs:
        reason_str = f"alignment_score={alignment_score:.4f} below required threshold={ALIGNMENT_MID_GTE}"
    else:
        reason_str = "MTA hierarchy or alignment constraint violated"

    conflict_analysis: dict[str, Any] = dict(conflict_pairs)
    conflict_analysis["reason"] = reason_str

    # ── Failed reason & recommendation ───────────────────────────────────
    active_blockers = [b for b in blocker_strs if b in _DIAGNOSTIC_TRIGGER_BLOCKERS]
    failed_reason = " + ".join(
        f"{b} due to {reason_str}" if i == 0 else b
        for i, b in enumerate(active_blockers)
    )

    recommendation = (
        "Check if market is genuinely not aligned (accept HOLD), "
        "threshold needs calibration (adjust with evidence), "
        "H1/H4 producer has gaps (fix producer), "
        "or candle counts are insufficient (wait for warmup)"
    )

    # ── Assemble and emit ─────────────────────────────────────────────────
    payload: dict[str, Any] = {
        "symbol": symbol,
        "timeframe_analysis": timeframe_analysis,
        "alignment_score": round(alignment_score, 4),
        "required_alignment_threshold": ALIGNMENT_MID_GTE,
        "available_timeframes": list(available_tfs),
        "conflict_analysis": conflict_analysis,
        "failed_reason": failed_reason,
        "recommendation": recommendation,
    }

    try:
        payload_json = json.dumps(payload, default=str)
    except Exception:
        payload_json = str(payload)

    logger.warning("L2_MTA_DIAGNOSTICS {}", payload_json)


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
        partial_coverage = any(tf not in available_tfs for tf in COVERAGE_TARGET_TIMEFRAMES)

        # ── Step 6b: Close alignment band gap ─────────────────
        # If band is LOW but MTA says hierarchy_followed (threshold gap
        # between MTA warn_threshold and constitutional ALIGNMENT_MID_GTE),
        # add an explicit blocker so halts are never silent.
        _has_alignment_blocker = any(
            str(b) in (BlockerCode.MTA_HIERARCHY_VIOLATED, BlockerCode.LOW_ALIGNMENT_BAND)
            if isinstance(b, BlockerCode)
            else b in (BlockerCode.MTA_HIERARCHY_VIOLATED.value, BlockerCode.LOW_ALIGNMENT_BAND.value)
            for b in blockers
        )
        if band == CoherenceBand.LOW and not _has_alignment_blocker:
            blockers.append(BlockerCode.LOW_ALIGNMENT_BAND)
            rule_hits.append("low_alignment_band_blocker_injected")

        # ── Step 7: Compress status ───────────────────────────
        # Deduplicate blockers
        blocker_strs = list(dict.fromkeys(b.value if isinstance(b, BlockerCode) else str(b) for b in blockers))

        # ── Step 6c: Emit granular MTA diagnostics before blocking ────────
        # Fires only when MTA_HIERARCHY_VIOLATED or LOW_ALIGNMENT_BAND are
        # present.  Pure read-only — no effect on evaluation outcome.
        _emit_mta_diagnostics_warning(
            symbol=symbol,
            l2_analysis=l2_analysis,
            available_tfs=available_tfs,
            alignment_score=alignment_score,
            candle_counts=candle_counts,
            blocker_strs=blocker_strs,
        )

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
                freshness,
                warmup,
                fallback,
                aligned,
                partial_coverage,
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
        mta_diagnostics = _build_mta_diagnostics(
            l2_analysis=l2_analysis,
            available_tfs=available_tfs,
            alignment_score=alignment_score,
            candle_counts=candle_counts,
        )

        # Log constitutional result
        logger.info(
            "[L2] {} constitutional: status={} band={} alignment={:.4f} freshness={} warmup={} fallback={} blockers={}",
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
                "required_alignment": ALIGNMENT_MID_GTE,
                "hierarchy_followed": hierarchy_followed,
                "aligned": aligned,
                "candle_age_seconds": candle_age_seconds,
                "candle_age_by_tf": dict(l2_analysis.get("candle_age_by_tf", {})),
                "candle_counts": dict(candle_counts or {}),
                "required_timeframes": list(REQUIRED_TIMEFRAMES),
                "coverage_target_timeframes": list(COVERAGE_TARGET_TIMEFRAMES),
                "available_timeframes": available_tfs,
                "missing_timeframes": mta_diagnostics["missing_timeframes"],
                "missing_required_timeframes": missing_required,
                "direction_consensus": mta_diagnostics["direction_consensus"],
                "per_tf_bias": dict(mta_diagnostics["per_tf_bias"]),
                "per_tf_strength": dict(mta_diagnostics["per_tf_strength"]),
                "conflict_matrix": list(mta_diagnostics["conflict_matrix"]),
                "primary_conflict": mta_diagnostics["primary_conflict"],
            },
            "mta_diagnostics": mta_diagnostics,
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
