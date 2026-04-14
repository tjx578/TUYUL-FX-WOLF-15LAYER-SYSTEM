"""
L11 Constitutional Governor — Strict Mode v1.0.0
=================================================

Constitutional sub-gate evaluator for risk-reward / battle-strategy legality.

Implements the frozen L11 spec:
  - Evaluation order: upstream → contract → RR sources → freshness
    → warmup → fallback → RR validation → battle plan → score → compress → emit
  - Critical blockers spec (frozen v1)
  - Fallback legality matrix (frozen v1)
  - Freshness / warmup states
  - RR score thresholds (frozen baseline v1)
  - Final compression logic (strict mode)

Authority boundary:
  L11 is a risk-reward / battle-strategy legality governor only.
  L11 must never emit direction, execute, position_size, or verdict.
  Hard legality checks run before score band evaluation.
  Always-forward scoring: continuation_allowed is always True.
  L12 is sole verdict authority. FAIL status records degradation but does not halt.
  next_legal_targets always includes ["L6"].

Zone: analysis/ — pure read-only analysis, no execution side-effects.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# §1  FROZEN ENUMS
# ═══════════════════════════════════════════════════════════════════════════


class L11Status(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L11FreshnessState(StrEnum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class L11WarmupState(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class L11FallbackClass(StrEnum):
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class L11CoherenceBand(StrEnum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class L11BlockerCode(StrEnum):
    UPSTREAM_NOT_CONTINUABLE = "UPSTREAM_NOT_CONTINUABLE"
    REQUIRED_RR_SOURCE_MISSING = "REQUIRED_RR_SOURCE_MISSING"
    ENTRY_UNAVAILABLE = "ENTRY_UNAVAILABLE"
    STOP_LOSS_UNAVAILABLE = "STOP_LOSS_UNAVAILABLE"
    TAKE_PROFIT_UNAVAILABLE = "TAKE_PROFIT_UNAVAILABLE"
    RR_INVALID = "RR_INVALID"
    BATTLE_PLAN_UNAVAILABLE = "BATTLE_PLAN_UNAVAILABLE"
    ATR_CONTEXT_UNAVAILABLE = "ATR_CONTEXT_UNAVAILABLE"
    RR_SCORE_BELOW_MINIMUM = "RR_SCORE_BELOW_MINIMUM"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


# ═══════════════════════════════════════════════════════════════════════════
# §2  FROZEN THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════════

HIGH_THRESHOLD = 0.80
MID_THRESHOLD = 0.65
MIN_RR_RATIO = 1.5


# ═══════════════════════════════════════════════════════════════════════════
# §3  SUB-GATE HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _score_band(rr_score: float) -> L11CoherenceBand:
    if rr_score >= HIGH_THRESHOLD:
        return L11CoherenceBand.HIGH
    if rr_score >= MID_THRESHOLD:
        return L11CoherenceBand.MID
    return L11CoherenceBand.LOW


def _check_upstream(upstream_output: dict[str, Any]) -> list[L11BlockerCode]:
    if not upstream_output:
        return [L11BlockerCode.UPSTREAM_NOT_CONTINUABLE]
    allowed = upstream_output.get(
        "continuation_allowed",
        upstream_output.get("valid", True),
    )
    if not allowed:
        return [L11BlockerCode.UPSTREAM_NOT_CONTINUABLE]
    return []


def _check_contract(l11_analysis: dict[str, Any]) -> list[L11BlockerCode]:
    required = ("rr", "valid", "entry", "sl", "tp1")
    if not l11_analysis:
        return [L11BlockerCode.CONTRACT_PAYLOAD_MALFORMED]
    if not any(k in l11_analysis for k in required):
        return [L11BlockerCode.CONTRACT_PAYLOAD_MALFORMED]
    return []


def _check_rr_sources(l11_analysis: dict[str, Any]) -> list[L11BlockerCode]:
    blockers: list[L11BlockerCode] = []
    entry = float(l11_analysis.get("entry_price", l11_analysis.get("entry", 0.0)))
    sl = float(l11_analysis.get("stop_loss", l11_analysis.get("sl", 0.0)))
    tp = float(l11_analysis.get("take_profit_1", l11_analysis.get("tp1", 0.0)))

    if not entry or entry <= 0:
        blockers.append(L11BlockerCode.ENTRY_UNAVAILABLE)
    if not sl or sl <= 0:
        blockers.append(L11BlockerCode.STOP_LOSS_UNAVAILABLE)
    if not tp or tp <= 0:
        blockers.append(L11BlockerCode.TAKE_PROFIT_UNAVAILABLE)
    return blockers


def _eval_freshness(l11_analysis: dict[str, Any]) -> L11FreshnessState:
    explicit = l11_analysis.get("freshness_state")
    if explicit:
        try:
            return L11FreshnessState(str(explicit))
        except ValueError:
            pass

    reason = str(l11_analysis.get("reason", ""))
    if reason in ("no_data", "no_entry_price"):
        return L11FreshnessState.NO_PRODUCER

    if l11_analysis.get("valid", False):
        atr = float(l11_analysis.get("atr", 0.0))
        if atr > 0:
            return L11FreshnessState.FRESH
        return L11FreshnessState.DEGRADED

    return L11FreshnessState.DEGRADED


def _eval_warmup(l11_analysis: dict[str, Any]) -> L11WarmupState:
    explicit = l11_analysis.get("warmup_state")
    if explicit:
        try:
            return L11WarmupState(str(explicit))
        except ValueError:
            pass

    if not l11_analysis.get("valid", False):
        return L11WarmupState.INSUFFICIENT

    atr = float(l11_analysis.get("atr", 0.0))
    rr = float(l11_analysis.get("rr", 0.0))
    if atr > 0 and rr > 0:
        return L11WarmupState.READY
    if atr > 0 or rr > 0:
        return L11WarmupState.PARTIAL
    return L11WarmupState.INSUFFICIENT


def _eval_fallback(l11_analysis: dict[str, Any]) -> L11FallbackClass:
    explicit = l11_analysis.get("fallback_class")
    if explicit:
        try:
            return L11FallbackClass(str(explicit))
        except ValueError:
            pass

    reason = str(l11_analysis.get("reason", ""))
    tp1_source = str(l11_analysis.get("tp1_source", ""))
    if reason in ("no_data", "no_entry_price"):
        return L11FallbackClass.LEGAL_EMERGENCY_PRESERVE
    if tp1_source not in ("", "atr_2x"):
        return L11FallbackClass.LEGAL_PRIMARY_SUBSTITUTE
    return L11FallbackClass.NO_FALLBACK


def _check_rr_validation(l11_analysis: dict[str, Any]) -> tuple[list[L11BlockerCode], list[str]]:
    blockers: list[L11BlockerCode] = []
    warnings: list[str] = []

    rr = float(l11_analysis.get("rr", 0.0))
    if rr <= 0:
        blockers.append(L11BlockerCode.RR_INVALID)

    battle_strategy = l11_analysis.get("battle_strategy", "")
    if not battle_strategy:
        blockers.append(L11BlockerCode.BATTLE_PLAN_UNAVAILABLE)
    elif battle_strategy == "SHADOW_STRIKE":
        warnings.append("BATTLE_PLAN_DEGRADED")

    atr = float(l11_analysis.get("atr", 0.0))
    if atr <= 0:
        blockers.append(L11BlockerCode.ATR_CONTEXT_UNAVAILABLE)

    tp1_source = str(l11_analysis.get("tp1_source", ""))
    if tp1_source == "atr_2x":
        warnings.append("TP1_SOURCE_BASIC")

    return blockers, warnings


def _derive_rr_score(l11_analysis: dict[str, Any]) -> float:
    rr = float(l11_analysis.get("rr", 0.0))
    valid = l11_analysis.get("valid", False)
    atr = float(l11_analysis.get("atr", 0.0))
    battle_strategy = str(l11_analysis.get("battle_strategy", ""))

    score = 0.0
    if valid:
        score += 0.3
    if rr >= 2.0:
        score += 0.3
    elif rr >= MIN_RR_RATIO:
        score += 0.15
    if atr > 0:
        score += 0.2
    if battle_strategy in ("APEX_PREDATOR", "TSUNAMI_BREAKOUT", "BLOOD_MOON_HUNT"):
        score += 0.2
    elif battle_strategy == "SHADOW_STRIKE":
        score += 0.1
    return min(1.0, score)


# ═══════════════════════════════════════════════════════════════════════════
# §4  COMPRESSION LOGIC
# ═══════════════════════════════════════════════════════════════════════════


def _compress_status(
    blockers: list[L11BlockerCode],
    band: L11CoherenceBand,
    freshness: L11FreshnessState,
    warmup: L11WarmupState,
    fallback: L11FallbackClass,
    rr_warnings: list[str],
) -> L11Status:
    if blockers:
        return L11Status.FAIL
    if band == L11CoherenceBand.LOW:
        return L11Status.FAIL

    is_clean = (
        freshness == L11FreshnessState.FRESH
        and warmup == L11WarmupState.READY
        and fallback in (L11FallbackClass.NO_FALLBACK, L11FallbackClass.LEGAL_PRIMARY_SUBSTITUTE)
        and band == L11CoherenceBand.HIGH
        and "BATTLE_PLAN_DEGRADED" not in rr_warnings
    )
    if is_clean:
        return L11Status.PASS

    is_legal_warn = (
        freshness
        in (
            L11FreshnessState.FRESH,
            L11FreshnessState.STALE_PRESERVED,
            L11FreshnessState.DEGRADED,
        )
        and warmup in (L11WarmupState.READY, L11WarmupState.PARTIAL)
        and fallback
        in (
            L11FallbackClass.NO_FALLBACK,
            L11FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
            L11FallbackClass.LEGAL_EMERGENCY_PRESERVE,
        )
        and band in (L11CoherenceBand.HIGH, L11CoherenceBand.MID)
    )
    if is_legal_warn:
        return L11Status.WARN

    return L11Status.FAIL


def _collect_warning_codes(
    freshness: L11FreshnessState,
    warmup: L11WarmupState,
    fallback: L11FallbackClass,
    band: L11CoherenceBand,
    rr_warnings: list[str],
) -> list[str]:
    codes: list[str] = []
    if freshness == L11FreshnessState.STALE_PRESERVED:
        codes.append("STALE_PRESERVED_CONTEXT")
    if freshness == L11FreshnessState.DEGRADED:
        codes.append("DEGRADED_CONTEXT")
    if warmup == L11WarmupState.PARTIAL:
        codes.append("PARTIAL_WARMUP")
    if fallback == L11FallbackClass.LEGAL_EMERGENCY_PRESERVE:
        codes.append("LEGAL_EMERGENCY_PRESERVE_USED")
    if fallback == L11FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
        codes.append("PRIMARY_SUBSTITUTE_USED")
    if band == L11CoherenceBand.MID:
        codes.append("RR_MID_BAND")
    codes.extend(rr_warnings)
    return codes


# ═══════════════════════════════════════════════════════════════════════════
# §5  GOVERNOR
# ═══════════════════════════════════════════════════════════════════════════


class L11ConstitutionalGovernor:
    """Frozen v1 constitutional governor for L11 RR/battle-strategy legality."""

    VERSION = "1.0.0"

    def evaluate(
        self,
        l11_analysis: dict[str, Any],
        upstream_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run all sub-gates and emit canonical L11 constitutional envelope.

        Parameters
        ----------
        l11_analysis : dict
            Raw output from L11RRAnalyzer.calculate_rr().
        upstream_output : dict | None
            Output from the previous phase (Phase 3 / L9).
        """
        timestamp = datetime.now(UTC).isoformat()
        input_ref = l11_analysis.get("direction", "UNKNOWN")
        upstream = upstream_output or {"valid": True, "continuation_allowed": True}

        blockers: list[L11BlockerCode] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        # ── Step 1: upstream legality ────────────────────────────────
        blockers.extend(_check_upstream(upstream))

        # ── Step 2: contract integrity ───────────────────────────────
        blockers.extend(_check_contract(l11_analysis))

        # ── Step 3: RR source availability ───────────────────────────
        blockers.extend(_check_rr_sources(l11_analysis))

        # ── Step 4: freshness ────────────────────────────────────────
        freshness = _eval_freshness(l11_analysis)
        if freshness == L11FreshnessState.NO_PRODUCER:
            blockers.append(L11BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL)
        rule_hits.append(f"freshness_state={freshness.value}")

        # ── Step 5: warmup ───────────────────────────────────────────
        warmup = _eval_warmup(l11_analysis)
        if warmup == L11WarmupState.INSUFFICIENT:
            blockers.append(L11BlockerCode.WARMUP_INSUFFICIENT)
        rule_hits.append(f"warmup_state={warmup.value}")

        # ── Step 6: fallback legality ────────────────────────────────
        fallback = _eval_fallback(l11_analysis)
        if fallback == L11FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(L11BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED)
        rule_hits.append(f"fallback_class={fallback.value}")

        # ── Step 7: RR validation ────────────────────────────────────
        rr_blockers, rr_warnings = _check_rr_validation(l11_analysis)
        blockers.extend(rr_blockers)

        # ── Step 8: RR score band ────────────────────────────────────
        rr_score = _derive_rr_score(l11_analysis)
        band = _score_band(rr_score)
        rule_hits.append(f"coherence_band={band.value}")
        rule_hits.append(f"rr_score={rr_score:.4f}")

        if band == L11CoherenceBand.LOW and not blockers and l11_analysis.get("valid", False):
            blockers.append(L11BlockerCode.RR_SCORE_BELOW_MINIMUM)

        # ── Step 9: compress status ──────────────────────────────────
        status = _compress_status(
            blockers,
            band,
            freshness,
            warmup,
            fallback,
            rr_warnings,
        )

        # Always-forward: L12 is sole verdict authority.
        # FAIL status is recorded for diagnostics but never halts the pipeline.
        continuation_allowed = True
        next_targets = ["L6"]

        # ── Step 10: warning codes ───────────────────────────────────
        warning_codes = _collect_warning_codes(
            freshness,
            warmup,
            fallback,
            band,
            rr_warnings,
        )

        # ── Step 11: assemble features ───────────────────────────────
        features = {
            "rr_score": round(rr_score, 4),
            "rr_ratio": round(float(l11_analysis.get("rr", 0.0)), 4),
            "entry_price": float(l11_analysis.get("entry_price", l11_analysis.get("entry", 0.0))),
            "stop_loss": float(l11_analysis.get("stop_loss", l11_analysis.get("sl", 0.0))),
            "take_profit_1": float(l11_analysis.get("take_profit_1", l11_analysis.get("tp1", 0.0))),
            "atr": round(float(l11_analysis.get("atr", 0.0)), 6),
            "battle_strategy": str(l11_analysis.get("battle_strategy", "")),
            "execution_mode": str(l11_analysis.get("execution_mode", "")),
            "tp1_source": str(l11_analysis.get("tp1_source", "")),
            "feature_hash": f"L11_{band.value}_{status.value}_{int(round(rr_score * 100))}",
        }

        routing = {
            "source_used": [s for s in ["atr", "tp1_generator", "quantum"] if l11_analysis.get("valid", False)],
            "fallback_used": fallback != L11FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
        }

        logger.info(
            "[L11-GOV] %s status=%s band=%s rr_score=%.4f blockers=%d warnings=%d",
            input_ref,
            status.value,
            band.value,
            rr_score,
            len(blockers),
            len(warning_codes),
        )

        return {
            "layer": "L11",
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
            "score_numeric": round(rr_score, 4),
            "features": features,
            "routing": routing,
            "audit": audit,
        }
