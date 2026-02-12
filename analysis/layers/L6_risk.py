"""
L6 — Risk Feasibility (NO POSITION SIZING)
"""

from config.constants import get_threshold

# Risk thresholds
DEFAULT_BASE_RISK_PCT: float = get_threshold("risk.base_risk_pct", 1.0)
DEFAULT_MAX_EFFECTIVE_RISK_PCT: float = get_threshold("risk.max_effective_risk_pct", 2.0)
DEFAULT_MAX_DD_DAILY: float = get_threshold("risk.max_dd_daily", 4.0)
DEFAULT_MAX_DD_TOTAL: float = get_threshold("risk.max_dd_total", 8.0)
DEFAULT_MIN_RR: float = get_threshold("rr.constitutional_min", 2.0)


class L6RiskAnalyzer:
    def analyze(self, rr: float) -> dict:
        if rr is None:
            return {"valid": False}

        return {
            "rr": rr,
            "risk_ok": rr >= 2.0,
            "valid": True,
        }


# Placeholder
