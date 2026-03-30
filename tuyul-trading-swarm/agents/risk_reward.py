"""Agent 5: Risk-Reward — validasi matematika dan position sizing.

Hard rules:
  - Minimum RR: 1:2.0
  - Maximum pip risk: 50 pip (default, configurable)
  - Maximum account risk: 1% per trade
  - Lot sizing harus proporsional
"""
from __future__ import annotations

import os
from typing import Any

from schemas.agent_report import AgentReport
from schemas.trade_candidate import TradeCandidate
from agents.base_agent import BaseAgent


MIN_RR = float(os.getenv("MIN_RR_RATIO", "2.0"))
MAX_PIP_RISK = float(os.getenv("MAX_PIP_RISK", "50.0"))
MAX_ACCOUNT_RISK_PCT = float(os.getenv("MAX_ACCOUNT_RISK_PCT", "1.0"))
DEFAULT_ACCOUNT_BALANCE = float(os.getenv("DEFAULT_ACCOUNT_BALANCE", "100000"))
PIP_VALUE_PER_LOT = float(os.getenv("PIP_VALUE_PER_LOT", "10.0"))  # USD per pip per lot


class RiskRewardAgent(BaseAgent):
    """Validasi RR ratio, pip risk, dan lot sizing — hard gate matematika."""

    agent_id = 5
    agent_name = "risk_reward"
    domain = "risk"
    role = "risk-gate"

    async def _evaluate(self, candidate: TradeCandidate) -> AgentReport:
        disqualifiers: list[str] = []
        warnings: list[str] = []
        details: dict[str, Any] = {}

        pip_risk = candidate.pip_risk()
        pip_reward = candidate.pip_reward()
        rr = candidate.rr_ratio()

        details["pip_risk"] = round(pip_risk, 1)
        details["pip_reward"] = round(pip_reward, 1)
        details["rr_ratio"] = f"1:{rr}"
        details["min_rr"] = MIN_RR

        # ── RR check ─────────────────────────────────────────────────────
        if rr < MIN_RR:
            disqualifiers.append(
                f"RR 1:{rr} di bawah minimum 1:{MIN_RR}"
            )

        # ── Pip risk check ────────────────────────────────────────────────
        if pip_risk > MAX_PIP_RISK:
            disqualifiers.append(
                f"Pip risk {pip_risk:.1f} melebihi maximum {MAX_PIP_RISK} pip"
            )
        details["max_pip_risk"] = MAX_PIP_RISK

        # ── Account risk dan lot sizing ───────────────────────────────────
        account_balance = float(
            candidate.raw_context.get("account_balance", DEFAULT_ACCOUNT_BALANCE)
        )
        max_risk_usd = account_balance * (MAX_ACCOUNT_RISK_PCT / 100)

        if pip_risk > 0:
            max_lot = max_risk_usd / (pip_risk * PIP_VALUE_PER_LOT)
            max_lot = round(max_lot, 2)
        else:
            max_lot = 0.0
            disqualifiers.append("Pip risk = 0 — SL tidak valid")

        details["account_balance"] = account_balance
        details["max_risk_usd"] = round(max_risk_usd, 2)
        details["max_lot_size"] = max_lot
        details["lot_size"] = max_lot

        # ── Cek lot dari candidate ────────────────────────────────────────
        if candidate.lot_size and candidate.lot_size > max_lot * 1.05:
            disqualifiers.append(
                f"Lot {candidate.lot_size} melebihi batas aman {max_lot} "
                f"(risk {MAX_ACCOUNT_RISK_PCT}% dari balance {account_balance})"
            )

        # ── Pip reward minimum ────────────────────────────────────────────
        if pip_reward < 20:
            warnings.append(f"Target reward kecil: {pip_reward:.1f} pip")

        # ── SL/TP arah konsisten ──────────────────────────────────────────
        from schemas.trade_candidate import Direction
        dir_val = candidate.direction if isinstance(candidate.direction, str) else candidate.direction.value
        if dir_val == Direction.LONG:
            if candidate.stop_loss >= candidate.entry_price:
                disqualifiers.append("LONG: SL harus di bawah entry")
            if candidate.take_profit <= candidate.entry_price:
                disqualifiers.append("LONG: TP harus di atas entry")
        else:
            if candidate.stop_loss <= candidate.entry_price:
                disqualifiers.append("SHORT: SL harus di atas entry")
            if candidate.take_profit >= candidate.entry_price:
                disqualifiers.append("SHORT: TP harus di bawah entry")

        if disqualifiers:
            return self.fail_report(
                candidate,
                reason=f"RR/Risk check gagal: {'; '.join(disqualifiers)}",
                disqualifiers=disqualifiers,
                details=details,
            )

        return self.pass_report(
            candidate,
            reason=f"RR 1:{rr} ✓ | Pip risk {pip_risk:.1f} ✓ | Lot max {max_lot} ✓",
            score=min(100.0, rr * 40),
            details=details,
            warnings=warnings,
        )
