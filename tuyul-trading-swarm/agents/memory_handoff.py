"""Agent 12: Memory & Handoff — persistent memory dan shift handoff continuity.

Menjaga:
  - Shared memory di semua agent
  - Handoff summary antar shift
  - Watchlist aktif
  - Pending confirmations
  - Upcoming event risks
  - Audit flags
  - Psychology warnings
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from core.memory_fabric import get_memory_fabric
from core.shift_manager import get_shift_manager
from schemas.agent_report import AgentReport
from schemas.trade_candidate import TradeCandidate
from agents.base_agent import BaseAgent


class MemoryHandoffAgent(BaseAgent):
    """Kelola shared memory dan pastikan continuity antar shift."""

    agent_id = 12
    agent_name = "memory_handoff"
    domain = "infrastructure"
    role = "memory-handoff"

    async def _evaluate(self, candidate: TradeCandidate) -> AgentReport:
        """Memory agent selalu PASS — tidak ada gate logic."""
        details: dict[str, Any] = {
            "candidate_id": candidate.candidate_id,
            "memory_updated": True,
        }
        return self.pass_report(
            candidate,
            reason="Memory fabric updated untuk candidate ini",
            score=100.0,
            details=details,
        )

    async def produce_handoff_summary(self) -> dict[str, Any]:
        """Produksi handoff summary untuk shift berikutnya."""
        memory = get_memory_fabric()
        shift_mgr = get_shift_manager()

        watchlist = await memory.get_all_watchlist()
        open_trades = await memory.get_open_trades()
        psych_warnings = await memory.get_psychology_warnings(5)
        audit_flags = await memory.get_audit_flags(5)
        upcoming_events = await memory.get_upcoming_events()
        decisions_today = await memory.get_decisions_today()

        execute_today = sum(1 for d in decisions_today if d.get("final_verdict") == "EXECUTE")
        skip_today = sum(1 for d in decisions_today if d.get("final_verdict") == "SKIP")
        halt_today = sum(1 for d in decisions_today if d.get("final_verdict") == "HALT")

        summary: dict[str, Any] = {
            "handoff_id": shift_mgr.shift_id(),
            "handoff_time": datetime.utcnow().isoformat(),
            "outgoing_shift": shift_mgr.active_shift().value,
            "shift_status": shift_mgr.status_summary(),
            # Active watchlist
            "active_watchlist": watchlist,
            "watchlist_count": len(watchlist),
            # Open trades
            "open_trades": open_trades,
            "open_trades_count": len(open_trades),
            # Psychology / discipline
            "psychology_warnings": psych_warnings,
            "psychology_warning_count": len(psych_warnings),
            # Audit
            "recent_audit_flags": audit_flags,
            "audit_flag_count": len(audit_flags),
            # Upcoming events
            "upcoming_events": upcoming_events[:10],
            "high_impact_events": [
                e for e in upcoming_events if str(e.get("impact", "")).upper() == "HIGH"
            ][:5],
            # Today stats
            "today_decisions": {
                "total": len(decisions_today),
                "execute": execute_today,
                "skip": skip_today,
                "halt": halt_today,
                "watchlist": len(decisions_today) - execute_today - skip_today - halt_today,
            },
            # Handoff notes
            "handoff_notes": self._generate_notes(
                watchlist, psych_warnings, audit_flags, open_trades
            ),
        }

        # Simpan ke memory
        await memory.store_handoff(summary["handoff_id"], summary)
        logger.info(f"[Handoff] Summary produced: {summary['handoff_id']}")
        return summary

    def _generate_notes(
        self,
        watchlist: list,
        psych_warnings: list,
        audit_flags: list,
        open_trades: list,
    ) -> list[str]:
        notes: list[str] = []
        if watchlist:
            notes.append(f"{len(watchlist)} setup dalam watchlist — monitor recheck conditions")
        if psych_warnings:
            notes.append(f"{len(psych_warnings)} psychology warning aktif — monitor mental state")
        if audit_flags:
            notes.append(f"{len(audit_flags)} audit flag perlu perhatian")
        if open_trades:
            notes.append(f"{len(open_trades)} trade sedang berjalan — monitor management")
        if not notes:
            notes.append("Handoff bersih — semua clear untuk shift berikutnya")
        return notes

    async def store_session_context(self, instrument: str, session: str, bias: str) -> None:
        """Update bias instrumen untuk session aktif."""
        memory = get_memory_fabric()
        await memory.set_session_bias(instrument, session, bias)

    async def get_full_context(self) -> dict[str, Any]:
        """Ambil full context dari memory fabric untuk dashboard."""
        memory = get_memory_fabric()
        shift_mgr = get_shift_manager()

        return {
            "shift_status": shift_mgr.status_summary(),
            "watchlist": await memory.get_all_watchlist(),
            "open_trades": await memory.get_open_trades(),
            "psychology_warnings": await memory.get_psychology_warnings(),
            "audit_flags": await memory.get_audit_flags(),
            "upcoming_events": await memory.get_upcoming_events(),
            "decisions_today": await memory.get_decisions_today(),
            "last_handoff": await memory.get_last_handoff(),
        }
