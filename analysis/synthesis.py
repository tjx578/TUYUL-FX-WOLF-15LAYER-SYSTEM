"""
SYNTHESIS — Aggregate L1–L11
Produces candidate setup (pre-constitution).
"""

from analysis.layers.L1_context import L1ContextAnalyzer
from analysis.layers.L2_mta import L2MTAAnalyzer
from analysis.layers.L3_technical import L3TechnicalAnalyzer
from analysis.layers.L4_scoring import L4ScoringEngine
from analysis.layers.L5_psychology import L5PsychologyAnalyzer
from analysis.layers.L6_risk import L6RiskAnalyzer
from analysis.layers.L7_probability import L7ProbabilityAnalyzer
from analysis.layers.L8_tii_integrity import L8TIIIntegrityAnalyzer
from analysis.layers.L9_smc import L9SMCAnalyzer
from analysis.layers.L10_position import L10PositionAnalyzer
from analysis.layers.L11_rr import L11RRAnalyzer


class SynthesisEngine:
    def __init__(self):
        self.l1 = L1ContextAnalyzer()
        self.l2 = L2MTAAnalyzer()
        self.l3 = L3TechnicalAnalyzer()
        self.l4 = L4ScoringEngine()
        self.l5 = L5PsychologyAnalyzer()
        self.l6 = L6RiskAnalyzer()
        self.l7 = L7ProbabilityAnalyzer()
        self.l8 = L8TIIIntegrityAnalyzer()
        self.l9 = L9SMCAnalyzer()
        self.l10 = L10PositionAnalyzer()
        self.l11 = L11RRAnalyzer()

    def build_candidate(self, symbol: str) -> dict:
        """
        Build candidate setup for a symbol.
        """
        l1 = self.l1.analyze(symbol)
        l2 = self.l2.analyze(symbol)
        l3 = self.l3.analyze(symbol)

        l4 = self.l4.score(l1, l2, l3)
        l7 = self.l7.analyze(l4["technical_score"])

        l8 = self.l8.analyze(
            {
                "l1": l1,
                "l2": l2,
                "l3": l3,
                "l4": l4,
                "l7": l7,
            }
        )

        l9 = self.l9.analyze(l3)
        l6 = self.l6.analyze(rr=2.0)  # placeholder RR
        l10 = self.l10.analyze(l6.get("risk_ok"), l9.get("confidence", 0))
        l11 = {"valid": False}  # entry/sl/tp calculated later (constitution/execution prep)

        return {
            "symbol": symbol,
            "L1": l1,
            "L2": l2,
            "L3": l3,
            "L4": l4,
            "L5": None,
            "L6": l6,
            "L7": l7,
            "L8": l8,
            "L9": l9,
            "L10": l10,
            "L11": l11,
            "valid": True,
        }
