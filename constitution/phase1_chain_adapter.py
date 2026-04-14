"""
Phase 1 Chain Adapter — Always-Forward Scoring
================================================

Enforces Phase 1 canonical pipeline semantics:
    L1 → L2 → L3 (strict sequential, always-forward)

Each layer always executes regardless of upstream failure.
Layer failures are recorded as degraded scores and blockers,
but the chain never halts. L12 is the sole verdict authority.

If a layer raises an exception, the chain records the error
and continues with an empty result for that layer.

Authority boundary:
  This adapter orchestrates Phase 1 only. It does not emit direction,
  verdict, or execution authority. It connects layers sequentially
  and collects scores for downstream consumption by L12.

Zone: constitution/ — pipeline governance, no execution side-effects.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# §1  CHAIN RESULT
# ═══════════════════════════════════════════════════════════════════════════


class ChainStatus(StrEnum):
    """Phase 1 chain execution status."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class ChainResult:
    """Result of the Phase 1 chain execution."""

    status: ChainStatus
    continuation_allowed: bool
    halted_at: str | None = None  # Deprecated — always None (chain never halts)
    failed_at: str | None = None  # First layer that failed (diagnostics only)
    l1: dict[str, Any] = field(default_factory=dict)
    l2: dict[str, Any] = field(default_factory=dict)
    l3: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timing_ms: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for pipeline consumption."""
        return {
            "phase": "PHASE_1",
            "status": self.status.value,
            "chain_status": self.status.value,
            "continuation_allowed": self.continuation_allowed,
            "halted": False,
            "halted_at": None,
            "failed_at": self.failed_at,
            "l1": self.l1,
            "l2": self.l2,
            "l3": self.l3,
            "errors": self.errors,
            "warnings": self.warnings,
            "timing_ms": self.timing_ms,
        }

    @property
    def chain_status(self) -> str:
        """Chain status as string (alias for status.value)."""
        return self.status.value

    @property
    def halted(self) -> bool:
        """Whether the chain halted before completing all layers.

        .. deprecated:: Always returns False — chain always completes.
        """
        return False


# ═══════════════════════════════════════════════════════════════════════════
# §2  PHASE 1 CHAIN ADAPTER
# ═══════════════════════════════════════════════════════════════════════════


class Phase1ChainAdapter:
    """Always-forward scoring chain for Phase 1 (L1 → L2 → L3).

    Usage::

        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: l1.analyze(sym),
            l2_callable=lambda sym: l2.analyze(sym),
            l3_callable=lambda sym, l2_out: l3.analyze(sym),
        )
        result = adapter.execute("EURUSD")

    The adapter:
    1. Runs L1, records status/blockers
    2. Always runs L2 (even if L1 failed), records status/blockers
    3. Injects L2 output into L3, always runs L3, records status/blockers
    4. Returns ChainResult with all layer outputs — L12 decides verdict

    Layer failures degrade the chain status and are recorded as errors,
    but the chain never halts early. ``failed_at`` tracks the first
    layer that failed (for diagnostics), but all layers always execute.
    """

    def __init__(
        self,
        l1_callable: Callable[[str], dict[str, Any]],
        l2_callable: Callable[[str], dict[str, Any]],
        l3_callable: Callable[[str], dict[str, Any]],
        l3_l2_injector: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize Phase 1 Chain Adapter.

        Parameters
        ----------
        l1_callable : Callable[[str], dict]
            L1 analysis function: f(symbol) -> dict
        l2_callable : Callable[[str], dict]
            L2 analysis function: f(symbol) -> dict
        l3_callable : Callable[[str], dict]
            L3 analysis function: f(symbol) -> dict
        l3_l2_injector : Callable[[dict], None] | None
            Optional function to inject L2 output into L3 analyzer
            before L3 executes. E.g. l3.set_l2_output(l2_out).
        """
        self._l1 = l1_callable
        self._l2 = l2_callable
        self._l3 = l3_callable
        self._l3_l2_injector = l3_l2_injector

    def execute(self, symbol: str) -> ChainResult:
        """Execute the Phase 1 chain for *symbol*.

        All three layers always execute. Failures are recorded but
        never halt the chain. Returns ChainResult with layer outputs
        and degradation details for L12 consumption.
        """
        timing: dict[str, float] = {}
        errors: list[str] = []
        warnings: list[str] = []
        worst_status = ChainStatus.PASS
        failed_at: str | None = None

        l1: dict[str, Any] = {}
        l2: dict[str, Any] = {}
        l3: dict[str, Any] = {}

        # ── Step 1: L1 ───────────────────────────────────────
        l1_start = time.monotonic()
        try:
            l1 = self._l1(symbol)
        except Exception as exc:
            logger.error("[Phase1] L1 raised: %s: %s", type(exc).__name__, exc, exc_info=True)
            errors.append(f"L1_EXCEPTION:{type(exc).__name__}")
            worst_status = ChainStatus.FAIL
            failed_at = failed_at or "L1"
        timing["L1"] = (time.monotonic() - l1_start) * 1000

        l1_continue = l1.get("continuation_allowed", l1.get("valid", False))
        l1_status = l1.get("status", "PASS" if l1_continue else "FAIL")
        l1_blockers = l1.get("blocker_codes", [])
        l1_warnings = l1.get("warning_codes", [])

        if l1_status == "WARN":
            if worst_status == ChainStatus.PASS:
                worst_status = ChainStatus.WARN
            warnings.extend(f"L1:{w}" for w in l1_warnings)

        if not l1_continue:
            worst_status = ChainStatus.FAIL
            failed_at = failed_at or "L1"
            errors.append(f"L1_FAIL:status={l1_status}")
            errors.extend(f"L1_BLOCKER:{b}" for b in l1_blockers)
            if not l1_blockers and not any("L1_EXCEPTION" in e for e in errors):
                errors.append("L1_BLOCKER:UNCLASSIFIED_FAIL")
            logger.warning(
                "[Phase1] L1 FAIL | symbol=%s status=%s blockers=%s warnings=%s (chain continues)",
                symbol,
                l1_status,
                l1_blockers,
                l1_warnings,
            )

        # ── Step 2: L2 (always runs) ─────────────────────────
        l2_start = time.monotonic()
        try:
            l2 = self._l2(symbol)
        except Exception as exc:
            logger.error("[Phase1] L2 raised: %s: %s", type(exc).__name__, exc, exc_info=True)
            errors.append(f"L2_EXCEPTION:{type(exc).__name__}")
            worst_status = ChainStatus.FAIL
            failed_at = failed_at or "L2"
        timing["L2"] = (time.monotonic() - l2_start) * 1000

        l2_continue = l2.get("continuation_allowed", l2.get("valid", False))
        l2_status = l2.get("status", "PASS" if l2_continue else "FAIL")
        l2_blockers = l2.get("blocker_codes", [])
        l2_warnings = l2.get("warning_codes", [])

        if l2_status == "WARN" and worst_status == ChainStatus.PASS:
            worst_status = ChainStatus.WARN
            warnings.extend(f"L2:{w}" for w in l2_warnings)

        if not l2_continue:
            worst_status = ChainStatus.FAIL
            failed_at = failed_at or "L2"
            errors.append(f"L2_FAIL:status={l2_status}")
            errors.extend(f"L2_BLOCKER:{b}" for b in l2_blockers)
            if not l2_blockers and not any("L2_EXCEPTION" in e for e in errors):
                errors.append("L2_BLOCKER:UNCLASSIFIED_FAIL")
            logger.warning(
                "[Phase1] L2 FAIL | symbol=%s status=%s blockers=%s warnings=%s (chain continues)",
                symbol,
                l2_status,
                l2_blockers,
                l2_warnings,
            )

        # ── Step 3: L3 (always runs, with L2 injection) ──────
        if self._l3_l2_injector is not None:
            self._l3_l2_injector(l2)

        l3_start = time.monotonic()
        try:
            l3 = self._l3(symbol)
        except Exception as exc:
            logger.error("[Phase1] L3 raised: %s: %s", type(exc).__name__, exc, exc_info=True)
            errors.append(f"L3_EXCEPTION:{type(exc).__name__}")
            worst_status = ChainStatus.FAIL
            failed_at = failed_at or "L3"
        timing["L3"] = (time.monotonic() - l3_start) * 1000

        l3_continue = l3.get("continuation_allowed", l3.get("valid", False))
        l3_status = l3.get("status", "PASS" if l3_continue else "FAIL")
        l3_blockers = l3.get("blocker_codes", [])
        l3_warnings = l3.get("warning_codes", [])

        if l3_status == "WARN" and worst_status == ChainStatus.PASS:
            worst_status = ChainStatus.WARN
            warnings.extend(f"L3:{w}" for w in l3_warnings)

        if not l3_continue:
            worst_status = ChainStatus.FAIL
            failed_at = failed_at or "L3"
            errors.append(f"L3_FAIL:status={l3_status}")
            errors.extend(f"L3_BLOCKER:{b}" for b in l3_blockers)
            if not l3_blockers and not any("L3_EXCEPTION" in e for e in errors):
                errors.append("L3_BLOCKER:UNCLASSIFIED_FAIL")
            logger.warning(
                "[Phase1] L3 FAIL | symbol=%s status=%s blockers=%s warnings=%s",
                symbol,
                l3_status,
                l3_blockers,
                l3_warnings,
            )

        # ── Chain complete — always forward to L12 ───────────
        # continuation_allowed is always True: L12 decides verdict.
        # failed_at records the first failure for diagnostics only.
        if worst_status == ChainStatus.FAIL:
            logger.warning(
                "[Phase1] DEGRADED | symbol=%s failed_at=%s L1=%s L2=%s L3=%s "
                "timing_ms=L1:%.1f/L2:%.1f/L3:%.1f (forwarding to L12)",
                symbol,
                failed_at,
                l1_status,
                l2_status,
                l3_status,
                timing.get("L1", 0),
                timing.get("L2", 0),
                timing.get("L3", 0),
            )
        else:
            logger.info(
                "[Phase1] %s | symbol=%s L1=%s L2=%s L3=%s timing_ms=L1:%.1f/L2:%.1f/L3:%.1f",
                worst_status.value,
                symbol,
                l1_status,
                l2_status,
                l3_status,
                timing.get("L1", 0),
                timing.get("L2", 0),
                timing.get("L3", 0),
            )

        return ChainResult(
            status=worst_status,
            continuation_allowed=True,  # Always forward — L12 is sole verdict authority
            halted_at=None,  # Chain never halts
            failed_at=failed_at,
            l1=l1,
            l2=l2,
            l3=l3,
            errors=errors,
            warnings=warnings,
            timing_ms=timing,
        )

    # ── Pure constitutional evaluation (no callables) ────────
    def run(
        self,
        l1_payload: dict[str, Any],
        l2_payload: dict[str, Any],
        l3_payload: dict[str, Any],
    ) -> ChainResult:
        """Evaluate Phase 1 constitutional governors from pre-computed payloads.

        Unlike :meth:`execute` (which calls layer analyzers), this method
        takes raw dict payloads, builds governor inputs, and evaluates
        the constitutional chain directly.

        Payloads may be simplified wrapper dicts (e.g. only
        ``alignment_score``, ``confirmation_score``, ``freshness_state``).
        Missing required governor fields are synthesised from the
        available fields so that the governor evaluation is legal.

        Returns ChainResult with constitutional outputs for L1, L2, L3.
        """
        from analysis.layers.L1_constitutional import (
            L1GateInput,
            evaluate_l1_constitutional,
        )
        from analysis.layers.L2_constitutional import L2ConstitutionalGovernor
        from analysis.layers.L3_constitutional import L3ConstitutionalGovernor

        timing: dict[str, float] = {}
        errors: list[str] = []
        warnings: list[str] = []
        worst = ChainStatus.PASS

        # ── L1 ────────────────────────────────────────────────
        t0 = time.monotonic()
        try:
            l1_inp = L1GateInput(
                analysis_result={
                    "regime": l1_payload.get("regime", "UNKNOWN"),
                    "context_coherence": l1_payload.get("context_coherence", 0.0),
                    "valid": True,
                },
                symbol=l1_payload.get("symbol", ""),
                feed_timestamp=time.time(),  # current time → FRESH
                producer_available=l1_payload.get("freshness_state", "FRESH") != "NO_PRODUCER",
                snapshot_valid=l1_payload.get("warmup_state", "READY") != "INSUFFICIENT",
            )
            l1_result_obj = evaluate_l1_constitutional(l1_inp)
            l1 = l1_result_obj.to_dict()
        except Exception as exc:
            logger.error("[Phase1.run] L1 raised: %s", exc, exc_info=True)
            errors.append(f"L1_EXCEPTION:{type(exc).__name__}")
            return ChainResult(
                status=ChainStatus.FAIL,
                continuation_allowed=False,
                halted_at="L1",
                errors=errors,
                timing_ms=timing,
            )
        timing["L1"] = (time.monotonic() - t0) * 1000

        l1_continue = l1.get("continuation_allowed", False)
        l1_status = l1.get("status", "FAIL")
        if l1_status == "WARN":
            worst = ChainStatus.WARN
            warnings.extend(f"L1:{w}" for w in l1.get("warning_codes", []))
        if not l1_continue:
            errors.append(f"L1_HALT:status={l1_status}")
            return ChainResult(
                status=ChainStatus.FAIL,
                continuation_allowed=False,
                halted_at="L1",
                l1=l1,
                errors=errors,
                warnings=warnings,
                timing_ms=timing,
            )

        # ── L2 ────────────────────────────────────────────────
        t0 = time.monotonic()
        try:
            l2_analysis = _enrich_l2_payload(l2_payload)
            l2_gov = L2ConstitutionalGovernor()
            l2 = l2_gov.evaluate(
                l1_output=l1,
                l2_analysis=l2_analysis,
                symbol=l2_payload.get("symbol", ""),
                fallback_used=bool(l2_payload.get("fallback_class")),
                fallback_source=l2_payload.get("fallback_class", ""),
                fallback_approved=l2_payload.get("fallback_class", "")
                in (
                    "LEGAL_PRIMARY_SUBSTITUTE",
                    "LEGAL_EMERGENCY_PRESERVE",
                ),
            )
        except Exception as exc:
            logger.error("[Phase1.run] L2 raised: %s", exc, exc_info=True)
            errors.append(f"L2_EXCEPTION:{type(exc).__name__}")
            return ChainResult(
                status=ChainStatus.FAIL,
                continuation_allowed=False,
                halted_at="L2",
                l1=l1,
                errors=errors,
                timing_ms=timing,
            )
        timing["L2"] = (time.monotonic() - t0) * 1000

        l2_continue = l2.get("continuation_allowed", False)
        l2_status = l2.get("status", "FAIL")
        if l2_status == "WARN" and worst == ChainStatus.PASS:
            worst = ChainStatus.WARN
            warnings.extend(f"L2:{w}" for w in l2.get("warning_codes", []))
        if not l2_continue:
            errors.append(f"L2_HALT:status={l2_status}")
            return ChainResult(
                status=ChainStatus.FAIL,
                continuation_allowed=False,
                halted_at="L2",
                l1=l1,
                l2=l2,
                errors=errors,
                warnings=warnings,
                timing_ms=timing,
            )

        # ── L3 ────────────────────────────────────────────────
        t0 = time.monotonic()
        try:
            l3_analysis = _enrich_l3_payload(l3_payload)
            l3_gov = L3ConstitutionalGovernor()
            l3 = l3_gov.evaluate(
                l2_output=l2,
                l3_analysis=l3_analysis,
                symbol=l3_payload.get("symbol", ""),
                fallback_used=bool(l3_payload.get("fallback_class")),
                fallback_source=l3_payload.get("fallback_class", ""),
                fallback_approved=l3_payload.get("fallback_class", "")
                in (
                    "LEGAL_PRIMARY_SUBSTITUTE",
                    "LEGAL_EMERGENCY_PRESERVE",
                ),
            )
        except Exception as exc:
            logger.error("[Phase1.run] L3 raised: %s", exc, exc_info=True)
            errors.append(f"L3_EXCEPTION:{type(exc).__name__}")
            return ChainResult(
                status=ChainStatus.FAIL,
                continuation_allowed=False,
                halted_at="L3",
                l1=l1,
                l2=l2,
                errors=errors,
                timing_ms=timing,
            )
        timing["L3"] = (time.monotonic() - t0) * 1000

        l3_continue = l3.get("continuation_allowed", False)
        l3_status = l3.get("status", "FAIL")
        if l3_status == "WARN" and worst == ChainStatus.PASS:
            worst = ChainStatus.WARN
            warnings.extend(f"L3:{w}" for w in l3.get("warning_codes", []))
        if not l3_continue:
            errors.append(f"L3_HALT:status={l3_status}")
            return ChainResult(
                status=ChainStatus.FAIL,
                continuation_allowed=False,
                halted_at="L3",
                l1=l1,
                l2=l2,
                l3=l3,
                errors=errors,
                warnings=warnings,
                timing_ms=timing,
            )

        return ChainResult(
            status=worst,
            continuation_allowed=True,
            halted_at=None,
            l1=l1,
            l2=l2,
            l3=l3,
            errors=errors,
            warnings=warnings,
            timing_ms=timing,
        )


