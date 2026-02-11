"""
L2 — Multi-Timeframe Alignment (H1 vs M15)
"""

from context.live_context_bus import LiveContextBus


class L2MTAAnalyzer:
    def __init__(self):
        self.context = LiveContextBus()

    def analyze(self, symbol: str) -> dict:
        h1 = self.context.get_candle(symbol, "H1")
        m15 = self.context.get_candle(symbol, "M15")

        if not h1 or not m15:
            return {"aligned": False, "valid": False}

        aligned = self._check_alignment(h1, m15)

        return {
            "aligned": aligned,
            "valid": True,
        }

    @staticmethod
    def _check_alignment(h1: dict, m15: dict) -> bool:
        # placeholder: candle direction agreement
        h1_dir = h1["close"] > h1["open"]
        m15_dir = m15["close"] > m15["open"]
        return h1_dir == m15_dir


# Placeholder
