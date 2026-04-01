"""
Phase 3 Chain Adapter — Strict Sequential Halt-on-Failure
=========================================================

Enforces the Phase 3 canonical pipeline semantics:
    L7 → L8 → L9 (strict sequential, halt-on-failure)

Operates on bridge-derived payloads (from
FoundationScoringEnrichmentToPhase3BridgeAdapter).  Each layer is
evaluated against its constitutional threshold bands.  If any layer
produces a FAIL status, the chain halts and returns a Phase3ChainResult
with the failure details.

Authority boundary:
  This adapter orchestrates Phase 3 only. It does not emit direction,
  verdict, or execution authority.  It connects probability / integrity /
  structure validation to enforce halt-on-failure semantics.

Zone: constitution/ — pipeline governance, no execution side-effects.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# §1  THRESHOLDS  (frozen — sourced from L7/L8/L9 constitutional governors)
# ═══════════════════════════════════════════════════════════════════════════

L7_HIGH = 0.67
L7_MID = 0.55

L8_HIGH = 0.88
L8_MID = 0.75

L9_HIGH = 0.80
L9_MID = 0.65

HARD_FAIL_FRESHNESS = "NO_PRODUCER"
HARD_FAIL_WARMUP = "INSUFFICIENT"
HARD_FAIL_FALLBACK = "ILLEGAL_FALLBACK"

WARN_FRESHNESS = ("STALE_PRESERVED", "DEGRADED")
WARN_WARMUP = ("PARTIAL",)
WARN_FALLBACK = ("LEGAL_EMERGENCY_PRESERVE", "LEGAL_PRIMARY_SUBSTITUTE")


# ═══════════════════════════════════════════════════════════════════════════
# §2  CHAIN RESULT
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class Phase3ChainResult:
    """Result of the Phase 3 chain execution (L7 → L8 → L9)."""

    phase: str = "PHASE_3_STRUCTURE"
    status: str = "PASS"
    continuation_allowed: bool = True
    halted_at: str | None = None
    next_legal_targets: list[str] = field(default_factory=lambda: ["PHASE_4"])
    summary_status: dict[str, str] = field(default_factory=dict)
    layer_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timing_ms: dict[str, float] = field(default_factory=dict)

    @property
    def chain_status(self) -> str:
        """Chain status as string (alias for status)."""
        return self.status

    @property
    def halted(self) -> bool:
        """Whether the chain halted before completing all layers."""
        return self.halted_at is not None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for pipeline consumption."""
        return {
            "phase": self.phase,
            "chain_status": self.status,
            "continuation_allowed": self.continuation_allowed,
            "halted": self.halted,
            "halted_at": self.halted_at,
            "next_legal_targets": self.next_legal_targets,
            "summary_status": dict(self.summary_status),
            "layer_results": dict(self.layer_results),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "timing_ms": dict(self.timing_ms),
        }


# ═══════════════════════════════════════════════════════════════════════════
# §3  LAYER EVALUATORS  (bridge-payload-oriented)
# ═══════════════════════════════════════════════════════════════════════════


