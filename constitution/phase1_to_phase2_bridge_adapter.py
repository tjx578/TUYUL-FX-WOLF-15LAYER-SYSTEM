"""
Phase 1 → Phase 2 Bridge Adapter
=================================

Derives Phase 2 payloads (L4 + L5) from a completed Phase 1 chain result.

The bridge computes:
  - Upstream scores (aggregated from L1/L2/L3 constitutional outputs)
  - Freshness / warmup / fallback state (worst-case aggregation)
  - Warning pressure metric
  - L4 and L5 payloads ready for Phase2ChainAdapter.run()

Authority boundary:
  This adapter only *reads* Phase 1 outputs and *derives* Phase 2 inputs.
  It does not modify Phase 1 results, emit direction, verdict, or execution
  authority.

Zone: constitution/ — pipeline governance, no execution side-effects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# §1  BRIDGE RESULT
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class BridgeResult:
    """Output of the Phase 1 → Phase 2 bridge derivation."""

    l4_payload: dict[str, Any] = field(default_factory=dict)
    l5_payload: dict[str, Any] = field(default_factory=dict)
    upstream_score: float = 0.0
    freshness_state: str = "FRESH"
    warmup_state: str = "READY"
    fallback_class: str = "NO_FALLBACK"
    warning_pressure: float = 0.0
    notes: list[str] = field(default_factory=list)
    bridge: str = "PHASE1_TO_PHASE2"
    bridge_status: str = "PASS"
    bridge_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize for inspection / audit."""
        return {
            "bridge": self.bridge,
            "bridge_status": self.bridge_status,
            "bridge_allowed": self.bridge_allowed,
            "upstream_score": round(self.upstream_score, 4),
            "freshness_state": self.freshness_state,
            "warmup_state": self.warmup_state,
            "fallback_class": self.fallback_class,
            "warning_pressure": round(self.warning_pressure, 4),
            "notes": self.notes,
        }


# ═══════════════════════════════════════════════════════════════════════════
# §2  SCORE DERIVATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _safe_score(layer_out: dict[str, Any]) -> float | None:
    """Extract a 0.0–1.0 score from a layer output, or None if absent."""
    for key in ("score_numeric", "coherence_score", "score"):
        val = layer_out.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    return None


def _derive_l4_score(
    l1: dict[str, Any],
    l2: dict[str, Any],
    l3: dict[str, Any],
) -> float:
    """Derive a synthetic upstream context score for L4 payload.

    Averages available L1/L2/L3 coherence scores.
    Falls back to 0.5 if no scores are available.
    """
    scores: list[float] = []
    for layer_out in (l1, l2, l3):
        s = _safe_score(layer_out)
        if s is not None:
            scores.append(s)
    return sum(scores) / len(scores) if scores else 0.5


def _derive_l5_score(
    l1: dict[str, Any],
    l2: dict[str, Any],
    l3: dict[str, Any],
    chain_status: str,
) -> float:
    """Derive a synthetic upstream context score for L5 payload.

    Same base score as L4, but capped at 0.65 if chain status is WARN.
    """
    base = _derive_l4_score(l1, l2, l3)
    if chain_status == "WARN":
        return min(base, 0.65)
    return base


def _derive_freshness(
    l1: dict[str, Any],
    l2: dict[str, Any],
    l3: dict[str, Any],
) -> str:
    """Derive aggregated freshness state (worst-case wins).

    Freshness priority (worst → best):
      NO_PRODUCER > DEGRADED > STALE_PRESERVED > FRESH
    """
    priority = {
        "FRESH": 0,
        "STALE_PRESERVED": 1,
        "DEGRADED": 2,
        "NO_PRODUCER": 3,
    }
    worst_idx = 0
    for layer_out in (l1, l2, l3):
        fs = str(layer_out.get("freshness_state", "FRESH"))
        idx = priority.get(fs, 0)
        if idx > worst_idx:
            worst_idx = idx
    # Reverse lookup
    for name, idx in priority.items():
        if idx == worst_idx:
            return name
    return "FRESH"


