"""
L8 Constitutional Governor — Strict Mode v1.0.0
================================================

Constitutional sub-gate evaluator for integrity / TII legality.

Implements the frozen L8 spec:
  - Evaluation order: upstream → contract → integrity sources → freshness
    → warmup → fallback → TII validation → integrity score → compress → emit
  - Critical blockers spec (frozen v1)
  - Fallback legality matrix (frozen v1)
  - Freshness / warmup states
  - Integrity score thresholds (frozen baseline v1)
  - Final compression logic (strict mode)

Authority boundary:
  L8 is an integrity / TII legality governor only.
  L8 must never emit direction, execute, trade_valid, position_size, or verdict.
  Hard legality checks run before score band evaluation.
  Always-forward scoring: continuation_allowed is always True.
  L12 evaluates degradation via status/blocker_codes.
  next_legal_targets always includes ["L9"].

Zone: analysis/ — pure read-only analysis, no execution side-effects.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from constitution.adaptive_threshold_governor import get_governor

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# §1  FROZEN ENUMS
# ═══════════════════════════════════════════════════════════════════════════


class L8Status(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L8FreshnessState(StrEnum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class L8WarmupState(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class L8FallbackClass(StrEnum):
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class L8CoherenceBand(StrEnum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class L8IntegrityMode(StrEnum):
    """Source-aware integrity availability mode.

    FULL      → source_completeness >= SOURCE_COMPLETENESS_THRESHOLD
    PARTIAL   → 0 < source_completeness < SOURCE_COMPLETENESS_THRESHOLD
    DEGRADED  → no required integrity sources available
    """

    FULL = "FULL"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"


class L8BlockerCode(StrEnum):
    UPSTREAM_NOT_CONTINUABLE = "UPSTREAM_NOT_CONTINUABLE"
    UPSTREAM_L2_HARD_STOP = "UPSTREAM_L2_HARD_STOP"
    REQUIRED_INTEGRITY_SOURCE_MISSING = "REQUIRED_INTEGRITY_SOURCE_MISSING"
    TII_UNAVAILABLE = "TII_UNAVAILABLE"
    TWMS_UNAVAILABLE = "TWMS_UNAVAILABLE"
    INTEGRITY_SOURCE_INCOMPLETE = "INTEGRITY_SOURCE_INCOMPLETE"
    INTEGRITY_SCORE_BELOW_MINIMUM = "INTEGRITY_SCORE_BELOW_MINIMUM"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"
    INVALID_INTEGRITY_STATE = "INVALID_INTEGRITY_STATE"


# ═══════════════════════════════════════════════════════════════════════════
# §2  FROZEN THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════════

HIGH_THRESHOLD = 0.88
MID_THRESHOLD = 0.75

# ── Source-aware integrity completeness (PR-4) ────────────────────
# Required integrity sources that feed the L8 composite integrity score.
# Completeness = count(available) / len(REQUIRED_INTEGRITY_SOURCES).
# Blueprint P4: HIGH band must be gated by source completeness to prevent
# nil-padding from L7/L9 upstream producing deceptively high integrity.
REQUIRED_INTEGRITY_SOURCES: tuple[str, ...] = ("tii", "twms", "components")
SOURCE_COMPLETENESS_THRESHOLD: float = 0.80

# ── LFS borderline rescue constants (conservative) ───────────────
_ENABLE_L8_LFS_RESCUE: bool = os.getenv("ENABLE_L8_LFS_RESCUE", "0") == "1"
_LFS_RESCUE_SCORE_MIN = 0.72
_LFS_RESCUE_SCORE_MAX = MID_THRESHOLD  # 0.75
_LFS_RESCUE_LRCE_MIN = 0.970
_LFS_RESCUE_DRIFT_MAX = 0.0045
_LFS_RESCUE_GRAD_MAX = 0.005
MIN_SAMPLE_WARN = 10


# ═══════════════════════════════════════════════════════════════════════════
# §3  SUB-GATE HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _score_band(integrity_score: float, *, mid_threshold: float = MID_THRESHOLD) -> L8CoherenceBand:
    """Map integrity score to coherence band."""
    if integrity_score >= HIGH_THRESHOLD:
        return L8CoherenceBand.HIGH
    if integrity_score >= mid_threshold:
        return L8CoherenceBand.MID
    return L8CoherenceBand.LOW


def _can_apply_lfs_borderline_rescue(
    l8_analysis: dict[str, Any],
    integrity_score: float,
    freshness: L8FreshnessState,
    warmup: L8WarmupState,
    fallback: L8FallbackClass,
    blockers: list[L8BlockerCode],
) -> bool:
    """Check whether LFS borderline rescue may promote FAIL → WARN.

    Conditions (ALL must hold):
    - No hard blockers except INTEGRITY_SCORE_BELOW_MINIMUM (which is the
      exact condition rescue is designed to soften)
    - Freshness == FRESH
    - Warmup == READY
    - Fallback is not ILLEGAL
    - Integrity score in narrow borderline window [0.72, 0.75)
    - LFS rescue_eligible == True with strict LRCE/drift/gradient checks
    """
    # Allow INTEGRITY_SCORE_BELOW_MINIMUM — that's the blocker we rescue.
    # Any OTHER blocker → reject.
    hard_blockers = [b for b in blockers if b != L8BlockerCode.INTEGRITY_SCORE_BELOW_MINIMUM]
    if hard_blockers:
        return False
    if freshness != L8FreshnessState.FRESH:
        return False
    if warmup != L8WarmupState.READY:
        return False
    if fallback == L8FallbackClass.ILLEGAL_FALLBACK:
        return False
    if not (_LFS_RESCUE_SCORE_MIN <= integrity_score < _LFS_RESCUE_SCORE_MAX):
        return False

    lfs = l8_analysis.get("lorentzian", {})
    if not isinstance(lfs, dict):
        return False

    return bool(
        lfs.get("rescue_eligible", False)
        and float(lfs.get("lrce", 0.0)) >= _LFS_RESCUE_LRCE_MIN
        and float(lfs.get("drift", 1.0)) <= _LFS_RESCUE_DRIFT_MAX
        and abs(float(lfs.get("gradient_signed", 1.0))) <= _LFS_RESCUE_GRAD_MAX
    )


def _check_upstream(upstream_output: dict[str, Any]) -> list[L8BlockerCode]:
    """Step 1: upstream continuation legality."""
    if not upstream_output:
        return [L8BlockerCode.UPSTREAM_NOT_CONTINUABLE]
    allowed = upstream_output.get(
        "continuation_allowed",
        upstream_output.get("valid", True),
    )
    if not allowed:
        return [L8BlockerCode.UPSTREAM_NOT_CONTINUABLE]
    return []


def _extract_upstream_l2_context(upstream_output: dict[str, Any]) -> dict[str, Any]:
    """Best-effort extraction of L2 constitutional context from upstream payload."""
    direct = upstream_output.get("l2_context")
    if isinstance(direct, dict):
        constitutional = direct.get("constitutional")
        if isinstance(constitutional, dict):
            return constitutional
        return direct

    nested = upstream_output.get("phase1_layer_results")
    if isinstance(nested, dict):
        l2_layer = nested.get("L2")
        if isinstance(l2_layer, dict):
            constitutional = l2_layer.get("constitutional")
            if isinstance(constitutional, dict):
                return constitutional
            return l2_layer

    phase_results = upstream_output.get("phase_results")
    if isinstance(phase_results, dict):
        phase1 = phase_results.get("PHASE_1")
        if isinstance(phase1, dict):
            layer_results = phase1.get("layer_results")
            if isinstance(layer_results, dict):
                l2_layer = layer_results.get("L2")
                if isinstance(l2_layer, dict):
                    constitutional = l2_layer.get("constitutional")
                    if isinstance(constitutional, dict):
                        return constitutional
                    return l2_layer

    return {}


def _classify_upstream_l2_dependency(upstream_output: dict[str, Any]) -> tuple[str, list[str]]:
    """Classify upstream L2 dependency severity for L8 diagnostics."""
    l2_context = _extract_upstream_l2_context(upstream_output)
    if not l2_context:
        return "NONE", []

    status = str(l2_context.get("status", "")).upper()
    hard_blockers = [str(code) for code in l2_context.get("hard_blockers", [])]
    soft_blockers = [str(code) for code in l2_context.get("soft_blockers", l2_context.get("warning_codes", []))]
    hard_stop = bool(l2_context.get("hard_stop", False))
    advisory_continuation = bool(l2_context.get("advisory_continuation", l2_context.get("continuation_allowed", True)))

    if hard_stop or hard_blockers or (status == "FAIL" and not advisory_continuation):
        return "HARD_STOP", hard_blockers or ["UPSTREAM_L2_HARD_STOP"]
    if status == "WARN" or soft_blockers:
        return "WEAK_EVIDENCE", soft_blockers
    return "NONE", []


def _check_contract(l8_analysis: dict[str, Any]) -> list[L8BlockerCode]:
    """Step 2: contract payload integrity."""
    required = ("integrity", "valid", "tii_sym")
    if not l8_analysis:
        return [L8BlockerCode.CONTRACT_PAYLOAD_MALFORMED]
    if not any(k in l8_analysis for k in required):
        return [L8BlockerCode.CONTRACT_PAYLOAD_MALFORMED]
    return []


def _check_integrity_sources(l8_analysis: dict[str, Any]) -> list[L8BlockerCode]:
    """Step 3: required integrity source availability."""
    blockers: list[L8BlockerCode] = []

    # TII must be available
    tii_sym = l8_analysis.get("tii_sym")
    if tii_sym is None and not l8_analysis.get("valid", False):
        blockers.append(L8BlockerCode.TII_UNAVAILABLE)

    # TWMS must be available
    twms = l8_analysis.get("twms_score")
    if twms is None and not l8_analysis.get("valid", False):
        blockers.append(L8BlockerCode.TWMS_UNAVAILABLE)

    return blockers


def _eval_freshness(l8_analysis: dict[str, Any]) -> L8FreshnessState:
    """Step 4: freshness governance."""
    explicit = l8_analysis.get("freshness_state")
    if explicit:
        try:
            return L8FreshnessState(str(explicit))
        except ValueError:
            pass

    # Infer from data characteristics
    note = str(l8_analysis.get("note", ""))
    if "minimal_fallback" in note:
        return L8FreshnessState.DEGRADED
    if "stale" in note.lower() or "preserved" in note.lower():
        return L8FreshnessState.STALE_PRESERVED

    # If we have valid TII computation → FRESH
    if l8_analysis.get("valid", False) and l8_analysis.get("tii_sym", 0.0) > 0:
        return L8FreshnessState.FRESH

    return L8FreshnessState.DEGRADED


def _eval_warmup(l8_analysis: dict[str, Any]) -> L8WarmupState:
    """Step 5: warmup state."""
    explicit = l8_analysis.get("warmup_state")
    if explicit:
        try:
            return L8WarmupState(str(explicit))
        except ValueError:
            pass

    # If valid result with decent TII → READY
    if l8_analysis.get("valid", False):
        components = l8_analysis.get("components", {})
        if components and len(components) >= 3:
            return L8WarmupState.READY
        if l8_analysis.get("tii_sym", 0.0) > 0:
            return L8WarmupState.PARTIAL
    return L8WarmupState.INSUFFICIENT


def _eval_fallback(l8_analysis: dict[str, Any]) -> L8FallbackClass:
    """Step 6: fallback legality classification."""
    explicit = l8_analysis.get("fallback_class")
    if explicit:
        try:
            return L8FallbackClass(str(explicit))
        except ValueError:
            pass

    note = str(l8_analysis.get("note", ""))
    if "minimal_fallback" in note:
        return L8FallbackClass.LEGAL_EMERGENCY_PRESERVE
    if l8_analysis.get("core_enhanced", False):
        return L8FallbackClass.NO_FALLBACK
    if "computed_vwap" in l8_analysis and l8_analysis.get("computed_vwap", 0.0) > 0:
        # Used fallback estimators (VWAP/energy/bias estimated from closes)
        return L8FallbackClass.LEGAL_PRIMARY_SUBSTITUTE
    return L8FallbackClass.NO_FALLBACK


def _check_tii_validation(l8_analysis: dict[str, Any]) -> tuple[list[L8BlockerCode], list[str]]:
    """Step 7: TII validation and gate status."""
    blockers: list[L8BlockerCode] = []
    warnings: list[str] = []

    gate_status = str(l8_analysis.get("gate_status", "CLOSED")).upper()
    gate_passed = l8_analysis.get("gate_passed", False)
    tii_status = str(l8_analysis.get("tii_status", ""))

    if gate_status == "CLOSED" and not gate_passed:
        warnings.append("TII_GATE_CLOSED")

    if tii_status in ("WEAK", "VERY_WEAK"):
        warnings.append(f"TII_STATUS_{tii_status}")

    # Check for invalid integrity state
    integrity = l8_analysis.get("integrity", 0.0)
    tii_sym = l8_analysis.get("tii_sym", 0.0)
    if l8_analysis.get("valid", False) and isinstance(tii_sym, (int, float)) and (tii_sym < 0 or tii_sym > 1.0):
        blockers.append(L8BlockerCode.INVALID_INTEGRITY_STATE)
    if l8_analysis.get("valid", False) and isinstance(integrity, (int, float)):  # noqa: SIM102
        if integrity < 0 or integrity > 1.0:
            blockers.append(L8BlockerCode.INVALID_INTEGRITY_STATE)

    return blockers, warnings


def _derive_integrity_score(l8_analysis: dict[str, Any]) -> float:
    """Extract integrity score as 0-1 float."""
    integrity = l8_analysis.get("integrity", 0.0)
    if isinstance(integrity, (int, float)):
        return max(0.0, min(1.0, float(integrity)))
    return 0.0


def _integrity_source_flags(l8_analysis: dict[str, Any]) -> dict[str, bool]:
    """Derive per-source readiness flags for REQUIRED_INTEGRITY_SOURCES.

    An explicit ``integrity_sources`` dict on the analysis payload overrides
    inferred flags (mirrors L9's ``structure_sources`` escape hatch).
    Otherwise flags are inferred from raw fields:
      - tii        → ``tii_sym`` is not None
      - twms       → ``twms_score`` is not None
      - components → ``components`` is a non-empty dict
    """
    explicit = l8_analysis.get("integrity_sources")
    if isinstance(explicit, dict):
        return {name: bool(explicit.get(name, False)) for name in REQUIRED_INTEGRITY_SOURCES}

    components = l8_analysis.get("components")
    return {
        "tii": l8_analysis.get("tii_sym") is not None,
        "twms": l8_analysis.get("twms_score") is not None,
        "components": bool(isinstance(components, dict) and components),
    }


def _compute_source_completeness(flags: dict[str, bool]) -> float:
    """Return ratio of available required integrity sources in [0.0, 1.0]."""
    total = len(REQUIRED_INTEGRITY_SOURCES)
    if total == 0:
        return 1.0
    available = sum(1 for name in REQUIRED_INTEGRITY_SOURCES if flags.get(name, False))
    return round(available / total, 4)


def _derive_integrity_mode(completeness: float) -> L8IntegrityMode:
    """Map source completeness ratio to an integrity mode."""
    if completeness >= SOURCE_COMPLETENESS_THRESHOLD:
        return L8IntegrityMode.FULL
    if completeness > 0.0:
        return L8IntegrityMode.PARTIAL
    return L8IntegrityMode.DEGRADED


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce value to float, tolerating None/non-numeric inputs.

    PR-4: required because source-aware integrity formally accepts missing
    (None) tii_sym / twms_score upstream, which previously raised TypeError
    in diagnostics / features assembly.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_integrity_diagnostics(
    *,
    l8_analysis: dict[str, Any],
    blockers: list[L8BlockerCode],
    tii_warnings: list[str],
    integrity_score: float,
    band: L8CoherenceBand,
    sample_count: int,
) -> dict[str, Any]:
    """Assemble audit-friendly L8 diagnostics without affecting legality."""
    source_states = _integrity_source_flags(l8_analysis)
    available_sources = [name for name in REQUIRED_INTEGRITY_SOURCES if source_states.get(name)]
    missing_sources = [name for name in REQUIRED_INTEGRITY_SOURCES if not source_states.get(name)]
    source_completeness = _compute_source_completeness(source_states)
    integrity_mode = _derive_integrity_mode(source_completeness)

    primary_integrity_gap = None
    for blocker in blockers:
        if blocker in (
            L8BlockerCode.INTEGRITY_SCORE_BELOW_MINIMUM,
            L8BlockerCode.TII_UNAVAILABLE,
            L8BlockerCode.TWMS_UNAVAILABLE,
            L8BlockerCode.INTEGRITY_SOURCE_INCOMPLETE,
            L8BlockerCode.WARMUP_INSUFFICIENT,
            L8BlockerCode.INVALID_INTEGRITY_STATE,
        ):
            primary_integrity_gap = blocker.value
            break

    return {
        "integrity_score": round(integrity_score, 4),
        "required_integrity": MID_THRESHOLD,
        "coherence_band": band.value,
        "primary_integrity_gap": primary_integrity_gap,
        "available_sources": available_sources,
        "missing_sources": missing_sources,
        "required_sources": list(REQUIRED_INTEGRITY_SOURCES),
        "source_completeness": source_completeness,
        "source_completeness_threshold": SOURCE_COMPLETENESS_THRESHOLD,
        "integrity_mode": integrity_mode.value,
        "tii_sym": round(_safe_float(l8_analysis.get("tii_sym")), 4),
        "twms_score": round(_safe_float(l8_analysis.get("twms_score")), 4),
        "gate_status": str(l8_analysis.get("gate_status", "CLOSED")).upper(),
        "gate_passed": bool(l8_analysis.get("gate_passed", False)),
        "component_count": sample_count,
        "warn_component_floor": MIN_SAMPLE_WARN,
        "fallback_note": str(l8_analysis.get("note", "")),
        "warnings": list(tii_warnings),
    }


# ═══════════════════════════════════════════════════════════════════════════
# §4  COMPRESSION LOGIC
# ═══════════════════════════════════════════════════════════════════════════


def _compress_status(
    blockers: list[L8BlockerCode],
    band: L8CoherenceBand,
    freshness: L8FreshnessState,
    warmup: L8WarmupState,
    fallback: L8FallbackClass,
    tii_warnings: list[str],
    integrity_score: float,
    sample_count: int,
) -> L8Status:
    """Deterministic status compression per spec."""
    # Any blocker → FAIL
    if blockers:
        return L8Status.FAIL

    # LOW band → FAIL (integrity score below minimum)
    if band == L8CoherenceBand.LOW:
        return L8Status.FAIL

    # Check for clean PASS envelope
    is_clean = (
        freshness == L8FreshnessState.FRESH
        and warmup == L8WarmupState.READY
        and fallback in (L8FallbackClass.NO_FALLBACK, L8FallbackClass.LEGAL_PRIMARY_SUBSTITUTE)
        and band == L8CoherenceBand.HIGH
        and not any("GATE_CLOSED" in w for w in tii_warnings)
        and sample_count >= MIN_SAMPLE_WARN
    )
    if is_clean:
        return L8Status.PASS

    # Legal degraded envelope → WARN
    is_legal_warn = (
        freshness
        in (
            L8FreshnessState.FRESH,
            L8FreshnessState.STALE_PRESERVED,
            L8FreshnessState.DEGRADED,
        )
        and warmup in (L8WarmupState.READY, L8WarmupState.PARTIAL)
        and fallback
        in (
            L8FallbackClass.NO_FALLBACK,
            L8FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
            L8FallbackClass.LEGAL_EMERGENCY_PRESERVE,
        )
        and band in (L8CoherenceBand.HIGH, L8CoherenceBand.MID)
    )
    if is_legal_warn:
        return L8Status.WARN

    return L8Status.FAIL


def _collect_warning_codes(
    freshness: L8FreshnessState,
    warmup: L8WarmupState,
    fallback: L8FallbackClass,
    band: L8CoherenceBand,
    tii_warnings: list[str],
    sample_count: int,
    gate_status: str,
) -> list[str]:
    """Collect non-fatal warning codes."""
    codes: list[str] = []
    if freshness == L8FreshnessState.STALE_PRESERVED:
        codes.append("STALE_PRESERVED_CONTEXT")
    if freshness == L8FreshnessState.DEGRADED:
        codes.append("DEGRADED_CONTEXT")
    if warmup == L8WarmupState.PARTIAL:
        codes.append("PARTIAL_WARMUP")
    if fallback == L8FallbackClass.LEGAL_EMERGENCY_PRESERVE:
        codes.append("LEGAL_EMERGENCY_PRESERVE_USED")
    if fallback == L8FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
        codes.append("PRIMARY_SUBSTITUTE_USED")
    if band == L8CoherenceBand.MID:
        codes.append("INTEGRITY_MID_BAND")
    if sample_count < MIN_SAMPLE_WARN and sample_count > 0:
        codes.append("LOW_SAMPLE_COUNT")
    if gate_status == "CLOSED":
        codes.append("TII_GATE_CLOSED")
    codes.extend(tii_warnings)
    return codes


# ═══════════════════════════════════════════════════════════════════════════
# §5  GOVERNOR
# ═══════════════════════════════════════════════════════════════════════════


class L8ConstitutionalGovernor:
    """Frozen v1 constitutional governor for L8 integrity legality."""

    VERSION = "1.0.0"

    def evaluate(
        self,
        l8_analysis: dict[str, Any],
        upstream_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run all sub-gates and emit canonical L8 constitutional envelope.

        Parameters
        ----------
        l8_analysis : dict
            Raw output from L8TIIIntegrityAnalyzer.analyze() or L8PipelineAdapter.analyze().
        upstream_output : dict | None
            Output from the previous layer (L7).
            Used to check upstream continuation legality.
        """
        timestamp = datetime.now(UTC).isoformat()
        input_ref = l8_analysis.get("symbol", "UNKNOWN")
        upstream = upstream_output or {"valid": True, "continuation_allowed": True}

        blockers: list[L8BlockerCode] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        # ── Step 1: upstream legality ────────────────────────────────
        blockers.extend(_check_upstream(upstream))
        upstream_l2_state, upstream_l2_codes = _classify_upstream_l2_dependency(upstream)
        if upstream_l2_state == "HARD_STOP":
            blockers.append(L8BlockerCode.UPSTREAM_L2_HARD_STOP)
        if upstream_l2_state != "NONE":
            rule_hits.append(f"upstream_l2_state={upstream_l2_state}")

        # ── Step 2: contract integrity ───────────────────────────────
        blockers.extend(_check_contract(l8_analysis))

        # ── Step 3: integrity source availability ────────────────────
        blockers.extend(_check_integrity_sources(l8_analysis))

        # ── Step 3b: source completeness (PR-4 source-aware integrity) ─
        # Guard HIGH band from nil-padded upstream (L7/L9) by requiring
        # required integrity sources to be sufficiently complete.
        # Only fires when upstream didn't already report missing TII/TWMS
        # so the new blocker is strictly a "valid-but-incomplete" signal.
        source_flags = _integrity_source_flags(l8_analysis)
        source_completeness = _compute_source_completeness(source_flags)
        integrity_mode = _derive_integrity_mode(source_completeness)
        if (
            l8_analysis.get("valid", False)
            and source_completeness < SOURCE_COMPLETENESS_THRESHOLD
            and L8BlockerCode.TII_UNAVAILABLE not in blockers
            and L8BlockerCode.TWMS_UNAVAILABLE not in blockers
        ):
            blockers.append(L8BlockerCode.INTEGRITY_SOURCE_INCOMPLETE)
        rule_hits.append(f"integrity_mode={integrity_mode.value}")
        rule_hits.append(f"source_completeness={source_completeness:.4f}")

        # ── Step 4: freshness ────────────────────────────────────────
        freshness = _eval_freshness(l8_analysis)
        if freshness == L8FreshnessState.NO_PRODUCER:
            blockers.append(L8BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL)
        rule_hits.append(f"freshness_state={freshness.value}")

        # ── Step 5: warmup ───────────────────────────────────────────
        warmup = _eval_warmup(l8_analysis)
        if warmup == L8WarmupState.INSUFFICIENT:
            blockers.append(L8BlockerCode.WARMUP_INSUFFICIENT)
        rule_hits.append(f"warmup_state={warmup.value}")

        # ── Step 6: fallback legality ────────────────────────────────
        fallback = _eval_fallback(l8_analysis)
        if fallback == L8FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(L8BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED)
        rule_hits.append(f"fallback_class={fallback.value}")

        # ── Step 7: TII validation ──────────────────────────────────
        tii_blockers, tii_warnings = _check_tii_validation(l8_analysis)
        blockers.extend(tii_blockers)

        # ── Step 8: integrity score band ─────────────────────────────
        integrity_score = _derive_integrity_score(l8_analysis)
        adaptive_threshold = get_governor().get_adjusted(
            layer="L8",
            metric="integrity",
            base_threshold=MID_THRESHOLD,
            frpc_data=upstream.get("frpc_snapshot", l8_analysis.get("frpc_snapshot", {})),
            source_completeness=source_completeness,
            regime_tag=upstream.get("regime_tag"),
            rollout_key=input_ref,
        )
        effective_mid_threshold = adaptive_threshold.adjusted
        band = _score_band(integrity_score, mid_threshold=effective_mid_threshold)
        rule_hits.append(f"coherence_band={band.value}")
        rule_hits.append(f"integrity_score={integrity_score:.4f}")
        rule_hits.append(f"adaptive_mode={adaptive_threshold.mode}")
        rule_hits.append(f"effective_mid_threshold={effective_mid_threshold:.4f}")

        # LOW band with valid result → add blocker
        if band == L8CoherenceBand.LOW and not blockers and l8_analysis.get("valid", False):
            blockers.append(L8BlockerCode.INTEGRITY_SCORE_BELOW_MINIMUM)

        # ── Step 9: sample count ─────────────────────────────────────
        components = l8_analysis.get("components", {})
        sample_count = len(components) if isinstance(components, dict) else 0
        gate_status = str(l8_analysis.get("gate_status", "CLOSED")).upper()

        # ── Step 10: compress status ─────────────────────────────────
        status = _compress_status(
            blockers,
            band,
            freshness,
            warmup,
            fallback,
            tii_warnings,
            integrity_score,
            sample_count,
        )

        if upstream_l2_state == "WEAK_EVIDENCE" and status == L8Status.PASS:
            status = L8Status.WARN
            notes.append("L2 weak evidence downgraded L8 envelope from PASS to WARN")

        # Always-forward: continuation_allowed is always True.
        # L12 evaluates degradation via status/blocker_codes.
        continuation_allowed = True
        next_targets = ["L9"]
        integrity_diagnostics = _build_integrity_diagnostics(
            l8_analysis=l8_analysis,
            blockers=blockers,
            tii_warnings=tii_warnings,
            integrity_score=integrity_score,
            band=band,
            sample_count=sample_count,
        )

        # ── Step 11: warning codes ───────────────────────────────────
        warning_codes = _collect_warning_codes(
            freshness,
            warmup,
            fallback,
            band,
            tii_warnings,
            sample_count,
            gate_status,
        )
        if upstream_l2_state == "WEAK_EVIDENCE":
            warning_codes.append("UPSTREAM_L2_WEAK_EVIDENCE")
        if status == L8Status.PASS and fallback == L8FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:  # noqa: SIM102
            if "PRIMARY_SUBSTITUTE_USED" not in warning_codes:
                warning_codes.append("PRIMARY_SUBSTITUTE_USED")

        # Source-aware integrity warnings (PR-4). The blocker above already
        # forces FAIL when valid-but-incomplete; these codes keep the
        # diagnostic trail explicit in both FAIL and degraded envelopes.
        if integrity_mode == L8IntegrityMode.PARTIAL:
            warning_codes.append("PARTIAL_INTEGRITY_SOURCES")
        elif integrity_mode == L8IntegrityMode.DEGRADED:
            warning_codes.append("INTEGRITY_SOURCES_DEGRADED")

        # ── Step 11b: LFS borderline rescue (guarded by feature flag) ─
        if (
            _ENABLE_L8_LFS_RESCUE
            and status == L8Status.FAIL
            and _can_apply_lfs_borderline_rescue(
                l8_analysis,
                integrity_score,
                freshness,
                warmup,
                fallback,
                blockers,
            )
        ):
            status = L8Status.WARN
            continuation_allowed = True
            next_targets = ["L9"]
            warning_codes.append("LFS_BORDERLINE_RESCUE")
            notes.append(
                f"LFS rescue applied: score={integrity_score:.4f} "
                f"lrce={l8_analysis.get('lorentzian', {}).get('lrce', 0):.4f}"
            )
            logger.info(
                "[L8-GOV] %s LFS borderline rescue: score=%.4f → status promoted FAIL→WARN",
                input_ref,
                integrity_score,
            )

        # ── Step 12: assemble features ───────────────────────────────
        features = {
            "integrity_score": round(integrity_score, 4),
            "effective_mid_threshold": round(effective_mid_threshold, 4),
            "tii_sym": round(_safe_float(l8_analysis.get("tii_sym")), 4),
            "twms_score": round(_safe_float(l8_analysis.get("twms_score")), 4),
            "tii_status": str(l8_analysis.get("tii_status", "UNKNOWN")),
            "tii_grade": str(l8_analysis.get("tii_grade", "UNKNOWN")),
            "gate_passed": bool(l8_analysis.get("gate_passed", False)),
            "gate_status": gate_status,
            "core_enhanced": bool(l8_analysis.get("core_enhanced", False)),
            "component_count": sample_count,
            "feature_hash": f"L8_{band.value}_{status.value}_{int(round(integrity_score * 100))}",
        }

        routing = {
            "source_used": [s for s in ["tii", "twms", "integrity"] if l8_analysis.get("valid", False)],
            "fallback_used": fallback != L8FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
            "upstream_l2_state": upstream_l2_state,
            "upstream_l2_codes": upstream_l2_codes,
            "adaptive_threshold": adaptive_threshold.to_dict(),
        }

        logger.info(
            "[L8-GOV] %s status=%s band=%s integrity=%.4f blockers=%d warnings=%d",
            input_ref,
            status.value,
            band.value,
            integrity_score,
            len(blockers),
            len(warning_codes),
        )

        return {
            "layer": "L8",
            "layer_version": self.VERSION,
            "timestamp": timestamp,
            "input_ref": input_ref,
            "status": status.value,
            "continuation_allowed": continuation_allowed,
            "blocker_codes": [b.value for b in dict.fromkeys(blockers)],
            "warning_codes": list(dict.fromkeys(warning_codes)),
            "fallback_class": fallback.value,
            "freshness_state": freshness.value,
            "warmup_state": warmup.value,
            "coherence_band": band.value,
            "integrity_mode": integrity_mode.value,
            "source_completeness": source_completeness,
            "score_numeric": round(integrity_score, 4),
            "adaptive_threshold_audit": adaptive_threshold.to_dict(),
            "features": features,
            "integrity_diagnostics": integrity_diagnostics,
            "routing": routing,
            "audit": audit,
        }
