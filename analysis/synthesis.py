"""
SYNTHESIS — Aggregate L1–L11
Produces candidate setup (pre-constitution).
"""

from context.runtime_state import RuntimeState
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


def build_synthesis(pair: str) -> dict:
    """
    Module-level function to build synthesis and transform to L12 contract format.
    
    Args:
        pair: Trading pair symbol (e.g., "XAUUSD")
        
    Returns:
        Dictionary matching L12 contract with keys: pair, scores, layers, execution,
        risk, propfirm, bias, system
    """
    engine = SynthesisEngine()
    raw_candidate = engine.build_candidate(pair)
    
    # Extract layer data
    l4 = raw_candidate.get("L4", {})
    l7 = raw_candidate.get("L7", {})
    l8 = raw_candidate.get("L8", {})
    l9 = raw_candidate.get("L9", {})
    l10 = raw_candidate.get("L10", {})
    
    # Compute scores
    scores = {
        "wolf_30_point": l4.get("wolf_score", 0.0),
        "f_score": l4.get("fundamental_score", 0.0),
        "t_score": l4.get("technical_score", 0.0),
        "fta_score": l4.get("fta_score", 0.0),
        "exec_score": l4.get("execution_score", 0.0),
    }
    
    # Flatten layers data
    layers = {
        "L8_tii_sym": l8.get("tii_sym", 0.0),
        "L8_integrity_index": l8.get("integrity_index", 0.0),
        "L7_monte_carlo_win": l7.get("win_probability", 0.0),
        "conf12": l9.get("confidence", 0.0),
    }
    
    # Build execution data
    execution = {
        "direction": l10.get("direction", "NONE"),
        "entry": l10.get("entry", 0.0),
        "sl": l10.get("sl", 0.0),
        "tp": l10.get("tp", 0.0),
        "rr_ratio": l10.get("rr", 2.0),
        "lot_size": l10.get("lot_size", 0.01),
        "risk_percent": l10.get("risk_percent", 1.0),
    }
    
    # Get current drawdown from runtime state
    risk = {
        "current_drawdown": getattr(RuntimeState, "current_drawdown", 0.0),
    }
    
    # Prop firm compliance
    propfirm = {
        "compliant": True,
    }
    
    # Bias alignment
    bias = {
        "fundamental": "NEUTRAL",
        "technical": "NEUTRAL",
        "aligned": False,
    }
    
    # System data (placeholder)
    system = {
        "latency_ms": 0,  # Will be injected in main loop
    }
    
    return {
        "pair": pair,
        "scores": scores,
        "layers": layers,
        "execution": execution,
        "risk": risk,
        "propfirm": propfirm,
        "bias": bias,
        "system": system,
    }