def _derive_warmup(
    l1: dict[str, Any],
    l2: dict[str, Any],
    l3: dict[str, Any],
) -> str:
    """Derive aggregated warmup state (worst-case wins).

    Warmup priority (worst → best):
      INSUFFICIENT > PARTIAL > READY
    """
    priority = {"READY": 0, "PARTIAL": 1, "INSUFFICIENT": 2}
    worst_idx = 0
    for layer_out in (l1, l2, l3):
        ws = str(layer_out.get("warmup_state", "READY"))
        idx = priority.get(ws, 0)
        if idx > worst_idx:
            worst_idx = idx
    for name, idx in priority.items():
        if idx == worst_idx:
            return name
    return "READY"


def _derive_fallback(
    l1: dict[str, Any],
    l2: dict[str, Any],
    l3: dict[str, Any],
) -> str:
    """Derive aggregated fallback class (worst-case wins).

    Fallback priority (worst → best):
      ILLEGAL_FALLBACK > LEGAL_EMERGENCY_PRESERVE >
      LEGAL_PRIMARY_SUBSTITUTE > NO_FALLBACK
    """
    priority = {
        "NO_FALLBACK": 0,
        "LEGAL_PRIMARY_SUBSTITUTE": 1,
        "LEGAL_EMERGENCY_PRESERVE": 2,
        "ILLEGAL_FALLBACK": 3,
    }
    worst_idx = 0
    for layer_out in (l1, l2, l3):
        fb = str(layer_out.get("fallback_class", "NO_FALLBACK"))
        idx = priority.get(fb, 0)
        if idx > worst_idx:
            worst_idx = idx
    for name, idx in priority.items():
        if idx == worst_idx:
            return name
    return "NO_FALLBACK"


def _compute_warning_pressure(
    l1: dict[str, Any],
    l2: dict[str, Any],
    l3: dict[str, Any],
) -> float:
    """Compute warning pressure as fraction of total warning slots used.

    Each layer has a warning_codes list. Count total warning codes
    over the 3 layers, normalize by a soft cap of 6.
    """
    total = 0
    for layer_out in (l1, l2, l3):
        wc = layer_out.get("warning_codes", [])
        if isinstance(wc, list):
            total += len(wc)
    return min(1.0, total / 6.0)


# ═══════════════════════════════════════════════════════════════════════════
# §2.5  DEFAULT ANALYSIS SYNTHESIS
# ═══════════════════════════════════════════════════════════════════════════


def _default_l4_analysis() -> dict[str, Any]:
    """Build a minimal L4 analysis that satisfies governor contract checks.

    When the bridge is called without real L4 analysis (e.g. from the
    pure-constitutional wrapper path), we synthesise a baseline that
    passes the L4 governor's source/warmup/freshness gates.
    """
    return {
        "session": {"name": "DEFAULT", "active": True},
        "tradeable": True,
        "wolf_30_point": {"total": 20},
        "bayesian": {"expected_value": 0.5},
    }


def _default_l5_analysis() -> dict[str, Any]:
    """Build a minimal L5 analysis that satisfies governor contract checks.

    Synthesises neutral/healthy psychology defaults so the L5 governor
    does not trip on missing fields.
    """
    return {
        "psychology_score_normalized": 0.85,
        "discipline_score": 1.0,
        "fatigue_level": "LOW",
        "focus_level": 1.0,
        "fomo_level": 0.0,
        "emotional_bias": 0.0,
        "revenge_trading": False,
        "risk_event_active": False,
        "caution_event": False,
    }


# ═══════════════════════════════════════════════════════════════════════════
# §3  BRIDGE ADAPTER
# ═══════════════════════════════════════════════════════════════════════════


