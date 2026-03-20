from datetime import UTC, datetime
from typing import Literal


class J2DecisionLogger:
    """
    J2: Decision journal (immutable audit trail).

    Logs ALL Layer-12 verdicts, including rejections.
    """

    def __init__(self, storage):
        self.storage = storage  # Redis/PostgreSQL adapter

    async def log_decision(
        self,
        signal_id: str,
        symbol: str,
        verdict: Literal["EXECUTE", "NO_TRADE", "HOLD", "ABORT"],
        confidence: float,
        reason: str,
        gate_results: dict,
        context: dict | None = None,
    ) -> str:
        """
        Log Layer-12 decision to J2.

        Args:
            signal_id: Unique identifier for this analysis cycle
            verdict: Constitutional decision
            reason: Human-readable explanation
            gate_results: Per-layer pass/fail details
            context: Optional extra metadata (e.g., account_id, timeframe)

        Returns:
            j2_entry_id: Immutable journal entry ID
        """
        entry = {
            "journal_type": "J2_DECISION",
            "signal_id": signal_id,
            "symbol": symbol,
            "timestamp": datetime.now(UTC).isoformat(),
            "verdict": verdict,
            "confidence": confidence,
            "reason": reason,
            "gate_results": gate_results,
            "context": context or {},
        }

        # Append-only write
        j2_id = await self.storage.append("journal:j2", entry)

        # ✅ CRITICAL: Log rejections with same priority as executions
        if verdict in {"NO_TRADE", "ABORT"}:
            await self._emit_rejection_alert(signal_id, symbol, verdict, reason)

        return j2_id

    async def _emit_rejection_alert(
        self,
        signal_id: str,
        symbol: str,
        verdict: str,
        reason: str,
    ) -> None:
        """Emit structured alert for rejected signals (monitoring/analysis)."""
        await self.storage.publish(
            "alerts:rejections",
            {
                "type": "SIGNAL_REJECTED",
                "signal_id": signal_id,
                "symbol": symbol,
                "verdict": verdict,
                "reason": reason,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
