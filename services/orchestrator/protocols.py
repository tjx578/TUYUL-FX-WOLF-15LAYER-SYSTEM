"""
Orchestrator Protocols — ARCH-GAP-09
======================================
Protocol-based abstractions for the orchestrator coordinator.

The coordinator depends on these Protocols instead of concrete types from
``execution.*`` and ``risk.*``. This decouples the orchestrator service from
the execution and risk packages, enabling independent deployment and testing.

Concrete implementations (TakeSignalService, RiskFirewall) satisfy these
Protocols via structural subtyping — no base-class inheritance required.

Zone: orchestrator — boundary contracts, no market logic.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# ── Status / Verdict string constants ─────────────────────────────────────
# Mirror the subset of TakeSignalStatus and FirewallVerdict values the
# coordinator actually uses.  Using plain strings avoids importing the
# concrete StrEnum types from execution/risk packages.

STATUS_PENDING = "PENDING"
STATUS_FIREWALL_APPROVED = "FIREWALL_APPROVED"
STATUS_FIREWALL_REJECTED = "FIREWALL_REJECTED"
STATUS_EXECUTION_SENT = "EXECUTION_SENT"
STATUS_REJECTED = "REJECTED"

VERDICT_REJECTED = "REJECTED"


# ── Protocol: TakeSignalResponse ──────────────────────────────────────────

@runtime_checkable
class TakeSignalResponseLike(Protocol):
    """Minimal read interface the coordinator needs from a take-signal record."""

    @property
    def status(self) -> str: ...

    @property
    def signal_id(self) -> str: ...

    @property
    def account_id(self) -> str: ...


# ── Protocol: TakeSignalService ───────────────────────────────────────────

@runtime_checkable
class TakeSignalServiceLike(Protocol):
    """Async service for retrieving and transitioning take-signal records."""

    async def get(self, take_id: str) -> TakeSignalResponseLike | None: ...

    async def transition(
        self,
        take_id: str,
        new_status: str,
        *,
        reason: str | None = None,
        firewall_result_id: str | None = None,
        execution_intent_id: str | None = None,
    ) -> Any: ...


# ── Protocol: FirewallResult ──────────────────────────────────────────────

@runtime_checkable
class FirewallResultLike(Protocol):
    """Minimal read interface the coordinator needs from a firewall result."""

    @property
    def verdict(self) -> str: ...

    @property
    def firewall_id(self) -> str: ...

    @property
    def short_circuited_at(self) -> str | None: ...


# ── Protocol: RiskFirewall ────────────────────────────────────────────────

@runtime_checkable
class RiskFirewallLike(Protocol):
    """Async firewall evaluator for take-signal gating."""

    async def evaluate(
        self,
        take_id: str,
        signal: dict[str, Any],
        account_state: dict[str, Any],
    ) -> FirewallResultLike: ...
