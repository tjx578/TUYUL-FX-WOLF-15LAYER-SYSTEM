"""
L10 — Position Feasibility
NO LOT SIZE | NO EXECUTION
"""

from config.constants import get_threshold

# Position sizing thresholds
DEFAULT_BASE_RISK_PCT: float = get_threshold("risk.base_risk_pct", 1.0)
DEFAULT_MAX_LOT: float = get_threshold("position.max_lot", 5.0)
DEFAULT_MIN_LOT: float = get_threshold("position.min_lot", 0.01)
FTA_SCALE: dict = get_threshold("position.fta_scale", {
    "4": 1.0,
    "3": 0.8,
    "2": 0.5,
    "1": 0.3,
    "0": 0.0
})


class L10PositionAnalyzer:
    def analyze(self, risk_ok: bool, smc_confidence: float) -> dict:
        if not risk_ok:
            return {"position_ok": False, "valid": False}

        position_ok = smc_confidence >= 0.6

        return {
            "position_ok": position_ok,
            "valid": True,
        }


# Placeholder
