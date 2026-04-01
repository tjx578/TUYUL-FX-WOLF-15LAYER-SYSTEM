"""
Phase 1 Chain Adapter — Strict Sequential Halt-on-Failure
=========================================================

Enforces the Phase 1 canonical pipeline semantics:
    L1 → L2 → L3 (strict sequential, halt-on-failure)

Each layer's constitutional governor is evaluated before proceeding
to the next layer. If any layer produces `continuation_allowed == false`,
the chain halts and returns a ChainResult with the failure details.

Authority boundary:
  This adapter orchestrates Phase 1 only. It does not emit direction,
  verdict, or execution authority. It connects constitutional governors
  to enforce halt-on-failure semantics that the parallel DAG batch
  runner cannot enforce.

Zone: constitution/ — pipeline governance, no execution side-effects.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# §1  CHAIN RESULT
# ═══════════════════════════════════════════════════════════════════════════


class ChainStatus(str, Enum):
    """Phase 1 chain execution status."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class ChainResult:
    """Result of the Phase 1 chain execution."""

    status: ChainStatus
    continuation_allowed: bool
    halted_at: str | None = None  # Layer ID where chain halted (None = completed)
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
            "continuation_allowed": self.continuation_allowed,
            "halted_at": self.halted_at,
            "l1": self.l1,
            "l2": self.l2,
            "l3": self.l3,
            "errors": self.errors,
            "warnings": self.warnings,
            "timing_ms": self.timing_ms,
        }


# ═══════════════════════════════════════════════════════════════════════════
# §2  PHASE 1 CHAIN ADAPTER
# ═══════════════════════════════════════════════════════════════════════════


class Phase1ChainAdapter:
    """Strict sequential halt-on-failure chain for Phase 1 (L1 → L2 → L3).

    Usage::

        adapter = Phase1ChainAdapter(
            l1_callable=lambda sym: l1.analyze(sym),
            l2_callable=lambda sym: l2.analyze(sym),
            l3_callable=lambda sym, l2_out: l3.analyze(sym),
        )
        result = adapter.execute("EURUSD")

    The adapter:
    1. Runs L1, checks continuation_allowed
    2. If L1 passes, runs L2, checks continuation_allowed
    3. If L2 passes, injects L2 output into L3, runs L3, checks continuation_allowed
    4. Returns ChainResult with all layer outputs and halt details
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

        Returns ChainResult with layer outputs and halt details.
        """
        timing: dict[str, float] = {}
        errors: list[str] = []
        warnings: list[str] = []
        worst_status = ChainStatus.PASS

        # ── Step 1: L1 ───────────────────────────────────────
        l1_start = time.monotonic()
        try:
            l1 = self._l1(symbol)
        except Exception as exc:
            logger.error("[Phase1] L1 raised: %s: %s", type(exc).__name__, exc, exc_info=True)
            errors.append(f"L1_EXCEPTION:{type(exc).__name__}")
            return ChainResult(
                status=ChainStatus.FAIL,
                continuation_allowed=False,
                halted_at="L1",
                errors=errors,
                timing_ms=timing,
            )
        timing["L1"] = (time.monotonic() - l1_start) * 1000

        l1_continue = l1.get("continuation_allowed", l1.get("valid", False))
        l1_status = l1.get("status", "PASS" if l1_continue else "FAIL")
        l1_blockers = l1.get("blocker_codes", [])
        l1_warnings = l1.get("warning_codes", [])

        if l1_status == "WARN":
            worst_status = ChainStatus.WARN
            warnings.extend(f"L1:{w}" for w in l1_warnings)

        if not l1_continue:
            errors.append(f"L1_HALT:status={l1_status}")
            errors.extend(f"L1_BLOCKER:{b}" for b in l1_blockers)
            logger.warning(
                "[Phase1] L1 HALT | symbol=%s status=%s blockers=%s",
                symbol, l1_status, l1_blockers,
            )
            return ChainResult(
                status=ChainStatus.FAIL,
                continuation_allowed=False,
                halted_at="L1",
                l1=l1,
                errors=errors,
                warnings=warnings,
                timing_ms=timing,
            )

        # ── Step 2: L2 ───────────────────────────────────────
        l2_start = time.monotonic()
        try:
            l2 = self._l2(symbol)
        except Exception as exc:
            logger.error("[Phase1] L2 raised: %s: %s", type(exc).__name__, exc, exc_info=True)
            errors.append(f"L2_EXCEPTION:{type(exc).__name__}")
            return ChainResult(
                status=ChainStatus.FAIL,
                continuation_allowed=False,
                halted_at="L2",
                l1=l1,
                errors=errors,
                timing_ms=timing,
            )
        timing["L2"] = (time.monotonic() - l2_start) * 1000

        l2_continue = l2.get("continuation_allowed", l2.get("valid", False))
        l2_status = l2.get("status", "PASS" if l2_continue else "FAIL")
        l2_blockers = l2.get("blocker_codes", [])
        l2_warnings = l2.get("warning_codes", [])

        if l2_status == "WARN" and worst_status == ChainStatus.PASS:
            worst_status = ChainStatus.WARN
            warnings.extend(f"L2:{w}" for w in l2_warnings)

        if not l2_continue:
            errors.append(f"L2_HALT:status={l2_status}")
            errors.extend(f"L2_BLOCKER:{b}" for b in l2_blockers)
            logger.warning(
                "[Phase1] L2 HALT | symbol=%s status=%s blockers=%s",
                symbol, l2_status, l2_blockers,
            )
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

        # ── Step 3: L3 (with L2 injection) ───────────────────
        if self._l3_l2_injector is not None:
            self._l3_l2_injector(l2)

        l3_start = time.monotonic()
        try:
            l3 = self._l3(symbol)
        except Exception as exc:
            logger.error("[Phase1] L3 raised: %s: %s", type(exc).__name__, exc, exc_info=True)
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
        timing["L3"] = (time.monotonic() - l3_start) * 1000

        l3_continue = l3.get("continuation_allowed", l3.get("valid", False))
        l3_status = l3.get("status", "PASS" if l3_continue else "FAIL")
        l3_blockers = l3.get("blocker_codes", [])
        l3_warnings = l3.get("warning_codes", [])

        if l3_status == "WARN" and worst_status == ChainStatus.PASS:
            worst_status = ChainStatus.WARN
            warnings.extend(f"L3:{w}" for w in l3_warnings)

        if not l3_continue:
            errors.append(f"L3_HALT:status={l3_status}")
            errors.extend(f"L3_BLOCKER:{b}" for b in l3_blockers)
            logger.warning(
                "[Phase1] L3 HALT | symbol=%s status=%s blockers=%s",
                symbol, l3_status, l3_blockers,
            )
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

        # ── All three layers passed ──────────────────────────
        logger.info(
            "[Phase1] PASS | symbol=%s chain_status=%s L1=%s L2=%s L3=%s "
            "timing_ms=L1:%.1f/L2:%.1f/L3:%.1f",
            symbol,
            worst_status.value,
            l1_status,
            l2_status,
            l3_status,
            timing.get("L1", 0),
            timing.get("L2", 0),
            timing.get("L3", 0),
        )

        return ChainResult(
            status=worst_status,
            continuation_allowed=True,
            halted_at=None,
            l1=l1,
            l2=l2,
            l3=l3,
            errors=errors,
            warnings=warnings,
            timing_ms=timing,
        )
