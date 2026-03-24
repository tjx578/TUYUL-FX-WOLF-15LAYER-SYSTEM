"""Ultra Fusion Orchestrator v6 -- main pipeline L8-L11."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .ema_engine import EMAFusionEngine
from .equilibrium import equilibrium_momentum_fusion
from .precision_engine import FusionPrecisionEngine

logger = logging.getLogger(__name__)


class UltraFusionOrchestrator:
    """Main orchestrator: EMA -> Precision -> Equilibrium -> Reflective Propagation."""

    VERSION = "6.0"

    def __init__(self) -> None:
        self.ema_engine = EMAFusionEngine()
        self.precision_engine = FusionPrecisionEngine()

    def execute_pipeline(
        self,
        symbol: str,
        prices: list[float],
        vwap_val: float,
        atr_val: float,
        reflex_strength: float,
        volatility: float,
        rsi_val: float,
        ema50_val: float,
        ema100_val: float,
        rc_adjusted: float,
    ) -> dict[str, Any]:
        ts = datetime.now(UTC).isoformat()
        ema_fusion = self.ema_engine.compute(prices)
        ema_fusion["timestamp"] = ts

        pr = self.precision_engine.compute_precision(
            price=prices[-1] if prices else 0.0,
            ema_fast_val=ema_fusion.get("ema21", 0.0),
            ema_slow_val=ema_fusion.get("ema55", 0.0),
            vwap=vwap_val,
            atr=atr_val,
            reflex_strength=reflex_strength,
            volatility=volatility,
            rsi=rsi_val,
            symbol=symbol,
        )
        precision = pr.as_dict()

        eq = equilibrium_momentum_fusion(
            vwap_val=vwap_val,
            ema_fusion_data={
                "ema50": ema50_val,
                "fusion_strength": precision.get("fusion_strength", 0.0),
                "cross_state": "bullish" if ema_fusion.get("direction") == "BULL" else "bearish",
            },
            reflex_strength=reflex_strength,
            lambda_esi=precision.get("details", {}).get("lambda_esi", 0.06),
        )

        frpc = {
            "fusion_strength": precision.get("fusion_strength", 0.0),
            "reflex_strength": reflex_strength,
            "rc_adjusted": rc_adjusted,
            "equilibrium_state": eq.get("state", "NEUTRAL"),
            "propagation_index": round((precision.get("fusion_strength", 0.0) + reflex_strength + rc_adjusted) / 3, 4),
            "timestamp": ts,
        }

        logger.info(f"[☁️] ULTRA FUSION pipeline synced -> {symbol}")
        return {
            "symbol": symbol,
            "timestamp": ts,
            "ema_layer": ema_fusion,
            "precision_layer": precision,
            "equilibrium_layer": eq,
            "reflective_layer": frpc,
        }


UltraFusionOrchestratorV6 = UltraFusionOrchestrator
