"""
Dashboard State Manager — account state, risk state, signal tracking.

Zone: dashboard/ — account/risk governor. No market direction computation.

Responsibilities:
- Hold current account state (balance, equity, margin, etc.)
- Hold active signals and their dashboard-level lifecycle state.
- Provide thread-safe snapshots for consumers (API, UI, risk guards).

Fixes applied:
- RWLock: multiple concurrent readers, exclusive writer.
- All attributes initialized in __init__ (no hasattr lazy init).
- snapshot() returns deep copy to prevent consumer mutation of internal state.
"""

from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from dashboard.rwlock import RWLock

logger = logging.getLogger(__name__)


@dataclass
class AccountState:
    """Immutable-style account state snapshot."""
    balance: float = 0.0
    equity: float = 0.0
    margin_used: float = 0.0
    margin_free: float = 0.0
    margin_level_pct: float | None = None
    open_positions: int = 0
    daily_pnl: float = 0.0
    daily_trades: int = 0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "balance": self.balance,
            "equity": self.equity,
            "margin_used": self.margin_used,
            "margin_free": self.margin_free,
            "margin_level_pct": self.margin_level_pct,
            "open_positions": self.open_positions,
            "daily_pnl": self.daily_pnl,
            "daily_trades": self.daily_trades,
            "updated_at": self.updated_at,
        }


@dataclass
class SignalState:
    """Dashboard-level signal tracking."""
    signal_id: str
    symbol: str
    verdict: str
    confidence: float
    status: str = "SIGNAL_CREATED"
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata.copy(),
        }


class StateManager:
    """
    Thread-safe dashboard state manager.

    Uses RWLock for concurrent read access under high tick rates.
    All attributes initialized in __init__ — no lazy init via hasattr.
    snapshot() returns deep copies to prevent consumer mutation.
    """

    def __init__(self) -> None:
        self._lock = RWLock()

        # Explicit initialization of ALL state — no hasattr lazy init
        self._account_state: AccountState = AccountState()
        self._signals: dict[str, SignalState] = {}
        self._risk_overrides: dict[str, Any] = {}
        self._last_heartbeat: float = 0.0
        self._metadata: dict[str, Any] = {}

    # ─── Account State ────────────────────────────────────────────

    def update_account_state(
        self,
        balance: float | None = None,
        equity: float | None = None,
        margin_used: float | None = None,
        margin_free: float | None = None,
        margin_level_pct: float | None = None,
        open_positions: int | None = None,
        daily_pnl: float | None = None,
        daily_trades: int | None = None,
    ) -> None:
        """
        Update account state fields. Only provided fields are updated.
        Writer-exclusive lock ensures no concurrent reads see partial updates.
        """
        now = time.time()

        with self._lock.write():
            if balance is not None:
                self._account_state.balance = balance
            if equity is not None:
                self._account_state.equity = equity
            if margin_used is not None:
                self._account_state.margin_used = margin_used
            if margin_free is not None:
                self._account_state.margin_free = margin_free
            if margin_level_pct is not None:
                self._account_state.margin_level_pct = margin_level_pct
            if open_positions is not None:
                self._account_state.open_positions = open_positions
            if daily_pnl is not None:
                self._account_state.daily_pnl = daily_pnl
            if daily_trades is not None:
                self._account_state.daily_trades = daily_trades
            self._account_state.updated_at = now

        logger.debug("Account state updated at %.3f", now)

    def get_account_state(self) -> AccountState:
        """
        Get a deep copy of the current account state.
        Multiple readers can call this concurrently without blocking each other.
        """
        with self._lock.read():
            return copy.deepcopy(self._account_state)

    # ─── Signal State ─────────────────────────────────────────────

    def register_signal(self, signal: SignalState) -> None:
        """Register a new signal from Layer-12 verdict."""
        now = time.time()
        with self._lock.write():
            signal.created_at = now
            signal.updated_at = now
            self._signals[signal.signal_id] = signal
        logger.info("Signal registered: %s (%s)", signal.signal_id, signal.symbol)

    def update_signal_status(self, signal_id: str, status: str) -> bool:
        """
        Update signal lifecycle status.
        Returns True if signal found and updated, False if not found.
        """
        now = time.time()
        with self._lock.write():
            signal = self._signals.get(signal_id)
            if signal is None:
                logger.warning("Signal not found for status update: %s", signal_id)
                return False
            signal.status = status
            signal.updated_at = now
        logger.info("Signal %s → %s", signal_id, status)
        return True

    def get_signal(self, signal_id: str) -> SignalState | None:
        """Get a deep copy of a specific signal."""
        with self._lock.read():
            signal = self._signals.get(signal_id)
            if signal is None:
                return None
            return copy.deepcopy(signal)

    def get_active_signals(self) -> list[SignalState]:
        """
        Get deep copies of all non-terminal signals.
        Safe for concurrent reads.
        """
        terminal = {"TRADE_CLOSED", "TRADE_ABORTED", "SIGNAL_EXPIRED", "PENDING_CANCELLED"}
        with self._lock.read():
            return [
                copy.deepcopy(s)
                for s in self._signals.values()
                if s.status not in terminal
            ]

    # ─── Risk Overrides ──────────────────────────────────────────

    def set_risk_override(self, key: str, value: Any) -> None:
        """Set a risk override (e.g., max_lot_override, trading_paused)."""
        with self._lock.write():
            self._risk_overrides[key] = value
        logger.info("Risk override set: %s = %s", key, value)

    def get_risk_overrides(self) -> dict[str, Any]:
        """Get deep copy of all risk overrides."""
        with self._lock.read():
            return copy.deepcopy(self._risk_overrides)

    # ─── Heartbeat ────────────────────────────────────────────────

    def heartbeat(self) -> None:
        """Record a heartbeat timestamp."""
        now = time.time()
        with self._lock.write():
            self._last_heartbeat = now

    def get_last_heartbeat(self) -> float:
        """Get last heartbeat timestamp."""
        with self._lock.read():
            return self._last_heartbeat

    # ─── Snapshot ─────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """
        Full state snapshot for API/UI consumers.

        Returns a DEEP COPY — consumers cannot mutate internal state.
        Multiple readers can call this concurrently.
        """
        with self._lock.read():
            return copy.deepcopy({
                "account": self._account_state.to_dict(),
                "signals": {
                    sid: s.to_dict() for sid, s in self._signals.items()
                },
                "risk_overrides": self._risk_overrides,
                "last_heartbeat": self._last_heartbeat,
                "metadata": self._metadata,
            })

    # ─── Reset (testing) ─────────────────────────────────────────

    def reset(self) -> None:
        """Reset all state. For testing only."""
        with self._lock.write():
            self._account_state = AccountState()
            self._signals.clear()
            self._risk_overrides.clear()
            self._last_heartbeat = 0.0
            self._metadata.clear()