# ═══════════════════════════════════════════════════════════════════════════
# §3  PAYLOAD ENRICHMENT HELPERS
# ═══════════════════════════════════════════════════════════════════════════

# Default timeframe set for L2 when not supplied in the payload.
_DEFAULT_TFS = ["MN", "W1", "D1", "H4", "H1", "M15"]


def _enrich_l2_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Build a proper L2 analysis dict from a (possibly simplified) payload.

    If the payload already contains the required keys (``valid``,
    ``per_tf_bias``) it is returned as-is.  Otherwise, the wrapper
    synthesises the structural fields the L2 governor requires
    (hierarchy, alignment, timeframe set) from the higher-level
    ``alignment_score`` / ``freshness_state`` keys.
    """
    if "valid" in raw and "per_tf_bias" in raw:
        return raw

    alignment = raw.get("alignment_score", 0.0)
    freshness = raw.get("freshness_state", "FRESH")

    # Build per_tf_bias so _extract_available_tfs finds real TF keys
    tfs = raw.get("available_timeframes", _DEFAULT_TFS)
    if isinstance(tfs, int):
        tfs = _DEFAULT_TFS[:tfs]
    per_tf_bias = {tf: {"bias": "NEUTRAL"} for tf in tfs}

    enriched: dict[str, Any] = {
        "valid": freshness != "NO_PRODUCER",
        "per_tf_bias": per_tf_bias,
        "available_timeframes": len(tfs),
        "hierarchy_followed": True,
        "aligned": alignment >= 0.65,
        "alignment_strength": alignment,
    }
    enriched.update(raw)
    return enriched


def _enrich_l3_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Build a proper L3 analysis dict from a (possibly simplified) payload.

    If the payload already contains the required keys (``valid``,
    ``trend``, ``technical_score``) it is returned as-is.  Otherwise,
    the wrapper synthesises the structural fields from the
    ``confirmation_score`` / ``freshness_state`` keys.
    """
    if "valid" in raw and "trend" in raw and "technical_score" in raw:
        return raw

    confirmation = raw.get("confirmation_score", 0.0)
    freshness = raw.get("freshness_state", "FRESH")

    enriched: dict[str, Any] = {
        "valid": freshness != "NO_PRODUCER",
        "trend": "BULLISH" if confirmation >= 0.5 else "NEUTRAL",
        "technical_score": int(confirmation * 100),
        "edge_probability": confirmation,
        "trend_strength": 3 if confirmation >= 0.5 else 0,
        "trq3d_energy": 1.0 if confirmation >= 0.5 else 0.0,
        "structure_validity": "STRONG" if confirmation >= 0.65 else "WEAK",
        "confidence": int(confirmation * 100),
    }
    enriched.update(raw)
    return enriched


