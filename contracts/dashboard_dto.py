"""Canonical dashboard DTO contracts shared with frontend typings."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SignalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    verdict: str
    confidence: str | float
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit_1: float | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RiskRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trade_allowed: bool
    recommended_lot: float
    max_safe_lot: float
    reason: str
    expiry: datetime