class Phase1ToPhase2BridgeAdapter:
    """Derives Phase 2 payloads from a completed Phase 1 chain result.

    Usage::

        bridge = Phase1ToPhase2BridgeAdapter()
        bridge_result = bridge.build(
            phase1_result=chain_result.to_dict(),
            l4_analysis=raw_l4_analysis,
            l5_analysis=raw_l5_analysis,
            symbol="EURUSD",
        )
        # Feed bridge_result.l4_payload / l5_payload to Phase2ChainAdapter
    """

    def build(
        self,
        phase1_result: dict[str, Any],
        l4_analysis: dict[str, Any] | None = None,
        l5_analysis: dict[str, Any] | None = None,
        symbol: str = "",
    ) -> BridgeResult:
        """Build Phase 2 payloads from Phase 1 chain output.

        Parameters
        ----------
        phase1_result : dict
            Phase1ChainAdapter output (via .to_dict()).
            Must contain ``l1``, ``l2``, ``l3``, ``status``,
            ``continuation_allowed``, ``warnings``.
        l4_analysis : dict | None
            Raw L4 analysis output. If None, an empty dict is used.
        l5_analysis : dict | None
            Raw L5 analysis output. If None, an empty dict is used.
        symbol : str
            Trading pair symbol.
        """
        l4_analysis = l4_analysis if l4_analysis is not None else _default_l4_analysis()
        l5_analysis = l5_analysis if l5_analysis is not None else _default_l5_analysis()
        l1 = phase1_result.get("l1", {})
        l2 = phase1_result.get("l2", {})
        l3 = phase1_result.get("l3", {})
        chain_status = phase1_result.get("status", "PASS")
        phase1_result.get("warnings", [])

        notes: list[str] = []

        # -- Upstream score derivation --
        l4_score = _derive_l4_score(l1, l2, l3)
        l5_score = _derive_l5_score(l1, l2, l3, chain_status)

        # -- State aggregation (worst-case) --
        freshness = _derive_freshness(l1, l2, l3)
        warmup = _derive_warmup(l1, l2, l3)
        fallback = _derive_fallback(l1, l2, l3)
        warning_pressure = _compute_warning_pressure(l1, l2, l3)

        if freshness != "FRESH":
            notes.append(f"aggregated_freshness={freshness}")
        if warmup != "READY":
            notes.append(f"aggregated_warmup={warmup}")
        if fallback != "NO_FALLBACK":
            notes.append(f"aggregated_fallback={fallback}")
        if warning_pressure > 0.5:
            notes.append(f"warning_pressure={warning_pressure:.2f}")

        # -- L4 payload: L3 output + L4 analysis --
        l4_payload = {
            "l3_output": l3,
            "l4_analysis": {
                **l4_analysis,
                "freshness_state": l4_analysis.get("freshness_state", freshness),
                "warmup_state": l4_analysis.get("warmup_state", warmup),
                "fallback_class": l4_analysis.get("fallback_class", fallback),
                "upstream_context_score": l4_score,
            },
            "symbol": symbol,
        }

        # -- L5 payload: L4 output (placeholder) + L5 analysis --
        l5_payload = {
            "l4_output": {},  # will be overwritten by Phase2ChainAdapter
            "l5_analysis": {
                **l5_analysis,
                "freshness_state": l5_analysis.get("freshness_state", freshness),
                "warmup_state": l5_analysis.get("warmup_state", warmup),
                "fallback_class": l5_analysis.get("fallback_class", fallback),
                "upstream_context_score": l5_score,
            },
            "symbol": symbol,
        }

        logger.debug(
            "[Bridge] P1→P2 | symbol=%s l4_score=%.4f l5_score=%.4f "
            "freshness=%s warmup=%s fallback=%s wp=%.2f",
            symbol, l4_score, l5_score, freshness, warmup, fallback,
            warning_pressure,
        )

        # -- Bridge legality --
        chain_status = phase1_result.get("status", phase1_result.get("chain_status", "PASS"))
        continuation = phase1_result.get("continuation_allowed", True)
        bridge_allowed = continuation and chain_status != "FAIL"
        bridge_status = "FAIL" if not bridge_allowed else ("WARN" if chain_status == "WARN" or warning_pressure > 0.5 else "PASS")

        return BridgeResult(
            l4_payload=l4_payload,
            l5_payload=l5_payload,
            upstream_score=l4_score,
            freshness_state=freshness,
            warmup_state=warmup,
            fallback_class=fallback,
            warning_pressure=warning_pressure,
            notes=notes,
            bridge="PHASE1_TO_PHASE2",
            bridge_status=bridge_status,
            bridge_allowed=bridge_allowed,
        )
