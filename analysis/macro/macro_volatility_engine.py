"""
Macro Volatility Engine - FINAL PRODUCTION

Real-time macro regime detection.
Finnhub VIX (real) -> Fallback proxy -> Redis + LiveContextBus

Output: macro:vix:state (Redis hash)
        snapshot()["macro"] (LiveContextBus)
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time

from datetime import UTC, datetime
from typing import Any

import httpx  # pyright: ignore[reportMissingImports]

from loguru import logger  # pyright: ignore[reportMissingImports]

from analysis.macro.vix_analysis_engine import VIXAnalysisEngine
from analysis.macro.vix_proxy_estimator import VIXProxyEstimator
from context.live_context_bus import LiveContextBus
from storage.redis_client import redis_client

FINNHUB_VIX_URL = "https://finnhub.io/api/v1/quote"
REFRESH_INTERVAL = 60
API_TIMEOUT = 5.0

# Multipliers per regime state
MULTIPLIERS = {
    0: {"volatility": 0.8, "risk": 1.2},   # Tranquil
    1: {"volatility": 1.0, "risk": 1.0},   # Stressed
    2: {"volatility": 1.3, "risk": 0.3},   # Crisis
}


class MacroVolatilityEngine:
    """Production macro volatility engine for Wolf-15."""

    def __init__(self):
        self.redis = redis_client
        self.context = LiveContextBus()
        from ingest.finnhub_key_manager import finnhub_keys  # noqa: PLC0415
        self._key_manager = finnhub_keys
        self.api_key = self._key_manager.current_key() or None

        self.vix_engine = VIXAnalysisEngine()
        self.proxy_engine = VIXProxyEstimator()

        self._last_state: dict | None = None
        logger.info("[MACRO] Engine initialized")

    async def start(self):
        """Start background refresh loop."""
        logger.info("[MACRO] Refresh loop started")
        while True:
            try:
                await self._refresh()
            except Exception as exc:
                logger.error(f"[MACRO] Error: {exc}")
            await asyncio.sleep(REFRESH_INTERVAL)

    async def _refresh(self):
        """Refresh cycle with fallback chain."""

        # Try real VIX first
        vix_level = await self._fetch_real_vix()
        source = "real"

        # Fallback to proxy
        if vix_level is None:
            vix_level = self._fetch_proxy()
            source = "proxy"

        # Final fallback
        if vix_level is None:
            vix_level = 15.0
            source = "fallback"

        # Analyze
        vix_state = self.vix_engine.analyze(vix_level)
        regime_state = self._classify(vix_level)
        multipliers = MULTIPLIERS[regime_state]

        # Build payload
        payload = {
            "vix_level": float(vix_level),
            "vix_regime": vix_state.vix_regime,
            "term_structure": vix_state.term_structure,
            "fear_greed_score": float(vix_state.fear_greed_score),
            "regime_score": float(vix_state.regime_score),
            "regime_state": regime_state,
            "volatility_multiplier": multipliers["volatility"],
            "risk_multiplier": multipliers["risk"],
            "source": source,
            "updated_at": datetime.now(UTC).isoformat(),
            "timestamp": int(time.time()),
        }

        # Publish
        self._publish(payload)

    async def _fetch_real_vix(self) -> float | None:
        """Fetch real VIX from Finnhub."""
        if not self.api_key:
            return None

        with contextlib.suppress(Exception):
            async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
                r = await client.get(
                    FINNHUB_VIX_URL,
                    params={"symbol": "VIX", "token": self.api_key},
                )
                if r.status_code == 200:
                    return float(r.json().get("c"))
        return None

    def _fetch_proxy(self) -> float | None:
        """Estimate synthetic VIX from forex H1 candle history.

        BUG FIX: Uses get_candle_history() directly instead of
        snapshot().get("candle_history") which doesn't exist in
        LiveContextBus.snapshot() return schema.
        """
        with contextlib.suppress(Exception):
            candles = self.context.get_candle_history("EURUSD", "H1", count=50)
            if candles:
                proxy = self.proxy_engine.estimate("EURUSD", candles)
                if proxy:
                    return proxy.vix_equivalent
        return None

    @staticmethod
    def _classify(vix: float) -> int:
        """Classify regime (0=Tranquil, 1=Stressed, 2=Crisis)."""
        if vix <= 14:
            return 0
        if vix <= 20:
            return 1
        return 2

    def _publish(self, state: dict):
        """Publish to Redis + LiveContextBus."""
        if state == self._last_state:
            return

        self._last_state = state

        # Redis
        try:
            self.redis.hset("macro:vix:state", mapping=state)
        except Exception as exc:
            logger.error(f"[MACRO] Redis write failed: {exc}")

        # LiveContextBus
        try:
            self.context.update_macro_state(state)
        except Exception as exc:
            logger.error(f"[MACRO] ContextBus update failed: {exc}")

        logger.info(
            f"[MACRO] {state['vix_regime']} "
            f"(VIX={state['vix_level']}, risk={state['risk_multiplier']})"
        )

    def get_state(self) -> dict[str, Any]:
        """Get latest macro state."""
        return self._last_state or self._default_state()

    @staticmethod
    def _default_state() -> dict[str, Any]:
        """Safe default (neutral regime)."""
        return {
            "vix_level": 15.0,
            "vix_regime": "ELEVATED",
            "term_structure": "UNKNOWN",
            "fear_greed_score": 0.5,
            "regime_score": 0.5,
            "regime_state": 1,
            "volatility_multiplier": 1.0,
            "risk_multiplier": 1.0,
            "source": "default",
            "timestamp": int(time.time()),
        }
