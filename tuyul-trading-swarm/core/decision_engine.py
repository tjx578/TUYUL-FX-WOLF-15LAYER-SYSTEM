"""Decision Engine — gate aggregator utama untuk semua evaluasi trade candidate.

Tuyul Exception v.3 Rule:
  - Semua mandatory gate HARUS lulus
  - Satu disqualifier cukup untuk SKIP
  - HALT dari psychology agent override semua gate
  - Tidak ada upgrade via storytelling
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime
from typing import Optional

from loguru import logger

from schemas.agent_report import AgentReport, GateResult
from schemas.decision_packet import DecisionPacket, ExecutionPacket, WatchlistEntry
from schemas.trade_candidate import FinalVerdict, TradeCandidate


MANDATORY_GATES = [
    "technical_structure",
    "smart_money",
    "risk_reward",
    "market_condition",
    "news_event_risk",
    "psychology_discipline",
]

HALT_AGENTS = ["psychology_discipline"]  # agent yang bisa trigger absolute HALT


class DecisionEngine:
    """Aggregator laporan agent → keputusan final (EXECUTE/SKIP/HALT/WATCHLIST)."""

    def aggregate(
        self,
        candidate: TradeCandidate,
        reports: list[AgentReport],
        shift_id: str = "",
    ) -> DecisionPacket:
        """Agregasi semua laporan agent menjadi satu DecisionPacket."""
        start_ms = time.monotonic() * 1000

        # ── Cek HALT absolute ──────────────────────────────────────────────
        halt_reports = [r for r in reports if r.is_halt]
        if halt_reports:
            halt_reason = " | ".join(r.reason for r in halt_reports)
            logger.critical(f"[DecisionEngine] HALT triggered: {halt_reason}")
            return self._build_packet(
                candidate=candidate,
                reports=reports,
                verdict=FinalVerdict.HALT,
                reason=f"HALT ABSOLUTE: {halt_reason}",
                shift_id=shift_id,
                start_ms=start_ms,
            )

        # ── Kumpulkan disqualifier ─────────────────────────────────────────
        failed_gates: list[str] = []
        all_disqualifiers: list[str] = []

        for report in reports:
            if report.agent_name in MANDATORY_GATES and not report.is_pass:
                failed_gates.append(report.agent_name)
                all_disqualifiers.extend(report.disqualifiers)

        if failed_gates:
            reason = f"Gate gagal: {', '.join(failed_gates)}"
            if all_disqualifiers:
                reason += f" | Disqualifier: {'; '.join(all_disqualifiers)}"
            logger.warning(f"[DecisionEngine] SKIP: {reason}")
            return self._build_packet(
                candidate=candidate,
                reports=reports,
                verdict=FinalVerdict.SKIP,
                reason=reason,
                failed_gates=failed_gates,
                disqualifiers=all_disqualifiers,
                shift_id=shift_id,
                start_ms=start_ms,
            )

        # ── Cek caution/incomplete ─────────────────────────────────────────
        caution_reports = [r for r in reports if r.gate_result == GateResult.CAUTION]
        if caution_reports:
            caution_reasons = " | ".join(r.reason for r in caution_reports)
            logger.info(f"[DecisionEngine] WATCHLIST: {caution_reasons}")
            watchlist_entry = self._build_watchlist(candidate, caution_reasons)
            return self._build_packet(
                candidate=candidate,
                reports=reports,
                verdict=FinalVerdict.WATCHLIST,
                reason=f"Setup belum matang: {caution_reasons}",
                watchlist_entry=watchlist_entry,
                shift_id=shift_id,
                start_ms=start_ms,
            )

        # ── Semua gate lulus → EXECUTE ────────────────────────────────────
        exec_packet = self._build_execution_packet(candidate, reports)
        logger.success(f"[DecisionEngine] EXECUTE: {candidate.instrument} {candidate.direction}")
        return self._build_packet(
            candidate=candidate,
            reports=reports,
            verdict=FinalVerdict.EXECUTE,
            reason="Semua mandatory gate lulus — setup exceptional quality",
            execution_packet=exec_packet,
            shift_id=shift_id,
            start_ms=start_ms,
        )

    def _build_packet(
        self,
        candidate: TradeCandidate,
        reports: list[AgentReport],
        verdict: FinalVerdict,
        reason: str,
        failed_gates: Optional[list[str]] = None,
        disqualifiers: Optional[list[str]] = None,
        watchlist_entry: Optional[WatchlistEntry] = None,
        execution_packet: Optional[ExecutionPacket] = None,
        shift_id: str = "",
        start_ms: float = 0.0,
    ) -> DecisionPacket:
        """Bangun DecisionPacket dari komponen evaluasi."""
        cycle_ms = (time.monotonic() * 1000) - start_ms

        # Extract scores dari reports
        tech_report = next((r for r in reports if r.agent_name == "technical_structure"), None)
        sm_report = next((r for r in reports if r.agent_name == "smart_money"), None)
        rr_report = next((r for r in reports if r.agent_name == "risk_reward"), None)
        news_report = next((r for r in reports if r.agent_name == "news_event_risk"), None)
        psych_report = next((r for r in reports if r.agent_name == "psychology_discipline"), None)

        tech_score = tech_report.details.get("twms_score", "N/A") if tech_report else "N/A"
        sm_conf = f"{sm_report.confidence:.0f}%" if sm_report and sm_report.confidence else "N/A"
        rr_str = rr_report.details.get("rr_ratio", f"1:{candidate.rr_ratio()}") if rr_report else f"1:{candidate.rr_ratio()}"
        news_risk = news_report.details.get("risk_level", "N/A") if news_report else "N/A"
        psych_state = psych_report.details.get("state", "N/A") if psych_report else "N/A"

        market_report = next((r for r in reports if r.agent_name == "market_condition"), None)
        market_state = market_report.details.get("market_state", "UNKNOWN") if market_report else "UNKNOWN"

        return DecisionPacket(
            packet_id=str(uuid.uuid4()),
            candidate_id=candidate.candidate_id,
            instrument=candidate.instrument,
            direction=candidate.direction if isinstance(candidate.direction, str) else candidate.direction.value,
            session=candidate.session if isinstance(candidate.session, str) else candidate.session.value,
            market_state=market_state,
            technical_score=tech_score,
            smart_money_confidence=sm_conf,
            rr_ratio=str(rr_str),
            news_risk=news_risk,
            discipline_state=psych_state,
            final_verdict=verdict,
            decision_reason=reason,
            next_action=self._derive_next_action(verdict, candidate),
            audit_note=f"Cycle: {cycle_ms:.1f}ms | Gates checked: {len(reports)}",
            journal_summary=self._build_journal_summary(candidate, verdict, reason),
            agent_reports=reports,
            failed_gates=failed_gates or [],
            disqualifiers=disqualifiers or [],
            watchlist_entry=watchlist_entry,
            execution_packet=execution_packet,
            shift=shift_id,
            cycle_ms=cycle_ms,
        )

    def _derive_next_action(self, verdict: FinalVerdict, candidate: TradeCandidate) -> str:
        if verdict == FinalVerdict.EXECUTE:
            return f"Kirim execution packet untuk {candidate.instrument} ke broker"
        if verdict == FinalVerdict.WATCHLIST:
            return f"Monitor {candidate.instrument} sampai kondisi recheck terpenuhi"
        if verdict == FinalVerdict.HALT:
            return "Hentikan semua aktivitas trading — tunggu psychology reset"
        return f"Skip {candidate.instrument} — cari setup lebih baik"

    def _build_watchlist(self, candidate: TradeCandidate, caution_reason: str) -> WatchlistEntry:
        from datetime import timedelta
        return WatchlistEntry(
            candidate_id=candidate.candidate_id,
            instrument=candidate.instrument,
            direction=candidate.direction if isinstance(candidate.direction, str) else candidate.direction.value,
            wait_reason=caution_reason,
            invalidation_trigger="Harga menembus invalidation level atau setup struktur rusak",
            recheck_condition="Semua gate menunjukkan sinyal PASS",
            expiration_condition="Setup tidak matang dalam 4 jam atau news high-impact muncul",
            next_review_time=datetime.utcnow() + timedelta(hours=1),
        )

    def _build_execution_packet(self, candidate: TradeCandidate, reports: list[AgentReport]) -> ExecutionPacket:
        """Build execution-ready packet — hanya dipanggil jika semua gate lulus."""
        rr_report = next((r for r in reports if r.agent_name == "risk_reward"), None)
        lot = rr_report.details.get("lot_size", candidate.lot_size or 0.01) if rr_report else (candidate.lot_size or 0.01)

        return ExecutionPacket(
            candidate_id=candidate.candidate_id,
            instrument=candidate.instrument,
            direction=candidate.direction if isinstance(candidate.direction, str) else candidate.direction.value,
            entry_price=candidate.entry_price,
            stop_loss=candidate.stop_loss,
            take_profit=candidate.take_profit,
            lot_size=float(lot),
            pip_risk=candidate.pip_risk(),
            pip_reward=candidate.pip_reward(),
            rr_ratio=candidate.rr_ratio(),
            session=candidate.session if isinstance(candidate.session, str) else candidate.session.value,
            execution_note="Approved by full agent consensus — Tuyul Exception v.3",
        )

    def _build_journal_summary(self, candidate: TradeCandidate, verdict: FinalVerdict, reason: str) -> str:
        v = verdict.value if hasattr(verdict, "value") else str(verdict)
        return (
            f"[{v}] {candidate.instrument} {candidate.direction} @ {candidate.entry_price} "
            f"| SL:{candidate.stop_loss} TP:{candidate.take_profit} "
            f"| RR:1:{candidate.rr_ratio()} | {reason}"
        )
