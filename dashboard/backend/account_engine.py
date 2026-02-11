"""
Account Engine - Thread-Safe Account State Manager

Manages account state tracking with thread-safe operations.
Each account has its own singleton instance.

Responsibilities:
    - Track balance, equity, drawdown
    - Track open trades and risk
    - Compute risk severity state
    - Thread-safe updates
"""

from threading import Lock

from loguru import logger

from dashboard.backend.schemas import AccountState, RiskSeverity


class AccountEngine:
    """
    Thread-safe account state manager.

    One instance per account_id (singleton pattern per account).
    """

    # Class-level instance cache
    _instances: dict[str, "AccountEngine"] = {}
    _instances_lock = Lock()

    def __init__(
        self,
        account_id: str,
        balance: float,
        equity: float,
        prop_firm_code: str,
    ):
        """
        Initialize account engine (use get_or_create instead).

        Args:
            account_id: Account identifier
            balance: Initial balance
            equity: Initial equity
            prop_firm_code: Prop firm profile code
        """
        self.account_id = account_id
        self.prop_firm_code = prop_firm_code

        # Account state
        self._balance = balance
        self._equity = equity
        self._equity_high = equity
        self._open_trades = 0
        self._open_risk_amount = 0.0
        self._daily_starting_equity = equity

        # Thread safety
        self._lock = Lock()

        logger.info(
            f"AccountEngine initialized: {account_id} | "
            f"Balance={balance} | PropFirm={prop_firm_code}"
        )

    @classmethod
    def get_or_create(
        cls,
        account_id: str,
        balance: float,
        equity: float,
        prop_firm_code: str,
    ) -> "AccountEngine":
        """
        Factory method: get existing or create new account engine.

        Args:
            account_id: Account identifier
            balance: Account balance
            equity: Account equity
            prop_firm_code: Prop firm code

        Returns:
            AccountEngine instance
        """
        with cls._instances_lock:
            if account_id not in cls._instances:
                cls._instances[account_id] = cls(account_id, balance, equity, prop_firm_code)
            return cls._instances[account_id]

    def update_balance(self, balance: float, equity: float) -> None:
        """
        Update account balance and equity.

        Args:
            balance: New balance
            equity: New equity
        """
        with self._lock:
            self._balance = balance
            self._equity = equity

            # Update equity high watermark
            self._equity_high = max(self._equity_high, equity)

            logger.debug(
                f"Balance updated: {self.account_id} | Balance={balance} | Equity={equity}"
            )

    def record_trade_open(self, risk_amount: float) -> None:
        """
        Record a trade opening (increment counters).

        Args:
            risk_amount: Amount at risk in USD
        """
        with self._lock:
            self._open_trades += 1
            self._open_risk_amount += risk_amount

            logger.info(
                f"Trade opened: {self.account_id} | "
                f"OpenTrades={self._open_trades} | "
                f"OpenRisk=${self._open_risk_amount:.2f}"
            )

    def record_trade_close(self, pnl: float, risk_amount: float) -> None:
        """
        Record a trade closure (update equity, DD, decrement counters).

        Args:
            pnl: Profit/loss amount in USD
            risk_amount: Amount that was at risk in USD
        """
        with self._lock:
            # Update equity
            self._equity += pnl

            # Update equity high if new high
            self._equity_high = max(self._equity_high, self._equity)

            # Decrement counters
            self._open_trades = max(0, self._open_trades - 1)
            self._open_risk_amount = max(0.0, self._open_risk_amount - risk_amount)

            logger.info(
                f"Trade closed: {self.account_id} | "
                f"PnL=${pnl:.2f} | Equity=${self._equity:.2f} | "
                f"OpenTrades={self._open_trades}"
            )

    def reset_daily_dd(self) -> None:
        """Reset daily drawdown tracking (call at start of trading day)."""
        with self._lock:
            self._daily_starting_equity = self._equity
            logger.info(f"Daily DD reset: {self.account_id} | StartEquity=${self._equity:.2f}")

    def get_state(self) -> AccountState:
        """
        Get immutable snapshot of current account state.

        Returns:
            AccountState with computed DD percentages and risk state
        """
        with self._lock:
            # Calculate daily DD
            if self._daily_starting_equity > 0:
                daily_dd_amount = max(0, self._daily_starting_equity - self._equity)
                daily_dd_percent = daily_dd_amount / self._daily_starting_equity * 100
            else:
                daily_dd_percent = 0.0

            # Calculate total DD from equity high
            if self._equity_high > 0:
                total_dd_amount = max(0, self._equity_high - self._equity)
                total_dd_percent = total_dd_amount / self._equity_high * 100
            else:
                total_dd_percent = 0.0

            # Calculate open risk percent
            if self._balance > 0:
                open_risk_percent = self._open_risk_amount / self._balance * 100
            else:
                open_risk_percent = 0.0

            # Determine risk state
            risk_state = self._compute_risk_state(daily_dd_percent, total_dd_percent)

            return AccountState(
                account_id=self.account_id,
                balance=self._balance,
                equity=self._equity,
                equity_high=self._equity_high,
                daily_dd_percent=daily_dd_percent,
                total_dd_percent=total_dd_percent,
                open_risk_percent=open_risk_percent,
                open_trades=self._open_trades,
                risk_state=risk_state,
            )

    def _compute_risk_state(self, daily_dd: float, total_dd: float) -> RiskSeverity:
        """
        Compute risk severity state based on drawdown levels.

        Args:
            daily_dd: Daily drawdown percent
            total_dd: Total drawdown percent

        Returns:
            RiskSeverity (SAFE/WARNING/CRITICAL)
        """
        # Critical thresholds (conservative defaults)
        daily_critical = 4.0  # 4% daily DD
        total_critical = 8.0  # 8% total DD

        # Warning thresholds (80% of critical)
        daily_warning = daily_critical * 0.8
        total_warning = total_critical * 0.8

        if daily_dd >= daily_critical or total_dd >= total_critical:
            return RiskSeverity.CRITICAL
        if daily_dd >= daily_warning or total_dd >= total_warning:
            return RiskSeverity.WARNING
        return RiskSeverity.SAFE
