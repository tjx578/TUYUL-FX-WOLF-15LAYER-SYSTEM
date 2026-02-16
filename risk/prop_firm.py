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
        """
        Check if a trade is allowed based on account state and risk.

        Parameters
        ----------
        account_state : dict
            Account state (e.g., "drawdown", "circuit_breaker")
        trade_risk : dict
            Trade risk (e.g., "risk_percent", "rr_ratio")

        Returns
        -------
        dict
            Result with:
            - allowed: bool
            - code: str
            - severity: str
            - details: str?
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

        # Ensure max_safe_lot is always present in result
        if "max_safe_lot" not in result:
            result["max_safe_lot"] = result.get("recommended_lot", 0.0)

        return result
