"""
L9 Constitutional Governor — Strict Mode v1.0.0
================================================

Constitutional sub-gate evaluator for structure / entry-timing legality.

Implements the frozen L9 spec:
  - Evaluation order: upstream → contract → structure sources → freshness
    → warmup → fallback → SMC validation → structure score → compress → emit
  - Critical blockers spec (frozen v1)
  - Fallback legality matrix (frozen v1)
  - Freshness / warmup states
  - Structure score thresholds (frozen baseline v1)
  - Final compression logic (strict mode)

Authority boundary:
  L9 is a structure / entry-timing legality governor only.
  L9 must never emit direction, execute, trade_valid, position_size, or verdict.
  Hard legality checks run before score band evaluation.
  Always-forward scoring: continuation_allowed is always True.
  L12 evaluates degradation via status/blocker_codes.
  next_legal_targets always includes ["PHASE_4"].

Zone: analysis/ — pure read-only analysis, no execution side-effects.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from constitution.adaptive_threshold_governor import get_governor

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# §1  FROZEN ENUMS
# ═══════════════════════════════════════════════════════════════════════════


class L9Status(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L9FreshnessState(StrEnum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class L9WarmupState(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class L9FallbackClass(StrEnum):
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class L9CoherenceBand(StrEnum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class L9BlockerCode(StrEnum):
    UPSTREAM_NOT_CONTINUABLE = "UPSTREAM_NOT_CONTINUABLE"
    REQUIRED_STRUCTURE_SOURCE_MISSING = "REQUIRED_STRUCTURE_SOURCE_MISSING"
    SMC_UNAVAILABLE = "SMC_UNAVAILABLE"
    LIQUIDITY_DATA_UNAVAILABLE = "LIQUIDITY_DATA_UNAVAILABLE"
    STRUCTURE_SCORE_BELOW_MINIMUM = "STRUCTURE_SCORE_BELOW_MINIMUM"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"
    INVALID_STRUCTURE_STATE = "INVALID_STRUCTURE_STATE"


# ═══════════════════════════════════════════════════════════════════════════
# §2  FROZEN THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════════

HIGH_THRESHOLD = 0.80
MID_THRESHOLD = 0.65
MIN_SAMPLE_WARN = 3
REQUIRED_STRUCTURE_SOURCES: tuple[str, ...] = ("smc", "liquidity", "divergence")


# ═══════════════════════════════════════════════════════════════════════════
# §3  SUB-GATE HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _score_band(structure_score: float, *, mid_threshold: float = MID_THRESHOLD) -> L9CoherenceBand:
    """Map structure score to coherence band."""
    if structure_score >= HIGH_THRESHOLD:
        return L9CoherenceBand.HIGH
    if structure_score >= mid_threshold:
        return L9CoherenceBand.MID
    return L9CoherenceBand.LOW


def _check_upstream(upstream_output: dict[str, Any]) -> list[L9BlockerCode]:
    """Step 1: upstream continuation legality."""
    if not upstream_output:
        return [L9BlockerCode.UPSTREAM_NOT_CONTINUABLE]
    allowed = upstream_output.get(
        "continuation_allowed",
        upstream_output.get("valid", True),
    )
    if not allowed:
        return [L9BlockerCode.UPSTREAM_NOT_CONTINUABLE]
    return []


def _check_contract(l9_analysis: dict[str, Any]) -> list[L9BlockerCode]:
    """Step 2: contract payload integrity."""
    required = ("smc_score", "valid", "confidence")
    if not l9_analysis:
        return [L9BlockerCode.CONTRACT_PAYLOAD_MALFORMED]
    if not any(k in l9_analysis for k in required):
        return [L9BlockerCode.CONTRACT_PAYLOAD_MALFORMED]
    return []


def _check_structure_sources(l9_analysis: dict[str, Any]) -> list[L9BlockerCode]:
    """Step 3: required structure source availability."""
    blockers: list[L9BlockerCode] = []

    # SMC signal must be evaluable
    if not l9_analysis.get("valid", False):
        reason = str(l9_analysis.get("reason", ""))
        if reason in ("no_structure_data", "invalid_structure"):
            blockers.append(L9BlockerCode.REQUIRED_STRUCTURE_SOURCE_MISSING)
        elif "smc" not in l9_analysis:
            blockers.append(L9BlockerCode.SMC_UNAVAILABLE)

    return blockers


def _eval_freshness(l9_analysis: dict[str, Any]) -> L9FreshnessState:
    """Step 4: freshness governance."""
    explicit = l9_analysis.get("freshness_state")
    if explicit:
        try:
            return L9FreshnessState(str(explicit))
        except ValueError:
            pass

    reason = str(l9_analysis.get("reason", ""))
    if "no_structure_data" in reason:
        return L9FreshnessState.NO_PRODUCER

    # If valid with SMC data → FRESH
    if l9_analysis.get("valid", False) and l9_analysis.get("smc_score", 0) > 0:
        return L9FreshnessState.FRESH

    # Valid but no SMC signal → DEGRADED
    if l9_analysis.get("valid", False):
        return L9FreshnessState.DEGRADED

    return L9FreshnessState.DEGRADED


def _eval_warmup(l9_analysis: dict[str, Any]) -> L9WarmupState:
    """Step 5: warmup state."""
    explicit = l9_analysis.get("warmup_state")
    if explicit:
        try:
            return L9WarmupState(str(explicit))
        except ValueError:
            pass

    if not l9_analysis.get("valid", False):
        return L9WarmupState.INSUFFICIENT

    # Count SMC detection features present
    smc_features = sum(
        [
            bool(l9_analysis.get("bos_detected", False)),
            bool(l9_analysis.get("choch_detected", False)),
            bool(l9_analysis.get("fvg_present", False)),
            bool(l9_analysis.get("ob_present", False)),
            bool(l9_analysis.get("sweep_detected", False)),
        ]
    )

    if smc_features >= 2:
        return L9WarmupState.READY
    if l9_analysis.get("smc", False) or smc_features >= 1:
        return L9WarmupState.PARTIAL
    return L9WarmupState.INSUFFICIENT


def _eval_fallback(l9_analysis: dict[str, Any]) -> L9FallbackClass:
    """Step 6: fallback legality classification."""
    explicit = l9_analysis.get("fallback_class")
    if explicit:
        try:
            return L9FallbackClass(str(explicit))
        except ValueError:
            pass

    reason = str(l9_analysis.get("reason", ""))
    if "no_structure_data" in reason:
        return L9FallbackClass.LEGAL_EMERGENCY_PRESERVE
    if "invalid_structure" in reason:
        return L9FallbackClass.LEGAL_EMERGENCY_PRESERVE
    return L9FallbackClass.NO_FALLBACK


def _check_smc_validation(l9_analysis: dict[str, Any]) -> tuple[list[L9BlockerCode], list[str]]:
    """Step 7: SMC validation and quality checks."""
    blockers: list[L9BlockerCode] = []
    warnings: list[str] = []

    # Check confidence quality
    confidence = float(l9_analysis.get("confidence", 0.0))
    if confidence == 0.0 and l9_analysis.get("valid", False):
        warnings.append("ZERO_CONFIDENCE")

    # Check for no SMC signal
    smc = l9_analysis.get("smc", False)
    if not smc and l9_analysis.get("valid", False):
        warnings.append("NO_SMC_SIGNAL")

    # Divergence quality
    dvg_conf = float(l9_analysis.get("dvg_confidence", 0.0))
    if dvg_conf == 0.0:
        warnings.append("NO_DIVERGENCE_DATA")

    # Liquidity quality
    liq_score = float(l9_analysis.get("liquidity_score", 0.0))
    if liq_score == 0.0:
        warnings.append("NO_LIQUIDITY_DATA")

    # Check for invalid structure state
    smc_score = l9_analysis.get("smc_score", 0)
    if isinstance(smc_score, (int, float)) and l9_analysis.get("valid", False):  # noqa: SIM102
        if smc_score < 0 or smc_score > 100:
            blockers.append(L9BlockerCode.INVALID_STRUCTURE_STATE)

    return blockers, warnings


def _derive_structure_score(l9_analysis: dict[str, Any]) -> float:
    """Extract structure score as 0-1 float."""
    # smc_score is 0-100, convert to 0-1
    smc_score = l9_analysis.get("smc_score", 0)
    if isinstance(smc_score, (int, float)):
        score_01 = float(smc_score) / 100.0
        return max(0.0, min(1.0, score_01))
    return 0.0


def _coerce_float(value: Any) -> float:
    """Best-effort float coercion for diagnostics fields."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _structure_source_flags(l9_analysis: dict[str, Any]) -> dict[str, bool]:
    """Derive structure source readiness from the current L9 contract."""
    explicit = l9_analysis.get("structure_sources")
    if isinstance(explicit, dict):
        return {str(name): bool(state) for name, state in explicit.items()}

    return {
        "smc": bool(l9_analysis.get("smc", False)),
        "liquidity": _coerce_float(l9_analysis.get("liquidity_score", 0.0)) > 0.0,
        "divergence": _coerce_float(l9_analysis.get("dvg_confidence", 0.0)) > 0.0,
    }


