"""Agent 1: Trading Orchestrator — koordinator pusat seluruh swarm.

Alur:
  1. Terima trade candidate
  2. Jalankan pre-qualification (market scanner, news, market condition) secara parallel
  3. Jalankan deep validation (technical, smart money, RR) secara parallel
  4. Jalankan discipline gate (psychology)
  5. Agregasi semua reports ke DecisionEngine
  6. Eksekusi control (jika EXECUTE)
  7. Journal + Audit setiap keputusan
  8. Update memory fabric
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from loguru import logger

from agents.base_agent import BaseAgent
from agents.market_scanner import MarketScannerAgent
from agents.technical_structure import TechnicalStructureAgent
from agents.smart_money import SmartMoneyAgent
from agents.risk_reward import RiskRewardAgent
from agents.market_condition import MarketConditionAgent
from agents.news_event_risk import NewsEventRiskAgent
from agents.psychology_discipline import PsychologyDisciplineAgent
from agents.trade_execution import TradeExecutionAgent
from agents.journal_review import JournalReviewAgent
from agents.audit_governance import AuditGovernanceAgent
from agents.memory_handoff import MemoryHandoffAgent
from core.decision_engine import DecisionEngine
from core.event_bus import get_event_bus
from core.memory_fabric import get_memory_fabric
from core.shift_manager import get_shift_manager
from schemas.agent_report import AgentReport
from schemas.decision_packet import DecisionPacket
from schemas.trade_candidate import TradeCandidate


class TradingOrchestratorAgent(BaseAgent):
    """Koordinator utama — mengorkestrasi semua 11 agent lainnya."""

    agent_id = 1
    agent_name = "orchestrator"
    domain = "coordination"
    role = "orchestrator"

    def __init__(self) -> None:
        # Instantiate semua agent
        self.market_scanner = MarketScannerAgent()
        self.technical_structure = TechnicalStructureAgent()
        self.smart_money = SmartMoneyAgent()
        self.risk_reward = RiskRewardAgent()
        self.market_condition = MarketConditionAgent()
        self.news_event_risk = NewsEventRiskAgent()
        self.psychology_discipline = PsychologyDisciplineAgent()
        self.trade_execution = TradeExecutionAgent()
        self.journal = JournalReviewAgent()
        self.audit = AuditGovernanceAgent()
        self.memory_handoff = MemoryHandoffAgent()

        self.decision_engine = DecisionEngine()
        self.event_bus = get_event_bus()
        self.memory = get_memory_fabric()
        self.shift_mgr = get_shift_manager()

    async def _evaluate(self, candidate: TradeCandidate) -> AgentReport:
        """BaseAgent contract — tidak digunakan langsung untuk orchestrator."""
        return self.pass_report(candidate, reason="Orchestrator active", score=100.0)

    async def run_full_cycle(self, candidate: TradeCandidate) -> DecisionPacket:
        """Jalankan siklus evaluasi lengkap untuk satu trade candidate."""
        shift_id = self.shift_mgr.shift_id()
        logger.info(
            f"[Orchestrator] ─── Cycle START ───\n"
            f"  Candidate: {candidate.candidate_id}\n"
            f"  Instrument: {candidate.instrument} {candidate.direction}\n"
            f"  Shift: {shift_id}\n"
            f"  Session: {self.shift_mgr.active_session().value}"
        )

        # ── TAHAP 1: Pre-Qualification (parallel) ─────────────────────────
        logger.debug("[Orchestrator] Tahap 1: Pre-qualification")
        pre_qual_reports = await asyncio.gather(
            self.market_scanner.evaluate(candidate),
            self.market_condition.evaluate(candidate),
            self.news_event_risk.evaluate(candidate),
        )

        # Cek apakah ada HALT atau FAIL di pre-qualification
        halt_in_prequal = any(r.is_halt for r in pre_qual_reports)
        fail_in_prequal = any(r.is_fail for r in pre_qual_reports)

        if halt_in_prequal or fail_in_prequal:
            # Skip deep analysis — langsung decision
            logger.warning(
                f"[Orchestrator] Pre-qualification gagal — "
                f"skip deep analysis"
            )
            packet = self.decision_engine.aggregate(
                candidate,
                list(pre_qual_reports),
                shift_id=shift_id,
            )
            await self._post_decision(packet, candidate)
            return packet

        # ── TAHAP 2: Deep Validation (parallel) ────────────────────────────
        logger.debug("[Orchestrator] Tahap 2: Deep validation")
        deep_reports = await asyncio.gather(
            self.technical_structure.evaluate(candidate),
            self.smart_money.evaluate(candidate),
            self.risk_reward.evaluate(candidate),
        )

        # ── TAHAP 3: Psychology Gate ────────────────────────────────────────
        logger.debug("[Orchestrator] Tahap 3: Psychology gate")
        psych_report = await self.psychology_discipline.evaluate(candidate)

        # ── Kumpulkan semua reports ────────────────────────────────────────
        all_reports: list[AgentReport] = [
            *pre_qual_reports,
            *deep_reports,
            psych_report,
        ]

        # ── TAHAP 4: Aggregate decision ────────────────────────────────────
        logger.debug("[Orchestrator] Tahap 4: Aggregate decision")
        packet = self.decision_engine.aggregate(
            candidate,
            all_reports,
            shift_id=shift_id,
        )

        # ── TAHAP 5: Execution (jika EXECUTE) ─────────────────────────────
        if packet.final_verdict == "EXECUTE":
            logger.debug("[Orchestrator] Tahap 5: Execution control")
            # Inject approval flag
            candidate.raw_context["orchestrator_approved"] = True
            exec_report = await self.trade_execution.evaluate(candidate)
            if not exec_report.is_pass:
                # Execution pre-flight gagal — ubah ke SKIP
                from schemas.trade_candidate import FinalVerdict
                packet.final_verdict = FinalVerdict.SKIP
                packet.decision_reason += f" | Execution pre-flight gagal: {exec_report.reason}"
                packet.failed_gates.append("trade_execution")

        # ── TAHAP 6-9: Journal, Audit, Memory ─────────────────────────────
        await self._post_decision(packet, candidate)

        logger.info(
            f"[Orchestrator] ─── Cycle DONE ───\n"
            f"  Verdict: {packet.final_verdict}\n"
            f"  Reason: {packet.decision_reason[:100]}\n"
            f"  Cycle: {packet.cycle_ms:.0f}ms"
        )

        return packet

    async def _post_decision(self, packet: DecisionPacket, candidate: TradeCandidate) -> None:
        """Post-decision: journal, audit, memory update, event publish."""
        try:
            # Journal
            await self.journal.log_decision(packet)

            # Audit
            audit_result = await self.audit.audit_decision(packet)
            packet.audit_note = (
                f"{packet.audit_note} | Audit: {audit_result.get('recommendation', 'OK')}"
            )

            # Memory
            if packet.final_verdict == "WATCHLIST" and packet.watchlist_entry:
                await self.memory.add_watchlist(packet.watchlist_entry.dict())
            if packet.final_verdict == "EXECUTE" and packet.execution_packet:
                await self.memory.set_open_trade(
                    packet.candidate_id,
                    packet.execution_packet.dict(),
                )

            # Psychology warning ke memory
            if packet.discipline_state in ("HALT", "CAUTION"):
                await self.memory.set_psychology_warning(
                    level=packet.discipline_state,
                    reason=packet.decision_reason,
                )

            # Event bus broadcast
            await self.event_bus.publish_decision(packet.dict())

        except Exception as e:
            logger.error(f"[Orchestrator] Post-decision error: {e}")

    async def produce_handoff(self) -> dict[str, Any]:
        """Produksi shift handoff summary."""
        return await self.memory_handoff.produce_handoff_summary()

    def agents_status(self) -> list[dict[str, Any]]:
        """Status semua agent dalam swarm."""
        agents = [
            self, self.market_scanner, self.technical_structure,
            self.smart_money, self.risk_reward, self.market_condition,
            self.news_event_risk, self.psychology_discipline,
            self.trade_execution, self.journal, self.audit, self.memory_handoff,
        ]
        return [a.status() for a in agents]
