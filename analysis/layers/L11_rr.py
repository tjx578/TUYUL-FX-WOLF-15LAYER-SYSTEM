"""
L11 Risk-Reward Optimizer - RR + Battle Strategy.

Sources:
    core_quantum_unified.py    -> QuantumScenarioMatrix, QuantumExecutionOptimizer, BattleStrategy
    core_reflective_unified.py -> generate_trade_targets
    context.live_context_bus   -> candle history for ATR

Produces:
    - rr (float)               -> target ≥ 2.0
    - battle_strategy (str)    -> APEX_PREDATOR | BLOOD_MOON_HUNT | TSUNAMI_BREAKOUT | SHADOW_STRIKE
    - execution_mode (str)     -> TP1_ONLY
    - entry / entry_price (float)
    - sl / stop_loss (float)
    - tp1 / take_profit_1 (float)
    - atr (float)
    - direction (str)
    - entry_zone (str)
    - reason (str)
    - valid (bool)
"""  # noqa: N999

from __future__ import annotations

from typing import Any

from loguru import logger

try:
    import core.core_quantum_unified
except ImportError as exc:
    logger.warning(f"[L11] Could not import core modules at startup: {exc}")
    core = None

_MIN_CANDLES = 14
_MIN_RR = 1.5
_VALID_DIRECTIONS = {"BUY", "SELL"}


class L11RRAnalyzer:
    """Layer 11: Risk-Reward Optimization - Execution & Decision zone."""

    def __init__(self) -> None:
        self._scenario_matrix = None
        self._exec_optimizer = None

    def _ensure_loaded(self) -> None:
        if self._scenario_matrix is not None:
            return
        if core is None:
            logger.warning("[L11] Core modules unavailable; RR calculation unavailable")
            return
        try:
            self._scenario_matrix = core.core_quantum_unified.QuantumScenarioMatrix()
            self._exec_optimizer = core.core_quantum_unified.QuantumExecutionOptimizer()
        except Exception as exc:
            logger.warning(f"[L11] Could not instantiate core modules: {exc}")

    # ------------------------------------------------------------------
    # ATR helper
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_atr(candles: list[dict], period: int = 14) -> float:
        """Compute Average True Range from candle list."""
        if len(candles) < 2:
            return 0.0
        trs: list[float] = []
        for i in range(1, len(candles)):
            h = candles[i].get("high", 0.0)
            l = candles[i].get("low", 0.0)  # noqa: E741
            prev_c = candles[i - 1].get("close", 0.0)
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)
        if not trs:
            return 0.0
        use = trs[-period:]
        return sum(use) / len(use)

    # ------------------------------------------------------------------
    # Candle retrieval
    # ------------------------------------------------------------------
    @staticmethod
    def _get_candles(symbol: str, timeframe: str = "H1", count: int = 30) -> list[dict]:
        """Retrieve candles from LiveContextBus (best-effort)."""
        try:
            from context.live_context_bus import LiveContextBus  # noqa: PLC0415

            bus = LiveContextBus()
            return bus.get_candle_history(symbol, timeframe, count)
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------
    def calculate_rr(self, symbol: str, direction: str, *, entry: float | None = None) -> dict[str, Any]:
        """
        Calculate risk-reward and select battle strategy.

        Args:
            symbol: Trading pair.
            direction: "BUY" or "SELL".
            entry: Optional custom entry price.

        Returns:
            dict with keys: valid, reason, rr, entry, sl, tp1, atr,
            direction, battle_strategy, execution_mode, entry_zone, ...
        """
        self._ensure_loaded()

        # --- Direction validation ---
        if direction not in _VALID_DIRECTIONS:
            return self._fail("invalid_direction")

        # --- Candle data ---
        candles = self._get_candles(symbol)
        if len(candles) < _MIN_CANDLES:
            return self._fail("no_data")

        # --- ATR ---
        atr = self._compute_atr(candles)
        if atr <= 0.0:
            # Fallback: simple high-low range of last candle
            last = candles[-1]
            atr = last.get("high", 0.0) - last.get("low", 0.0)

        # --- Entry ---
        if entry is None:
            entry = candles[-1].get("close", 0.0)

        if entry is None or entry == 0.0:
            return self._fail("no_entry_price")

        # --- SL / TP ---
        sl_distance = atr * 1.0
        tp_distance = atr * 2.0

        if direction == "BUY":
            sl = round(entry - sl_distance, 5)
            tp1 = round(entry + tp_distance, 5)
        else:
            sl = round(entry + sl_distance, 5)
            tp1 = round(entry - tp_distance, 5)

        # --- RR ---
        rr = round(tp_distance / sl_distance, 2) if sl_distance > 0 else 0.0

        if rr < _MIN_RR:
            return {
                "valid": False,
                "reason": "rr_too_low",
                "rr": rr,
                "entry": round(entry, 5),
                "sl": sl,
                "tp1": tp1,
                "atr": round(atr, 5),
                "direction": direction,
                "battle_strategy": "SHADOW_STRIKE",
                "execution_mode": "TP1_ONLY",
                "entry_price": round(entry, 5),
                "stop_loss": sl,
                "take_profit_1": tp1,
                "entry_zone": f"{sl:.5f}-{tp1:.5f}",
            }

        # --- Battle strategy selection ---
        if rr >= 3.0:
            strategy = "APEX_PREDATOR"
        elif rr >= 2.5:
            strategy = "TSUNAMI_BREAKOUT"
        elif rr >= 2.0:
            strategy = "BLOOD_MOON_HUNT"
        else:
            strategy = "SHADOW_STRIKE"

        return {
            "valid": True,
            "reason": "rr_ok",
            "rr": rr,
            "entry": round(entry, 5),
            "sl": sl,
            "tp1": tp1,
            "atr": round(atr, 5),
            "direction": direction,
            "battle_strategy": strategy,
            "execution_mode": "TP1_ONLY",
            "entry_price": round(entry, 5),
            "stop_loss": sl,
            "take_profit_1": tp1,
            "entry_zone": f"{sl:.5f}-{tp1:.5f}",
        }

    # ------------------------------------------------------------------
    # Legacy compatibility
    # ------------------------------------------------------------------
    def calculate(
        self, *, entry: float | None = None, sl: float | None = None, tp: float | None = None
    ) -> dict[str, Any]:
        """Legacy calculate method: compute RR from explicit entry/sl/tp."""
        if entry is None or sl is None or tp is None:
            return {"valid": False, "rr": 0.0, "reason": "invalid_params"}
        sl_dist = abs(entry - sl)
        tp_dist = abs(tp - entry)
        if sl_dist == 0:
            return {"valid": False, "rr": 0.0, "reason": "zero_sl_distance"}
        rr = round(tp_dist / sl_dist, 2)
        return {
            "valid": True,
            "rr": rr,
            "entry": entry,
            "sl": sl,
            "tp1": tp,
            "reason": "rr_ok" if rr >= _MIN_RR else "rr_too_low",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _fail(reason: str) -> dict[str, Any]:
        return {
            "valid": False,
            "reason": reason,
            "rr": 0.0,
            "entry": 0.0,
            "sl": 0.0,
            "tp1": 0.0,
            "atr": 0.0,
            "direction": "",
            "battle_strategy": "SHADOW_STRIKE",
            "execution_mode": "TP1_ONLY",
            "entry_price": 0.0,
            "stop_loss": 0.0,
            "take_profit_1": 0.0,
            "entry_zone": "0.00000-0.00000",
        }
