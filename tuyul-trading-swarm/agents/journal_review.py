"""Agent 10: Journal & Review — log semua keputusan untuk audit dan learning.

Logs: EXECUTE, SKIP, HALT, WATCHLIST decisions
Records: reason, context, confidence, lesson points
Produces: daily dan weekly review artifacts
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from loguru import logger

from core.memory_fabric import get_memory_fabric
from schemas.agent_report import AgentReport
from schemas.decision_packet import DecisionPacket
from schemas.trade_candidate import TradeCandidate
from agents.base_agent import BaseAgent

JOURNAL_DIR = os.getenv("JOURNAL_DIR", "./storage/journal")


class JournalReviewAgent(BaseAgent):
    """Catat semua keputusan trading ke journal untuk review dan pembelajaran."""

    agent_id = 10
    agent_name = "journal_review"
    domain = "review"
    role = "journal"

    async def _evaluate(self, candidate: TradeCandidate) -> AgentReport:
        """Agent ini selalu PASS — tugasnya log, bukan gate."""
        details: dict[str, Any] = {
            "journal_written": False,
            "candidate_id": candidate.candidate_id,
        }

        try:
            await self._write_journal(candidate)
            details["journal_written"] = True
            details["journal_time"] = datetime.utcnow().isoformat()
        except Exception as e:
            logger.error(f"[Journal] Write error: {e}")
            details["journal_error"] = str(e)

        return self.pass_report(
            candidate,
            reason="Journal entry ditulis",
            score=100.0,
            details=details,
        )

    async def log_decision(self, packet: DecisionPacket) -> None:
        """Log full decision packet ke memory fabric dan file."""
        memory = get_memory_fabric()
        data = packet.dict()
        # Convert datetime ke string
        for key, val in data.items():
            if isinstance(val, datetime):
                data[key] = val.isoformat()

        await memory.store_decision(data)

        # Record rejection reason untuk learning
        if packet.final_verdict in ("SKIP", "HALT"):
            for disq in packet.disqualifiers:
                await memory.record_rejection_reason(packet.instrument, disq)

        logger.info(
            f"[Journal] Decision logged: {packet.packet_id} "
            f"| {packet.instrument} {packet.direction} "
            f"| Verdict: {packet.final_verdict}"
        )

        # Write ke file journal
        await self._write_decision_to_file(packet)

    async def _write_journal(self, candidate: TradeCandidate) -> None:
        """Write candidate entry ke memory."""
        memory = get_memory_fabric()
        entry = {
            "candidate_id": candidate.candidate_id,
            "instrument": candidate.instrument,
            "direction": candidate.direction if isinstance(candidate.direction, str) else candidate.direction.value,
            "submitted_at": candidate.submitted_at.isoformat(),
            "notes": candidate.notes,
        }
        await memory.store_decision({**entry, "packet_id": f"cand_{candidate.candidate_id}", "final_verdict": "PENDING"})

    async def _write_decision_to_file(self, packet: DecisionPacket) -> None:
        """Append decision ke file journal harian."""
        os.makedirs(JOURNAL_DIR, exist_ok=True)
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        file_path = os.path.join(JOURNAL_DIR, f"journal_{date_str}.jsonl")

        entry = {
            "packet_id": packet.packet_id,
            "candidate_id": packet.candidate_id,
            "instrument": packet.instrument,
            "direction": packet.direction,
            "session": packet.session,
            "final_verdict": packet.final_verdict,
            "decision_reason": packet.decision_reason,
            "technical_score": packet.technical_score,
            "smart_money_confidence": packet.smart_money_confidence,
            "rr_ratio": packet.rr_ratio,
            "news_risk": packet.news_risk,
            "discipline_state": packet.discipline_state,
            "failed_gates": packet.failed_gates,
            "disqualifiers": packet.disqualifiers,
            "decided_at": packet.decided_at.isoformat() if isinstance(packet.decided_at, datetime) else str(packet.decided_at),
            "cycle_ms": packet.cycle_ms,
        }

        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    async def get_daily_summary(self, date_str: str | None = None) -> dict[str, Any]:
        """Buat ringkasan keputusan harian."""
        memory = get_memory_fabric()
        if date_str:
            decisions = await memory.get_decisions_by_date(date_str)
        else:
            decisions = await memory.get_decisions_today()

        total = len(decisions)
        execute = sum(1 for d in decisions if d.get("final_verdict") == "EXECUTE")
        skip = sum(1 for d in decisions if d.get("final_verdict") == "SKIP")
        halt = sum(1 for d in decisions if d.get("final_verdict") == "HALT")
        watchlist = sum(1 for d in decisions if d.get("final_verdict") == "WATCHLIST")

        return {
            "date": date_str or datetime.utcnow().strftime("%Y-%m-%d"),
            "total_candidates": total,
            "execute": execute,
            "skip": skip,
            "halt": halt,
            "watchlist": watchlist,
            "skip_rate_pct": round((skip / total * 100) if total > 0 else 0, 1),
            "execute_rate_pct": round((execute / total * 100) if total > 0 else 0, 1),
            "decisions": decisions,
        }
