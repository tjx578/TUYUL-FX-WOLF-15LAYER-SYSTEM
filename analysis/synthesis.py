"""
SYNTHESIS — Aggregate L1–L11
Produces candidate setup (pre-constitution).
"""

from loguru import logger

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
from analysis.macro.monthly_regime import MonthlyRegimeAnalyzer


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
        self.macro = MonthlyRegimeAnalyzer()

    def build_candidate(self, symbol: str) -> dict:
        """
        Build candidate setup for a symbol.
        """
        l1 = self.l1.analyze(symbol)
        l2 = self.l2.analyze(symbol)
        l3 = self.l3.analyze(symbol)

        # L4 Scoring
        l4 = self.l4.score(l1, l2, l3)

        # L5 Psychology
        l5 = self.l5.analyze(symbol, volatility_profile=l2)

        # L7 Probability
        l7 = self.l7.analyze(l4["technical_score"])

        # L8 TII Integrity
        l8 = self.l8.analyze(
            {
                "l1": l1,
                "l2": l2,
                "l3": l3,
                "l4": l4,
                "l7": l7,
            }
        )

        # L9 SMC - Get full structure analysis
        structure = self.l3.structure.analyze(symbol)
        l9 = self.l9.analyze(symbol, structure)

        # L11 RR - Map trend explicitly to direction
        # In real trading, direction would come from signal
        trend = l3.get("trend")
        direction = None
        l11 = {"valid": False}

        if trend == "BULLISH":
            direction = "BUY"
        elif trend == "BEARISH":
            direction = "SELL"

        if direction is not None:
            l11 = self.l11.calculate_rr(symbol, direction)

        # L6 Risk - Use L11 RR if available
        rr_value = l11.get("rr", 2.0) if l11.get("valid") else 2.0
        l6 = self.l6.analyze(rr=rr_value)

        # L10 Position
        l10 = self.l10.analyze(bool(l6.get("risk_ok", False)), l9.get("confidence", 0))

        # Macro regime analysis
        macro = self.macro.analyze(symbol)

        return {
            "symbol": symbol,
            "L1": l1,
            "L2": l2,
            "L3": l3,
            "L4": l4,
            "L5": l5,
            "L6": l6,
            "L7": l7,
            "L8": l8,
            "L9": l9,
            "L10": l10,
            "L11": l11,
            "macro": macro,
            "valid": True,
        }


# Placeholder