def _evaluate_layer(
    payload: dict[str, Any],
    score_key: str,
    high_threshold: float,
    mid_threshold: float,
    label: str,
) -> tuple[str, list[str], list[str]]:
    """Evaluate a single layer from a bridge-derived payload.

    Returns (status, blockers, warnings).
    """
    blockers: list[str] = []
    warnings: list[str] = []

    # ── Hard gates ────────────────────────────────────────────────────
    freshness = str(payload.get("freshness_state", "FRESH")).upper()
    if freshness == HARD_FAIL_FRESHNESS:
        blockers.append(f"{label}_FRESHNESS_NO_PRODUCER")

    warmup = str(payload.get("warmup_state", "READY")).upper()
    if warmup == HARD_FAIL_WARMUP:
        blockers.append(f"{label}_WARMUP_INSUFFICIENT")

    fallback = str(payload.get("fallback_class", "NO_FALLBACK")).upper()
    if fallback == HARD_FAIL_FALLBACK:
        blockers.append(f"{label}_ILLEGAL_FALLBACK")

    # ── Score band ────────────────────────────────────────────────────
    score = float(payload.get(score_key, 0.0))
    if score < mid_threshold:
        blockers.append(f"{label}_SCORE_BELOW_MINIMUM")
    elif score < high_threshold:
        warnings.append(f"{label}_SCORE_MID_BAND")

    # ── Advisory warnings ─────────────────────────────────────────────
    if freshness in WARN_FRESHNESS:
        warnings.append(f"{label}_FRESHNESS_{freshness}")
    if warmup in WARN_WARMUP:
        warnings.append(f"{label}_WARMUP_{warmup}")
    if fallback in WARN_FALLBACK:
        warnings.append(f"{label}_FALLBACK_{fallback}")

    # Layer-specific degradation flags
    for flag_key in (
        "validation_partial", "edge_status",
        "tii_partial", "twms_partial", "governance_degraded", "stability_non_ideal",
        "entry_timing_degraded", "liquidity_partial", "structure_non_ideal",
    ):
        val = payload.get(flag_key)
        if val is True:
            warnings.append(f"{label}_{flag_key.upper()}")
        elif isinstance(val, str) and val.upper() == "DEGRADED":
            warnings.append(f"{label}_{flag_key.upper()}_DEGRADED")

    # ── Compress ──────────────────────────────────────────────────────
    if blockers:
        return "FAIL", blockers, warnings
    if warnings:
        return "WARN", blockers, warnings
    return "PASS", blockers, warnings


# ═══════════════════════════════════════════════════════════════════════════
# §4  PAYLOAD BUILDER
# ═══════════════════════════════════════════════════════════════════════════


