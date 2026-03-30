"""Agent 11: Audit & Governance — integritas aturan dan deteksi protocol drift.

Tugas:
  - Audit semua executed trades untuk kepatuhan
  - Deteksi score inflation / narrative bias
  - Catat rule breaches
  - Rekomendasikan tightening filter jika ada pola pelanggaran
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from core.memory_fabric import get_memory_fabric
from schemas.agent_report import AgentReport
from schemas.decision_packet import DecisionPacket
from schemas.trade_candidate import TradeCandidate
from agents.base_agent import BaseAgent


class AuditGovernanceAgent(BaseAgent):
    """Audit kepatuhan keputusan dan deteksi protocol drift."""

    agent_id = 11
    agent_name = "audit_governance"
    domain = "governance"
    role = "audit"

    async def _evaluate(self, candidate: TradeCandidate) -> AgentReport:
        """Audit pre-evaluation — cek anomali sebelum evaluate dimulai."""
        details: dict[str, Any] = {
            "candidate_id": candidate.candidate_id,
            "audit_type": "pre_evaluation",
        }

        # Audit selalu PASS di pre-eval — full audit dilakukan post-decision
        return self.pass_report(
            candidate,
            reason="Pre-evaluation audit OK — full audit dilakukan setelah decision",
            score=100.0,
            details=details,
        )

    async def audit_decision(self, packet: DecisionPacket) -> dict[str, Any]:
        """Full post-decision audit — dipanggil oleh orchestrator setelah decision."""
        memory = get_memory_fabric()
        audit_result: dict[str, Any] = {
            "packet_id": packet.packet_id,
            "candidate_id": packet.candidate_id,
            "audit_time": datetime.utcnow().isoformat(),
            "violations": [],
            "warnings": [],
            "integrity_score": 100.0,
            "recommendation": "OK",
        }

        # ── Check 1: EXECUTE tanpa complete reports ────────────────────────
        if packet.final_verdict == "EXECUTE":
            expected_gates = {"technical_structure", "smart_money", "risk_reward",
                              "market_condition", "news_event_risk", "psychology_discipline"}
            reported_agents = {r.agent_name for r in packet.agent_reports}
            missing_gates = expected_gates - reported_agents

            if missing_gates:
                audit_result["violations"].append(
                    f"EXECUTE dilakukan dengan gate tidak lengkap: {missing_gates}"
                )
                audit_result["integrity_score"] -= 30.0

        # ── Check 2: EXECUTE dengan disqualifier tercatat ─────────────────
        if packet.final_verdict == "EXECUTE" and packet.disqualifiers:
            audit_result["violations"].append(
                f"EXECUTE dengan disqualifier tercatat: {packet.disqualifiers}"
            )
            audit_result["integrity_score"] -= 50.0

        # ── Check 3: SKIP/HALT tanpa alasan jelas ─────────────────────────
        if packet.final_verdict in ("SKIP", "HALT") and not packet.decision_reason:
            audit_result["violations"].append("SKIP/HALT tanpa decision_reason — logging incomplete")
            audit_result["integrity_score"] -= 20.0

        # ── Check 4: Journal harus ada ────────────────────────────────────
        if not packet.journal_summary:
            audit_result["warnings"].append("Journal summary kosong — review quality berkurang")
            audit_result["integrity_score"] -= 5.0

        # ── Check 5: Cycle time anomaly ────────────────────────────────────
        if packet.cycle_ms and packet.cycle_ms > 30000:
            audit_result["warnings"].append(
                f"Evaluation cycle sangat lambat: {packet.cycle_ms:.0f}ms"
            )

        # ── Determine recommendation ───────────────────────────────────────
        if audit_result["integrity_score"] < 50:
            audit_result["recommendation"] = "CRITICAL_BREACH — tightening required"
            logger.critical(f"[Audit] CRITICAL breach: {packet.packet_id}")
        elif audit_result["integrity_score"] < 80:
            audit_result["recommendation"] = "PROTOCOL_DRIFT — review required"
            logger.warning(f"[Audit] Protocol drift: {packet.packet_id}")
        else:
            audit_result["recommendation"] = "OK"

        # ── Store audit flag jika ada violation ───────────────────────────
        if audit_result["violations"]:
            await memory.add_audit_flag({
                **audit_result,
                "instrument": packet.instrument,
                "verdict": packet.final_verdict,
            })

        logger.info(
            f"[Audit] {packet.packet_id} | Score: {audit_result['integrity_score']:.0f} "
            f"| Violations: {len(audit_result['violations'])}"
        )
        return audit_result

    async def get_governance_report(self) -> dict[str, Any]:
        """Ringkasan governance — audit flags dan rekomendasi."""
        memory = get_memory_fabric()
        flags = await memory.get_audit_flags(50)

        violations_total = sum(len(f.get("violations", [])) for f in flags)
        critical_count = sum(1 for f in flags if "CRITICAL" in f.get("recommendation", ""))

        return {
            "total_audits": len(flags),
            "total_violations": violations_total,
            "critical_breaches": critical_count,
            "avg_integrity_score": (
                sum(f.get("integrity_score", 100) for f in flags) / len(flags)
                if flags else 100.0
            ),
            "recent_flags": flags[:10],
            "recommendation": (
                "TIGHTEN_FILTERS" if critical_count > 2
                else "MONITOR" if violations_total > 5
                else "OK"
            ),
        }
