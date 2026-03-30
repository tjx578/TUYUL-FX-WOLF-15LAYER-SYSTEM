"""Trade candidate schema — input contract untuk semua agent evaluation."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class Session(str, Enum):
    SYDNEY = "SYDNEY"
    TOKYO = "TOKYO"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    OVERLAP_LDN_NY = "OVERLAP_LDN_NY"
    OVERLAP_TOK_LDN = "OVERLAP_TOK_LDN"


class MarketState(str, Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    CHOPPY = "CHOPPY"
    EXTREME = "EXTREME"
    UNKNOWN = "UNKNOWN"


class FinalVerdict(str, Enum):
    EXECUTE = "EXECUTE"
    SKIP = "SKIP"
    HALT = "HALT"
    WATCHLIST = "WATCHLIST"
    PENDING = "PENDING"


class TradeCandidate(BaseModel):
    """Trade candidate yang akan dievaluasi oleh semua agent."""

    candidate_id: str = Field(..., description="UUID unik untuk candidate ini")
    instrument: str = Field(..., description="Simbol pair, e.g. EURUSD")
    direction: Direction
    session: Session
    entry_price: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profit: float = Field(..., gt=0)
    lot_size: Optional[float] = Field(default=None, ge=0.01)
    timeframe: str = Field(default="H4", description="Timeframe utama analisis")
    htf_bias: str = Field(default="", description="Higher timeframe bias")
    notes: str = Field(default="", description="Catatan analis")
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    raw_context: dict[str, Any] = Field(default_factory=dict, description="Raw market data context")

    model_config = ConfigDict(use_enum_values=True)

    def pip_risk(self) -> float:
        """Hitung pip risk dari entry ke stop loss."""
        return abs(self.entry_price - self.stop_loss) * 10000

    def pip_reward(self) -> float:
        """Hitung pip reward dari entry ke take profit."""
        return abs(self.take_profit - self.entry_price) * 10000

    def rr_ratio(self) -> float:
        """Hitung risk-reward ratio."""
        risk = self.pip_risk()
        if risk == 0:
            return 0.0
        return round(self.pip_reward() / risk, 2)
