"""
Prop Firm Rule Validator

Validates trading decisions against prop firm rules.
Integrates with circuit breaker and drawdown monitoring
for real-time compliance checks.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def load_prop_firm() -> dict[str, Any]:
    """Load prop firm configuration from YAML or return defaults.

    Looks for ``config/prop_firm.yaml`` relative to the repository root
    (two levels up from this file).  Falls back to sensible defaults so
    the module is usable even without the config file.
    """
    config_path = Path(__file__).resolve().parent.parent / "config" / "prop_firm.yaml"

    if config_path.exists():
        try:
            import yaml  # type: ignore[import-untyped]

            with open(config_path, "r") as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict):
                return data
        except Exception:  # noqa: BLE001
            pass  # fall through to defaults

    # Sensible defaults so the guard is always functional
    return {
        "allowed_markets": {
            "forex": True,
            "commodities": True,
            "indices": True,
            "crypto": False,
        },
        "risk": {
            "max_risk_per_trade_percent": 0.01,
            "min_rr_required": 2.0,
            "max_daily_loss": 500.0,
            "max_open_positions": 5,
            "max_lot_per_trade": 1.0,
        },
    }


@dataclass
class AccountState:
    """Typed account state for validation."""
    balance: float
    equity: float
    daily_loss: float
    open_positions: list[dict]

    @classmethod
    def from_dict(cls, data: dict) -> AccountState:
        """Safe constructor with validation."""
        try:
            return cls(
                balance=float(data.get("balance", 0.0)),
                equity=float(data.get("equity", 0.0)),
                daily_loss=float(data.get("daily_loss", 0.0)),
                open_positions=data.get("open_positions", []),
            )
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid account state: {e}")  # noqa: B904


@dataclass
class TradeRisk:
    """Typed trade risk for validation."""
    category: str
    risk_percent: float
    rr_ratio: float
    lot_size: float
    risk_amount: float | None = None
    symbol: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> TradeRisk:
        """Safe constructor with validation."""
        try:
            return cls(
                category=str(data.get("category", "unknown")),
                risk_percent=float(data.get("risk_percent", 0.0)),
                rr_ratio=float(data.get("rr_ratio", 0.0)),
                lot_size=float(data.get("lot_size", 0.0)),
                risk_amount=float(data["risk_amount"]) if "risk_amount" in data else None,
                symbol=data.get("symbol"),
            )
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid trade risk: {e}")  # noqa: B904


@dataclass
class GuardResult:
    """Standard result from a prop-firm guard check."""
    allowed: bool
    code: str
    severity: str  # "info" | "warning" | "block"
    details: dict[str, Any] | None = None


class BasePropFirmGuard(ABC):
    """
    Base class for prop-firm risk guards.

    Interface contract (from copilot-instructions):
        check(account_state: dict, trade_risk: dict) -> {allowed, code, severity, details?}

    Dashboard must treat guard result as binding for risk legality
    (but still not a market decision).
    """

    @abstractmethod
    def check(self, account_state: dict[str, Any], trade_risk: dict[str, Any]) -> GuardResult:
        """Evaluate whether a trade is allowed under this prop-firm's rules.

        Parameters
        ----------
        account_state : dict
            Current account metrics (balance, equity, daily-dd, etc.).
        trade_risk : dict
            Proposed trade risk details (lot_size, risk_amount, symbol, etc.).

        Returns
        -------
        GuardResult
            Binding decision with code and severity.
        """


class PropFirmRules:
    """
    Prop firm rule validator.

    Validates:
    - Allowed market categories
    - Max risk per trade
    - Minimum RR ratio

    Can be integrated with RiskManager for full compliance checks
    including circuit breaker state and drawdown limits.

    Attributes
    ----------
    cfg : dict
        Prop firm configuration from config/prop_firm.yaml
    """

    def __init__(self) -> None:
        """Initialize PropFirmRules with config."""
        self.cfg: dict[str, Any] = load_prop_firm()
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate that required config keys exist."""
        required_keys = ["allowed_markets", "risk"]
        for key in required_keys:
            if key not in self.cfg:
                raise ValueError(f"Missing required config key: {key}")

        risk_keys = [
            "max_risk_per_trade_percent",
            "min_rr_required",
            "max_daily_loss",
            "max_open_positions",
            "max_lot_per_trade",
        ]
        for key in risk_keys:
            if key not in self.cfg["risk"]:
                raise ValueError(f"Missing required risk config key: {key}")

    def is_market_allowed(self, category: str) -> bool:
        """
        Check if market category is allowed.

        Parameters
        ----------
        category : str
            Market category (e.g., "forex", "crypto", "commodities")

        Returns
        -------
        bool
            True if allowed
        """
        if not category or not isinstance(category, str):
            return False
        return bool(self.cfg["allowed_markets"].get(category, False))

    def max_risk_allowed(self) -> float:
        """
        Get maximum risk % allowed per trade.

        Returns
        -------
        float
            Max risk as decimal (e.g., 0.01 = 1%)
        """
        return float(self.cfg["risk"]["max_risk_per_trade_percent"])

    def min_rr_required(self) -> float:
        """
        Get minimum risk/reward ratio required.

        Returns
        -------
        float
            Minimum RR ratio (e.g., 2.0)
        """
        return float(self.cfg["risk"]["min_rr_required"])

    @property
    def max_daily_loss(self) -> float:
        """Maximum daily loss allowed (in account currency)."""
        return float(self.cfg["risk"]["max_daily_loss"])

    @max_daily_loss.setter
    def max_daily_loss(self, value: float) -> None:
        """Set maximum daily loss (for testing/override only)."""
        self.cfg["risk"]["max_daily_loss"] = float(value)

    @property
    def max_open_positions(self) -> int:
        """Maximum number of open positions allowed."""
        return int(self.cfg["risk"]["max_open_positions"])

    @max_open_positions.setter
    def max_open_positions(self, value: int) -> None:
        """Set maximum open positions (for testing/override only)."""
        self.cfg["risk"]["max_open_positions"] = int(value)

    @property
    def max_lot_per_trade(self) -> float:
        """Maximum lot size per trade."""
        return float(self.cfg["risk"]["max_lot_per_trade"])

    @max_lot_per_trade.setter
    def max_lot_per_trade(self, value: float) -> None:
        """Set maximum lot per trade (for testing/override only)."""
        self.cfg["risk"]["max_lot_per_trade"] = float(value)

    def validate_trade(
        self,
        category: str,
        risk_percent: float,
        rr_ratio: float,
    ) -> dict:
        """
        Validate a trade against all prop firm rules.

        Parameters
        ----------
        category : str
            Market category
        risk_percent : float
            Risk % for this trade
        rr_ratio : float
            Risk/reward ratio

        Returns
        -------
        dict
            Validation result with:
            - compliant: bool
            - violations: list of violation messages
        """
        violations = []

        # Check market allowed
        if not self.is_market_allowed(category):
            violations.append(
                f"Market category '{category}' not allowed by prop firm"
            )

        # Check risk limit
        max_risk = self.max_risk_allowed()
        if risk_percent > max_risk:
            violations.append(
                f"Risk {risk_percent*100:.2f}% exceeds max "
                f"{max_risk*100:.2f}%"
            )

        # Check RR requirement
        min_rr = self.min_rr_required()
        if rr_ratio < min_rr:
            violations.append(
                f"RR {rr_ratio:.2f} below minimum {min_rr:.2f}"
            )

        return {
            "compliant": len(violations) == 0,
            "violations": violations,
        }

    def calculate_safe_lot(
        self,
        account_balance: float,
        risk_percent: float,
        stop_loss_pips: float,
        pip_value: float = 10.0,  # Default for standard lot on major pairs
    ) -> float:
        """
        Calculate maximum safe lot size based on risk parameters.

        Parameters
        ----------
        account_balance : float
            Current account balance
        risk_percent : float
            Risk percent (as decimal, e.g., 0.01 for 1%)
        stop_loss_pips : float
            Stop loss distance in pips
        pip_value : float
            Value per pip for 1 standard lot (default: $10 for majors)

        Returns
        -------
        float
            Maximum safe lot size
        """
        if account_balance <= 0 or stop_loss_pips <= 0 or pip_value <= 0:
            return 0.0

        # Clamp risk to max allowed
        max_risk = self.max_risk_allowed()
        clamped_risk = min(risk_percent, max_risk)

        # Calculate risk amount
        risk_amount = account_balance * clamped_risk

        # Calculate lot size
        lot_size = risk_amount / (stop_loss_pips * pip_value)

        # Clamp to max lot per trade
        return min(lot_size, self.max_lot_per_trade)

    def check(self, account_state: dict, trade_risk: dict) -> dict:
        """
        Check trade against prop firm rules.

        Constitutional authority: This is a RISK LEGALITY check, NOT a market decision.
        Dashboard must treat result as binding for account/position limits.

        Parameters
        ----------
        account_state : dict
            Must contain: balance, equity, daily_loss, open_positions
        trade_risk : dict
            Must contain: category, risk_percent, rr_ratio, lot_size

        Returns
        -------
        dict
            {
                allowed: bool,
                code: str,
                severity: str,
                details: str,
                max_safe_lot: float,
                recommended_lot: float,
                violations: list
            }
        """
        try:
            # Validate inputs
            AccountState.from_dict(account_state)
            t_risk = TradeRisk.from_dict(trade_risk)
        except ValueError as e:
            return GuardResult(
                allowed=False,
                code="INVALID_INPUT",
                severity="ERROR",
                details=f"Input validation failed: {e}",
                max_safe_lot=0.0,
                recommended_lot=0.0,
            ).to_dict()

        violations = []

        # Validate trade against rules
        trade_result = self.validate_trade(
            t_risk.category,
            t_risk.risk_percent,
            t_risk.rr_ratio,
        )

        violations.extend(trade_result["violations"])

        # Calculate safe lot size
        # Note: This requires stop_loss info which may not be in trade_risk yet
        # For now, use the requested lot and clamp to max
        max_safe_lot = min(t_risk.lot_size, self.max_lot_per_trade)
        recommended_lot = max_safe_lot if trade_result["compliant"] else 0.0

        if trade_result["compliant"]:
            return GuardResult(
                allowed=True,
                code="TRADE_ALLOWED",
                severity="INFO",
                details="Trade compliant with prop firm rules",
                max_safe_lot=max_safe_lot,
                recommended_lot=recommended_lot,
                violations=[],
            ).to_dict()
        else:
            return GuardResult(
                allowed=False,
                code="RISK_EXCEEDED",
                severity="ERROR",
                details="; ".join(violations),
                max_safe_lot=max_safe_lot,
                recommended_lot=0.0,
                violations=violations,
            ).to_dict()


