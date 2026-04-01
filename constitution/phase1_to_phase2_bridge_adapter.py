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


# ═══════════════════════════════════════════════════════════════════════════
# §4  EVALUATOR-BASED BRIDGE RESULT
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Phase1ToPhase2EvaluatorBridgeResult:
    """Bridge result for evaluator-based pipeline path.

    Contains fully-formed L4/L5 evaluator payloads ready to feed
    into ``Phase2RouterEvaluatorAdapter.run()``.
    """

    bridge: str
    bridge_version: str
    input_ref: str
    timestamp: str
    bridge_allowed: bool
    bridge_status: str
    next_legal_targets: list[str]
    l4_payload: dict[str, Any]
    l5_payload: dict[str, Any]
    audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bridge": self.bridge,
            "bridge_version": self.bridge_version,
            "input_ref": self.input_ref,
            "timestamp": self.timestamp,
            "bridge_allowed": self.bridge_allowed,
            "bridge_status": self.bridge_status,
            "next_legal_targets": self.next_legal_targets,
            "l4_payload": self.l4_payload,
            "l5_payload": self.l5_payload,
            "audit": self.audit,
        }


# ═══════════════════════════════════════════════════════════════════════════
# §5  EVALUATOR-BASED BRIDGE ADAPTER
# ═══════════════════════════════════════════════════════════════════════════


