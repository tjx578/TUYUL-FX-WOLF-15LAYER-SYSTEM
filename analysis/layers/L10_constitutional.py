"""
L10 Constitutional Governor — Strict Mode v1.0.0
=================================================

Constitutional sub-gate evaluator for position-sizing / risk-geometry legality.

Implements the frozen L10 spec:
  - Evaluation order: upstream(L6) → contract → sizing sources → freshness
    → warmup → fallback → geometry/sizing/compliance → score → compress → emit
  - Critical blockers spec (frozen v1)
  - Fallback legality matrix (frozen v1)
  - Freshness / warmup states
  - Sizing score thresholds (frozen baseline v1)
  - Final compression logic (strict mode)

Authority boundary:
  L10 is a position-sizing / risk-geometry legality governor only.
  L10 must never emit direction, execute, trade_valid, or verdict.
  Hard legality checks run before score band evaluation.
  status == FAIL implies continuation_allowed == false.
  continuation_allowed == true implies next_legal_targets == ["PHASE_5"].

Zone: analysis/ — pure read-only analysis, no execution side-effects.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# §1  FROZEN ENUMS
# ═══════════════════════════════════════════════════════════════════════════


class L10Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L10FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class L10WarmupState(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class L10FallbackClass(str, Enum):
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class L10CoherenceBand(str, Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class L10BlockerCode(str, Enum):
    UPSTREAM_L6_NOT_CONTINUABLE = "UPSTREAM_L6_NOT_CONTINUABLE"
    REQUIRED_SIZING_SOURCE_MISSING = "REQUIRED_SIZING_SOURCE_MISSING"
    ENTRY_UNAVAILABLE = "ENTRY_UNAVAILABLE"
    STOP_LOSS_UNAVAILABLE = "STOP_LOSS_UNAVAILABLE"
    RISK_INPUT_UNAVAILABLE = "RISK_INPUT_UNAVAILABLE"
    GEOMETRY_INVALID = "GEOMETRY_INVALID"
    POSITION_SIZING_UNAVAILABLE = "POSITION_SIZING_UNAVAILABLE"
    COMPLIANCE_INVALID = "COMPLIANCE_INVALID"
    SIZING_SCORE_BELOW_MINIMUM = "SIZING_SCORE_BELOW_MINIMUM"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


# ═══════════════════════════════════════════════════════════════════════════
# §2  FROZEN THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════════

HIGH_THRESHOLD = 0.85
MID_THRESHOLD = 0.70


# ═══════════════════════════════════════════════════════════════════════════
# §3  SUB-GATE HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _score_band(sizing_score: float) -> L10CoherenceBand:
    if sizing_score >= HIGH_THRESHOLD:
        return L10CoherenceBand.HIGH
    if sizing_score >= MID_THRESHOLD:
        return L10CoherenceBand.MID
    return L10CoherenceBand.LOW


def _check_upstream(upstream_output: dict[str, Any]) -> list[L10BlockerCode]:
    if not upstream_output:
        return [L10BlockerCode.UPSTREAM_L6_NOT_CONTINUABLE]
    allowed = upstream_output.get(
        "continuation_allowed",
        upstream_output.get("valid", True),
    )
    if not allowed:
        return [L10BlockerCode.UPSTREAM_L6_NOT_CONTINUABLE]
    return []


def _check_contract(l10_analysis: dict[str, Any]) -> list[L10BlockerCode]:
    required = ("lot_size", "valid", "position_ok", "sl_pips")
    if not l10_analysis:
        return [L10BlockerCode.CONTRACT_PAYLOAD_MALFORMED]
    if not any(k in l10_analysis for k in required):
        return [L10BlockerCode.CONTRACT_PAYLOAD_MALFORMED]
    return []


def _check_sizing_sources(l10_analysis: dict[str, Any]) -> tuple[list[L10BlockerCode], list[str]]:
    blockers: list[L10BlockerCode] = []
    warnings: list[str] = []

    entry = float(l10_analysis.get("entry", 0.0))
    sl = float(l10_analysis.get("stop_loss", 0.0))
    if not entry or entry <= 0:
        blockers.append(L10BlockerCode.ENTRY_UNAVAILABLE)
    if not sl or sl <= 0:
        blockers.append(L10BlockerCode.STOP_LOSS_UNAVAILABLE)

    risk_amount = l10_analysis.get("risk_amount")
    adjusted_risk = l10_analysis.get("adjusted_risk_pct")
    if risk_amount is None and adjusted_risk is None:
        blockers.append(L10BlockerCode.RISK_INPUT_UNAVAILABLE)

    sl_pips = float(l10_analysis.get("sl_pips", 0.0))
    rr_ratio = float(l10_analysis.get("rr_ratio", 0.0))
    if sl_pips <= 0 or rr_ratio <= 0:
        blockers.append(L10BlockerCode.GEOMETRY_INVALID)
    else:
        rr_quality = str(l10_analysis.get("rr_quality", ""))
        if rr_quality in ("POOR", "UNACCEPTABLE"):
            warnings.append("RR_QUALITY_DEGRADED")

    lot_size = l10_analysis.get("lot_size")
    if lot_size is None or float(lot_size) <= 0:
        blockers.append(L10BlockerCode.POSITION_SIZING_UNAVAILABLE)

    # Compliance check
    prop_violations = l10_analysis.get("prop_violations", [])
    if prop_violations:
        # Multiple prop violations → hard block
        if len(prop_violations) >= 2:
            blockers.append(L10BlockerCode.COMPLIANCE_INVALID)
        else:
            warnings.append("PROP_VIOLATION_MINOR")

    # Direction warnings
    direction = l10_analysis.get("direction")
    if direction is None:
        warnings.append("DIRECTION_UNAVAILABLE")

    # FTA degradation
    fta_label = str(l10_analysis.get("fta_label", ""))
    if fta_label in ("VERY_LOW", "LOW"):
        warnings.append("FTA_CONFIDENCE_LOW")

    # Account warnings
    account_balance = float(l10_analysis.get("account_balance", 0.0))
    if account_balance <= 0:
        warnings.append("ACCOUNT_BALANCE_UNAVAILABLE")

    return blockers, warnings


def _eval_freshness(l10_analysis: dict[str, Any]) -> L10FreshnessState:
    explicit = l10_analysis.get("freshness_state")
    if explicit:
        try:
            return L10FreshnessState(str(explicit))
        except ValueError:
            pass

    meta_state = str(l10_analysis.get("meta_state", "")).upper()
    if meta_state == "INVALID":
        return L10FreshnessState.NO_PRODUCER

    if l10_analysis.get("valid", False) and l10_analysis.get("position_ok", False):
        return L10FreshnessState.FRESH

    if l10_analysis.get("valid", False):
        return L10FreshnessState.DEGRADED

    return L10FreshnessState.NO_PRODUCER


def _eval_warmup(l10_analysis: dict[str, Any]) -> L10WarmupState:
    explicit = l10_analysis.get("warmup_state")
    if explicit:
        try:
            return L10WarmupState(str(explicit))
        except ValueError:
            pass

    if not l10_analysis.get("valid", False):
        return L10WarmupState.INSUFFICIENT

    lot_size = float(l10_analysis.get("lot_size", 0.0))
    sl_pips = float(l10_analysis.get("sl_pips", 0.0))
    if lot_size > 0 and sl_pips > 0:
        return L10WarmupState.READY
    if lot_size > 0 or sl_pips > 0:
        return L10WarmupState.PARTIAL
    return L10WarmupState.INSUFFICIENT


def _eval_fallback(l10_analysis: dict[str, Any]) -> L10FallbackClass:
    explicit = l10_analysis.get("fallback_class")
    if explicit:
        try:
            return L10FallbackClass(str(explicit))
        except ValueError:
            pass

    degraded_fields = l10_analysis.get("degraded_fields", [])
    if degraded_fields:
        return L10FallbackClass.LEGAL_PRIMARY_SUBSTITUTE

    sizing_source = str(l10_analysis.get("sizing_source", ""))
    if sizing_source == "STATIC_KELLY_NO_EDGE":
        return L10FallbackClass.LEGAL_EMERGENCY_PRESERVE

    return L10FallbackClass.NO_FALLBACK


def _derive_sizing_score(l10_analysis: dict[str, Any]) -> float:
    score = 0.0
    if l10_analysis.get("valid", False):
        score += 0.2
    if l10_analysis.get("position_ok", False):
        score += 0.3

    rr_quality = str(l10_analysis.get("rr_quality", ""))
    if rr_quality == "EXCELLENT":
        score += 0.2
    elif rr_quality == "GOOD":
        score += 0.15
    elif rr_quality == "ACCEPTABLE":
        score += 0.1

    fta_label = str(l10_analysis.get("fta_label", ""))
    if fta_label in ("VERY_HIGH", "HIGH"):
        score += 0.15
    elif fta_label == "MODERATE":
        score += 0.1

    prop_violations = l10_analysis.get("prop_violations", [])
    if not prop_violations:
        score += 0.15

    return min(1.0, score)


# ═══════════════════════════════════════════════════════════════════════════
# §4  COMPRESSION LOGIC
# ═══════════════════════════════════════════════════════════════════════════


def _compress_status(
    blockers: list[L10BlockerCode],
    band: L10CoherenceBand,
    freshness: L10FreshnessState,
    warmup: L10WarmupState,
    fallback: L10FallbackClass,
    sizing_warnings: list[str],
) -> L10Status:
    if blockers:
        return L10Status.FAIL
    if band == L10CoherenceBand.LOW:
        return L10Status.FAIL

    is_clean = (
        freshness == L10FreshnessState.FRESH
        and warmup == L10WarmupState.READY
        and fallback in (L10FallbackClass.NO_FALLBACK, L10FallbackClass.LEGAL_PRIMARY_SUBSTITUTE)
        and band == L10CoherenceBand.HIGH
        and not sizing_warnings
    )
    if is_clean:
        return L10Status.PASS

    is_legal_warn = (
        freshness in (
            L10FreshnessState.FRESH,
            L10FreshnessState.STALE_PRESERVED,
            L10FreshnessState.DEGRADED,
        )
        and warmup in (L10WarmupState.READY, L10WarmupState.PARTIAL)
        and fallback in (
            L10FallbackClass.NO_FALLBACK,
            L10FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
            L10FallbackClass.LEGAL_EMERGENCY_PRESERVE,
        )
        and band in (L10CoherenceBand.HIGH, L10CoherenceBand.MID)
    )
    if is_legal_warn:
        return L10Status.WARN

    return L10Status.FAIL


def _collect_warning_codes(
    freshness: L10FreshnessState,
    warmup: L10WarmupState,
    fallback: L10FallbackClass,
    band: L10CoherenceBand,
    sizing_warnings: list[str],
) -> list[str]:
    codes: list[str] = []
    if freshness == L10FreshnessState.STALE_PRESERVED:
        codes.append("STALE_PRESERVED_CONTEXT")
    if freshness == L10FreshnessState.DEGRADED:
        codes.append("DEGRADED_CONTEXT")
    if warmup == L10WarmupState.PARTIAL:
        codes.append("PARTIAL_WARMUP")
    if fallback == L10FallbackClass.LEGAL_EMERGENCY_PRESERVE:
        codes.append("LEGAL_EMERGENCY_PRESERVE_USED")
    if fallback == L10FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
        codes.append("PRIMARY_SUBSTITUTE_USED")
    if band == L10CoherenceBand.MID:
        codes.append("SIZING_MID_BAND")
    codes.extend(sizing_warnings)
    return codes


# ═══════════════════════════════════════════════════════════════════════════
# §5  GOVERNOR
# ═══════════════════════════════════════════════════════════════════════════


class L10ConstitutionalGovernor:
    """Frozen v1 constitutional governor for L10 position-sizing legality."""

    VERSION = "1.0.0"

    def evaluate(
        self,
        l10_analysis: dict[str, Any],
        upstream_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run all sub-gates and emit canonical L10 constitutional envelope.

        Parameters
        ----------
        l10_analysis : dict
            Raw output from L10PositionAnalyzer.analyze().
        upstream_output : dict | None
            L6 constitutional output (or L6 raw output).
        """
        timestamp = datetime.now(UTC).isoformat()
        input_ref = str(l10_analysis.get("pair", l10_analysis.get("meta_state", "UNKNOWN")))
        upstream = upstream_output or {"valid": True, "continuation_allowed": True}

        blockers: list[L10BlockerCode] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        # ── Step 1: upstream legality (L6) ───────────────────────────
        blockers.extend(_check_upstream(upstream))

        # ── Step 2: contract integrity ───────────────────────────────
        blockers.extend(_check_contract(l10_analysis))

        # ── Step 3: sizing source availability ───────────────────────
        sizing_blockers, sizing_warnings = _check_sizing_sources(l10_analysis)
        blockers.extend(sizing_blockers)

        # ── Step 4: freshness ────────────────────────────────────────
        freshness = _eval_freshness(l10_analysis)
        if freshness == L10FreshnessState.NO_PRODUCER:
            blockers.append(L10BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL)
        rule_hits.append(f"freshness_state={freshness.value}")

        # ── Step 5: warmup ───────────────────────────────────────────
        warmup = _eval_warmup(l10_analysis)
        if warmup == L10WarmupState.INSUFFICIENT:
            blockers.append(L10BlockerCode.WARMUP_INSUFFICIENT)
        rule_hits.append(f"warmup_state={warmup.value}")

        # ── Step 6: fallback legality ────────────────────────────────
        fallback = _eval_fallback(l10_analysis)
        if fallback == L10FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(L10BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED)
        rule_hits.append(f"fallback_class={fallback.value}")

        # ── Step 7: sizing score band ────────────────────────────────
        sizing_score = _derive_sizing_score(l10_analysis)
        band = _score_band(sizing_score)
        rule_hits.append(f"coherence_band={band.value}")
        rule_hits.append(f"sizing_score={sizing_score:.4f}")

        if band == L10CoherenceBand.LOW and not blockers and l10_analysis.get("valid", False):
            blockers.append(L10BlockerCode.SIZING_SCORE_BELOW_MINIMUM)

        # ── Step 8: compress status ──────────────────────────────────
        status = _compress_status(
            blockers, band, freshness, warmup, fallback, sizing_warnings,
        )

        continuation_allowed = status != L10Status.FAIL
        next_targets = ["PHASE_5"] if continuation_allowed else []

        # ── Step 9: warning codes ────────────────────────────────────
        warning_codes = _collect_warning_codes(
            freshness, warmup, fallback, band, sizing_warnings,
        )

        # ── Step 10: assemble features ───────────────────────────────
        features = {
            "sizing_score": round(sizing_score, 4),
            "lot_size": float(l10_analysis.get("lot_size", 0.0)),
            "risk_amount": float(l10_analysis.get("risk_amount", 0.0)),
            "adjusted_risk_pct": float(l10_analysis.get("adjusted_risk_pct", 0.0)),
            "sl_pips": float(l10_analysis.get("sl_pips", 0.0)),
            "tp_pips": float(l10_analysis.get("tp_pips", 0.0)),
            "rr_ratio": float(l10_analysis.get("rr_ratio", 0.0)),
            "rr_quality": str(l10_analysis.get("rr_quality", "")),
            "fta_label": str(l10_analysis.get("fta_label", "")),
            "meta_state": str(l10_analysis.get("meta_state", "")),
            "position_ok": bool(l10_analysis.get("position_ok", False)),
            "sizing_source": str(l10_analysis.get("sizing_source", "")),
            "feature_hash": f"L10_{band.value}_{status.value}_{int(round(sizing_score * 100))}",
        }

        routing = {
            "source_used": [
                s for s in ["risk_geometry", "fta_engine", "prop_compliance"]
                if l10_analysis.get("valid", False)
            ],
            "fallback_used": fallback != L10FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
        }

        logger.info(
            "[L10-GOV] %s status=%s band=%s sizing=%.4f blockers=%d warnings=%d",
            input_ref,
            status.value,
            band.value,
            sizing_score,
            len(blockers),
            len(warning_codes),
        )

        return {
            "layer": "L10",
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
            "score_numeric": round(sizing_score, 4),
            "features": features,
            "routing": routing,
            "audit": audit,
        }