class PropFirmGuard:
    """
    Risk authority for prop firm compliance.

    Constitutional constraint: ALWAYS checked before execution,
    regardless of signal strength or confidence.

    This is a GOVERNANCE layer, NOT a market decision layer.
    """

    def __init__(self):
        """Initialize PropFirmGuard with prop firm rules."""
        self.profile = PropFirmRules()

    def check(
        self,
        account_state: dict,
        trade_risk: dict,
        signal_verdict: str | None = None,  # For audit only
    ) -> dict:
        """
        Validate trade against prop firm rules.

        Constitutional principle: Even EXECUTE verdicts must pass prop firm checks.
        Signal confidence does NOT override risk rules.

        Args:
            account_state: {balance, equity, open_positions, daily_loss, ...}
            trade_risk: {lot_size, risk_amount, symbol, category, risk_percent, rr_ratio, ...}
            signal_verdict: L12 verdict (for audit only, NOT a bypass key)

        Returns:
            {
                "allowed": bool,
                "code": str,
                "severity": "ERROR" | "WARNING" | "INFO",
                "details": str | None,
                "max_safe_lot": float,
                "recommended_lot": float,
            }
        """
        try:
            # Validate inputs using typed models
            acc_state = AccountState.from_dict(account_state)
            t_risk = TradeRisk.from_dict(trade_risk)
        except ValueError as e:
            return GuardResult(
                allowed=False,
                code="INVALID_INPUT",
                severity="ERROR",
                details=f"Input validation failed: {e}",
            ).to_dict()

        # Check 1: Daily loss limit
        if acc_state.daily_loss >= self.profile.max_daily_loss:
            return GuardResult(
                allowed=False,
                code="DAILY_LOSS_LIMIT",
                severity="ERROR",
                details=f"Daily loss {acc_state.daily_loss:.2f} >= {self.profile.max_daily_loss:.2f}",
            ).to_dict()

        # Check 2: Max open positions
        if len(acc_state.open_positions) >= self.profile.max_open_positions:
            return GuardResult(
                allowed=False,
                code="MAX_POSITIONS",
                severity="ERROR",
                details=f"Already at max positions ({self.profile.max_open_positions})",
            ).to_dict()

        # Check 3: Lot size validation
        if t_risk.lot_size > self.profile.max_lot_per_trade:
            return GuardResult(
                allowed=False,
                code="LOT_SIZE_EXCEEDED",
                severity="ERROR",
                details=f"Lot {t_risk.lot_size:.2f} > max {self.profile.max_lot_per_trade:.2f}",
                max_safe_lot=self.profile.max_lot_per_trade,
                recommended_lot=self.profile.max_lot_per_trade,
            ).to_dict()

        # Check 4: Comprehensive prop firm rule validation
        prop_check = self.profile.check(account_state, trade_risk)

        if not prop_check["allowed"]:
            return prop_check

        # All checks passed
        return GuardResult(
            allowed=True,
            code="APPROVED",
            severity="INFO",
            details=f"Trade approved (verdict: {signal_verdict})" if signal_verdict else "Trade approved",
            max_safe_lot=min(t_risk.lot_size, self.profile.max_lot_per_trade),
            recommended_lot=min(t_risk.lot_size, self.profile.max_lot_per_trade),
        ).to_dict()
