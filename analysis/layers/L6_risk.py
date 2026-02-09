"""
L6 — Risk Feasibility (NO POSITION SIZING)
"""


class L6RiskAnalyzer:
    def analyze(self, rr: float) -> dict:
        if rr is None:
            return {"valid": False}

        return {
            "rr": rr,
            "risk_ok": rr >= 2.0,
            "valid": True,
        }
