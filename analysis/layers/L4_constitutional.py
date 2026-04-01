"""
L4 Constitutional Governor — Strict Mode v1.0.0
================================================

Constitutional sub-gate evaluator for L4 session/scoring legality.

Implements the frozen L4 spec:
  - Evaluation order: upstream → contract → sources → freshness → warmup
    → fallback → session → expectancy → score band → compress → emit
  - Critical blockers spec (frozen v1)
  - Fallback legality matrix (frozen v1)
  - Freshness / warmup states
  - Session score thresholds (frozen baseline v1)
  - Final compression logic (strict mode)

Authority boundary:
  L4 is a session/scoring legality governor only.
  L4 must never emit direction, execute, trade_valid, position_size, or verdict.
  Hard legality checks run before score band evaluation.
  status == FAIL implies continuation_allowed == false.
  continuation_allowed == true implies next_legal_targets == ["L5"].

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


class L4Status(str, Enum):
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
    UPSTREAM_L3_NOT_CONTINUABLE = "UPSTREAM_L3_NOT_CONTINUABLE"
    REQUIRED_SESSION_SOURCE_MISSING = "REQUIRED_SESSION_SOURCE_MISSING"
    SESSION_STATE_INVALID = "SESSION_STATE_INVALID"
    SESSION_EXPECTANCY_UNAVAILABLE = "SESSION_EXPECTANCY_UNAVAILABLE"
    FRESHNESS_GOVERNANCE_HARD_FAIL = "FRESHNESS_GOVERNANCE_HARD_FAIL"
    WARMUP_INSUFFICIENT = "WARMUP_INSUFFICIENT"
    FALLBACK_DECLARED_BUT_NOT_ALLOWED = "FALLBACK_DECLARED_BUT_NOT_ALLOWED"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


# ═══════════════════════════════════════════════════════════════════════════
# §2  FROZEN THRESHOLDS
# ═══════════════════════════════════════════════════════════════════════════

HIGH_THRESHOLD: float = 0.85
MID_THRESHOLD: float = 0.65


def _score_band(score: float) -> CoherenceBand:
    if score >= HIGH_THRESHOLD:
        return CoherenceBand.HIGH
    if score >= MID_THRESHOLD:
        return CoherenceBand.MID
    return CoherenceBand.LOW


# ═══════════════════════════════════════════════════════════════════════════
# §3  SUB-GATE: Upstream Legality
# ═══════════════════════════════════════════════════════════════════════════


def _check_upstream_legality(
    l3_output: dict[str, Any],
) -> list[BlockerCode]:
    """Check L3 authorized continuation into L4."""
    continuation = l3_output.get("continuation_allowed", l3_output.get("valid", False))
    if not continuation:
        return [BlockerCode.UPSTREAM_L3_NOT_CONTINUABLE]
    return []


# ═══════════════════════════════════════════════════════════════════════════
# §4  SUB-GATE: Contract Payload Validation
# ═══════════════════════════════════════════════════════════════════════════


def _check_contract_payload(
    input_ref: str,
    timestamp: str,
) -> list[BlockerCode]:
    if not input_ref or not timestamp:
        return [BlockerCode.CONTRACT_PAYLOAD_MALFORMED]
    return []


# ═══════════════════════════════════════════════════════════════════════════
# §5  SUB-GATE: Required Session Sources
# ═══════════════════════════════════════════════════════════════════════════


def _check_required_sources(
    required: list[str],
    available: list[str],
) -> tuple[list[BlockerCode], list[str]]:
    """Check required session/scoring sources availability."""
    missing = sorted(set(required) - set(available))
    blockers: list[BlockerCode] = []
    notes: list[str] = []
    if missing:
        blockers.append(BlockerCode.REQUIRED_SESSION_SOURCE_MISSING)
        notes.append(f"Missing required session sources: {', '.join(missing)}")
    return blockers, notes


# ═══════════════════════════════════════════════════════════════════════════
# §6  SUB-GATE: Freshness Legality
# ═══════════════════════════════════════════════════════════════════════════


def _check_freshness(
    state: FreshnessState,
) -> tuple[list[BlockerCode], list[str]]:
    blockers: list[BlockerCode] = []
    warnings: list[str] = []
    if state == FreshnessState.NO_PRODUCER:
        blockers.append(BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL)
    elif state == FreshnessState.STALE_PRESERVED:
        warnings.append("STALE_PRESERVED_CONTEXT")
    elif state == FreshnessState.DEGRADED:
        warnings.append("DEGRADED_CONTEXT")
    return blockers, warnings


# ═══════════════════════════════════════════════════════════════════════════
# §7  SUB-GATE: Warmup Legality
# ═══════════════════════════════════════════════════════════════════════════


def _check_warmup(
    state: WarmupState,
) -> tuple[list[BlockerCode], list[str]]:
    blockers: list[BlockerCode] = []
    warnings: list[str] = []
    if state == WarmupState.INSUFFICIENT:
        blockers.append(BlockerCode.WARMUP_INSUFFICIENT)
    elif state == WarmupState.PARTIAL:
        warnings.append("PARTIAL_WARMUP")
    return blockers, warnings


# ═══════════════════════════════════════════════════════════════════════════
# §8  SUB-GATE: Fallback Legality
# ═══════════════════════════════════════════════════════════════════════════


def _check_fallback(
    fb_class: FallbackClass,
) -> tuple[list[BlockerCode], list[str], list[str]]:
    blockers: list[BlockerCode] = []
    warnings: list[str] = []
    rule_hits: list[str] = []
    if fb_class == FallbackClass.ILLEGAL_FALLBACK:
        blockers.append(BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED)
    elif fb_class == FallbackClass.LEGAL_EMERGENCY_PRESERVE:
        warnings.append("LEGAL_EMERGENCY_PRESERVE_USED")
    elif fb_class == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE:
        rule_hits.append("LEGAL_PRIMARY_SUBSTITUTE")
    return blockers, warnings, rule_hits


# ═══════════════════════════════════════════════════════════════════════════
# §9  SUB-GATE: Session & Expectancy Validity
# ═══════════════════════════════════════════════════════════════════════════


def _check_session_validity(
    session_valid: bool,
    expectancy_available: bool,
) -> list[BlockerCode]:
    blockers: list[BlockerCode] = []
    if not session_valid:
        blockers.append(BlockerCode.SESSION_STATE_INVALID)
    if not expectancy_available:
        blockers.append(BlockerCode.SESSION_EXPECTANCY_UNAVAILABLE)
    return blockers


# ═══════════════════════════════════════════════════════════════════════════
# §10  COMPRESSION LOGIC
# ═══════════════════════════════════════════════════════════════════════════


def _compress_status(
    blockers: list[BlockerCode],
    band: CoherenceBand,
    freshness: FreshnessState,
    warmup: WarmupState,
    fallback: FallbackClass,
    prime_session: bool,
    degraded_scoring: bool,
) -> tuple[L4Status, bool]:
    """Return (status, continuation_allowed)."""
    if blockers:
        return L4Status.FAIL, False

    if band == CoherenceBand.LOW:
        return L4Status.FAIL, False

    # Check for clean PASS
    is_clean = (
        freshness == FreshnessState.FRESH
        and warmup == WarmupState.READY
        and fallback in (FallbackClass.NO_FALLBACK, FallbackClass.LEGAL_PRIMARY_SUBSTITUTE)
        and band == CoherenceBand.HIGH
        and prime_session
        and not degraded_scoring
    )
    if is_clean:
        return L4Status.PASS, True

    # Any degradation → WARN
    return L4Status.WARN, True


# ═══════════════════════════════════════════════════════════════════════════
# §11  GOVERNOR
# ═══════════════════════════════════════════════════════════════════════════


class L4ConstitutionalGovernor:
    """Strict constitutional governor for L4 session/scoring legality.

    Follows frozen evaluation order:
      1. check upstream L3 legality
      2. check contract payload
      3. check required session sources
      4. check freshness legality
      5. check warmup legality
      6. check fallback legality
      7. check session/expectancy validity
      8. compute score band
      9. compress status
     10. set continuation
     11. emit contract
    """

    VERSION = "1.0.0"

    def evaluate(
        self,
        l3_output: dict[str, Any],
        l4_analysis: dict[str, Any],
        symbol: str = "",
    ) -> dict[str, Any]:
        """Evaluate L4 constitutional legality.

        Parameters
        ----------
        l3_output : dict
            L3 constitutional output (must include continuation_allowed or valid).
        l4_analysis : dict
            Raw L4 session/scoring analysis output from L4SessionScoring.analyze().
        symbol : str
            Currency pair identifier.

        Returns
        -------
        dict
            Constitutional envelope per L4 spec v1.0.0.
        """
        ts = datetime.now(UTC).isoformat()
        input_ref = f"{symbol}_L4_{ts}" if symbol else f"L4_{ts}"

        all_blockers: list[BlockerCode] = []
        all_warnings: list[str] = []
        all_rule_hits: list[str] = []
        all_notes: list[str] = []

        # ── 1. Upstream legality ──────────────────────────────────
        all_blockers.extend(_check_upstream_legality(l3_output))

        # ── 2. Contract payload ───────────────────────────────────
        all_blockers.extend(_check_contract_payload(input_ref, ts))

        # ── 3. Required session sources ───────────────────────────
        # Derive from L4 analysis: session engine and expectancy
        sources_used: list[str] = []
        if l4_analysis.get("session"):
            sources_used.append("session_engine")
        if l4_analysis.get("bayesian", {}).get("expected_value") is not None:
            sources_used.append("expectancy_engine")

        required_sources = ["session_engine"]
        available_sources = sources_used

        src_blockers, src_notes = _check_required_sources(required_sources, available_sources)
        all_blockers.extend(src_blockers)
        all_notes.extend(src_notes)

        # ── 4. Freshness legality ─────────────────────────────────
        freshness = FreshnessState.FRESH
        if not l4_analysis.get("tradeable", True):
            freshness = FreshnessState.DEGRADED
        fr_blockers, fr_warnings = _check_freshness(freshness)
        all_blockers.extend(fr_blockers)
        all_warnings.extend(fr_warnings)

        # ── 5. Warmup legality ────────────────────────────────────
        warmup = WarmupState.READY
        # Check if scoring data is sufficient
        wolf = l4_analysis.get("wolf_30_point", {})
        if not wolf:
            warmup = WarmupState.INSUFFICIENT
        elif wolf.get("total", 0) == 0:
            warmup = WarmupState.PARTIAL
        wu_blockers, wu_warnings = _check_warmup(warmup)
        all_blockers.extend(wu_blockers)
        all_warnings.extend(wu_warnings)

        # ── 6. Fallback legality ──────────────────────────────────
        fallback = FallbackClass.NO_FALLBACK
        fb_blockers, fb_warnings, fb_rules = _check_fallback(fallback)
        all_blockers.extend(fb_blockers)
        all_warnings.extend(fb_warnings)
        all_rule_hits.extend(fb_rules)

        # ── 7. Session/expectancy validity ────────────────────────
        session_valid = l4_analysis.get("valid", True)
        bayesian = l4_analysis.get("bayesian", {})
        expectancy_available = bayesian.get("expected_value") is not None

        sv_blockers = _check_session_validity(session_valid, expectancy_available)
        all_blockers.extend(sv_blockers)

        # ── 8. Compute score band ────────────────────────────────
        # Normalize session score: Wolf 30-point total / 30 → [0, 1]
        wolf_total = wolf.get("total", 0.0) if wolf else 0.0
        session_score = min(1.0, max(0.0, wolf_total / 30.0))

        # Boost from Bayesian confidence index
        ci = bayesian.get("confidence_index", 0.0)
        if ci > 0:
            session_score = min(1.0, session_score * 0.7 + ci * 0.3)

        band = _score_band(session_score)
        all_rule_hits.append(f"score_band={band.value}")
        all_rule_hits.append(f"session_score={session_score:.4f}")
        all_rule_hits.append(f"wolf_total={wolf_total:.1f}")

        # ── 9. Session quality checks ─────────────────────────────
        prime_session = l4_analysis.get("quality", 0.0) >= 0.60
        degraded_scoring = l4_analysis.get("grade", "FAIL") == "FAIL"

        if not prime_session:
            all_warnings.append("NON_PRIME_BUT_LEGAL_SESSION")
        if degraded_scoring:
            all_warnings.append("DEGRADED_SCORING_MODE")

        # ── 10. Compress status ───────────────────────────────────
        status, continuation_allowed = _compress_status(
            all_blockers, band, freshness, warmup, fallback,
            prime_session, degraded_scoring,
        )

        # LOW band adds synthetic blocker for audit
        if band == CoherenceBand.LOW and not any(
            b == BlockerCode.UPSTREAM_L3_NOT_CONTINUABLE for b in all_blockers
        ):
            all_blockers.append(BlockerCode.SESSION_STATE_INVALID)
            all_notes.append(f"Session score too low: {session_score:.4f}")

        # ── 11. Emit contract ─────────────────────────────────────
        next_targets = ["L5"] if continuation_allowed else []

        # Collect warnings for PASS status (e.g., PRIMARY_SUBSTITUTE)
        if status == L4Status.PASS and fb_warnings:
            all_warnings.extend(fb_warnings)

        # Deduplicate
        blocker_codes = list(dict.fromkeys(b.value for b in all_blockers))
        warning_codes = list(dict.fromkeys(all_warnings))

        features = {
            "feature_vector": {
                "session_score": round(session_score, 4),
                "wolf_total": wolf_total,
                "session_valid": session_valid,
                "expectancy_available": expectancy_available,
                "prime_session": prime_session,
                "degraded_scoring_mode": degraded_scoring,
                "grade": l4_analysis.get("grade", "UNKNOWN"),
                "quality": l4_analysis.get("quality", 0.0),
            },
            "feature_hash": f"L4_{band.value}_{status.value}_{int(round(session_score * 100))}",
        }

        routing = {
            "source_used": sources_used,
            "fallback_used": fallback != FallbackClass.NO_FALLBACK,
            "next_legal_targets": next_targets,
        }

        audit = {
            "rule_hits": all_rule_hits,
            "blocker_triggered": bool(all_blockers),
            "notes": all_notes,
        }

        result = {
            "layer": "L4",
            "layer_version": self.VERSION,
            "timestamp": ts,
            "input_ref": input_ref,
            "status": status.value,
            "continuation_allowed": continuation_allowed,
            "blocker_codes": blocker_codes,
            "warning_codes": warning_codes,
            "fallback_class": fallback.value,
            "freshness_state": freshness.value,
            "warmup_state": warmup.value,
            "coherence_band": band.value,
            "score_numeric": round(session_score, 4),
            "features": features,
            "routing": routing,
            "audit": audit,
        }

        logger.info(
            "[L4 Constitutional] %s status=%s band=%s score=%.4f "
            "continuation=%s blockers=%s warnings=%s",
            symbol, status.value, band.value, session_score,
            continuation_allowed, blocker_codes, warning_codes,
        )

        return result
