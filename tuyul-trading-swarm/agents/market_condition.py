"""Agent 6: Market Condition — deteksi kondisi pasar dan validasi lingkungan trading.

TRENDING    → kondisi ideal untuk directional trade
RANGING     → hanya near-boundary trades, waspada
CHOPPY      → REJECT semua setup
EXTREME     → REJECT atau extreme caution
"""
from __future__ import annotations

from typing import Any

from schemas.agent_report import AgentReport
from schemas.trade_candidate import TradeCandidate, MarketState
from agents.base_agent import BaseAgent


HOSTILE_CONDITIONS = {MarketState.CHOPPY.value, MarketState.EXTREME.value, "CHOPPY", "EXTREME"}
CAUTION_CONDITIONS = {MarketState.RANGING.value, "RANGING"}


class MarketConditionAgent(BaseAgent):
    """Deteksi kondisi pasar — reject hostile environments."""

    agent_id = 6
    agent_name = "market_condition"
    domain = "environment"
    role = "environment-gate"

    async def _evaluate(self, candidate: TradeCandidate) -> AgentReport:
        ctx = candidate.raw_context
        details: dict[str, Any] = {}
        disqualifiers: list[str] = []
        warnings: list[str] = []

        # ── Deteksi market state ──────────────────────────────────────────
        market_state = str(ctx.get("market_state", "UNKNOWN")).upper()
        details["market_state"] = market_state

        # ── ADX / trend strength ──────────────────────────────────────────
        adx = float(ctx.get("adx", 0))
        details["adx"] = adx

        if adx == 0:
            # Infer dari market_state jika ADX tidak ada
            if market_state in ("TRENDING",):
                adx = 30.0  # assume strong
            elif market_state in ("RANGING",):
                adx = 18.0
            elif market_state in ("CHOPPY",):
                adx = 10.0

        # Overwrite market_state berdasarkan ADX jika tidak konsisten
        if adx >= 25 and market_state == "UNKNOWN":
            market_state = "TRENDING"
        elif adx < 20 and market_state == "UNKNOWN":
            market_state = "RANGING"

        details["market_state_final"] = market_state

        # ── Reject hostile conditions ─────────────────────────────────────
        if market_state in HOSTILE_CONDITIONS:
            disqualifiers.append(
                f"Kondisi pasar hostile: {market_state} — trading tidak diizinkan"
            )
            if market_state == "CHOPPY":
                disqualifiers.append("Choppy market: false breakout dan whipsaw risk tinggi")
            if market_state == "EXTREME":
                disqualifiers.append("Extreme volatility: spread lebar, slippage tinggi, unpredictable")

        # ── Caution untuk ranging ──────────────────────────────────────────
        if market_state in CAUTION_CONDITIONS:
            warnings.append(
                "Pasar ranging — hanya valid jika setup adalah near-boundary reversion"
            )
            near_boundary = ctx.get("near_range_boundary", False)
            if not near_boundary:
                disqualifiers.append(
                    "Ranging market dan bukan near-boundary — directional trade tidak valid"
                )

        # ── HTF alignment ─────────────────────────────────────────────────
        htf_aligned = ctx.get("htf_bias_aligned", True)
        if not htf_aligned:
            disqualifiers.append("Setup berlawanan dengan HTF bias")
            details["htf_bias_aligned"] = False
        else:
            details["htf_bias_aligned"] = True

        # ── Volatility extremes ────────────────────────────────────────────
        atr_pips = float(ctx.get("atr_pips", 0))
        details["atr_pips"] = atr_pips
        if atr_pips > 200:
            warnings.append(f"ATR sangat tinggi ({atr_pips} pip) — position sizing extra hati-hati")

        # ── Liquidity assessment ──────────────────────────────────────────
        liquidity = str(ctx.get("market_liquidity", "NORMAL")).upper()
        details["market_liquidity"] = liquidity
        if liquidity in ("LOW", "THIN", "DEAD"):
            warnings.append(f"Likuiditas {liquidity} — eksekusi dan spread bermasalah")

        if disqualifiers:
            return self.fail_report(
                candidate,
                reason=f"Kondisi pasar tidak mendukung: {market_state}",
                disqualifiers=disqualifiers,
                details=details,
            )

        score = 80.0
        if market_state == "TRENDING" and adx >= 25:
            score = 95.0
        elif market_state == "TRENDING":
            score = 85.0

        return self.pass_report(
            candidate,
            reason=f"Market state {market_state} mendukung trading (ADX:{adx:.0f})",
            score=score,
            details=details,
            warnings=warnings,
        )
