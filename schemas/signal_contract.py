from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FROZEN_SIGNAL_CONTRACT_VERSION = "2026-03-03"


@dataclass(frozen=True)
class SignalContract:
    """Frozen signal boundary contract (read-only payload model)."""

    signal_id: str
    symbol: str
    verdict: str
    confidence: float
    timestamp: float
    direction: str | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit_1: float | None = None
    risk_reward_ratio: float | None = None
    scores: dict[str, float] = field(default_factory=dict)
    expires_at: float | None = None
    contract_version: str = FROZEN_SIGNAL_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.direction is not None and self.direction not in ("BUY", "SELL"):
            raise ValueError(f"SignalContract.direction must be 'BUY', 'SELL', or None, got {self.direction!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit_1": self.take_profit_1,
            "risk_reward_ratio": self.risk_reward_ratio,
            "scores": dict(self.scores),
            "timestamp": self.timestamp,
            "expires_at": self.expires_at,
        }
