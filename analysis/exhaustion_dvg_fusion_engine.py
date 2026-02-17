from dataclasses import dataclass
from typing import Literal


@dataclass
class DivergenceInput:
    """Validated input for divergence analysis."""
    osc: dict[str, list[float]]
    price: dict[str, list[float]]
    mode: Literal["bullish", "bearish"]

    def validate(self) -> tuple[bool, str]:
        """
        Validate multi-timeframe data availability.

        Returns:
            (is_valid, error_message)
        """
        required_tfs = {"M5", "M15", "H1", "H4"}

        # Check timeframe presence
        missing_tfs = required_tfs - set(self.osc.keys())
        if missing_tfs:
            return False, f"Missing oscillator data for: {missing_tfs}"

        missing_price_tfs = required_tfs - set(self.price.keys())
        if missing_price_tfs:
            return False, f"Missing price data for: {missing_price_tfs}"

        # Check minimum data points (need 2 for prev/curr comparison)
        for tf in required_tfs:
            if len(self.osc.get(tf, [])) < 2:
                return False, f"{tf} oscillator needs ≥2 data points, got {len(self.osc.get(tf, []))}"
            if len(self.price.get(tf, [])) < 2:
                return False, f"{tf} price needs ≥2 data points, got {len(self.price.get(tf, []))}"

        return True, ""


class ExhaustionDivergenceFusionEngine:
    """
    Multi-timeframe divergence detector with graceful degradation.

    Constitutional compliance:
    - Analysis only, no execution decisions
    - Returns score + confidence + reason (NOT verdict)
    - Handles missing data without crashing
    """

    def __init__(self):
        self.tf_weights = {
            "M5": 0.1,
            "M15": 0.2,
            "H1": 0.3,
            "H4": 0.4,
        }
        self.min_confidence = 0.5  # Below this = NO_SIGNAL

    def analyze(
        self,
        osc: dict[str, list[float]],
        price: dict[str, list[float]],
        mode: Literal["bullish", "bearish"],
    ) -> dict:
        """
        Compute divergence score across timeframes.

        Returns:
            {
                "score": float (0.0-1.0),
                "confidence": float (0.0-1.0),
                "reason": str,
                "available_tfs": list[str],
                "missing_tfs": list[str],
            }
        """
        # Validate input
        input_data = DivergenceInput(osc=osc, price=price, mode=mode)
        is_valid, error_msg = input_data.validate()

        if not is_valid:
            return {
                "score": 0.0,
                "confidence": 0.0,
                "reason": f"INSUFFICIENT_DATA: {error_msg}",
                "available_tfs": list(osc.keys()),
                "missing_tfs": list(set(self.tf_weights.keys()) - set(osc.keys())),
            }

        # Compute weighted divergence score
        total_score = 0.0
        total_weight = 0.0
        detected_tfs = []

        for tf, weight in self.tf_weights.items():
            try:
                dvg_present = self._check_divergence(
                    osc[tf][-2], osc[tf][-1],
                    price[tf][-2], price[tf][-1],
                    mode,
                )

                if dvg_present:
                    total_score += weight
                    detected_tfs.append(tf)

                total_weight += weight

            except (KeyError, IndexError) as e:
                # Should not happen after validation, but defensive
                return {
                    "score": 0.0,
                    "confidence": 0.0,
                    "reason": f"DATA_ACCESS_ERROR: {tf} - {e}",
                    "available_tfs": [],
                    "missing_tfs": [tf],
                }

        # Normalize score
        final_score = total_score / total_weight if total_weight > 0 else 0.0

        # Confidence = alignment strength (how many TFs agree)
        confidence = len(detected_tfs) / len(self.tf_weights)

        # Reason generation
        if confidence >= 0.75:
            reason = f"STRONG_DIVERGENCE: {len(detected_tfs)}/4 TFs ({', '.join(detected_tfs)})"
        elif confidence >= 0.5:
            reason = f"MODERATE_DIVERGENCE: {len(detected_tfs)}/4 TFs ({', '.join(detected_tfs)})"
        else:
            reason = f"WEAK_DIVERGENCE: {len(detected_tfs)}/4 TFs"

        return {
            "score": round(final_score, 3),
            "confidence": round(confidence, 3),
            "reason": reason,
            "available_tfs": list(self.tf_weights.keys()),
            "missing_tfs": [],
        }

    def _check_divergence(
        self,
        prev_osc: float,
        curr_osc: float,
        prev_price: float,
        curr_price: float,
        mode: Literal["bullish", "bearish"],
    ) -> bool:
        """
        Check if divergence exists between oscillator and price.

        Bullish divergence: price makes lower low, oscillator makes higher low
        Bearish divergence: price makes higher high, oscillator makes lower high
        """
        if mode == "bullish":
            price_lower = curr_price < prev_price
            osc_higher = curr_osc > prev_osc
            return price_lower and osc_higher
        else:  # bearish
            price_higher = curr_price > prev_price
            osc_lower = curr_osc < prev_osc
            return price_higher and osc_lower

async def fetch_price_data(symbol: str) -> dict:
    raise NotImplementedError

async def fetch_rsi_data(symbol: str) -> dict:
    raise NotImplementedError


# ✅ USAGE EXAMPLE
async def exhaustion_layer_analysis(symbol: str) -> dict:
    """
    Layer-7 Exhaustion analysis with validation.

    Returns analysis result, NOT a verdict.
    Constitution (Layer-12) decides.
    """
    engine = ExhaustionDivergenceFusionEngine()

    # Fetch multi-timeframe data
    osc_data = await fetch_rsi_data(symbol)  # {"M5": [...], "M15": [...], ...}  # noqa: F821
    price_data = await fetch_price_data(symbol)

    # Analyze (handles missing data gracefully)
    result = engine.analyze(
        osc=osc_data,
        price=price_data,
        mode="bullish",  # or "bearish" based on context
    )

    # Return to Layer-12 for verdict
    return {
        "layer": "L7_EXHAUSTION",
        "symbol": symbol,
        "exhaustion_score": result["score"],
        "confidence": result["confidence"],
        "reason": result["reason"],
        "data_quality": {
            "available_tfs": result["available_tfs"],
            "missing_tfs": result["missing_tfs"],
        },
    }
