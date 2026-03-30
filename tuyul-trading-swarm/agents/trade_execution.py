"""Agent 9: Trade Execution Control — persiapkan execution packet setelah full approval.

Rules:
  - Hanya dijalankan setelah semua gate PASS
  - Tidak boleh reinterpret kondisi yang gagal
  - Konfirmasi semua parameter order sebelum emit
  - Enforce no-bypass rule
"""
from __future__ import annotations

from typing import Any

from schemas.agent_report import AgentReport
from schemas.trade_candidate import TradeCandidate
from agents.base_agent import BaseAgent


class TradeExecutionAgent(BaseAgent):
    """Persiapkan dan validasi execution packet — hanya setelah full approval."""

    agent_id = 9
    agent_name = "trade_execution"
    domain = "execution"
    role = "execution-control"

    async def _evaluate(self, candidate: TradeCandidate) -> AgentReport:
        """
        NOTE: Agent ini hanya dipanggil oleh orchestrator setelah semua gate lulus.
        Tugasnya adalah final pre-flight check dan konfirmasi parameter.
        """
        ctx = candidate.raw_context
        details: dict[str, Any] = {}
        disqualifiers: list[str] = []
        warnings: list[str] = []

        # ── Konfirmasi approval flag dari orchestrator ─────────────────────
        orchestrator_approved = ctx.get("orchestrator_approved", False)
        details["orchestrator_approved"] = orchestrator_approved

        if not orchestrator_approved:
            disqualifiers.append(
                "Execution agent dipanggil tanpa approval orchestrator — protokol bypass terdeteksi"
            )
            return self.fail_report(
                candidate,
                reason="NO-BYPASS VIOLATION: Execution tanpa orchestrator approval",
                disqualifiers=disqualifiers,
                details=details,
            )

        # ── Parameter validation ───────────────────────────────────────────
        if candidate.entry_price <= 0:
            disqualifiers.append("Entry price tidak valid")
        if candidate.stop_loss <= 0:
            disqualifiers.append("Stop loss tidak valid")
        if candidate.take_profit <= 0:
            disqualifiers.append("Take profit tidak valid")
        if candidate.lot_size is not None and candidate.lot_size < 0.01:
            disqualifiers.append(f"Lot size {candidate.lot_size} terlalu kecil (min 0.01)")

        details["entry_price"] = candidate.entry_price
        details["stop_loss"] = candidate.stop_loss
        details["take_profit"] = candidate.take_profit
        details["lot_size"] = candidate.lot_size
        details["pip_risk"] = round(candidate.pip_risk(), 1)
        details["pip_reward"] = round(candidate.pip_reward(), 1)
        details["rr_ratio"] = f"1:{candidate.rr_ratio()}"

        # ── Slippage tolerance ────────────────────────────────────────────
        max_slippage_pips = float(ctx.get("max_slippage_pips", 3.0))
        details["max_slippage_pips"] = max_slippage_pips

        if disqualifiers:
            return self.fail_report(
                candidate,
                reason=f"Pre-flight check gagal: {'; '.join(disqualifiers)}",
                disqualifiers=disqualifiers,
                details=details,
            )

        # ── Execution packet ready ────────────────────────────────────────
        details["execution_ready"] = True
        details["order_type"] = ctx.get("order_type", "LIMIT")
        details["execution_mode"] = ctx.get("execution_mode", "paper")

        return self.pass_report(
            candidate,
            reason=f"Execution packet siap — {candidate.instrument} {candidate.direction} @ {candidate.entry_price}",
            score=100.0,
            details=details,
            warnings=warnings,
        )
