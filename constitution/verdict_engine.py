"""
Verdict Engine — L12 Final Authority
"""

from constitution.gatekeeper import Gatekeeper


class VerdictEngine:
    def __init__(self):
        self.gatekeeper = Gatekeeper()

    def issue_verdict(self, candidate: dict) -> dict:
        gate_result = self.gatekeeper.evaluate(candidate)

        if not gate_result["passed"]:
            return {
                "verdict": "NO_TRADE",
                "reason": gate_result["reason"],
                "confidence": "LOW",
            }

        direction = self._infer_direction(candidate)

        return {
            "verdict": f"EXECUTE_{direction}",
            "confidence": "HIGH",
            "execution_mode": "TP1_ONLY",
        }

    @staticmethod
    def _infer_direction(candidate: dict) -> str:
        trend = candidate["L3"].get("trend", "NEUTRAL")
        if trend == "BULLISH":
            return "BUY"
        if trend == "BEARISH":
            return "SELL"
        return "HOLD"
# Placeholder
