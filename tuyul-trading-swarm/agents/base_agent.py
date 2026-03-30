"""Base Agent — abstract class untuk semua 12 trading agent.

Tuyul Exception v.3 contract:
  - Setiap agent WAJIB mengimplementasikan evaluate()
  - Output HARUS AgentReport
  - Satu disqualifier = FAIL
  - Psychology HALT = HALT absolut
"""
from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from loguru import logger

from schemas.agent_report import AgentReport, GateResult
from schemas.trade_candidate import TradeCandidate


class BaseAgent(ABC):
    """Abstract base untuk semua agent dalam TUYUL Trading Swarm."""

    agent_id: int = 0
    agent_name: str = "base_agent"
    domain: str = "base"
    role: str = "gate"
    min_pass_score: float = 0.0  # Override di subclass

    async def evaluate(self, candidate: TradeCandidate) -> AgentReport:
        """Entry point evaluasi — wrapper dengan timing dan logging."""
        start_ms = time.monotonic() * 1000
        logger.debug(f"[{self.agent_name}] Evaluating {candidate.candidate_id} ({candidate.instrument})")

        try:
            report = await self._evaluate(candidate)
            report.evaluation_ms = (time.monotonic() * 1000) - start_ms
            logger.debug(
                f"[{self.agent_name}] Result: {report.gate_result} "
                f"({report.evaluation_ms:.1f}ms)"
            )
            return report
        except Exception as exc:
            logger.error(f"[{self.agent_name}] Evaluation error: {exc}")
            return self._error_report(candidate, str(exc), start_ms)

    @abstractmethod
    async def _evaluate(self, candidate: TradeCandidate) -> AgentReport:
        """Implementasi evaluasi spesifik — override di setiap agent."""
        ...

    def pass_report(
        self,
        candidate: TradeCandidate,
        reason: str,
        score: float | None = None,
        confidence: float | None = None,
        details: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> AgentReport:
        """Helper: buat report PASS."""
        return AgentReport(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            candidate_id=candidate.candidate_id,
            gate_result=GateResult.PASS,
            score=score,
            confidence=confidence,
            reason=reason,
            details=details or {},
            warnings=warnings or [],
        )

    def fail_report(
        self,
        candidate: TradeCandidate,
        reason: str,
        disqualifiers: list[str],
        score: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> AgentReport:
        """Helper: buat report FAIL."""
        return AgentReport(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            candidate_id=candidate.candidate_id,
            gate_result=GateResult.FAIL,
            score=score,
            reason=reason,
            disqualifiers=disqualifiers,
            details=details or {},
        )

    def halt_report(
        self,
        candidate: TradeCandidate,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> AgentReport:
        """Helper: buat report HALT (absolute override)."""
        return AgentReport(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            candidate_id=candidate.candidate_id,
            gate_result=GateResult.HALT,
            reason=f"HALT: {reason}",
            details=details or {},
        )

    def caution_report(
        self,
        candidate: TradeCandidate,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> AgentReport:
        """Helper: buat report CAUTION (→ WATCHLIST)."""
        return AgentReport(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            candidate_id=candidate.candidate_id,
            gate_result=GateResult.CAUTION,
            reason=reason,
            details=details or {},
        )

    def _error_report(
        self,
        candidate: TradeCandidate,
        error_msg: str,
        start_ms: float,
    ) -> AgentReport:
        """Fallback report saat agent error — selalu FAIL untuk safety."""
        return AgentReport(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            candidate_id=candidate.candidate_id,
            gate_result=GateResult.FAIL,
            reason=f"Agent error — auto-FAIL for safety: {error_msg}",
            disqualifiers=["agent_runtime_error"],
            evaluation_ms=(time.monotonic() * 1000) - start_ms,
        )

    def status(self) -> dict[str, Any]:
        """Status snapshot agent ini."""
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "domain": self.domain,
            "role": self.role,
            "min_pass_score": self.min_pass_score,
            "status": "active",
        }
