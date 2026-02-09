"""
L11 — Risk Reward Calculation
"""


class L11RRAnalyzer:
    def calculate(self, entry: float, sl: float, tp: float) -> dict:
        if entry is None or sl is None or tp is None:
            return {"valid": False}

        risk = abs(entry - sl)
        reward = abs(tp - entry)

        if risk == 0:
            return {"valid": False}

        rr = round(reward / risk, 2)

        return {
            "rr": rr,
            "valid": True,
        }
