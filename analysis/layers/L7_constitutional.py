"""
L7 Constitutional Governor — Strict Mode v1.0.0
================================================

Constitutional sub-gate evaluator for probability / survivability legality.

Implements the frozen L7 spec:
  - Evaluation order: upstream → contract → probability sources → freshness
    → warmup → fallback → edge validation → probability score → compress → emit
  - Critical blockers spec (frozen v1)
  - Fallback legality matrix (frozen v1)
  - Freshness / warmup states
  - Probability score thresholds (frozen baseline v1)
  - Final compression logic (strict mode)

Authority boundary:
  L7 is a probability/survivability legality governor only.
  L7 must never emit direction, execute, trade_valid, position_size, or verdict.
  Hard legality checks run before score band evaluation.
  Always-forward scoring: continuation_allowed is always True.
  L12 evaluates degradation via status/blocker_codes.
  next_legal_targets always includes ["L8"].

Zone: analysis/ — pure read-only analysis, no execution side-effects.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any

from constitution.adaptive_threshold_governor import get_governor, parse_history_ratio

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# §1  FROZEN ENUMS
# ═══════════════════════════════════════════════════════════════════════════


class L7Status(StrEnum):
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
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class CoherenceBand(str, Enum):  # noqa: UP042
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class BlockerCode(StrEnum):
    UPSTREAM_NOT_CONTINUABLE = "UPSTREAM_NOT_CONTINUABLE"
    REQUIRED_PROBABILITY_SOURCE_MISSING = "REQUIRED_PROBABILITY_SOURCE_MISSING"
    EDGE_VALIDATION_UNAVAILABLE = "EDGE_VALIDATION_UNAVAILABLE"
    EDGE_STATUS_INVALID = "EDGE_STATUS_INVALID"
    WIN_PROBABILITY_BELOW_MINIMUM = "WIN_PROBABILITY_BELOW_MINIMUM"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


# ═══════════════════════════════════════════════════════════════════════════
# §2  FROZEN THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════════

HIGH_THRESHOLD = 0.67
MID_THRESHOLD = 0.55
MIN_SAMPLE_WARN = 30


# ═══════════════════════════════════════════════════════════════════════════
# §3  SUB-GATE HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _score_band(win_probability: float, *, mid_threshold: float = MID_THRESHOLD) -> CoherenceBand:
    """Map win probability to coherence band."""
    if win_probability >= HIGH_THRESHOLD:
        return CoherenceBand.HIGH
    if win_probability >= mid_threshold:
        return CoherenceBand.MID
    return CoherenceBand.LOW


def _check_upstream(upstream_output: dict[str, Any]) -> list[BlockerCode]:
    """Step 1: upstream continuation legality."""
    if not upstream_output:
        return [BlockerCode.UPSTREAM_NOT_CONTINUABLE]
    allowed = upstream_output.get(
        "continuation_allowed",
        upstream_output.get("valid", True),
    )
    if not allowed:
        return [BlockerCode.UPSTREAM_NOT_CONTINUABLE]
    return []


def _check_contract(l7_analysis: dict[str, Any]) -> list[BlockerCode]:
    """Step 2: contract payload integrity."""
    required = ("validation", "valid")
    if not l7_analysis:
        return [BlockerCode.CONTRACT_PAYLOAD_MALFORMED]
    if not any(k in l7_analysis for k in required):
        return [BlockerCode.CONTRACT_PAYLOAD_MALFORMED]
    return []


def _check_probability_sources(l7_analysis: dict[str, Any]) -> list[BlockerCode]:
    """Step 3: required probability source availability."""
    # MC engine is the required source; if simulations=0 → MC didn't run
    sims = l7_analysis.get("simulations", 0)
    if sims == 0 and l7_analysis.get("validation") == "FAIL":
        note = l7_analysis.get("note", "")
        if "insufficient_data" in str(note):
            return [BlockerCode.REQUIRED_PROBABILITY_SOURCE_MISSING]
    return []


def _eval_freshness(l7_analysis: dict[str, Any]) -> FreshnessState:
    """Step 4: freshness governance."""
    explicit = l7_analysis.get("freshness_state")
    if explicit:
        try:
            return FreshnessState(str(explicit))
        except ValueError:
            pass

    # Infer from returns_source
    source = str(l7_analysis.get("returns_source", ""))
    if source == "synthetic":
        return FreshnessState.DEGRADED
    if "stale" in source.lower() or "preserved" in source.lower():
        return FreshnessState.STALE_PRESERVED

    # If MC ran with real data → FRESH
    if l7_analysis.get("simulations", 0) > 0:
        return FreshnessState.FRESH

    return FreshnessState.DEGRADED


def _eval_warmup(l7_analysis: dict[str, Any]) -> WarmupState:
    """Step 5: warmup state."""
    explicit = l7_analysis.get("warmup_state")
    if explicit:
        try:
            return WarmupState(str(explicit))
        except ValueError:
            pass

    sims = l7_analysis.get("simulations", 0)
    if sims == 0:
        return WarmupState.INSUFFICIENT
    if sims < 500:
        return WarmupState.PARTIAL
    return WarmupState.READY


def _eval_fallback(l7_analysis: dict[str, Any]) -> FallbackClass:
    """Step 6: fallback legality classification."""
    explicit = l7_analysis.get("fallback_class")
    if explicit:
        try:
            return FallbackClass(str(explicit))
        except ValueError:
            pass

    source = str(l7_analysis.get("returns_source", ""))
    if source.startswith("cluster:"):
        return FallbackClass.LEGAL_PRIMARY_SUBSTITUTE
    if source == "synthetic":
        return FallbackClass.LEGAL_EMERGENCY_PRESERVE
    return FallbackClass.NO_FALLBACK


def _check_edge_validation(l7_analysis: dict[str, Any]) -> tuple[list[BlockerCode], list[str]]:
    """Step 7: edge validation availability and status."""
    blockers: list[BlockerCode] = []
    warnings: list[str] = []

    # Edge status from validation field
    validation = str(l7_analysis.get("validation", "FAIL")).upper()
    mc_passed = l7_analysis.get("mc_passed_threshold", False)
    wf_passed = l7_analysis.get("wf_passed")

    # If validation is FAIL and MC didn't pass → edge invalid
    if validation == "FAIL" and not mc_passed:
        sims = l7_analysis.get("simulations", 0)
        if sims > 0:
            # MC ran but failed thresholds → edge invalid
            blockers.append(BlockerCode.EDGE_STATUS_INVALID)

    # WF degradation
    if wf_passed is False:
        warnings.append("WF_VALIDATION_FAILED")
    elif wf_passed is None:
        skipped = l7_analysis.get("wf_skipped_reason")
        if skipped:
            warnings.append(f"WF_SKIPPED:{skipped}")

    return blockers, warnings


def _derive_win_probability(l7_analysis: dict[str, Any]) -> float:
    """Extract win probability as 0-1 float."""
    wp = l7_analysis.get("win_probability", 0.0)
    if isinstance(wp, (int, float)):
        # L7 outputs win_probability as percentage (0-100)
        if wp > 1.0:
            return wp / 100.0
        return float(wp)
    return 0.0


def _compute_source_completeness(l7_analysis: dict[str, Any]) -> float:
    """Estimate probability-source completeness for adaptive shadow wiring."""
    history_count = l7_analysis.get("history_count")
    if isinstance(history_count, (int, float)):
        return max(0.0, min(1.0, float(history_count) / 30.0))

    sims = l7_analysis.get("simulations", 0)
    if isinstance(sims, (int, float)) and float(sims) > 0:
        return 1.0

    return parse_history_ratio(str(l7_analysis.get("note", "")))


def _build_edge_diagnostics(
    *,
    l7_analysis: dict[str, Any],
    blockers: list[BlockerCode],
    edge_warnings: list[str],
    win_prob: float,
    band: CoherenceBand,
    sample_count: int,
) -> dict[str, Any]:
    """Assemble audit-friendly L7 diagnostics without affecting legality."""
    validation = str(l7_analysis.get("validation", "FAIL")).upper()
    primary_edge_gap = None
    for blocker in blockers:
        if blocker in (
            BlockerCode.EDGE_STATUS_INVALID,
            BlockerCode.WIN_PROBABILITY_BELOW_MINIMUM,
            BlockerCode.REQUIRED_PROBABILITY_SOURCE_MISSING,
            BlockerCode.WARMUP_INSUFFICIENT,
        ):
            primary_edge_gap = blocker.value
            break

    return {
        "edge_status": validation,
        "primary_edge_gap": primary_edge_gap,
        "win_probability": round(win_prob, 4),
        "required_win_probability": MID_THRESHOLD,
        "coherence_band": band.value,
        "simulations": sample_count,
        "warn_sample_floor": MIN_SAMPLE_WARN,
        "mc_passed_threshold": bool(l7_analysis.get("mc_passed_threshold", False)),
        "wf_passed": l7_analysis.get("wf_passed"),
        "wf_skipped_reason": l7_analysis.get("wf_skipped_reason"),
        "returns_source": str(l7_analysis.get("returns_source", "")),
        "profit_factor": round(float(l7_analysis.get("profit_factor", 0.0)), 4),
        "risk_of_ruin": round(float(l7_analysis.get("risk_of_ruin", 1.0)), 4),
        "conf12_raw": round(float(l7_analysis.get("conf12_raw", 0.0)), 4),
        "bayesian_posterior": round(float(l7_analysis.get("bayesian_posterior", 0.0)), 4),
        "warnings": list(edge_warnings),
    }


def _is_low_band_primary_substitute(
    *,
    band: CoherenceBand,
    fallback: FallbackClass,
    validation: str,
) -> bool:
    return (
        band == CoherenceBand.LOW and fallback == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE and validation == "CONDITIONAL"
    )


# ═══════════════════════════════════════════════════════════════════════════
# §4  COMPRESSION LOGIC
# ═══════════════════════════════════════════════════════════════════════════


def _compress_status(
    blockers: list[BlockerCode],
    band: CoherenceBand,
    freshness: FreshnessState,
    warmup: WarmupState,
    fallback: FallbackClass,
    edge_warnings: list[str],
    win_prob: float,
    sample_count: int,
    validation: str = "FAIL",
) -> L7Status:
    allow_low_band_primary_substitute = _is_low_band_primary_substitute(
        band=band,
        fallback=fallback,
        validation=validation,
    )

    # Any blocker → FAIL
    if blockers:
        return L7Status.FAIL

    # LOW band → FAIL (win_probability below minimum)
    if band == CoherenceBand.LOW and not allow_low_band_primary_substitute:
        return L7Status.FAIL

    # Check for clean PASS envelope
    is_clean = (
        freshness == FreshnessState.FRESH
        and warmup == WarmupState.READY
        and fallback in (FallbackClass.NO_FALLBACK, FallbackClass.LEGAL_PRIMARY_SUBSTITUTE)
        and band == CoherenceBand.HIGH
        and not any("FAILED" in w for w in edge_warnings)
        and sample_count >= MIN_SAMPLE_WARN
    )
    if is_clean:
        return L7Status.PASS

    # Legal degraded envelope → WARN
    is_legal_warn = (
        freshness
        in (
            FreshnessState.FRESH,
            FreshnessState.STALE_PRESERVED,
            FreshnessState.DEGRADED,
        )
        and warmup in (WarmupState.READY, WarmupState.PARTIAL)
        and fallback
        in (
            FallbackClass.NO_FALLBACK,
            FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
            FallbackClass.LEGAL_EMERGENCY_PRESERVE,
        )
        and (band in (CoherenceBand.HIGH, CoherenceBand.MID) or allow_low_band_primary_substitute)
    )
    if is_legal_warn:
        return L7Status.WARN

    return L7Status.FAIL


def _collect_warning_codes(
    freshness: FreshnessState,
    warmup: WarmupState,
    fallback: FallbackClass,
    band: CoherenceBand,
    edge_warnings: list[str],
    sample_count: int,
    validation: str,
) -> list[str]:
    """Collect non-fatal warning codes."""
    codes: list[str] = []
    if freshness == FreshnessState.STALE_PRESERVED:
        codes.append("STALE_PRESERVED_CONTEXT")
    if freshness == FreshnessState.DEGRADED:
        codes.append("DEGRADED_CONTEXT")
    if warmup == WarmupState.PARTIAL:
        codes.append("PARTIAL_WARMUP")
    if fallback == FallbackClass.LEGAL_EMERGENCY_PRESERVE:
        codes.append("LEGAL_EMERGENCY_PRESERVE_USED")
    if fallback == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
        codes.append("PRIMARY_SUBSTITUTE_USED")
    if band == CoherenceBand.MID:
        codes.append("PROBABILITY_MID_BAND")
    if sample_count < MIN_SAMPLE_WARN and sample_count > 0:
        codes.append("LOW_SAMPLE_COUNT")
    if validation == "CONDITIONAL":
        codes.append("VALIDATION_CONDITIONAL")
    codes.extend(edge_warnings)
    return codes


# ═══════════════════════════════════════════════════════════════════════════
# §5  GOVERNOR
# ═══════════════════════════════════════════════════════════════════════════


class L7ConstitutionalGovernor:
    """Frozen v1 constitutional governor for L7 probability legality."""

    VERSION = "1.0.0"

    def evaluate(
        self,
        l7_analysis: dict[str, Any],
        upstream_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run all sub-gates and emit canonical L7 constitutional envelope.

        Parameters
        ----------
        l7_analysis : dict
            Raw output from L7ProbabilityAnalyzer.analyze().
        upstream_output : dict | None
            Output from the previous layer/phase (Phase 2 result or L5/enrichment).
            Used to check upstream continuation legality.
        """
        timestamp = datetime.now(UTC).isoformat()
        input_ref = l7_analysis.get("symbol", "UNKNOWN")
        upstream = upstream_output or {"valid": True, "continuation_allowed": True}

        blockers: list[BlockerCode] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        # ── Step 1: upstream legality ────────────────────────────────
        blockers.extend(_check_upstream(upstream))

        # ── Step 2: contract integrity ───────────────────────────────
        blockers.extend(_check_contract(l7_analysis))

        # ── Step 3: probability source availability ──────────────────
        blockers.extend(_check_probability_sources(l7_analysis))

        # ── Step 4: freshness ────────────────────────────────────────
        freshness = _eval_freshness(l7_analysis)
        if freshness == FreshnessState.NO_PRODUCER:
            blockers.append(BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL)
        rule_hits.append(f"freshness_state={freshness.value}")

        # ── Step 5: warmup ───────────────────────────────────────────
        warmup = _eval_warmup(l7_analysis)
        if warmup == WarmupState.INSUFFICIENT:
            blockers.append(BlockerCode.WARMUP_INSUFFICIENT)
        rule_hits.append(f"warmup_state={warmup.value}")

        # ── Step 6: fallback legality ────────────────────────────────
        fallback = _eval_fallback(l7_analysis)
        if fallback == FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED)
        rule_hits.append(f"fallback_class={fallback.value}")

        # ── Step 7: edge validation ──────────────────────────────────
        edge_blockers, edge_warnings = _check_edge_validation(l7_analysis)
        blockers.extend(edge_blockers)

        # ── Step 8: win probability score band ───────────────────────
        win_prob = _derive_win_probability(l7_analysis)
        source_completeness = _compute_source_completeness(l7_analysis)
        adaptive_threshold = get_governor().get_adjusted(
            layer="L7",
            metric="win_probability",
            base_threshold=MID_THRESHOLD,
            frpc_data=upstream.get("frpc_snapshot", l7_analysis.get("frpc_snapshot", {})),
            source_completeness=source_completeness,
            regime_tag=upstream.get("regime_tag"),
        )
        effective_mid_threshold = adaptive_threshold.adjusted
        band = _score_band(win_prob, mid_threshold=effective_mid_threshold)
        validation = str(l7_analysis.get("validation", "FAIL")).upper()
        rule_hits.append(f"coherence_band={band.value}")
        rule_hits.append(f"win_probability={win_prob:.4f}")
        rule_hits.append(f"adaptive_mode={adaptive_threshold.mode}")
        rule_hits.append(f"effective_mid_threshold={effective_mid_threshold:.4f}")

        # LOW band with valid MC → add blocker
        if band == CoherenceBand.LOW and not blockers:
            sims = l7_analysis.get("simulations", 0)
            if sims > 0 and not _is_low_band_primary_substitute(
                band=band,
                fallback=fallback,
                validation=validation,
            ):
                blockers.append(BlockerCode.WIN_PROBABILITY_BELOW_MINIMUM)

        # ── Step 9: sample count ─────────────────────────────────────
        sample_count = int(l7_analysis.get("simulations", 0))

        # ── Step 10: compress status ─────────────────────────────────
        status = _compress_status(
            blockers,
            band,
            freshness,
            warmup,
            fallback,
            edge_warnings,
            win_prob,
            sample_count,
            validation,
        )

        # Always-forward: continuation_allowed is always True.
        # L12 evaluates degradation via status/blocker_codes.
        continuation_allowed = True
        next_targets = ["L8"]
        edge_diagnostics = _build_edge_diagnostics(
            l7_analysis=l7_analysis,
            blockers=blockers,
            edge_warnings=edge_warnings,
            win_prob=win_prob,
            band=band,
            sample_count=sample_count,
        )

        # ── Step 11: warning codes ───────────────────────────────────
        warning_codes = _collect_warning_codes(
            freshness,
            warmup,
            fallback,
            band,
            edge_warnings,
            sample_count,
            validation,
        )
        # PASS status can also carry advisory warnings
        if status == L7Status.PASS and fallback == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:  # noqa: SIM102
            if "PRIMARY_SUBSTITUTE_USED" not in warning_codes:
                warning_codes.append("PRIMARY_SUBSTITUTE_USED")

        # ── Step 12: assemble features ───────────────────────────────
        features = {
            "win_probability": round(win_prob, 4),
            "effective_mid_threshold": round(effective_mid_threshold, 4),
            "profit_factor": round(float(l7_analysis.get("profit_factor", 0.0)), 4),
            "sample_count": sample_count,
            "edge_validation_available": bool(l7_analysis.get("simulations", 0) > 0),
            "edge_status": validation,
            "validation_partial": l7_analysis.get("wf_passed") is None,
            "conf12_raw": round(float(l7_analysis.get("conf12_raw", 0.0)), 4),
            "risk_of_ruin": round(float(l7_analysis.get("risk_of_ruin", 1.0)), 4),
            "bayesian_posterior": round(
                float(l7_analysis.get("bayesian_posterior", 0.0)),
                4,
            ),
            "feature_hash": f"L7_{band.value}_{status.value}_{int(round(win_prob * 100))}",
        }

        routing = {
            "source_used": [
                s
                for s in ["monte_carlo", "bayesian", "walk_forward"]
                if l7_analysis.get("simulations", 0) > 0 or s not in ("monte_carlo", "bayesian")
            ],
            "fallback_used": fallback != FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
            "adaptive_threshold": adaptive_threshold.to_dict(),
        }

        logger.info(
            "[L7-GOV] %s status=%s band=%s wp=%.4f blockers=%d warnings=%d",
            input_ref,
            status.value,
            band.value,
            win_prob,
            len(blockers),
            len(warning_codes),
        )

        return {
            "layer": "L7",
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
            "score_numeric": round(win_prob, 4),
            "adaptive_threshold_audit": adaptive_threshold.to_dict(),
            "features": features,
            "edge_diagnostics": edge_diagnostics,
            "routing": routing,
            "audit": audit,
        }
