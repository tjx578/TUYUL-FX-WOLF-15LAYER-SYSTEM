"""Agent 3: Technical Structure — TWMS 12-point checklist evaluation.

Pass threshold: 11/12 (EXCELLENT) atau 12/12 (PERFECT)
10/12 = SKIP, <10 = HARD FAIL
"""
from __future__ import annotations

from typing import Any

from schemas.agent_report import AgentReport
from schemas.trade_candidate import TradeCandidate
from agents.base_agent import BaseAgent


TWMS_CHECKLIST = [
    # Trend Confirmation (4 poin)
    "htf_trend_aligned",
    "ema_alignment",
    "trendline_respect",
    "momentum_confirmed",
    # Smart Money Structure (4 poin)
    "order_block_identified",
    "liquidity_sweep",
    "fair_value_gap",
    "volume_profile",
    # Entry Precision (4 poin)
    "mtf_sync",
    "fibonacci_confluence",
    "candle_pattern",
    "divergence_confirmation",
]

PASS_THRESHOLD = 11  # Minimum 11/12


class TechnicalStructureAgent(BaseAgent):
    """Evaluasi kualitas struktur teknikal menggunakan TWMS 12-point framework."""

    agent_id = 3
    agent_name = "technical_structure"
    domain = "technical"
    role = "technical-gate"
    min_pass_score = float(PASS_THRESHOLD)

    async def _evaluate(self, candidate: TradeCandidate) -> AgentReport:
        ctx = candidate.raw_context
        scores: dict[str, bool] = {}
        details: dict[str, Any] = {}
        disqualifiers: list[str] = []

        # ── Evaluasi setiap checklist item ────────────────────────────────
        for item in TWMS_CHECKLIST:
            val = ctx.get(item)
            if val is None:
                # Item tidak ada di context → FAIL item ini
                scores[item] = False
            elif isinstance(val, bool):
                scores[item] = val
            elif isinstance(val, (int, float)):
                scores[item] = val >= 0.5
            else:
                scores[item] = str(val).lower() in ("true", "yes", "1", "strong")

        passed = sum(1 for v in scores.values() if v)
        failed_items = [k for k, v in scores.items() if not v]
        twms_score = f"{passed}/12"

        details["twms_score"] = twms_score
        details["passed"] = passed
        details["scores"] = scores
        details["failed_items"] = failed_items

        # ── Grade dan threshold ────────────────────────────────────────────
        if passed == 12:
            grade = "PERFECT"
        elif passed == 11:
            grade = "EXCELLENT"
        elif passed == 10:
            grade = "BELOW_THRESHOLD"
            disqualifiers.append(f"Skor TWMS {twms_score} di bawah minimum (11/12)")
        else:
            grade = "HARD_FAIL"
            disqualifiers.append(f"Skor TWMS {twms_score} — hard fail (<10/12)")

        details["grade"] = grade
        details["threshold"] = PASS_THRESHOLD

        # ── Hard disqualifier: item kritis ────────────────────────────────
        critical_items = ["htf_trend_aligned", "order_block_identified", "liquidity_sweep"]
        for ci in critical_items:
            if not scores.get(ci, False):
                disqualifiers.append(f"Item kritis gagal: {ci}")

        if disqualifiers:
            return self.fail_report(
                candidate,
                reason=f"TWMS {twms_score} gagal threshold — {grade}",
                disqualifiers=disqualifiers,
                score=float(passed),
                details=details,
            )

        score_pct = (passed / 12) * 100
        return self.pass_report(
            candidate,
            reason=f"TWMS {twms_score} — {grade} — struktur teknikal valid",
            score=score_pct,
            confidence=score_pct,
            details=details,
        )
