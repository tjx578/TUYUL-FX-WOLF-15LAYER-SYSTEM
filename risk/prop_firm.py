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
        return self.cfg["allowed_markets"].get(category, False)

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
            violations.append(f"Market category '{category}' not allowed by prop firm")

        # Check risk limit
        max_risk = self.max_risk_allowed()
        if risk_percent > max_risk:
            violations.append(f"Risk {risk_percent * 100:.2f}% exceeds max {max_risk * 100:.2f}%")

        # Check RR requirement
        min_rr = self.min_rr_required()
        if rr_ratio < min_rr:
            violations.append(f"RR {rr_ratio:.2f} below minimum {min_rr:.2f}")

        return {
            "compliant": len(violations) == 0,
            "violations": violations,
        }
