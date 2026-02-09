"""
Prop Firm Rule Validator
"""

from config_loader import load_prop_firm


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