def build_synthesis(
    pair: str, risk_manager=None, vix_level: float | None = None
) -> dict:
    """
    Build L12-contract-compliant synthesis for a pair.

    This is the bridge between L1-L11 raw layer analysis and the L12 verdict engine.
    Transforms SynthesisEngine.build_candidate() output into the contract format
    expected by synthesis_adapter.py and verdict_engine.py.

    Args:
        pair: Trading pair symbol (e.g., "EURUSD")
        risk_manager: Optional RiskManager instance for real risk data
        vix_level: Optional VIX level for risk calculations


    Returns:
        Dict with L12 contract fields: pair, scores, layers, execution, risk, propfirm, bias, system
    """
    engine = SynthesisEngine()
    raw = engine.build_candidate(pair)

    # Extract layer data (only layers used in this function)
    l1 = raw.get("L1", {})
    l2 = raw.get("L2", {})
    l3 = raw.get("L3", {})
    l4 = raw.get("L4", {})
    l7 = raw.get("L7", {})
    l8 = raw.get("L8", {})
    l10 = raw.get("L10", {})
    l11 = raw.get("L11", {})
    macro = raw.get("macro", {})

    # Compute wolf_30_point score (0-30) from layer scores
    # Based on L4 technical_score and L7 win probability
    technical_score = l4.get("technical_score", 0)
    win_prob = l7.get("win_probability", 0)
    wolf_30_point = int((technical_score / 100) * 15 + (win_prob / 100) * 15)
    wolf_30_point = max(0, min(30, wolf_30_point))  # clamp to 0-30

    # Compute FTA score (fundamental-technical alignment) 0.0-1.0
    # For now, based on validity of L1, L2, L3
    l1_valid = l1.get("valid", False)
    l2_valid = l2.get("valid", False)
    l3_valid = l3.get("valid", False)
    valid_count = sum([l1_valid, l2_valid, l3_valid])
    fta_score = valid_count / 3.0

    # Compute execution readiness score (0-10)
    exec_score = 10 if l10.get("position_ok", False) else 5

    # Determine direction from L3 trend
    trend = l3.get("trend", "NEUTRAL")
    if trend == "BULLISH":
        direction = "BUY"
    elif trend == "BEARISH":
        direction = "SELL"
    else:
        direction = "HOLD"

    # Compute basic entry/stop/tp from L11 or defaults
    # In production, L11 would calculate these based on structure
    entry_price = 1.1000  # placeholder
    stop_loss = 1.0950  # placeholder
    take_profit_1 = 1.1100  # placeholder
    rr_ratio = l11.get("rr", 2.0)

    # Get risk data from RiskManager if available
    if risk_manager is not None:
        try:
            # Get risk snapshot
            risk_snapshot = risk_manager.get_risk_snapshot(
                vix_level=vix_level,
                session=None,  # auto-detect
            )

            # Calculate position size
            position_data = risk_manager.calculate_position(
                entry_price=entry_price,
                stop_loss_price=stop_loss,
                pair=pair,
                vix_level=vix_level,
            )

            # Check prop firm compliance
            prop_compliance = risk_manager.check_prop_firm_compliance(
                {
                    "risk_percent": position_data["risk_percent"],
                    "rr_ratio": rr_ratio,
                }
            )

            # Extract values
            current_drawdown = risk_snapshot["drawdown"]["total_dd_percent"]
            lot_size = position_data["lot_size"]
            risk_percent = position_data["risk_percent"]
            risk_amount = position_data["risk_amount"]
            prop_compliant = prop_compliance["compliant"]

        except Exception as e:
            # Fallback to defaults on error
            logger.warning(
                "Failed to get risk data from RiskManager, using defaults",
                error=str(e),
                pair=pair,
            )
            current_drawdown = 0.0
            lot_size = 0.01
            risk_percent = 0.01  # 1%
            risk_amount = 100.0
            prop_compliant = True
    else:
        # Use defaults if no RiskManager provided
        current_drawdown = 0.0
        lot_size = 0.01
        risk_percent = 0.01  # 1%
        risk_amount = 100.0
        prop_compliant = True


    # Compute confidence index (conf12)
    # Average of key integrity metrics
    tii_sym = l8.get("tii_sym", 0.5)
    integrity = l8.get("integrity", 0.5)
    conf12 = (tii_sym + integrity) / 2.0

    # Build L12 contract
    return {
        "pair": pair,
        "scores": {
            "wolf_30_point": wolf_30_point,
            "f_score": l4.get("fundamental_score", 50.0),
            "t_score": technical_score,
            "fta_score": fta_score,
            "exec_score": exec_score,
        },
        "layers": {
            "L8_tii_sym": tii_sym,
            "L8_integrity_index": integrity,
            "L7_monte_carlo_win": win_prob,
            "conf12": conf12,
        },
        "execution": {
            "direction": direction,
            # NOTE: Duplicate fields for backwards compatibility
            # - 'entry' and 'entry_price' both contain the entry price
            # - 'take_profit' and 'take_profit_1' both contain TP1 price
            # This ensures compatibility with both test contracts and L12 verdict engine
            "entry": entry_price,
            "entry_zone": f"{entry_price - 0.0010:.5f}-{entry_price + 0.0010:.5f}",
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit_1": take_profit_1,
            "take_profit": take_profit_1,
            "rr_ratio": rr_ratio,
            "lot_size": lot_size,
            "risk_percent": risk_percent,
            "risk_amount": risk_amount,
        },
        "risk": {
            "current_drawdown": current_drawdown,
        },
        "propfirm": {
            "compliant": prop_compliant,
        },
        "bias": {
            "fundamental": "NEUTRAL" if not l1_valid else trend,
            "technical": trend,
            "macro": macro.get("regime", "UNKNOWN"),
        },
        "macro": {
            "regime": macro.get("regime", "UNKNOWN"),
            "phase": macro.get("phase", "NEUTRAL"),
            "volatility_ratio": macro.get("macro_vol_ratio", 1.0),
            "mn_aligned": macro.get("alignment", False),
            "liquidity": macro.get("liquidity", {}),
            "bias_override": macro.get("bias_override", {}),
        },
        "system": {
            "latency_ms": 0,  # will be injected by main.py
        },
    }