def build_phase3_payloads_from_dict(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Extract and validate L7/L8/L9 payloads from a combined dict.

    Parameters
    ----------
    payload : dict
        Must contain ``L7``, ``L8``, and ``L9`` keys.

    Returns
    -------
    tuple[dict, dict, dict]
        (l7_payload, l8_payload, l9_payload)

    Raises
    ------
    ValueError
        If any of L7/L8/L9 is missing.
    """
    missing = [k for k in ("L7", "L8", "L9") if k not in payload]
    if missing:
        raise ValueError(
            f"Phase 3 payload must contain L7, L8, and L9 keys. Missing: {missing}"
        )
    return dict(payload["L7"]), dict(payload["L8"]), dict(payload["L9"])


# ═══════════════════════════════════════════════════════════════════════════
# §5  PHASE 3 CHAIN ADAPTER
# ═══════════════════════════════════════════════════════════════════════════


class Phase3ChainAdapter:
    """Strict sequential halt-on-failure chain for Phase 3 (L7 → L8 → L9).

    Operates on bridge-derived payloads.  Each layer is evaluated against
    its constitutional threshold bands.  Upstream continuation flags are
    injected between layers.

    Usage::

        adapter = Phase3ChainAdapter()
        l7, l8, l9 = build_phase3_payloads_from_dict(combined)
        result = adapter.run(l7, l8, l9)
    """

    def run(
        self,
        l7_payload: dict[str, Any],
        l8_payload: dict[str, Any],
        l9_payload: dict[str, Any],
    ) -> Phase3ChainResult:
        """Execute the Phase 3 chain.

        Parameters
        ----------
        l7_payload : dict
            Bridge-derived L7 payload (probability / edge).
        l8_payload : dict
            Bridge-derived L8 payload (integrity / TII).
        l9_payload : dict
            Bridge-derived L9 payload (structure / SMC).
        """
        timing: dict[str, float] = {}
        errors: list[str] = []
        warnings: list[str] = []
        summary: dict[str, str] = {}
        layer_results: dict[str, dict[str, Any]] = {}
        worst_status = "PASS"

        # ── Step 1: L7 ───────────────────────────────────────────────
        t0 = time.monotonic()
        l7_status, l7_blockers, l7_warns = _evaluate_layer(
            l7_payload, "win_probability", L7_HIGH, L7_MID, "L7",
        )
        timing["L7"] = (time.monotonic() - t0) * 1000

        summary["L7"] = l7_status
        layer_results["L7"] = {
            "status": l7_status,
            "blockers": l7_blockers,
            "warnings": l7_warns,
            "payload": l7_payload,
        }
        errors.extend(f"L7_BLOCKER:{b}" for b in l7_blockers)
        warnings.extend(f"L7:{w}" for w in l7_warns)

        if l7_status == "WARN":
            worst_status = "WARN"

        if l7_status == "FAIL":
            logger.warning(
                "[Phase3] L7 HALT | blockers=%s",
                l7_blockers,
            )
            return Phase3ChainResult(
                status="FAIL",
                continuation_allowed=False,
                halted_at="L7",
                next_legal_targets=[],
                summary_status=summary,
                layer_results=layer_results,
                errors=errors,
                warnings=warnings,
                timing_ms=timing,
            )

        # ── Step 2: L8 (inject upstream flag) ────────────────────────
        l8_payload_resolved = dict(l8_payload)
        l8_payload_resolved["upstream_l7_continuation_allowed"] = True

        t0 = time.monotonic()
        l8_status, l8_blockers, l8_warns = _evaluate_layer(
            l8_payload_resolved, "integrity_score", L8_HIGH, L8_MID, "L8",
        )
        timing["L8"] = (time.monotonic() - t0) * 1000

        summary["L8"] = l8_status
        layer_results["L8"] = {
            "status": l8_status,
            "blockers": l8_blockers,
            "warnings": l8_warns,
            "payload": l8_payload_resolved,
        }
        errors.extend(f"L8_BLOCKER:{b}" for b in l8_blockers)
        warnings.extend(f"L8:{w}" for w in l8_warns)

        if l8_status == "WARN" and worst_status == "PASS":
            worst_status = "WARN"

        if l8_status == "FAIL":
            logger.warning(
                "[Phase3] L8 HALT | blockers=%s",
                l8_blockers,
            )
            return Phase3ChainResult(
                status="FAIL",
                continuation_allowed=False,
                halted_at="L8",
                next_legal_targets=[],
                summary_status=summary,
                layer_results=layer_results,
                errors=errors,
                warnings=warnings,
                timing_ms=timing,
            )

        # ── Step 3: L9 (inject upstream flag) ────────────────────────
        l9_payload_resolved = dict(l9_payload)
        l9_payload_resolved["upstream_l8_continuation_allowed"] = True

        t0 = time.monotonic()
        l9_status, l9_blockers, l9_warns = _evaluate_layer(
            l9_payload_resolved, "structure_score", L9_HIGH, L9_MID, "L9",
        )
        timing["L9"] = (time.monotonic() - t0) * 1000

        summary["L9"] = l9_status
        layer_results["L9"] = {
            "status": l9_status,
            "blockers": l9_blockers,
            "warnings": l9_warns,
            "payload": l9_payload_resolved,
        }
        errors.extend(f"L9_BLOCKER:{b}" for b in l9_blockers)
        warnings.extend(f"L9:{w}" for w in l9_warns)

        if l9_status == "WARN" and worst_status == "PASS":
            worst_status = "WARN"

        if l9_status == "FAIL":
            logger.warning(
                "[Phase3] L9 HALT | blockers=%s",
                l9_blockers,
            )
            return Phase3ChainResult(
                status="FAIL",
                continuation_allowed=False,
                halted_at="L9",
                next_legal_targets=[],
                summary_status=summary,
                layer_results=layer_results,
                errors=errors,
                warnings=warnings,
                timing_ms=timing,
            )

        # ── All passed ───────────────────────────────────────────────
        return Phase3ChainResult(
            status=worst_status,
            continuation_allowed=True,
            halted_at=None,
            next_legal_targets=["PHASE_4"],
            summary_status=summary,
            layer_results=layer_results,
            errors=errors,
            warnings=warnings,
            timing_ms=timing,
        )