# ═══════════════════════════════════════════════════════════════════════════
# §4  PAYLOAD BUILDER
# ═══════════════════════════════════════════════════════════════════════════


def build_phase1_payloads_from_dict(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Extract L1, L2, L3 payloads from a combined Phase 1 dict.

    Expected keys: ``L1``, ``L2``, ``L3`` (each a dict).
    Returns (l1_payload, l2_payload, l3_payload).
    """
    l1 = payload.get("L1", {})
    l2 = payload.get("L2", {})
    l3 = payload.get("L3", {})
    return dict(l1), dict(l2), dict(l3)


# ═══════════════════════════════════════════════════════════════════════════
# §5  ROUTER EVALUATOR CHAIN
# ═══════════════════════════════════════════════════════════════════════════


class Phase1EvaluatorChainResult:
    """Rich result from the router-evaluator based Phase 1 chain.

    Wraps the canonical :class:`Phase1ChainResult` from the router
    evaluator prototype and also exposes a :meth:`to_dict` compatible
    with the rest of the constitution layer.
    """

    __slots__ = (
        "phase",
        "phase_version",
        "input_ref",
        "timestamp",
        "halted",
        "halted_at",
        "continuation_allowed",
        "next_legal_targets",
        "chain_status",
        "summary_status",
        "blocker_map",
        "warning_map",
        "layer_results",
        "audit",
    )

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            object.__setattr__(self, k, v)

    def to_dict(self) -> dict[str, Any]:
        return {s: getattr(self, s) for s in self.__slots__}


class Phase1RouterEvaluatorAdapter:
    """Runs L1→L2→L3 using the standalone router evaluators.

    This adapter delegates to ``L1RouterEvaluator``, ``L2RouterEvaluator``,
    ``L3RouterEvaluator`` from ``constitution/`` and orchestrates them in
    strict halt-safe order with upstream flag injection.

    Usage::

        adapter = Phase1RouterEvaluatorAdapter()
        result = adapter.run(l1_payload, l2_payload, l3_payload)
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        l1_evaluator: Any | None = None,
        l2_evaluator: Any | None = None,
        l3_evaluator: Any | None = None,
    ) -> None:
        from constitution.l1_router_evaluator import L1RouterEvaluator
        from constitution.l2_router_evaluator import L2RouterEvaluator
        from constitution.l3_router_evaluator import L3RouterEvaluator

        self.l1_evaluator = l1_evaluator or L1RouterEvaluator()
        self.l2_evaluator = l2_evaluator or L2RouterEvaluator()
        self.l3_evaluator = l3_evaluator or L3RouterEvaluator()

    @staticmethod
    def _canonicalize(payloads: list[dict[str, Any]], key: str) -> str:
        vals = [str(p.get(key, "")).strip() for p in payloads]
        non_empty = [v for v in vals if v]
        if not non_empty:
            raise ValueError(f"Phase 1 requires at least one non-empty {key}.")
        return non_empty[0]

    @staticmethod
    def _inject_upstream(
        l1_result: Any | None,
        l2_payload: dict[str, Any],
        l2_result: Any | None,
        l3_payload: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        l2_rt = dict(l2_payload)
        if l1_result is not None:
            l2_rt["upstream_l1_continuation_allowed"] = l1_result.continuation_allowed

        l3_rt = dict(l3_payload)
        if l2_result is not None:
            l3_rt["upstream_l2_continuation_allowed"] = l2_result.continuation_allowed

        return l2_rt, l3_rt

    def run(
        self,
        l1_payload: dict[str, Any],
        l2_payload: dict[str, Any],
        l3_payload: dict[str, Any],
    ) -> Phase1EvaluatorChainResult:
        """Evaluate Phase 1 chain using router evaluators."""
        from constitution.l1_router_evaluator import build_l1_input_from_dict
        from constitution.l2_router_evaluator import build_l2_input_from_dict
        from constitution.l3_router_evaluator import build_l3_input_from_dict

        payloads = [l1_payload, l2_payload, l3_payload]
        input_ref = self._canonicalize(payloads, "input_ref")
        timestamp = self._canonicalize(payloads, "timestamp")

        summary_status: dict[str, str] = {}
        blocker_map: dict[str, list[str]] = {}
        warning_map: dict[str, list[str]] = {}
        layer_results: dict[str, dict[str, Any]] = {}
        audit_steps: list[str] = []

        def _halt(at: str, reason: str) -> Phase1EvaluatorChainResult:
            audit_steps.append(f"Chain halted at {at}")
            return Phase1EvaluatorChainResult(
                phase="PHASE_1_FOUNDATION",
                phase_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                halted=True,
                halted_at=at,
                continuation_allowed=False,
                next_legal_targets=[],
                chain_status="FAIL",
                summary_status=summary_status,
                blocker_map=blocker_map,
                warning_map=warning_map,
                layer_results=layer_results,
                audit={"halt_safe": True, "steps": audit_steps, "reason": reason},
            )

        # ── L1 ────────────────────────────────────────────
        l1_input = build_l1_input_from_dict(l1_payload)
        l1_result = self.l1_evaluator.evaluate(l1_input)
        summary_status["L1"] = l1_result.status.value
        blocker_map["L1"] = list(l1_result.blocker_codes)
        warning_map["L1"] = list(l1_result.warning_codes)
        layer_results["L1"] = l1_result.to_dict()
        audit_steps.append("L1 evaluated")
        audit_steps.append(f"L1 continuation_allowed={l1_result.continuation_allowed}")

        if not l1_result.continuation_allowed:
            return _halt("L1", "L1 continuation disallowed")

        # ── L2 ────────────────────────────────────────────
        l2_rt, l3_rt = self._inject_upstream(l1_result, l2_payload, None, l3_payload)
        l2_input = build_l2_input_from_dict(l2_rt)
        l2_result = self.l2_evaluator.evaluate(l2_input)
        summary_status["L2"] = l2_result.status.value
        blocker_map["L2"] = list(l2_result.blocker_codes)
        warning_map["L2"] = list(l2_result.warning_codes)
        layer_results["L2"] = l2_result.to_dict()
        audit_steps.append("L2 evaluated")
        audit_steps.append(f"L2 continuation_allowed={l2_result.continuation_allowed}")

        if not l2_result.continuation_allowed:
            return _halt("L2", "L2 continuation disallowed")

        # ── L3 ────────────────────────────────────────────
        _, l3_rt = self._inject_upstream(l1_result, l2_payload, l2_result, l3_payload)
        l3_input = build_l3_input_from_dict(l3_rt)
        l3_result = self.l3_evaluator.evaluate(l3_input)
        summary_status["L3"] = l3_result.status.value
        blocker_map["L3"] = list(l3_result.blocker_codes)
        warning_map["L3"] = list(l3_result.warning_codes)
        layer_results["L3"] = l3_result.to_dict()
        audit_steps.append("L3 evaluated")
        audit_steps.append(f"L3 continuation_allowed={l3_result.continuation_allowed}")

        if not l3_result.continuation_allowed:
            return _halt("L3", "L3 continuation disallowed")

        # ── ALL PASS ──────────────────────────────────────
        chain_status = "PASS"
        if any(s == "WARN" for s in summary_status.values()):
            chain_status = "WARN"

        audit_steps.append("Phase 1 completed")
        return Phase1EvaluatorChainResult(
            phase="PHASE_1_FOUNDATION",
            phase_version=self.VERSION,
            input_ref=input_ref,
            timestamp=timestamp,
            halted=False,
            halted_at=None,
            continuation_allowed=True,
            next_legal_targets=["L4"],
            chain_status=chain_status,
            summary_status=summary_status,
            blocker_map=blocker_map,
            warning_map=warning_map,
            layer_results=layer_results,
            audit={"halt_safe": True, "steps": audit_steps, "reason": "Phase 1 completed legally"},
        )
