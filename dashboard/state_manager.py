"""
dashboard/state_manager.py — Centralised dashboard state

Manages account state, active signals, risk overrides, and heartbeat
using a reader/writer lock for thread safety.

Authority: Dashboard-layer governor. No market decisions.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any

from dashboard.rwlock import RWLock

# ── Terminal signal states (excluded from active_signals) ────────────
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        "TRADE_CLOSED",
        "SIGNAL_EXPIRED",
        "PENDING_CANCELLED",
        "TRADE_ABORTED",
    }
)


@dataclass
class AccountState:
    """Current account state snapshot."""

    balance: float = 0.0
    equity: float = 0.0
    open_positions: int = 0
    updated_at: float = 0.0


@dataclass
class SignalState:
    """State for a single L12 signal through its lifecycle."""

    signal_id: str = ""
    symbol: str = ""
    verdict: str = ""
    confidence: float = 0.0
    status: str = "SIGNAL_CREATED"
    metadata: dict[str, Any] = field(default_factory=lambda: {})


class StateManager:
    """Thread-safe centralised dashboard state manager.

    Attributes follow copilot-instructions dashboard state machine:
        SIGNAL_CREATED -> PENDING_PLACED -> TRADE_OPEN -> TRADE_CLOSED
    """

    def __init__(self) -> None:
        super().__init__()
        self._account_state: AccountState = AccountState()
        self._signals: dict[str, SignalState] = {}
        self._risk_overrides: dict[str, Any] = {}
        self._last_heartbeat: float = 0.0
        self._metadata: dict[str, Any] = {}
        self._lock: RWLock = RWLock()

    # ── Account state ─────────────────────────────────────────────

    def get_account_state(self) -> AccountState:
        """Return a deep copy of current account state."""
        with self._lock.read():
            return copy.deepcopy(self._account_state)

    def update_account_state(
        self,
        balance: float | None = None,
        equity: float | None = None,
        open_positions: int | None = None,
    ) -> None:
        """Partially update account state."""
        with self._lock.write():
            if balance is not None:
                self._account_state.balance = balance
            if equity is not None:
                self._account_state.equity = equity
            if open_positions is not None:
                self._account_state.open_positions = open_positions
            self._account_state.updated_at = time.time()

    # ── Signals ───────────────────────────────────────────────────

    def register_signal(self, signal: SignalState) -> None:
        """Register a new signal (sets status to SIGNAL_CREATED if not set)."""
        sig_copy = copy.deepcopy(signal)
        if sig_copy.status == "":
            sig_copy.status = "SIGNAL_CREATED"
        with self._lock.write():
            self._signals[sig_copy.signal_id] = sig_copy

    def get_signal(self, signal_id: str) -> SignalState | None:
        """Return a deep copy of a signal by ID, or None."""
        with self._lock.read():
            sig = self._signals.get(signal_id)
            return copy.deepcopy(sig) if sig is not None else None

    def update_signal_status(self, signal_id: str, status: str) -> bool:
        """Update the lifecycle status of a signal. Returns False if not found."""
        with self._lock.write():
            sig = self._signals.get(signal_id)
            if sig is None:
                return False
            sig.status = status
            return True

    def get_active_signals(self) -> list[SignalState]:
        """Return deep copies of all non-terminal signals."""
        with self._lock.read():
            return [copy.deepcopy(s) for s in self._signals.values() if s.status not in _TERMINAL_STATUSES]

    # ── Risk overrides ────────────────────────────────────────────

    def set_risk_override(self, key: str, value: Any) -> None:
        """Set a risk override key/value."""
        with self._lock.write():
            self._risk_overrides[key] = value

    def get_risk_overrides(self) -> dict[str, Any]:
        """Return a deep copy of current risk overrides."""
        with self._lock.read():
            return copy.deepcopy(self._risk_overrides)

    # ── Heartbeat ─────────────────────────────────────────────────

    def heartbeat(self) -> None:
        """Update last heartbeat timestamp."""
        with self._lock.write():
            self._last_heartbeat = time.time()

    def get_last_heartbeat(self) -> float:
        """Return last heartbeat timestamp."""
        with self._lock.read():
            return self._last_heartbeat

    # ── Snapshot ──────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Return a deep-copy snapshot of the full dashboard state."""
        with self._lock.read():
            acc = copy.deepcopy(self._account_state)
            signals = {k: copy.deepcopy(v) for k, v in self._signals.items()}
            overrides = copy.deepcopy(self._risk_overrides)
            heartbeat = self._last_heartbeat

        return {
            "account": {
                "balance": acc.balance,
                "equity": acc.equity,
                "open_positions": acc.open_positions,
                "updated_at": acc.updated_at,
            },
            "signals": {k: vars(v) for k, v in signals.items()},
            "risk_overrides": overrides,
            "last_heartbeat": heartbeat,
        }

    # ── Reset ─────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset all state to defaults."""
        with self._lock.write():
            self._account_state = AccountState()
            self._signals = {}
            self._risk_overrides = {}
            self._last_heartbeat = 0.0
            self._metadata = {}
