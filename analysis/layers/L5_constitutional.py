"""
L5 Constitutional Governor — Strict Mode v1.0.0
================================================

Constitutional sub-gate evaluator for L5 psychology/emotional readiness legality.

Implements the frozen L5 spec:
  - Evaluation order: contract → upstream → required inputs → freshness
    → warmup → fallback → discipline → fatigue/focus → revenge/FOMO/bias
    → risk-event → score band → compress → emit
  - Critical blockers spec (frozen v1)
  - Fallback legality matrix (frozen v1)
  - Freshness / warmup states
  - Psychology score thresholds (frozen baseline v1)
  - Final compression logic (strict mode)

Authority boundary:
  L5 is a psychology/emotional readiness legality governor only.
  L5 must never emit direction, execute, trade_valid, position_size, or verdict.
  Hard legality checks run before score band evaluation.
  status == FAIL implies continuation_allowed == false.
  continuation_allowed == true implies next_legal_targets == ["PHASE_2_5"].

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


class L5Status(str, Enum):
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
    NO_FALLBACK = "NO_FALLBACK"
    LEGAL_PRIMARY_SUBSTITUTE = "LEGAL_PRIMARY_SUBSTITUTE"
    LEGAL_EMERGENCY_PRESERVE = "LEGAL_EMERGENCY_PRESERVE"
    ILLEGAL_FALLBACK = "ILLEGAL_FALLBACK"


class CoherenceBand(str, Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class BlockerCode(str, Enum):
    UPSTREAM_L4_NOT_CONTINUABLE = "UPSTREAM_L4_NOT_CONTINUABLE"
    REQUIRED_PSYCHOLOGY_INPUT_MISSING = "REQUIRED_PSYCHOLOGY_INPUT_MISSING"
    DISCIPLINE_BELOW_MINIMUM = "DISCIPLINE_BELOW_MINIMUM"
    FATIGUE_CRITICAL = "FATIGUE_CRITICAL"
    FOCUS_CRITICAL = "FOCUS_CRITICAL"
    REVENGE_TRADING_ACTIVE = "REVENGE_TRADING_ACTIVE"
    RISK_EVENT_HARD_BLOCK = "RISK_EVENT_HARD_BLOCK"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


# ═══════════════════════════════════════════════════════════════════════════
# §2  FROZEN THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════════

HIGH_THRESHOLD = 0.85
MID_THRESHOLD = 0.65
DISCIPLINE_MIN = 0.65
FOCUS_CRITICAL_MAX = 0.30
FOCUS_WARN_MAX = 0.60
FOMO_WARN_MIN = 0.60
EMOTIONAL_BIAS_WARN_ABS = 0.60


# ═══════════════════════════════════════════════════════════════════════════
# §3  SUB-GATE HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _score_band(score: float) -> CoherenceBand:
    if score >= HIGH_THRESHOLD:
        return CoherenceBand.HIGH
    if score >= MID_THRESHOLD:
        return CoherenceBand.MID
    return CoherenceBand.LOW


def _collect_blockers(
    l4_output: dict[str, Any],
    l5_analysis: dict[str, Any],
) -> list[BlockerCode]:
    """Check all hard-fail conditions per frozen spec."""
    blockers: list[BlockerCode] = []

    # 1. Upstream L4 legality
    l4_cont = l4_output.get("continuation_allowed", l4_output.get("valid", True))
    if not l4_cont:
        blockers.append(BlockerCode.UPSTREAM_L4_NOT_CONTINUABLE)

    # 2. Freshness
    freshness = l5_analysis.get("freshness_state", "FRESH")
    if freshness == "NO_PRODUCER":
        blockers.append(BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL)

    # 3. Warmup
    warmup = l5_analysis.get("warmup_state", "READY")
    if warmup == "INSUFFICIENT":
        blockers.append(BlockerCode.WARMUP_INSUFFICIENT)

    # 4. Fallback
    fallback = l5_analysis.get("fallback_class", "NO_FALLBACK")
    if fallback == "ILLEGAL_FALLBACK":
        blockers.append(BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED)

    # 5. Discipline
    discipline = float(l5_analysis.get("discipline_score", 1.0))
    if discipline < DISCIPLINE_MIN:
        blockers.append(BlockerCode.DISCIPLINE_BELOW_MINIMUM)

    # 6. Fatigue
    fatigue = str(l5_analysis.get("fatigue_level", "LOW")).upper()
    if fatigue == "CRITICAL":
        blockers.append(BlockerCode.FATIGUE_CRITICAL)

    # 7. Focus
    focus = float(l5_analysis.get("focus_level", 1.0))
    if focus < FOCUS_CRITICAL_MAX:
        blockers.append(BlockerCode.FOCUS_CRITICAL)

    # 8. Revenge trading
    revenge = bool(l5_analysis.get("revenge_trading", False))
    if revenge:
        blockers.append(BlockerCode.REVENGE_TRADING_ACTIVE)

    # 9. Risk event
    risk_event = bool(l5_analysis.get("risk_event_active", False))
    if risk_event:
        blockers.append(BlockerCode.RISK_EVENT_HARD_BLOCK)

    # Deduplicate preserving order
    seen: set[str] = set()
    deduped: list[BlockerCode] = []
    for b in blockers:
        if b.value not in seen:
            seen.add(b.value)
            deduped.append(b)
    return deduped


def _collect_warning_codes(l5_analysis: dict[str, Any]) -> list[str]:
    """Collect non-fatal warning codes from L5 analysis output."""
    warnings: list[str] = []

    freshness = l5_analysis.get("freshness_state", "FRESH")
    if freshness == "STALE_PRESERVED":
        warnings.append("STALE_PRESERVED_CONTEXT")
    elif freshness == "DEGRADED":
        warnings.append("DEGRADED_CONTEXT")

    warmup = l5_analysis.get("warmup_state", "READY")
    if warmup == "PARTIAL":
        warnings.append("PARTIAL_WARMUP")

    fallback = l5_analysis.get("fallback_class", "NO_FALLBACK")
    if fallback == "LEGAL_EMERGENCY_PRESERVE":
        warnings.append("LEGAL_EMERGENCY_PRESERVE_USED")
    elif fallback == "LEGAL_PRIMARY_SUBSTITUTE":
        warnings.append("PRIMARY_SUBSTITUTE_USED")

    fatigue = str(l5_analysis.get("fatigue_level", "LOW")).upper()
    if fatigue in ("HIGH", "MEDIUM"):
        warnings.append(f"FATIGUE_{fatigue}")

    focus = float(l5_analysis.get("focus_level", 1.0))
    if FOCUS_CRITICAL_MAX <= focus < FOCUS_WARN_MAX:
        warnings.append("FOCUS_LOW")

    fomo = float(l5_analysis.get("fomo_level", l5_analysis.get("fomo_score", 0.0)))
    if fomo >= FOMO_WARN_MIN:
        warnings.append("FOMO_ELEVATED")

    em_bias = float(l5_analysis.get("emotional_bias", l5_analysis.get("emotion_delta", 0.0)))
    if abs(em_bias) >= EMOTIONAL_BIAS_WARN_ABS:
        warnings.append("EMOTIONAL_BIAS_ELEVATED")

    caution = bool(l5_analysis.get("caution_event", False))
    if caution:
        warnings.append("CAUTION_EVENT_ACTIVE")

    return warnings


def _compute_psychology_score(l5_analysis: dict[str, Any]) -> float:
    """Derive a 0.0–1.0 psychology score from L5 analysis output.

    Sources (in priority order):
    1. Explicit ``psychology_score_normalized`` (0.0–1.0)
    2. ``eaf_score`` (already 0.0–1.0)
    3. ``psychology_score`` (0–100 integer scale) → normalize
    4. Fallback 0.5
    """
    normalized = l5_analysis.get("psychology_score_normalized")
    if isinstance(normalized, (int, float)) and 0.0 <= float(normalized) <= 1.0:
        return float(normalized)

    eaf = l5_analysis.get("eaf_score")
    if isinstance(eaf, (int, float)) and 0.0 <= float(eaf) <= 1.0:
        return float(eaf)

    raw = l5_analysis.get("psychology_score")
    if isinstance(raw, (int, float)):
        val = float(raw)
        if val > 1.0:
            return min(1.0, val / 100.0)
        return max(0.0, min(1.0, val))

    return 0.5


def _compress_status(
    blockers: list[BlockerCode],
    band: CoherenceBand,
    l5_analysis: dict[str, Any],
    warnings: list[str],
) -> tuple[L5Status, bool]:
    """Compress to final PASS/WARN/FAIL per frozen spec."""
    if blockers:
        return L5Status.FAIL, False

    if band == CoherenceBand.LOW:
        return L5Status.FAIL, False

    freshness = l5_analysis.get("freshness_state", "FRESH")
    warmup = l5_analysis.get("warmup_state", "READY")
    fallback = l5_analysis.get("fallback_class", "NO_FALLBACK")

    # PASS: cleanest envelope
    is_clean = (
        freshness == "FRESH"
        and warmup == "READY"
        and band == CoherenceBand.HIGH
        and fallback in ("NO_FALLBACK", "LEGAL_PRIMARY_SUBSTITUTE")
        and not warnings  # no warning-level degradation at all
    )

    if is_clean:
        return L5Status.PASS, True

    # WARN: legal but degraded
    legal_degraded = (
        freshness in ("FRESH", "STALE_PRESERVED", "DEGRADED")
        and warmup in ("READY", "PARTIAL")
        and band in (CoherenceBand.HIGH, CoherenceBand.MID)
        and fallback in ("NO_FALLBACK", "LEGAL_PRIMARY_SUBSTITUTE", "LEGAL_EMERGENCY_PRESERVE")
    )

    if legal_degraded:
        return L5Status.WARN, True

    return L5Status.FAIL, False


# ═══════════════════════════════════════════════════════════════════════════
# §4  GOVERNOR
# ═══════════════════════════════════════════════════════════════════════════


class L5ConstitutionalGovernor:
    """Strict constitutional evaluator for L5 psychology/emotional readiness."""

    VERSION = "1.0.0"

    def evaluate(
        self,
        l4_output: dict[str, Any],
        l5_analysis: dict[str, Any],
        symbol: str = "",
    ) -> dict[str, Any]:
        """Run full L5 constitutional evaluation.

        Returns a dict with the canonical L5 output contract fields.
        """
        timestamp = l5_analysis.get("timestamp", datetime.now(UTC).isoformat())
        input_ref = f"{symbol}_L5" if symbol else "L5"

        # Step 1–9: collect blockers
        blockers = _collect_blockers(l4_output, l5_analysis)

        # Step 10: collect warnings
        warnings = _collect_warning_codes(l5_analysis)

        # Step 11: score band
        psych_score = _compute_psychology_score(l5_analysis)
        band = _score_band(psych_score)

        # Step 12–13: compress
        status, continuation_allowed = _compress_status(
            blockers, band, l5_analysis, warnings,
        )

        next_targets = ["PHASE_2_5"] if continuation_allowed else []

        # Build rule_hits
        rule_hits = [
            f"score_band={band.value}",
            f"freshness_state={l5_analysis.get('freshness_state', 'FRESH')}",
            f"warmup_state={l5_analysis.get('warmup_state', 'READY')}",
            f"fallback_class={l5_analysis.get('fallback_class', 'NO_FALLBACK')}",
            f"psychology_score={psych_score:.4f}",
            f"discipline_score={l5_analysis.get('discipline_score', 1.0):.4f}",
            f"fatigue_level={l5_analysis.get('fatigue_level', 'LOW')}",
            f"focus_level={l5_analysis.get('focus_level', 1.0):.4f}",
        ]

        logger.debug(
            "L5 constitutional: symbol=%s status=%s band=%s score=%.4f blockers=%d",
            symbol, status.value, band.value, psych_score, len(blockers),
        )

        return {
            "layer": "L5",
            "layer_version": self.VERSION,
            "timestamp": timestamp,
            "input_ref": input_ref,
            "status": status.value,
            "continuation_allowed": continuation_allowed,
            "blocker_codes": [b.value for b in blockers],
            "warning_codes": warnings,
            "fallback_class": l5_analysis.get("fallback_class", "NO_FALLBACK"),
            "freshness_state": l5_analysis.get("freshness_state", "FRESH"),
            "warmup_state": l5_analysis.get("warmup_state", "READY"),
            "coherence_band": band.value,
            "score_numeric": round(psych_score, 4),
            "features": {
                "feature_vector": {
                    "psychology_score": round(psych_score, 4),
                    "discipline_score": round(float(l5_analysis.get("discipline_score", 1.0)), 4),
                    "fatigue_level": str(l5_analysis.get("fatigue_level", "LOW")).upper(),
                    "focus_level": round(float(l5_analysis.get("focus_level", 1.0)), 4),
                    "revenge_trading": bool(l5_analysis.get("revenge_trading", False)),
                    "fomo_level": round(float(l5_analysis.get("fomo_level", l5_analysis.get("fomo_score", 0.0))), 4),
                    "emotional_bias": round(float(l5_analysis.get("emotional_bias", l5_analysis.get("emotion_delta", 0.0))), 4),
                    "risk_event_active": bool(l5_analysis.get("risk_event_active", False)),
                    "caution_event": bool(l5_analysis.get("caution_event", False)),
                    "eaf_score": round(float(l5_analysis.get("eaf_score", 0.0)), 4),
                    "can_trade": bool(l5_analysis.get("can_trade", True)),
                    "gate_status": str(l5_analysis.get("gate_status", "OPEN")),
                },
                "feature_hash": f"L5_{band.value}_{status.value}_{int(round(psych_score * 100))}",
            },
            "routing": {
                "source_used": list(l5_analysis.get("psychology_sources_used", ["eaf_engine"])),
                "fallback_used": l5_analysis.get("fallback_class", "NO_FALLBACK") != "NO_FALLBACK",
                "next_legal_targets": next_targets,
            },
            "audit": {
                "rule_hits": rule_hits,
                "blocker_triggered": bool(blockers),
                "notes": list(l5_analysis.get("warnings", [])),
            },
        }
