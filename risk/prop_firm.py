"""
Prop Firm Rule Validator

Validates trading decisions against prop firm rules.
Integrates with circuit breaker and drawdown monitoring
for real-time compliance checks.
"""

try:
    from config_loader import load_prop_firm
except ModuleNotFoundError:

    def load_prop_firm():
        """
        Fallback configuration loader used when `config_loader` is not available.

        Returns a minimal configuration structure with the keys expected by
        `PropFirmRules`, so that the module can be imported without error.
        """
        return {
            "allowed_markets": {},
            "risk": {
                "max_risk_per_trade_percent": 0.0,
                "min_rr_required": 0.0,
            },
        }


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

    def __init__(self):
        """Initialize PropFirmRules with config."""
        self.cfg = load_prop_firm()

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
        return self.cfg["allowed_markets"].get(category, False) # pyright: ignore[reportReturnType]

    def max_risk_allowed(self) -> float:
        """
        Get maximum risk % allowed per trade.

        Returns
        -------
        float
            Max risk as decimal (e.g., 0.01 = 1%)
        """
        return self.cfg["risk"]["max_risk_per_trade_percent"]

    def min_rr_required(self) -> float:
        """
        Get minimum risk/reward ratio required.

        Returns
        -------
        float
            Minimum RR ratio (e.g., 2.0)
        """
        return self.cfg["risk"]["min_rr_required"]

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

    def check(self, account_state: dict, trade_risk: dict) -> dict:
        """Check trade against prop firm rules.

        Returns dict with at minimum:
            allowed, code, severity, max_safe_lot
        """
        result: dict[str, bool | str | float] = {
            "allowed": False,
            "code": "RISK_EXCEEDED",
            "severity": "HIGH",
            "details": "",
        }

        # Validate trade
        trade_result = self.validate_trade(
            trade_risk["category"],
            trade_risk["risk_percent"],
            trade_risk["rr_ratio"],
        )

        if trade_result["compliant"]:
            result["allowed"] = True
            result["code"] = "TRADE_ALLOWED"
            result["severity"] = "LOW"
            result["details"] = "Trade is compliant with prop firm rules."
        else:
            result["details"] = "Trade violates prop firm rules."
            result["code"] = "RISK_EXCEEDED"
            result["severity"] = "HIGH"

        # Guarantee max_safe_lot is always present before returning
        if "max_safe_lot" not in result:
            result["max_safe_lot"] = result.get("recommended_lot", 0.0)

        return result

    @property
    def max_daily_loss(self):
        raise NotImplementedError

    @max_daily_loss.setter
    def max_daily_loss(self, value):
        raise NotImplementedError

    @property
    def max_open_positions(self):
        raise NotImplementedError

    @max_open_positions.setter
    def max_open_positions(self, value):
        raise NotImplementedError

    @property
    def max_lot_per_trade(self):
        raise NotImplementedError

    @max_lot_per_trade.setter
    def max_lot_per_trade(self, value):
        raise NotImplementedError


class PropFirmGuard:
    """
    Risk authority for prop firm compliance.

    Constitutional constraint: ALWAYS checked before execution,
    regardless of signal strength or confidence.
    """

    def __init__(self):
        """Initialize PropFirmGuard with prop firm rules."""
        self.profile = PropFirmRules()

    def check(
        self,
        account_state: dict,
        trade_risk: dict,
        signal_verdict: str,  # ✅ NEW: Accept verdict but don't let it bypass checks
    ) -> dict:
        """
        Validate trade against prop firm rules.

        Args:
            account_state: {balance, equity, open_positions, daily_loss, ...}
            trade_risk: {lot_size, risk_amount, symbol, ...}
            signal_verdict: L12 verdict (for audit only, NOT a bypass key)

        Returns:
            {
                "allowed": bool,
                "code": str,
                "severity": "ERROR" | "WARNING",
                "details": str | None,
            }
        """
        # ✅ CRITICAL: Even EXECUTE verdicts must pass prop firm checks
        # Signal confidence does NOT override risk rules

        # Check 1: Daily loss limit
        if account_state["daily_loss"] >= self.profile.max_daily_loss:
            return {
                "allowed": False,
                "code": "DAILY_LOSS_LIMIT",
                "severity": "ERROR",
                "details": f"Daily loss {account_state['daily_loss']:.2f} >= {self.profile.max_daily_loss:.2f}",
            }

        # Check 2: Max open positions
        if len(account_state["open_positions"]) >= self.profile.max_open_positions:
            return {
                "allowed": False,
                "code": "MAX_POSITIONS",
                "severity": "ERROR",
                "details": f"Already at max positions ({self.profile.max_open_positions})",
            }

        # Check 3: Lot size validation
        if trade_risk["lot_size"] > self.profile.max_lot_per_trade:
            return {
                "allowed": False,
                "code": "LOT_SIZE_EXCEEDED",
                "severity": "ERROR",
                "details": f"Lot {trade_risk['lot_size']} > max {self.profile.max_lot_per_trade}",
            }

        # ✅ All checks passed
        return {
            "allowed": True,
            "code": "APPROVED",
            "severity": "INFO",
            "details": None,
        }
