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


class L8BlockerCode(StrEnum):
    UPSTREAM_NOT_CONTINUABLE = "UPSTREAM_NOT_CONTINUABLE"
    REQUIRED_INTEGRITY_SOURCE_MISSING = "REQUIRED_INTEGRITY_SOURCE_MISSING"
    TII_UNAVAILABLE = "TII_UNAVAILABLE"
    TWMS_UNAVAILABLE = "TWMS_UNAVAILABLE"
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


def _score_band(integrity_score: float) -> L8CoherenceBand:
    """Map integrity score to coherence band."""
    if integrity_score >= HIGH_THRESHOLD:
        return L8CoherenceBand.HIGH
    if integrity_score >= MID_THRESHOLD:
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
    source_states = {
        "tii": l8_analysis.get("tii_sym") is not None,
        "twms": l8_analysis.get("twms_score") is not None,
        "components": bool(isinstance(l8_analysis.get("components"), dict) and l8_analysis.get("components")),
    }
    available_sources = [name for name, present in source_states.items() if present]
    missing_sources = [name for name, present in source_states.items() if not present]

    primary_integrity_gap = None
    for blocker in blockers:
        if blocker in (
            L8BlockerCode.INTEGRITY_SCORE_BELOW_MINIMUM,
            L8BlockerCode.TII_UNAVAILABLE,
            L8BlockerCode.TWMS_UNAVAILABLE,
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
        "tii_sym": round(float(l8_analysis.get("tii_sym", 0.0)), 4),
        "twms_score": round(float(l8_analysis.get("twms_score", 0.0)), 4),
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

        # ── Step 2: contract integrity ───────────────────────────────
        blockers.extend(_check_contract(l8_analysis))

        # ── Step 3: integrity source availability ────────────────────
        blockers.extend(_check_integrity_sources(l8_analysis))

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
        band = _score_band(integrity_score)
        rule_hits.append(f"coherence_band={band.value}")
        rule_hits.append(f"integrity_score={integrity_score:.4f}")

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
        if status == L8Status.PASS and fallback == L8FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:  # noqa: SIM102
            if "PRIMARY_SUBSTITUTE_USED" not in warning_codes:
                warning_codes.append("PRIMARY_SUBSTITUTE_USED")

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
            "tii_sym": round(float(l8_analysis.get("tii_sym", 0.0)), 4),
            "twms_score": round(float(l8_analysis.get("twms_score", 0.0)), 4),
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
            "score_numeric": round(integrity_score, 4),
            "features": features,
            "integrity_diagnostics": integrity_diagnostics,
            "routing": routing,
            "audit": audit,
        }
