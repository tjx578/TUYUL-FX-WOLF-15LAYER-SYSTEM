"""
L6 Constitutional Governor — Strict Mode v1.0.0
================================================

Constitutional sub-gate evaluator for capital firewall / correlation-risk legality.

Implements the frozen L6 spec:
  - Evaluation order: upstream(L11) → contract → risk sources → freshness
    → warmup → fallback → drawdown/daily/correlation/vol → firewall score → compress → emit
  - Critical blockers spec (frozen v1)
  - Fallback legality matrix (frozen v1)
  - Freshness / warmup states
  - Firewall score thresholds (frozen baseline v1)
  - Final compression logic (strict mode)

Authority boundary:
  L6 is a capital firewall / correlation-risk legality governor only.
  L6 must never emit direction, execute, trade_valid, position_size, or verdict.
  Hard legality checks run before score band evaluation.
  status == FAIL implies continuation_allowed == false.
  continuation_allowed == true implies next_legal_targets == ["L10"].

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


class L6Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L6FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE_PRESERVED = "STALE_PRESERVED"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


class L6WarmupState(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class L6FallbackClass(str, Enum):
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class L6CoherenceBand(str, Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class L6BlockerCode(str, Enum):
    UPSTREAM_L11_NOT_CONTINUABLE = "UPSTREAM_L11_NOT_CONTINUABLE"
    REQUIRED_RISK_SOURCE_MISSING = "REQUIRED_RISK_SOURCE_MISSING"
    ACCOUNT_STATE_UNAVAILABLE = "ACCOUNT_STATE_UNAVAILABLE"
    DRAWDOWN_LIMIT_BREACHED = "DRAWDOWN_LIMIT_BREACHED"
    DAILY_LOSS_LIMIT_BREACHED = "DAILY_LOSS_LIMIT_BREACHED"
    CORRELATION_EXPOSURE_EXCEEDED = "CORRELATION_EXPOSURE_EXCEEDED"
    VOL_CLUSTER_EXTREME = "VOL_CLUSTER_EXTREME"
    FIREWALL_STATE_INVALID = "FIREWALL_STATE_INVALID"
    FIREWALL_SCORE_BELOW_MINIMUM = "FIREWALL_SCORE_BELOW_MINIMUM"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


# ═══════════════════════════════════════════════════════════════════════════
# §2  FROZEN THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════════

HIGH_THRESHOLD = 0.85
MID_THRESHOLD = 0.70

DRAWDOWN_HARD_LIMIT = 0.10  # 10%
DAILY_LOSS_HARD_LIMIT = 0.05  # 5%
CORRELATION_HARD_LIMIT = 0.80


# ═══════════════════════════════════════════════════════════════════════════
# §3  SUB-GATE HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _score_band(firewall_score: float) -> L6CoherenceBand:
    if firewall_score >= HIGH_THRESHOLD:
        return L6CoherenceBand.HIGH
    if firewall_score >= MID_THRESHOLD:
        return L6CoherenceBand.MID
    return L6CoherenceBand.LOW


def _check_upstream(upstream_output: dict[str, Any]) -> list[L6BlockerCode]:
    if not upstream_output:
        return [L6BlockerCode.UPSTREAM_L11_NOT_CONTINUABLE]
    allowed = upstream_output.get(
        "continuation_allowed",
        upstream_output.get("valid", True),
    )
    if not allowed:
        return [L6BlockerCode.UPSTREAM_L11_NOT_CONTINUABLE]
    return []


def _check_contract(l6_analysis: dict[str, Any]) -> list[L6BlockerCode]:
    required = ("risk_status", "valid", "risk_ok")
    if not l6_analysis:
        return [L6BlockerCode.CONTRACT_PAYLOAD_MALFORMED]
    if not any(k in l6_analysis for k in required):
        return [L6BlockerCode.CONTRACT_PAYLOAD_MALFORMED]
    return []


def _eval_freshness(l6_analysis: dict[str, Any]) -> L6FreshnessState:
    explicit = l6_analysis.get("freshness_state")
    if explicit:
        try:
            return L6FreshnessState(str(explicit))
        except ValueError:
            pass

    risk_status = str(l6_analysis.get("risk_status", "")).upper()
    if risk_status in ("CRITICAL", "TOTAL_DD_BREACH", "DAILY_LIMIT_BREACH"):
        return L6FreshnessState.DEGRADED

    if l6_analysis.get("valid", False) and l6_analysis.get("risk_ok", False):
        return L6FreshnessState.FRESH

    if l6_analysis.get("valid", False):
        return L6FreshnessState.DEGRADED

    return L6FreshnessState.NO_PRODUCER


def _eval_warmup(l6_analysis: dict[str, Any]) -> L6WarmupState:
    explicit = l6_analysis.get("warmup_state")
    if explicit:
        try:
            return L6WarmupState(str(explicit))
        except ValueError:
            pass

    if not l6_analysis.get("valid", False):
        return L6WarmupState.INSUFFICIENT

    risk_multiplier = float(l6_analysis.get("risk_multiplier", 0.0))
    if risk_multiplier > 0:
        return L6WarmupState.READY
    return L6WarmupState.PARTIAL


def _eval_fallback(l6_analysis: dict[str, Any]) -> L6FallbackClass:
    explicit = l6_analysis.get("fallback_class")
    if explicit:
        try:
            return L6FallbackClass(str(explicit))
        except ValueError:
            pass

    risk_status = str(l6_analysis.get("risk_status", "")).upper()
    if risk_status in ("DEFENSIVE", "WARNING"):
        return L6FallbackClass.LEGAL_EMERGENCY_PRESERVE
    return L6FallbackClass.NO_FALLBACK


def _check_capital_gates(l6_analysis: dict[str, Any]) -> tuple[list[L6BlockerCode], list[str]]:
    blockers: list[L6BlockerCode] = []
    warnings: list[str] = []

    # Account state availability
    risk_multiplier = l6_analysis.get("risk_multiplier")
    max_risk = l6_analysis.get("max_risk_pct")
    if risk_multiplier is None and max_risk is None:
        blockers.append(L6BlockerCode.ACCOUNT_STATE_UNAVAILABLE)

    # Drawdown check
    drawdown_level = str(l6_analysis.get("drawdown_level", "LEVEL_0"))
    if drawdown_level in ("LEVEL_4",):
        blockers.append(L6BlockerCode.DRAWDOWN_LIMIT_BREACHED)
    elif drawdown_level in ("LEVEL_3", "LEVEL_2"):
        warnings.append("DRAWDOWN_ELEVATED")

    # Risk status hard blocks
    risk_status = str(l6_analysis.get("risk_status", "")).upper()
    if risk_status == "DAILY_LIMIT_BREACH":
        blockers.append(L6BlockerCode.DAILY_LOSS_LIMIT_BREACHED)
    elif risk_status == "TOTAL_DD_BREACH":
        blockers.append(L6BlockerCode.DRAWDOWN_LIMIT_BREACHED)

    # Correlation
    corr_exposure = float(l6_analysis.get("corr_dampener", l6_analysis.get("corr_exposure", 0.0)))
    if "CORRELATION_STRESS" in risk_status:
        blockers.append(L6BlockerCode.CORRELATION_EXPOSURE_EXCEEDED)
    elif corr_exposure > 0.7:
        warnings.append("CORRELATION_EXPOSURE_ELEVATED")

    # Vol cluster
    vol_cluster = str(l6_analysis.get("vol_cluster", "NORMAL")).upper()
    if vol_cluster == "EXTREME":
        blockers.append(L6BlockerCode.VOL_CLUSTER_EXTREME)
    elif vol_cluster == "HIGH":
        warnings.append("VOL_CLUSTER_HIGH")

    # LRCE field instability
    lrce = float(l6_analysis.get("lrce", 0.0))
    if risk_status == "UNSTABLE_FIELD" or lrce > 0.6:
        blockers.append(L6BlockerCode.FIREWALL_STATE_INVALID)
    elif lrce > 0.4:
        warnings.append("LRCE_ELEVATED")

    # Risk OK hard block
    if not l6_analysis.get("risk_ok", True) and not blockers:
        blockers.append(L6BlockerCode.FIREWALL_STATE_INVALID)

    # Prop firm compliance
    if not l6_analysis.get("propfirm_compliant", True):
        warnings.append("PROPFIRM_NON_COMPLIANT")

    # Sharpe degradation
    rolling_sharpe = float(l6_analysis.get("rolling_sharpe", 0.0))
    if "SHARPE_DEGRADATION" in risk_status:
        warnings.append("SHARPE_DEGRADATION")
    elif rolling_sharpe < 0:
        warnings.append("NEGATIVE_SHARPE")

    return blockers, warnings


def _derive_firewall_score(l6_analysis: dict[str, Any]) -> float:
    score = 0.0
    if l6_analysis.get("valid", False):
        score += 0.2
    if l6_analysis.get("risk_ok", False):
        score += 0.3

    risk_mult = float(l6_analysis.get("risk_multiplier", 0.0))
    score += min(0.3, risk_mult * 0.3)

    if l6_analysis.get("propfirm_compliant", False):
        score += 0.1

    lrce = float(l6_analysis.get("lrce", 0.0))
    if lrce <= 0.3:
        score += 0.1

    return min(1.0, score)


# ═══════════════════════════════════════════════════════════════════════════
# §4  COMPRESSION LOGIC
# ═══════════════════════════════════════════════════════════════════════════


def _compress_status(
    blockers: list[L6BlockerCode],
    band: L6CoherenceBand,
    freshness: L6FreshnessState,
    warmup: L6WarmupState,
    fallback: L6FallbackClass,
    capital_warnings: list[str],
) -> L6Status:
    if blockers:
        return L6Status.FAIL
    if band == L6CoherenceBand.LOW:
        return L6Status.FAIL

    is_clean = (
        freshness == L6FreshnessState.FRESH
        and warmup == L6WarmupState.READY
        and fallback in (L6FallbackClass.NO_FALLBACK, L6FallbackClass.LEGAL_PRIMARY_SUBSTITUTE)
        and band == L6CoherenceBand.HIGH
        and not capital_warnings
    )
    if is_clean:
        return L6Status.PASS

    is_legal_warn = (
        freshness in (
            L6FreshnessState.FRESH,
            L6FreshnessState.STALE_PRESERVED,
            L6FreshnessState.DEGRADED,
        )
        and warmup in (L6WarmupState.READY, L6WarmupState.PARTIAL)
        and fallback in (
            L6FallbackClass.NO_FALLBACK,
            L6FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
            L6FallbackClass.LEGAL_EMERGENCY_PRESERVE,
        )
        and band in (L6CoherenceBand.HIGH, L6CoherenceBand.MID)
    )
    if is_legal_warn:
        return L6Status.WARN

    return L6Status.FAIL


def _collect_warning_codes(
    freshness: L6FreshnessState,
    warmup: L6WarmupState,
    fallback: L6FallbackClass,
    band: L6CoherenceBand,
    capital_warnings: list[str],
) -> list[str]:
    codes: list[str] = []
    if freshness == L6FreshnessState.STALE_PRESERVED:
        codes.append("STALE_PRESERVED_CONTEXT")
    if freshness == L6FreshnessState.DEGRADED:
        codes.append("DEGRADED_CONTEXT")
    if warmup == L6WarmupState.PARTIAL:
        codes.append("PARTIAL_WARMUP")
    if fallback == L6FallbackClass.LEGAL_EMERGENCY_PRESERVE:
        codes.append("LEGAL_EMERGENCY_PRESERVE_USED")
    if fallback == L6FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
        codes.append("PRIMARY_SUBSTITUTE_USED")
    if band == L6CoherenceBand.MID:
        codes.append("FIREWALL_MID_BAND")
    codes.extend(capital_warnings)
    return codes


# ═══════════════════════════════════════════════════════════════════════════
# §5  GOVERNOR
# ═══════════════════════════════════════════════════════════════════════════


class L6ConstitutionalGovernor:
    """Frozen v1 constitutional governor for L6 capital firewall legality."""

    VERSION = "1.0.0"

    def evaluate(
        self,
        l6_analysis: dict[str, Any],
        upstream_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run all sub-gates and emit canonical L6 constitutional envelope.

        Parameters
        ----------
        l6_analysis : dict
            Raw output from L6RiskAnalyzer.analyze().
        upstream_output : dict | None
            L11 constitutional output (or L11 raw output).
        """
        timestamp = datetime.now(UTC).isoformat()
        input_ref = str(l6_analysis.get("risk_status", "UNKNOWN"))
        upstream = upstream_output or {"valid": True, "continuation_allowed": True}

        blockers: list[L6BlockerCode] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        # ── Step 1: upstream legality (L11) ──────────────────────────
        blockers.extend(_check_upstream(upstream))

        # ── Step 2: contract integrity ───────────────────────────────
        blockers.extend(_check_contract(l6_analysis))

        # ── Step 3: freshness ────────────────────────────────────────
        freshness = _eval_freshness(l6_analysis)
        if freshness == L6FreshnessState.NO_PRODUCER:
            blockers.append(L6BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL)
        rule_hits.append(f"freshness_state={freshness.value}")

        # ── Step 4: warmup ───────────────────────────────────────────
        warmup = _eval_warmup(l6_analysis)
        if warmup == L6WarmupState.INSUFFICIENT:
            blockers.append(L6BlockerCode.WARMUP_INSUFFICIENT)
        rule_hits.append(f"warmup_state={warmup.value}")

        # ── Step 5: fallback legality ────────────────────────────────
        fallback = _eval_fallback(l6_analysis)
        if fallback == L6FallbackClass.ILLEGAL_FALLBACK:
            blockers.append(L6BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED)
        rule_hits.append(f"fallback_class={fallback.value}")

        # ── Step 6: capital gates ────────────────────────────────────
        capital_blockers, capital_warnings = _check_capital_gates(l6_analysis)
        blockers.extend(capital_blockers)

        # ── Step 7: firewall score band ──────────────────────────────
        firewall_score = _derive_firewall_score(l6_analysis)
        band = _score_band(firewall_score)
        rule_hits.append(f"coherence_band={band.value}")
        rule_hits.append(f"firewall_score={firewall_score:.4f}")

        if band == L6CoherenceBand.LOW and not blockers and l6_analysis.get("valid", False):
            blockers.append(L6BlockerCode.FIREWALL_SCORE_BELOW_MINIMUM)

        # ── Step 8: compress status ──────────────────────────────────
        status = _compress_status(
            blockers, band, freshness, warmup, fallback, capital_warnings,
        )

        continuation_allowed = status != L6Status.FAIL
        next_targets = ["L10"] if continuation_allowed else []

        # ── Step 9: warning codes ────────────────────────────────────
        warning_codes = _collect_warning_codes(
            freshness, warmup, fallback, band, capital_warnings,
        )

        # ── Step 10: assemble features ───────────────────────────────
        features = {
            "firewall_score": round(firewall_score, 4),
            "risk_status": str(l6_analysis.get("risk_status", "")),
            "risk_ok": bool(l6_analysis.get("risk_ok", False)),
            "risk_multiplier": round(float(l6_analysis.get("risk_multiplier", 0.0)), 4),
            "drawdown_level": str(l6_analysis.get("drawdown_level", "")),
            "max_risk_pct": round(float(l6_analysis.get("max_risk_pct", 0.0)), 4),
            "lrce": round(float(l6_analysis.get("lrce", 0.0)), 4),
            "rolling_sharpe": round(float(l6_analysis.get("rolling_sharpe", 0.0)), 4),
            "propfirm_compliant": bool(l6_analysis.get("propfirm_compliant", False)),
            "feature_hash": f"L6_{band.value}_{status.value}_{int(round(firewall_score * 100))}",
        }

        routing = {
            "source_used": [
                s for s in ["account_state", "drawdown_engine", "vol_cluster", "correlation"]
                if l6_analysis.get("valid", False)
            ],
            "fallback_used": fallback != L6FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
        }

        logger.info(
            "[L6-GOV] %s status=%s band=%s firewall=%.4f blockers=%d warnings=%d",
            input_ref,
            status.value,
            band.value,
            firewall_score,
            len(blockers),
            len(warning_codes),
        )

        return {
            "layer": "L6",
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
            "score_numeric": round(firewall_score, 4),
            "features": features,
            "routing": routing,
            "audit": audit,
        }
