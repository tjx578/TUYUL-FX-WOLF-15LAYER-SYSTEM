"""WebSocket event contracts for real-time dashboard channels."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MarketEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["market.tick"]
    symbol: str
    bid: float
    ask: float
    ts: datetime = Field(default_factory=datetime.utcnow)


class SignalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["signal.update"]
    symbol: str
    verdict: str
    confidence: float
    ts: datetime = Field(default_factory=datetime.utcnow)


class RiskEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["risk.state"]
    trade_allowed: bool
    code: str
    ts: datetime = Field(default_factory=datetime.utcnow)
