"""
Prop Firm Rule Validator
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
    def __init__(self):
        self.cfg = load_prop_firm()

    def is_market_allowed(self, category: str) -> bool:
        return self.cfg["allowed_markets"].get(category, False)

    def max_risk_allowed(self) -> float:
        return self.cfg["risk"]["max_risk_per_trade_percent"]

    def min_rr_required(self) -> float:
        return self.cfg["risk"]["min_rr_required"]
# Placeholder