def _compute_source_completeness(l9_analysis: dict[str, Any]) -> float:
    """Return ratio of available required structure sources in [0.0, 1.0]."""
    flags = _structure_source_flags(l9_analysis)
    available = sum(1 for name in REQUIRED_STRUCTURE_SOURCES if flags.get(name, False))
    return round(available / len(REQUIRED_STRUCTURE_SOURCES), 4)


def _build_structure_diagnostics(
    *,
    l9_analysis: dict[str, Any],
    blockers: list[L9BlockerCode],
    warmup: L9WarmupState,
    structure_score: float,
    smc_feature_count: int,
) -> dict[str, Any]:
    """Assemble audit-friendly L9 diagnostics without affecting legality."""
    source_flags = _structure_source_flags(l9_analysis)
    required_sources = list(REQUIRED_STRUCTURE_SOURCES)
    available_sources = [name for name in required_sources if source_flags.get(name, False)]
    missing_sources = [name for name in required_sources if name not in available_sources]

    warmup_required_bars = l9_analysis.get("warmup_required_bars", {})
    if not isinstance(warmup_required_bars, dict):
        warmup_required_bars = {}

    warmup_available_bars = l9_analysis.get("warmup_available_bars", {})
    if not isinstance(warmup_available_bars, dict):
        warmup_available_bars = {}

    explicit_builder_state = l9_analysis.get("source_builder_state")
    if isinstance(explicit_builder_state, str) and explicit_builder_state.strip():
        source_builder_state = explicit_builder_state.strip()
    elif not available_sources:
        source_builder_state = "not_ready"
    elif missing_sources or warmup == L9WarmupState.INSUFFICIENT:
        source_builder_state = "partial"
    else:
        source_builder_state = "ready"

    primary_structure_gap = blockers[0].value if blockers else None
    source_diagnostics = l9_analysis.get("source_diagnostics", {})
    if not isinstance(source_diagnostics, dict):
        source_diagnostics = {}

    publisher_metadata = l9_analysis.get("publisher_metadata", {})
    if not isinstance(publisher_metadata, dict):
        publisher_metadata = {}

    return {
        "required_sources": required_sources,
        "available_sources": available_sources,
        "missing_sources": missing_sources,
        "warmup_required_bars": warmup_required_bars,
        "warmup_available_bars": warmup_available_bars,
        "source_builder_state": source_builder_state,
        "source_diagnostics": source_diagnostics,
        "publisher_metadata": publisher_metadata,
        "primary_structure_gap": primary_structure_gap,
        "structure_score_components": {
            "smc_score": int(_coerce_float(l9_analysis.get("smc_score", 0.0))),
            "liquidity_score": round(_coerce_float(l9_analysis.get("liquidity_score", 0.0)), 4),
            "dvg_confidence": round(_coerce_float(l9_analysis.get("dvg_confidence", 0.0)), 4),
            "confidence": round(_coerce_float(l9_analysis.get("confidence", 0.0)), 4),
            "smc_feature_count": smc_feature_count,
            "structure_score": round(structure_score, 4),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# §4  COMPRESSION LOGIC
# ═══════════════════════════════════════════════════════════════════════════


def _compress_status(
    blockers: list[L9BlockerCode],
    band: L9CoherenceBand,
    freshness: L9FreshnessState,
    warmup: L9WarmupState,
    fallback: L9FallbackClass,
    smc_warnings: list[str],
    structure_score: float,
    smc_feature_count: int,
) -> L9Status:
    """Deterministic status compression per spec."""
    # Any blocker → FAIL
    if blockers:
        return L9Status.FAIL

    # LOW band → FAIL (structure score below minimum)
    if band == L9CoherenceBand.LOW:
        return L9Status.FAIL

    # Check for clean PASS envelope
    is_clean = (
        freshness == L9FreshnessState.FRESH
        and warmup == L9WarmupState.READY
        and fallback in (L9FallbackClass.NO_FALLBACK, L9FallbackClass.LEGAL_PRIMARY_SUBSTITUTE)
        and band == L9CoherenceBand.HIGH
        and "NO_SMC_SIGNAL" not in smc_warnings
        and smc_feature_count >= MIN_SAMPLE_WARN
    )
    if is_clean:
        return L9Status.PASS

    # Legal degraded envelope → WARN
    is_legal_warn = (
        freshness
        in (
            L9FreshnessState.FRESH,
            L9FreshnessState.STALE_PRESERVED,
            L9FreshnessState.DEGRADED,
        )
        and warmup in (L9WarmupState.READY, L9WarmupState.PARTIAL)
        and fallback
        in (
            L9FallbackClass.NO_FALLBACK,
            L9FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
            L9FallbackClass.LEGAL_EMERGENCY_PRESERVE,
        )
        and band in (L9CoherenceBand.HIGH, L9CoherenceBand.MID)
    )
    if is_legal_warn:
        return L9Status.WARN

    return L9Status.FAIL


def _collect_warning_codes(
    freshness: L9FreshnessState,
    warmup: L9WarmupState,
    fallback: L9FallbackClass,
    band: L9CoherenceBand,
    smc_warnings: list[str],
    smc_feature_count: int,
) -> list[str]:
    """Collect non-fatal warning codes."""
    codes: list[str] = []
    if freshness == L9FreshnessState.STALE_PRESERVED:
        codes.append("STALE_PRESERVED_CONTEXT")
    if freshness == L9FreshnessState.DEGRADED:
        codes.append("DEGRADED_CONTEXT")
    if warmup == L9WarmupState.PARTIAL:
        codes.append("PARTIAL_WARMUP")
    if fallback == L9FallbackClass.LEGAL_EMERGENCY_PRESERVE:
        codes.append("LEGAL_EMERGENCY_PRESERVE_USED")
    if fallback == L9FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
        codes.append("PRIMARY_SUBSTITUTE_USED")
    if band == L9CoherenceBand.MID:
        codes.append("STRUCTURE_MID_BAND")
    if smc_feature_count < MIN_SAMPLE_WARN and smc_feature_count > 0:
        codes.append("LOW_SMC_FEATURE_COUNT")
    codes.extend(smc_warnings)
    return codes


# ═══════════════════════════════════════════════════════════════════════════
# §5  GOVERNOR
# ═══════════════════════════════════════════════════════════════════════════


class L9ConstitutionalGovernor:
    """Frozen v1 constitutional governor for L9 structure legality."""

    VERSION = "1.0.0"

    def evaluate(
        self,
        l9_analysis: dict[str, Any],
        upstream_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run all sub-gates and emit canonical L9 constitutional envelope.

        Parameters
        ----------
        l9_analysis : dict
            Raw output from L9SMCAnalyzer.analyze().
        upstream_output : dict | None
            Output from the previous layer (L8).
            Used to check upstream continuation legality.
        """
        timestamp = datetime.now(UTC).isoformat()
        input_ref = l9_analysis.get("symbol", "UNKNOWN")
        upstream = upstream_output or {"valid": True, "continuation_allowed": True}

        blockers: list[L9BlockerCode] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        # ── Step 1: upstream legality ────────────────────────────────
        blockers.extend(_check_upstream(upstream))

        # ── Step 2: contract integrity ───────────────────────────────
        blockers.extend(_check_contract(l9_analysis))

        # ── Step 3: structure source availability ────────────────────
        blockers.extend(_check_structure_sources(l9_analysis))

        # ── Step 4: freshness ────────────────────────────────────────
        freshness = _eval_freshness(l9_analysis)
        if freshness == L9FreshnessState.NO_PRODUCER:
            blockers.append(L9BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL)
        rule_hits.append(f"freshness_state={freshness.value}")

        # ── Step 5: warmup ───────────────────────────────────────────
        warmup = _eval_warmup(l9_analysis)
        if warmup == L9WarmupState.INSUFFICIENT:
            blockers.append(L9BlockerCode.WARMUP_INSUFFICIENT)
        rule_hits.append(f"warmup_state={warmup.value}")

        # ── Step 6: fallback legality ────────────────────────────────
        fallback = _eval_fallback(l9_analysis)
        if fallback == L9FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(L9BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED)
        rule_hits.append(f"fallback_class={fallback.value}")

        # ── Step 7: SMC validation ──────────────────────────────────
        smc_blockers, smc_warnings = _check_smc_validation(l9_analysis)
        blockers.extend(smc_blockers)

        # ── Step 8: structure score band ─────────────────────────────
        structure_score = _derive_structure_score(l9_analysis)
        source_completeness = _compute_source_completeness(l9_analysis)
        adaptive_threshold = get_governor().get_adjusted(
            layer="L9",
            metric="structure_score",
            base_threshold=MID_THRESHOLD,
            frpc_data=upstream.get("frpc_snapshot", l9_analysis.get("frpc_snapshot", {})),
            source_completeness=source_completeness,
            regime_tag=upstream.get("regime_tag"),
            rollout_key=input_ref,
        )
        effective_mid_threshold = adaptive_threshold.adjusted
        band = _score_band(structure_score, mid_threshold=effective_mid_threshold)
        rule_hits.append(f"coherence_band={band.value}")
        rule_hits.append(f"structure_score={structure_score:.4f}")
        rule_hits.append(f"adaptive_mode={adaptive_threshold.mode}")
        rule_hits.append(f"effective_mid_threshold={effective_mid_threshold:.4f}")

        # LOW band with valid result → add blocker
        if band == L9CoherenceBand.LOW and not blockers and l9_analysis.get("valid", False):
            blockers.append(L9BlockerCode.STRUCTURE_SCORE_BELOW_MINIMUM)

        # ── Step 9: SMC feature count ────────────────────────────────
        smc_feature_count = sum(
            [
                bool(l9_analysis.get("bos_detected", False)),
                bool(l9_analysis.get("choch_detected", False)),
                bool(l9_analysis.get("fvg_present", False)),
                bool(l9_analysis.get("ob_present", False)),
                bool(l9_analysis.get("sweep_detected", False)),
            ]
        )
        structure_diagnostics = _build_structure_diagnostics(
            l9_analysis=l9_analysis,
            blockers=blockers,
            warmup=warmup,
            structure_score=structure_score,
            smc_feature_count=smc_feature_count,
        )

        # ── Step 10: compress status ─────────────────────────────────
        status = _compress_status(
            blockers,
            band,
            freshness,
            warmup,
            fallback,
            smc_warnings,
            structure_score,
            smc_feature_count,
        )

        # Always-forward: continuation_allowed is always True.
        # L12 evaluates degradation via status/blocker_codes.
        continuation_allowed = True
        next_targets = ["PHASE_4"]

        # ── Step 11: warning codes ───────────────────────────────────
        warning_codes = _collect_warning_codes(
            freshness,
            warmup,
            fallback,
            band,
            smc_warnings,
            smc_feature_count,
        )
        if status == L9Status.PASS and fallback == L9FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:  # noqa: SIM102
            if "PRIMARY_SUBSTITUTE_USED" not in warning_codes:
                warning_codes.append("PRIMARY_SUBSTITUTE_USED")

        # ── Step 12: assemble features ───────────────────────────────
        features = {
            "structure_score": round(structure_score, 4),
            "effective_mid_threshold": round(effective_mid_threshold, 4),
            "smc_score": int(l9_analysis.get("smc_score", 0)),
            "confidence": round(float(l9_analysis.get("confidence", 0.0)), 4),
            "liquidity_score": round(float(l9_analysis.get("liquidity_score", 0.0)), 4),
            "dvg_confidence": round(float(l9_analysis.get("dvg_confidence", 0.0)), 4),
            "smc_signal": bool(l9_analysis.get("smc", False)),
            "bos_detected": bool(l9_analysis.get("bos_detected", False)),
            "choch_detected": bool(l9_analysis.get("choch_detected", False)),
            "fvg_present": bool(l9_analysis.get("fvg_present", False)),
            "ob_present": bool(l9_analysis.get("ob_present", False)),
            "sweep_detected": bool(l9_analysis.get("sweep_detected", False)),
            "smart_money_signal": str(l9_analysis.get("smart_money_signal", "NEUTRAL")),
            "smc_feature_count": smc_feature_count,
            "feature_hash": f"L9_{band.value}_{status.value}_{int(round(structure_score * 100))}",
        }

        routing = {
            "source_used": [s for s in ["smc", "liquidity", "divergence"] if l9_analysis.get("valid", False)],
            "fallback_used": fallback != L9FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
            "adaptive_threshold": adaptive_threshold.to_dict(),
        }

        logger.info(
            "[L9-GOV] %s status=%s band=%s structure=%.4f blockers=%d warnings=%d",
            input_ref,
            status.value,
            band.value,
            structure_score,
            len(blockers),
            len(warning_codes),
        )

        return {
            "layer": "L9",
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
            "score_numeric": round(structure_score, 4),
            "adaptive_threshold_audit": adaptive_threshold.to_dict(),
            "features": features,
            "structure_diagnostics": structure_diagnostics,
            "routing": routing,
            "audit": audit,
        }
