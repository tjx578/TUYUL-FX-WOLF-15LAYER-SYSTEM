"""
Execution Guard
Final safety layer before any execution.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock


@dataclass(frozen=True)
class ExecutionGateResult:
    allowed: bool
    code: str
    details: str = ""


class ExecutionGuard:
    """Execution-level gate for account-scoped and EA-scoped isolation."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = Lock()
        self._global_kill_enabled = False
        self._global_kill_reason = ""
        self._account_kill: dict[str, str] = {}
        self._ea_enabled: dict[tuple[str, str], bool] = {}
        self._news_lock_by_account: dict[str, bool] = {}
        self._max_concurrent_by_account: dict[str, int] = {}
        self._circuit_breaker_open: dict[str, bool] = {}
        self._pair_cooldown_by_account: dict[str, dict[str, str]] = {}

        self._prop_compliance_check: Callable[[str, str], bool] = lambda _signal_id, _account_id: True
        self._open_trades_provider: Callable[[str], int] = lambda _account_id: 0
        self._orchestrator_mode_provider: Callable[[], str] = lambda: "NORMAL"
        self._freshness_severity_provider: Callable[[str], str] = lambda _symbol: "UNKNOWN"
        self._blocked_freshness_severity: set[str] = {"HIGH", "CRITICAL"}

    def allow_execution(self, verdict: dict[str, object]) -> bool:
        if not verdict:
            return False

        if verdict.get("verdict") not in ("EXECUTE_BUY", "EXECUTE_SELL"):
            return False

        if verdict.get("execution_mode") != "TP1_ONLY":
            return False

        # Hard lock: no market execution
        return verdict.get("order_type", "PENDING_ONLY") == "PENDING_ONLY"

    def set_global_kill_switch(self, enabled: bool, reason: str = "") -> None:
        with self._lock:
            self._global_kill_enabled = enabled
            self._global_kill_reason = reason

    def set_account_kill_switch(self, account_id: str, enabled: bool, reason: str = "") -> None:
        with self._lock:
            if enabled:
                self._account_kill[account_id] = reason or "ACCOUNT_KILL_SWITCH"
            else:
                self._account_kill.pop(account_id, None)

    def set_ea_instance_enabled(self, account_id: str, ea_instance_id: str, enabled: bool) -> None:
        with self._lock:
            self._ea_enabled[(account_id, ea_instance_id)] = enabled

    def set_news_lock(self, account_id: str, enabled: bool) -> None:
        with self._lock:
            self._news_lock_by_account[account_id] = enabled

    def set_max_concurrent(self, account_id: str, max_open_trades: int) -> None:
        with self._lock:
            self._max_concurrent_by_account[account_id] = max(1, int(max_open_trades))

    def set_circuit_breaker(self, account_id: str, is_open: bool) -> None:
        with self._lock:
            self._circuit_breaker_open[account_id] = bool(is_open)

    def set_pair_cooldown(self, account_id: str, pair_cooldown: dict[str, str]) -> None:
        with self._lock:
            self._pair_cooldown_by_account[account_id] = {k.upper(): v for k, v in pair_cooldown.items()}

    def set_prop_compliance_checker(self, checker: Callable[[str, str], bool]) -> None:
        self._prop_compliance_check = checker

    def set_open_trades_provider(self, provider: Callable[[str], int]) -> None:
        self._open_trades_provider = provider

    def set_orchestrator_mode_provider(self, provider: Callable[[], str]) -> None:
        """Set a callback that returns the current orchestrator mode (NORMAL/SAFE/KILL_SWITCH)."""
        self._orchestrator_mode_provider = provider

    def set_freshness_severity_provider(self, provider: Callable[[str], str]) -> None:
        """Set callback returning feed freshness severity for a symbol."""
        self._freshness_severity_provider = provider

    def set_blocked_freshness_severity(self, severities: set[str]) -> None:
        """Configure freshness severities that must block execution."""
        self._blocked_freshness_severity = {str(item).upper() for item in severities}

    def validate_scope(
        self,
        *,
        account_id: str,
        ea_instance_id: str | None = None,
    ) -> ExecutionGateResult:
        if not account_id or not account_id.strip():
            return ExecutionGateResult(False, "ACCOUNT_ID_REQUIRED", "Explicit account_id is mandatory")

        # Check orchestrator mode before account-level gates
        orchestrator_mode = self._orchestrator_mode_provider()
        if orchestrator_mode == "KILL_SWITCH":
            return ExecutionGateResult(False, "ORCHESTRATOR_KILL_SWITCH", "Orchestrator in KILL_SWITCH mode")
        if orchestrator_mode == "SAFE":
            return ExecutionGateResult(False, "ORCHESTRATOR_SAFE_MODE", "Orchestrator in SAFE mode — new execution blocked")

        with self._lock:
            if self._global_kill_enabled:
                return ExecutionGateResult(False, "GLOBAL_KILL_SWITCH", self._global_kill_reason)

            if account_id in self._account_kill:
                return ExecutionGateResult(False, "ACCOUNT_KILL_SWITCH", self._account_kill[account_id])

            if ea_instance_id:
                enabled = self._ea_enabled.get((account_id, ea_instance_id), True)
                if not enabled:
                    return ExecutionGateResult(False, "EA_INSTANCE_STOPPED", ea_instance_id)

        return ExecutionGateResult(True, "ALLOW", "")

    def execute(
        self,
        signal_id: str,
        account_id: str,
        *,
        symbol: str | None = None,
    ) -> ExecutionGateResult:
        """Validate per-account execution permission for one signal.

        Mandatory entrypoint for account-scoped execution checks.
        """
        base_gate = self.validate_scope(account_id=account_id)
        if not base_gate.allowed:
            return base_gate

        if not signal_id or not signal_id.strip():
            return ExecutionGateResult(False, "SIGNAL_ID_REQUIRED", "Explicit signal_id is mandatory")

        with self._lock:
            if self._news_lock_by_account.get(account_id, False):
                return ExecutionGateResult(False, "NEWS_LOCK", "news lock active")

            if self._circuit_breaker_open.get(account_id, False):
                return ExecutionGateResult(False, "CIRCUIT_BREAKER", "circuit breaker open")

            if symbol:
                until_map = self._pair_cooldown_by_account.get(account_id, {})
                raw_until = until_map.get(symbol.upper())
                if raw_until:
                    try:
                        until = datetime.fromisoformat(raw_until.replace("Z", "+00:00"))
                        if until > datetime.now(UTC):
                            return ExecutionGateResult(False, "PAIR_COOLDOWN", f"{symbol} until {raw_until}")
                    except ValueError:
                        pass

            max_open = self._max_concurrent_by_account.get(account_id)
            if max_open is not None:
                open_trades = self._open_trades_provider(account_id)
                if open_trades >= max_open:
                    return ExecutionGateResult(False, "MAX_CONCURRENT_TRADES", f"{open_trades}/{max_open}")

        if symbol:
            freshness_severity = str(self._freshness_severity_provider(symbol)).upper()
            if freshness_severity in self._blocked_freshness_severity:
                return ExecutionGateResult(
                    False,
                    "FEED_FRESHNESS_BLOCK",
                    f"{symbol} freshness severity={freshness_severity}",
                )

        if not self._prop_compliance_check(signal_id, account_id):
            return ExecutionGateResult(False, "PROP_COMPLIANCE", "prop guard rejected")

        return ExecutionGateResult(True, "ALLOW", "")


# Placeholder
