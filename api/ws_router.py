from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal


@dataclass
class SignalStatus:
    """
    Dashboard-level signal state tracking.

    Conceptual states (UI/governance):
    - WARMUP: Data insufficient for analysis
    - SIGNAL_CREATED: L12 verdict received
    - SIGNAL_EXPIRED: Verdict expired before action
    - PENDING_PLACED: Order submitted to broker
    - TRADE_OPEN: Position live
    - TRADE_CLOSED: Final state
    - TRADE_ABORTED: Constitutional violation
    """

    signal_id: str
    symbol: str
    state: Literal[
        "WARMUP",
        "SIGNAL_CREATED",
        "SIGNAL_EXPIRED",
        "PENDING_PLACED",
        "PENDING_FILLED",
        "PENDING_CANCELLED",
        "TRADE_OPEN",
        "TRADE_CLOSED",
        "TRADE_ABORTED",
    ]
    verdict: str | None  # L12 verdict if available
    confidence: float
    reason: str
    created_at: datetime
    updated_at: datetime
    warmup_details: dict | None = None  # ✅ NEW: Explains what's missing


class SignalStatusTracker:
    """Track signal lifecycle from analysis → execution → closure."""

    def __init__(self, storage):
        self.storage = storage

    async def create_warmup_status(
        self,
        symbol: str,
        missing_tfs: list[str],
        available_tfs: list[str],
    ) -> SignalStatus:
        """
        Create WARMUP status when data is insufficient.

        Dashboard will show: "⏳ Data warming up for EURUSD (missing H4, D1)"
        """
        signal_id = f"warmup_{symbol}_{int(datetime.now(UTC).timestamp())}"

        status = SignalStatus(
            signal_id=signal_id,
            symbol=symbol,
            state="WARMUP",
            verdict=None,
            confidence=0.0,
            reason=f"INSUFFICIENT_DATA: Missing {', '.join(missing_tfs)}",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            warmup_details={
                "missing_timeframes": missing_tfs,
                "available_timeframes": available_tfs,
                "estimated_ready": self._estimate_warmup_completion(missing_tfs),
            },
        )

        await self.storage.set(f"signal_status:{signal_id}", status)
        return status

    def _estimate_warmup_completion(self, missing_tfs: list[str]) -> str:
        """Estimate when warmup will complete based on missing timeframes."""
        # H4 needs ~4 hours, D1 needs ~24 hours, etc.
        max_wait_minutes = {
            "M5": 10,
            "M15": 30,
            "H1": 120,
            "H4": 240,
            "D1": 1440,
        }

        max_wait = max((max_wait_minutes.get(tf, 0) for tf in missing_tfs), default=0)
        estimated_ready = datetime.now(UTC).timestamp() + (max_wait * 60)

        return datetime.fromtimestamp(estimated_ready, UTC).isoformat()

    async def transition_to_signal_created(
        self,
        signal_id: str,
        verdict: str,
        confidence: float,
        reason: str,
    ) -> None:
        """Update status when L12 verdict arrives."""
        status = await self.storage.get(f"signal_status:{signal_id}")

        if status and status.state == "WARMUP":
            status.state = "SIGNAL_CREATED"
            status.verdict = verdict
            status.confidence = confidence
            status.reason = reason
            status.updated_at = datetime.now(UTC)
            status.warmup_details = None  # Clear warmup metadata

            await self.storage.set(f"signal_status:{signal_id}", status)
