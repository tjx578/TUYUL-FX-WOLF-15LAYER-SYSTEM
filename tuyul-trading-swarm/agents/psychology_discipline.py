"""Agent 8: Psychology & Discipline — HALT absolut jika mental state tidak aman.

HALT conditions (absolute override — tidak bisa di-bypass):
  - Daily loss limit terlampaui
  - Revenge trading pattern detected
  - FOMO trade (masuk tanpa setup, karena takut ketinggalan)
  - Consecutive losses tanpa review
  - Emotional state: ANGRY / EUPHORIC / DESPERATE
  - Overconfidence setelah streak menang
"""
from __future__ import annotations

import os
from typing import Any

from schemas.agent_report import AgentReport
from schemas.trade_candidate import TradeCandidate
from agents.base_agent import BaseAgent


MAX_DAILY_TRADES = int(os.getenv("MAX_DAILY_TRADES", "3"))
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "2"))
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "2.0"))


class PsychologyDisciplineAgent(BaseAgent):
    """Penjaga disiplin dan mental state — HALT jika ada indikasi bias psikologis."""

    agent_id = 8
    agent_name = "psychology_discipline"
    domain = "psychology"
    role = "psychology-gate"

    async def _evaluate(self, candidate: TradeCandidate) -> AgentReport:
        ctx = candidate.raw_context
        details: dict[str, Any] = {}
        halt_triggers: list[str] = []
        warnings: list[str] = []

        # ── State emosi ────────────────────────────────────────────────────
        emotional_state = str(ctx.get("emotional_state", "NEUTRAL")).upper()
        details["emotional_state"] = emotional_state
        dangerous_states = {"ANGRY", "EUPHORIC", "DESPERATE", "FEARFUL", "OVERCONFIDENT"}
        if emotional_state in dangerous_states:
            halt_triggers.append(
                f"Emotional state berbahaya: {emotional_state} — trading tidak boleh dilanjutkan"
            )

        # ── Daily loss check ──────────────────────────────────────────────
        daily_loss_pct = float(ctx.get("daily_loss_pct", 0.0))
        details["daily_loss_pct"] = daily_loss_pct
        details["max_daily_loss_pct"] = MAX_DAILY_LOSS_PCT
        if daily_loss_pct >= MAX_DAILY_LOSS_PCT:
            halt_triggers.append(
                f"Daily loss limit tercapai: {daily_loss_pct:.1f}% >= {MAX_DAILY_LOSS_PCT}%"
            )

        # ── Consecutive losses ────────────────────────────────────────────
        consecutive_losses = int(ctx.get("consecutive_losses", 0))
        details["consecutive_losses"] = consecutive_losses
        details["max_consecutive_losses"] = MAX_CONSECUTIVE_LOSSES
        if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            halt_triggers.append(
                f"{consecutive_losses} loss berturut-turut — mandatory review sebelum trade berikutnya"
            )

        # ── Anti-revenge trading ──────────────────────────────────────────
        is_revenge_trade = ctx.get("is_revenge_trade", False)
        details["is_revenge_trade"] = is_revenge_trade
        if is_revenge_trade:
            halt_triggers.append(
                "Revenge trade terdeteksi — masuk setelah loss tanpa setup valid"
            )

        # ── Anti-FOMO ─────────────────────────────────────────────────────
        is_fomo = ctx.get("is_fomo_trade", False)
        details["is_fomo_trade"] = is_fomo
        if is_fomo:
            halt_triggers.append(
                "FOMO trade terdeteksi — masuk karena takut ketinggalan bukan karena setup"
            )

        # ── Daily trade count ─────────────────────────────────────────────
        daily_trades = int(ctx.get("daily_trades_count", 0))
        details["daily_trades_count"] = daily_trades
        details["max_daily_trades"] = MAX_DAILY_TRADES
        if daily_trades >= MAX_DAILY_TRADES:
            halt_triggers.append(
                f"Batas trade harian tercapai: {daily_trades}/{MAX_DAILY_TRADES}"
            )

        # ── Overconfidence ────────────────────────────────────────────────
        win_streak = int(ctx.get("consecutive_wins", 0))
        details["consecutive_wins"] = win_streak
        if win_streak >= 5:
            warnings.append(
                f"Win streak {win_streak} — waspadai overconfidence dan position sizing meningkat"
            )
        if win_streak >= 7:
            halt_triggers.append(
                f"Win streak {win_streak} — high overconfidence risk, mandatory review"
            )

        # ── System readiness ──────────────────────────────────────────────
        system_ready = ctx.get("system_ready", True)
        if not system_ready:
            halt_triggers.append("System tidak dalam kondisi ready — cek koneksi dan environment")

        # ── Determine state ───────────────────────────────────────────────
        if halt_triggers:
            details["state"] = "HALT"
            return self.halt_report(
                candidate,
                reason=f"Psychology HALT: {' | '.join(halt_triggers)}",
                details=details,
            )

        if warnings:
            details["state"] = "CAUTION"
        else:
            details["state"] = "READY"

        return self.pass_report(
            candidate,
            reason=f"Psychology state {details['state']} — disiplin terjaga",
            score=100.0 if not warnings else 80.0,
            details=details,
            warnings=warnings,
        )
