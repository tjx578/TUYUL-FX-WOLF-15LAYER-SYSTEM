"""Agent 4: Smart Money — validasi institutional footprint.

Minimum confidence: 80% (Grade B atau A)
  Grade A: 90-100%
  Grade B: 80-89%
  Grade C: <80% → DISQUALIFIED
"""
from __future__ import annotations

from typing import Any

from schemas.agent_report import AgentReport
from schemas.trade_candidate import TradeCandidate
from agents.base_agent import BaseAgent


MIN_CONFIDENCE = 80.0  # Persen


def _score_component(ctx: dict, key: str, strong_vals: list, weak_vals: list) -> float:
    """Score satu komponen: 1.0=strong, 0.5=moderate, 0.0=weak/absent."""
    val = ctx.get(key, "")
    val_str = str(val).lower()
    if any(s in val_str for s in strong_vals):
        return 1.0
    if val_str in ("moderate", "medium", "partial"):
        return 0.5
    if any(w in val_str for w in weak_vals) or not val:
        return 0.0
    return 0.5


class SmartMoneyAgent(BaseAgent):
    """Validasi footprint institusional — order block, liquidity sweep, FVG, volume."""

    agent_id = 4
    agent_name = "smart_money"
    domain = "technical"
    role = "smart-money-gate"
    min_pass_score = MIN_CONFIDENCE

    async def _evaluate(self, candidate: TradeCandidate) -> AgentReport:
        ctx = candidate.raw_context
        details: dict[str, Any] = {}
        disqualifiers: list[str] = []
        warnings: list[str] = []

        # ── Komponen 1: Fresh Order Block ─────────────────────────────────
        ob_score = _score_component(
            ctx, "order_block_freshness",
            strong_vals=["fresh", "untouched", "pristine", "strong"],
            weak_vals=["tested", "stale", "old", "weak", "visited"],
        )
        details["order_block_freshness"] = ctx.get("order_block_freshness", "not_provided")
        details["ob_score"] = ob_score

        # ── Komponen 2: Liquidity Sweep Quality ───────────────────────────
        liq_score = _score_component(
            ctx, "liquidity_sweep_quality",
            strong_vals=["strong", "clean", "obvious", "high"],
            weak_vals=["weak", "ambiguous", "none", "no_sweep"],
        )
        details["liquidity_sweep_quality"] = ctx.get("liquidity_sweep_quality", "not_provided")
        details["liq_score"] = liq_score

        # ── Komponen 3: FVG Quality ───────────────────────────────────────
        fvg_pips = float(ctx.get("fvg_pips", 0))
        if fvg_pips >= 20:
            fvg_score = 1.0
        elif fvg_pips >= 10:
            fvg_score = 0.5
        else:
            fvg_score = 0.0
        details["fvg_pips"] = fvg_pips
        details["fvg_score"] = fvg_score

        # ── Komponen 4: Volume Confirmation ───────────────────────────────
        vol_pct = float(ctx.get("volume_vs_avg_pct", 100))
        if vol_pct >= 150:
            vol_score = 1.0
        elif vol_pct >= 120:
            vol_score = 0.5
        else:
            vol_score = 0.0
        details["volume_vs_avg_pct"] = vol_pct
        details["vol_score"] = vol_score

        # ── Hitung confidence ─────────────────────────────────────────────
        confidence = (
            ob_score * 0.25 +
            liq_score * 0.25 +
            fvg_score * 0.25 +
            vol_score * 0.25
        ) * 100

        if confidence >= 90:
            grade = "A"
        elif confidence >= 80:
            grade = "B"
        else:
            grade = "C"
            disqualifiers.append(
                f"Smart money confidence {confidence:.0f}% di bawah minimum {MIN_CONFIDENCE}% (Grade C)"
            )

        details["confidence"] = round(confidence, 1)
        details["grade"] = grade
        details["min_confidence"] = MIN_CONFIDENCE

        if ob_score == 0:
            disqualifiers.append("Order block tidak fresh atau tidak teridentifikasi")
        if liq_score == 0:
            warnings.append("Liquidity sweep lemah atau tidak jelas")

        if disqualifiers:
            return self.fail_report(
                candidate,
                reason=f"Smart money Grade {grade} ({confidence:.0f}%) — tidak memenuhi threshold",
                disqualifiers=disqualifiers,
                score=confidence,
                details=details,
            )

        return self.pass_report(
            candidate,
            reason=f"Smart money Grade {grade} ({confidence:.0f}%) — institutional footprint valid",
            score=confidence,
            confidence=confidence,
            details=details,
            warnings=warnings,
        )