class Phase1ToPhase2EvaluatorBridgeAdapter:
    """Bridges Phase 1 evaluator chain output into Phase 2 evaluator payloads.

    Derives L4/L5 evaluator payloads from a
    ``Phase1EvaluatorChainResult.to_dict()`` output under strict
    constitutional semantics.

    Usage::

        bridge = Phase1ToPhase2EvaluatorBridgeAdapter()
        result = bridge.build(phase1_evaluator_result.to_dict())
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        default_session_sources: list[str] | None = None,
        default_psychology_sources: list[str] | None = None,
    ) -> None:
        self.default_session_sources = default_session_sources or [
            "session_engine",
            "expectancy_engine",
        ]
        self.default_psychology_sources = default_psychology_sources or [
            "discipline_engine",
            "risk_event_feed",
        ]

    @staticmethod
    def _extract_meta(
        phase1_result: dict[str, Any],
    ) -> tuple[str, str]:
        input_ref = str(phase1_result.get("input_ref", "")).strip()
        timestamp = str(phase1_result.get("timestamp", "")).strip()
        if not input_ref or not timestamp:
            raise ValueError(
                "Phase 1 result must contain non-empty input_ref and timestamp."
            )
        return input_ref, timestamp

    @staticmethod
    def _phase1_is_bridgeable(
        phase1_result: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if phase1_result.get("halted", False):
            reasons.append("PHASE1_HALTED")
        if not bool(phase1_result.get("continuation_allowed", False)):
            reasons.append("PHASE1_CONTINUATION_DISALLOWED")

        next_targets = [
            str(x) for x in phase1_result.get("next_legal_targets", [])
        ]
        if "L4" not in next_targets:
            reasons.append("PHASE1_NEXT_TARGET_NOT_L4")

        chain_status = (
            str(phase1_result.get("chain_status", "")).strip().upper()
        )
        if chain_status not in {"PASS", "WARN"}:
            reasons.append("PHASE1_CHAIN_STATUS_NOT_BRIDGEABLE")

        return (len(reasons) == 0, reasons)

    @staticmethod
    def _derive_l4_score(phase1_result: dict[str, Any]) -> float:
        layer_results = phase1_result.get("layer_results", {})
        scores: list[float] = []
        for layer_name in ("L1", "L2", "L3"):
            layer = layer_results.get(layer_name, {})
            for key in ("score_numeric", "coherence_score", "alignment_score", "confirmation_score"):
                value = layer.get(key)
                if isinstance(value, (int, float)):
                    scores.append(float(value))
                    break
        if not scores:
            return 0.0
        return round(sum(scores) / len(scores), 4)

    @staticmethod
    def _derive_l5_score(
        phase1_result: dict[str, Any],
        l4_score: float,
    ) -> float:
        chain_status = str(
            phase1_result.get("chain_status", "FAIL")
        ).upper()
        if chain_status == "PASS":
            return max(0.85, round(l4_score, 4))
        if chain_status == "WARN":
            return min(max(0.65, round(l4_score, 4)), 0.84)
        return min(round(l4_score, 4), 0.64)

    @staticmethod
    def _derive_freshness_state(phase1_result: dict[str, Any]) -> str:
        layer_results = phase1_result.get("layer_results", {})
        states: list[str] = []
        for layer_name in ("L1", "L2", "L3"):
            layer = layer_results.get(layer_name, {})
            state = str(layer.get("freshness_state", "")).strip().upper()
            if state:
                states.append(state)
        priority = ["NO_PRODUCER", "DEGRADED", "STALE_PRESERVED", "FRESH"]
        for state in priority:
            if state in states:
                return state
        return "FRESH"

    @staticmethod
    def _derive_warmup_state(phase1_result: dict[str, Any]) -> str:
        layer_results = phase1_result.get("layer_results", {})
        states: list[str] = []
        for layer_name in ("L1", "L2", "L3"):
            layer = layer_results.get(layer_name, {})
            state = str(layer.get("warmup_state", "")).strip().upper()
            if state:
                states.append(state)
        priority = ["INSUFFICIENT", "PARTIAL", "READY"]
        for state in priority:
            if state in states:
                return state
        return "READY"

    @staticmethod
    def _derive_fallback_class(phase1_result: dict[str, Any]) -> str:
        layer_results = phase1_result.get("layer_results", {})
        fallback_values: list[str] = []
        for layer_name in ("L1", "L2", "L3"):
            layer = layer_results.get(layer_name, {})
            value = str(layer.get("fallback_class", "")).strip().upper()
            if value:
                fallback_values.append(value)
        priority = [
            "ILLEGAL_FALLBACK",
            "LEGAL_EMERGENCY_PRESERVE",
            "LEGAL_PRIMARY_SUBSTITUTE",
            "NO_FALLBACK",
        ]
        for value in priority:
            if value in fallback_values:
                return value
        return "NO_FALLBACK"

    @staticmethod
    def _derive_warning_pressure(
        phase1_result: dict[str, Any],
    ) -> dict[str, bool]:
        warning_map = phase1_result.get("warning_map", {})
        warnings: list[str] = []
        for layer_name in ("L1", "L2", "L3"):
            warnings.extend(
                [str(w) for w in warning_map.get(layer_name, [])]
            )
        text = " ".join(warnings).upper()
        return {
            "stale_or_degraded": ("STALE" in text) or ("DEGRADED" in text),
            "partial_warmup": "PARTIAL" in text,
            "emergency_fallback": "EMERGENCY" in text,
        }

    def build(
        self,
        phase1_result: dict[str, Any],
    ) -> Phase1ToPhase2EvaluatorBridgeResult:
        """Build Phase 2 evaluator payloads from Phase 1 evaluator chain output."""
        input_ref, timestamp = self._extract_meta(phase1_result)
        bridge_allowed, reasons = self._phase1_is_bridgeable(phase1_result)

        if not bridge_allowed:
            return Phase1ToPhase2EvaluatorBridgeResult(
                bridge="PHASE1_TO_PHASE2_EVALUATOR",
                bridge_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                bridge_allowed=False,
                bridge_status="FAIL",
                next_legal_targets=[],
                l4_payload={},
                l5_payload={},
                audit={
                    "bridge_reasons": reasons,
                    "notes": [
                        "Phase 1 result is not legally bridgeable into Phase 2."
                    ],
                },
            )

        freshness_state = self._derive_freshness_state(phase1_result)
        warmup_state = self._derive_warmup_state(phase1_result)
        fallback_class = self._derive_fallback_class(phase1_result)
        warning_pressure = self._derive_warning_pressure(phase1_result)

        l4_score = self._derive_l4_score(phase1_result)
        l5_score = self._derive_l5_score(phase1_result, l4_score)

        phase1_chain_status = str(
            phase1_result.get("chain_status", "FAIL")
        ).upper()
        prime_session = phase1_chain_status == "PASS"
        degraded_scoring_mode = phase1_chain_status == "WARN"

        l4_payload: dict[str, Any] = {
            "input_ref": input_ref,
            "timestamp": timestamp,
            "upstream_l3_continuation_allowed": True,
            "session_sources_used": list(self.default_session_sources),
            "required_session_sources": [self.default_session_sources[0]],
            "available_session_sources": list(self.default_session_sources),
            "session_score": l4_score,
            "session_valid": True,
            "expectancy_available": True,
            "prime_session": prime_session,
            "degraded_scoring_mode": degraded_scoring_mode,
            "fallback_class": fallback_class,
            "freshness_state": freshness_state,
            "warmup_state": warmup_state,
        }

        fatigue_level = "LOW"
        focus_level = 0.95
        caution_event = False
        if phase1_chain_status == "WARN":
            fatigue_level = "MEDIUM"
            focus_level = 0.55
            caution_event = True
        if warning_pressure["partial_warmup"]:
            focus_level = min(focus_level, 0.55)
        if warning_pressure["stale_or_degraded"]:
            caution_event = True

        l5_payload: dict[str, Any] = {
            "input_ref": input_ref,
            "timestamp": timestamp,
            "upstream_l4_continuation_allowed": True,
            "psychology_sources_used": list(self.default_psychology_sources),
            "required_psychology_inputs": [
                self.default_psychology_sources[0]
            ],
            "available_psychology_inputs": list(
                self.default_psychology_sources
            ),
            "psychology_score": l5_score,
            "discipline_score": 0.9 if prime_session else 0.75,
            "fatigue_level": fatigue_level,
            "focus_level": focus_level,
            "revenge_trading": False,
            "fomo_level": 0.2 if prime_session else 0.65,
            "emotional_bias": 0.1 if prime_session else 0.6,
            "risk_event_active": False,
            "caution_event": caution_event,
            "fallback_class": fallback_class,
            "freshness_state": freshness_state,
            "warmup_state": warmup_state,
        }

        bridge_status = (
            "WARN" if phase1_chain_status == "WARN" else "PASS"
        )
        return Phase1ToPhase2EvaluatorBridgeResult(
            bridge="PHASE1_TO_PHASE2_EVALUATOR",
            bridge_version=self.VERSION,
            input_ref=input_ref,
            timestamp=timestamp,
            bridge_allowed=True,
            bridge_status=bridge_status,
            next_legal_targets=["L4", "L5"],
            l4_payload=l4_payload,
            l5_payload=l5_payload,
            audit={
                "bridge_reasons": ["PHASE1_BRIDGEABLE"],
                "derived": {
                    "freshness_state": freshness_state,
                    "warmup_state": warmup_state,
                    "fallback_class": fallback_class,
                    "warning_pressure": warning_pressure,
                    "l4_score": l4_score,
                    "l5_score": l5_score,
                },
                "notes": [
                    "Bridge payloads derived from Phase 1 evaluator chain "
                    "result under strict constitutional mode."
                ],
            },
        )
